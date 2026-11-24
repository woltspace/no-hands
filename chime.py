"""Bounded unsolicited speech for the currently routed session.
Same-user local processes remain trusted; session IDs are routing fences, not credentials.
"""
import asyncio

class Chimes:
 def __init__(self,router,call_id,speak,emit):
  self.router=router;self.call_id=call_id;self.speak=speak;self.emit=emit
  self.queue=asyncio.Queue(maxsize=3);self.task=None;self.closed=False
 def submit(self,session,call_id,generation,text):
  state=self.router.status()
  if self.closed:raise ValueError('No active call')
  if session!=state['session'] or not session:raise ValueError('Only the routed session may chime in')
  if call_id!=self.call_id or generation!=state['generation']:raise ValueError('Call or route changed; get status again')
  if not isinstance(text,str) or not text.strip() or len(text)>600:raise ValueError('Chime text must be 1..600 characters')
  try:self.queue.put_nowait((generation,state['voice'],text))
  except asyncio.QueueFull:raise ValueError('Chime queue is full')
  if not self.task or self.task.done():self.task=asyncio.create_task(self.run())
  self.emit('chime_queued',generation=generation)
 async def run(self):
  while not self.queue.empty():
   generation,voice,text=self.queue.get_nowait()
   try:
    if generation==self.router.generation:
     await self.speak(text,voice,generation)
   finally:self.queue.task_done()
 async def cancel(self):
  if self.task:self.task.cancel();await asyncio.gather(self.task,return_exceptions=True)
  self.task=None
  while not self.queue.empty():self.queue.get_nowait();self.queue.task_done()
 async def close(self):
  self.closed=True;await self.cancel()
