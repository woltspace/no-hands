# No-hands — voice prototype

Call your AI while walking.

An experimental hands-free voice bridge for Wolt sessions. Initial MVP: two participating Wolts on one phone call, with spoken switching and distinct voices. This checkpoint includes CLI switching; per-route voices, spoken switching, reachability checks and real two-Wolt phone validation remain follow-up work. It is not a one-click installer.

## What works
- Linphone call → Tailscale → Asterisk → local WOCAL ASR → existing Wolt session → local WOCAL TTS → call.
- Opus with48kHz PCM bridge; no narrowband fallback.
- “Welcome to Shellphone!” greeting.
- Faint generated music, music on/off/change commands, music mute while speaking.
- Speech interrupts queued playback; it does not cancel agent work already delivered.
- Captured tick; delivered rising chime; descending failure/timeout cue. Delivered does not mean completed.
- Private QR onboarding; voice settings go into Linphone without typing a password.

Prototype testing covered local conversation, music muting and interruption. Remote call input and spoken exchange succeeded after TCP signaling and explicit media_address correction; longer cellular/locked-screen/battery testing remains. Original echo with locked screen worked on Wi-Fi. Do not claim all combinations tested.

## Scope
Two-way conversation with an existing Wolt/WOCAL host. One-way radio and generalized session management are deferred. Shellphone room routing is not automatic: the bridge targets registered Wolt sessions.

## Phone setup (the short version)
1. Create/sign in to a Personal Tailscale account for non-commercial use. Install Tailscale on Mac and iPhone and use the same account. The Personal plan is currently free; ordinary internet/mobile data costs remain.
2. Install Linphone. Allow microphone; allow local network for LAN testing. Camera is needed for QR scanning only. Contacts and video camera access are not required for audio calling. Review permissions afterward.
3. Give the host operator the Mac and iPhone Tailscale IPv4 addresses. Never share login passwords, recovery codes or Tailscale auth/API keys.
4. Host operator starts the stack and opens the private QR page on another screen.
5. In Linphone choose Scan QR Code. Tailscale must stay connected. This prototype overwrites the first SIP account, so use a fresh app profile or deliberately replace the test account.
6. Dial100 for echo, then101 for the Wolt. Test on Wi-Fi, then cellular with Wi-Fi off.

## Host prerequisites (not installed automatically)
- Supported Mac with Docker Desktop running, Python3, ffmpeg, and uv for QR dependencies.
- WOCAL already running at127.0.0.1:4077: /health, /v1/audio/transcriptions (model parakeet), /v1/audio/speech (voice alba).
- Woltspace with `woltspace session send` on PATH, a verified live target session, and a session able to write the supplied local reply file. Agent model provider/billing remain unchanged. Other agent harnesses need an adapter.
- Tailscale connected on both devices; Mac private address locally bindable.
- Network policy reviewed for phone→Mac TCP5060 and UDP18000–18009. Temporarily allow TCP18975 for QR provisioning. Generated policy is a draft; broad existing allow rules are additive and must be reviewed. No router port forwarding, public Funnel, exit node or subnet route required.
- Mac awake/reachable for the trial; no sleep/settings changes made automatically.

## Prepare
From this directory:

```sh
docker build -t shellphone-voice:local .
python3 setup.py init --name personal --mac-ip MAC_TAILSCALE_IP --phone-ip PHONE_TAILSCALE_IP --session VERIFIED_WOLT_SESSION
```

The profile is stored in runtime/personal with restrictive permissions. It creates fresh SIP credentials, a bridge UUID, Asterisk config, Docker Compose file, policy draft and provisioning XML. Init does not start services or change Tailscale. Never publish runtime/ or its QR codes. Existing profiles are never silently overwritten.

Stop earlier trial listeners before starting another stack on the same ports; do not stop unrelated apps.

## Start / QR / stop
```sh
python3 setup.py start --name personal
```
In a managed background session, start the bridge:
```sh
python3 setup.py bridge --name personal
```
In another terminal or managed background session, serve the QR temporarily:
```sh
uv run --with 'qrcode[pil]' python setup.py qr --name personal --minutes 15
```
Open the LOCAL setup-qr.html path printed by that command on the Mac. It is not a public page. The QR server accepts only the selected phone's private source IP and a random URL token; the port closes at expiry or Ctrl-C. It removes generated QR HTML/image on normal shutdown. The underlying private XML stays in the profile for later reprovisioning. An updated QR replaces the old first account, including explicit TCP server/route.

Bridge runs1h by default; a call is capped15min. Managed persistent lifecycle is not implemented. Press Ctrl-C in the bridge terminal to stop it, then:
```sh
python3 setup.py stop --name personal
python3 setup.py status --name personal
```
`stop` stops only this profile's container; bridge and provisioning are separate processes. No auto-start at login/reboot. Do not promise later calls will work after the timed bridge ends.

