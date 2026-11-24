import asyncio,unittest
from unittest.mock import patch
from isolation import Isolation,FRAME

def frame(i):return i.to_bytes(2,'little')*960
class Recovery(unittest.IsolatedAsyncioTestCase):
 def setUp(self):
  self.events=[];self.f=Isolation('unused',lambda e,**k:self.events.append((e,k)))
  self.f.state='probing';self.f.probe_started=0;self.f.STABLE_FRAMES=3
  self.clock=patch('isolation.time.monotonic',return_value=0);self.now=self.clock.start();self.addCleanup(self.clock.stop)
 def tick(self,t):self.now.return_value=t
 def complete(self,t,data):
  self.tick(t);self.f.inputs.get_nowait();self.f.observe(data)
 def ready(self):
  for i in range(3):
   self.tick(i*.02);self.assertEqual(self.f.feed(frame(i)),[frame(i)]);self.complete(i*.02+.01,frame(i))
  self.assertEqual(self.f.state,'armed')
 async def test_real_frame_readiness_and_cutover_no_replay(self):
  self.ready();self.tick(.06);self.assertEqual(self.f.feed(frame(3)),[])
  self.complete(.07,frame(3));self.tick(.25)
  self.assertEqual(self.f.feed(frame(4)),[frame(3)])
  self.assertEqual(self.f.state,'on')
  self.assertEqual(self.f.cutover,3)
 async def test_lag_recovers_without_replaying_forwarded_raw(self):
  self.ready();self.tick(.06);self.f.feed(frame(3))
  self.tick(.37);self.assertEqual(self.f.feed(frame(4)),[frame(3),frame(4)])
  self.assertEqual(self.f.state,'recovering');self.assertEqual(self.f.recoveries,1)
  self.complete(.58,frame(3));self.complete(.58,frame(4))
  for i in range(5,8):
   self.tick(.6+(i-5)*.02);self.assertEqual(self.f.feed(frame(i)),[frame(i)])
   self.complete(.61+(i-5)*.02,frame(i))
  self.assertEqual(self.f.state,'armed');self.tick(.7);self.assertEqual(self.f.feed(frame(8)),[])
  self.complete(.71,frame(8));self.tick(.9);self.assertEqual(self.f.feed(frame(9)),[frame(8)])
  self.assertEqual(self.f.cutover,8)
 async def test_stability_resets_on_slow_frame(self):
  self.tick(0);self.f.feed(frame(0));self.complete(.01,frame(0));self.assertEqual(self.f.streak,1)
  self.tick(.02);self.f.feed(frame(1));self.complete(.25,frame(1));self.assertEqual(self.f.streak,0)
 async def test_retry_limit_and_metadata(self):
  for _ in range(3):
   self.f.episode=False;self.f.recover('latency_budget')
  self.f.episode=False
  self.f.recover('latency_budget');self.assertEqual(self.f.state,'bypass')
  self.assertEqual(self.f.recoveries,3)
  last=self.events[-1][1];self.assertIn('push_ms',last);self.assertIn('frame_ms',last)
 async def test_one_stall_restart_is_one_episode(self):
  self.f.recover('latency_budget');self.tick(.072)
  self.f.recover('input_backlog',restart=True)
  self.assertEqual(self.f.recoveries,1)
  self.assertEqual(self.f.episode_restarts,1)
  self.assertFalse(self.events[-1][1]['new_episode'])
 async def test_budget_expires_for_long_call(self):
  for t in (0,100,200,300,400,500,600):
   self.tick(t);self.f.episode=False;self.f.recover('latency_budget')
   self.assertEqual(self.f.state,'recovering')
  self.assertEqual(self.f.recoveries,7)
  self.assertEqual(len(self.f.recovery_times),3)
 async def test_fourth_distinct_episode_inside_window_stops(self):
  for t in (0,50,100,299.999):
   self.tick(t);self.f.episode=False;self.f.recover('latency_budget')
  self.assertEqual(self.f.reason,'recovery_rate_limit:latency_budget')
 async def test_rearm_closes_episode(self):
  self.f.recover('latency_budget');self.f.state='armed';self.f.feed(frame(0))
  self.assertFalse(self.f.episode)
  self.f.recover('latency_budget');self.assertEqual(self.f.recoveries,2)
 async def test_readiness_timeout_and_off(self):
  self.tick(31);self.assertEqual(self.f.feed(frame(0)),[frame(0)]);self.assertEqual(self.f.reason,'readiness_timeout')
  await self.f.stop();self.assertEqual(self.f.feed(frame(1)),[frame(1)])
 async def test_protocol_overproduction_rejected(self):
  with self.assertRaisesRegex(ValueError,'unsolicited'):self.f.observe(frame(0))
 async def test_partial_output_alignment(self):
  self.tick(0);self.f.feed(frame(0));self.f.inputs.get_nowait()
  self.f.observe(frame(0)[:500]);self.assertEqual(len(self.f.inflight),1)
  self.f.observe(frame(0)[500:]);self.assertEqual(len(self.f.inflight),0);self.assertEqual(self.f.streak,1)
 async def test_bounded_input_backlog(self):
  self.f.desired=True
  for i in range(16):self.assertEqual(self.f.feed(frame(i)),[frame(i)])
  self.assertEqual(self.f.state,'warming');self.assertTrue(self.f.restart_requested)
 async def test_off_drains_unemitted_originals(self):
  self.ready();self.tick(.06);self.f.feed(frame(3));await self.f.stop()
  self.assertEqual(self.f.feed(frame(4)),[frame(3),frame(4)])

