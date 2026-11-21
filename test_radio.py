import asyncio
from music import Radio
async def test():
 r=Radio()
 try:
  await r.play('https://radio.cliamp.stream/lofi/stream')
  for _ in range(200):
   if r.queue.qsize()>=3:break
   await asyncio.sleep(.1)
  assert r.queue.qsize()>=3,r.status()
  assert len(r.frame())==1920
  await asyncio.sleep(1);assert r.queue.qsize()<=25
  proc=r.proc
  await asyncio.wait_for(r.command('off'),5)
  assert proc.returncode is not None and r.queue.empty() and not r.enabled
  print('PASS live radio decode, bounded buffer, off terminates decoder',flush=True)
 finally:await r.stop()
asyncio.run(test())
