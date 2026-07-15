# OttoGuide Physical Validation Master Ledger

Reconciled during `MASTER-OFFLINE-R1-RELEASE-READINESS-R1`, on top of `MASTER-OFFLINE-R1-CORRECTION-R1`'s checkpoint (`c68032d`, parent chain `254cddd → 0d14de6 → 3da2e9a → bed9e01 → b41559d → 4caecd9 → c68032d`).

**Correction note (CORRECTION-R1):** the prior version of this ledger (written during `MASTER-OFFLINE-R1-LOCAL-R1`) used only evidence generated within that single checkpoint's own session and, for several domains, conflated "this checkpoint did not execute X" with "the project has not validated X." That revision separated those two questions explicitly and incorporated real raw evidence found in five prior physical/consolidation runs under `OttoGuide-Agent-Runs` (`FINAL_MVP_R2_EXPEDITED/run_20260714T185718Z`, `MVP_IA_CXX_R1/run_20260714T194651Z`, `FINAL_ROBOT_HARVEST_R1/run_20260714T203807Z`, `MIRROR_STAGING_MVP_IA_CXX_R1_R0/run_20260715T005710Z`, `FINAL_SAFETY_R1_R3_OFFLINE_CANONICAL/run_20260714T033823Z`), all five verified to exist and read directly during that reconciliation.

