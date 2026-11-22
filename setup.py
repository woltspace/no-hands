"""Local voice prototype setup. No account login, installation, policy application or public sharing."""
import sys
import argparse,base64,ipaddress,json,os,re,secrets,shutil,socket,subprocess,time,uuid
from pathlib import Path
from http.server import HTTPServer,BaseHTTPRequestHandler
import xml.etree.ElementTree as ET
from call_modes import mode_token
ROOT=Path(__file__).resolve().parent
IMAGE='shellphone-voice:local'

def tail_ip(value):
 ip=ipaddress.ip_address(value)
 if ip.version!=4 or ip not in ipaddress.ip_network('100.64.0.0/10'):raise ValueError('Use the Tailscale IPv4 address (100.64.0.0/10).')
 return str(ip)

def profile_path(name):
 if not re.fullmatch(r'[a-z][a-z0-9-]{0,31}',name):raise ValueError('Profile name: lowercase letters, digits and hyphens, starting with a letter.')
 return ROOT/'runtime'/name

def xml_config(host,password):
 root=ET.Element('config',xmlns='http://www.linphone.org/xsds/lpconfig.xsd')
 sections={'sip':{'default_proxy':'0'},'misc':{'transient_provisioning':'1'},'auth_info_0':{'username':'voice-phone','passwd':password,'realm':'asterisk','domain':host},'proxy_0':{'reg_proxy':f'sip:{host};transport=tcp','reg_route':f'sip:{host};transport=tcp','reg_identity':f'"Shellphone voice" <sip:voice-phone@{host}>','reg_sendregister':'1','reg_expires':'600','publish':'0','push_notification_allowed':'0','remote_push_notification_allowed':'0'}}
 for name,entries in sections.items():
  sec=ET.SubElement(root,'section',name=name)
  for k,v in entries.items():ET.SubElement(sec,'entry',name=k,overwrite='true').text=v
 return ET.tostring(root,encoding='utf-8',xml_declaration=True)

def initialize(name,mac,phone,session,wolt="assistant"):
 if not re.fullmatch('[a-z][a-z0-9-]*',wolt):raise ValueError('Wolt name must be lowercase letters, digits and hyphens.')
 mac=tail_ip(mac);phone=tail_ip(phone)
 if mac==phone:raise ValueError('Device addresses must differ.')
 if not re.fullmatch(r'[a-zA-Z0-9_-]+',session):raise ValueError('Provide a verified Wolt session ID.')
 p=profile_path(name)
 if p.exists():raise ValueError('Profile exists. Choose another name; existing credentials are not overwritten.')
 os.umask(0o077);p.mkdir(parents=True,mode=0o700);(p/'config').mkdir();(p/'replies').mkdir()
 password=secrets.token_urlsafe(24);token=str(uuid.uuid4())
 settings={'name':name,'mac_ip':mac,'phone_ip':phone,'session':session,'wolt':wolt,'trial_seconds':3600,'container':'shellphone-voice-'+name}
 (p/'profile.json').write_text(json.dumps(settings,indent=2));(p/'bridge-token').write_text(token)
 (p/'credentials.json').write_text(json.dumps({'username':'voice-phone','password':password}))
 (p/'provisioning.xml').write_bytes(xml_config(mac,password))
 (p/'config/pjsip.conf').write_text(f'''[transport-tcp]
type=transport
protocol=tcp
bind=0.0.0.0:5060
external_media_address={mac}
external_signaling_address={mac}

[voice-phone]
type=endpoint
transport=transport-tcp
context=voice-test
media_address={mac}
disallow=all
allow=opus
auth=phone-auth
aors=voice-phone
direct_media=no
rtp_symmetric=yes
force_rport=yes
rewrite_contact=yes

[phone-auth]
type=auth
auth_type=userpass
username=voice-phone
password={password}

[voice-phone]
type=aor
max_contacts=1
remove_existing=yes
''')
 (p/'config/extensions.conf').write_text(f'''[voice-test]
exten => 100,1,Answer()
 same => n,Set(TIMEOUT(absolute)=300)
 same => n,Echo()
 same => n,Hangup()
exten => 101,1,Answer()
 same => n,Dial(AudioSocket/host.docker.internal:18974/{mode_token(token,'normal')}/c(slin48))
 same => n,Hangup()
exten => 102,1,Answer()
 same => n,Dial(AudioSocket/host.docker.internal:18974/{mode_token(token,'car')}/c(slin48))
 same => n,Hangup()
''')
 (p/'config/rtp.conf').write_text('[general]\nrtpstart=18000\nrtpend=18009\nicesupport=no\n')
 (p/'config/modules.conf').write_text('[modules]\nautoload=yes\nnoload=chan_sip.so\nnoload=chan_alsa.so\nnoload=chan_console.so\nnoload=res_hep.so\nnoload=res_hep_pjsip.so\nnoload=res_hep_rtcp.so\nnoload=res_pjsip_refer.so\nnoload=app_voicemail_imap.so\nnoload=app_voicemail_odbc.so\n')
 ports=[{'target':5060,'published':'5060','host_ip':mac,'protocol':'tcp'}]+[{'target':n,'published':str(n),'host_ip':mac,'protocol':'udp'} for n in range(18000,18010)]
 mounts=[{'type':'bind','source':str(p/'config'/n),'target':'/etc/asterisk/'+n,'read_only':True} for n in ['pjsip.conf','extensions.conf','rtp.conf','modules.conf']]
 (p/'compose.json').write_text(json.dumps({'services':{'voice':{'image':IMAGE,'container_name':settings['container'],'ports':ports,'volumes':mounts}}},indent=2))
 (p/'policy-draft.json').write_text(json.dumps({'grants':[{'src':[phone],'dst':[mac],'ip':['tcp:5060','udp:18000-18009','tcp:18975']}]},indent=2))
 return p

