# MVP-IA-CXX-R1 — Known Gaps

Documented as required by this task's scope. None of these are corrected here — this task consolidates evidence and builds offline tooling; it does not touch the interaction/IA C++ runtime, telemetry, WebSocket, vision, QR, odometry, TF, mapping, localization, Nav2, or movement subsystems.

These gaps apply to the `cxx_jsonl_physical` backend introduced in `0d14de6` and its UI wiring in `3da2e9a`.

1. **Capture thread has no readiness handshake.** The audio capture thread starts without a synchronization point confirming it is actually listening before the worker reports itself ready to the supervisor.
2. **Socket/bind/multicast errors are not propagated.** UDP multicast socket setup failures (bind, join-group) are not surfaced through the JSONL protocol as a distinct error state; failure modes here are opaque to the supervisor/UI.
3. **Physical configuration is hardcoded.** Multicast group/port, local IP, sample rate, capture duration, RMS threshold, chunk size, SDK volume, model paths (Whisper, Piper voice), and network interface name are compile-time constants in the worker source, not externalized to configuration.
4. **Ollama HTTP/JSON client is frail.** The LLM client integration lacks robust handling of malformed responses, timeouts, or connection drops from the local Ollama service.
5. **UADE context is not injected directly.** Institutional/context grounding for the LLM is not wired as an explicit, inspectable input to the prompt construction.
6. **No capture-start audio cue (beep) exists.** Users receive no audible signal that capture has begun.
7. **Pause/resume are no-ops.** The protocol may accept pause/resume commands but they do not change worker behavior.
8. **`playback_started` can fire before TTS synthesis actually completes.** The event ordering does not guarantee synthesis-then-playback strictly.
9. **Playback completion is estimated by elapsed time, not observed.** The worker infers `playback_completed` from an expected-duration calculation rather than a hardware/driver-reported completion signal.
10. **Temporary files use global paths under `/tmp`.** No per-session isolation of intermediate audio/text artifacts; concurrent or repeated sessions could collide.
11. **Startup timeout is sensitive to cold start.** `INTERACTION_STARTUP_TIMEOUT_S` (default 3.0s per `settings.py`) may be too tight on a cold Jetson boot where model loading (Whisper GPU, first Ollama call) has not yet warmed up, producing spurious startup failures unrelated to actual worker health.

## Scope note

This list is carried forward unchanged from the spec's own minimum-gaps enumeration; it was not independently re-derived from code inspection beyond confirming the gaps are plausible given the worker's structure read during the `0d14de6` audit (e.g., the hardcoded `constexpr` configuration block observed directly in the diff supports gap #3). No gap here has been marked resolved, partially resolved, or reclassified — that determination is out of scope for this task.
