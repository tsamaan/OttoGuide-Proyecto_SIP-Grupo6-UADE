# OttoGuide Physical Validation Master Ledger

Consolidated during `MASTER-OFFLINE-R1-LOCAL-R1`, on top of the physical audit branch tip (`3da2e9a`, parent chain `254cddd → 0d14de6 → 3da2e9a`, all three refs independently verified via `git ls-remote` and structurally via `git rev-parse` against a fresh clone in this session).

Classification vocabulary used throughout: `PHYSICALLY_VALIDATED`, `PHYSICAL_EVIDENCE_HARVESTED`, `OFFLINE_VALIDATED`, `IMPLEMENTED_NOT_PHYSICALLY_VALIDATED`, `NOT_IMPLEMENTED`, `REQUIRES_FUTURE_ROBOT`, `REJECTED_OR_SUPERSEDED`.

No entry below asserts autonomous navigation as validated. No replay, mock, or offline test result is elevated to physical evidence.

| Domain | Classification | Claim | Source | Limitations |
|---|---|---|---|---|
| Git (baseline chain) | `VERIFIED` (structural, not itself a "physical validation" category but foundational) | `254cddd → 0d14de6 → 3da2e9a` parent chain confirmed; canonical review, mirror review, mirror audit refs all match expected SHAs | `git ls-remote` (3 refs) + `git rev-parse HEAD/HEAD^/HEAD^^` against a fresh clone, this session | Verified once, this session; refs could drift after this ledger is written |
| Hardware adapter | `IMPLEMENTED_NOT_PHYSICALLY_VALIDATED` | Real/mock/sim adapter selection exists and is unit-tested (`test_settings.py`, 24/24 pass this session) | Baseline test run, this session | No adapter behavior against live hardware was exercised in this task |
| DDS | `NOT_IMPLEMENTED` (in this task's scope) | This task never imports `cyclonedds` for actual DDS traffic; `cyclonedds` is installed only as a Python dependency required for production module import compatibility | This session's venv install log | Zero DDS packets sent or received during this task |
| Web (frontend) | `OFFLINE_VALIDATED` | 51/51 frontend tests pass; `vite build` succeeds (2394 modules) | `npm test` / `npm run build`, this session | Not run against a live backend or browser in this task |
| WebSocket | `OFFLINE_VALIDATED` (contract only) | `ws_lowstate_frame.json` and `ws_interaction_sequence.jsonl` fixtures define offline-only contract shapes; the replay tool's `--output websocket-compatible` mode produces the same envelope shape but is never connected to a real socket | This task's Phase E/F fixtures and tests | No live WebSocket transport was exercised; this is a data-contract validation only |
| Emergency (stop) | `OFFLINE_VALIDATED` | `POST /emergency` 200 response contract (`executed`, `terminal_safe`, `stop_motion_succeeded`, `posture_preserved`, etc.) grounded in `test_emergency_safe_stop_returns_200_with_terminal_safe_true`, executed and passing in this session's baseline | `tests/integration/test_api_router_canonical.py`, this session's baseline run | Test uses a fake orchestrator (`_EmergencyOrchestrator`), not a physical robot |
| SIGTERM | `IMPLEMENTED_NOT_PHYSICALLY_VALIDATED` | `test_sigterm_exits_without_sigkill_and_runs_stopmove_once` asserts `StopMove` invoked exactly once on SIGTERM | `tests/integration/test_sigterm_graceful_shutdown.py` | Test is explicitly skipped on this Windows host ("exercised on Linux/WSL"); not executed in this task's baseline. See `sigterm_claims.json`. |
| Posture preservation | `OFFLINE_VALIDATED` | `test_posture_preserving_authority.py` (4/4 pass, this session): `StopMove` invoked exactly once, no posture command in the initialize path, timeout bounded, no programmatic posture methods exposed | This session's baseline run | Unit-level, no physical actuation observed |
| Interaction protocol | `OFFLINE_VALIDATED` | `WorkerCommandEnvelope`/`WorkerEventEnvelope` protocol (see `runtime_port.py`) exercised by `test_mvp_r0_standalone_interaction.py` (10/10 pass) and `test_mvp_r0_interaction_endpoint.py` (7/7 pass) | This session's baseline run | No physical worker process was spawned or connected to real hardware |
| Physical C++ worker | `PHYSICAL_EVIDENCE_HARVESTED` (build artifact only) | `otto_jsonl_physical_worker_aarch64` binary exists in the harvest (CORE and DATA), hash-verified; commit `0d14de6`'s message claims on-Jetson build/link/smoke success | `FINAL_ROBOT_HARVEST_R1_PRIORITY_CORE.zip` / `_DATA.tar.gz`, both SHA-256 verified this session; commit message text | Binary was only statically present in the harvest, never executed in this task (aarch64, execution explicitly prohibited on this Windows host); on-Jetson claims are `REPORTED_BY_OPERATOR`/`REPORTED_BY_AGENT` per this task's evidence precedence, not independently re-derived here |
| Wake word | `IMPLEMENTED_NOT_PHYSICALLY_VALIDATED` | `WorkerEventType.WAKE_WORD_CONFIRMED` exists in the protocol; exercised only via the synthetic `ws_interaction_sequence.jsonl` contract fixture in this task | This task's Phase F fixture | No physical audio wake-word detection was performed |
| STT | `NOT_IMPLEMENTED` (this task's scope) / `IMPLEMENTED_NOT_PHYSICALLY_VALIDATED` (upstream) | `faster-whisper` is a declared dependency, installed in this session's venv; not exercised by this task | `pyproject.toml`, install log | This task performs no audio transcription |
| LLM | `NOT_IMPLEMENTED` (this task's scope) | Ollama client code exists upstream (known-gaps doc notes its fragility); not exercised by this task | `MVP_IA_CXX_R1_KNOWN_GAPS.md` | No LLM calls made in this task |
| TTS | `NOT_IMPLEMENTED` (this task's scope) | `piper-tts` installed in this session's venv as a dependency; 8 pre-existing test failures in `test_conversation_playback_lifecycle.py` trace to a hardcoded Unix Piper voice path absent on Windows (documented, not fixed) | `TEST_BASELINE_RESULTS.json`, this session | This task does not touch TTS synthesis code |
| Speaker (playback) | `NOT_IMPLEMENTED` (this task's scope) | `playback_started`/`playback_completed` events exist in the protocol and in the synthetic sequence fixture; known gap #8/#9 (in `MVP_IA_CXX_R1_KNOWN_GAPS.md`) notes completion is time-estimated, not hardware-observed | Known-gaps doc | No physical audio was played in this task |
| Lowstate | `PHYSICAL_EVIDENCE_HARVESTED` + `OFFLINE_VALIDATED` (replay) | 299 records, `receipt_monotonic_ns`/`tick` strictly increasing, ~9.94Hz, 35 motor states received / 29 persisted-named, `power_v`/`power_a`/`bms_state`/`foot_force` consistently null (never fabricated as 0) | `FINAL_ROBOT_HARVEST_R1_PRIORITY_CORE.zip` (hash-verified), replayed offline by `lowstate_replay.py` (21/21 tests pass, this session) | Single ~30s capture window at `mode_machine=5`; not a continuous or multi-mode recording |
| Energy | `NOT_IMPLEMENTED` (data absent) | N/A — `power_v`/`power_a` fields are absent from the harvested `rt/lowstate` message on this G1 EDU unit | Lowstate fixture `field_availability.json` | Genuinely absent from the source telemetry, not an omission of this task |
| BMS | `NOT_IMPLEMENTED` (data absent) | N/A — `bms_state` absent from harvested telemetry | Lowstate fixture | Same as Energy |
| Foot force | `NOT_IMPLEMENTED` (data absent) | N/A — `foot_force` absent from harvested telemetry | Lowstate fixture | Same as Energy |
| IMU | `PHYSICAL_EVIDENCE_HARVESTED` | Quaternion, gyroscope, accelerometer, rpy, temperature present and populated in every one of the 299 harvested records | Lowstate fixture (`imu` field, present=true in every record per this task's replay tests) | Single capture window; orientation/motion range during capture unknown beyond what these 299 samples show |
| Camera | `NOT_IMPLEMENTED` (this task's scope) | Not touched by this task | — | — |
| QR | `NOT_IMPLEMENTED` (this task's scope) | Not touched by this task | — | — |
| Livox | `NOT_IMPLEMENTED` (this task's scope) | Not touched by this task | — | — |
| Odometry | `NOT_IMPLEMENTED` (this task's scope) | Not touched by this task | — | — |
| TF | `NOT_IMPLEMENTED` (this task's scope) | Not touched by this task | — | — |
| Mapping | `NOT_IMPLEMENTED` (this task's scope) | Not touched by this task | — | — |
| Localization | `NOT_IMPLEMENTED` (this task's scope) | Not touched by this task | — | — |
| Nav2 | `NOT_IMPLEMENTED` (this task's scope) | Not touched by this task | — | — |
| Movement | `NOT_IMPLEMENTED` / `REQUIRES_FUTURE_ROBOT` | No locomotion code introduced or exercised; `0d14de6`/`3da2e9a` diffs independently scanned and contain zero real locomotion API symbol introductions (only a disclaiming comment) | This session's Phase C commit audit | Explicitly out of scope; **no autonomous navigation or movement is declared validated anywhere in this ledger** |

## Machine-readable companion

See `ottoguide_physical_validation_master_state.json` in this same directory for the structured equivalent of this table.

## Provenance note

This ledger was built exclusively from: (1) Git objects/refs verified this session, (2) the hash-verified harvest artifacts (CORE/DATA), (3) tests actually executed this session (see `docs/audits/master_offline_r1/` and the Phase C test baseline), and (4) commit messages, explicitly labeled as operator/agent-reported where their claims could not be independently re-derived from raw logs within this task. No workspace history, prior informal report, or narrative summary was used as a substitute for these sources.