**Correction note (RELEASE-READINESS-R1):** this revision fixes a second conflation the prior ledger still had: several unrelated domains (Web, WebSocket, DDS, Camera/QR, Livox, Odometry) were each collapsed into a single row per topic, or bundled together under one blanket `NOT_IMPLEMENTED`/`NOT_IN_SCOPE` line, even though within each topic some sub-capabilities have real implementation or real physical evidence and others do not. This revision splits every such domain into its constituent sub-capabilities (e.g. `web_frontend_offline_tests` vs. `web_real_profile_control_path`; `websocket_live_transport` vs. `websocket_offline_replay_contract`; `dds_lowstate_read_path` vs. `dds_generic_runtime` vs. `dds_write_or_publish_path`; `camera_vision_runtime`/`qr_frame_detector`/`station_trigger` vs. `camera_rgb_intrinsics_e2e`/`qr_physical_e2e`; `livox_sdk2_bridge_implementation`/`livox_cloud_callback`/`livox_imu_callback`/`livox_coordinate_validation`/`scan_gate`; `odometry_candidate_adapter`/`adapter_offline_tests`/`adapter_pure_code_robot_validation` vs. `dynamic_odometry_runtime`/`odom_publication`/`tf_publication`), incorporating evidence read directly from `OttoGuide-Agent-Runs`, `OttoGuide-Mapping-Workspace`, and `OttoGuide-Workspaces` during this reconciliation. See `EVIDENCE_SOURCE_INVENTORY.md` (this checkpoint's run root) for the full source list with hashes and quoted excerpts. No `NOT_IMPLEMENTED` classification survives where verified source code or a verified commit exists for that exact sub-capability; no domain's overall row is reduced to a single `OFFLINE_VALIDATED` classification where physical raw evidence exists for part of it.

**Correction note (EVIDENCE-LEDGER-R2):** this revision incorporates evidence from `MASTER-R1`, `ROBOT-R2X`, `ROBOT-R3X`, and `ODOM-R5` runs under `OttoGuide-Mapping-Workspace` that RELEASE-READINESS-R1 had cited only partially or not at all, and separates `implementation_status` from `project_validation_status` as two independent dimensions (a capability can be `IMPLEMENTED` in source/commit while still `NOT_VALIDATED`, `OFFLINE_VALIDATED`, or `PHYSICAL_EVIDENCE_HARVESTED` at the project level — the two axes are not synonyms and must not be conflated). The Odometry, Mapping/Localization/Nav2, and Livox sections are rewritten with finer-grained sub-domains distinguishing offline-code validation from on-robot-but-stationary physical evidence capture from live dynamic runtime (never present). See `EVIDENCE_LEDGER_R2_SOURCE_INVENTORY.md` (this checkpoint's run root) for the full source list, hashes, and flagged cross-source contradictions.

## Vocabulary

**Implementation status:** `IMPLEMENTED`, `PARTIALLY_IMPLEMENTED`, `NOT_IMPLEMENTED`, `UNKNOWN`. This dimension answers only "does the code/commit exist," independent of whether it has been validated at any level.

**Project validation status:** `PHYSICALLY_VALIDATED`, `PHYSICAL_EVIDENCE_HARVESTED`, `OFFLINE_VALIDATED`, `IMPLEMENTED_NOT_PHYSICALLY_VALIDATED`, `NOT_VALIDATED`, `UNKNOWN`. This dimension answers "what has actually been validated and at what level," independent of implementation status. `NOT_IMPLEMENTED` (implementation axis) must never be used as a synonym for `NOT_VALIDATED` (validation axis) — a capability can be fully implemented and still not validated, and the converse (validated without a corresponding implementation entry) should not occur.

Legacy `project_classification` field (RELEASE-READINESS-R1 and earlier) is retained on domains not touched by this checkpoint's Phase C/D/E rewrite, for continuity; domains rewritten in this checkpoint use the explicit two-axis fields instead.

**This checkpoint's activity** (`MASTER-OFFLINE-R1-EVIDENCE-LEDGER-R2` specifically, for rewritten domains) / prior checkpoints' activity (retained on untouched domains): `EXECUTED`, `NOT_EXECUTED_NO_ROBOT`, `STATICALLY_INSPECTED`, `REPLAYED_OFFLINE`, `TESTED_OFFLINE`, `NOT_IN_SCOPE`.

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

### dds_lowstate_read_path

- **project_classification:** PHYSICAL_EVIDENCE_HARVESTED
- **this_checkpoint_activity:** NOT_EXECUTED_NO_ROBOT
- **evidence_level:** RAW_LOG
- **source_paths:** `FINAL_ROBOT_R0_OFFLINE_CONSOLIDATION/run_20260713T234047Z/extracted_dataset/continuation_r1_20260713T211007Z/backend_real.log` (`[REAL] Negociando DDS via ChannelFactoryInitialize(0)...` → `[REAL] SDK inicializado correctamente. LocoClient activo.`); the harvested `rt/lowstate` dataset itself (see Lowstate below)
- **source_hashes:** `backend_real.log` `5b58dd5c6375141f3f55dea0357ec883571d04a9b688d84da7e9d05766a04e46`
- **limitations:** confirms a real DDS channel was negotiated and read on the robot in a prior checkpoint; this offline checkpoint never opens a DDS channel itself.

### dds_generic_runtime

- **project_classification:** IMPLEMENTED_NOT_PHYSICALLY_VALIDATED
- **this_checkpoint_activity:** NOT_IN_SCOPE (cyclonedds installed only as a Python import dependency; zero DDS traffic sent or received by this checkpoint)
- **evidence_level:** HASH_VERIFIED_ARTIFACT (worker binary links `libddsc.so.0`/`libddscxx.so.0`, per raw `ldd` output)
- **source_paths:** `MVP_IA_CXX_R1/run_20260714T194651Z/CXX_LINKAGE.txt`; this checkpoint's venv install log
- **limitations:** confirms the binary is linked against DDS libraries; does not by itself confirm a runtime session.

### dds_write_or_publish_path

- **project_classification:** NOT_IMPLEMENTED
- **this_checkpoint_activity:** NOT_IN_SCOPE
- **evidence_level:** UNKNOWN
- **source_paths:** none found in any searched root
- **limitations:** no evidence of any DDS publish/write call anywhere in the searched roots. Must not be declared validated.

## Web (frontend)

### web_frontend_offline_tests

- **project_classification:** OFFLINE_VALIDATED
- **this_checkpoint_activity:** TESTED_OFFLINE (51/51 pass, build succeeds)
- **evidence_level:** OFFLINE_TEST
- **source_paths:** this checkpoint's `npm test`/`npm run build`; `MVP_IA_CXX_R1/run_20260714T194651Z/FRONTEND_TESTS.txt`, `FRONTEND_BUILD.txt` (51 passed / 0 failed, exit 0)
- **limitations:** not run against a live backend or real browser by any offline checkpoint.

### web_real_profile_control_path

- **project_classification:** PHYSICALLY_VALIDATED
- **this_checkpoint_activity:** NOT_EXECUTED_NO_ROBOT
- **evidence_level:** OPERATOR_ATTESTATION + RAW_RESPONSE
- **source_paths:** `FINAL_MVP_R2_EXPEDITED/run_20260714T185718Z/WEB_UI_BROWSER_ACCEPTANCE.txt` (real browser, real backend, "Detener" button visible/enabled, "Modo simulacion" desmarcado, "Conectado" verde, `ROBOT http://192.168.123.164:8000`); `P1_EMERGENCY_RESPONSE.json` (`trigger: web_operator (Detener button in live Web UI)`, real `POST /emergency`)
- **source_hashes:** `WEB_UI_BROWSER_ACCEPTANCE.txt` `98fe5f58b3e610495223f382d07aa4c30a5b845548e8a7a9a1f30fd50c6f4dc0`
- **limitations:** single operator session; UI described as showing "pocos datos" beyond the Detener control at the time of this observation.

## WebSocket

### websocket_offline_replay_contract

- **project_classification:** OFFLINE_VALIDATED (contract only)
- **this_checkpoint_activity:** TESTED_OFFLINE
- **evidence_level:** OFFLINE_TEST
- **source_paths:** `ws_lowstate_frame.json`, `ws_interaction_sequence.jsonl` fixtures and replay's `--output websocket-compatible` mode
- **limitations:** no live WebSocket transport was exercised by any offline checkpoint.

### websocket_live_transport

- **project_classification:** PHYSICAL_EVIDENCE_HARVESTED
- **this_checkpoint_activity:** NOT_EXECUTED_NO_ROBOT
- **evidence_level:** RAW_LOG
- **source_paths:** `MVP_IA_CXX_R1/run_20260714T194651Z/PHYSICAL_BACKEND.log` (real `WebSocket /ws/telemetry [accepted]`); independently corroborated by a second raw log, `FINAL_ROBOT_R0_OFFLINE_CONSOLIDATION/run_20260713T234047Z/extracted_dataset/continuation_r1_20260713T211007Z/backend_real.log` (6 accepted `/ws/telemetry` sessions, 1 `403 Origin no autorizado` rejection, 4 `standalone:N` interactions completed)
- **source_hashes:** `backend_real.log` `5b58dd5c6375141f3f55dea0357ec883571d04a9b688d84da7e9d05766a04e46`
- **limitations:** confirms the production telemetry socket works on the robot in two independent sessions; does not confirm this repository's offline replay/fixture contract matches it byte-for-byte.

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

## Camera / Vision / QR / Station trigger

### camera_vision_runtime / qr_frame_detector / station_trigger

- **project_classification:** IMPLEMENTED_NOT_PHYSICALLY_VALIDATED
- **this_checkpoint_activity:** STATICALLY_INSPECTED
- **evidence_level:** COMMIT_EXACT (source files confirmed present in the audited working tree)
- **source_paths:** `codigo ottoguide/src/vision/vision_processor.py`, `codigo ottoguide/src/vision/qr_frame_detector.py`, `codigo ottoguide/src/vision/station_trigger.py`, `codigo ottoguide/src/stations/station_registry.py`
- **limitations:** implementation exists and was confirmed present; no physical runtime log, RGB frame capture, or physical QR detection event was found in any of the three searched roots. Must not be classified `NOT_IMPLEMENTED`.

### camera_rgb_intrinsics_e2e / qr_physical_e2e

- **project_classification:** NOT_IMPLEMENTED
- **this_checkpoint_activity:** NOT_IN_SCOPE
- **evidence_level:** UNKNOWN
- **source_paths:** none found
- **limitations:** genuinely no evidence found for either camera RGB intrinsics end-to-end or physical QR detection anywhere searched. Distinct from the source-code sub-capability above, which does exist.

## Livox

### livox_sdk2_bridge_implementation

- **implementation_status:** IMPLEMENTED
- **project_validation_status:** IMPLEMENTED_NOT_PHYSICALLY_VALIDATED
- **this_checkpoint_activity:** STATICALLY_INSPECTED
- **evidence_level:** COMMIT_EXACT
- **source_paths:** `codigo ottoguide/ros2_ws/src/ottoguide_livox_sdk_bridge/src/livox_sdk_bridge_node.cpp` (`point_cloud_callback`, `imu_callback`, `SetLivoxLidarPointCloudCallBack`, `SetLivoxLidarImuDataCallback`)
- **limitations:** confirmed present in the audited working tree; ROS-level publication behavior not confirmed executed by the source code alone (see `livox_ros_pointcloud_publication`/`livox_ros_imu_publication` below).

### livox_raw_cloud_capture

- **project_validation_status:** PHYSICAL_EVIDENCE_HARVESTED
- **this_checkpoint_activity:** NOT_EXECUTED_NO_ROBOT
- **evidence_level:** RAW_LOG
- **source_paths:** `FINAL_ROBOT_R0_OFFLINE_CONSOLIDATION/run_20260713T234047Z/LIVOX_CAPTURE_ANALYSIS.md` (SDK2 quick-start session: 30,033 point-cloud callbacks over ~25s, real LiDAR serial `47MCN8N0035124` MID360, multicast `224.1.1.5`, no errors, robot stationary); `extracted_dataset/continuation_r1_20260713T211007Z/STATIONARY_LIVOX_DATASET/livox_quickstart_raw.log` (32,961 lines, real timestamps); independently corroborated at ROS-topic level by `route_capture_summary.json` (`/utlidar/cloud` 651,527 msgs recorded in a separate, later physical rosbag session)
- **source_hashes:** `LIVOX_CAPTURE_ANALYSIS.md` `eb97fe2cc31cda5c9df7c82e63f740dd78734073bf754d232546d4bccbcb9761`; `route_capture_summary.json` `7373cf00ac614db1abf5a6ca01785d3f45893e053fd6b85c08df6081c861fdcc`
- **limitations:** SDK2 session was raw-callback-level, not a ROS topic; the SDK2 probe was not strictly passive (negotiated master-mode device control, sent commands, received Acks) — disclosed, not hidden. `wall_clock_trusted: false` for the rosbag session (robot RTC unreliable); only monotonic duration and message counts treated as reliable there.

### livox_raw_imu_capture

- **project_validation_status:** PHYSICAL_EVIDENCE_HARVESTED
- **this_checkpoint_activity:** NOT_EXECUTED_NO_ROBOT
- **evidence_level:** RAW_LOG
- **source_paths:** `LIVOX_CAPTURE_ANALYSIS.md` (2,883 IMU callbacks over the same ~25s SDK2 session); independently corroborated at ROS-topic level by `route_capture_summary.json` (`/livox/imu` 90,753 msgs in the separate rosbag session)
- **source_hashes:** same as `livox_raw_cloud_capture`
- **limitations:** same session/caveats as `livox_raw_cloud_capture`.

### livox_ros_pointcloud_publication

- **project_validation_status:** NOT_VALIDATED
- **this_checkpoint_activity:** NOT_IN_SCOPE
- **evidence_level:** RAW_LOG (explicit non-execution disclosed in the SDK2 session) + PHYSICAL_EVIDENCE_HARVESTED (message-count evidence of `/utlidar/cloud`/`/scan` topics flowing in the separate rosbag session, which implies real ROS-level publication occurred there, though the publishing node/pipeline itself was not independently inspected)
- **source_paths:** `LIVOX_CAPTURE_ANALYSIS.md` ("ROS publication = not executed" for the SDK2 session); `route_capture_summary.json` (`/utlidar/cloud` 651,527 msgs, `/scan` 630,915 msgs recorded, implying real topic-level publication in that separate session)
- **limitations:** the SDK2 quick-start session explicitly did not publish to ROS. The separate rosbag session's message counts strongly imply real ROS publication occurred, but this reconciliation did not independently inspect the publishing node/pipeline for that session, so this is recorded as evidence of the effect (messages recorded) rather than a fully traced publication path.

### livox_ros_imu_publication

- **project_validation_status:** NOT_VALIDATED
- **this_checkpoint_activity:** NOT_IN_SCOPE
- **evidence_level:** RAW_LOG (explicit non-execution disclosed in the SDK2 session) + PHYSICAL_EVIDENCE_HARVESTED (message-count evidence of `/livox/imu` flowing in the separate rosbag session)
- **source_paths:** same as `livox_ros_pointcloud_publication`
- **limitations:** same as `livox_ros_pointcloud_publication`.

### livox_coordinate_validation

- **implementation_status:** IMPLEMENTED
- **project_validation_status:** IMPLEMENTED_NOT_PHYSICALLY_VALIDATED
- **this_checkpoint_activity:** STATICALLY_INSPECTED
- **evidence_level:** COMMIT_EXACT
- **source_paths:** `livox_sdk_bridge_node.cpp` (`drop_unsafe_dot_num`, `dry_run_drop`)
- **limitations:** implementation only; not confirmed exercised against physical out-of-range/unsafe coordinate data in any run found.

### scan_gate

- **implementation_status:** IMPLEMENTED
- **project_validation_status:** IMPLEMENTED_NOT_PHYSICALLY_VALIDATED
- **this_checkpoint_activity:** STATICALLY_INSPECTED
- **evidence_level:** COMMIT_EXACT
- **source_paths:** `docs/Operaciones_HIL/README_SCAN_GATE.md`
- **limitations:** documented gate/contract logic; not confirmed exercised in any physical run found in this reconciliation's scope.

### extrinsics_calibration

- **implementation_status:** NOT_IMPLEMENTED
- **project_validation_status:** NOT_VALIDATED
- **this_checkpoint_activity:** NOT_IN_SCOPE
- **evidence_level:** RAW_LOG (explicit placeholder confirmed)
- **source_paths:** `LIVOX_CAPTURE_ANALYSIS.md` ("extrinsics = unknown (config con extrinsic 0,0,0,0,0,0 = placeholder, no calibrado)")
- **limitations:** confirmed uncalibrated placeholder values; no calibration attempt found in any searched root.

## Odometry

### odometry_candidate_adapter_implementation

- **implementation_status:** IMPLEMENTED
- **project_validation_status:** IMPLEMENTED_NOT_PHYSICALLY_VALIDATED
- **this_checkpoint_activity:** NOT_IN_SCOPE
- **evidence_level:** COMMIT_EXACT
- **source_paths:** `OttoGuide-Mapping-Workspace/_ODOM_R5_LOCAL_COMMIT_DECISION_WITH_RUFF_GAP_NO_PUBLISH/run_20260707T203329Z/ODOM_R5_COMMIT_LOG.txt` (commit `92a8bc45a7a8d7557bcdca9ae5684692016168a7`, 12 files, 1021 insertions)
- **source_hashes:** `ODOM_R5_COMMIT_LOG.txt` `a6342c790027d7aba1ff820b8b65fb65c5a935cb33c7c3ae06342e3d310f4549`
- **limitations:** exists on branch `odom/odometry-candidate-adapter-r1`, not merged into this repository's tracked source (`C:\OG\master-offline-r1-local-r1\repo` only has `src/navigation/odom_bridge_contract.py`, a pure static contract module), never pushed anywhere.

### adapter_offline_tests

- **project_validation_status:** OFFLINE_VALIDATED
- **this_checkpoint_activity:** NOT_IN_SCOPE
- **evidence_level:** OFFLINE_TEST
- **result:** 58/58 PASS
- **source_paths:** `ODOM_R5_GO_NO_GO_DECISION.md` ("Tests: 58/58 PASS"); `ODOM_R5_TEST_OUTPUT.txt` ("58 passed in 0.44s")
- **source_hashes:** `ODOM_R5_GO_NO_GO_DECISION.md` `d9080450064c61b84111cc0fd5f6c40c49209dcd08df0a1e85d48fddb450e8ed`; `ODOM_R5_TEST_OUTPUT.txt` `39108077449507b83dd4f992ac5306b9cc45a6bc253776389bd48f1de638708c`
- **detail:** includes `TestOdometryCandidateAdapterRealFixtures`, run against real captured fixtures, not purely synthetic mocks — stronger than a plain synthetic-only offline classification, but still executed on a desktop, not the robot/Jetson.
- **limitations:** desktop-executed, not robot-executed (see `adapter_pure_code_robot_validation` below for the separate robot-side claim).

### adapter_pure_code_robot_validation

- **project_validation_status:** OFFLINE_VALIDATED
- **execution_environment:** robot/Jetson (code-pure/offline; no live topic subscription)
- **this_checkpoint_activity:** NOT_IN_SCOPE
- **evidence_level:** REPORTED_BY_AGENT (uncorroborated figure) — see limitation
- **claimed_result:** "35/35 PASS" per `MASTER_R1_STATE.json` (`robot_pytest_adapter_result: "35/35 PASS"`, `adapter_offline_validated_on_robot: true`)
- **source_paths:** `OttoGuide-Mapping-Workspace/_MASTER_R1_CONSOLIDATE_PHYSICAL_SESSIONS_AND_MVP_NAVIGATION_ROADMAP_NO_ROBOT/run_20260708T014019Z/MASTER_R1_STATE.json`
- **source_hashes:** `MASTER_R1_STATE.json` `8c2edeec9e9623181eb39d783562c965fb7813ba961ef49374f49622ad872b35`
- **limitations:** **unreconciled discrepancy, disclosed rather than silently resolved**: no test-output artifact showing 35 tests was found anywhere in the searched roots; MASTER-R1's own state file cites no source for this figure, and it does not match the 58/58 figure from `adapter_offline_tests` (same commit `92a8bc4`, different execution environment/desktop). It is plausible these are two different test scopes (a robot-side subset vs. the full desktop suite), but that has not been confirmed by any artifact this reconciliation could open, so the evidence level here is capped at `REPORTED_BY_AGENT`, not elevated to `OFFLINE_TEST`. This is still code-pure/offline execution — no live DDS odometry topic was subscribed to or published during this validation, per `MASTER_R1_STATE.json`'s own `odom_present: false`, `tf_present: false`.

### odometry_source_channels_physical_capture

- **project_validation_status:** PHYSICAL_EVIDENCE_HARVESTED
- **this_checkpoint_activity:** NOT_EXECUTED_NO_ROBOT
- **evidence_level:** RAW_LOG + HASH_VERIFIED_ARTIFACT
- **source_paths:** `OttoGuide-Mapping-Workspace/_ROBOT_R2X_ONE_SHOT_PHYSICAL_READONLY_EVIDENCE_CAPTURE_NO_PUBLISH/run_20260708T215327Z/ROBOT_R2X_STATE.json`, `ROBOT_R2X_GO_NO_GO_DECISION.md`, `ROBOT_R2X_EVIDENCE_MANIFEST.md`; cross-verified independently by `ROBOT_R3X_INPUT_INTEGRITY_REPORT.md` (`INPUT_INTEGRITY_STATUS: VERIFIED_CONSISTENT`)
- **source_hashes:** `ROBOT_R2X_STATE.json` `1501a8b42b3760a717909f9834096dd42c4c17569197da2ad5988920a6e93f4f`; `ROBOT_R2X_GO_NO_GO_DECISION.md` `373dbbe921d846741346a4e85f5a095c72c9eed8dda4ed2ffc92939367ff7939`
- **detail:** `primary_channel: rt/odommodestate`, 80 samples, `hz_estimated: 501.1499074937536`, `receipt_monotonic: true`; `secondary_channel: rt/lf/odommodestate`, 80 samples, `hz_estimated: 19.999747436100858`, `receipt_monotonic: true`. `movement_performed: false`, `topics_published: false`, `odom_published: false`, `tf_published: false`, `critical_publishers: []`.
- **limitations:** robot stationary throughout (no movement), read-only subscription only (no publish of any kind). IMU fields (`gyroscope`, `accelerometer`) are zero in 100% of samples in both channels — no independent motion cross-check exists. The `critical_publishers: []` conclusion partially rests on `ros2 topic info -v` introspection calls that crashed (`bad_alloc`) for some topics rather than returning a clean negative for every one queried — a data-quality caveat on that specific sub-claim, not a refutation of it. `MASTER_R1_ODOMETRY_STATE.md`'s earlier ~507 Hz estimate for the same channel is superseded by this more precise, hash-verified 501.1499 Hz figure.

### adapter_live_dynamic_runtime

- **project_validation_status:** NOT_VALIDATED
- **this_checkpoint_activity:** NOT_IN_SCOPE
- **evidence_level:** UNKNOWN
- **source_paths:** none found
- **limitations:** no evidence anywhere of the candidate adapter running live against a subscribed DDS topic while processing real-time odometry data end-to-end. `ROBOT_R3X_ODOM_TF_READINESS_DECISION.md` explicitly notes `frame_id`/`child_frame_id` are "acuerdos de contrato, no campos observados en el payload."

### dynamic_odometry_solution

- **project_validation_status:** NOT_VALIDATED
- **state:** UNRESOLVED
- **this_checkpoint_activity:** NOT_IN_SCOPE
- **evidence_level:** UNKNOWN
- **source_paths:** `MASTER_R1_STATE.json` (`autonomous_navigation_ready: false`); `ROBOT_R3X_STATE.json` (`odom_publication_ready: false`, `tf_publication_ready: false`, `autonomous_navigation_ready: false`)
- **limitations:** no dynamic (in-motion) odometry solution has been designed, implemented, or validated anywhere in the searched roots.

### odom_publication

- **implementation_status:** NOT_IMPLEMENTED
- **project_validation_status:** NOT_VALIDATED
- **observed:** false
- **this_checkpoint_activity:** NOT_IN_SCOPE
- **evidence_level:** RAW_LOG (explicit absence confirmed in two independent physical captures)
- **source_paths:** `ROBOT_R2X_STATE.json` (`odom_published: false`); `PHYSICAL_BASELINE_20260623/route_capture_summary.json` (`topics_absent` includes `/odom`)
- **limitations:** positive confirmation of absence from two specific physical captures, not an exhaustive claim that `/odom` has never been published in any session anywhere.

### tf_publication

- **implementation_status:** NOT_IMPLEMENTED
- **project_validation_status:** NOT_VALIDATED
- **observed:** false
- **this_checkpoint_activity:** NOT_IN_SCOPE
- **evidence_level:** RAW_LOG (explicit absence confirmed in two independent physical captures)
- **source_paths:** `ROBOT_R2X_STATE.json` (`tf_published: false`); `PHYSICAL_BASELINE_20260623/route_capture_summary.json` (`topics_absent` includes `/tf`, `/tf_static`)
- **limitations:** same scope caveat as `odom_publication` above.

## Mapping / Localization / Nav2

### scan_equivalent_offline_pipeline

- **implementation_status:** IMPLEMENTED
- **project_validation_status:** OFFLINE_VALIDATED
- **this_checkpoint_activity:** NOT_IN_SCOPE
- **evidence_level:** HASH_VERIFIED_ARTIFACT
- **source_paths:** `OttoGuide-Mapping-Workspace/M3A_R3R_R3O_TO_ROS2_LASERSCAN_BAG_DRY_RUN_NO_MAP/run_20260709T171721Z/M3A_R3R_GO_NO_GO_DECISION.md` ("Classification A — R3O_TO_ROS2_LASERSCAN_BAG_DRY_RUN_READY_NO_MAP … Message count = 521 … Topic /scan present … Ranges length = 723 per message")
- **source_hashes:** `M3A_R3R_GO_NO_GO_DECISION.md` `4eccd6e04f6b9fdaca18dd061d5460fb281606acb7c77c8ac8db6db5010aa875`
- **limitations:** dry run converting `M3A-R3O`'s data-shape contract into a ROS2 bag with `/scan` messages; explicitly "NO_MAP," no robot, no physical LiDAR scan involved in this specific pipeline step.

### map_input_contract

- **implementation_status:** IMPLEMENTED
- **project_validation_status:** OFFLINE_VALIDATED
- **this_checkpoint_activity:** NOT_IN_SCOPE
- **evidence_level:** HASH_VERIFIED_ARTIFACT
- **source_paths:** `OttoGuide-Mapping-Workspace/M3A_R3O_MAP_INPUT_PACKAGE_CONTRACT_NO_MAP/run_20260709T051407Z/M3A_R3O_GO_NO_GO_DECISION.md` ("Result: OTTOGUIDE_M3A_R3O_MAP_INPUT_PACKAGE_CONTRACT_READY_NO_MAP")
- **source_hashes:** `M3A_R3O_GO_NO_GO_DECISION.md` `caa407b2d33dbc2340540e45a9ba180cb5396d26d4e148e0dabd82532e83e13e`
- **limitations:** data shape/schema contract only, no map built, no execution against physical or simulated sensor data.

### simulated_mapping

- **implementation_status:** UNKNOWN
- **project_validation_status:** NOT_VALIDATED
- **this_checkpoint_activity:** NOT_IN_SCOPE
- **evidence_level:** UNKNOWN
- **source_paths:** none found distinctly from `map_input_contract`/`scan_equivalent_offline_pipeline` above
- **limitations:** no run found in this reconciliation's scope builds an actual simulated occupancy map from the R3O/R3R pipeline outputs; the M3A chain proceeds from data contract directly to Nav2-sandbox planning against a pre-existing simulated map (see `nav2_sandbox` below), not a self-built simulated map.

### nav2_sandbox

- **implementation_status:** IMPLEMENTED
- **project_validation_status:** OFFLINE_VALIDATED
- **this_checkpoint_activity:** NOT_IN_SCOPE
- **evidence_level:** HASH_VERIFIED_ARTIFACT
- **source_paths:** `OttoGuide-Mapping-Workspace/M3A_R3Z_NAV2_SANDBOX_ROUTE_ON_SIMULATED_MAP_NO_ROBOT/run_20260709T201235Z/M3A_R3Z_GO_NO_GO_DECISION.md` ("Classification A — NAV2_SANDBOX_ROUTE_ON_SIMULATED_MAP_READY_NO_ROBOT … map_server load PASS … Nav2 planner route PASS (ComputePathToPose succeeded, 455 poses, 11.533m) … No robot used … No map physical claim … No route physical claim")
- **source_hashes:** `M3A_R3Z_GO_NO_GO_DECISION.md` `5eb9b3d3f3a61a02f1338d05eddc5f23349f970712de41b488e1d0cf90dc4333`
- **limitations:** Nav2 stack executed against a simulated map only; explicitly disclaims any physical Nav2 or physical route claim.

### simulated_waypoint_follower

- **implementation_status:** IMPLEMENTED
- **project_validation_status:** OFFLINE_VALIDATED
- **this_checkpoint_activity:** NOT_IN_SCOPE
- **evidence_level:** HASH_VERIFIED_ARTIFACT
- **source_paths:** `OttoGuide-Mapping-Workspace/M3A_R4A_NAV2_SANDBOX_WAYPOINT_FOLLOWER_ON_SIMULATED_MAP_NO_ROBOT/run_20260709T211119Z/M3A_R4A_STATE.json` (`SIMULATION_ONLY: true`, `NOT_PHYSICAL: true`, `robot_used: false`, `cmd_vel_physical_published: false`, `fake_robot_started: true`, `follow_waypoints_succeeded: true`, `waypoints_completed: 3`, `waypoints_total: 3`, `go_no_go: "GO"`); also `OttoGuide-Mapping-Workspace/M3A_R4A_R1_REFERENCE_ROUTE_ALIGNMENT_AND_AUTONOMOUS_SANDBOX_REPLAY_NO_ROBOT/run_20260709T222239Z/M3A_R4A_R1_GO_NO_GO_DECISION.md` (reference trajectory 1376 poses used as replay input; sandbox `FollowWaypoints` 5/5 succeeded; "No robot. No SSH. No DDS. No physical cmd_vel.")
- **source_hashes:** `M3A_R4A_STATE.json` `9982a22d60510c0529ae16cc27dd9661257e0cefbb7c197db8fe73b36694c81e`; `M3A_R4A_R1_GO_NO_GO_DECISION.md` `fe02ca65b8c0e0c26fce186ef4024e9611ed970d9d813238171c51601b3c9b97`
- **limitations:** uses a `fake_robot` node in sandbox; a previously-captured physical trajectory is used only as *replay input data*, not as a live physical execution. `cmd_vel` counts observed are entirely in-sandbox.

### mujoco_reference_route_replay

- **implementation_status:** IMPLEMENTED
- **project_validation_status:** OFFLINE_VALIDATED
- **this_checkpoint_activity:** NOT_IN_SCOPE
- **evidence_level:** HASH_VERIFIED_ARTIFACT
- **source_paths:** `OttoGuide-Mapping-Workspace/M3A_R4B_G1_MUJOCO_3D_REFERENCE_ROUTE_REPLAY_DEMO_NO_ROBOT/run_20260709T230031Z/M3A_R4B_GO_NO_GO_DECISION.md` ("Classification A: G1_MUJOCO_3D_REFERENCE_ROUTE_REPLAY_DEMO_READY_NO_ROBOT … G1 model load: PASS (scene_23dof.xml, nq=36) … Frames: 180 rendered … No robot. No SSH. No DDS. No physical cmd_vel/odom/TF.")
- **source_hashes:** `M3A_R4B_GO_NO_GO_DECISION.md` `14318291c88beded197985f8ef1199985d47a0932fcf1bd44ae14fb2d744ace5`
- **limitations:** a kinematic visualization/demo video (GIF/MP4) of the G1 model replaying a reference route in MuJoCo simulation — not a physical robot execution of any kind.

### physical_map

- **project_validation_status:** NOT_VALIDATED
- **this_checkpoint_activity:** NOT_IN_SCOPE
- **evidence_level:** RAW_LOG (explicit absence confirmed)
- **source_paths:** `PHYSICAL_BASELINE_20260623/route_capture_summary.json` (`topics_absent` includes `/map`, `/map_metadata`; `"navigation_validation_summary": "NOT_READY (odom/TF/map/Nav2 absent)"`)
- **limitations:** no run found anywhere in this reconciliation's scope claims a physical map was built.

### physical_localization

- **project_validation_status:** NOT_VALIDATED
- **this_checkpoint_activity:** NOT_IN_SCOPE
- **evidence_level:** RAW_LOG (explicit absence confirmed, by dependency: no `/odom` or `/tf` means no localization input exists)
- **source_paths:** same as `physical_map`
- **limitations:** no localization stack has anything physical to localize against; not attempted anywhere in the searched roots.

### physical_nav2

- **project_validation_status:** NOT_VALIDATED
- **this_checkpoint_activity:** NOT_IN_SCOPE
- **evidence_level:** RAW_LOG (explicit absence confirmed) + INFERRED (all M3A runs explicitly disclaim physical Nav2)
- **source_paths:** `M3A_R3Z_GO_NO_GO_DECISION.md` ("No physical Nav2"); `PHYSICAL_BASELINE_20260623/route_capture_summary.json`
- **limitations:** Nav2 has been exercised only in sandbox against simulated maps (see `nav2_sandbox` above); never against physical sensor input or on the physical robot.

### physical_autonomous_movement

- **project_validation_status:** NOT_VALIDATED
- **this_checkpoint_activity:** NOT_IN_SCOPE
- **evidence_level:** RAW_LOG (explicit absence confirmed) + INFERRED
- **source_paths:** `M3A_R4A_STATE.json` (`cmd_vel_physical_published: false`); `M3A_R4A_R1_GO_NO_GO_DECISION.md` ("No physical cmd_vel"); `M3A_R4B_GO_NO_GO_DECISION.md` ("No physical cmd_vel/odom/TF"); `ROBOT_R2X_STATE.json` (`movement_performed: false`)
- **limitations:** every mapping/Nav2 run found in this reconciliation's scope (six M3A runs) explicitly and consistently disclaims physical movement; `ROBOT_R2X`/`R3X` independently confirm the robot was stationary throughout the odometry channel capture. **No autonomous navigation or movement is declared validated anywhere in this ledger, at any evidence level, in this or any prior checkpoint reviewed.**

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

### From MASTER-OFFLINE-R1-LOCAL-R1 (applied in CORRECTION-R1)

1. **Emergency: `OFFLINE_VALIDATED` → `PHYSICALLY_VALIDATED`** (project level). Real raw response + operator attestation found in `FINAL_MVP_R2_EXPEDITED/run_20260714T185718Z`, not reviewed by the prior checkpoint.
2. **SIGTERM: `IMPLEMENTED_NOT_PHYSICALLY_VALIDATED` → `PHYSICALLY_VALIDATED`** (project level). The prior ledger conflated "skipped on this Windows host" with "never validated" — a real WSL execution (`SIGTERM_TEST_WSL.log`, PASSED) plus two independent raw process-exit logs plus operator attestation exist in prior runs.
3. **Posture preservation: `OFFLINE_VALIDATED` → `PHYSICALLY_VALIDATED`**, now corroborated by a real static-audit artifact and by zero posture-command markers in two independent physical events, not solely by unit tests.
4. **Physical C++ worker: build/link/GPU-load specifically upgraded from `REPORTED_BY_AGENT` (commit-message text) to `RAW_LOG`** (real build log and `ldd`/`file` output found and read directly). The full end-to-end voice-interaction claim is **explicitly not upgraded** and is called out as pending human confirmation.
5. **Wake word/STT/LLM/TTS/Speaker: added as its own reconciled entry**. The explicit `PENDING`/`<PENDING>` operator attestation status is surfaced directly, exact transcript/response text recorded as unavailable.

### From MASTER-OFFLINE-R1-CORRECTION-R1 (applied in this checkpoint, RELEASE-READINESS-R1)

6. **Web split** into `web_frontend_offline_tests` (unchanged, `OFFLINE_VALIDATED`) and `web_real_profile_control_path` (new, `PHYSICALLY_VALIDATED` — real browser/backend session, `WEB_UI_BROWSER_ACCEPTANCE.txt`).
7. **WebSocket split** into `websocket_offline_replay_contract` (unchanged, `OFFLINE_VALIDATED`) and `websocket_live_transport` (upgraded to `PHYSICAL_EVIDENCE_HARVESTED`, now with two independent corroborating raw logs instead of one).
8. **DDS split** into `dds_lowstate_read_path` (new, `PHYSICAL_EVIDENCE_HARVESTED` — real `ChannelFactoryInitialize`/`LocoClient` negotiation log), `dds_generic_runtime` (unchanged, `IMPLEMENTED_NOT_PHYSICALLY_VALIDATED`), `dds_write_or_publish_path` (unchanged, `NOT_IMPLEMENTED` — no evidence anywhere).
9. **Camera/QR/Livox/Odometry/TF/Mapping/Localization/Nav2 blanket row eliminated.** It previously classified all of these as a single `NOT_IMPLEMENTED`, which was false for several sub-capabilities where source code or physical evidence exists:
   - `camera_vision_runtime`/`qr_frame_detector`/`station_trigger`: `NOT_IMPLEMENTED` → `IMPLEMENTED_NOT_PHYSICALLY_VALIDATED` (source code confirmed present).
   - `camera_rgb_intrinsics_e2e`/`qr_physical_e2e`: unchanged, `NOT_IMPLEMENTED` (genuinely no evidence).
   - `livox_sdk2_bridge_implementation` and raw sensor capture: `NOT_IMPLEMENTED` → `PHYSICAL_EVIDENCE_HARVESTED` (real point-cloud/IMU capture logs and a 4.7 GiB physical rosbag found in `OttoGuide-Mapping-Workspace`, previously unsearched).
   - `odometry_candidate_adapter`/`adapter_offline_tests`: `NOT_IMPLEMENTED` → `IMPLEMENTED_NOT_PHYSICALLY_VALIDATED` (candidate adapter with 58/58 tests against real fixtures, committed locally on an unmerged branch, found in `OttoGuide-Mapping-Workspace/_ODOM_R5...`, previously unsearched).
   - `dynamic_odometry_runtime`/`odom_publication`/`tf_publication`: unchanged in substance (`UNRESOLVED`/absent), now cited to an explicit raw source instead of "no source_paths."
   - `mapping`/`localization`/`nav2`: unchanged (`NOT_VALIDATED`), now cited to an explicit raw source (`route_capture_summary.json`) confirming absence, instead of relying on an unsearched-root caveat.
10. `movement`/autonomous navigation row: unchanged. **No autonomous navigation or movement is declared validated anywhere in this ledger, at any evidence level, in this or any prior checkpoint reviewed.**

### From MASTER-OFFLINE-R1-RELEASE-READINESS-R1 (applied in this checkpoint, EVIDENCE-LEDGER-R2)

11. **Odometry rewritten into 8 sub-domains** (`odometry_candidate_adapter_implementation`, `adapter_offline_tests`, `adapter_pure_code_robot_validation`, `odometry_source_channels_physical_capture`, `adapter_live_dynamic_runtime`, `dynamic_odometry_solution`, `odom_publication`, `tf_publication`), replacing the two-row RELEASE-READINESS-R1 version:
    - New: `odometry_source_channels_physical_capture` — `PHYSICAL_EVIDENCE_HARVESTED`, `rt/odommodestate` (80 samples, 501.15 Hz) and `rt/lf/odommodestate` (80 samples, 20.00 Hz), both receipt-monotonic, robot stationary, no publish — from `ROBOT-R2X`, cross-verified by `ROBOT-R3X`, both previously uncited in this ledger.
    - New: `adapter_pure_code_robot_validation` — `OFFLINE_VALIDATED`, robot/Jetson-side code-pure validation per `MASTER-R1` (`adapter_offline_validated_on_robot: true`), with the claimed "35/35 PASS" figure explicitly flagged as an **unreconciled, uncited discrepancy** against `adapter_offline_tests`' hash-verified 58/58 (same commit, different execution environment) — recorded at `REPORTED_BY_AGENT` evidence level, not silently accepted or silently dropped.
    - New: `adapter_live_dynamic_runtime` and `dynamic_odometry_solution` — both `NOT_VALIDATED`, making explicit that no live/dynamic odometry runtime exists anywhere, distinct from the offline/stationary-capture evidence above.
    - `odom_publication`/`tf_publication` — unchanged in substance (`NOT_VALIDATED`/absent), now corroborated by a second independent source (`ROBOT_R2X_STATE.json`) in addition to the rosbag baseline already cited.
12. **Mapping/Localization/Nav2 rewritten into 10 sub-domains** (`scan_equivalent_offline_pipeline`, `map_input_contract`, `simulated_mapping`, `nav2_sandbox`, `simulated_waypoint_follower`, `mujoco_reference_route_replay`, `physical_map`, `physical_localization`, `physical_nav2`, `physical_autonomous_movement`), replacing the single blanket `NOT_IMPLEMENTED`/`NOT_VALIDATED` row. Six M3A runs (R3O, R3R, R3Z, R4A, R4A-R1, R4B) read directly and cited by hash for the first time in this ledger — all six offline/simulated sub-domains are `OFFLINE_VALIDATED` (real code, real sandbox execution, zero physical claim, each run's own text explicitly disclaiming physical execution); all four physical sub-domains remain `NOT_VALIDATED`, unchanged, now cited to explicit raw sources instead of an "unsearched root" caveat.
13. **Livox rewritten into 8 sub-domains** (`livox_sdk2_bridge_implementation`, `livox_raw_cloud_capture`, `livox_raw_imu_capture`, `livox_ros_pointcloud_publication`, `livox_ros_imu_publication`, `livox_coordinate_validation`, `scan_gate`, `extrinsics_calibration`), replacing the single bundled `PHYSICAL_EVIDENCE_HARVESTED` row that had conflated raw SDK2-callback capture with ROS-topic-level publication and with unvalidated coordinate/scan-gate/extrinsics code:
    - Raw cloud/IMU capture: `PHYSICAL_EVIDENCE_HARVESTED`, unchanged in substance, now separated from...
    - ROS PointCloud2/IMU publication: newly split out as its own pair of entries, `NOT_VALIDATED` for the SDK2 session (explicitly not executed there) with corroborating message-count evidence of real publication in the separate rosbag session, not conflated with the SDK2 session's raw-callback-only evidence.
    - Coordinate validation / scan_gate: downgraded from being folded into the bundled `PHYSICAL_EVIDENCE_HARVESTED` row to their correct `IMPLEMENTED_NOT_PHYSICALLY_VALIDATED` (source/documentation exists, not confirmed exercised against physical data).
    - Extrinsics calibration: newly made explicit as its own `NOT_VALIDATED` entry (previously only mentioned in a limitations sentence, not as a first-class domain).

All classifications not explicitly touched by items 11-13 above are carried forward unchanged from RELEASE-READINESS-R1.

## Provenance note

This ledger was built from: (1) Git objects/refs verified this and prior checkpoints, (2) hash-verified harvest artifacts, (3) tests executed in prior checkpoints, (4) raw logs, raw HTTP responses, marker counts, state JSON fields, and operator attestations found in prior physical/consolidation runs under `OttoGuide-Agent-Runs` and `OttoGuide-Mapping-Workspace`, read directly during this and prior reconciliations (not summarized from any intermediate report), and (5) commit messages/logs, labeled `REPORTED_BY_AGENT` only where no raw corroboration was found (see the `adapter_pure_code_robot_validation` "35/35" discrepancy above for a concrete example of this label in use). No claim in this ledger was elevated to a physical-evidence classification on the strength of a report or summary alone — every such classification here points to a specific raw log, raw response, marker count, commit, state field, or operator attestation file that this or a prior reconciliation opened and read directly. Full source list with hashes for this checkpoint's additions: `EVIDENCE_LEDGER_R2_SOURCE_INVENTORY.md` and `EVIDENCE_LEDGER_R2_SOURCE_HASHES.txt` in this checkpoint's run root. This checkpoint modified no code, tests, fixtures, settings, or packages — documentation only.
