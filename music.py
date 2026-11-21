"""Bounded external PCM source for the single active call."""
import asyncio
from urllib.parse import urlsplit

class Radio:
 def __init__(self):
  self.queue=asyncio.Queue(maxsize=25);self.proc=None;self.reader=None;self.enabled=True;self.external=False;self.volume=.08;self.frames=0;self.style=0
 async def stop(self):
  if self.reader:
   self.reader.cancel();await asyncio.gather(self.reader,return_exceptions=True);self.reader=None
  if self.proc:
   if self.proc.returncode is None:
    self.proc.terminate()
    try:await asyncio.wait_for(self.proc.communicate(),2)
    except asyncio.TimeoutError:self.proc.kill();await self.proc.communicate()
   self.proc=None
  while not self.queue.empty():self.queue.get_nowait()
  self.external=False
 async def play(self,url):
  parsed=urlsplit(url)
  if parsed.scheme not in ('http','https') or not parsed.hostname or parsed.username or parsed.password:raise ValueError('Use an HTTP(S) stream URL without credentials')
  await self.stop();self.external=True;self.enabled=True;self.frames=0
  self.proc=await asyncio.create_subprocess_exec('ffmpeg','-nostdin','-v','error','-rw_timeout','10000000','-re','-i',url,'-vn','-f','s16le','-ar','48000','-ac','1','pipe:1',stdout=asyncio.subprocess.PIPE,stderr=asyncio.subprocess.DEVNULL,limit=3840)
  async def read():
   try:
    while True:
     data=await self.proc.stdout.readexactly(1920)
     await self.queue.put(data);self.frames+=1
   except asyncio.IncompleteReadError:pass
  self.reader=asyncio.create_task(read())
 def frame(self):
  try:return self.queue.get_nowait()
  except asyncio.QueueEmpty:return bytes(1920)
 def status(self):return {'enabled':self.enabled,'external':self.external,'buffered_frames':self.queue.qsize(),'decoded_frames':self.frames,'volume':self.volume,'decoder_running':bool(self.proc and self.proc.returncode is None)}
 async def command(self,mode,source=None,volume=None):
  if mode=='play':await self.play(source or '')
  elif mode=='off':await self.stop();self.enabled=False
  elif mode=='on':self.enabled=True
  elif mode=='next':await self.stop();self.enabled=True;self.style=1-self.style
  elif mode=='volume':
   if volume is None or not 0<=volume<=100:raise ValueError('Volume must be 0..100')
   self.volume=volume/100
  return self.status()
