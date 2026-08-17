# Pre-Push Review — 0d14de65165805793b6c7c752780e0472507a388

- **Parent:** `254cdddfa33477b794561560b397418870d777d9`
- **Author:** LucasCap12
- **Date:** 2026-07-14 17:20:31 -0300
- **Subject:** `feat(interaction): add physical cxx jsonl runtime`
- **Files changed:** 6, +1115/-3, 1201 diff lines total

## Files

| Path | Change |
|---|---|
| `codigo ottoguide/config/settings.py` | +16/-1 |
| `codigo ottoguide/src/interaction/cxx_runtime/CMakeLists.txt` | +52 (new) |
| `codigo ottoguide/src/interaction/cxx_runtime/src/otto_jsonl_physical_worker.cpp` | +728 (new) |
| `codigo ottoguide/src/interaction/cxx_runtime/vendor/wav.hpp` | +232 (new, vendored third-party) |
| `codigo ottoguide/src/interaction/runtime_factory.py` | +7/-2 |
| `codigo ottoguide/tests/unit/test_mvp_ia_cxx_r1_physical_runtime.py` | +83 (new) |

## Message summary

Adds a new `cxx_jsonl_physical` interaction backend: a native C++ worker (`otto_jsonl_physical_worker.cpp`) that drives the real audio stack (UDP multicast mic → Whisper GPU STT → Ollama LLM → Piper TTS → Unitree `AudioClient` `PlayStream`/`PlayStop`) behind the existing `WorkerCommandEnvelope`/`WorkerEventEnvelope` JSONL protocol. Commit message states it reuses the proven logic/constants of the protected `otto_pipeline.cpp` (a separate new file, not an edit of the protected one) and explicitly disclaims linking any locomotion/posture/FSM API.

Settings changes extend `INTERACTION_RUNTIME_BACKEND` from `Literal["disabled", "cxx_jsonl_mock"]` to include `"cxx_jsonl_physical"`, with a new validation branch requiring `INTERACTION_WORKER_PATH` to be non-empty when that backend is selected, and inline commentary noting this new backend is not gated by the mock-in-real interlock (it is genuinely physical, not a test double).

`runtime_factory.py` change resolves `cxx_jsonl_physical` to the same `JsonlInteractionWorkerSupervisor` used by the mock backend (stated as "no duplication" in the commit message) — mock/physical distinction is claimed to remain evidence-grounded downstream (`main.py`: `mock=(backend==cxx_jsonl_mock)`; router: `physical=(not mock) AND capabilities.physical_playback`).

CMake adds an `OTTO_BUILD_PHYSICAL_WORKER` target, default `OFF`, so the offline/protocol build stays hardware-free by default.

## Verification performed during this audit (offline, this session)

- **Locomotion/motion symbol scan** of the full diff (`LocoClient`, `MotionSwitcher`, `StopMove`, `BalanceStand`, `SetFsmId`, `cmd_vel`, `Damp(`): the only match found was the comment line in the new `.cpp` file's header explicitly *disclaiming* those symbols are linked — **zero actual introductions**.
- **Protected file check:** `otto_pipeline.cpp` does not appear in this commit's file list; confirmed separately (see main task report) that its SHA-256 in the working tree matches the expected value exactly, both before and after this audit.
- Diff reviewed line-by-line for the `settings.py` and `runtime_factory.py` hunks (see excerpt captured during this session); consistent with the commit message's description.

## Physical evidence status of claims in the commit message

The commit message asserts: "Verified on the Jetson: builds aarch64, links AudioClient+Whisper (no motion symbols), start/health/close protocol smoke clean, and a live no-motion voice interaction completed."

Per this task's evidence-precedence rules, this assertion is **REPORTED_BY_OPERATOR / REPORTED_BY_AGENT** at the commit-message level — it is not itself raw evidence recoverable from Git objects alone. Corroborating raw evidence (build logs, protocol smoke transcripts, live interaction transcript) is expected to live in the harvest artifacts (`FINAL_ROBOT_HARVEST_R1_PRIORITY_CORE.zip` / `..._DATA.tar.gz`), which were independently hash-verified in this session's Phase A (see `docs/audits/master_offline_r1/PHYSICAL_COMMITS_VERDICT.md`). This audit does not re-derive that corroboration file-by-file; it records the claim's provenance and status honestly rather than asserting it as directly verified here.

## Known gaps

See `MVP_IA_CXX_R1_KNOWN_GAPS.md` — this commit introduces the runtime whose gaps are catalogued there. Gaps are documented, not fixed, per this task's explicit scope.

## Verdict contribution

This commit is well-scoped to its stated purpose (introduce the physical backend without touching the protected file or motion APIs), and no evidence contradicting that scope was found during this offline audit. See `PHYSICAL_COMMITS_VERDICT.md` for the combined verdict across both commits.
