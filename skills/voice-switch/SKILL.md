---
name: voice-switch
description: Reply in a local lodge voice call, change its listening mode, or switch its destination to another participating Wolt when the caller asks.
---

Use the CLI and private profile paths supplied in the incoming live-call message. This prototype trusts processes running as the same Mac user; it is not a multi-user permission boundary.

Keep spoken answers to one or two short sentences unless asked for detail. Send reply text on stdin to `python3 /PATH/voice.py --profile /PRIVATE/PROFILE reply TURN_ID`. Use a single-quoted heredoc. Do not write reply files in another Wolt's folder or send live-call replies to Telegram/Shellphone.

For a transfer, run `status` to list registered names. Clarify ambiguous names. An explicit request to switch to a registered Wolt is sufficient; run `switch NAME`. Success means subsequent speech goes to that registered session, not that the destination has answered. The previous reply is cancelled, so do not submit a reply after switching. A rejected expired turn must not be retried in another channel.

For listening conditions, run `mode normal` (AirPods/quiet, RMS detector) or `mode car` (WebRTC detector) when the caller asks. These are experimental presets, not automatic device detection or validated car tuning. This changes the active call only, preserves its pending reply, Wolt, queued playback and music, and requires no hangup. You may confirm using the current reply turn after the command succeeds. `status` reports `call_mode`; no active call means there is no mode to change. Do not use `switch` for this: that command transfers to another Wolt and cancels the turn. Fresh configured dialplans start normal on 101 and car on 102; 100 remains echo. An explicit change resets unfinished microphone capture, while completed ASR and pending answers are preserved.

Session registration (`add NAME SESSION`) is host setup: use a verified session ID, never infer one from a Wolt's name. No transcripts or handoff summary are forwarded automatically. Switching does not undo actions already delivered to the previous Wolt.

To offer an unprompted short update, use `say` with text on stdin from the currently routed session (`WOLTSPACE_WOLT_SESSION` must identify you). No pending turn is needed. The CLI fences the current call and route; do not substitute another session's ID. A successful response means queued, not played. Chimes are limited to600 characters, wait/pause for microphone activity, serialize with replies, and are cancelled by recognized speech, switch, or hangup. Never retry a refused stale message on another call automatically.

The optional MLX filter follows the profile’s `isolation_default` setting; when true, each call starts sandboxed warm-up automatically. If prepared by the host, `isolation on` starts sandboxed warm-up while raw audio continues; check `status` for `isolation.state == on`. `warming`, `probing`, `armed`, `recovering` and `bypass` use original audio; only `on` means filtered delivery. Recovery is bounded and may eventually latch bypass. `isolation off` stops the worker immediately and preserves the call. No model installation or deployment is implied by a caller asking to toggle this prepared control. See [call extras](../../docs/call-extras.md) for setup and limits.

For the caller’s explicit request to record this call, use `record on`; it checks your current session/call/route, announces before capture, then status becomes `recording.state == on`. `arming` is not recording. `record off` stops and finalizes. Recording is always off on a new call, even if isolation auto-starts. Raw caller WAV and metadata sidecar stay private locally (0700/0600), with a10-minute segment cap and disk-space checks. Never upload, commit or share them without separate permission. See [recovery and recording](../../docs/recovery-recording.md).
