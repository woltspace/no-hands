# Experimental opt-in isolation and unprompted speech

Both features are local, experimental, and independent of the call listening mode. Installing these source changes requires an idle bridge restart; do not restart an active call. No Asterisk change is needed specifically for these two features. The separate transport/mode dialplan update has its own deployment procedure.

## Wolt chime-in

From the session currently routed to a call, use the supplied CLI/profile path:

```sh
python3 /PATH/voice.py --profile /PRIVATE/PROFILE say <<'SPOKEN_TEXT'
A short update for the caller.
SPOKEN_TEXT
```

The CLI reads `WOLTSPACE_WOLT_SESSION` and snapshots call ID and route generation before submitting. The bridge rejects a stale call/route or another session. This is a routing fence within the existing trusted-same-user model, not authentication against another process running as that user. Do not override the session variable to impersonate the selected Wolt.

Text is limited to 600 characters; at most three messages may wait behind an active chime. Acceptance means queued, not heard. Chimes serialize with ordinary synthesized replies, pause while microphone activity is detected, resume after quiet, and are cancelled by recognized speech, switching, or hangup. The raw microphone activity gate remains active even when isolation adds input latency. Detection is not acoustic echo cancellation or a guarantee of detecting every quiet voice. Ordinary pending replies and the existing noise-duck behavior are preserved. No active call produces a clear refusal.

## Experimental opt-in MLX filter

The bridge does **not** import MLX or load model weights. `isolation.py` starts `voice-isolate-worker` only via Apple's `/usr/bin/sandbox-exec` with the checked-in `isolator/worker.sb`. There is no unsandboxed or remote fallback. The worker has only PCM stdin/stdout, a minimal environment, no network/local sockets, and writes only in its trial folder. The profile is the tested Mac sandbox policy; it is not a Docker container. Inspect that policy for its precise allowed system/GPU access.

Prepare a private local directory containing:

- `voice-isolate-worker`, built from `isolator/worker.swift` against VoiceIsolatorMLX tag 0.1.0 (`3d4540560f546efd0b76bb86b49a9b3eecb8c74f`), mlx-swift 0.32.3 (`19601207e9a0de51e03ee6ec0c3c5f3784275075`), swift-numerics 1.1.1 (`0c0290ff6b24942dadb83a929ffaaa1481df04a2`).
- The matching `mlx-swift_Cmlx.bundle` beside the binary.
- Official Inworld `denoiser_realtime.safetensors`, revision `9b0285b3fe8403aa8e2f1dbb2165a80a4294c970`, SHA-256 `76598f05523c0669e76562a8b2f31c9d395fca316e80c907ee11775e7497ae0f`.

`isolator/build-existing.py --build DERIVED_DATA --output PRIVATE_TRIAL` links against an existing reviewed build without downloading or installing anything. It does not fetch model weights. Preserve dependency pins and notices; do not substitute arbitrary compiled objects. The bridge verifies the official weight checksum before **every** worker launch. It never calls the port's downloader or selects third-party converted weights. No binary/weights are bundled in this repository.

Once the owner approves deployment, add `"isolator_folder": "/ABSOLUTE/PRIVATE_TRIAL"` to that bridge's private profile and restart the bridge only while idle. This is a path setting, not an enable flag. The experimental filter is off by default. Use `isolation on` to try it on a call. Setting `"isolation_default": true` is a separate explicit opt-in to experimental automatic startup, not a recommended default. Leave it false or absent for per-call opt-in; recording always starts off.

```sh
python3 /PATH/voice.py --profile /PRIVATE/PROFILE isolation on
python3 /PATH/voice.py --profile /PRIVATE/PROFILE status
python3 /PATH/voice.py --profile /PRIVATE/PROFILE isolation off
```

`on` acknowledges startup, not readiness. Status progresses `warming` → `probing` → `armed` → `on`, or `bypass` on failure. During warm-up (~5 s in one local measurement), original audio continues through VAD/ASR. The worker warms kernels on synthetic audio, discards that stream state, then accepts call audio. Filtered audio is used for VAD and transcription only; outgoing TTS/music is unchanged.

Input is rebuffered to 20 ms PCM. The adapter targets roughly 180–200 ms input buffering and bounds its worker queue to 15 frames. A frame waiting over 300 ms triggers raw recovery; backlog or worker failure may restart the worker. Invalid protocol or exhausted recovery budgets latch raw bypass. Pending originals drain in order; stale output is discarded. Re-entry requires 100 consecutive timely frames. Recovery permits three distinct episodes per rolling five minutes and three restarts per episode. See [recovery and recording](recovery-recording.md) for controls and limits. Switches preserve the call's filter setting; hangup stops the child.

Rollback during a call: `isolation off`. Remove the profile setting at the next approved idle maintenance window to disable future startup. Full source rollback requires an idle restart using the saved previous source/profile; never replace a running bridge merely to undo an optional filter.

Metadata logs contain warm-up, readiness, and bypass reason codes, not PCM, transcript text or model output. The worker does not save call audio. Phone quality, echo behavior, long-call thermals and combined production ASR/TTS load remain acceptance tests; a successful isolated benchmark does not establish those.
