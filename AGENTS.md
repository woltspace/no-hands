# Install No-hands for your human

You are the installer and guide. Keep technical commands out of the human's path. They install phone apps, sign in, enter their own key if needed, scan the QR, and call. Never claim setup is complete until they hear their Wolt on a real phone.

## Before changing anything

Read the host lodge's app instructions. Use its supported app install/start API; never restart Woltspace or install a second lodge. This package targets macOS with Python 3.13, Docker Desktop and one owner/phone. Windows/Linux deployment is not validated. Do not overwrite an existing No-hands app or private profile.

Create a local friction record using [this template](docs/friction-template.md) under `runtime/friction.md` (gitignored). Record elapsed minutes, failed steps and unclear instructions as you work. Do not record credentials, QR contents, transcripts, real addresses or personal names. At the end, show a sanitized report to the human and ask before sending it anywhere. Nothing is uploaded automatically.

## 1. Install in the lodge

Find the lodge's actual apps directory using its instructions. Clone `https://github.com/woltspace/no-hands` there as `no-hands`. A private repository requires authorized GitHub access. Set `keeper` in `woltspace.json` to your Wolt name and choose an unused app port if 4091 conflicts. Keep `public: false`. Do not share this setup app through a public tunnel.

The manifest install command creates an app-local `.venv`. The current lodge auto-installs Node apps only, so run the Python installation explicitly in this app folder before starting:

```sh
python3.13 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
```

Verify `ffmpeg`, `woltspace`, and `docker compose` are available. If Python/ffmpeg/build tools/Docker Desktop are missing, guide installation according to the human's machine policy. Never silently change system packages. Start Docker Desktop; check `docker info`. Build the phone image:

```sh
docker build -t shellphone-voice:local .
```

This can take several minutes on a fresh machine. The image is Asterisk only, not a voice model or agent runtime.

## 2. Choose speech with the human

Offer **local** (existing WOCAL-compatible server; not bundled here) or **OpenAI** (their account/API charges; audio and reply text sent to OpenAI). See [provider details](docs/speech-providers.md). No automatic fallback between providers.

For OpenAI, have the human run `.venv/bin/python app.py key` in this app's terminal: it prompts invisibly and writes only this app's `.env` with owner-only permissions. Never ask for a key in chat, put it in a command argument, use lodge tokens, or search other apps' secrets. The app never returns the key to the browser. This is API usage, not a ChatGPT subscription integration.

## 3. Prepare the connection

Help the human install Tailscale on Mac and phone and connect to the same private network. Determine both devices' verified Tailscale IPv4 addresses. Do not guess from examples. The app is a private Mac-local setup page, not a remote/public web console.

Have the human install Linphone. QR provisioning replaces its first SIP account: explain this before scanning. Use a fresh setup or an account they mean to replace.

Verify your live session with `woltspace session list --alive`. Read [live call instructions](skills/voice-switch/SKILL.md). Use the actual session ID. Register the session that should answer; it must stay available during calls. A busy coding session can delay answers.

Configure a fresh profile from this app directory (replace all placeholders):

```sh
.venv/bin/python app.py configure --name personal \
  --mac-ip MAC_TAILSCALE_IP --phone-ip PHONE_TAILSCALE_IP \
  --wolt YOUR_NAME --session YOUR_LIVE_SESSION_ID --provider local
```

Use `--provider openai` for OpenAI. Local defaults to voice `alba`; OpenAI to `coral`. Optional `--voice`, `--stt-model`, `--tts-model` customize provider settings; local supports `--base-url http://127.0.0.1:PORT`. OpenAI's endpoint is fixed so its key cannot be redirected to another host.

Configure creates `runtime/personal/`, selects it in `runtime/app.json`, registers your route and sets the manifest keeper. It never overwrites an existing profile. App profiles have no automatic bridge expiry. Other pre-existing/manual profiles are not adopted.

Allow only the phone's private address to reach the Mac on TCP5060, UDP18000–18009 and temporary TCP18975. `runtime/personal/policy-draft.json` is a draft, not an applied Tailscale policy. Have the owner review/apply changes if required. Never open public ports or disable firewalls. Keep credentials and provisioning private.

## 4. Open the app

Start through the lodge API:

```sh
curl -X POST http://localhost:7777/apps/no-hands/start
```

Open the app in the lodge on the Mac. If necessary open `http://localhost:4091` (or the chosen manifest port). The page binds loopback and rejects nonlocal Host headers deliberately; remote tunnel setup is not supported in this version.

The app shows prerequisite checks. Explain a failed check and fix its cause; do not click past failures. **Start phone** runs a short speech/transcription test (a small API charge with OpenAI), starts Asterisk and the bridge, and reports readiness. It does not pay for tests during passive status polling.

**Create setup QR** starts a private, phone-address-restricted provisioning server for 15 minutes. The human scans it in Linphone. **Hide and expire QR**, expiry, or stopping the app removes the QR and stops provisioning.

**Ready to call** verifies the owned bridge control socket, Asterisk and a successful speech test. It does not prove phone registration, microphone permissions or the network audio path. Have the human dial100 for echo, then101 for a real question and response. Test cellular with Tailscale connected after Wi-Fi works.

## Lifecycle and recovery

The app owns only its new profile's container and child processes. Start/stop operates the phone stack together. The page refuses Stop phone during a call; stopping the app from the lodge ends calls and cleans up its bridge, QR and container. No automatic Mac reboot startup is included.

If an old container/bridge occupies the profile or ports, identify it before stopping anything. Never kill a process based only on a port or name. After an ungraceful app crash, inspect and stop the exact profile with `docker compose -f runtime/personal/compose.json down` and inspect any orphan bridge before relaunch. Do not touch another trial or the lodge.

`runtime/personal/service.log` contains private service diagnostics; call event logs omit audio/transcript text. Wolt history still contains transcripts. Report errors without copying credentials/configs. If OpenAI authorization/models fail, fix the key/access/model with the human; don't switch to another provider silently.

A changed/dead Wolt session needs re-registration: while running use `voice.py ... add`/`switch` as documented, or stop the app and update the profile session and route together. Never replace a selected session in an active call. Startup checks the configured session, so keep profile and route consistent.

## Finish and report friction

Record whether install, QR scan, echo, real Wolt reply and cellular test actually passed, and how long each took. Mark skipped steps clearly. Show the human a sanitized report for approval, then offer to share it as a GitHub issue or back to whoever sent the project. Success is a real first call, not a green terminal exit.
