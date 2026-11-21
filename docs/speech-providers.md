# Speech choices

The bridge has explicit adapters for two providers, not arbitrary “OpenAI-compatible” endpoints.

| | Local | OpenAI |
| --- | --- | --- |
| Audio processing | Existing local voice server | OpenAI API |
| Endpoint | http://127.0.0.1:4077 (loopback configurable) | https://api.openai.com (fixed) |
| Transcription model | parakeet | gpt-transcribe |
| Speech model | server default | gpt-4o-mini-tts |
| Initial voice | alba | coral |
| Credential | none | app-local .env OPENAI_API_KEY |

OpenAI requests use bearer authentication, multipart WAV transcription and JSON speech requests returning WAV. The bridge resamples to its call format. Voices must belong to the chosen provider; local names such as alba/cosette are not OpenAI voices. Models and initial voice can be overridden during `app.py configure`.

**Compatibility window:** the current OpenAI Speech API reference announces shutdown of gpt-4o-mini-tts on January 6, 2027 and recommends migration to a Realtime model/API. This initial adapter uses the existing speech endpoint intentionally; a Realtime TTS adapter is separate follow-up work. Do not assume changing only the model name performs that migration. Recheck availability before installing after that date.

Official contracts checked for this implementation:
- [Create speech](https://developers.openai.com/api/reference/resources/audio/subresources/speech/methods/create)
- [File transcription](https://developers.openai.com/api/docs/guides/speech-to-text)

OpenAI sends audio and reply text to that provider and incurs account charges. The user enters their own key with `app.py key`. No key is inherited from the lodge or exposed through app status. A setup probe sends a fixed synthetic phrase through speech and transcription; passive checks never perform billed speech requests. A successful probe verifies those endpoints now, not ongoing account quota or call quality.

The local server is not installed by this repository. It must implement `/v1/audio/speech` and `/v1/audio/transcriptions` with the configured model/voice contract. The app probes both instead of relying on a provider-specific `/health` schema. Do not silently download models or forward audio to a cloud provider when local speech fails.
