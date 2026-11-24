import asyncio,re,struct
from test_noise_gate import NoiseGate

class Handoff(NoiseGate):
 async def prepare(self):
  self.original=self.m.ROUTER.selected
  self.spoken=[]
  def speech(text,voice):
   self.spoken.append((text,voice));return struct.pack('<h',5000)*960
  self.m.speech=speech
  await self.connect();await self.audio(0,12)
  self.m.ROUTER.add('other','other-session','cosette')
  self.spoken.clear();self.frames.clear()
 async def until_sent(self):
  for _ in range(100):
   if self.sent:return
   await self.audio(0,1)
  self.fail('No greeting request delivered')
 async def test_sequence_waits_for_target_reply(self):
  await self.prepare();await self.m.SWITCH_CONTROL('other','Handing you over now.')
  await self.until_sent()
  self.assertEqual(self.spoken,[('Handing you over now.','alba'),('Switching to other.',self.m.SYSTEM_VOICE)])
  self.assertEqual(self.m.ROUTER.selected,'other')
  self.assertIn('Introduce yourself in one short sentence',self.sent[-1])
  self.assertNotIn('Switched to other.',[t for t,v in self.spoken])
  ident=next(iter(self.m.ROUTER.pending));self.m.ROUTER.reply(ident,'Hello, I am Other.')
  await self.audio(0,60)
  self.assertEqual([t for t,v in self.spoken],['Handing you over now.','Switching to other.','Switched to other.','Hello, I am Other.'])
  self.assertEqual([v for t,v in self.spoken],['alba',self.m.SYSTEM_VOICE,self.m.SYSTEM_VOICE,'cosette'])
  self.assertFalse(self.m.ROUTER.pending)
 async def test_timeout_never_claims_connected(self):
  await self.prepare();self.m.SYSTEM_VOICE='custom-line';self.m.HANDOFF_WAIT_SECONDS=.5
  await self.m.SWITCH_CONTROL('other');await self.until_sent();await self.audio(0,60)
  self.assertFalse(any(t=='Switched to other.' for t,v in self.spoken))
  self.assertTrue(any('not answered yet' in t for t,v in self.spoken));self.assertFalse(self.m.ROUTER.pending)
  self.assertTrue(all(v=='custom-line' for t,v in self.spoken))
 async def test_second_switch_fences_late_greeting(self):
  await self.prepare();await self.m.SWITCH_CONTROL('other');await self.until_sent()
  ident=next(iter(self.m.ROUTER.pending))
  await self.m.SWITCH_CONTROL(self.original)
  with self.assertRaises(ValueError):self.m.ROUTER.reply(ident,'stale')
  await self.audio(0,30)
  self.assertEqual(self.m.ROUTER.selected,self.original)
  self.assertFalse(any(t=='Switched to other.' or t=='stale' for t,v in self.spoken))
 async def test_invalid_target_preserves_route(self):
  await self.prepare()
  with self.assertRaises(ValueError):await self.m.SWITCH_CONTROL('missing')
  self.assertEqual(self.m.ROUTER.selected,self.original);self.assertEqual(self.spoken,[])
 async def test_hangup_clears_greeting(self):
  await self.prepare();await self.m.SWITCH_CONTROL('other');await self.until_sent()
  self.writer.close();await self.writer.wait_closed();self.writer=None
  await asyncio.sleep(.2)
  self.assertFalse(self.m.ROUTER.pending);self.assertIsNone(self.m.SWITCH_CONTROL)

 async def test_welcome_and_recording_use_line_voice(self):
  self.m.SYSTEM_VOICE='custom-line'
  spoken=[]
  def speech(text,voice):
   spoken.append((text,voice));return struct.pack('<h',5000)*960
  self.m.speech=speech
  await self.connect();await self.audio(0,12)
  self.assertIn(('Welcome to Shellphone!','custom-line'),spoken)
  await self.m.RECORD_CONTROL('on');await self.audio(0,20)
  self.assertTrue(any('Recording your microphone' in t and v=='custom-line' for t,v in spoken))
  await self.m.RECORD_CONTROL('off')
