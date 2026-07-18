# MVP Offline — Next Checkpoints

Recommended order of future work, built from the completion matrix and known-gaps audit produced in `MASTER-OFFLINE-R1-LOCAL-R1`. None of these checkpoints are started by this task.

1. **IA-CXX-R2 hardening and UADE context.** Address the capture-thread readiness handshake, socket/multicast error propagation, hardcoded configuration externalization, Ollama client robustness, and direct UADE context injection (`MVP_IA_CXX_R1_KNOWN_GAPS.md` items 1-5). Offline-testable: yes, for configuration externalization and client robustness; the capture-thread handshake likely needs a Jetson session to verify meaningfully.
2. **MVP-TELEMETRY-R2 over replay lowstate.** Wire `tools/offline_replay/lowstate_replay.py` into a telemetry test double so WebSocket/telemetry integration tests can run against realistic (not hand-typed) lowstate frames offline. Fully offline-testable.
3. **FULL-MVP-OFFLINE-R1.** Broaden offline fixture coverage: capture and replay a longer, multi-mode lowstate window; extend contractual fixtures (`interaction_contracts_r1/`) to cover more state-machine transitions and failure paths. Fully offline-testable.
4. **VISION-QR-OFFLINE-R1.** Design and, where possible, offline-test vision/QR pipeline logic against recorded image fixtures (not yet captured). Requires camera-frame harvest before offline work can begin.
5. **ODOM-TF-OFFLINE-R1.** _Partially advanced (MVP-ODOM-TF-R1)._ A **stationary source capture is available** (MFR-R6 fixtures, `codigo ottoguide/tests/fixtures/mfr_r6_sportmodestate/`, 160 samples across `rt/odommodestate` + `rt/lf/odommodestate`), and an offline, fail-closed readiness gate (`src/navigation/odometry_candidate_adapter/readiness.py`) now evaluates whether `/odom` and `odom -> base_link` can be prepared. Result on the current evidence: `NOT_READY` with explicit blockers. Still **missing**: a **dynamic motion capture** (moving robot) and any **`/odom` / TF publication**. Correcting the earlier statement that no odometry capture existed:
   - `stationary source capture = available`
   - `dynamic motion capture = missing`
   - `/odom and TF publication = missing`

   The remaining work (harvest a dynamic capture, then clear the documented blockers in `docs/Arquitectura/ODOM_TF_R1_OFFLINE_READINESS_CONTRACT.md`) still requires a future robot session. _MVP-ODOM-TF-R1A_ hardened the gate to be fail-closed on malformed contracts/candidates and to reject boolean flags that contradict the typed evidence (covariance/IMU/dynamic), plus rejecting unfiltered mixed-channel sequences and non-monotonic receipts; the current-fixture result is unchanged (`NOT_READY`, same 11 blockers).
6. **NAV2-OFFLINE-R1.** Only after odometry/TF/mapping data exists offline; build sandboxed Nav2 configuration testing against recorded/simulated maps, never against a live robot from this workstation.
7. **Future minimal, separate physical session.** A dedicated, scoped robot session to: (a) verify the SIGTERM/StopMove contract on the actual Jetson under Linux (this task could only document the claim, not execute it, on Windows); (b) re-confirm the `0d14de6` on-Jetson build/link/smoke claims with fresh raw logs; (c) harvest a longer/multi-mode lowstate window; (d) harvest the vision/QR/odometry source data needed to unblock checkpoints 4-6.

## Sequencing note

Checkpoints 1-3 are fully achievable offline, on this Desktop, without robot access, and should be prioritized accordingly. Checkpoints 4-6 are blocked on raw data that does not yet exist locally and requires checkpoint 7 (or an equivalent harvest) first. Checkpoint 7 is the only item on this list requiring physical robot access, and it should remain a separate, explicitly scoped session distinct from any offline consolidation work.
