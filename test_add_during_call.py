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
 from voice import call
 ctlpath=m.control_path(p)
 ctl=await asyncio.start_unix_server(m.control,str(ctlpath))
 server=await asyncio.start_server(m.client,'127.0.0.1',0)
 r,w=await asyncio.open_connection('127.0.0.1',server.sockets[0].getsockname()[1]);w.write(b'\x01\x00\x10'+m.TOKEN);await w.drain()
 received=[]
 async def read():
  try:
   while True:
    k,n=struct.unpack('!BH',await r.readexactly(3));d=await r.readexactly(n)
    received.append(max(abs(x) for x in struct.unpack('<960h',d)))
  except (asyncio.IncompleteReadError,ConnectionError):pass
 reader=asyncio.create_task(read());await asyncio.sleep(.15)
 assert any(x>4000 for x in received)
 await asyncio.to_thread(call,p,{'action':'music','mode':'off'})
 pending=asyncio.get_running_loop().create_future();m.ROUTER.pending['pending']=pending
 generation=m.ROUTER.generation
 for i in range(20):
  await asyncio.to_thread(call,p,{'action':'add','name':'other','session':'verified-test-session','voice':'jean' if i%2 else 'cosette'})
  await asyncio.sleep(.025)
  assert m.busy and m.RADIO is not None,'call ended'
  assert not m.RADIO.enabled,'music reset'
  assert not pending.done() and m.ROUTER.pending.get('pending') is pending,'pending reply lost'
  assert m.ROUTER.generation==generation,'generation changed'
 await asyncio.to_thread(call,p,{'action':'reply','turn':'pending','text':'still accepted'})
 assert pending.result()=='still accepted'
 w.close();await w.wait_closed();await reader;await asyncio.sleep(.05)
 assert not m.busy
 server.close();ctl.close();await server.wait_closed();await ctl.wait_closed();ctlpath.unlink(missing_ok=True)
 print('PASS 20 mid-call adds/voice changes preserve call, music off, generation and pending reply')
try:asyncio.run(test())
finally:tmp.cleanup()
