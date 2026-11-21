import json
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch
from http.server import ThreadingHTTPServer

import app
from speech_provider import SpeechProvider


class ProviderTests(unittest.TestCase):
    def test_openai_contract_and_local_separation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / '.env').write_text('OPENAI_API_KEY=test-only-key\n')
            provider = SpeechProvider({'speech': {'provider': 'openai'}}, root)
            response = Mock()
            response.__enter__ = Mock(return_value=response)
            response.__exit__ = Mock(return_value=False)
            response.read.return_value = b'wave'
            provider.opener.open = Mock(return_value=response)
            self.assertEqual(provider.speech('hello'), b'wave')
            request = provider.opener.open.call_args.args[0]
            self.assertEqual(request.full_url, 'https://api.openai.com/v1/audio/speech')
            self.assertEqual(request.get_header('Authorization'), 'Bearer test-only-key')
            self.assertEqual(json.loads(request.data), {'model': 'gpt-4o-mini-tts', 'input': 'hello', 'voice': 'coral', 'response_format': 'wav'})
            response.read.return_value = b'{"text":"hello"}'
            self.assertEqual(provider.transcribe(b'RIFF-test-wav'), 'hello')
            request = provider.opener.open.call_args.args[0]
            self.assertIn(b'gpt-transcribe', request.data)
            self.assertIn(b'RIFF-test-wav', request.data)
            local = SpeechProvider({}, root)
            local.opener.open = provider.opener.open
            local.speech('local')
            request = local.opener.open.call_args.args[0]
            self.assertIsNone(request.get_header('Authorization'))
            self.assertNotIn('model', json.loads(request.data))

    def test_no_inherited_key_or_error_body(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict('os.environ', {'OPENAI_API_KEY': 'lodge-secret'}):
            provider = SpeechProvider({'speech': {'provider': 'openai'}}, tmp)
            with self.assertRaisesRegex(ValueError, 'private .env'):
                provider.speech('private')
            (Path(tmp) / '.env').write_text('OPENAI_API_KEY=app-secret')
            provider.opener.open = Mock(side_effect=urllib.error.HTTPError('url', 401, 'secret-body', {}, None))
            with self.assertRaisesRegex(RuntimeError, 'HTTP 401') as error:
                provider.speech('private')
            self.assertNotIn('secret', str(error.exception))

    def test_endpoint_validation(self):
        for url in ['https://remote.example', 'http://localhost@evil.example', 'http://localhost/?x=1']:
            with self.assertRaises(ValueError):
                SpeechProvider({'speech': {'provider': 'local', 'base_url': url}})
        provider = SpeechProvider({'speech': {'provider': 'openai', 'base_url': 'http://evil.example'}})
        self.assertEqual(provider.config['base_url'], 'https://api.openai.com')


class LifecycleTests(unittest.TestCase):
    def manager(self):
        manager = app.Manager()
        manager.profile = Mock(return_value=(Path('/not-used'), {'name': 'test', 'container': 'test-container'}))
        return manager

    def test_stop_refuses_active_call(self):
        manager = self.manager()
        manager.control = Mock(return_value={'active_call': True})
        manager.terminate = Mock()
        with self.assertRaisesRegex(ValueError, 'Hang up'):
            manager.stop()
        manager.terminate.assert_not_called()

    def test_only_owned_children_and_container_stopped(self):
        manager = self.manager()
        manager.control = Mock(return_value={})
        manager.stop_qr = Mock()
        manager.terminate = Mock()
        manager.compose = Mock(return_value=SimpleNamespace(returncode=0))
        manager.bridge = object()
        manager.stop()
        manager.compose.assert_not_called()
        manager.phone_owned = True
        manager.stop()
        manager.compose.assert_called_once_with('down')
        self.assertFalse(manager.phone_owned)

    def test_existing_container_not_adopted(self):
        manager = self.manager()
        manager.prerequisites = Mock(return_value=[{'ok': True}])
        manager.control = Mock(return_value={})
        with patch('app.run', return_value=SimpleNamespace(returncode=0)), patch('app.SpeechProvider') as speech:
            with self.assertRaisesRegex(ValueError, 'already has a phone container'):
                manager.start()
            speech.assert_not_called()

    def test_probe_failure_does_not_start_phone(self):
        manager = self.manager()
        manager.prerequisites = Mock(return_value=[{'ok': True}])
        manager.control = Mock(return_value={})
        with patch('app.run', return_value=SimpleNamespace(returncode=1)) as run, patch('app.SpeechProvider') as speech:
            speech.return_value.probe.side_effect = RuntimeError('provider failed')
            with self.assertRaises(RuntimeError):
                manager.start()
            self.assertEqual(run.call_count, 1)  # inspect only, no compose/start
            self.assertFalse(manager.phone_owned)

    def test_bridge_spawn_failure_rolls_back_owned_stack(self):
        with tempfile.TemporaryDirectory() as tmp:
            manager = self.manager()
            manager.profile.return_value = (Path(tmp), {'name': 'test', 'container': 'test-container'})
            manager.prerequisites = Mock(return_value=[{'ok': True}])
            manager.control = Mock(return_value={})
            manager.compose = Mock(return_value=SimpleNamespace(returncode=0))
            with patch('app.run', side_effect=[SimpleNamespace(returncode=1), SimpleNamespace(returncode=0)]), patch('app.SpeechProvider'), patch('app.subprocess.Popen', side_effect=OSError('spawn failed')):
                with self.assertRaises(OSError):
                    manager.start()
            manager.compose.assert_called_once_with('down')
            self.assertFalse(manager.phone_owned)
            self.assertIsNone(manager.log)

    def test_fresh_configuration_selects_provider_and_route(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'woltspace.json').write_text('{"keeper":"placeholder"}')
            args = SimpleNamespace(name='test', mac_ip='100.64.0.1', phone_ip='100.64.0.2', session='friend-live', wolt='friend', provider='openai', voice=None, stt_model=None, tts_model=None, base_url=None)
            with patch('app.ROOT', root), patch('setup.ROOT', root):
                app.configure(args)
            profile = json.loads((root / 'runtime/test/profile.json').read_text())
            self.assertEqual(profile['speech']['provider'], 'openai')
            self.assertIsNone(profile['trial_seconds'])
            self.assertEqual(json.loads((root / 'runtime/test/routes.json').read_text())['friend']['voice'], 'coral')
            self.assertEqual(json.loads((root / 'woltspace.json').read_text())['keeper'], 'friend')
            self.assertFalse((root / 'runtime/test/profile.json').stat().st_mode & 0o077)

    def test_start_and_stop_own_stack_together(self):
        with tempfile.TemporaryDirectory() as tmp:
            manager = self.manager()
            manager.profile.return_value = (Path(tmp), {'name': 'test', 'container': 'test-container'})
            manager.prerequisites = Mock(return_value=[{'ok': True}])
            manager.control = Mock(side_effect=[{}, {'wolt': 'friend'}, {}])
            manager.compose = Mock(return_value=SimpleNamespace(returncode=0))
            process = Mock()
            process.poll.return_value = None
            with patch('app.run', side_effect=[SimpleNamespace(returncode=1), SimpleNamespace(returncode=0)]), patch('app.SpeechProvider'), patch('app.subprocess.Popen', return_value=process):
                manager.start()
            self.assertTrue(manager.phone_owned)
            self.assertTrue(manager.voice_verified)
            manager.stop()
            process.terminate.assert_called_once()
            manager.compose.assert_called_once_with('down')


class QRTests(unittest.TestCase):
    def test_provisioning_token_and_expiry(self):
        import socket
        import time
        import qrcode
        import setup
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'provisioning.xml').write_bytes(b'<config/>')
            captured = []
            original = qrcode.make
            def make(url):
                captured.append(url)
                return original(url)
            with patch('setup.load', return_value=(root, {'mac_ip': '127.0.0.1', 'phone_ip': '127.0.0.1'})), patch('qrcode.make', side_effect=make):
                worker = threading.Thread(target=setup.qr, args=('test', .02))
                worker.start()
                try:
                    deadline = time.monotonic() + 3
                    while not (root / 'setup-qr.png').exists() and time.monotonic() < deadline:
                        time.sleep(.02)
                    self.assertTrue((root / 'setup-qr.png').exists())
                    with urllib.request.urlopen(captured[0]) as response:
                        self.assertEqual(response.read(), b'<config/>')
                        self.assertEqual(response.headers['Cache-Control'], 'no-store')
                    with self.assertRaises(urllib.error.HTTPError) as error:
                        urllib.request.urlopen('http://127.0.0.1:18975/wrong-token')
                    self.assertEqual(error.exception.code, 403)
                finally:
                    worker.join(timeout=5)
                self.assertFalse(worker.is_alive())
            self.assertFalse((root / 'setup-qr.png').exists())
            self.assertFalse((root / 'setup-qr.html').exists())


