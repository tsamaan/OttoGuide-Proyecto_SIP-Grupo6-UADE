# OttoGuide Physical Validation Master Ledger

Reconciled during `MASTER-OFFLINE-R1-RELEASE-READINESS-R1`, on top of `MASTER-OFFLINE-R1-CORRECTION-R1`'s checkpoint (`c68032d`, parent chain `254cddd → 0d14de6 → 3da2e9a → bed9e01 → b41559d → 4caecd9 → c68032d`).

**Correction note (CORRECTION-R1):** the prior version of this ledger (written during `MASTER-OFFLINE-R1-LOCAL-R1`) used only evidence generated within that single checkpoint's own session and, for several domains, conflated "this checkpoint did not execute X" with "the project has not validated X." That revision separated those two questions explicitly and incorporated real raw evidence found in five prior physical/consolidation runs under `OttoGuide-Agent-Runs` (`FINAL_MVP_R2_EXPEDITED/run_20260714T185718Z`, `MVP_IA_CXX_R1/run_20260714T194651Z`, `FINAL_ROBOT_HARVEST_R1/run_20260714T203807Z`, `MIRROR_STAGING_MVP_IA_CXX_R1_R0/run_20260715T005710Z`, `FINAL_SAFETY_R1_R3_OFFLINE_CANONICAL/run_20260714T033823Z`), all five verified to exist and read directly during that reconciliation.

