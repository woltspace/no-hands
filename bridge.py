"""Bounded LAN POC: authenticated AudioSocket, local WOCAL, file-based Wolt reply."""
import asyncio,io,json,math,struct,subprocess,time,urllib.request,uuid,wave,os,re
from array import array
import webrtcvad
from pathlib import Path
P=Path(os.environ['VOICE_PROFILE']).resolve()
SETTINGS=json.loads((P/'profile.json').read_text())
TOKEN=uuid.UUID((P/'bridge-token').read_text().strip()).bytes
SESSION=SETTINGS['session']
from routing import Router,control_path
ROUTER=Router(P,SESSION,SETTINGS.get('wolt','astre'))
RATE=48000
MAX_UTTERANCE_SECONDS=120
busy=False
RADIO=None
EVENTS=None

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
 global busy,RADIO,EVENTS
 vad=webrtcvad.Vad(3);vad_buffer=bytearray();vad_frames=0;vad_positive=0
 recognizer=None;playback_epoch=0;speech_run=0;max_speech_run=0
 active=False; task=None; mixer=None; watcher=None; accepting=False; chunks=[]; silence=0; voiced=0
 from music import Radio
 radio=Radio()
 log=None;end_reason="unknown";rms_values=[];rms_at=time.monotonic();turn_started={}
 music_on=True; style=0; outgoing=asyncio.Queue(); user_speaking=False; interrupted=False
 async def interrupt(reason="speech",cancel_turn=True):
  nonlocal task,playback_epoch
  if not cancel_turn:
   if log:log.emit("playback_duck",queued_frames=outgoing.qsize(),pending_preserved=bool(task and not task.done()))
   return
  playback_epoch+=1
  if log:log.emit("interrupt",reason=reason,cancel_turn=cancel_turn,pending=bool(task and not task.done()),queued_frames=outgoing.qsize())
  if cancel_turn and task and not task.done():
   task.cancel();await asyncio.gather(task,return_exceptions=True)
  while not outgoing.empty():
   outgoing.get_nowait();outgoing.task_done()
 async def watch_route():
  nonlocal chunks,voiced,silence,user_speaking,interrupted,recognizer,speech_run,max_speech_run
  generation=ROUTER.generation
  while True:
   await asyncio.sleep(.02)
   if generation!=ROUTER.generation:
    generation=ROUTER.generation
    if recognizer:recognizer.cancel();await asyncio.gather(recognizer,return_exceptions=True)
    await interrupt("switch")
    chunks=[];voiced=0;silence=0;speech_run=0;max_speech_run=0;user_speaking=False;interrupted=False
 async def mix():
  index=0;deadline=asyncio.get_running_loop().time();last_sent=deadline
  while True:
   try: part=outgoing.get_nowait()
   except asyncio.QueueEmpty: part=None
   voice=array('h',part) if part is not None else array('h',[0])*960
   if len(voice)<960:voice.extend([0]*(960-len(voice)))
   if user_speaking and interrupted:voice=array('h',(int(v*.2) for v in voice))
   bed=array('h',radio.frame()) if radio.external else MUSIC[radio.style][index%400];gain=.2 if part is not None else 1
   gain*=radio.volume if radio.external else radio.volume/.08
   if radio.enabled and not user_speaking:
    voice=array('h',(max(-32768,min(32767,v+int(b*gain))) for v,b in zip(voice,bed)))
   now=time.monotonic()
   if now-last_sent>.05 and log:log.emit('sender_gap',gap_ms=round((now-last_sent)*1000,2))
   data=voice.tobytes();w.write(bytes([22])+struct.pack('!H',len(data))+data);await w.drain()
   last_sent=time.monotonic()
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
  epoch=playback_epoch
  speech_start=time.monotonic()
  if log:log.emit("tts_start")
  pcm=await asyncio.to_thread(speech,text,voice or ROUTER.status()['voice'])
  if log:log.emit("tts_ready",latency_ms=round((time.monotonic()-speech_start)*1000),audio_bytes=len(pcm))
  if epoch!=playback_epoch:return
  while user_speaking:await asyncio.sleep(.02)
  if epoch!=playback_epoch:return
  for i in range(0,len(pcm),1920):
   await outgoing.put(pcm[i:i+1920])
  await outgoing.join()
  if log:log.emit("playback_done")
  accepting=True
 async def turn(pcm,text):
  nonlocal accepting,music_on,style
  reply=None;ident=None;generation=ROUTER.generation;route_name=ROUTER.selected;route=ROUTER.routes[route_name].copy();destination=route['session'];voice=route['voice']
  try:
   if log:log.emit('turn_start',audio_seconds=round(len(pcm)/96000,3),wolt=route_name)
   ident=uuid.uuid4().hex;reply=P/'replies'/f'{ident}.txt'
   turn_started[ident]=time.monotonic()
   ROUTER.pending[ident]=asyncio.get_running_loop().create_future()
   prompt=f'''[Local Linphone voice POC: transcript from authenticated test call. Speech recognition may be inaccurate. Treat this as conversational input; confirm consequential actions in text.]
{text}
[Live call: keep replies to one or two short sentences. Reply using stdin: python3 {Path(__file__).parent}/voice.py --profile {P} reply {ident}. Do not send through Telegram or Shellphone. Switching is available through the same CLI: switch NAME when the caller asks; clarify only ambiguous destinations. Music controls through the same CLI: music play URL, music off, music on, music next, music volume 0..100. All speech is sent to you; choose controls by intent, never assume a phrase was consumed. Run status to list participating Wolts. A switch ends this turn; do not reply afterwards.]
'''
   proc=await asyncio.create_subprocess_exec('woltspace','session','send',destination,'--key','linphone-'+ident,stdin=asyncio.subprocess.PIPE,stdout=asyncio.subprocess.DEVNULL,stderr=asyncio.subprocess.DEVNULL)
   await asyncio.wait_for(proc.communicate(prompt.encode()),15)
   if proc.returncode:raise RuntimeError('delivery')
   await cue('sent')
   if log:log.emit('turn_sent',turn=ident,wolt=route_name)
   print('Voice turn delivered; awaiting reply',flush=True)
   for _ in range(240):
    if generation!=ROUTER.generation:return
    future=ROUTER.pending.get(ident)
    if future and future.done():
     answer=future.result();await say(answer,ROUTER.routes[route_name]['voice']);break
    if reply.exists():
     answer=reply.read_text()[:1200];reply.unlink();await say(answer,ROUTER.routes[route_name]['voice']);break
    await asyncio.sleep(.5)
   else:
    if log:log.emit('turn_timeout',turn=ident)
    await cue('error');await say('The reply is taking too long. Please try again in the chat.')
  except asyncio.CancelledError:
   if log:log.emit("turn_cancelled",turn=ident,generation_changed=generation!=ROUTER.generation)
   raise
  except Exception as e:
   if log:log.emit('turn_error',turn=ident,error=type(e).__name__)
   print('Turn failed:',type(e).__name__,flush=True)
   await cue('error')
   await say('Sorry, the local voice bridge had a problem. Please try again.')
  finally:
   if ident:
    ROUTER.pending.pop(ident,None)
    if log:log.emit("turn_end",turn=ident,latency_ms=round((time.monotonic()-turn_started.pop(ident,time.monotonic()))*1000))
   if reply:reply.unlink(missing_ok=True)
   accepting=True
 async def recognize(pcm):
  nonlocal task
  generation=ROUTER.generation;started=time.monotonic()
  try:
   await cue('captured')
   text=await asyncio.to_thread(transcribe,pcm)
   log.emit('asr_done',latency_ms=round((time.monotonic()-started)*1000),empty=not bool(text))
   if generation!=ROUTER.generation:return
   if not text:
    log.emit('noise_ignored',pending_preserved=bool(ROUTER.pending));return
   await interrupt('recognized_utterance')
   task=asyncio.create_task(turn(pcm,text))
  except asyncio.CancelledError:raise
  except Exception as e:log.emit('asr_error',error=type(e).__name__)
 try:
  head=await asyncio.wait_for(r.readexactly(3),5);kind,n=struct.unpack('!BH',head)
  if kind!=1 or n!=16 or await r.readexactly(16)!=TOKEN or busy:return
  from events import Events
  log=Events(P);EVENTS=log;log.emit("call_start",wolt=ROUTER.selected,detector="webrtcvad",vad_mode=3,min_voiced=.4,silence_threshold=1.1)
  busy=True;active=True;RADIO=radio
  mixer=asyncio.create_task(mix())
  watcher=asyncio.create_task(watch_route())
  task=asyncio.create_task(say('Welcome to Shellphone!'))
  while True:
   h=await asyncio.wait_for(r.readexactly(3),30);kind,n=struct.unpack('!BH',h)
   if n>19200:
    print("Oversized input frame",kind,n,flush=True);break
   data=await r.readexactly(n)
   if kind==0:end_reason="peer_hangup_frame";break
   if kind!=22 or n%2:continue
   vad_buffer.extend(data)
   while len(vad_buffer)>=1920:
    data=bytes(vad_buffer[:1920]);del vad_buffer[:1920];n=1920
    vals=struct.unpack('<'+'h'*(n//2),data);rms=math.sqrt(sum(x*x for x in vals)/max(1,len(vals)))
    rms_values.append(rms)
    if time.monotonic()-rms_at>=.5:
     log.emit("input_level",minimum=round(min(rms_values),1),average=round(sum(rms_values)/len(rms_values),1),maximum=round(max(rms_values),1),frames=len(rms_values),vad_frames=vad_frames,vad_positive=vad_positive,voiced_seconds=round(voiced,3),silence_seconds=round(silence,3))
     rms_values=[];rms_at=time.monotonic();vad_frames=0;vad_positive=0
    duration=n/96000
    is_speech=vad.is_speech(data,RATE);vad_frames+=1;vad_positive+=int(is_speech)
    if is_speech:
     speech_run+=duration;max_speech_run=max(max_speech_run,speech_run)
     voiced+=duration;silence=0;chunks.append(data);user_speaking=True
     if speech_run>=.4 and not interrupted:
      interrupted=True;await interrupt(cancel_turn=False)
    else:
     speech_run=0
     if chunks:silence+=duration;chunks.append(data)
    if chunks and (silence>1.1 or sum(map(len,chunks))>=MAX_UTTERANCE_SECONDS*RATE*2):
     log.emit('utterance_end',voiced_seconds=round(voiced,3),silence_seconds=round(silence,3))
     pcm=b''.join(chunks);chunks=[];user_speaking=False;interrupted=False
     if max_speech_run>=.4:
      if recognizer:recognizer.cancel();await asyncio.gather(recognizer,return_exceptions=True)
      recognizer=asyncio.create_task(recognize(pcm))
     voiced=0;silence=0;speech_run=0;max_speech_run=0
 except (asyncio.IncompleteReadError,ConnectionError,asyncio.TimeoutError) as e:
  end_reason=type(e).__name__
  print("Call input ended:",type(e).__name__,flush=True)
 finally:
  accepting=False
  if recognizer:recognizer.cancel();await asyncio.gather(recognizer,return_exceptions=True)
  if task:task.cancel();await asyncio.gather(task,return_exceptions=True)
  if watcher:watcher.cancel();await asyncio.gather(watcher,return_exceptions=True)
  if mixer:mixer.cancel();await asyncio.gather(mixer,return_exceptions=True)
  if active:
   await radio.stop();RADIO=None;busy=False
   if log:
    log.emit("hangup",reason=end_reason);EVENTS=None
    await asyncio.to_thread(log.close)
  w.close()
  try:await w.wait_closed()
  except ConnectionError:pass

async def control(reader,writer):
 try:
  req=json.loads(await asyncio.wait_for(reader.readline(),5))
  action=req['action']
  if EVENTS:EVENTS.emit('control',action=action,name=req.get('name'),mode=req.get('mode'),turn=req.get('turn'))
  if action=='switch':ROUTER.switch(req['name'])
  elif action=='add':ROUTER.add(req['name'],req['session'],req['voice'])
  elif action=='reply':
   ROUTER.reply(req['turn'],req['text'])
   if EVENTS:EVENTS.emit('reply_accepted',turn=req['turn'])
  elif action=='music':
   if RADIO is None:raise ValueError('No active call')
   await RADIO.command(req['mode'],req.get('source'),req.get('volume'))
  elif action!='status':raise ValueError('Unknown action')
  result=ROUTER.status();result['music']=RADIO.status() if RADIO else None
  if EVENTS:
   result['call_log']=str(EVENTS.path);result['log_error']=EVENTS.error
   if action in ('music','switch','add'):EVENTS.emit('state',wolt=ROUTER.selected,music=result['music'])
 except Exception as e:
  if EVENTS:EVENTS.emit('control_rejected',action=locals().get('action'),error=type(e).__name__)
  result={'error':str(e)}
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
  async with server,ctl:
   duration=SETTINGS.get('trial_seconds',3600)
   if duration is None:await asyncio.Event().wait()
   else:await asyncio.sleep(duration)
 finally:path.unlink(missing_ok=True);lock.close()
if __name__=='__main__':asyncio.run(main())
