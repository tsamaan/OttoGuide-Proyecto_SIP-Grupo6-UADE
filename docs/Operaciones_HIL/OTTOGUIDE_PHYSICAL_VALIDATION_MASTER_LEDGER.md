# OttoGuide Physical Validation Master Ledger

Reconciled during `MASTER-OFFLINE-R1-CORRECTION-R1`, on top of the physical audit branch tip (`3da2e9a`, parent chain `254cddd → 0d14de6 → 3da2e9a → bed9e01 → b41559d`).

**Correction note:** the prior version of this ledger (written during `MASTER-OFFLINE-R1-LOCAL-R1`) used only evidence generated within that single checkpoint's own session and, for several domains, conflated "this checkpoint did not execute X" with "the project has not validated X." This revision separates those two questions explicitly and incorporates real raw evidence found in five prior physical/consolidation runs under `OttoGuide-Agent-Runs` (`FINAL_MVP_R2_EXPEDITED/run_20260714T185718Z`, `MVP_IA_CXX_R1/run_20260714T194651Z`, `FINAL_ROBOT_HARVEST_R1/run_20260714T203807Z`, `MIRROR_STAGING_MVP_IA_CXX_R1_R0/run_20260715T005710Z`, `FINAL_SAFETY_R1_R3_OFFLINE_CANONICAL/run_20260714T033823Z`), all five verified to exist and read directly during this reconciliation.

## Vocabulary

**Project classification:** `PHYSICALLY_VALIDATED`, `PHYSICAL_EVIDENCE_HARVESTED`, `OFFLINE_VALIDATED`, `IMPLEMENTED_NOT_PHYSICALLY_VALIDATED`, `NOT_IMPLEMENTED`, `REQUIRES_FUTURE_ROBOT`, `REJECTED_OR_SUPERSEDED`, `UNKNOWN`.

**This checkpoint's activity** (`MASTER-OFFLINE-R1-CORRECTION-R1` specifically): `EXECUTED`, `NOT_EXECUTED_NO_ROBOT`, `STATICALLY_INSPECTED`, `REPLAYED_OFFLINE`, `TESTED_OFFLINE`, `NOT_IN_SCOPE`.

**Evidence level:** `RAW_LOG`, `RAW_RESPONSE`, `OPERATOR_ATTESTATION`, `HASH_VERIFIED_ARTIFACT`, `COMMIT_EXACT`, `OFFLINE_TEST`, `REPORTED_BY_AGENT`, `REPORTED_BY_USER`, `INFERRED`, `UNKNOWN`.

No entry below asserts autonomous navigation as validated. No replay, mock, or offline test result from this or any checkpoint is elevated to a physical-evidence project classification without raw log, raw response, marker count, or operator attestation backing it.

---

## Git (baseline chain)

- **project_classification:** N/A (structural, not a physical-validation domain)
- **this_checkpoint_activity:** EXECUTED
- **evidence_level:** RAW_LOG (git command output)
- **source_paths:** this checkpoint's own `git ls-remote`/`git rev-parse` output; `FINAL_SAFETY_R1_R3_OFFLINE_CANONICAL/run_20260714T033823Z/CANONICAL_AND_MIRROR_ATTESTATION.txt`
- **limitations:** verified at read time only; refs could drift after this ledger is written.

## Hardware adapter (real/mock/sim selection)

- **project_classification:** OFFLINE_VALIDATED
- **this_checkpoint_activity:** TESTED_OFFLINE (24/24 `test_settings.py` pass)
- **evidence_level:** OFFLINE_TEST
- **source_paths:** this checkpoint's baseline test run; `FINAL_SAFETY_R1_R3_OFFLINE_CANONICAL/run_20260714T033823Z/FOCUSED_TEST_MATRIX.md` (`test_real_adapter_network_interface.py` 7/7 pass)
- **limitations:** no adapter behavior against live hardware was exercised by any offline checkpoint; adapter's `LocoClient()`/`ChannelFactoryInitialize` calls are structurally present but only reachable in `ROBOT_MODE=real`, never exercised this way offline.

## DDS

- **project_classification:** IMPLEMENTED_NOT_PHYSICALLY_VALIDATED
- **this_checkpoint_activity:** NOT_IN_SCOPE (cyclonedds installed only as a Python import dependency; zero DDS traffic sent or received)
- **evidence_level:** HASH_VERIFIED_ARTIFACT (worker binary links `libddsc.so.0`/`libddscxx.so.0`, per raw `ldd` output)
- **source_paths:** `MVP_IA_CXX_R1/run_20260714T194651Z/CXX_LINKAGE.txt`; this checkpoint's venv install log
- **limitations:** the harvested `rt/lowstate` subscription (see Lowstate below) is real DDS-derived data captured on the robot, but this checkpoint never opens a DDS channel itself; no live DDS session was ever established or observed end-to-end within any offline checkpoint's own execution.

