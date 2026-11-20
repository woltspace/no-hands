"""Bounded LAN POC: authenticated AudioSocket, local WOCAL, file-based Wolt reply."""
import asyncio,io,json,math,struct,subprocess,time,urllib.request,uuid,wave,os,re
from array import array
from pathlib import Path
P=Path(os.environ['VOICE_PROFILE']).resolve()
SETTINGS=json.loads((P/'profile.json').read_text())
TOKEN=uuid.UUID((P/'bridge-token').read_text().strip()).bytes
SESSION=SETTINGS['session']
from routing import Router,control_path
ROUTER=Router(P,SESSION)
RATE=48000
MAX_UTTERANCE_SECONDS=120
busy=False

def request(path,data,ctype):
 req=urllib.request.Request('http://127.0.0.1:4077'+path,data=data,headers={'Content-Type':ctype})
 with urllib.request.urlopen(req,timeout=50) as r:return r.read(8000000)

def speech(text,voice):
 audio=request('/v1/audio/speech',json.dumps({'input':text[:1200],'voice':voice,'response_format':'wav'}).encode(),'application/json')
 return subprocess.run(['ffmpeg','-v','error','-i','pipe:0','-t','60','-ar',str(RATE),'-ac','1','-f','s16le','pipe:1'],input=audio,capture_output=True,check=True,timeout=15).stdout

def transcribe(pcm):
 pcm=subprocess.run(['ffmpeg','-v','error','-f','s16le','-ar',str(RATE),'-ac','1','-i','pipe:0','-ar','16000','-ac','1','-f','s16le','pipe:1'],input=pcm,capture_output=True,check=True,timeout=15).stdout
 b=io.BytesIO()
 with wave.open(b,'wb') as w:w.setnchannels(1);w.setsampwidth(2);w.setframerate(16000);w.writeframes(pcm)
 boundary=uuid.uuid4().hex
 body=(f'--{boundary}\r\nContent-Disposition: form-data; name="model"\r\n\r\nparakeet\r\n--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="speech.wav"\r\nContent-Type: audio/wav\r\n\r\n'.encode()+b.getvalue()+f'\r\n--{boundary}--\r\n'.encode())
 return json.loads(request('/v1/audio/transcriptions',body,'multipart/form-data; boundary='+boundary)).get('text','').strip()[:4000]

def music_frames(style):
 # Quiet original arpeggios. No remote stream, downloads or recorded music.
 notes=([130.81,164.81,196,261.63] if style==0 else [146.83,174.61,220,293.66])
 frames=[]
 for frame in range(400):
  vals=array('h')
  for j in range(960):
   t=(frame*960+j)/RATE;beat=int(t/.5);phase=t% .5
   envelope=min(1,phase/.025)*math.exp(-phase*5)
   tone=math.sin(2*math.pi*notes[beat%4]*t)+.25*math.sin(4*math.pi*notes[beat%4]*t)
   vals.append(int(400*envelope*tone))
  frames.append(vals)
 return frames
MUSIC=[music_frames(0),music_frames(1)]