def load(name):
 p=profile_path(name);return p,json.loads((p/'profile.json').read_text())

def qr(name,minutes):
 import qrcode
 p,c=load(name);data=(p/'provisioning.xml').read_bytes();token=secrets.token_urlsafe(32)
 url=f"http://{c['mac_ip']}:18975/{token}"
 class Handler(BaseHTTPRequestHandler):
  def log_message(self,*args):pass
  def do_GET(self):
   if self.client_address[0]!=c['phone_ip'] or self.path!='/'+token:self.send_error(403);return
   self.send_response(200);self.send_header('Content-Type','application/xml');self.send_header('Cache-Control','no-store');self.send_header('Content-Length',str(len(data)));self.end_headers();self.wfile.write(data)
   print('Phone fetched settings.',flush=True)
 server=HTTPServer((c['mac_ip'],18975),Handler);server.timeout=1
 qrcode.make(url).save(p/'setup-qr.png');img=base64.b64encode((p/'setup-qr.png').read_bytes()).decode()
 (p/'setup-qr.html').write_text('<!doctype html><meta name="viewport" content="width=device-width"><title>Shellphone voice setup</title><style>body{font:20px system-ui;text-align:center;padding:30px}img{width:420px;max-width:90vw}</style><h1>Scan in Linphone</h1><p>Keep Tailscale connected on your iPhone.</p><img alt="Private setup QR" src="data:image/png;base64,'+img+'"><p>Replaces the first SIP account. Keep this QR private.</p><p>Once registered, dial 100 to test audio, 101 for normal mode, or 102 for car mode.</p>')
 print('Open this LOCAL page on your Mac:',p/'setup-qr.html',flush=True)
 print(f'QR service expires in {minutes} minutes. Ctrl-C stops it.',flush=True)
 try:
  end=time.monotonic()+minutes*60
  while time.monotonic()<end:server.handle_request()
 finally:
  server.server_close()
  for n in ['setup-qr.html','setup-qr.png']:(p/n).unlink(missing_ok=True)

def main():
 ap=argparse.ArgumentParser(description=__doc__);sub=ap.add_subparsers(dest='action',required=True)
 init=sub.add_parser('init');init.add_argument('--name',default='personal');init.add_argument('--mac-ip',required=True);init.add_argument('--phone-ip',required=True);init.add_argument('--session',required=True);init.add_argument('--wolt',required=True)
 for action in ['start','stop','status','bridge','qr']:
  x=sub.add_parser(action);x.add_argument('--name',default='personal')
  if action=='qr':x.add_argument('--minutes',type=int,choices=range(1,31),default=15)
 a=ap.parse_args()
 if a.action=='init':print('Created private inactive profile:',initialize(a.name,a.mac_ip,a.phone_ip,a.session,a.wolt));return
 p,c=load(a.name)
 if a.action=='qr':qr(a.name,a.minutes);return
 if a.action=='bridge':
  env=os.environ.copy();env['VOICE_PROFILE']=str(p);raise SystemExit(subprocess.call([sys.executable,str(ROOT/'bridge.py')],env=env))
 if a.action=='start':
  for proto,port in [(socket.SOCK_STREAM,5060),(socket.SOCK_STREAM,18974)]:
   with socket.socket(socket.AF_INET,proto) as sock:
    try:sock.bind((c['mac_ip'] if port==5060 else '127.0.0.1',port))
    except OSError:raise SystemExit(f'Port {port} unavailable: stop the prior trial or check the private address first.')
  command=['up','-d']
 elif a.action=='stop':command=['stop']
 else:command=['ps']
 raise SystemExit(subprocess.call(['docker','compose','-f',str(p/'compose.json'),*command]))
if __name__=='__main__':main()
