import importlib.util,asyncio,struct
import os,tempfile
from pathlib import Path
import setup
tmp=tempfile.TemporaryDirectory(dir=Path(__file__).parent)
setup.ROOT=Path(tmp.name)
p=setup.initialize('test','100.64.0.1','100.64.0.2','test-session')
os.environ['VOICE_PROFILE']=str(p)
s=importlib.util.spec_from_file_location('bridge',Path(__file__).parent/'bridge.py');m=importlib.util.module_from_spec(s);s.loader.exec_module(m)
m.speech=lambda text,voice:struct.pack('<h',5000)*(m.RATE*5)
seen=[]
def transcribe(pcm):seen.append(pcm);return 'stop'
m.transcribe=transcribe
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
 for i in range(20):
  d=struct.pack('<h',1500)*960;w.write(b'\x16\x07\x80'+d);await w.drain();await asyncio.sleep(.02)
 cut=len(received);await asyncio.sleep(.1)
 assert all(x==0 for x in received[cut:]),'speech and music silent while user speaks'
 for i in range(65):
  w.write(b'\x16\x07\x80'+bytes(1920));await w.drain();await asyncio.sleep(.02)
 assert len(seen)==1,'interruption sentence transcribed'
 assert max(received[-5:])<500,'old greeting never resumed; only quiet music'
 w.write(b'\0\0\0');await w.drain();w.close();await w.wait_closed();await reader;await asyncio.sleep(.05)
 server.close();await server.wait_closed();assert not m.busy
 print('PASS: speech interrupts queued playback; music mutes while speaking; stop consumed locally; no old audio resumes; hangup releases call')
try:asyncio.run(test())
finally:tmp.cleanup()
