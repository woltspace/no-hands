"""Real Asterisk AudioSocket call; no SIP phone, host services, or real profile.

Run only in a disposable container with --network none. EXPECT_FIXED=1 asserts
fragment recovery; baseline asserts the exact original payload timeout instead.
"""
import asyncio
import os
from pathlib import Path
import struct
import subprocess
import tempfile
import time

FIXED = os.environ.get('EXPECT_FIXED') == '1'
UUID = '00000000-0000-4000-8000-000000000001'

async def main():
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        for d in ('conf', 'run', 'log', 'db', 'spool'):
            (root/d).mkdir()
        conf = root/'conf'
        (conf/'asterisk.conf').write_text(f'''[directories]
astetcdir => {conf}
astmoddir => /usr/lib/asterisk/modules
astvarlibdir => /var/lib/asterisk
astdbdir => {root}/db
astkeydir => {root}/db
astdatadir => /var/lib/asterisk
astagidir => {root}
astspooldir => {root}/spool
astrundir => {root}/run
astlogdir => {root}/log
[options]
defaultlanguage = en
''')
        (conf/'modules.conf').write_text('''[modules]
autoload=no
load=res_timing_timerfd.so
load=codec_resample.so
load=res_audiosocket.so
load=chan_audiosocket.so
load=pbx_config.so
load=app_dial.so
load=bridge_simple.so
load=res_clioriginate.so
''')
        (conf/'logger.conf').write_text('[logfiles]\nconsole => notice,warning,error,verbose\n')
        queue = asyncio.Queue()
        async def accept(reader, writer):
            await queue.put((reader, writer))
        server = await asyncio.start_server(accept, '127.0.0.1', 0)
        port = server.sockets[0].getsockname()[1]
        (conf/'extensions.conf').write_text(f'''[fixture]
exten => start,1,Answer()
 same => n,Dial(AudioSocket/127.0.0.1:{port}/{UUID}/c(slin48),5)
 same => n,Hangup()
''')
        log_path = root/'asterisk.log'
        log = log_path.open('w')
        command = ['asterisk', '-C', str(conf/'asterisk.conf')]
        proc = subprocess.Popen(command + ['-f', '-g', '-vvv'], stdout=log, stderr=log)
        calls = []
        try:
            for _ in range(100):
                if 'Asterisk Ready' in log_path.read_text():
                    break
                if proc.poll() is not None:
                    raise AssertionError('Asterisk exited: ' + log_path.read_text())
                await asyncio.sleep(.05)
            else:
                raise AssertionError('Asterisk startup timeout: ' + log_path.read_text())
            async def call():
                p = await asyncio.create_subprocess_exec(*command, '-rx',
                    'channel originate Local/start@fixture application Wait 20',
                    stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.PIPE)
                await p.communicate()
                reader, writer = await asyncio.wait_for(queue.get(), 5)
                header = await asyncio.wait_for(reader.readexactly(3), 2)
                kind, length = struct.unpack('!BH', header)
                assert kind == 1 and length == 16
                await reader.readexactly(length)
                closed = asyncio.Event()
                async def consume():
                    try:
                        while await reader.read(65536):
                            pass
                    finally:
                        closed.set()
                task = asyncio.create_task(consume())
                calls.append((writer, task))
                return writer, closed
            frame = b'\x16\x07\x80' + bytes(1920)
            writer, closed = await call()
            for _ in range(5):
                writer.write(frame)
                await writer.drain()
                await asyncio.sleep(.02)
            # A frame split inside its payload; otherwise ordinary PCM silence.
            writer.write(frame[:1000])
            await writer.drain()
            await asyncio.sleep(.04)
            if not FIXED:
                await asyncio.wait_for(closed.wait(), 2)
                assert 'Poll timed out while waiting for data' in log_path.read_text()
                assert 'Failed to read payload from AudioSocket' in log_path.read_text()
                print('PASS baseline: 40 ms split payload reproduces exact Asterisk timeout and call closure.')
            else:
                assert not closed.is_set(), 'partial payload prematurely ended call'
                writer.write(frame[1000:])
                await writer.drain()
                # Header and payload may both be fragmented, over multiple reads.
                for cut, delay in ((1, .04), (3, .15), (1400, .3)):
                    writer.write(frame[:cut]); await writer.drain()
                    await asyncio.sleep(delay)
                    assert not closed.is_set()
                    writer.write(frame[cut:]); await writer.drain()
                    await asyncio.sleep(.02)
                for _ in range(100):
                    writer.write(frame); await writer.drain(); await asyncio.sleep(.02)
                assert not closed.is_set(), 'call did not survive recovered frames'
                print('PASS patched: payload/header fragments at 40/150/300 ms recover; call survives subsequent audio.')
                # A missing remainder must terminate within the whole-frame bound.
                writer.write(frame[:1000]); await writer.drain()
                started = time.monotonic()
                await asyncio.wait_for(closed.wait(), 2)
                elapsed = time.monotonic() - started
                assert .8 < elapsed < 1.8, elapsed
                assert 'Operation timed out' in log_path.read_text()
                print('PASS patched: abandoned partial payload closes within the 1 s whole-frame deadline.')
                writer, closed = await call()
                writer.write(frame[:1]); await writer.drain()
                await asyncio.wait_for(closed.wait(), 2)
                print('PASS patched: abandoned partial header is bounded too.')
                writer, closed = await call()
                writer.write(b'\0\0\0'); await writer.drain()
                await asyncio.wait_for(closed.wait(), 2)
                print('PASS patched: explicit hangup closes cleanly.')
        except Exception:
            print(log_path.read_text())
            raise
        finally:
            for writer, task in calls:
                writer.close()
                await asyncio.gather(task, return_exceptions=True)
            server.close(); await server.wait_closed()
            proc.terminate()
            try:
                proc.wait(3)
            except subprocess.TimeoutExpired:
                proc.kill(); proc.wait()
            log.close()

asyncio.run(main())
