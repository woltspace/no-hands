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
from call_modes import PRESETS,incoming_mode
ROUTER=Router(P,SESSION,SETTINGS.get('wolt','astre'))
RATE=48000
DETECTOR=SETTINGS.get("detector","webrtcvad")
if DETECTOR not in ("webrtcvad","rms"):raise ValueError("Unknown speech detector")
MIN_VOICED=.18 if DETECTOR=="rms" else .4
DUCK_RELEASE_SECONDS=.2
HANDOFF_WAIT_SECONDS=30
MAX_UTTERANCE_SECONDS=120
busy=False
RADIO=None
EVENTS=None
MODE_CONTROL=None
ISOLATION=None
CHIMES=None
CALL_ID=None
RECORDING=None
RECORD_CONTROL=None
SWITCH_CONTROL=None
HANDOFF_STATUS=None

from speech_provider import SpeechProvider
PROVIDER=SpeechProvider(SETTINGS)
SYSTEM_VOICE=SETTINGS.get('system_voice','azelma' if PROVIDER.kind=='local' else 'onyx')
if not isinstance(SYSTEM_VOICE,str) or not SYSTEM_VOICE.strip():raise ValueError('system_voice must be a nonempty voice name')
if any(r['voice']==SYSTEM_VOICE for r in ROUTER.routes.values()):raise ValueError('system_voice must differ from every Wolt route voice')

def speech(text,voice):
 audio=PROVIDER.speech(text,voice)
 return subprocess.run(['ffmpeg','-v','error','-i','pipe:0','-t','60','-ar',str(RATE),'-ac','1','-f','s16le','pipe:1'],input=audio,capture_output=True,check=True,timeout=15).stdout

def transcribe(pcm):
 pcm=subprocess.run(['ffmpeg','-v','error','-f','s16le','-ar',str(RATE),'-ac','1','-i','pipe:0','-ar','16000','-ac','1','-f','s16le','pipe:1'],input=pcm,capture_output=True,check=True,timeout=15).stdout
 b=io.BytesIO()
 with wave.open(b,'wb') as w:w.setnchannels(1);w.setsampwidth(2);w.setframerate(16000);w.writeframes(pcm)
 return PROVIDER.transcribe(b.getvalue())

