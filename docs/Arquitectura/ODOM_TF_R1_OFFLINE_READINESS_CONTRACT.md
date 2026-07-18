# ODOM-TF-R1 — Offline `/odom` and TF Readiness Contract

**Checkpoint:** `MVP-ODOM-TF-R1-OFFLINE-READINESS-CONTRACT`
**Risk level:** B (pure offline, no robot, no ROS/DDS publication)
**Status of physical readiness:** `NOT_READY` — publication of `/odom` and the
`odom -> base_link` TF transform is withheld, with explicit, traceable blockers.

This document describes an offline, deterministic, fail-closed gate that decides
whether the available evidence and contract are sufficient to *prepare* `/odom`
and `odom -> base_link`. It does not build ROS messages, does not publish any
topic, and never declares physical readiness.

---

## 1. Available evidence

### 1.1 Stationary source capture (available)

The MFR-R6 fixtures under
`codigo ottoguide/tests/fixtures/mfr_r6_sportmodestate/` contain a **real,
stationary** capture of the robot's SportModeState odometry-candidate channels:

- `mfr_r6_primary_rt_odommodestate.jsonl` — 80 samples, channel `rt/odommodestate`.
- `mfr_r6_secondary_rt_lf_odommodestate.jsonl` — 80 samples, channel `rt/lf/odommodestate`.
- 160 samples total, robot stationary, all position/velocity/yaw finite,
  receipt-monotonic ordering preserved per channel.

Known facts from the capture (not to be reinterpreted):

- Source capture rates: primary ≈ 501.15 Hz, secondary ≈ 19.9997 Hz.
- A **later** Web observation (`WEB_R0B1_REAL_20260717`,
  `R0B1_LIVE_MONITOR_REPORT.json`) measured primary ≈ 417.1 Hz, secondary
  ≈ 19.8 Hz. **The rate of neither channel is a fixed constant**, and the
  higher-rate channel is **not** thereby authoritative.
- Message stamp is zero in the fixture; receipt monotonic time is available.
- Gyroscope and accelerometer read all-zero in the source capture.
- Covariance is unavailable in the source; `child_frame_id` is unresolved.

### 1.2 Dynamic motion capture (missing)

No dynamic (moving-robot) capture exists. Odometry integration, drift, and
scale/sign cannot be validated against a stationary capture alone.

### 1.3 `/odom` and TF publication (missing)

`/odom`, `/tf`, and `/tf_static` were not observed in the named physical
captures, and no publisher exists in this repository's runtime. This is a
scoped statement about the inspected captures, never a project-wide
absence claim.

---

## 2. What the adapter resolves

`codigo ottoguide/src/navigation/odometry_candidate_adapter/` (commit
`92a8bc45a7a8d7557bcdca9ae5684692016168a7`, an ancestor of the current
`review/orchestrator-unification`) provides a pure `SportModeState_` sample →
`OdometryCandidate` transform. It:

- validates each sample (channel allow-list, finite position/velocity/yaw,
  positive receipt-monotonic time) and fails closed on malformed input;
- records the fixed contract policies (`FRAME_ID = "unitree_odom_candidate"`,
  `COVARIANCE_POLICY`, `TIMESTAMP_POLICY`) without inventing values;
- flags message-stamp-zero and all-zero IMU as warnings / unreliability,
  never silently normalizing them away.

The adapter is **not** `nav_msgs/Odometry`, carries no ROS dependency, and is
never published.

## 3. What the new gate resolves

`codigo ottoguide/src/navigation/odometry_candidate_adapter/readiness.py`
adds `assess_odom_tf_readiness(candidates, evidence_contract)`, returning an
immutable `OdomTfReadinessReport` that separates:

- `offline_contract_ready` — the gate ran and the candidate sequence is
  processable (non-empty, all-valid). This is **not** permission to publish.
- `odom_publication_ready` — false whenever any BLOCKER is present.
- `odom_to_base_link_tf_ready` — false unless publication is ready **and** the
  child frame is resolved.
- `physical_validation_required` — true whenever any readiness axis is withheld.
- `nav2_ready` — **always false** in this checkpoint.

