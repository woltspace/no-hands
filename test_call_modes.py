import tempfile
from pathlib import Path
import unittest
import uuid
from unittest.mock import patch
from call_modes import incoming_mode,mode_token
import setup

class Modes(unittest.TestCase):
 def test_private_dialplan_selects_distinct_modes(self):
  with tempfile.TemporaryDirectory() as directory,patch.object(setup,'ROOT',Path(directory)):
   profile=setup.initialize('test','100.64.0.1','100.64.0.2','session')
   secret=uuid.UUID((profile/'bridge-token').read_text())
   text=(profile/'config/extensions.conf').read_text()
   self.assertIn('exten => 100,1,Answer()',text)
   for number,name in ((101,'normal'),(102,'car')):
    section=text.split(f'exten => {number},1,Answer()')[1].split('exten =>')[0]
    self.assertIn(str(mode_token(secret,name)),section)
    self.assertEqual(incoming_mode(mode_token(secret,name).bytes,secret,'webrtcvad'),name)
   self.assertNotEqual(mode_token(secret,'car'),mode_token(secret,'normal'))

 def test_legacy_token_preserves_setting_and_foreign_tokens_fail(self):
  secret=uuid.uuid4()
  self.assertEqual(incoming_mode(secret.bytes,secret,'rms'),'normal')
  self.assertEqual(incoming_mode(secret.bytes,secret,'webrtcvad'),'car')
  self.assertIsNone(incoming_mode(uuid.uuid4().bytes,secret,'webrtcvad'))
  self.assertIsNone(incoming_mode(mode_token(uuid.uuid4(),'car').bytes,secret,'webrtcvad'))
  with self.assertRaises(ValueError):mode_token(secret,'unknown')

if __name__=='__main__':unittest.main()