class ProcessRecovery(unittest.IsolatedAsyncioTestCase):
 async def test_crash_restart_preserves_each_frame_once(self):
  import sys,tempfile
  from pathlib import Path
  worker="""import sys,struct
print('READY',flush=True)
while True:
 x=sys.stdin.buffer.read(1920)
 if len(x)!=1920:break
 sys.stdout.buffer.write(struct.pack('!I',1920)+x);sys.stdout.buffer.flush()
"""
  with tempfile.TemporaryDirectory() as d:
   f=Isolation(d);f.STABLE_FRAMES=3
   actual=[];killed=False;states=set();first_pid=None
   with patch('isolation.command',return_value=([sys.executable,'-u','-c',worker],Path(d))):
    f.enable()
    try:
     for i in range(90):
      actual.extend(f.feed(frame(i)));states.add(f.state)
      if i==25:
       self.assertEqual(f.state,'on');first_pid=f.proc.pid;f.proc.kill();killed=True
      await asyncio.sleep(.02)
     self.assertTrue(killed);self.assertEqual(f.state,'on');self.assertNotEqual(f.proc.pid,first_pid)
     self.assertEqual(f.recoveries,1)
    finally:await f.stop()
    actual.extend(f.feed(frame(90)))
    self.assertEqual([int.from_bytes(x[:2],'little') for x in actual],list(range(91)))
    self.assertIsNone(f.proc)
 async def test_stop_during_probe_reaps_worker(self):
  import sys,tempfile
  from pathlib import Path
  with tempfile.TemporaryDirectory() as d:
   f=Isolation(d)
   with patch('isolation.command',return_value=([sys.executable,'-u','-c',"import time;print('READY',flush=True);time.sleep(60)"],Path(d))):
    f.enable()
    for _ in range(100):
     if f.state=='probing':break
     await asyncio.sleep(.01)
    self.assertEqual(f.state,'probing');f.feed(frame(0))
    await asyncio.wait_for(f.stop(),2)
    self.assertIsNone(f.proc);self.assertEqual(f.state,'off');self.assertIsNone(f.task)
 async def test_repeated_worker_failure_stops_at_limit(self):
  import sys,tempfile
  from pathlib import Path
  with tempfile.TemporaryDirectory() as d:
   f=Isolation(d)
   with patch('isolation.command',return_value=([sys.executable,'-u','-c',"import sys;print('READY',flush=True);sys.stdin.buffer.read(1920)"],Path(d))):
    f.enable()
    try:
     for i in range(300):
      f.feed(frame(i))
      if f.state=='bypass':break
      await asyncio.sleep(.01)
     self.assertEqual(f.state,'bypass');self.assertEqual(f.recoveries,1)
     self.assertIn('episode_restart_limit',f.reason)
    finally:await f.stop()

if __name__=='__main__':unittest.main()
