# Development checks

Use an isolated test environment; never run experimental setup against a live phone profile or the lodge database. Do not mount private profiles or API keys in test containers.

```sh
python -m unittest test_app.py test_routing.py
python test_interrupt.py
python test_noise_reply.py
python test_noise_playback.py
python test_switch.py
python test_add_during_call.py
python test_music_volume.py
```

`test_app.py` tests provider request contracts, credential isolation, startup refusal/cleanup and HTTP host/CSRF guards with synthetic data and mocked Docker/provider calls. It makes no billed API calls. `test_setup.py` additionally needs the Docker Compose CLI to validate generated configuration. Optional radio tests contact an external stream.

Use a fresh copied source tree and synthetic profile for app UI testing. The app deliberately listens on loopback; test through its loopback URL or inside the same isolated container/network namespace. All lifecycle actions must use mocked services until an explicitly designated test Docker/phone environment is available.

Human validation is separate: perform the [friction checklist](friction-template.md), including actual QR scan, echo, Wolt reply, provider choice and stop/restart. No synthetic test establishes mobile network quality, successful fresh-phone provisioning, or OpenAI account access.
