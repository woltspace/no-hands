"""Private local Woltspace app: onboarding and ownership of one phone stack."""
import argparse
import fcntl
import json
import os
import re
import secrets
import shutil
import signal
import socket
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

import setup
from speech_provider import DEFAULTS, SpeechProvider, app_key
from voice import call

ROOT = Path(__file__).resolve().parent


def run(args, timeout=12):
    return subprocess.run(args, capture_output=True, timeout=timeout, text=True, start_new_session=True)


def private_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temp = path.with_suffix('.tmp')
    with os.fdopen(os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600), 'w') as file:
        json.dump(value, file, indent=2)
    temp.replace(path)


def configure(args):
    # Fresh profiles only: never mutate a live or another installation's profile.
    speech = {**DEFAULTS[args.provider], 'provider': args.provider}
    for key in ('voice', 'stt_model', 'tts_model', 'base_url'):
        value = getattr(args, key, None)
        if value is not None:
            speech[key] = value
    SpeechProvider({'speech': speech})  # Validate before creating private files.
    if not re.fullmatch('[a-z][a-z0-9_-]*', speech['voice']):
        raise ValueError('Invalid voice name')
    p = setup.initialize(args.name, args.mac_ip, args.phone_ip, args.session, args.wolt)
    settings = json.loads((p / 'profile.json').read_text())
    settings.update(speech=speech, trial_seconds=None)
    private_json(p / 'profile.json', settings)
    private_json(p / 'routes.json', {args.wolt: {'session': args.session, 'voice': speech['voice']}})
    private_json(ROOT / 'runtime/app.json', {'profile': args.name})
    manifest = json.loads((ROOT / 'woltspace.json').read_text())
    manifest['keeper'] = args.wolt
    (ROOT / 'woltspace.json').write_text(json.dumps(manifest, indent=2) + '\n')
    print('Configured. Start No-hands from your lodge, then open the app on this Mac.')


