import asyncio,json,os,struct
from test_noise_gate import NoiseGate

class ChimeBridge(NoiseGate):
 async def prepare(self):
  self.m.speech=lambda text,voice:struct.pack('<h',5000)*(960*(1 if text=='Welcome to Shellphone!' else 30))
  await self.connect();await self.audio(0,10)
  self.frames.clear()
 def submit(self,text='hello'):
  self.m.CHIMES.submit('test-session',self.m.CALL_ID,self.m.ROUTER.generation,text)
 async def test_chime_waits_for_silence(self):
  await self.prepare();await self.audio(1500,5);self.frames.clear();self.submit()
  await self.audio(1500,8)
  self.assertTrue(all(x==0 for x in self.frames),'chime spoke over microphone activity')
  await self.audio(0,20)
  self.assertTrue(any(x==5000 for x in self.frames),'chime did not resume')
 async def test_recognized_words_cancel_chime(self):
  await self.prepare();self.submit();await self.audio(0,5)
  self.m.transcribe=lambda pcm:'new question'
  await self.audio(1500,25);await self.audio(0,65);await asyncio.sleep(.1)
  self.assertTrue(self.sent)
  self.assertTrue(self.m.CHIMES.queue.empty())
  self.assertTrue(self.m.CHIMES.task is None or self.m.CHIMES.task.done())
 async def test_switch_cancels_old_chime(self):
  await self.prepare();await self.audio(1500,5);self.submit()
  self.m.ROUTER.add('other','other-session','alba');self.m.ROUTER.switch('other')
  await self.audio(0,25)
  self.assertFalse(any(x==5000 for x in self.frames))
 async def test_control_say_and_no_call(self):
  server=await asyncio.start_server(self.m.control,'127.0.0.1',0)
  async def request(req):
   r,w=await asyncio.open_connection('127.0.0.1',server.sockets[0].getsockname()[1])
   w.write(json.dumps(req).encode()+b'\n');await w.drain();result=json.loads(await r.readline());w.close();await w.wait_closed();return result
  try:
   self.assertIn('error',await request({'action':'say','text':'hello'}))
   await self.prepare()
   req={'action':'say','session':'wrong','text':'hello','generation':0,'call_id':self.m.CALL_ID}
   self.assertIn('error',await request(req));req['session']='test-session'
   self.assertNotIn('error',await request(req));await self.audio(0,10)
   self.assertTrue(any(x==5000 for x in self.frames))
   self.assertIn('error',await request({'action':'isolation','name':'on'}))
  finally:server.close();await server.wait_closed()
 async def test_cli_uses_session_and_call_snapshot(self):
  import subprocess,sys
  from pathlib import Path
  await self.prepare()
  path=self.m.control_path(self.m.P);ctl=await asyncio.start_unix_server(self.m.control,str(path))
  async def command(session):
   return await asyncio.to_thread(subprocess.run,[sys.executable,str(Path(__file__).with_name('voice.py')),'--profile',str(self.m.P),'say'],input='an update',capture_output=True,text=True,timeout=5,env={**os.environ,'WOLTSPACE_WOLT_SESSION':session})
  try:
   bad=await command('wrong');self.assertNotEqual(bad.returncode,0)
   good=await command('test-session');self.assertEqual(good.returncode,0,good.stderr)
   await self.audio(0,10);self.assertTrue(any(x==5000 for x in self.frames))
  finally:ctl.close();await ctl.wait_closed();path.unlink(missing_ok=True)
