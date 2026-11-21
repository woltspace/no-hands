"""Local metadata-only call events; bounded queue, disk writes on a worker."""
import json,os,queue,threading,time,uuid
from pathlib import Path
from datetime import datetime,timezone

class Events:
 def __init__(self,profile):
  self.call=uuid.uuid4().hex;self.start=time.monotonic();self.q=queue.Queue(2048);self.done=threading.Event();self.dropped=0;self.error=None
  self.path=Path(profile)/'logs'/('call-'+self.call+'.jsonl')
  self.worker=threading.Thread(target=self._write,daemon=True);self.worker.start()
 def emit(self,event,**fields):
  row={'utc':datetime.now(timezone.utc).isoformat(),'elapsed':round(time.monotonic()-self.start,4),'call':self.call,'event':event,**fields}
  try:self.q.put_nowait(row)
  except queue.Full:self.dropped+=1
 def _write(self):
  try:
   self.path.parent.mkdir(mode=0o700,exist_ok=True)
   fd=os.open(self.path,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
   with os.fdopen(fd,'w') as out:
    while not self.done.is_set() or not self.q.empty():
     try:row=self.q.get(timeout=.2)
     except queue.Empty:continue
     out.write(json.dumps(row,separators=(',',':'))+'\n');out.flush()
    out.write(json.dumps({'event':'log_closed','dropped':self.dropped})+'\n')
  except OSError as e:self.error=type(e).__name__;print('Call log failed:',self.error,flush=True)
 def close(self):self.done.set();self.worker.join(timeout=2)
