# Dependencies

This project's MIT license does not relicense its dependencies.

- [Asterisk](https://github.com/asterisk/asterisk): see its COPYING and LICENSE files. Installed in the Docker image from Alpine packages. The AudioSocket module is rebuilt from checksum-pinned Asterisk 22.11.0 source with `patches/asterisk-audiosocket-read.patch`; that derivative patch/module remains under Asterisk's GPL-2.0 terms, not this project's MIT license. The Dockerfile retains the exact source URL and build recipe.
- [py-webrtcvad](https://github.com/wiseman/py-webrtcvad): see its LICENSE, including the bundled WebRTC notices. Installed as a Python dependency, not vendored here.
- [ffmpeg](https://ffmpeg.org/legal.html): license depends on the user's build and enabled components. Installed separately.
- Python packages qrcode, Pillow and setuptools: consult the installed distributions' license metadata.

Linphone, Tailscale and the agent/voice services are separately installed software, not included in this source repository.

Optional MLX worker: `isolator/worker.swift` uses VoiceIsolatorMLX 0.1.0 (Apache-2.0), Apple's mlx-swift 0.32.3 and swift-numerics 1.1.1 (Apache-2.0), and the official Inworld realtime checkpoint (Apache-2.0). These external binaries/weights are not redistributed here. Preserve their LICENSE/NOTICE files, including Inworld's training-data notices, when preparing or distributing a worker folder. Pinned sources and weight checksum: [call-extras.md](docs/call-extras.md).
