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
 server=await asyncio.start_server(m.client,'127.0.0.1',0)
 r,w=await asyncio.open_connection('127.0.0.1',server.sockets[0].getsockname()[1]);w.write(b'\x01\x00\x10'+m.TOKEN);await w.drain()
 received=[]
 async def read():
  try:
   while True:
    k,n=struct.unpack('!BH',await r.readexactly(3));d=await r.readexactly(n);assert k==22 and n==1920
    received.append(max(abs(x) for x in struct.unpack('<960h',d)))
  except asyncio.IncompleteReadError:pass
 reader=asyncio.create_task(read());await asyncio.sleep(.15)
 assert any(x>4000 for x in received),'greeting played'
 for i in range(25):
  d=struct.pack('<h',1500)*960;w.write(b'\x16\x07\x80'+d);await w.drain();await asyncio.sleep(.02)
 cut=len(received);await asyncio.sleep(.1)
 assert received[cut:] and all(0<x<=1000 for x in received[cut:]),'speech ducked and music muted while user speaks'
 for i in range(65):
  w.write(b'\x16\x07\x80'+bytes(1920));await w.drain();await asyncio.sleep(.02)
 assert len(seen)==1,'interruption sentence transcribed'
 await asyncio.sleep(.4)
 assert sent and '\nstop\n' in sent[0], 'stop transcript must reach Wolt'
 assert max(received[-5:])<500,'old greeting never resumed; only quiet music'
 w.write(b'\0\0\0');await w.drain();w.close();await w.wait_closed();await reader;await asyncio.sleep(.05)
 server.close();await server.wait_closed();assert not m.busy
 import json
 logs=list((p/'logs').glob('call-*.jsonl'));assert len(logs)==1
 rows=[json.loads(line) for line in logs[0].read_text().splitlines()]
 kinds={row['event'] for row in rows}
 assert {'call_start','input_level','interrupt','turn_sent','turn_cancelled','hangup','log_closed'}<=kinds,kinds
 assert not logs[0].stat().st_mode & 0o077
 assert all('text' not in row and 'transcript' not in row and 'audio' not in row for row in rows)
 print('PASS metadata log events and private file permissions')
 print('PASS: speech ducks playback; music mutes while speaking; stop forwarded to Wolt; no old audio resumes; hangup releases call')
try:asyncio.run(test())
finally:tmp.cleanup()