def has_words(text):
 # Only empty/punctuation or hesitation-only ASR is noise. Do not interpret
 # commands, strip fillers from real sentences, or swallow short answers.
 tokens=re.findall(r"\w+(?:['’]\w+)*",text.casefold())
 return bool(tokens) and not all(re.fullmatch(r'u+h+|u+m+|er|erm',token) for token in tokens)

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
 global busy,RADIO,EVENTS,MODE_CONTROL,ISOLATION,CHIMES,CALL_ID,RECORDING,RECORD_CONTROL,SWITCH_CONTROL,HANDOFF_STATUS
 vad=None;detector=DETECTOR;min_voiced=MIN_VOICED;mode=None;vad_buffer=bytearray();vad_frames=0;vad_positive=0
 recognizer=None;playback_epoch=0;speech_run=0;max_speech_run=0
 active=False; task=None; mixer=None; watcher=None; accepting=False; chunks=[]; silence=0; voiced=0
 from music import Radio
 radio=Radio()
 log=None;end_reason="unknown";rms_values=[];rms_at=time.monotonic();turn_started={}
 music_on=True; style=0; outgoing=asyncio.Queue(); user_speaking=False; interrupted=False
 from recording import Recording
 recorder=Recording(P);record_arm=None;call_input_samples=0;call_processed_samples=0
 def metadata(event,**fields):
  if log:log.emit(event,**fields)
  recorder.event(event,**fields)
 from isolation import Isolation
 from chime import Chimes
 isolator=Isolation(SETTINGS.get('isolator_folder'),metadata)
 route_generation=ROUTER.generation;handoff_state={'state':'idle'};switch_lock=asyncio.Lock()
 chimes=None;speech_lock=asyncio.Lock();chime_playing=False;chime_generation=None;mic_active=False;mic_quiet=0;raw_quiet_until=0
 def set_mode(name=None):
  nonlocal mode,detector,min_voiced,vad,vad_buffer,vad_frames,vad_positive
  nonlocal chunks,voiced,silence,speech_run,max_speech_run,user_speaking,interrupted
  if name is not None and name!=mode:
   if name not in PRESETS:raise ValueError('Mode must be normal or car')
   preset=PRESETS[name]
   next_vad=webrtcvad.Vad(3) if preset['detector']=='webrtcvad' else None
   mode=name;detector=preset['detector'];min_voiced=preset['min_voiced'];vad=next_vad
   # A clean capture boundary; completed ASR, pending reply, playback, route
   # and radio are preserved. Never call interrupt() for a mode change.
   vad_buffer.clear();vad_frames=0;vad_positive=0
   chunks=[];voiced=0;silence=0;speech_run=0;max_speech_run=0
   user_speaking=False;interrupted=False
   if log:log.emit('mode_changed',mode=mode,detector=detector,min_voiced=min_voiced)
  return {'name':mode,'detector':detector,'min_voiced':min_voiced,'duck_release_seconds':DUCK_RELEASE_SECONDS}
 async def cancel_record_arm():
  nonlocal record_arm
  if record_arm and not record_arm.done():
   record_arm.cancel();await asyncio.gather(record_arm,return_exceptions=True)
  record_arm=None
  if recorder.state=='arming':recorder.state='off'
 async def recording_command(name):
  nonlocal record_arm
  if name=='off':
   await cancel_record_arm();await recorder.stop();metadata('recording_off');return
  if name!='on':raise ValueError('Recording must be on or off')
  if recorder.state in ('on','arming'):return
  if recorder.state=='stopping' or (recorder.preparing_task and not recorder.preparing_task.done()):raise ValueError('Recording writer is still stopping')
  recorder.state='arming';generation=ROUTER.generation
  async def arm():
   try:
    heard=await chime_say('Recording your microphone on this call. Ask me to stop recording when you want to stop.',SYSTEM_VOICE,generation)
    if not heard or generation!=ROUTER.generation:
     recorder.state='off';return
    await recorder.start();metadata('recording_on',call_id=CALL_ID,call_input_samples=call_input_samples)
   except asyncio.CancelledError:
    if recorder.state=='arming':recorder.state='off'
    raise
   except Exception as e:
    recorder.state='off';recorder.reason=type(e).__name__;metadata('recording_error',reason=type(e).__name__)
  record_arm=asyncio.create_task(arm())
 async def interrupt(reason="speech",cancel_turn=True):
  nonlocal task,playback_epoch
  if not cancel_turn:
   if log:log.emit("playback_duck",queued_frames=outgoing.qsize(),pending_preserved=bool(task and not task.done()))
   return
  playback_epoch+=1
  await cancel_record_arm()
  if chimes:await chimes.cancel()
  if log:log.emit("interrupt",reason=reason,cancel_turn=cancel_turn,pending=bool(task and not task.done()),queued_frames=outgoing.qsize())
  if cancel_turn and task and not task.done():
   task.cancel();await asyncio.gather(task,return_exceptions=True)
  while not outgoing.empty():
   outgoing.get_nowait();outgoing.task_done()
 async def watch_route():
  nonlocal chunks,voiced,silence,user_speaking,interrupted,recognizer,speech_run,max_speech_run
  nonlocal route_generation
  while True:
   await asyncio.sleep(.02)
   if route_generation!=ROUTER.generation:
    route_generation=ROUTER.generation
    if recognizer:recognizer.cancel();await asyncio.gather(recognizer,return_exceptions=True)
    await interrupt("switch")
    chunks=[];voiced=0;silence=0;speech_run=0;max_speech_run=0;user_speaking=False;interrupted=False
 async def mix():
  index=0;deadline=asyncio.get_running_loop().time();last_sent=deadline;last_duck=False
  while True:
   try:
    if chime_playing and (mic_active or time.monotonic()<raw_quiet_until or chime_generation!=ROUTER.generation):raise asyncio.QueueEmpty
    part=outgoing.get_nowait()
   except asyncio.QueueEmpty: part=None
   voice=array('h',part) if part is not None else array('h',[0])*960
   if len(voice)<960:voice.extend([0]*(960-len(voice)))
   ducked=part is not None and user_speaking and interrupted
   if ducked!=last_duck and log:log.emit('playback_gain',ducked=ducked,queued_frames=outgoing.qsize())
   last_duck=ducked
   if ducked:voice=array('h',(int(v*.2) for v in voice))
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
  tones={'captured':[(660,.07)],'sent':[(660,.07),(880,.10)],'connected':[(660,.08),(990,.12),(1320,.12)],'error':[(330,.12),(220,.12)]}[kind]
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
  epoch=playback_epoch;generation=ROUTER.generation
  async with speech_lock:
   if epoch!=playback_epoch or generation!=ROUTER.generation:return
   await speak(text,voice)
 async def chime_say(text,voice,generation):
  nonlocal chime_playing,chime_generation
  epoch=playback_epoch
  async with speech_lock:
   if epoch!=playback_epoch or generation!=ROUTER.generation:return
   chime_playing=True;chime_generation=generation
   try:
    await speak(text,voice)
    return epoch==playback_epoch and generation==ROUTER.generation
   except asyncio.CancelledError:
    while not outgoing.empty():outgoing.get_nowait();outgoing.task_done()
    raise
   finally:chime_playing=False;chime_generation=None
 async def speak(text,voice=None):
  nonlocal accepting
  accepting=False
  epoch=playback_epoch
  speech_start=time.monotonic()
  if log:log.emit("tts_start")
  pcm=await asyncio.to_thread(speech,text,voice or SYSTEM_VOICE)
  if log:log.emit("tts_ready",latency_ms=round((time.monotonic()-speech_start)*1000),audio_bytes=len(pcm))
  if epoch!=playback_epoch:return
  while user_speaking:await asyncio.sleep(.02)
  if epoch!=playback_epoch:return
  if log:log.emit('playback_queued',audio_bytes=len(pcm),queued_frames=outgoing.qsize())
  for i in range(0,len(pcm),1920):
   await outgoing.put(pcm[i:i+1920])
  await outgoing.join()
  if log:log.emit("playback_done")
  accepting=True
 async def turn(pcm,text,arrival=False):
  nonlocal accepting,music_on,style
  reply=None;ident=None;generation=ROUTER.generation;route_name=ROUTER.selected;route=ROUTER.routes[route_name].copy();destination=route['session'];voice=route['voice']
  try:
   if log:log.emit('turn_start',audio_seconds=round(len(pcm)/96000,3),wolt=route_name)
   ident=uuid.uuid4().hex;reply=P/'replies'/f'{ident}.txt'
   turn_started[ident]=time.monotonic()
   ROUTER.pending[ident]=asyncio.get_running_loop().create_future()
   prompt=f'''[Local Linphone voice POC: transcript from authenticated test call. Speech recognition may be inaccurate. Treat this as conversational input; confirm consequential actions in text.]
{text}
[Live call: keep replies to one or two short sentences. Reply using stdin: python3 {Path(__file__).parent}/voice.py --profile {P} reply {ident}. Do not send through Telegram or Shellphone. Switching is available through the same CLI: switch NAME --handoff "Handing you to NAME." when the caller asks; supply your own short handoff sentence, which the bridge speaks in your voice before switching; clarify only ambiguous destinations. Music controls through the same CLI: music play URL, music off, music on, music next, music volume 0..100. All speech is sent to you; choose controls by intent, never assume a phrase was consumed. Run status to list participating Wolts. A switch ends this turn; do not reply afterwards.]
[Recording: record on/off via the same CLI. Off each call; on queues a spoken start notice and starts only after it finishes. Check recording.state; arming is not recording. Files remain private on this Mac, never automatically shared.]
[Unprompted speech: use the same CLI with say and text on stdin, from your routed session. It queues a short interruptible message only on this call, waits for caller silence, and is cancelled on switch/hangup or recognized interruption. Experimental opt-in noise filter: isolation on to try it on this call, isolation off to stop; off by default unless this profile explicitly opts into automatic startup; status shows warming/probing/on/recovering/bypass; only on means filtered audio. No model runs inside this bridge.]
[Call listening mode: {mode}. Use the same CLI with mode normal (AirPods/quiet) or mode car (WebRTC noise detector) when asked. Mode changes keep this turn, the call, Wolt and music; you may confirm with reply afterwards. These presets are experimental, not proven car tuning.]
'''
   if arrival:
    prompt=f'[Live-call handoff: the caller asked to speak with {route_name}. Introduce yourself in one short sentence; do not perform any other action. Reply using stdin: python3 {Path(__file__).parent}/voice.py --profile {P} reply {ident}. Your reply confirms this session is responsive. Do not use say or switch for this greeting.]'
   proc=None
   proc=await asyncio.create_subprocess_exec('woltspace','session','send',destination,'--key','linphone-'+ident,stdin=asyncio.subprocess.PIPE,stdout=asyncio.subprocess.DEVNULL,stderr=asyncio.subprocess.DEVNULL)
   try:await asyncio.wait_for(proc.communicate(prompt.encode()),15)
   finally:
    if proc.returncode is None:
     proc.kill();await proc.wait()
   if proc.returncode:raise RuntimeError('delivery')
   if not arrival:await cue('sent')
   if log:log.emit('turn_sent',turn=ident,wolt=route_name)
   print('Voice turn delivered; awaiting reply',flush=True)
   async def deliver(answer):
    if arrival:
     if not answer.strip():raise ValueError('empty_greeting')
     handoff_state['state']='connected';metadata('handoff_connected',wolt=route_name)
     await cue('connected');await outgoing.join()
     await say(f'Switched to {route_name}.')
    await say(answer,ROUTER.routes[route_name]['voice'])
    if arrival:handoff_state['state']='complete'
   for _ in range(max(1,int(HANDOFF_WAIT_SECONDS*2)) if arrival else 240):
    if generation!=ROUTER.generation:return
    future=ROUTER.pending.get(ident)
    if future and future.done():
     answer=future.result();await deliver(answer);break
    if reply.exists():
     answer=reply.read_text()[:1200];reply.unlink();await deliver(answer);break
    await asyncio.sleep(.5)
   else:
    if log:log.emit('turn_timeout',turn=ident)
    if arrival:handoff_state['state']='timeout'
    await cue('error');await say(f'{route_name} has not answered yet. The route is selected, but the connection is not confirmed.' if arrival else 'The reply is taking too long. Please try again in the chat.')
  except asyncio.CancelledError:
   if log:log.emit("turn_cancelled",turn=ident,generation_changed=generation!=ROUTER.generation)
   raise
  except Exception as e:
   if arrival:handoff_state['state']='failed'
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
 async def switching(name,handoff=None):
  nonlocal task,recognizer,route_generation,chunks,voiced,silence,speech_run,max_speech_run,user_speaking,interrupted
  async with switch_lock:
   if name not in ROUTER.routes:raise ValueError('Unknown Wolt; register its verified session first.')
   if name==ROUTER.selected and handoff_state['state'] not in ('announcing','connecting'):return
   if handoff is not None and (not isinstance(handoff,str) or not handoff.strip() or len(handoff)>300):raise ValueError('Handoff must be 1..300 characters')
   if recognizer:recognizer.cancel();await asyncio.gather(recognizer,return_exceptions=True)
   await interrupt('handoff')
   old=ROUTER.status().copy();destination=ROUTER.routes[name].copy()
   handoff_state.clear();handoff_state.update(state='announcing',target=name)
   async def sequence():
    nonlocal route_generation,chunks,voiced,silence,speech_run,max_speech_run,user_speaking,interrupted
    try:
     # The outgoing Wolt can supply its own handoff in the switch command.
     await say(handoff or f'Handing you to {name}.',old['voice'] if handoff else SYSTEM_VOICE)
     await say(f'Switching to {name}.')
     if ROUTER.routes.get(name)!=destination:raise ValueError('Destination changed during handoff')
     ROUTER.switch(name);route_generation=ROUTER.generation
     chunks=[];voiced=0;silence=0;speech_run=0;max_speech_run=0;user_speaking=False;interrupted=False
     handoff_state['state']='connecting';metadata('handoff_connecting',wolt=name)
     await turn(b'', '',arrival=True)
    except asyncio.CancelledError:
     handoff_state['state']='interrupted';metadata('handoff_interrupted',wolt=name);raise
    except Exception as e:
     handoff_state['state']='failed';metadata('handoff_failed',wolt=name,error=type(e).__name__)
     await cue('error');await say('The handoff failed. Please ask again.')
   task=asyncio.create_task(sequence())
 async def recognize(pcm):
  nonlocal task
  generation=ROUTER.generation;started=time.monotonic()
  try:
   await cue('captured')
   text=await asyncio.to_thread(transcribe,pcm)
   log.emit('asr_done',latency_ms=round((time.monotonic()-started)*1000),empty=not bool(text))
   if generation!=ROUTER.generation:return
   if not has_words(text):
    log.emit('noise_ignored',pending_preserved=bool(ROUTER.pending),nonempty=bool(text.strip()));return
   await interrupt('recognized_utterance')
   task=asyncio.create_task(turn(pcm,text))
  except asyncio.CancelledError:raise
  except Exception as e:log.emit('asr_error',error=type(e).__name__)
 try:
  head=await asyncio.wait_for(r.readexactly(3),5);kind,n=struct.unpack('!BH',head)
  if kind!=1 or n!=16:return
  selected_mode=incoming_mode(await r.readexactly(16),uuid.UUID(bytes=TOKEN),DETECTOR)
  if selected_mode is None or busy:return
  set_mode(selected_mode)
  from events import Events
  log=Events(P);EVENTS=log;log.emit("call_start",wolt=ROUTER.selected,mode=mode,detector=detector,vad_mode=3 if vad else None,rms_threshold=450 if vad is None else None,min_voiced=min_voiced,silence_threshold=1.1,duck_release_seconds=DUCK_RELEASE_SECONDS)
  busy=True;active=True;RADIO=radio;MODE_CONTROL=set_mode
  CALL_ID=uuid.uuid4().hex;ISOLATION=isolator;RECORDING=recorder;RECORD_CONTROL=recording_command;SWITCH_CONTROL=switching;HANDOFF_STATUS=handoff_state
  chimes=Chimes(ROUTER,CALL_ID,chime_say,log.emit);CHIMES=chimes
  if SETTINGS.get('isolation_default',False):
   try:isolator.enable()
   except Exception as e:isolator.fail(type(e).__name__)
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
    call_input_samples+=960;recorder.feed(data)
    raw_values=struct.unpack('<960h',data)
    if sum(v*v for v in raw_values)/960>450**2:raw_quiet_until=time.monotonic()+DUCK_RELEASE_SECONDS
    for data in isolator.feed(data):
     call_processed_samples+=960
     vals=struct.unpack('<'+'h'*(n//2),data);rms=math.sqrt(sum(x*x for x in vals)/max(1,len(vals)))
     rms_values.append(rms)
     if time.monotonic()-rms_at>=.5:
      log.emit("input_level",minimum=round(min(rms_values),1),average=round(sum(rms_values)/len(rms_values),1),maximum=round(max(rms_values),1),frames=len(rms_values),vad_frames=vad_frames,vad_positive=vad_positive,voiced_seconds=round(voiced,3),silence_seconds=round(silence,3))
      rms_values=[];rms_at=time.monotonic();vad_frames=0;vad_positive=0
     duration=n/96000
     is_speech=vad.is_speech(data,RATE) if vad else rms>450;vad_frames+=1;vad_positive+=int(is_speech)
     recorder.event('vad',processed_call_samples=call_processed_samples,positive=bool(is_speech),detector=detector,mode=mode,source='filtered' if isolator.state=='on' else 'raw',filter_buffer_ms=isolator.status()['buffer_ms'])
     if is_speech:mic_active=True;mic_quiet=0
     else:
      mic_quiet+=duration
      if mic_quiet>=DUCK_RELEASE_SECONDS:mic_active=False
     if is_speech:
      speech_run+=duration;max_speech_run=max(max_speech_run,speech_run)
      voiced+=duration;silence=0;chunks.append(data)
      if speech_run>=min_voiced and not interrupted:
       user_speaking=True;interrupted=True;await interrupt(cancel_turn=False)
     else:
      speech_run=0
      if chunks:silence+=duration;chunks.append(data)
      if silence>=DUCK_RELEASE_SECONDS:
       user_speaking=False;interrupted=False
     if chunks and (silence>1.1 or sum(map(len,chunks))>=MAX_UTTERANCE_SECONDS*RATE*2):
      log.emit('utterance_end',voiced_seconds=round(voiced,3),silence_seconds=round(silence,3))
      pcm=b''.join(chunks);chunks=[];user_speaking=False;interrupted=False
      if (voiced if vad is None else max_speech_run)>=min_voiced:
       if recognizer:recognizer.cancel();await asyncio.gather(recognizer,return_exceptions=True)
       recognizer=asyncio.create_task(recognize(pcm))
      voiced=0;silence=0;speech_run=0;max_speech_run=0
 except (asyncio.IncompleteReadError,ConnectionError,asyncio.TimeoutError) as e:
  end_reason=type(e).__name__
  print("Call input ended:",type(e).__name__,flush=True)
 finally:
  accepting=False
  if chimes:chimes.closed=True
  if active:RECORD_CONTROL=None;RECORDING=None;SWITCH_CONTROL=None;HANDOFF_STATUS=None
  await cancel_record_arm();await recorder.stop()
  await isolator.stop()
  if chimes:await chimes.close()
  if recognizer:recognizer.cancel();await asyncio.gather(recognizer,return_exceptions=True)
  if task:task.cancel();await asyncio.gather(task,return_exceptions=True)
  if watcher:watcher.cancel();await asyncio.gather(watcher,return_exceptions=True)
  if mixer:mixer.cancel();await asyncio.gather(mixer,return_exceptions=True)
  if active:
   await radio.stop();RADIO=None;busy=False;MODE_CONTROL=None;ISOLATION=None;CHIMES=None;CALL_ID=None
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
  if action=='switch':
   if SWITCH_CONTROL:await SWITCH_CONTROL(req['name'],req.get('handoff'))
   else:ROUTER.switch(req['name'])
  elif action=='add':
   if req['voice']==SYSTEM_VOICE:raise ValueError('That voice is reserved for the No-Hands line; choose a different Wolt voice')
   ROUTER.add(req['name'],req['session'],req['voice'])
  elif action=='reply':
   ROUTER.reply(req['turn'],req['text'])
   if EVENTS:EVENTS.emit('reply_accepted',turn=req['turn'])
  elif action=='music':
   if RADIO is None:raise ValueError('No active call')
   await RADIO.command(req['mode'],req.get('source'),req.get('volume'))
  elif action=='say':
   if CHIMES is None:raise ValueError('No active call')
   if HANDOFF_STATUS and HANDOFF_STATUS.get('state') in ('announcing','connecting','connected'):raise ValueError('Handoff in progress; use its greeting reply turn')
   CHIMES.submit(req.get('session'),req.get('call_id'),req.get('generation'),req.get('text'))
  elif action=='record':
   if RECORD_CONTROL is None:raise ValueError('No active call')
   if req.get('name')=='on':
    if req.get('session')!=ROUTER.status()['session'] or req.get('call_id')!=CALL_ID or req.get('generation')!=ROUTER.generation:raise ValueError('Only the current routed session/call may start recording')
   await RECORD_CONTROL(req.get('name'))
  elif action=='isolation':
   if ISOLATION is None:raise ValueError('No active call')
   if req.get('name')=='on':ISOLATION.enable()
   elif req.get('name')=='off':await ISOLATION.stop()
   else:raise ValueError('Isolation must be on or off')
  elif action=='mode':
   if MODE_CONTROL is None:raise ValueError('No active call')
   MODE_CONTROL(req['name'])
  elif action!='status':raise ValueError('Unknown action')
  result=ROUTER.status();result['active_call']=busy;result['music']=RADIO.status() if RADIO else None
  result['call_mode']=MODE_CONTROL() if MODE_CONTROL else None
  result['system_voice']=SYSTEM_VOICE
  result['handoff']=dict(HANDOFF_STATUS) if HANDOFF_STATUS is not None else None
  result['call_id']=CALL_ID;result['isolation']=ISOLATION.status() if ISOLATION else None
  result['recording']=RECORDING.status() if RECORDING else None
  result['isolation_experimental']=True
  result['isolation_default']=bool(SETTINGS.get('isolation_default',False))
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
