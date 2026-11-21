# Dependencies

This project's MIT license does not relicense its dependencies.

- [Asterisk](https://github.com/asterisk/asterisk): see its COPYING and LICENSE files. Installed in the Docker image from Alpine packages.
- [py-webrtcvad](https://github.com/wiseman/py-webrtcvad): see its LICENSE, including the bundled WebRTC notices. Installed as a Python dependency, not vendored here.
- [ffmpeg](https://ffmpeg.org/legal.html): license depends on the user's build and enabled components. Installed separately.
- Python packages qrcode, Pillow and setuptools: consult the installed distributions' license metadata.

Linphone, Tailscale and the agent/voice services are separately installed software, not included in this source repository.
