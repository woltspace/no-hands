"""Synthetic audio/ASR only. Run in a disposable container, never a live profile."""
import asyncio
import importlib.util
import json
import os
from pathlib import Path
import struct
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch
import setup


class NoiseGate(unittest.IsolatedAsyncioTestCase):
 async def asyncSetUp(self):
  self.tmp=tempfile.TemporaryDirectory()
  self.addCleanup(self.tmp.cleanup)
  self.root_patch=patch.object(setup,'ROOT',Path(self.tmp.name));self.root_patch.start();self.addCleanup(self.root_patch.stop)
  profile=setup.initialize('test','100.64.0.1','100.64.0.2','test-session')
  settings=json.loads((profile/'profile.json').read_text())
  settings['detector']=os.environ.get('TEST_DETECTOR','webrtcvad')
  (profile/'profile.json').write_text(json.dumps(settings))
  self.env=patch.dict(os.environ,VOICE_PROFILE=str(profile));self.env.start();self.addCleanup(self.env.stop)
  spec=importlib.util.spec_from_file_location('bridge_fixture',Path(__file__).with_name('bridge.py'))
  self.m=importlib.util.module_from_spec(spec);spec.loader.exec_module(self.m)
  class Vad:
   def __init__(self,mode):pass
   def is_speech(self,data,rate):return max(struct.unpack('<960h',data))>600
  self.vad_patch=patch.object(self.m.webrtcvad,'Vad',Vad);self.vad_patch.start();self.addCleanup(self.vad_patch.stop)
  self.gate=threading.Event();self.gate.set()
  def speech(*args):
   assert self.gate.wait(5)
   return struct.pack('<h',5000)*(self.m.RATE*15)
  self.m.speech=speech
  self.m.transcribe=lambda pcm:'uh, uh'
  self.sent=[]
  original=asyncio.create_subprocess_exec
  async def spawn(*args,**kwargs):
   if args[0]!='woltspace':return await original(*args,**kwargs)
   sent=self.sent
   class Process:
    returncode=0
    async def communicate(self,prompt):sent.append(prompt.decode());return b'',b''
   return Process()
  self.spawn_patch=patch.object(asyncio,'create_subprocess_exec',spawn);self.spawn_patch.start();self.addCleanup(self.spawn_patch.stop)
  self.server=await asyncio.start_server(self.m.client,'127.0.0.1',0)
  self.frames=[];self.writer=None;self.reader_task=None

 async def connect(self,token=None):
  reader,self.writer=await asyncio.open_connection('127.0.0.1',self.server.sockets[0].getsockname()[1])
  self.writer.write(b'\x01\x00\x10'+(token or self.m.TOKEN));await self.writer.drain()
  async def receive():
   try:
    while True:
     kind,n=struct.unpack('!BH',await reader.readexactly(3))
     pcm=await reader.readexactly(n)
     self.frames.append(max(struct.unpack('<960h',pcm)))
   except asyncio.IncompleteReadError:pass
  self.reader_task=asyncio.create_task(receive())
  for _ in range(100):
   if self.m.RADIO is not None:break
   await asyncio.sleep(.01)
  self.m.RADIO.enabled=False

 async def audio(self,level,count):
  data=b'\x16\x07\x80'+struct.pack('<h',level)*960
  for _ in range(count):
   self.writer.write(data);await self.writer.drain();await asyncio.sleep(.02)

 async def asyncTearDown(self):
  self.gate.set()
  if self.writer:
   self.writer.close();await self.writer.wait_closed()
  if self.reader_task:await asyncio.wait_for(self.reader_task,3)
  self.server.close();await self.server.wait_closed()
  for _ in range(100):
   if not self.m.busy:break
   await asyncio.sleep(.01)

 async def test_filler_only_preserves_playback(self):
  await self.connect();await asyncio.sleep(.1)
  await self.audio(1500,25);await self.audio(0,65);await asyncio.sleep(.15)
  self.assertFalse(self.sent,'filler-only ASR must not supersede the reply')
  self.assertGreater(min(self.frames[-5:]),4000,'reply audio must survive filler-only ASR')

 async def test_brief_vad_blip_does_not_delay_reply_start(self):
  self.gate.clear();await self.connect()
  await self.audio(1500,1)
  self.gate.set()
  await self.audio(0,15)
  self.assertGreater(max(self.frames[-10:]),4000,'20 ms blip must not hold a ready reply for the endpoint silence window')

 async def test_duck_releases_before_utterance_endpoint(self):
  await self.connect();await asyncio.sleep(.1)
  await self.audio(1500,25)
  self.assertTrue(any(0<x<=1000 for x in self.frames[-5:]),'sustained speech still ducks audio')
  await self.audio(0,15)
  self.assertGreater(min(self.frames[-3:]),4000,'duck must release during the longer ASR endpoint wait')
  await self.audio(1500,1);await self.audio(0,3)
  self.assertGreater(min(self.frames[-3:]),4000,'a new blip must not reuse the old duck threshold')

 async def test_only_hesitation_only_text_is_noise(self):
  for text in ('', '  ', '...', 'uh, uh', 'Umm... er, um', 'uhh'):
   self.assertFalse(self.m.has_words(text),text)
  for text in ('yes', 'no', 'stop', 'hmm', 'uh-huh', 'uh, please continue', '42', 'oui', 'non'):
   self.assertTrue(self.m.has_words(text),text)

 async def test_words_with_fillers_still_reach_wolt(self):
  self.m.transcribe=lambda pcm:'uh, please continue'
  await self.connect();await asyncio.sleep(.1)
  await self.audio(1500,25);await self.audio(0,65);await asyncio.sleep(.15)
  self.assertEqual(len(self.sent),1)
  self.assertIn('\nuh, please continue\n',self.sent[0])

 async def test_normal_extension_selects_rms(self):
  from call_modes import mode_token
  await self.connect(mode_token(self.m.uuid.UUID(bytes=self.m.TOKEN),'normal').bytes)
  self.assertEqual(self.m.MODE_CONTROL()['detector'],'rms')

 async def test_car_extension_selects_webrtc(self):
  from call_modes import mode_token
  await self.connect(mode_token(self.m.uuid.UUID(bytes=self.m.TOKEN),'car').bytes)
  self.assertEqual(self.m.MODE_CONTROL()['detector'],'webrtcvad')

 async def test_live_mode_cli_preserves_reply_route_music_and_playback(self):
  await self.connect();await asyncio.sleep(.1)
  path=self.m.control_path(self.m.P)
  ctl=await asyncio.start_unix_server(self.m.control,str(path))
  before=self.m.ROUTER.status()
  pending=asyncio.get_running_loop().create_future();self.m.ROUTER.pending['pending']=pending
  async def command(name):
   result=await asyncio.to_thread(subprocess.run,[sys.executable,str(Path(__file__).with_name('voice.py')),
                  '--profile',str(self.m.P),'mode',name],capture_output=True,text=True,timeout=5)
   self.assertEqual(result.returncode,0,result.stderr)
   return json.loads(result.stdout)
  try:
   for name in ('normal','car','car'):
    out=await command(name)
    self.assertEqual(out['call_mode']['name'],name)
    self.assertTrue(out['active_call'])
    self.assertEqual(self.m.ROUTER.status(),before)
    self.assertIs(self.m.ROUTER.pending['pending'],pending)
    self.assertFalse(pending.done())
    self.assertFalse(self.m.RADIO.enabled)
   await asyncio.sleep(.1)
   self.assertGreater(min(self.frames[-3:]),4000,'mode change must preserve queued speech')
   from voice import call
   await asyncio.to_thread(call,self.m.P,{'action':'reply','turn':'pending','text':'still accepted'})
   self.assertEqual(pending.result(),'still accepted')
   with self.assertRaises(RuntimeError):
    await asyncio.to_thread(call,self.m.P,{'action':'mode','name':'unknown'})
   self.assertEqual(self.m.MODE_CONTROL()['name'],'car')
  finally:
   ctl.close();await ctl.wait_closed();path.unlink(missing_ok=True)

 async def test_no_call_mode_change_is_refused(self):
  from voice import call
  path=self.m.control_path(self.m.P)
  ctl=await asyncio.start_unix_server(self.m.control,str(path))
  try:
   with self.assertRaisesRegex(RuntimeError,'No active call'):
    await asyncio.to_thread(call,self.m.P,{'action':'mode','name':'car'})
  finally:
   ctl.close();await ctl.wait_closed();path.unlink(missing_ok=True)

if __name__=='__main__':unittest.main()
