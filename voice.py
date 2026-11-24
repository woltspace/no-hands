"""Local CLI: status, add, switch, mode, reply. Reply text is read from stdin."""
import argparse,json,socket,sys,os
from pathlib import Path
from routing import control_path

def call(profile,request):
 with socket.socket(socket.AF_UNIX) as sock:
  sock.settimeout(5);sock.connect(str(control_path(profile)))
  sock.sendall(json.dumps(request).encode()+b'\n')
  data=b''
  while not data.endswith(b'\n'):
   part=sock.recv(4096)
   if not part:raise RuntimeError('Control connection closed')
   data+=part
  result=json.loads(data)
  if 'error' in result:raise RuntimeError(result['error'])
  return result

def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--profile',required=True)
 s=p.add_subparsers(dest='action',required=True);s.add_parser('status')
 a=s.add_parser('add');a.add_argument('name');a.add_argument('session');a.add_argument('--voice',required=True)
 a=s.add_parser('switch');a.add_argument('name');a.add_argument('--handoff',help='Short outgoing handoff sentence, spoken before switching')
 a=s.add_parser('mode');a.add_argument('name',choices=['normal','car'])
 a=s.add_parser('music');a.add_argument('mode',choices=['play','off','on','next','volume']);a.add_argument('value',nargs='?')
 a=s.add_parser('record');a.add_argument('name',choices=['on','off'])
 a=s.add_parser('isolation',help='experimental opt-in noise filter',description='Experimental noise filter, off by default. Use isolation on to try it on this call; isolation off stops it.');a.add_argument('name',choices=['on','off'])
 s.add_parser('say')
 a=s.add_parser('reply');a.add_argument('turn')
 a=p.parse_args();request=vars(a).copy();profile=request.pop('profile')
 if a.action=='music':
  value=request.pop('value')
  if a.mode=='play':request['source']=value
  elif a.mode=='volume':request['volume']=float(value) if value is not None else None
 if a.action=='reply':request['text']=sys.stdin.read(1201)
 try:
  if a.action in ('say','record'):
   state=call(profile,{'action':'status'})
   request.update(session=os.environ.get('WOLTSPACE_WOLT_SESSION'),call_id=state.get('call_id'),generation=state.get('generation'))
   if a.action=='say':request['text']=sys.stdin.read(601)
  print(json.dumps(call(profile,request)))
 except (OSError,RuntimeError) as e:p.exit(1,str(e)+'\n')
if __name__=='__main__':main()