Each withheld piece is an explicit `OdomTfBlocker` with a stable `code`, a
`severity` (`BLOCKER` / `WARNING` / `OBSERVATION`), and a message. Blockers are
emitted in a deterministic canonical order independent of check execution order.
The absence of evidence is never silently converted into a permissive default:
every field of `OdomTfEvidenceContract` defaults to the conservative
(unverified / unavailable) value and must be positively asserted to clear its
blocker.

The stable classification for the current evidence is:

```
MVP_ODOM_TF_R1_OFFLINE_CONTRACT_READY_PHYSICAL_VALIDATION_REQUIRED
```

This deliberately avoids a plain `READY`, which would be ambiguous. It means:
the gate works, the evidence is processable, and `/odom` / TF still cannot be
published.

## 4. What the gate does NOT resolve

The gate does not, and this checkpoint does not, establish any of:

- a moving-robot (dynamic) validation of odometry;
- selection of an authoritative source channel;
- equivalence of `unitree_odom_candidate` to a ROS `odom` frame;
- the `child_frame_id` for the TF edge;
- axis convention (handedness / forward axis / REP-103);
- scale and sign of position / velocity / yaw;
- a receipt-monotonic → ROS-time mapping;
- covariance values;
- an independent IMU cross-check;
- reset / discontinuity / wraparound behavior.

## 5. The two channels, and why neither is selected yet

Both `rt/odommodestate` and `rt/lf/odommodestate` are preserved in every report.
Their sample rates differ, and the observed rate of each **changed** between the
source capture and the later Web observation. A rate difference is therefore
recorded only as an `OBSERVATION`; it never selects a source. Channel
arbitration remains an explicit `BLOCKER`
(`SOURCE_CHANNEL_ARBITRATION_UNRESOLVED`) until a future session documents a
reason for selecting one channel that is not "the faster one."

## 6. Current blockers

With the current stationary evidence and the default (all-unverified) contract,
the gate emits these `BLOCKER`s (canonical order):

1. `DYNAMIC_MOTION_EVIDENCE_MISSING`
2. `SOURCE_CHANNEL_ARBITRATION_UNRESOLVED`
3. `SOURCE_FRAME_SEMANTICS_UNVERIFIED`
4. `CHILD_FRAME_ID_UNRESOLVED`
5. `AXIS_CONVENTION_UNVERIFIED`
6. `SCALE_AND_SIGN_UNVERIFIED`
7. `MESSAGE_TIMESTAMP_ZERO`
8. `RECEIPT_TIME_TO_ROS_TIME_UNRESOLVED`
9. `COVARIANCE_UNAVAILABLE`
10. `IMU_CROSSCHECK_UNAVAILABLE`
11. `RESET_AND_DISCONTINUITY_BEHAVIOR_UNVERIFIED`

Plus non-blocking `OBSERVATION`s: `MULTIPLE_CANDIDATE_CHANNELS_PRESENT`,
`RATE_DIFFERENCE_BETWEEN_CHANNELS`, `IMU_ZERO_IN_CAPTURE`.

## 7. Exact information required in a future dynamic session

To clear the blockers, a future (physical, separately scoped) session must
provide and validate:

- a dynamic, moving-robot capture across multiple motion modes;
- a documented arbitration selecting one authoritative channel, with reason;
- verification that the source frame corresponds to a ROS `odom` frame
  (origin, continuity, drift semantics);
- the resolved `child_frame_id` (e.g. `base_link`) for the TF edge;
- verified axis convention, scale, and sign against ground-truth motion;
- a defined receipt-monotonic → ROS-time mapping (and a non-zero header stamp
  strategy);
- covariance sourced or explicitly modeled (never invented);
- an independent IMU cross-check with non-zero, usable gyro/accel;
- characterized reset / discontinuity / wraparound behavior.

## 8. Future transition to a ROS publisher (still prohibited)

A future publisher would consume the validated candidates and, only after all
blockers clear, construct `nav_msgs/Odometry` and a `geometry_msgs`/`tf2_ros`
transform. **None of that is permitted in this checkpoint.** This checkpoint
imports no `rclpy`, `nav_msgs`, `geometry_msgs`, or `tf2_ros`, creates no
publisher, and performs no movement. The offline CLI
`codigo ottoguide/tools/hil/offline_navigation/verify_odom_tf_readiness.py`
prints the gate's JSON verdict and returns exit 0 only when publication is
correctly refused.
