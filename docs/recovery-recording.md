# Recovery and private recording

Apply bridge updates only while idle. Automatic isolation is an optional private-profile setting. Recording remains explicit opt-in per call.

## Isolation

`isolation on` starts the sandboxed worker, warms synthetic kernels, then probes actual incoming audio while passing raw audio through. `status` distinguishes `warming`, `probing`, `armed`, `on`, `recovering`, `bypass`, and `off`. Only `on` means the filter is supplying audio. A100-frame timely run is required before first activation or re-entry. Recovery keeps raw audio flowing, never replays frames already forwarded raw, and preserves order/length. Lag stays bounded at300ms; at most three distinct recovery episodes may begin in a rolling five-minute window. A backlog restart within an existing episode does not count again. Each episode permits at most three worker restarts; persistent failure still latches raw bypass. Successful re-entry closes the episode. `isolation off` stops the worker; the private profile may set `isolation_default: true` to start warm-up automatically on each new call. Without that setting it starts off. Recording always starts off.

Metadata includes rolling push/frame latency p50/p95/max, in-progress delay and backlog at fallback. The model can still be unable to keep up with shared-GPU ASR/TTS. No ASR device, global priority, provider configuration or delay-budget increase is implied.

## Recording

The current call's routed Wolt can run `record on` with the supplied `voice.py --profile ...` CLI. It snapshots the session/call/route and refuses a stale or different caller context. `record off` is also available to a trusted local operator as a stop control. This is the existing same-user trust boundary, not authentication against malicious same-user processes.

Recording starts off every call. `on` first reports `arming` and queues a spoken notice; audio capture begins **after** the notice plays. If recognized speech, a route change, hangup, or `off` cancels the unfinished notice, recording stays off. Ask for status rather than assuming an accepted request has started recording. Active recording remains on across a Wolt switch until explicitly stopped or hung up, consistent with per-call consent.

Files are private local `PROFILE/recordings/<random-id>/caller.wav` and `events.jsonl`, under0700 directories with0600 files. Only raw incoming caller PCM is written, before filtering; outgoing synthesized audio/music is not mixed into this file (microphone echo may naturally still be present). Audio is mono48kHz16-bit. Sidecar records capture origin/sample counts, VAD decisions and isolation transitions/latency, not transcripts. `processed_call_samples` can be compared with the start event's `call_input_samples` to align delayed decisions with recording-relative audio. Early negative offsets describe audio preceding the recording and must not be treated as captured samples.

A recording segment is capped at10minutes. At least1GiB free disk is required; space is rechecked while writing. A bounded writer queue prevents disk work from blocking the audio loop. Space, queue or disk errors stop recording and surface a status reason. Stop finalizes the WAV; a writer still stopping blocks starting another. Check status after any automatic stop/error. No automatic upload, deletion or transcript generation occurs. Keep `recordings/` ignored by version control; never stage audio/sidecars or place them in public site folders. Only explicit later user permission can authorize sharing recordings.

Replay locally: use the WAV as a48k mono input to the isolated benchmark. The sidecar has timing/sample alignment information; don't submit a real recording to a remote speech service as part of replay without separate permission. None of this draft testing records real call audio.

Rollback: use `record off` and `isolation off` during a call. To remove the candidate entirely, restore the exact pre-deployment source snapshot and restart only at an approved idle window; preserve private recordings rather than deleting them. Restore the previously selected route before the next call.
