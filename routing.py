"""Single-owner local call routing. Same-user processes are trusted."""
import json,re,uuid
from pathlib import Path

class Router:
 def __init__(self, profile, default, name="astre"):
  self.path=Path(profile)/'routes.json'
  self.routes=json.loads(self.path.read_text()) if self.path.exists() else {name:{'session':default,'voice':'alba'}}
  self.selected=next(iter(self.routes));self.generation=0;self.pending={}
 def switch(self,name):
  if name not in self.routes:raise ValueError('Unknown Wolt; register its verified session first.')
  self.selected=name;self.generation+=1
  for future in self.pending.values():
   if not future.done():future.cancel()
  self.pending.clear()
  return self.status()
 def status(self):return {'wolt':self.selected,'session':self.routes[self.selected]['session'],'voice':self.routes[self.selected]['voice'],'generation':self.generation,'wolts':list(self.routes)}
 def add(self,name,session,voice):
  if not re.fullmatch('[a-z][a-z0-9-]*',name) or not re.fullmatch('[a-zA-Z0-9_-]+',session):raise ValueError('Invalid name or session')
  if not re.fullmatch('[a-z][a-z0-9_-]*',voice):raise ValueError('Invalid voice')
  if name==self.selected and name in self.routes and self.routes[name]['session']!=session:raise ValueError('Cannot replace selected session; switch away first')
  self.routes[name]={'session':session,'voice':voice}
  tmp=self.path.with_name('routes-'+uuid.uuid4().hex+'.tmp');tmp.write_text(json.dumps(self.routes));tmp.chmod(0o600);tmp.replace(self.path)
 def reply(self,turn,text):
  future=self.pending.get(turn)
  if future is None or future.done():raise ValueError('Turn expired or switched away')
  future.set_result(text[:1200])

def control_path(profile):
 import hashlib
 p=Path(profile).resolve()
 # macOS Unix socket paths are limited to roughly 104 bytes.
 base=p
 while len(str(base).encode())>65:base=base.parent
 return base/('.voice-'+hashlib.sha256(str(p).encode()).hexdigest()[:16]+'.sock')
