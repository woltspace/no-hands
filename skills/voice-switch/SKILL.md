---
name: voice-switch
description: Reply in a local lodge voice call or switch its destination to another participating Wolt when the caller asks.
---

Use the CLI and private profile paths supplied in the incoming live-call message. This prototype trusts processes running as the same Mac user; it is not a multi-user permission boundary.

Keep spoken answers to one or two short sentences unless asked for detail. Send reply text on stdin to `python3 /PATH/voice.py --profile /PRIVATE/PROFILE reply TURN_ID`. Use a single-quoted heredoc. Do not write reply files in another Wolt's folder or send live-call replies to Telegram/Shellphone.

For a transfer, run `status` to list registered names. Clarify ambiguous names and confirm the intended destination conversationally. Once confirmed, run `switch NAME`. Success means subsequent speech goes to that registered session, not that the destination has answered. The previous reply is cancelled, so do not submit a reply after switching. A rejected expired turn must not be retried in another channel.

Session registration (`add NAME SESSION`) is host setup: use a verified session ID, never infer one from a Wolt's name. No transcripts or handoff summary are forwarded automatically. Switching does not undo actions already delivered to the previous Wolt.