## Web (frontend)

- **project_classification:** OFFLINE_VALIDATED
- **this_checkpoint_activity:** TESTED_OFFLINE (51/51 pass, build succeeds)
- **evidence_level:** OFFLINE_TEST
- **source_paths:** this checkpoint's `npm test`/`npm run build`; `MVP_IA_CXX_R1/run_20260714T194651Z/FRONTEND_TESTS.txt`, `FRONTEND_BUILD.txt` (51 passed / 0 failed, exit 0)
- **limitations:** not run against a live backend or real browser by any offline checkpoint.

## WebSocket

- **project_classification:** OFFLINE_VALIDATED (contract only)
- **this_checkpoint_activity:** TESTED_OFFLINE
- **evidence_level:** OFFLINE_TEST
- **source_paths:** `ws_lowstate_frame.json`, `ws_interaction_sequence.jsonl` fixtures and replay's `--output websocket-compatible` mode
- **limitations:** no live WebSocket transport was exercised by any offline checkpoint; `MVP_IA_CXX_R1/run_20260714T194651Z/PHYSICAL_BACKEND.log` shows a real `WebSocket /ws/telemetry [accepted]` connection during a live session, but that is evidence of the production telemetry socket working on the robot, not evidence about this repository's offline replay/fixture contract matching it byte-for-byte.

## Emergency (stop)

- **project_classification:** **PHYSICALLY_VALIDATED**
- **this_checkpoint_activity:** NOT_EXECUTED_NO_ROBOT (this checkpoint only re-derived the offline unit-test contract; the physical event below predates it)
- **evidence_level:** RAW_RESPONSE + OPERATOR_ATTESTATION
- **source_paths:** `FINAL_MVP_R2_EXPEDITED/run_20260714T185718Z/P1_EMERGENCY_RESPONSE.json`, `P1_OPERATOR_ATTESTATION.txt`
- **source_hashes:** N/A (raw JSON/text logs, not hash-manifested individually in that run)
- **detail:** real `POST /emergency` (`reason=web_operator`) on backend PID 5948, 2026-07-15T03:24:08Z. Response markers: `stopmove_emit=1`, `stopmove_success=1`, `direct_hardware_fallback_used=0`, `programmatic_damp=0`, `nonzero_motioncommand=0`, `posture_command=0`, `emergency_completed=1`, `terminal_safe=true`, `posture_preserved=true`. Operator (lucas.capatti, present) attested no non-null movement, no postural change, no fall/instability, hardstop not needed, consistent with the software markers.
- **limitations:** operator attestation is a human report, not an independent sensor log; no IMU/motor telemetry was captured simultaneously with this specific event to cross-verify "joints loose" beyond the operator's own observation.
- **downstream offline fixture:** `emergency_response.json` in this repository derives its *shape* from an offline unit test with a fake orchestrator, not from this physical event — see Phase E provenance correction; it must not claim `physical_evidence_derived`.

## SIGTERM

