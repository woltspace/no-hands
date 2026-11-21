"""Explicit local/OpenAI speech adapters. No global credential discovery."""
import io
import json
import os
import urllib.error
import urllib.request
import uuid
import wave
from pathlib import Path

DEFAULTS = {
    'local': {'base_url': 'http://127.0.0.1:4077', 'stt_model': 'parakeet', 'tts_model': '', 'voice': 'alba'},
    'openai': {'base_url': 'https://api.openai.com', 'stt_model': 'gpt-transcribe', 'tts_model': 'gpt-4o-mini-tts', 'voice': 'coral'},
}


def app_key(root):
    # Deliberately read only this app's .env, not inherited lodge credentials.
    path = Path(root) / '.env'
    if not path.exists():
        return ''
    for line in path.read_text().splitlines():
        key, sep, value = line.strip().partition('=')
        if sep and key == 'OPENAI_API_KEY':
            return value.strip().strip('\"\'')
    return ''


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


class SpeechProvider:
    def __init__(self, settings, root=None):
        config = settings.get('speech', {})
        self.kind = config.get('provider', 'local')
        if self.kind not in DEFAULTS:
            raise ValueError('Choose local or openai speech.')
        self.config = {**DEFAULTS[self.kind], **config}
        # Keys must never be sent to a configurable remote endpoint.
        if self.kind == 'openai':
            self.config['base_url'] = 'https://api.openai.com'
        else:
            from urllib.parse import urlsplit
            url = urlsplit(self.config['base_url'])
            if url.scheme != 'http' or url.hostname not in ('localhost', '127.0.0.1') or url.username or url.password or url.path not in ('', '/') or url.query or url.fragment:
                raise ValueError('Local speech must use http://localhost:PORT or http://127.0.0.1:PORT.')
        self.root = Path(root or Path(__file__).parent)
        self.opener = urllib.request.build_opener(NoRedirect)

    def request(self, path, data=None, ctype='application/json', timeout=50):
        headers = {'Content-Type': ctype}
        if self.kind == 'openai':
            key = app_key(self.root)
            if not key:
                raise ValueError('Add OPENAI_API_KEY to this app’s private .env file.')
            headers['Authorization'] = 'Bearer ' + key
        request = urllib.request.Request(self.config['base_url'].rstrip('/') + path, data=data, headers=headers)
        try:
            with self.opener.open(request, timeout=timeout) as response:
                result = response.read(8_000_001)
                if len(result) > 8_000_000:
                    raise RuntimeError('Speech response too large.')
                return result
        except urllib.error.HTTPError as error:
            # Do not echo provider response bodies, request data or credentials.
            raise RuntimeError(f'Speech provider returned HTTP {error.code}. Check the provider, model and account.') from None
        except (urllib.error.URLError, TimeoutError):
            raise RuntimeError('Speech provider is unavailable or timed out.') from None

    def speech(self, text, voice=None):
        payload = {'input': text[:1200], 'voice': voice or self.config['voice'], 'response_format': 'wav'}
        if self.config['tts_model']:
            payload['model'] = self.config['tts_model']
        return self.request('/v1/audio/speech', json.dumps(payload).encode())

    def transcribe(self, wav):
        boundary = uuid.uuid4().hex
        body = (f'--{boundary}\r\nContent-Disposition: form-data; name="model"\r\n\r\n{self.config["stt_model"]}\r\n'
                f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="speech.wav"\r\nContent-Type: audio/wav\r\n\r\n').encode()
        body += wav + f'\r\n--{boundary}--\r\n'.encode()
        return json.loads(self.request('/v1/audio/transcriptions', body, 'multipart/form-data; boundary=' + boundary)).get('text', '').strip()[:4000]

    def probe(self):
        """Explicit setup test: synthesize a fixed phrase and transcribe it back."""
        audio = self.speech('Hello. Your phone voice is ready.')
        if not self.transcribe(audio):
            raise RuntimeError('The voice test returned no words. Check both speech services.')
        return True