**Correction note (RELEASE-READINESS-R1):** this revision fixes a second conflation the prior ledger still had: several unrelated domains (Web, WebSocket, DDS, Camera/QR, Livox, Odometry) were each collapsed into a single row per topic, or bundled together under one blanket `NOT_IMPLEMENTED`/`NOT_IN_SCOPE` line, even though within each topic some sub-capabilities have real implementation or real physical evidence and others do not. This revision splits every such domain into its constituent sub-capabilities (e.g. `web_frontend_offline_tests` vs. `web_real_profile_control_path`; `websocket_live_transport` vs. `websocket_offline_replay_contract`; `dds_lowstate_read_path` vs. `dds_generic_runtime` vs. `dds_write_or_publish_path`; `camera_vision_runtime`/`qr_frame_detector`/`station_trigger` vs. `camera_rgb_intrinsics_e2e`/`qr_physical_e2e`; `livox_sdk2_bridge_implementation`/`livox_cloud_callback`/`livox_imu_callback`/`livox_coordinate_validation`/`scan_gate`; `odometry_candidate_adapter`/`adapter_offline_tests`/`adapter_pure_code_robot_validation` vs. `dynamic_odometry_runtime`/`odom_publication`/`tf_publication`), incorporating evidence read directly from `OttoGuide-Agent-Runs`, `OttoGuide-Mapping-Workspace`, and `OttoGuide-Workspaces` during this reconciliation. See `EVIDENCE_SOURCE_INVENTORY.md` (this checkpoint's run root) for the full source list with hashes and quoted excerpts. No `NOT_IMPLEMENTED` classification survives where verified source code or a verified commit exists for that exact sub-capability; no domain's overall row is reduced to a single `OFFLINE_VALIDATED` classification where physical raw evidence exists for part of it.

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

### livox_sdk2_bridge_implementation / livox_cloud_callback / livox_imu_callback / livox_coordinate_validation / scan_gate

- **project_classification:** PHYSICAL_EVIDENCE_HARVESTED
- **this_checkpoint_activity:** NOT_EXECUTED_NO_ROBOT
- **evidence_level:** RAW_LOG + HASH_VERIFIED_ARTIFACT
- **source_paths:** `codigo ottoguide/ros2_ws/src/ottoguide_livox_sdk_bridge/src/livox_sdk_bridge_node.cpp` (implementation: `point_cloud_callback`, `imu_callback`, `SetLivoxLidarPointCloudCallBack`, `SetLivoxLidarImuDataCallback`, coordinate/packet validation `drop_unsafe_dot_num`/`dry_run_drop`); `docs/Operaciones_HIL/README_SCAN_GATE.md`; `FINAL_ROBOT_R0_OFFLINE_CONSOLIDATION/run_20260713T234047Z/LIVOX_CAPTURE_ANALYSIS.md` (30,033 point-cloud callbacks + 2,883 IMU callbacks over ~25s, real LiDAR serial `47MCN8N0035124` MID360, multicast `224.1.1.5`, no errors); `LIVOX_COMMAND_INTERACTION_LEDGER.md` (discloses the SDK2 quick-start tool negotiated as "master SDK," not strictly passive-listen); `extracted_dataset/continuation_r1_20260713T211007Z/STATIONARY_LIVOX_DATASET/livox_quickstart_raw.log` (32,961 lines, real timestamps); `OttoGuide-Mapping-Workspace/py-iso-r1r-canonical/docs/Operaciones_HIL/Evidencia/PHYSICAL_BASELINE_20260623/route_capture_summary.json` (4.7 GiB physical rosbag `office_route_manual_control_raw_take01`, 362.464s, `/utlidar/cloud` 651,527 msgs, `/scan` 630,915, `/livox/imu` 90,753; second 2.2 GiB take also captured)
- **source_hashes:** `LIVOX_CAPTURE_ANALYSIS.md` `eb97fe2cc31cda5c9df7c82e63f740dd78734073bf754d232546d4bccbcb9761`; `LIVOX_COMMAND_INTERACTION_LEDGER.md` `c8fe0c3a029a6146d0639dc7156752db445257a1e022d73d094784a79c5ea1a8`; `route_capture_summary.json` `7373cf00ac614db1abf5a6ca01785d3f45893e053fd6b85c08df6081c861fdcc`
- **limitations:** raw sensor capture (point cloud + IMU) is real and physically observed. Extrinsics uncalibrated; ROS `PointCloud2` conversion/publication not executed; the quick-start probe was not strictly passive (sent commands, received Acks), which is disclosed rather than hidden. Coordinate validation logic (`drop_unsafe_dot_num`) is implementation only, not confirmed exercised against physical out-of-range data.

## Odometry

### odometry_candidate_adapter / adapter_offline_tests / adapter_pure_code_robot_validation

- **project_classification:** IMPLEMENTED_NOT_PHYSICALLY_VALIDATED
- **this_checkpoint_activity:** NOT_IN_SCOPE
- **evidence_level:** OFFLINE_TEST + COMMIT_EXACT
- **source_paths:** `OttoGuide-Mapping-Workspace/_ODOM_R5_LOCAL_COMMIT_DECISION_WITH_RUFF_GAP_NO_PUBLISH/run_20260707T203329Z/ODOM_R5_GO_NO_GO_DECISION.md` (`Tests: 58/58 PASS`; local commit `92a8bc4` on `dd155cec...`, 12 files, 1021 insertions, branch `odom/odometry-candidate-adapter-r1`; `git push no fue ejecutado en ningún momento`); `ODOM_R5_TEST_OUTPUT.txt`
- **source_hashes:** `ODOM_R5_GO_NO_GO_DECISION.md` `d9080450064c61b84111cc0fd5f6c40c49209dcd08df0a1e85d48fddb450e8ed`; `ODOM_R5_TEST_OUTPUT.txt` `39108077449507b83dd4f992ac5306b9cc45a6bc253776389bd48f1de638708c`
- **detail:** the candidate adapter's offline tests (including `TestOdometryCandidateAdapterRealFixtures`) ran against real captured fixtures, not purely synthetic mocks — stronger than a plain offline-only classification, but still not a live-robot validation.
- **limitations:** `odometry_candidate_adapter.py` does not exist in this repository's tracked source (`C:\OG\master-offline-r1-local-r1\repo`); only `src/navigation/odom_bridge_contract.py`, a pure static contract module, is present here. The adapter branch was never merged into this audited repository and never pushed anywhere. Must not be classified `NOT_IMPLEMENTED` (implementation and tests genuinely exist, just not in this repo/branch), and must not be classified `PHYSICALLY_VALIDATED` (never run live).

### dynamic_odometry_runtime / odom_publication / tf_publication

- **project_classification:** NOT_IMPLEMENTED — **dynamic odometry: UNRESOLVED; `/odom` publication: absent; TF publication: absent**
- **this_checkpoint_activity:** NOT_IN_SCOPE
- **evidence_level:** RAW_LOG (explicit absence confirmed in a physical capture)
- **source_paths:** `OttoGuide-Mapping-Workspace/py-iso-r1r-canonical/docs/Operaciones_HIL/Evidencia/PHYSICAL_BASELINE_20260623/route_capture_summary.json` (`topics_absent` includes `/odom`, `/tf`, `/tf_static`)
- **limitations:** this is a positive confirmation of absence from one specific physical baseline capture, not an exhaustive claim that odometry/TF have never been published in any session anywhere.

## Mapping / Localization / Nav2

- **project_classification:** NOT_IMPLEMENTED — **physical map: NOT_VALIDATED; physical localization: NOT_VALIDATED; physical Nav2: NOT_VALIDATED**
- **this_checkpoint_activity:** NOT_IN_SCOPE
- **evidence_level:** RAW_LOG (explicit absence confirmed) + INFERRED (SLAM/Nav2 workspace runs reviewed)
- **source_paths:** `PHYSICAL_BASELINE_20260623/route_capture_summary.json` (`"navigation_validation_summary": "NOT_READY (odom/TF/map/Nav2 absent)"`, `topics_absent` includes `/map`, `/map_metadata`, `/cmd_vel*`); SLAM/Nav2-related runs found under `OttoGuide-Mapping-Workspace` (e.g. M3A_R3Z, R4A, R4B) are explicitly tagged `NO_ROBOT`/`NO_MAP`/simulated (MuJoCo or synthetic DDS) by their own authors
- **limitations:** this reconciliation searched `OttoGuide-Mapping-Workspace` and `OttoGuide-Workspaces` directly (unlike the prior checkpoint, which explicitly had not); no run found anywhere claims physical map, physical localization, or physical Nav2 execution succeeded. A residual limitation: not every subdirectory of every workspace root was opened individually, so this is not a claim that literally zero mapping evidence exists anywhere on disk, only that none was found in this search.

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

## Provenance note

This ledger was built from: (1) Git objects/refs verified this and prior checkpoints, (2) hash-verified harvest artifacts, (3) tests executed this checkpoint, (4) raw logs, raw HTTP responses, marker counts, and operator attestations found in prior physical/consolidation runs under `OttoGuide-Agent-Runs`, `OttoGuide-Mapping-Workspace`, and `OttoGuide-Workspaces`, read directly during this and the prior reconciliation (not summarized from any intermediate report), and (5) commit messages, labeled `REPORTED_BY_AGENT` only where no raw corroboration was found. No claim in this ledger was elevated to a physical-evidence classification on the strength of a report or summary alone — every such classification here points to a specific raw log, raw response, marker count, commit, or operator attestation file that this or the prior reconciliation opened and read directly. Full source list with hashes for this checkpoint's additions: `EVIDENCE_SOURCE_INVENTORY.md` in this checkpoint's run root.
