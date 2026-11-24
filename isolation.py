"""Opt-in sandboxed MLX pipe worker. The bridge never imports model code.

All buffered samples retain their original ordering. Readiness and recovery are measured on arriving audio; retries are bounded.
No stale output crosses a worker restart or raw/filtered cutover.
"""
import asyncio,hashlib,os,struct,sys,time
from collections import deque
from pathlib import Path

MODEL_SHA='76598f05523c0669e76562a8b2f31c9d395fca316e80c907ee11775e7497ae0f'
FRAME=1920

def command(folder):
 if sys.platform!='darwin':raise ValueError('MLX isolation requires macOS')
 root=Path(folder).resolve(strict=True)
 binary=root/'voice-isolate-worker';model=root/'denoiser_realtime.safetensors'
 if not binary.is_file() or not model.is_file():raise ValueError('Isolator worker/model not prepared')
 if model.is_symlink() or binary.is_symlink():raise ValueError('Worker/model must be inside isolator folder')
 with model.open('rb') as f:
  if hashlib.file_digest(f,'sha256').hexdigest()!=MODEL_SHA:raise ValueError('Isolator model checksum mismatch')
 return ['/usr/bin/sandbox-exec','-D',f'TRIAL={root}','-D',f'HOME={Path.home()}',
         '-f',str(Path(__file__).parent/'isolator'/'worker.sb'),str(binary),str(model)],root