class HTTPTests(unittest.TestCase):
    def setUp(self):
        self.manager = Mock(root=app.ROOT)
        self.manager.status.return_value = {'configured': False}
        self.manager.prerequisites.return_value = []
        self.manager.qr = None
        self.server = ThreadingHTTPServer(('127.0.0.1', 0), app.handler(self.manager))
        self.host = '127.0.0.1:' + str(self.server.server_port)
        self.server.allowed_hosts = {self.host}
        self.url = 'http://' + self.host
        self.thread = threading.Thread(target=self.server.serve_forever)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()

    def test_csrf_and_host_guards(self):
        with urllib.request.urlopen(self.url + '/api/status') as r:
            token = json.load(r)['csrf']
            self.assertEqual(r.headers['Cache-Control'], 'no-store')
        for headers in [{}, {'Origin': 'http://evil.example', 'X-No-Hands': token}, {'Host': 'evil.example'}]:
            with self.assertRaises(urllib.error.HTTPError) as error:
                urllib.request.urlopen(urllib.request.Request(self.url + '/api/start', data=b'', headers=headers))
            self.assertEqual(error.exception.code, 403)
        self.manager.action.assert_not_called()
        with urllib.request.urlopen(urllib.request.Request(self.url + '/api/start', data=b'', headers={'Origin': self.url, 'X-No-Hands': token})) as r:
            self.assertEqual(r.status, 202)
        self.manager.action.assert_called_once_with('start')

    def test_no_static_secret_or_path_traversal(self):
        for path in ['/.env', '/runtime/personal/profile.json', '/../.env', '/qr.png']:
            with self.assertRaises(urllib.error.HTTPError) as error:
                urllib.request.urlopen(self.url + path)
            self.assertEqual(error.exception.code, 404)
        with urllib.request.urlopen(self.url) as r:
            self.assertIn(b'Call your Wolt', r.read())
            self.assertIn("script-src 'self'", r.headers['Content-Security-Policy'])


if __name__ == '__main__':
    unittest.main()
