import unittest,tempfile,json,os,subprocess,sys,xml.etree.ElementTree as ET
from pathlib import Path
import setup
class SetupTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory(dir=Path(__file__).parent);self.old=setup.ROOT;setup.ROOT=Path(self.tmp.name)
 def tearDown(self):setup.ROOT=self.old;self.tmp.cleanup()
 def test_profile_contract(self):
  p=setup.initialize('test','100.64.0.1','100.64.0.2','test-session','helper')
  self.assertEqual(json.loads((p/'profile.json').read_text())['wolt'],'helper')
  cfg=(p/'config/pjsip.conf').read_text()
  self.assertIn('media_address=100.64.0.1',cfg);self.assertIn('protocol=tcp',cfg);self.assertIn('allow=opus',cfg)
  xml=ET.fromstring((p/'provisioning.xml').read_bytes());ns={'l':'http://www.linphone.org/xsds/lpconfig.xsd'}
  values={e.attrib['name']:e.text for e in xml.findall('.//l:entry',ns)}
  self.assertIn('transport=tcp',values['reg_proxy']);self.assertEqual(values['push_notification_allowed'],'0')
  compose=json.loads((p/'compose.json').read_text());ports=compose['services']['voice']['ports']
  self.assertTrue(all(x['host_ip']=='100.64.0.1' for x in ports));self.assertEqual(len(ports),11)
  self.assertFalse((p/'credentials.json').stat().st_mode&0o077)
  with self.assertRaises(ValueError):setup.initialize('test','100.64.0.1','100.64.0.2','test-session')
  result=subprocess.run(['docker','compose','-f',str(p/'compose.json'),'config','--quiet'],capture_output=True)
  self.assertEqual(result.returncode,0)
 def test_bad_input(self):
  for ip in ['8.8.8.8','192.168.1.1','100.128.0.1','::1']:
   with self.assertRaises(ValueError):setup.tail_ip(ip)
  for name in ['../escape','a/b','UPPER','x;echo']:
   with self.assertRaises(ValueError):setup.profile_path(name)
  with self.assertRaises(ValueError):setup.initialize('test','100.64.0.1','100.64.0.1','session')
 def test_xml_escaping(self):ET.fromstring(setup.xml_config('100.64.0.1','test<&"value'))
if __name__=='__main__':unittest.main()
