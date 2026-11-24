import asyncio,json,os,stat,tempfile,unittest,wave
from pathlib import Path
from unittest.mock import patch
from recording import Recording
from test_noise_gate import NoiseGate
class Storage(unittest.IsolatedAsyncioTestCase):
 async def test_private_raw_wav_and_sidecar(self):
  with tempfile.TemporaryDirectory() as d:
   r=Recording(d);await r.start();pcm=b'\x12\x34'*960
   r.feed(pcm);r.event('vad',positive=True);await r.stop()
   with wave.open(str(r.path/'caller.wav')) as w:
    self.assertEqual(w.getframerate(),48000);self.assertEqual(w.readframes(960),pcm)
   for p,mode in [(r.root,0o700),(r.path,0o700),(r.path/'caller.wav',0o600),(r.path/'events.jsonl',0o600)]:self.assertEqual(stat.S_IMODE(p.stat().st_mode),mode)
   rows=[json.loads(x) for x in (r.path/'events.jsonl').read_text().splitlines()]
   self.assertEqual(rows[-1]['written_samples'],960);self.assertTrue(any(x['event']=='vad' for x in rows))
 async def test_off_and_duration_cap(self):
  with tempfile.TemporaryDirectory() as d:
   r=Recording(d);r.feed(bytes(1920));self.assertFalse(r.root.exists())
   r.MAX_BYTES=1920;await r.start();r.feed(bytes(1920));r.feed(bytes(1920));await r.stop()
   self.assertEqual(r.reason,'duration_limit')
   with wave.open(str(r.path/'caller.wav')) as w:self.assertEqual(w.getnframes(),960)
 async def test_low_disk_and_symlink_refused(self):
  with tempfile.TemporaryDirectory() as d:
   r=Recording(d)
   with patch('recording.shutil.disk_usage',return_value=type('Usage',(),{'free':0})()):
    with self.assertRaises(ValueError):await r.start()
   r.root.rmdir();r.root.symlink_to('/tmp',target_is_directory=True)
   with self.assertRaises(ValueError):await r.start()
class RecordBridge(NoiseGate):
 async def prepare(self):
  self.m.speech=lambda text,voice:bytes(1920) if text=='Welcome to Shellphone!' else b'\x88\x13'*960*10
  await self.connect();await self.audio(0,10)
 async def test_announcement_before_recording_and_raw_only(self):
  await self.prepare();self.gate.clear()
  import threading
  def speech(text,voice):
   self.gate.wait(5);return b'\x88\x13'*960*10
  self.m.speech=speech
  await self.m.RECORD_CONTROL('on');await self.audio(1500,5)
  self.assertEqual(self.m.RECORDING.state,'arming');self.assertEqual(self.m.RECORDING.samples,0)
  self.gate.set();await self.audio(0,30)
  self.assertEqual(self.m.RECORDING.state,'on')
  rec=self.m.RECORDING;before=rec.samples;await self.audio(1234,5);await self.m.RECORD_CONTROL('off')
  with wave.open(str(rec.path/'caller.wav')) as w:
   w.setpos(before);self.assertEqual(w.readframes(5*960),b'\xd2\x04'*(5*960))
  self.assertEqual(rec.state,'off')
 async def test_off_during_notice_prevents_recording(self):
  await self.prepare();await self.audio(1500,5);await self.m.RECORD_CONTROL('on')
  await asyncio.sleep(.05);await self.m.RECORD_CONTROL('off');await self.audio(0,20)
  self.assertEqual(self.m.RECORDING.state,'off');self.assertFalse(self.m.RECORDING.root.exists())
 async def test_rejected_second_connection_does_not_clear_controls(self):
  await self.prepare();control=self.m.RECORD_CONTROL
  r,w=await asyncio.open_connection('127.0.0.1',self.server.sockets[0].getsockname()[1]);w.write(b'\x01\x00\x10'+self.m.TOKEN);await w.drain();await r.read();w.close();await w.wait_closed()
  self.assertIs(self.m.RECORD_CONTROL,control)

class PreparationCancellation(unittest.IsolatedAsyncioTestCase):
 async def test_cancel_does_not_wait_for_blocked_disk_prepare(self):
  import threading
  with tempfile.TemporaryDirectory() as d:
   rec=Recording(d);real=rec.prepare;entered=threading.Event();release=threading.Event()
   def slow():entered.set();release.wait(5);return real()
   with patch.object(rec,'prepare',slow):
    task=asyncio.create_task(rec.start())
    for _ in range(100):
     if entered.is_set():break
     await asyncio.sleep(.005)
    task.cancel()
    with self.assertRaises(asyncio.CancelledError):await asyncio.wait_for(task,.2)
    with self.assertRaisesRegex(ValueError,'preparation'):await rec.start()
    release.set();await rec.preparing_task;await asyncio.sleep(.1)
    self.assertEqual(rec.state,'off');self.assertIsNone(rec.worker)

class RecordCLI(NoiseGate):
 async def test_only_current_session_can_start_and_operator_can_stop(self):
  import subprocess,sys
  from pathlib import Path
  self.m.speech=lambda text,voice:b'\x88\x13'*960*2
  path=self.m.control_path(self.m.P);ctl=await asyncio.start_unix_server(self.m.control,str(path))
  async def cli(name,session=''):
   return await asyncio.to_thread(subprocess.run,[sys.executable,str(Path(__file__).with_name('voice.py')),'--profile',str(self.m.P),'record',name],capture_output=True,text=True,timeout=5,env={**os.environ,'WOLTSPACE_WOLT_SESSION':session})
  try:
   self.assertNotEqual((await cli('on','test-session')).returncode,0)
   await self.connect();await self.audio(0,10)
   self.assertNotEqual((await cli('on','other')).returncode,0)
   good=await cli('on','test-session');self.assertEqual(good.returncode,0,good.stderr)
   await self.audio(0,20);self.assertEqual(self.m.RECORDING.state,'on')
   stopped=await cli('off');self.assertEqual(stopped.returncode,0,stopped.stderr);self.assertEqual(self.m.RECORDING.state,'off')
  finally:ctl.close();await ctl.wait_closed();path.unlink(missing_ok=True)


class DefaultIsolation(NoiseGate):
 async def test_configured_auto_start_keeps_recording_off(self):
  from isolation import Isolation
  self.m.SETTINGS['isolation_default']=True
  calls=[]
  def enable(iso):calls.append(iso);iso.state='warming'
  with patch.object(Isolation,'enable',enable):
   await self.connect()
   self.assertEqual(len(calls),1);self.assertEqual(self.m.ISOLATION.state,'warming')
   self.assertEqual(self.m.RECORDING.state,'off');self.assertFalse(self.m.RECORDING.root.exists())
 async def test_auto_start_failure_keeps_call_alive(self):
  self.m.SETTINGS['isolation_default']=True;self.m.SETTINGS.pop('isolator_folder',None)
  await self.connect();await self.audio(0,5)
  self.assertTrue(self.m.busy);self.assertEqual(self.m.ISOLATION.state,'bypass')
  self.assertEqual(self.m.RECORDING.state,'off')
