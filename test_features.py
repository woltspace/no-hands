import asyncio,unittest
from chime import Chimes

class ChimeTests(unittest.IsolatedAsyncioTestCase):
 async def asyncSetUp(self):
  self.router=type('Router',(),{'generation':0,'status':lambda r:{'session':'session-a','generation':r.generation,'voice':'alba'}})()
  self.spoken=[];self.gate=asyncio.Event()
  async def speak(text,voice,generation):
   await self.gate.wait();self.spoken.append(text)
  self.c=Chimes(self.router,'call',speak,lambda *a,**kw:None)
 async def asyncTearDown(self):await self.c.close()
 def submit(self,text='hello',**kwargs):
  a=dict(session='session-a',call_id='call',generation=0,text=text);a.update(kwargs);self.c.submit(**a)
 async def test_session_call_generation_fences(self):
  for bad in [{'session':'other'},{'call_id':'old'},{'generation':1},{'text':''},{'text':'a'*601}]:
   with self.assertRaises(ValueError):self.submit(**bad)
 async def test_queue_bound_and_order(self):
  for text in ['one','two','three']:self.submit(text)
  with self.assertRaises(ValueError):self.submit('four')
  self.gate.set();await self.c.task;self.assertEqual(self.spoken,['one','two','three'])
 async def test_cancel_discards_active_and_queued(self):
  self.submit();await asyncio.sleep(0);self.submit('later');await self.c.cancel()
  self.gate.set();await asyncio.sleep(0);self.assertEqual(self.spoken,[])
 async def test_route_switch_and_closed(self):
  self.submit();self.router.generation=1;self.gate.set();await self.c.task
  self.assertEqual(self.spoken,[]);await self.c.close()
  with self.assertRaises(ValueError):self.submit(generation=1)

if __name__=='__main__':unittest.main()
