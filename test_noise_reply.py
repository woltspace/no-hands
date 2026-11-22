import importlib.util,asyncio,struct
import os,tempfile
from pathlib import Path
import setup
tmp=tempfile.TemporaryDirectory(dir=Path(__file__).parent)
setup.ROOT=Path(tmp.name)
p=setup.initialize('test','100.64.0.1','100.64.0.2','test-session')
os.environ['VOICE_PROFILE']=str(p)
s=importlib.util.spec_from_file_location('bridge',Path(__file__).parent/'bridge.py');m=importlib.util.module_from_spec(s);s.loader.exec_module(m)
class FakeVad:
 def __init__(self,mode):pass
 def is_speech(self,data,rate):return max(abs(x) for x in struct.unpack('<960h',data))>600
m.webrtcvad.Vad=FakeVad
m.speech=lambda text,voice:struct.pack('<h',5000)*(m.RATE*5)
seen=[]
def transcribe(pcm):seen.append(pcm);return 'stop'
m.transcribe=transcribe
sent=[]
original_spawn=asyncio.create_subprocess_exec
async def fake_spawn(*args,**kwargs):
 if args[0]!='woltspace':return await original_spawn(*args,**kwargs)
 class Process:
  returncode=0
  async def communicate(self,prompt):sent.append(prompt.decode());return b'',b''
 return Process()
asyncio.create_subprocess_exec=fake_spawn
async def test():
 answers=iter(['hello','','uh, uh','new question'])
 m.transcribe=lambda pcm:next(answers)
 server=await asyncio.start_server(m.client,'127.0.0.1',0)
 r,w=await asyncio.open_connection('127.0.0.1',server.sockets[0].getsockname()[1]);w.write(b'\x01\x00\x10'+m.TOKEN);await w.drain()
 async def read():
  try:
   while True:
    k,n=struct.unpack('!BH',await r.readexactly(3));await r.readexactly(n)
  except asyncio.IncompleteReadError:pass
 reader=asyncio.create_task(read())
 async def utterance():
  for level,count in [(1500,25),(0,60)]:
   for _ in range(count):
    d=struct.pack('<h',level)*960;w.write(b'\x16\x07\x80'+d);await w.drain();await asyncio.sleep(.02)
  await asyncio.sleep(.15)
 await utterance();assert len(m.ROUTER.pending)==1
 old=next(iter(m.ROUTER.pending));future=m.ROUTER.pending[old]
 await utterance();assert m.ROUTER.pending.get(old) is future and not future.done(),'empty ASR cancelled reply'
 await utterance();assert m.ROUTER.pending.get(old) is future and not future.done(),'filler-only ASR cancelled reply'
 await utterance();assert old not in m.ROUTER.pending,'new words did not supersede old turn'
 try:m.ROUTER.reply(old,'stale')
 except ValueError:pass
 else:raise AssertionError('stale accepted')
 new=next(iter(m.ROUTER.pending));m.ROUTER.reply(new,'current accepted')
 w.close();await w.wait_closed();await reader;await asyncio.sleep(.3)
 server.close();await server.wait_closed()
 print('PASS empty/filler-only ASR preserves pending reply; new words supersede; stale reply rejected')
try:asyncio.run(test())
finally:tmp.cleanup()