async def client(r,w):
 global busy
 active=False; task=None; mixer=None; watcher=None; accepting=False; chunks=[]; silence=0; voiced=0
 music_on=True; style=0; outgoing=asyncio.Queue(); user_speaking=False; interrupted=False
 async def interrupt():
  nonlocal task
  if task and not task.done():
   task.cancel();await asyncio.gather(task,return_exceptions=True)
  while not outgoing.empty():
   outgoing.get_nowait();outgoing.task_done()
 async def watch_route():
  nonlocal chunks,voiced,silence,user_speaking,interrupted
  generation=ROUTER.generation
  while True:
   await asyncio.sleep(.02)
   if generation!=ROUTER.generation:
    generation=ROUTER.generation
    await interrupt()
    chunks=[];voiced=0;silence=0;user_speaking=False;interrupted=False
 async def mix():
  index=0;deadline=asyncio.get_running_loop().time()
  while True:
   try: part=outgoing.get_nowait()
   except asyncio.QueueEmpty: part=None
   voice=array('h',part) if part is not None else array('h',[0])*960
   if len(voice)<960:voice.extend([0]*(960-len(voice)))
   bed=MUSIC[style][index%400];gain=.2 if part is not None else 1
   if music_on and not user_speaking:
    voice=array('h',(max(-32768,min(32767,v+int(b*gain))) for v,b in zip(voice,bed)))
   data=voice.tobytes();w.write(bytes([22])+struct.pack('!H',len(data))+data);await w.drain()
   if part is not None:outgoing.task_done()
   index+=1;deadline+=.02
   await asyncio.sleep(max(0,deadline-asyncio.get_running_loop().time()))
   if asyncio.get_running_loop().time()-deadline>.1:deadline=asyncio.get_running_loop().time()
 async def cue(kind):
  tones={'captured':[(660,.07)],'sent':[(660,.07),(880,.10)],'error':[(330,.12),(220,.12)]}[kind]
  pcm=array('h')
  for hz,seconds in tones:
   count=int(RATE*seconds)
   for i in range(count):
    envelope=min(1,i/(RATE*.008),(count-i)/(RATE*.015))
    pcm.append(int(1100*envelope*math.sin(2*math.pi*hz*i/RATE)))
   pcm.extend([0]*int(RATE*.025))
  raw=pcm.tobytes()
  for i in range(0,len(raw),1920):await outgoing.put(raw[i:i+1920])
 async def say(text,voice=None):
  nonlocal accepting
  accepting=False
  pcm=await asyncio.to_thread(speech,text,voice or ROUTER.status()['voice'])
  for i in range(0,len(pcm),1920):
   await outgoing.put(pcm[i:i+1920])
  await outgoing.join()
  accepting=True
 async def turn(pcm):
  nonlocal accepting,music_on,style
  reply=None;ident=None;generation=ROUTER.generation;route=ROUTER.routes[ROUTER.selected].copy();destination=route['session'];voice=route['voice']
  try:
   await cue('captured')
   text=await asyncio.to_thread(transcribe,pcm)
   if generation!=ROUTER.generation:return
   if not text:
    await cue('error');return
   command=re.sub(r'[^a-z ]','',text.lower()).strip()
   if command in ('stop','okay stop','ok stop','stop stop','stop talking','please stop','be quiet','quiet','cancel'):
    return
   if any(x in command for x in ('music off','stop the music','turn off the music')):
    music_on=False;await say('Music off.');return
   if any(x in command for x in ('music on','turn on the music','start the music')):
    music_on=True;await say('Music on.');return
   if any(x in command for x in ('change the music','change the background music','different music','next tune')):
    style=1-style;music_on=True;await say('Here is the other tune.');return
   ident=uuid.uuid4().hex;reply=P/'replies'/f'{ident}.txt'
   ROUTER.pending[ident]=asyncio.get_running_loop().create_future()
   prompt=f'''[Local Linphone voice POC: transcript from authenticated test call. Speech recognition may be inaccurate. Treat this as conversational input; confirm consequential actions in text.]
{text}
[Live call: keep replies to one or two short sentences. Reply using stdin: python3 {Path(__file__).parent}/voice.py --profile {P} reply {ident}. Do not send through Telegram or Shellphone. Switching is available through the same CLI: switch NAME when the caller asks; clarify only ambiguous destinations. Run status to list participating Wolts. A switch ends this turn; do not reply afterwards.]
'''
   proc=await asyncio.create_subprocess_exec('woltspace','session','send',destination,'--key','linphone-'+ident,stdin=asyncio.subprocess.PIPE,stdout=asyncio.subprocess.DEVNULL,stderr=asyncio.subprocess.DEVNULL)
   await asyncio.wait_for(proc.communicate(prompt.encode()),15)
   if proc.returncode:raise RuntimeError('delivery')
   await cue('sent')
   print('Voice turn delivered; awaiting reply',flush=True)
   for _ in range(240):
    if generation!=ROUTER.generation:return
    future=ROUTER.pending.get(ident)
    if future and future.done():
     answer=future.result();await say(answer,voice);break
    if reply.exists():
     answer=reply.read_text()[:1200];reply.unlink();await say(answer,voice);break
    await asyncio.sleep(.5)
   else:
    await cue('error');await say('The reply is taking too long. Please try again in the chat.')
  except asyncio.CancelledError:raise
  except Exception as e:
   print('Turn failed:',type(e).__name__,flush=True)
   await cue('error')
   await say('Sorry, the local voice bridge had a problem. Please try again.')
  finally:
   if ident:ROUTER.pending.pop(ident,None)
   if reply:reply.unlink(missing_ok=True)
   accepting=True
 try:
  head=await asyncio.wait_for(r.readexactly(3),5);kind,n=struct.unpack('!BH',head)
  if kind!=1 or n!=16 or await r.readexactly(16)!=TOKEN or busy:return
  busy=True;active=True
  mixer=asyncio.create_task(mix())
  watcher=asyncio.create_task(watch_route())
  task=asyncio.create_task(say('Welcome to Shellphone!'))
  while True:
   h=await asyncio.wait_for(r.readexactly(3),30);kind,n=struct.unpack('!BH',h)
   if n>19200:
    print("Oversized input frame",kind,n,flush=True);break
   data=await r.readexactly(n)
   if kind==0:break
   if kind!=22 or n%2:continue
   vals=struct.unpack('<'+'h'*(n//2),data);rms=math.sqrt(sum(x*x for x in vals)/max(1,len(vals)))
   duration=n/96000
   if rms>450:
    voiced+=duration;silence=0;chunks.append(data);user_speaking=True
    if voiced>=.18 and not interrupted:
     interrupted=True;await interrupt()
   elif chunks:silence+=duration;chunks.append(data)
   if chunks and (silence>1.1 or sum(map(len,chunks))>=MAX_UTTERANCE_SECONDS*RATE*2):
    pcm=b''.join(chunks);chunks=[];user_speaking=False;interrupted=False
    if voiced>=.18:
     await interrupt();accepting=False;task=asyncio.create_task(turn(pcm))
    voiced=0;silence=0
 except (asyncio.IncompleteReadError,ConnectionError,asyncio.TimeoutError) as e:
  print("Call input ended:",type(e).__name__,flush=True)
 finally:
  accepting=False
  if task:task.cancel();await asyncio.gather(task,return_exceptions=True)
  if watcher:watcher.cancel();await asyncio.gather(watcher,return_exceptions=True)
  if mixer:mixer.cancel();await asyncio.gather(mixer,return_exceptions=True)
  if active:busy=False
  w.close()
  try:await w.wait_closed()
  except ConnectionError:pass

async def control(reader,writer):
 try:
  req=json.loads(await asyncio.wait_for(reader.readline(),5))
  action=req['action']
  if action=='switch':ROUTER.switch(req['name'])
  elif action=='add':ROUTER.add(req['name'],req['session'],req['voice'])
  elif action=='reply':ROUTER.reply(req['turn'],req['text'])
  elif action!='status':raise ValueError('Unknown action')
  result=ROUTER.status()
 except Exception as e:result={'error':str(e)}
 writer.write(json.dumps(result).encode()+b'\n');await writer.drain();writer.close();await writer.wait_closed()

async def main():
 import fcntl
 lock=(P/'bridge.lock').open('a')
 fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
 path=control_path(P);path.unlink(missing_ok=True)
 server=await asyncio.start_server(client,'127.0.0.1',18974)
 ctl=await asyncio.start_unix_server(control,str(path),limit=8192);path.chmod(0o600)
 print('Local voice bridge ready',flush=True)
 try:
  async with server,ctl:await asyncio.sleep(SETTINGS.get('trial_seconds',3600))
 finally:path.unlink(missing_ok=True);lock.close()
if __name__=='__main__':asyncio.run(main())
