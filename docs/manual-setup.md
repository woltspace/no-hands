# Manual setup

Talk to your Wolt from your phone. Ask questions, switch to another Wolt, or ask it to put on a radio station—all within one call.

**Experimental, single-owner prototype.** Conversations and radio have been tried on real phones, but car noise can still trigger speech detection and AudioSocket transport timeouts have dropped calls. A fresh installation on a friend's Mac has not yet been validated. Expect to use a terminal and troubleshoot.

## How it works

Your phone runs Linphone. Tailscale connects it privately to your Mac, where Asterisk handles the call. A Python bridge sends speech to a local voice server, delivers the transcript to a running Wolt session, and plays its answer back.

```text
Linphone → Tailscale → Asterisk → bridge → local ASR → Wolt
                                  ↑                    ↓
                                  └──── local TTS ← reply
```

The bridge uses WebRTC voice activity detection and 48 kHz mono audio. Wolts interpret your words and run CLI controls; the bridge does not match spoken commands. It supports one call at a time, with one selected Wolt. Switching does not transfer conversation history or cancel work already delivered.

## Before you start

On your Mac, install and start:

- [Docker Desktop](https://docs.docker.com/desktop/setup/install/mac-install/), including Docker Compose.
- Python **3.13** (the tested version), Git, and ffmpeg on your PATH. Installing `webrtcvad` may require the Apple command-line build tools.
- [Tailscale](https://tailscale.com/download) on both Mac and phone, signed into the same private network. The Mac must stay awake and reachable.
- A working **Woltspace** installation with `woltspace session send` on PATH and a running Wolt session.
- For the local speech option: a **WOCAL-compatible voice server** at `http://127.0.0.1:4077`. This repository does not install it. It must provide `POST /v1/audio/transcriptions` (multipart WAV, model `parakeet`, JSON `text`) and `POST /v1/audio/speech` (`input`, `voice`, `response_format: wav`). The default voice is `alba`.

On your phone, install [Linphone](https://www.linphone.org/) and Tailscale. Microphone access is required; camera access is only needed to scan the setup QR. Use headphones for the first test.

For OpenAI speech instead, configure the app as described in [the installation guide](../AGENTS.md); it sets provider-specific models and voices and reads an app-local key.

**Do not start with only a phone.** The Mac, agent session and voice server are required. Another ASR/TTS server needs to satisfy the above contract and voice names; arbitrary OpenAI-compatible endpoints are not automatically supported. Agent-provider costs and permissions remain those of your Wolt installation.

## 1. Get the code and Python dependencies

```sh
git clone https://github.com/woltspace/no-hands.git
cd no-hands
python3.13 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
docker build -t shellphone-voice:local .
```

The repository must be accessible to your GitHub account while it is private. The Docker image contains Asterisk, not your agent or voice server.

Check your prerequisites:

```sh
ffmpeg -version
docker compose version
curl --fail http://127.0.0.1:4077/health
woltspace session list --alive
```

Both speech and transcription should be ready. Choose an actual running session ID, not just a Wolt name. Tell that Wolt it will receive live-call turns and should follow the exact reply command in each turn. See [the agent instructions](../skills/voice-switch/SKILL.md).

## 2. Create your private phone profile

Find each device's Tailscale IPv4 address in the Tailscale app. Replace every uppercase placeholder below with your values:

```sh
.venv/bin/python setup.py init --name personal \
  --mac-ip MAC_TAILSCALE_IP \
  --phone-ip PHONE_TAILSCALE_IP \
  --wolt YOUR_WOLT_NAME \
  --session YOUR_RUNNING_SESSION_ID
```

This creates `runtime/personal/` with fresh credentials, configuration and QR provisioning data. It does not start services or change your Tailscale policy. Existing profiles are never overwritten.

Allow the phone to reach the Mac on **TCP 5060**, **UDP 18000–18009**, and temporarily **TCP 18975** for QR setup. The generated `policy-draft.json` is a draft to review against your existing Tailscale policy; it is not applied automatically. Do not expose these ports with public port forwarding or a public tunnel.

Docker must be able to publish ports on the Mac's Tailscale address. If it cannot, resolve that host/network setup before proceeding; substituting a public bind address changes the security assumptions.

## 3. Start the call stack

Start the phone server:

```sh
.venv/bin/python setup.py start --name personal
```

In a terminal you leave open, start the bridge:

```sh
.venv/bin/python setup.py bridge --name personal
```

Wait for `Local voice bridge ready`. In another terminal, temporarily serve the setup QR:

```sh
.venv/bin/python setup.py qr --name personal --minutes 15
```

Open the **local HTML file** printed by the command on your Mac. In Linphone on the phone, choose Scan QR Code. Tailscale must be connected on both devices. This provisioning replaces Linphone's first SIP account: use a fresh app setup or deliberately replace a test account.

Keep the QR private. It contains access to your phone configuration. The provisioning server accepts only the configured phone address and closes after the specified interval. Ctrl-C also stops it and removes generated QR images on normal exit.

## 4. Make your first call

1. Dial **100** for an echo test. Speak and listen for your voice.
2. Dial **101** for normal mode or **102** for car mode. If Linphone requires an address, use `sip:101@MAC_TAILSCALE_IP` (or `102`).
3. Ask a short question, then pause roughly **1.1 seconds**.
4. After Wi-Fi works, test cellular with Wi-Fi off and Tailscale still connected.

A tick means audio was captured; a rising chime means the transcript was delivered to the Wolt, not that it finished. An error cue indicates a failure or timeout. Replies from a busy Wolt may be delayed.

Normal mode uses the RMS detector with a 0.18-second playback threshold; car mode uses WebRTC with 0.4 seconds of consecutive speech. These are experimental starting presets, not verified device-specific tuning. Raw detection lowers reply volume to 20% rather than deleting it, releasing after 0.2 seconds of silence. Empty or hesitation-only transcription preserves the pending answer; meaningful new words supersede it. Speech recognition can still misinterpret background sound; there is no automatic noise-floor adaptation or neural noise suppressor.

Ask the current Wolt to switch to car or normal mode during the call. It uses `voice.py --profile runtime/personal mode car` or `mode normal`, and can confirm in the same reply. Mode changes preserve the call, pending reply, route, music and queued audio, but reset unfinished microphone capture. They last for this call; redialing chooses the extension's mode again. Extension 100 remains the echo test.

Existing private profiles are not silently rewritten: the original 101 handshake retains the profile's configured detector until an approved dialplan update installs the distinct 101/102 mode identifiers. The updated bridge still accepts the original handshake. Neither mode change requires restarting Asterisk once the updated bridge and dialplan are deployed.

## 5. Add another Wolt or control music

While the bridge is running:

```sh
.venv/bin/python voice.py --profile runtime/personal status
.venv/bin/python voice.py --profile runtime/personal add helper OTHER_SESSION_ID --voice cosette
.venv/bin/python voice.py --profile runtime/personal switch helper
```

The CLI prints the selected Wolt and voice. Ask the Wolt on the call to switch for you. There is no automatic spoken departure/arrival announcement yet; the next reply uses the new voice. On bridge restart, selection resets to the first registered route.

A voice change currently uses `add` with the **same name and session ID**, plus a different `--voice`. Use a voice supported by your voice server. This is trusted host setup, not a permission boundary between Wolts.

Music controls also go through the Wolt, or directly through the CLI:

```sh
.venv/bin/python voice.py --profile runtime/personal music play HTTPS_AUDIO_STREAM_URL
.venv/bin/python voice.py --profile runtime/personal music volume 15
.venv/bin/python voice.py --profile runtime/personal music off
.venv/bin/python voice.py --profile runtime/personal music on
.venv/bin/python voice.py --profile runtime/personal music next
```

`play` requires a direct HTTP(S) audio stream, not a station's webpage. `off` stops its decoder; `on` then enables the generated background bed. `next` selects the other generated tune. Volume is 0–100; 8 is the default. Music is reduced under replies and muted while the caller is speaking. A new call starts with the generated bed on. Local library playback is not implemented.

## Stop, restart and logs

Stop the bridge with Ctrl-C in its terminal. Then stop its Asterisk container:

```sh
.venv/bin/python setup.py stop --name personal
.venv/bin/python setup.py status --name personal
```

`stop` controls the container only; it does not terminate a separate bridge or QR process. There is no automatic login/reboot startup or crash supervisor.

New profiles expire the bridge after one hour. To keep it running, edit `runtime/personal/profile.json`, set `trial_seconds` to JSON `null`, and restart the bridge. Conversation calls have no fixed duration cutoff; the echo test ends after five minutes.

Per-call diagnostic logs are under `runtime/personal/logs/`. During a call, `voice.py status` reports the exact `call_log` path. Logs contain timestamps, RMS summaries, VAD counts, turn/reply timing, playback ducking, music/control state and observed hangup events. They contain **no recorded audio or transcript text**. They are local, not uploaded, and are not automatically rotated or deleted. Wolt history does contain transcripts; Asterisk has separate operational logs. Correlate their timestamps when investigating drops.

## Troubleshooting and known limits

| Symptom | Check |
| --- | --- |
| QR registers but calls do not connect | Keep Tailscale on; provisioning uses TCP SIP. Check the configured Mac address and allowed ports. |
| Music arrives but no microphone audio | Check Linphone microphone permissions/mute and the configured media address. |
| No agent answer | Check the selected session is running, the bridge terminal, and voice-server health. |
| Call drops | Asterisk AudioSocket payload-read timeouts have occurred in real testing. This remains unresolved; redialing is a workaround, not a fix. |
| Car noise triggers interruptions | Inspect VAD/ducking logs. Noise handling is experimental; headphones and car Bluetooth can behave differently. |
| `No active call` for music | Dial 101 first. Music belongs to the current call. |
| Reply rejected as expired/switched | A newer recognized utterance, switch, timeout or hangup may have ended the turn. Do not replay stale replies into another channel. |
| Port already in use | Stop your previous trial, not an unrelated application. Only one stack can use these fixed ports. |

Audio has been tested with Opus, but music can sound thin and mobile handover/battery behavior is not validated. This is not a general multi-user phone gateway, conferencing server, or emergency calling service.

## Privacy and trust

The intended network boundary is your private Tailscale network. SIP/RTP and QR HTTP are not independently encrypted by this project. The Mac decrypts and processes audio locally; transcripts enter the agent's context and may go to its model provider. The voice server and agent have their own retention policies.

Keep `runtime/`, credentials, QR files, call logs and tokens out of Git and shared screenshots. The Unix control socket is owner-only, but processes running as the same OS user are trusted. The bridge's call token is not strong isolation against other local processes. Voice instructions ask for text confirmation of consequential actions; that is a convention, not an enforced authorization system.

## Development checks

```sh
.venv/bin/python -m unittest test_setup.py test_routing.py
.venv/bin/python test_interrupt.py
.venv/bin/python test_noise_reply.py
.venv/bin/python test_noise_playback.py
.venv/bin/python test_switch.py
.venv/bin/python test_add_during_call.py
```

Setup tests validate generated Docker Compose configuration without starting containers. Call tests use synthetic audio and mocked agent delivery. Optional `test_radio.py` and `test_call_radio.py` contact an external test stream. Passing these checks does not establish fresh-device onboarding or real-world call stability.

## License

[MIT](../LICENSE) for this repository's code. Asterisk, WebRTC VAD, ffmpeg and other dependencies retain their own licenses; see [THIRD_PARTY.md](../THIRD_PARTY.md).
