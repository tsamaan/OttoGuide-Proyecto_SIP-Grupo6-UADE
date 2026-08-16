# OttoGuide Final Closure Scope

**Repository status:** `FINAL_CLOSURE_CANDIDATE`

This is not an active development backlog. It records scope intentionally deferred from the final repository closure and prevents those limitations from being represented as implemented or physically validated.

## Durable States

- `CLOSED_FOR_RELEASE`: represented by the sealed candidate and not a remaining release blocker.
- `DEFERRED_OUTSIDE_FINAL_SCOPE`: future work intentionally excluded from project closure.
- `REQUIRES_FUTURE_PHYSICAL_VALIDATION`: requires a separately authorized robot/HIL session.
- `NOT_CLAIMED`: no current evidence supports the capability claim.
- `HISTORICAL_SUPERSEDED`: preserved provenance that is no longer current operational work.

## Closed For Release

- [CLOSED_FOR_RELEASE] P2C offline claims, readiness, and provenance boundaries are represented by the audited payload and its versioned evidence.
- [CLOSED_FOR_RELEASE] Historical branch reconciliation is closed on `review/orchestrator-unification`; wholesale historical branch merges are not release work.
- [CLOSED_FOR_RELEASE] Repository closure governance and the single-root `main` release policy are versioned in the architecture handoff and unification state.

## Requires Future Physical Validation

- [REQUIRES_FUTURE_PHYSICAL_VALIDATION] Observe and validate physical `/odom`, `/tf`, `/tf_static`, `/map`, and related frame semantics on the intended Unitree environment.
- [REQUIRES_FUTURE_PHYSICAL_VALIDATION] Validate actual Nav2, SLAM/map, and autonomous tour behavior with an operator, hardstop, bounded motion plan, and an explicit HIL authorization.
- [REQUIRES_FUTURE_PHYSICAL_VALIDATION] Validate live DDS/ROS bridges, LiDAR, IMU, camera, and audio behavior against the deployed hardware and configuration.
- [REQUIRES_FUTURE_PHYSICAL_VALIDATION] Record new physical evidence before claiming a current hardware deployment or operational autonomy.

## Deferred Outside Final Scope

- [DEFERRED_OUTSIDE_FINAL_SCOPE] New product features, runtime redesign, CI expansion, and repository-wide restructuring.
- [DEFERRED_OUTSIDE_FINAL_SCOPE] Additional web application work outside the integrated frontend already present in `ottoguide_web_app/`.
- [DEFERRED_OUTSIDE_FINAL_SCOPE] Migration or reconciliation of historical/lateral branches not selected into the authoritative integration history.

## Not Claimed

- [NOT_CLAIMED] Current physical ODOM or TF publication readiness.
- [NOT_CLAIMED] Current physical Nav2 autonomy, SLAM/map operation, or complete robot tours.
- [NOT_CLAIMED] Current robot audio, camera, or network-runtime validation for this exact candidate tree.
- [NOT_CLAIMED] A final `main` root release commit. That release is created only after a sealed final tree and separately authorized mirror and canonical writes.

## Historical Or Superseded

- [HISTORICAL_SUPERSEDED] `RC1_LOCKED` and Post-RC1 backlog wording. They describe an earlier lifecycle, not the current final-closure candidate.
- [HISTORICAL_SUPERSEDED] Earlier deployment instructions and branch snapshots that were not durable current-state contracts. Historical evidence remains available under `docs/`.

## Safety Boundary

No deferred physical validation is authorized by this file. Robot, ROS, DDS, Nav2, SLAM, audio, SSH, and motion work each require an explicit dedicated checkpoint and the safety gates in `AGENTS.md`.
