# MVP Offline Completion Matrix

Built during `MASTER-OFFLINE-R1-LOCAL-R1`. Covers what is implemented, what has offline evidence, and what genuinely still requires a future physical robot session — without inflating any offline result into a physical claim.

| Capability | Implementation status | Physical evidence | Offline evidence | Fixture available | Offline work possible | Remaining work | Future physical validation | Priority | Blocking dependency |
|---|---|---|---|---|---|---|---|---|---|
| Lowstate telemetry capture | Implemented (harvested) | Yes (299-record harvest, hash-verified) | Yes (21/21 replay tests) | Yes (`lowstate_harvest_r1/`) | Yes | Extend replay to multi-window/multi-mode fixtures | Capture a longer, multi-mode session | Medium | None |
| Lowstate offline replay | Implemented (this task) | N/A (offline tool) | Yes (21/21 tests) | Uses lowstate fixture | Yes | Wire into a test double for WebSocket/telemetry integration tests (not done in this task) | N/A | High | Interaction/telemetry integration decision |
| cxx_jsonl_physical interaction backend | Implemented (`0d14de6`) | Partial (binary present, hash-verified; on-Jetson build/smoke claims are commit-message assertions) | Yes (unit tests pass) | N/A | Yes, for protocol-level work | Address known gaps (see `MVP_IA_CXX_R1_KNOWN_GAPS.md`) | Re-verify build/link/smoke on Jetson; live no-motion interaction | High | Jetson access |
| Interaction runtime UI gating | Implemented (`3da2e9a`) | N/A (frontend) | Yes (4 new + existing frontend tests pass) | N/A | Yes | None identified this session | Confirm against a live backend reporting real `physical`/`ready` | Medium | Backend live status endpoint |
| Emergency stop contract | Implemented (upstream) | N/A (unit-tested via fake orchestrator) | Yes (offline test + this task's contract fixture) | Yes (`emergency_response.json`) | Yes | None for the contract shape itself | Physical StopMove execution and timing | High | Robot session |
| SIGTERM graceful shutdown | Implemented (upstream) | No (test skipped on Windows) | No (not executed this session) | Yes (`sigterm_claims.json`, pointer only) | Only on Linux/WSL | Run the existing test on a Linux/WSL host | Verify on Jetson under real process supervision | Medium | Linux/WSL execution environment |
| Posture preservation | Implemented (upstream) | N/A (unit-tested) | Yes (4/4 pass) | N/A | Yes | None identified this session | Physical StopMove behavior under load | High | Robot session |
| Wake word / STT / LLM / TTS / speaker | Partially implemented (upstream, with known gaps) | No | Partial (dependencies installed, not exercised) | Partial (`ws_interaction_sequence.jsonl` synthetic only) | Limited (protocol-shape only, not actual audio) | Address `MVP_IA_CXX_R1_KNOWN_GAPS.md` items 1-11 | Full live voice interaction cycle | High (gaps), Medium (offline work) | Audio hardware / models |
| Energy / BMS / foot force telemetry | Not implemented (data genuinely absent from source) | No | No | N/A | No -- data does not exist in the harvested message type | Confirm whether a different Unitree topic exposes this data | Capture from the correct topic if one exists | Low | Robot access + protocol research |
| IMU telemetry | Implemented (harvested) | Yes (present in all 299 records) | Yes (replay tests assert presence) | Yes (part of lowstate fixture) | Yes | None identified this session | Longer-duration capture across more motion states | Low | None |
| Vision / QR | Not implemented (this task's scope) | No | No | No | Unknown, not assessed | Full design and implementation | Camera-based validation | Deferred | Out of this task's scope |
| Odometry / TF | Not implemented (this task's scope) | No | No | No | Unknown, not assessed | Full design and implementation | Robot session | Deferred | Out of this task's scope |
| Mapping / Localization | Not implemented (this task's scope) | No | No | No | Unknown, not assessed | Full design and implementation | Robot session | Deferred | Out of this task's scope |
| Nav2 | Not implemented (this task's scope) | No | No | No | Unknown, not assessed | Full design and implementation | Robot session | Deferred | Out of this task's scope |
| Movement / autonomous navigation | Not implemented, not validated anywhere in this task | No | No | No | N/A | N/A -- explicitly out of scope | Requires a dedicated future physical session | Deferred | Out of this task's scope; **never declare validated from offline work** |

## Explicit non-claim

This matrix does not declare autonomous navigation, movement, mapping, localization, or Nav2 as validated, implemented, or ready for physical testing. Those rows are marked `Not implemented (this task's scope)` precisely because this task never touched that code.