## Call controls
- No wake word. Speak, then pause~1.1s. Utterances max120s (two minutes). Transcription uploads are downsampled to16kHz; call audio stays48kHz.
- Energy detection, not a trained VAD. Headphones recommended to avoid speaker echo triggering interruptions.
- Music on / music off / change the music (two local generated loops).
- Start talking to interrupt playback. Stop/okay stop/stop talking ends playback without asking the agent a question. More complex phrases may reach the agent.
- Music mutes while speaking, resumes afterward, and ducks during replies.
- Tick: captured for transcription. Rising chime: transcript handed to Wolt. Lower cue: empty/failed transcription, delivery error or reply timeout. Local music/stop commands do not produce a “sent” cue.
- Mute/hangup in Linphone. Muting is the sure way to avoid interpreting ambient conversation.

## Troubleshooting learned from the actual phone tests
| Symptom | Check / fix |
|---|---|
| Wrong username/password after QR | Older Asterisk rejected long push notification contacts. Disable both push flags in provisioning. Do not assume a credential problem. |
| Registration succeeds, calls stall over VPN | Use TCP signaling. UDP authenticated INVITE disappeared in our test; fragmentation suspected, not proven. |
| Hear music, microphone never arrives | Check SDP `c=`. Explicit endpoint media_address must be the Mac Tailscale IP, not172.x Docker IP. Restart container if reload doesn't apply. |
| Still dialing192.168... | Old call history/account. Scan updated QR and use sip:101@MAC_TAILSCALE_IP. |
| Muffled despite48k bridge | Verify negotiated NativeFormats opus; earlier calls silently used ulaw8k. This setup requires Opus. |
| Silence/no Wolt response | Check bridge process and WOCAL health; bridge expires after1h. Check target Wolt session and response-file permissions. |
| Music but no speech detection | Check mic mute, permission, RTP route and input level; don't repeatedly change credentials. |
| No tutorial | Current greeting intentionally only says Welcome to Shellphone! |
| Speech stops itself | Use headphones; echo/noise may trigger the energy detector. |

## Security and remaining work
VPN encrypts device-to-device traffic, including relay paths; audio is decrypted on the Mac for local processing. Raw SIP/RTP and provisioning HTTP rely on that VPN for transport protection. Original LAN profile was unencrypted. Audio chunks stay in bridge RAM, but transcripts enter Wolt history and Asterisk writes operational logs. Do not log full SIP auth headers or publish QR/provisioning files. The bridge UUID is a same-host trust mechanism, not a hardened multi-user boundary.

Voice recognition can be wrong. The transcript envelope requires text confirmation of consequential actions; this prototype does not enforce a complete authorization system. Stopping audio does not undo actions or cancel an already-delivered agent request. One active call only. Conferencing parked.

Remaining: supervised lifecycle, installation/update UX, robust VAD/echo cancellation, bounded transcription/TTS cancellation, stale reply cleanup, exact command parsing, authentication/permissions for multiple people, selectable agent/room mapping, one-way worker integration, secure provisioning beyond the personal VPN test, mobile handover and battery tests. Keep checkpoint claims narrower than these product goals.

References:
- https://tailscale.com/pricing
- https://tailscale.com/docs/install/mac
- https://tailscale.com/docs/install/ios
- https://www.linphone.org/en/docs/login-with-qrcode/
- https://docs.asterisk.org/Configuration/Channel-Drivers/AudioSocket/

## Local Wolt switching prototype

The single caller stays connected while the selected destination changes. `routing.py` is the small routing library; `voice.py` is its Unix-socket CLI. Start the bridge with the existing `setup.py bridge --name personal` command, then:

```sh
python3 voice.py --profile runtime/personal status
python3 voice.py --profile runtime/personal add softie VERIFIED_SESSION_ID
python3 voice.py --profile runtime/personal switch softie
```

Each incoming turn includes the exact CLI reply command. Supply its spoken answer on stdin. The bundled `skills/voice-switch/SKILL.md` explains conversational confirmation and reply handling. No speech command parser is needed for switching: the Wolt invokes the CLI.

Registered sessions persist in private `routes.json`; the selected destination resets to the first registered entry when the bridge starts. A switch discards queued speech and partial input, cancels the old reply waiter, and rejects old turn IDs. It does not cancel work already delivered to a Wolt. Only future turns go to the new destination. No conversation history is forwarded.

This is single-owner, same-OS-user tooling. The socket is mode0600, not an authorization boundary between Wolts running under that user. A destination must be a real, reachable Wolt session. Cross-Wolt calls still need a real phone test; synthetic checks are not proof of successful handoff.
