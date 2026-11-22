"""Explicit per-call private input recording. No network, transcripts or outgoing mix.
Bounded queue; disk work is on a thread. Stop finalizes a valid WAV header.
"""
import asyncio,json,os,queue,shutil,threading,time,uuid,wave
from pathlib import Path

class Recording:
 MAX_BYTES=48000*2*600  # ten minutes, roughly55MiB of raw PCM
 MIN_FREE=1024**3
 def __init__(self,profile):
  self.root=Path(profile)/'recordings';self.state='off';self.reason=None;self.samples=0
  self.queue=queue.Queue(maxsize=256);self.done=threading.Event();self.worker=None;self.preparing_task=None
  self.written_samples=0;self.started=0;self.path=None;self.files=None;self.last_space_check=0
 def status(self):return {'state':self.state,'reason':self.reason,'samples':self.samples,'seconds':round(self.samples/48000,2)}
 def prepare(self):
  if self.root.is_symlink():raise ValueError('Recording folder must not be a symlink')
  self.root.mkdir(mode=0o700,parents=False,exist_ok=True);self.root.chmod(0o700)
  if shutil.disk_usage(self.root).free<self.MIN_FREE:raise ValueError('Not enough free disk for recording')
  folder=self.root/uuid.uuid4().hex;folder.mkdir(mode=0o700)
  raw=None;events=None
  try:
   raw=os.fdopen(os.open(folder/'caller.wav',os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600),'wb')
   events=os.fdopen(os.open(folder/'events.jsonl',os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600),'w')
   wav=wave.open(raw,'wb');wav.setnchannels(1);wav.setsampwidth(2);wav.setframerate(48000)
   return folder,raw,events,wav
  except BaseException:
   if raw:raw.close()
   if events:events.close()
   raise
 async def start(self):
  if self.state=='on':return
  if self.preparing_task and not self.preparing_task.done():raise ValueError('Previous recording preparation is still stopping')
  if self.worker:
   await self.stop()
   if self.worker:raise ValueError('Previous recording writer is still stopping')
  task=asyncio.create_task(asyncio.to_thread(self.prepare));self.preparing_task=task
  try:prepared=await asyncio.shield(task)
  except asyncio.CancelledError:
   def close_late(done):
    try:
     _,raw,events,wav=done.result()
     def close():
      try:wav.close()
      finally:raw.close();events.close()
     asyncio.create_task(asyncio.to_thread(close))
    except Exception:pass
   task.add_done_callback(close_late)
   self.state='off';raise
  self.path,raw,events,wav=prepared;self.files=(raw,events,wav)
  self.samples=0;self.written_samples=0;self.reason=None;self.started=time.monotonic();self.last_space_check=self.started
  self.queue=queue.Queue(maxsize=256);self.done=threading.Event();self.state='on'
  self.worker=threading.Thread(target=self.write,daemon=True);self.worker.start()
  self.event('record_start',format='s16le',sample_rate=48000,channels=1)
 def enqueue(self,item):
  try:self.queue.put_nowait(item)
  except queue.Full:self.fail('disk_queue_full')
 def feed(self,pcm):
  if self.state!='on':return
  if self.samples*2+len(pcm)>self.MAX_BYTES:self.fail('duration_limit');return
  self.samples+=len(pcm)//2;self.enqueue(('pcm',pcm))
 def event(self,event,**fields):
  if self.state!='on':return
  # Callers supply metadata only; never text/audio/provider responses.
  item={'event':event,'elapsed':round(time.monotonic()-self.started,6),'raw_samples_received':self.samples,**fields}
  self.enqueue(('event',item))
 def fail(self,reason):
  self.reason=reason;self.state='off';self.done.set()
 def write(self):
  raw,events,wav=self.files
  try:
   while not self.done.is_set() or not self.queue.empty():
    try:kind,value=self.queue.get(timeout=.1)
    except queue.Empty:continue
    try:
     if kind=='pcm':wav.writeframesraw(value);self.written_samples+=len(value)//2
     else:events.write(json.dumps(value)+'\n')
     if time.monotonic()-self.last_space_check>1:
      self.last_space_check=time.monotonic()
      if shutil.disk_usage(self.root).free<self.MIN_FREE:self.fail('disk_space_low')
    finally:self.queue.task_done()
   events.write(json.dumps({'event':'record_stop','elapsed':round(time.monotonic()-self.started,6),'raw_samples_received':self.samples,'reason':self.reason,'written_samples':self.written_samples})+'\n')
  except (OSError,ValueError) as e:self.fail(type(e).__name__)
  finally:
   try:wav.close()
   except (OSError,ValueError):pass
   raw.close();events.close()
   if self.state=='stopping':self.state='off'
 async def stop(self):
  self.state='off';self.done.set()
  if self.worker:
   await asyncio.to_thread(self.worker.join,2)
   if self.worker.is_alive():self.state='stopping';self.reason='writer_stopping'
   else:self.worker=None
