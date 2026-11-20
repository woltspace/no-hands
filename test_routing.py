import asyncio,tempfile,unittest
from pathlib import Path
from routing import Router
from voice import call
import json

class RoutingTest(unittest.IsolatedAsyncioTestCase):
 async def test_switch_fences_old_reply_and_persists_members(self):
  with tempfile.TemporaryDirectory() as d:
   r=Router(d,'astre-session');r.add('softie','softie-session')
   old=asyncio.get_running_loop().create_future();r.pending['old']=old
   r.switch('softie')
   self.assertTrue(old.cancelled())
   with self.assertRaises(ValueError):r.reply('old','late')
   new=asyncio.get_running_loop().create_future();r.pending['new']=new
   r.reply('new','hello');self.assertEqual(new.result(),'hello')
   with self.assertRaises(ValueError):r.reply('new','duplicate')
   before=r.status()
   with self.assertRaises(ValueError):r.switch('missing')
   self.assertEqual(before,r.status())
   self.assertEqual(Router(d,'ignored').routes['softie'],'softie-session')

if __name__=='__main__':unittest.main()