- **project_classification:** **PHYSICALLY_VALIDATED**
- **this_checkpoint_activity:** NOT_EXECUTED_NO_ROBOT (`test_sigterm_graceful_shutdown.py` remains skipped on this Windows host, as in the prior checkpoint)
- **evidence_level:** RAW_LOG (WSL test execution) + RAW_RESPONSE (independent process-exit log) + OPERATOR_ATTESTATION
- **source_paths:** `FINAL_SAFETY_R1_R3_OFFLINE_CANONICAL/run_20260714T033823Z/SIGTERM_TEST_WSL.log` (`test_sigterm_exits_without_sigkill_and_runs_stopmove_once PASSED`, 1 passed in 3.23s, platform linux/WSL Ubuntu-24.04); `FINAL_MVP_R2_EXPEDITED/run_20260714T185718Z/P2_PROCESS_EXIT.txt`, `P2_OPERATOR_ATTESTATION.txt`; `MVP_IA_CXX_R1/run_20260714T194651Z/PHYSICAL_BACKEND.log` (independent graceful-shutdown sequence on backend PID 14638, `StopMove ejecutado correctamente`, `terminal_safe=True`)
- **detail:** the exact test this checkpoint's `sigterm_claims.json` pointed at as "unexecuted on this host" was, in a prior checkpoint, executed and passed on WSL/Linux. Separately, an independent fresh-backend SIGTERM test (PID 8938, no prior `/emergency` call) showed a single SIGTERM producing a clean graceful shutdown in ~2s with `StopMove emit=1, success=1`, no Damp, no nonzero motion, no posture command, no SIGKILL. A third, independent instance of the same shutdown sequence appears in `PHYSICAL_BACKEND.log` from a live interaction session's own teardown.
- **limitations:** all three pieces of corroboration come from prior checkpoints, not from an execution within this specific checkpoint (this Windows host still cannot run the WSL-gated test itself); the correction here is to the *project*-level classification, not a claim that this checkpoint personally re-executed it.
- **downstream offline fixture:** `sigterm_claims.json` in this repository must be corrected to distinguish the offline-test pointer (still accurate: the test is genuinely skipped in *this checkpoint's own* environment) from the project-level fact that the behavior has been physically validated elsewhere — see Phase E.

## Posture preservation

- **project_classification:** PHYSICALLY_VALIDATED
- **this_checkpoint_activity:** TESTED_OFFLINE (4/4 `test_posture_preserving_authority.py` pass, this checkpoint)
- **evidence_level:** OFFLINE_TEST + RAW_RESPONSE (P1/P2 marker data) + STATICALLY_INSPECTED (source audit)
- **source_paths:** this checkpoint's baseline; `FINAL_MVP_R2_EXPEDITED/run_20260714T185718Z/P1_EMERGENCY_RESPONSE.json` and `P2_PROCESS_EXIT.txt` (`posture_command=0`/`Damp=0`/`programmatic_damp=0` in both real events); `FINAL_SAFETY_R1_R3_OFFLINE_CANONICAL/run_20260714T033823Z/STATIC_POSTURE_AUTHORITY_AUDIT.json` (204 total posture-API regex matches across the codebase; 203 in vendored libs, exactly 1 in a productive path — `heartbeat_.Start()`, a timer/thread start correctly triaged as a false positive, not `LocoClient.Start()`)
- **limitations:** the static audit is a regex-based scan, not a formal proof of unreachability; it is corroborated (not superseded) by the two independent physical events showing zero posture-command markers in practice.

## Interaction protocol (JSONL worker command/event envelopes)

- **project_classification:** OFFLINE_VALIDATED (protocol) + PHYSICAL_EVIDENCE_HARVESTED (protocol observed live on the robot)
- **this_checkpoint_activity:** TESTED_OFFLINE (17/17 combined unit+integration pass, this checkpoint's baseline)
- **evidence_level:** OFFLINE_TEST + RAW_LOG
- **source_paths:** this checkpoint's baseline; `MVP_IA_CXX_R1/run_20260714T194651Z/CXX_PROTOCOL_EVENTS.jsonl` (real `command_accepted`/`ready`/`closed` sequence from the physical worker, capabilities `{"audio_capture":true,"wake_word":true,"vad":true,"stt":true,"local_llm":true,"spanish_tts":true,"physical_playback":true,"physical_playback_stop":true,"physical_playback_completion":true}`)
- **limitations:** the offline tests exercise the protocol shape without a real worker process; the raw `CXX_PROTOCOL_EVENTS.jsonl` is real but from a smoke-test invocation (start/health/close), not a full interaction cycle.

## Physical C++ worker

- **project_classification:** PHYSICALLY_VALIDATED (build/link/GPU-load) + IMPLEMENTED_NOT_PHYSICALLY_VALIDATED (full end-to-end voice cycle, pending operator transcript confirmation — see Wake word/STT/LLM/TTS/Speaker below)
- **this_checkpoint_activity:** NOT_EXECUTED_NO_ROBOT (aarch64 binary was only statically inspected for hash purposes in the prior checkpoint, not executed; not touched at all in this checkpoint)
- **evidence_level:** RAW_LOG (build log, `ldd`/`file` output) + HASH_VERIFIED_ARTIFACT
- **source_paths:** `MVP_IA_CXX_R1/run_20260714T194651Z/CXX_BUILD_LOG.txt` (real Whisper GPU model load log, CUDA0 backend, `[physical_worker] boot: whisper loaded on GPU`, `[physical_worker] capture: UDP multicast 239.168.123.161:5555`), `CXX_LINKAGE.txt` (real `file`/`ldd` output: ELF 64-bit ARM aarch64, linked against `libwhisper.so.1`, `libddsc.so.0`, `libddscxx.so.0`, standard C/C++ libs -- **no Unitree motion/locomotion library in the link list**); `FINAL_ROBOT_HARVEST_R1_PRIORITY_CORE.zip`/`_DATA.tar.gz` (hash-verified, contain a copy of the same binary)
- **limitations:** the raw build/link log confirms the binary was built and linked on the Jetson and loaded its Whisper model on GPU; it does not by itself prove a full audio capture -> STT -> LLM -> TTS -> playback cycle completed (see the Wake word/STT/LLM/TTS/Speaker entry for that, which is evidence-level lower due to a pending operator transcript).

## Wake word / STT / local LLM / TTS / physical speaker (voice interaction cycle)

- **project_classification:** IMPLEMENTED_NOT_PHYSICALLY_VALIDATED (human-confirmed content) + PHYSICAL_EVIDENCE_HARVESTED (software-observed session completion)
- **this_checkpoint_activity:** NOT_IN_SCOPE
- **evidence_level:** RAW_LOG (software correlate) + REPORTED_BY_USER (attestation, **explicitly PENDING**, not completed)
- **source_paths:** `MVP_IA_CXX_R1/run_20260714T194651Z/INTERACTION_EVENTS.jsonl` (`interaction_id=standalone:2`: `active` [wake+capture+STT+LLM] -> `playback` [Piper TTS -> AudioClient PlayStream physical speaker] -> `completed` [`last_event=playback_completed`]); `PHYSICAL_BACKEND.log` (orchestrator log line "Interaccion standalone completada. interaction_id=standalone:2" at 2026-07-15T04:16:50 UTC); `INTERACTION_START_RESPONSE.json` (HTTP 202, `runtime_mock=false`, `runtime_backend=cxx_jsonl_physical`); `OPERATOR_AUDIO_ATTESTATION.txt`
- **critical finding:** `OPERATOR_AUDIO_ATTESTATION.txt` explicitly states `STATUS: PENDING operator confirmation` and both `Transcript` and `Response` fields are literally `<PENDING>`. The requested attestation text ("OTTO RECONOCIO 'HOLA OTTO'. ESCUCHO MI CONSULTA. RESPONDIO POR EL PARLANTE FISICO...") was never confirmed by the operator in this evidence set.
- **exact transcript text:** UNAVAILABLE (per this reconciliation's mandatory constraint)
- **exact response text:** UNAVAILABLE (per this reconciliation's mandatory constraint)
- **limitations:** a prior interaction attempt (`standalone:1`, from the live Web UI button) timed out at the wake-word stage and the runtime recovered to ready without a double-start; `standalone:2` (started via a second `curl` request while `standalone:1` was still pending correctly returned 409, confirming no double-start) reached `playback_completed` per software logs alone, but there is no confirmed human observation that the audio content was correct, was actually audible, or matched the claimed wake-word/transcript/response text. This must not be elevated to `PHYSICALLY_VALIDATED` on the strength of the software log alone.

## Lowstate

- **project_classification:** PHYSICAL_EVIDENCE_HARVESTED + OFFLINE_VALIDATED (replay)
- **this_checkpoint_activity:** REPLAYED_OFFLINE (38/38 tests pass post-correction, this checkpoint)
- **evidence_level:** HASH_VERIFIED_ARTIFACT + OFFLINE_TEST
- **source_paths:** `FINAL_ROBOT_HARVEST_R1_PRIORITY_CORE.zip` (hash-verified); `FINAL_ROBOT_HARVEST_R1/run_20260714T203807Z/02_lowstate/` (same dataset, corroborating source); this checkpoint's fixture and replay tests
- **source_hashes:** CORE `2f94536be0a6e8bd1cd20f2d75d98044d0a132b8795cf691c8ba200b9c87f4b4`; fixture `lowstate_10hz.jsonl` `f377c2ef3cc2659a109c66217b9ac9928e95dcf495caa624935ceaaf19e1d74f`
- **limitations:** 299 records, single ~30s window, `mode_machine=5` only; not a continuous or multi-mode recording.

## Energy / BMS / Foot force

- **project_classification:** NOT_IMPLEMENTED (data genuinely absent from the harvested message type, not an omission by any checkpoint)
- **this_checkpoint_activity:** NOT_IN_SCOPE
- **evidence_level:** HASH_VERIFIED_ARTIFACT (`field_availability.json` shows `false` for all three, consistently, across both this checkpoint's fixture and the original harvest run's copy)
- **source_paths:** `tests/fixtures/physical/lowstate_harvest_r1/field_availability.json`; `FINAL_ROBOT_HARVEST_R1/run_20260714T203807Z/02_lowstate/field_availability.json`
- **limitations:** confirmed absent specifically from `rt/lowstate` on this G1 EDU unit; a different Unitree topic might expose this data, unresearched.

## IMU

- **project_classification:** PHYSICAL_EVIDENCE_HARVESTED
- **this_checkpoint_activity:** REPLAYED_OFFLINE
- **evidence_level:** HASH_VERIFIED_ARTIFACT
- **source_paths:** lowstate fixture, `imu` field present in all 299 records
- **limitations:** single capture window; orientation/motion range limited to what these 299 samples show.

## Camera / QR / Livox / Odometry / TF / Mapping / Localization / Nav2

- **project_classification:** NOT_IMPLEMENTED (this repository's tracked source) — **dynamic odometry: UNRESOLVED; physical TF: UNRESOLVED; physical map: NOT_VALIDATED; physical localization: NOT_VALIDATED; physical Nav2: NOT_VALIDATED**
- **this_checkpoint_activity:** NOT_IN_SCOPE
- **evidence_level:** UNKNOWN (no source files reviewed by this reconciliation claim anything for these domains within the offline consolidation branch)
- **source_paths:** none within the audited commit chain or the five reviewed prior runs (those runs' evidence concerns interaction/telemetry/safety, not mapping/nav)
- **limitations:** this reconciliation did not search `OttoGuide-Mapping-Workspace` or other mapping-specific run trees; a real absence-of-evidence-here claim should not be read as "mapping has never been attempted anywhere in the project," only that no evidence for it appears in the five prioritized runs or the audited commit chain this checkpoint was scoped to.

## Movement / autonomous navigation

- **project_classification:** NOT_IMPLEMENTED / REQUIRES_FUTURE_ROBOT — **movement autonomy: NOT_VALIDATED, anywhere in this ledger**
- **this_checkpoint_activity:** NOT_IN_SCOPE
- **evidence_level:** N/A
- **source_paths:** N/A
- **limitations:** no locomotion code was introduced or exercised by any commit in the audited chain (`0d14de6`/`bed9e01`/`b41559d` diffs independently scanned; zero real locomotion API symbol introductions found, only a disclaiming comment). **No autonomous navigation or movement is declared validated anywhere in this ledger, at any evidence level, in this or any prior checkpoint reviewed.**

---

## Machine-readable companion

See `ottoguide_physical_validation_master_state.json` in this same directory.

## Changes from the prior version of this ledger

1. **Emergency: `OFFLINE_VALIDATED` → `PHYSICALLY_VALIDATED`** (project level). Real raw response + operator attestation found in `FINAL_MVP_R2_EXPEDITED/run_20260714T185718Z`, not reviewed by the prior checkpoint.
2. **SIGTERM: `IMPLEMENTED_NOT_PHYSICALLY_VALIDATED` → `PHYSICALLY_VALIDATED`** (project level). The prior ledger conflated "skipped on this Windows host" with "never validated" — a real WSL execution (`SIGTERM_TEST_WSL.log`, PASSED) plus two independent raw process-exit logs plus operator attestation exist in prior runs.
3. **Posture preservation: `OFFLINE_VALIDATED` → `PHYSICALLY_VALIDATED`**, now corroborated by a real static-audit artifact and by zero posture-command markers in two independent physical events, not solely by unit tests.
4. **Physical C++ worker: build/link/GPU-load specifically upgraded from `REPORTED_BY_AGENT` (commit-message text) to `RAW_LOG`** (real build log and `ldd`/`file` output found and read directly). The full end-to-end voice-interaction claim is **explicitly not upgraded** and is called out as pending human confirmation.
5. **Wake word/STT/LLM/TTS/Speaker: added as its own reconciled entry** (the prior ledger folded these into vaguer, more optimistic-sounding per-domain rows). The explicit `PENDING`/`<PENDING>` operator attestation status is now surfaced directly, and exact transcript/response text is recorded as unavailable, per this checkpoint's mandatory constraints.
6. Mapping/odometry/TF/localization/Nav2/movement rows are unchanged in substance but now explicitly carry the mandated `UNRESOLVED`/`NOT_VALIDATED` markers per-field rather than a single blanket "not implemented" note.

## Provenance note

This ledger was built from: (1) Git objects/refs verified this and prior checkpoints, (2) hash-verified harvest artifacts, (3) tests executed this checkpoint, (4) raw logs, raw HTTP responses, marker counts, and operator attestations found in five prior physical/consolidation runs under `OttoGuide-Agent-Runs`, read directly during this reconciliation (not summarized from any intermediate report), and (5) commit messages, labeled `REPORTED_BY_AGENT` only where no raw corroboration was found. No claim in this ledger was elevated to `PHYSICALLY_VALIDATED` on the strength of a report or summary alone — every such classification here points to a specific raw log, raw response, marker count, or operator attestation file that this reconciliation opened and read.