class Manager:
    def __init__(self, root=ROOT):
        self.root = Path(root)
        self.bridge = None
        self.qr = None
        self.phone_owned = False
        self.voice_verified = False
        self.error = ''
        self.operation = ''
        self.lock = threading.RLock()
        self.log = None

    def profile(self):
        config = json.loads((self.root / 'runtime/app.json').read_text())
        name = config['profile']
        if not re.fullmatch('[a-z][a-z0-9-]{0,31}', name):
            raise ValueError('Invalid profile name')
        p = self.root / 'runtime' / name
        return p, json.loads((p / 'profile.json').read_text())

    def control(self):
        try:
            p, _ = self.profile()
            return call(p, {'action': 'status'})
        except (OSError, ValueError, RuntimeError):
            return {}

    def compose(self, *args):
        p, _ = self.profile()
        return run(['docker', 'compose', '-f', str(p / 'compose.json'), *args], timeout=45)

    def prerequisites(self):
        checks = []
        def add(name, ok, help):
            checks.append({'name': name, 'ok': bool(ok), 'help': help})
        add('Audio tools', shutil.which('ffmpeg'), 'Ask your Wolt to install ffmpeg.')
        add('Woltspace', shutil.which('woltspace'), 'Ask your Wolt to check its command-line connection.')
        docker = False
        try:
            docker = run(['docker', 'info', '--format', '{{.ServerVersion}}']).returncode == 0
        except (OSError, subprocess.TimeoutExpired):
            pass
        add('Docker', docker, 'Open Docker Desktop and wait for it to start.')
        try:
            p, settings = self.profile()
        except (OSError, ValueError, KeyError):
            add('Your Wolt', False, 'Ask your Wolt to read AGENTS.md and finish configuring this app.')
            return checks
        network = False
        try:
            with socket.socket() as sock:
                sock.bind((settings['mac_ip'], 0))
            network = True
        except OSError:
            pass
        add('Private connection', network, 'Connect Tailscale on your Mac.')
        # This verifies the exact registered ID, not merely that woltspace is installed.
        alive = False
        try:
            result = run(['woltspace', 'session', 'list', '--alive'])
            alive = result.returncode == 0 and re.search(r'(?<![A-Za-z0-9_-])' + re.escape(settings['session']) + r'(?![A-Za-z0-9_-])', result.stdout) is not None
        except (OSError, subprocess.TimeoutExpired):
            pass
        add('Your Wolt', alive, 'Ask your Wolt to start or register its current session before calling.')
        provider = settings.get('speech', {}).get('provider', 'local')
        add('Voice configuration', provider != 'openai' or bool(app_key(self.root)), 'Add your OpenAI API key using the private key command in the Wolt guide.')
        return checks

    def status(self):
        # Do not reveal credentials, paths, phone addresses, session IDs or transcripts.
        try:
            p, settings = self.profile()
            configured = True
        except (OSError, ValueError, KeyError):
            configured = False
            settings = {}
        running = self.bridge is not None and self.bridge.poll() is None
        state = self.control() if configured and running else {}
        phone = False
        if running:
            try:
                result = run(['docker', 'exec', settings['container'], 'asterisk', '-rx', 'core show uptime'])
                phone = result.returncode == 0 and 'System uptime' in result.stdout
            except (OSError, subprocess.TimeoutExpired):
                pass
        if self.bridge is not None and not running:
            self.error = 'The voice bridge stopped. Stop the phone, then start it again. Ask your Wolt to inspect the local service log.'
        return {'configured': configured, 'running': running, 'ready': bool(running and state and phone and self.voice_verified),
                'active_call': state.get('active_call', False), 'wolt': state.get('wolt', settings.get('wolt', 'your Wolt')),
                'provider': settings.get('speech', {}).get('provider', 'local'), 'voice_verified': self.voice_verified,
                'qr': self.qr is not None and self.qr.poll() is None,
                'operation': self.operation, 'error': self.error}

    def start(self):
        if self.bridge and self.bridge.poll() is None:
            return
        missing = [c for c in self.prerequisites() if not c['ok']]
        if missing:
            raise ValueError(missing[0]['help'])
        p, settings = self.profile()
        if self.control():
            raise ValueError('This profile already has a bridge. Ask your Wolt to resolve the existing instance.')
        # Refuse an existing container even if stopped: no adopting an unrelated stack.
        existing = run(['docker', 'inspect', settings['container']])
        if existing.returncode == 0:
            raise ValueError('This profile already has a phone container. Ask your Wolt to stop the old stack before using the app.')
        self.operation = 'Checking your voice…'
        self.voice_verified = False
        SpeechProvider(settings, self.root).probe()
        self.voice_verified = True
        self.operation = 'Starting your phone…'
        self.phone_owned = True
        try:
            result = run([sys.executable, str(self.root / 'setup.py'), 'start', '--name', settings['name']], timeout=60)
            if result.returncode:
                raise ValueError('Phone server could not start. Ask your Wolt to check Docker and the private connection.')
            self.log = open(p / 'service.log', 'ab', buffering=0)
            os.chmod(p / 'service.log', 0o600)
            env = os.environ.copy()
            env['VOICE_PROFILE'] = str(p)
            self.bridge = subprocess.Popen([sys.executable, str(self.root / 'bridge.py')], env=env,
                                           stdout=self.log, stderr=self.log, start_new_session=True)
            deadline = time.monotonic() + 20
            while time.monotonic() < deadline:
                if self.bridge.poll() is not None:
                    break
                if self.control():
                    return
                time.sleep(.2)
            raise ValueError('Voice bridge did not start. Ask your Wolt to inspect the local service log.')
        except Exception:
            self.stop(force=True)
            raise

    @staticmethod
    def terminate(process):
        if process and process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=8)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=3)

    def stop_qr(self):
        self.terminate(self.qr)
        self.qr = None
        try:
            p, _ = self.profile()
            for name in ('setup-qr.png', 'setup-qr.html'):
                (p / name).unlink(missing_ok=True)
        except (OSError, ValueError):
            pass

    def stop(self, force=False):
        if not force and self.control().get('active_call'):
            raise ValueError('A call is active. Hang up before stopping the phone.')
        self.stop_qr()
        self.terminate(self.bridge)
        self.bridge = None
        if self.log:
            self.log.close()
            self.log = None
        if self.phone_owned:
            result = self.compose('down')
            if result.returncode:
                raise ValueError('Docker did not stop the phone server. Ask your Wolt to stop this profile manually.')
            self.phone_owned = False
        self.voice_verified = False

    def show_qr(self):
        if not self.status()['ready']:
            raise ValueError('Start your phone successfully before creating a QR.')
        self.stop_qr()
        p, settings = self.profile()
        self.qr = subprocess.Popen([sys.executable, str(self.root / 'setup.py'), 'qr', '--name', settings['name'], '--minutes', '15'],
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
        deadline = time.monotonic() + 8
        while time.monotonic() < deadline:
            if self.qr.poll() is not None:
                raise ValueError('Could not start QR provisioning. Ask your Wolt to check the private connection and provisioning port.')
            if (p / 'setup-qr.png').exists():
                return
            time.sleep(.1)
        self.stop_qr()
        raise ValueError('QR generation timed out.')

    def action(self, name):
        with self.lock:
            if self.operation:
                raise ValueError('Setup is already working. Please wait.')
            if name not in ('start', 'stop', 'qr', 'hide-qr'):
                raise ValueError('Unknown action')
            self.operation = 'Working…'
            self.error = ''
        def worker():
            try:
                {'start': self.start, 'stop': self.stop, 'qr': self.show_qr, 'hide-qr': self.stop_qr}[name]()
            except (ValueError, RuntimeError) as error:
                self.error = str(error)
            except Exception:
                self.error = 'Setup could not finish. Ask your Wolt to check the local setup.'
            finally:
                self.operation = ''
        thread = threading.Thread(target=worker, daemon=False)
        thread.start()
        return thread


def handler(manager):
    csrf = secrets.token_urlsafe(32)
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def allowed(self):
            host = self.headers.get('Host', '')
            return host in self.server.allowed_hosts

        def respond(self, code, body, kind='application/json'):
            if not isinstance(body, bytes):
                body = json.dumps(body).encode()
            self.send_response(code)
            self.send_header('Content-Type', kind)
            self.send_header('Content-Length', str(len(body)))
            self.send_header('Cache-Control', 'no-store')
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.send_header('Referrer-Policy', 'no-referrer')
            self.send_header('Content-Security-Policy', "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self'; connect-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'self' http://localhost:7777 http://127.0.0.1:7777 http://*.localhost:7777")
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            if not self.allowed():
                return self.respond(403, {'error': 'Open No-hands locally on your Mac.'})
            try:
                if self.path == '/api/status':
                    return self.respond(200, {**manager.status(), 'csrf': csrf})
                if self.path == '/api/checks':
                    return self.respond(200, {'checks': manager.prerequisites()})
                if self.path == '/qr.png':
                    if not manager.qr or manager.qr.poll() is not None:
                        return self.respond(404, {'error': 'QR expired. Create a new one.'})
                    p, _ = manager.profile()
                    return self.respond(200, (p / 'setup-qr.png').read_bytes(), 'image/png')
                assets = {'/': ('index.html', 'text/html; charset=utf-8'), '/app.js': ('app.js', 'text/javascript'), '/style.css': ('style.css', 'text/css')}
                if self.path in assets:
                    filename, kind = assets[self.path]
                    return self.respond(200, (manager.root / 'web' / filename).read_bytes(), kind)
                self.respond(404, {'error': 'Not found'})
            except Exception:
                self.respond(503, {'error': 'Setup status is unavailable. Ask your Wolt to check the app.'})

        def do_POST(self):
            # An unguessable header + same-origin request prevents drive-by starts/paid calls.
            origin = self.headers.get('Origin', '')
            expected = 'http://' + self.headers.get('Host', '')
            if not self.allowed() or origin != expected or not secrets.compare_digest(self.headers.get('X-No-Hands', ''), csrf):
                return self.respond(403, {'error': 'Reload the app on this Mac and try again.'})
            if self.headers.get('Content-Length', '0') != '0':
                return self.respond(400, {'error': 'No request body expected.'})
            try:
                manager.action(self.path.removeprefix('/api/'))
                self.respond(202, {'ok': True})
            except ValueError as error:
                self.respond(409, {'error': str(error)})
    return Handler


def serve(port):
    os.umask(0o077)
    (ROOT / 'runtime').mkdir(exist_ok=True, mode=0o700)
    lock = (ROOT / 'runtime/app.lock').open('a')
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    manager = Manager()
    server = ThreadingHTTPServer(('127.0.0.1', port), handler(manager))
    server.allowed_hosts = {f'localhost:{port}', f'127.0.0.1:{port}', 'no-hands.localhost:7777'}
    def shutdown(*_):
        threading.Thread(target=server.shutdown, daemon=True).start()
    signal.signal(signal.SIGTERM, shutdown)
    signal.signal(signal.SIGINT, shutdown)
    print(f'No-hands setup: http://localhost:{port}', flush=True)
    try:
        server.serve_forever()
    finally:
        # Finish an in-flight setup operation before stopping only our own children.
        while manager.operation:
            time.sleep(.1)
        manager.stop(force=True)
        server.server_close()
        lock.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    config = sub.add_parser('configure')
    config.add_argument('--name', default='personal')
    for name in ('mac-ip', 'phone-ip', 'session', 'wolt'):
        config.add_argument('--' + name, required=True)
    config.add_argument('--provider', choices=DEFAULTS, required=True)
    for name in ('voice', 'stt-model', 'tts-model', 'base-url'):
        config.add_argument('--' + name)
    server = sub.add_parser('serve')
    server.add_argument('--port', type=int, default=int(os.environ.get('PORT', 4091)))
    sub.add_parser('key', help='Store an app-specific OpenAI key using a hidden prompt (never an argument).')
    sub.add_parser('check', help='Print non-secret prerequisite checks.')
    args = parser.parse_args()
    if args.command == 'configure':
        configure(args)
    elif args.command == 'serve':
        serve(args.port)
    elif args.command == 'check':
        print(json.dumps(Manager().prerequisites(), indent=2))
    else:
        import getpass
        key = getpass.getpass('OpenAI API key (hidden): ')
        if not key or '\n' in key or '\r' in key or not key.isascii():
            parser.error('Invalid key')
        path = ROOT / '.env'
        lines = path.read_text().splitlines() if path.exists() else []
        lines = [line for line in lines if not line.startswith('OPENAI_API_KEY=')]
        if path.exists():
            path.chmod(0o600)
        with os.fdopen(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600), 'w') as file:
            file.write('\n'.join([*lines, 'OPENAI_API_KEY=' + key]) + '\n')
        path.chmod(0o600)
        print('Key saved privately. It is never returned to the browser.')


if __name__ == '__main__':
    main()
