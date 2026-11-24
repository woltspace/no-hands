# Validation and remaining limits

## Recovery accounting change

A latency fallback followed by a backlog restart previously consumed two allowances for one episode. The adapter now counts an episode once until successful filtered re-entry. It permits three new episodes per rolling five minutes, with an independent maximum of three worker restarts within an episode. Exceeding either bound still latches raw bypass; it does not automatically resume after the rate window expires. Explicit off/on or a new call is needed after a latch (recent episode history is retained within a call). The 300 ms deadline is unchanged.

Sixteen recovery fixtures pass in an offline, non-root, read-only Python 3.12 container. They include the duplicate transition, rolling-window expiry over simulated long calls, rate exhaustion, bounded crash loops, worker shutdown, and exact frame order across raw/filtered cutovers. Synthetic clocks are used for long-window tests, not ten-minute wall-clock runs. The accounting change is deployed; no native-model load rerun was performed for that revision.

The combined targeted container invocation passed 100 tests (including inherited/repeated bridge fixtures): `test_recovery test_recording test_chime_bridge test_features test_call_modes test_noise_gate`. Providers and WebRTC imports were stubbed; the fixtures supply deterministic detector behavior. This is not a full dependency-installed suite or native VAD accuracy test.

## Earlier native model measurements

The preceding recovery implementation used the same worker, official checksum-verified checkpoint and no-network Mac sandbox. A 60-second isolated run and two 60-second runs with local synthetic ASR/TTS completed 3001/3001 frames each, with no fallback. Each loaded run completed 19 speech-service rounds. A 35-second run with a forced 250 ms worker pause completed 1751/1751 frames, fell back to raw, and re-entered filtered mode after 3.479 seconds. A 35-second combined synthetic recording/ASR/TTS run completed 1751/1751 frames and wrote exactly 1,680,960 samples. Counts include a final drain-probe frame.

Warm-up/readiness took approximately 6.3–7 seconds. Sampled process RSS ranged approximately 226–500 MiB; it does not include all Metal/GPU allocations. These short runs did not reproduce the naturally occurring stalls. Live metadata subsequently showed rare stalls and the duplicate recovery accounting bug. Typical push latency around 18 ms does not exclude occasional scheduling, input-delivery or GPU stalls. ASR/TTS causation remains unproven; no GPU priority, speech-device or delay-budget change is included.

## Scope

The detector/provider fixtures are synthetic. They do not establish road-noise accuracy, echo cancellation, fresh-device onboarding, long-call thermals or reliable shared-GPU performance. Native load measurements above apply to the preceding recovery code, not a new validation of every line in this branch. Recording fixtures use synthetic PCM; real private recordings are not included. Repository changes do not deploy anything.
