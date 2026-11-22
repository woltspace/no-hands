# Development checks

Use an isolated test environment; never run experimental setup against a live phone profile or the lodge database. Do not mount private profiles or API keys in test containers.

```sh
python -m unittest test_app.py test_routing.py
python -m unittest test_call_modes.py
python -m unittest test_noise_gate.py
TEST_DETECTOR=rms python -m unittest test_noise_gate.py
python test_interrupt.py
python test_noise_reply.py
python test_noise_playback.py
python test_switch.py
python test_add_during_call.py
python test_music_volume.py
```

`test_app.py` tests provider request contracts, credential isolation, startup refusal/cleanup and HTTP host/CSRF guards with synthetic data and mocked Docker/provider calls. It makes no billed API calls. `test_setup.py` additionally needs the Docker Compose CLI to validate generated configuration. Optional radio tests contact an external stream.

Use a fresh copied source tree and synthetic profile for app UI testing. The app deliberately listens on loopback; test through its loopback URL or inside the same isolated container/network namespace. All lifecycle actions must use mocked services until an explicitly designated test Docker/phone environment is available.

Human validation is separate: perform the [friction checklist](friction-template.md), including actual QR scan, echo, Wolt reply, provider choice and stop/restart. No synthetic test establishes mobile network quality, successful fresh-phone provisioning, or OpenAI account access.

## AudioSocket partial-frame regression

Asterisk 22.11.0's packaged AudioSocket reader abandons a partial payload after a single 5 ms wait. TCP does not preserve the bridge's write boundaries. The production Dockerfile rebuilds just that module with a checksum-pinned source and the patch in `patches/`: partial headers and payloads share a one-second monotonic deadline. EOF, invalid types/lengths and explicit hangup still terminate the call. This tolerates short transport/scheduling delays; a stalled frame still ends the call rather than tying up its channel indefinitely.

The fixture starts real Asterisk with a synthetic Local channel and private loopback AudioSocket peer, without a phone, real profile, host service, SIP ports or credentials. Run from this checkout; do not reuse live image tags or containers:

```sh
docker build --target asterisk-stock -t no-hands-audiosocket-stock .
docker build -t no-hands-audiosocket-candidate .
docker build --build-arg ASTERISK_IMAGE=no-hands-audiosocket-stock -t no-hands-transport-stock tests/transport
docker build --build-arg ASTERISK_IMAGE=no-hands-audiosocket-candidate -t no-hands-transport-candidate tests/transport
docker run --rm --network none --cpus 1 --memory 256m --pids-limit 128 no-hands-transport-stock
docker run --rm --network none --cpus 1 --memory 256m --pids-limit 128 -e EXPECT_FIXED=1 no-hands-transport-candidate
```

The baseline must reproduce the original payload timeout and closure after a 40 ms split. The candidate must survive header/payload splits at 40/150/300 ms, continue audio, bound abandoned payload/header reads, and honor explicit hangup. Installing the candidate requires an approved idle restart of Asterisk; restarting only the Python bridge does not apply this fix. Keep the old image available for rollback. Do not infer permission to restart from a passing test.

## Playback noise handling

The speech detector must sustain the selected threshold before gating reply start or ducking playback. Playback gating releases after 200 ms of silence, independently of the 1.1-second ASR endpoint wait. Empty/punctuation-only and hesitation-only `uh`/`um`/`er`/`erm` transcripts preserve the current reply; all other transcripts, including short answers and sentences containing fillers, reach the Wolt unchanged. These are noise filters, not spoken command handlers.

Metadata events `playback_queued` and `playback_gain` distinguish a waiting reply from actual output ducking without recording text or audio. This is not acoustic echo cancellation: a real phone test must still establish how road noise and speaker echo affect VAD and ASR.

The `mode normal|car` control changes only an active call. It resets incomplete capture/VAD state but leaves completed recognition, pending answers, queued audio, routing generation and music intact. The next call starts from its authenticated extension: fresh profiles use separate derived UUIDs for 101 normal and 102 car. These identifiers are derived from the private bridge secret and must remain private. The original secret continues to select the configured legacy detector; existing profiles require a deliberate dialplan migration, never automatic rewriting during bridge startup. `status.call_mode` reports the actual active mode; there is no implicit persisted last-mode setting.
