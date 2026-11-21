# No-hands

**Call your Wolt from your phone.** Ask a question, switch to another Wolt, or put on a radio station—all in one call.

## Get started

1. **Ask your Wolt to install it.** Send: “Install the No-hands Woltspace app and guide me through setup: https://github.com/woltspace/no-hands”. Your Wolt starts with [the installation guide](AGENTS.md).
2. **Get your phone ready.** Install [Linphone](https://www.linphone.org/) and [Tailscale](https://tailscale.com/download). Your Wolt helps connect your phone and Mac.
3. **Scan your setup code.** Open No-hands in your lodge **on your Mac**. Start the phone, create a private QR, and scan it in Linphone.
4. **Talk.** Dial **101** and say hello to your Wolt.

Choose **local speech** with a compatible voice server, or **OpenAI speech** with your own API key. With OpenAI, audio and reply text leave your Mac and API charges apply. Your Wolt explains the choice and handles configuration; you enter the key privately. All spoken voices are AI-generated.

You need a Mac running Woltspace and Docker Desktop. Keep it awake and Tailscale connected. First installation may take longer than a few minutes while dependencies download.

**Experimental:** call drops and false speech detection can still happen, particularly in a car. Fresh-phone onboarding is not yet validated. Tell your Wolt anything confusing during setup; it keeps a local friction report and asks before sharing it.

- [Instructions for your Wolt](AGENTS.md)
- [Manual setup and troubleshooting](docs/manual-setup.md)
- [Speech providers](docs/speech-providers.md)
- [Development and validation](docs/development.md)

[MIT license](LICENSE). Dependencies retain their [own licenses](THIRD_PARTY.md).