class Isolation:
 STABLE_FRAMES=100
 READY_BUDGET=.18
 LATENCY_BUDGET=.3
 MAX_RECOVERIES=3
 RECOVERY_WINDOW=300
 MAX_EPISODE_RESTARTS=3
 PROBE_TIMEOUT=30
 def __init__(self,folder=None,emit=None):
  self.folder=folder;self.emit=emit or (lambda *a,**k:None)
  self.state='off';self.reason=None;self.task=None;self.worker_task=None;self.proc=None
  self.pending=deque();self.clean={};self.inputs=asyncio.Queue(maxsize=15)
  self.inflight=deque();self.output=bytearray();self.sequence=0;self.cutover=0
  self.streak=0;self.recoveries=0;self.desired=False;self.restart_requested=False
  self.episode=False;self.episode_restarts=0;self.recovery_times=deque()
  self.service_ms=deque(maxlen=250);self.frame_ms=deque(maxlen=250)
  self.probe_started=None;self.last_stats=0;self.push_started=None
 def status(self):return {'state':self.state,'reason':self.reason,'buffer_ms':len(self.pending)*20,'recoveries':self.recoveries,'stable_frames':self.streak}
 def stats(self):
  def summary(values):
   if not values:return {'count':0}
   s=sorted(values)
   return {'count':len(s),'p50':round(s[len(s)//2],2),'p95':round(s[min(len(s)-1,int(len(s)*.95))],2),'max':round(s[-1],2)}
  return {'push_ms':summary(self.service_ms),'frame_ms':summary(self.frame_ms),'pending_frames':len(self.pending),'worker_backlog':len(self.inflight),'recoveries':self.recoveries,'oldest_inflight_ms':round((time.monotonic()-self.inflight[0][1])*1000,2) if self.inflight else 0,'in_progress_ms':round((time.monotonic()-self.push_started)*1000,2) if self.push_started is not None else 0}
 def enable(self):
  if not self.folder:raise ValueError('No isolator folder configured')
  if self.task and not self.task.done():return
  if self.pending:raise ValueError('Wait for buffered audio to drain before enabling')
  self.desired=True;self.state='warming';self.reason=None
  self.emit('isolation_warming',recoveries=self.recoveries)
  self.task=asyncio.create_task(self.run())
 def _raw(self,data=None):
  originals=[pcm for _,_,pcm in self.pending];self.pending.clear();self.clean.clear()
  return originals+([data] if data is not None else [])
 def fail(self,reason):
  self.emit('isolation_bypass',reason=reason,**self.stats())
  self.state='bypass';self.reason=reason;self.desired=False;self.clean.clear();self.streak=0
  if self.worker_task and self.worker_task is not asyncio.current_task():self.worker_task.cancel()
 def recover(self,reason,restart=False):
  now=time.monotonic()
  while self.recovery_times and now-self.recovery_times[0]>=self.RECOVERY_WINDOW:
   self.recovery_times.popleft()
  new_episode=not self.episode
  if new_episode:
   if len(self.recovery_times)>=self.MAX_RECOVERIES:
    self.fail('recovery_rate_limit:'+reason);return
   self.recovery_times.append(now);self.recoveries+=1
   self.episode=True;self.episode_restarts=0
  if restart:
   if self.episode_restarts>=self.MAX_EPISODE_RESTARTS:
    self.fail('episode_restart_limit:'+reason);return
   self.episode_restarts+=1
  self.streak=0;self.clean.clear();self.reason=reason
  self.emit('isolation_recovering',reason=reason,restart=restart,
   new_episode=new_episode,episode_restarts=self.episode_restarts,
   recoveries_in_window=len(self.recovery_times),**self.stats())
  self.state='warming' if restart else 'recovering';self.probe_started=now
  if restart:
   self.restart_requested=True
   if self.worker_task and self.worker_task is not asyncio.current_task():self.worker_task.cancel()
 async def stop(self):
  self.episode=False;self.episode_restarts=0
  self.desired=False;self.state='off';self.reason=None;self.clean.clear();self.streak=0
  if self.task:self.task.cancel();await asyncio.gather(self.task,return_exceptions=True)
  self.task=None
 async def run(self):
  while self.desired:
   self.restart_requested=False
   self.worker_task=asyncio.create_task(self.once())
   try:await self.worker_task
   except asyncio.CancelledError:
    if not self.desired or asyncio.current_task().cancelling():raise
    if not self.restart_requested:raise
   except ValueError as e:self.fail(str(e))
   except Exception as e:self.recover(type(e).__name__,restart=True)
   finally:self.worker_task=None
   if not self.desired:break
   if not self.restart_requested:break
   await asyncio.sleep(.5)
 async def once(self):
  self.output.clear();self.inflight.clear();self.clean.clear();self.sequence=0
  self.inputs=asyncio.Queue(maxsize=15);self.streak=0
  try:
   args,root=await asyncio.to_thread(command,self.folder)
   self.proc=await asyncio.create_subprocess_exec(*args,cwd=root,
    env={'PATH':'/usr/bin:/bin','HOME':str(root),'TMPDIR':str(root)},
    stdin=asyncio.subprocess.PIPE,stdout=asyncio.subprocess.PIPE,stderr=asyncio.subprocess.DEVNULL)
   if await asyncio.wait_for(self.proc.stdout.readline(),30)!=b'READY\n':raise ValueError('worker_not_ready')
   self.state='probing';self.probe_started=time.monotonic()
   self.emit('isolation_probing',recoveries=self.recoveries)
   while True:
    frame=await self.inputs.get();started=time.monotonic();self.push_started=started
    self.proc.stdin.write(frame);await asyncio.wait_for(self.proc.stdin.drain(),.5)
    header=await asyncio.wait_for(self.proc.stdout.readexactly(4),.5)
    n=struct.unpack('!I',header)[0]
    if n>19200 or n%2:raise ValueError('invalid_worker_frame')
    data=await asyncio.wait_for(self.proc.stdout.readexactly(n),.5)
    self.service_ms.append((time.monotonic()-started)*1000)
    self.push_started=None;self.observe(data)
  finally:
   if self.proc:
    if self.proc.returncode is None:
     try:self.proc.terminate()
     except ProcessLookupError:pass
     try:await asyncio.wait_for(self.proc.wait(),1)
     except asyncio.TimeoutError:
      try:self.proc.kill()
      except ProcessLookupError:pass
      await self.proc.wait()
    self.proc=None
 def observe(self,data):
  self.output.extend(data);now=time.monotonic()
  if len(self.output)>FRAME*16:raise ValueError('worker_output_overflow')
  while len(self.output)>=FRAME:
   if not self.inflight:raise ValueError('unsolicited_worker_output')
   seq,received=self.inflight.popleft()
   pcm=bytes(self.output[:FRAME]);del self.output[:FRAME]
   latency=now-received;self.frame_ms.append(latency*1000)
   if self.state=='on' and seq>=self.cutover:self.clean[seq]=pcm
   elif self.state in ('probing','recovering'):
    self.streak=self.streak+1 if latency<=self.READY_BUDGET else 0
    if self.streak>=self.STABLE_FRAMES:
     # Next feed chooses a fresh boundary: never replay already forwarded raw.
     self.state='armed'
  if now-self.last_stats>=5:
   self.last_stats=now;self.emit('isolation_latency',state=self.state,**self.stats())
 def feed(self,data):
  """One 20ms frame; output order/length is conserved across every cutover."""
  now=time.monotonic()
  if self.state in ('off','warming','bypass'):return self._raw(data)
  if self.state=='armed':
   # pending originals must have drained on a preceding recovery feed.
   if self.pending:return self._raw(data)
   self.episode=False;self.episode_restarts=0
   self.state='on';self.reason=None;self.cutover=self.sequence
   self.emit('isolation_ready',**self.stats())
  seq=self.sequence;self.sequence+=1
  self.inflight.append((seq,now))
  try:self.inputs.put_nowait(data)
  except asyncio.QueueFull:
   self.recover('input_backlog',restart=True);return self._raw(data)
  if len(self.inflight)>25:
   self.recover('worker_backlog',restart=True);return self._raw(data)
  if self.state=='on':
   self.pending.append((seq,now,data))
   if now-self.pending[0][1]>self.LATENCY_BUDGET:
    self.recover('latency_budget');return self._raw() # pending already includes this frame
   ready=[]
   while self.pending and now-self.pending[0][1]>=.18 and self.pending[0][0] in self.clean:
    ident,_,_=self.pending.popleft();ready.append(self.clean.pop(ident))
   return ready
  if self.probe_started is not None and now-self.probe_started>self.PROBE_TIMEOUT:self.fail('readiness_timeout')
  return self._raw(data)
