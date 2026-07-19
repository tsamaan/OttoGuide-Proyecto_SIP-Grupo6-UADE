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

## 9. R1A hardening — fail-closed input and evidence coherence

MVP-ODOM-TF-R1A tightens the gate so that neither a malformed input nor an
isolated boolean can bypass a real gap. The current-fixture result is unchanged
(the same eleven blockers, `NOT_READY`).

- **Type validation (fail closed).** `assess_odom_tf_readiness` accepts only a
  real `OdomTfEvidenceContract` whose boolean fields are actual `bool` (a
  truthy `"false"` string or `1` is rejected, not trusted). A `None`,
  wrong-type, or malformed contract returns a fail-closed report with
  `EVIDENCE_CONTRACT_INVALID` and never raises to the caller. Each candidate is
  structurally validated (type, allowed channel, positive integer receipt,
  finite 3-vectors, integer in-range timestamps, boolean covariance/IMU flags);
  a bare `valid=True` on an arbitrary object yields
  `CANDIDATE_STRUCTURE_INVALID`.

- **Candidate/contract coherence.** A contract boolean can never override the
  typed evidence:
  - `covariance_available=true` cannot clear the covariance blocker unless the
    selected candidates carry covariance evidence. Because the current model
    transports no covariance values, an isolated boolean instead raises
    `COVARIANCE_EVIDENCE_CONTRADICTION`. **Covariance must be real or explicitly
    modeled** in a future model change — never asserted by a lone flag.
  - `imu_crosscheck_available=true` with unreliable gyro/accel candidates raises
    `IMU_EVIDENCE_CONTRADICTION`.
  - `dynamic_motion_evidence_available=true` with a single or observably-static
    sequence raises `DYNAMIC_EVIDENCE_CONTRADICTION`. **Dynamic evidence must be
    verifiable variation in the candidates**, not a boolean.

- **No mixed-channel publication.** When arbitration is asserted resolved, a
  sequence mixing both channels raises
  `MIXED_CHANNEL_SEQUENCE_REQUIRES_FILTERING`, and an authoritative channel
  absent from the sequence or the adapter allow-list raises
  `AUTHORITATIVE_CHANNEL_NOT_PRESENT`. A future stage must pass a sequence
  explicitly filtered to the selected channel.

- **Temporal coherence.** A receipt-monotonic inversion within a channel raises
  `RECEIPT_MONOTONIC_ORDER_INVALID` (no wall-clock is read).

- **Adapter IMU reliability.** A missing, malformed, or non-finite IMU vector is
  never reported reliable; the candidate stays valid when position/velocity/yaw
  remain usable (valid-candidate vs. unreliable-IMU stay separate).

`nav2_ready` remains false and `physical_validation_required` remains true
throughout R1A; no path declares physical readiness.

## 10. R1B — the R1 series is a non-publishable boundary

MVP-ODOM-TF-R1B closes the remaining false-ready paths and makes explicit what
R1 and R1A already intended: **the entire R1 series is a non-publishable,
offline blocker-characterization gate.** It cannot authorize `/odom` or TF under
any input.

The R1 data model deliberately does **not** contain, and R1/R1A/R1B therefore
cannot establish:

- a covariance matrix or covariance model;
- covariance provenance;
- displacement ground truth;
- a typed dynamic-motion-evidence object;
- physical validation of axes, scale, or signs.

Because none of that exists yet, **no combination of contract or candidate
booleans can authorize publication.** These are hard invariants of the series,
independent of the blocker set:

```
odom_publication_ready      = false
odom_to_base_link_tf_ready  = false
nav2_ready                  = false
physical_validation_required = true
publication_capability      = WITHHELD_BY_R1_BOUNDARY
```

`offline_contract_ready` may still be true — it means only that the input is
well-formed and processable, never that publication is permitted. A
fully-satisfied synthetic contract with synthetic candidates is explicitly
tested to keep every operational readiness axis false.

R1B also hardens the input boundary:

- **Strict candidate type + full structure.** A candidate must be an actual
  `OdometryCandidate` instance (a complete duck-typed fake is rejected with
  `CANDIDATE_STRUCTURE_INVALID`), and — when it claims `valid=True` — must carry
  a coherent payload: fixed `timestamp_policy` / `frame_id` / `covariance_policy`,
  3-component finite position/velocity/rpy, a 4-component finite quaternion with
  non-zero norm, in-range integer timestamps, and `warnings`/`errors` that are
  lists of strings. A legitimately invalid adapter output (`valid=False`) stays a
  well-formed typed failure and routes to `EMPTY_OR_INVALID_SEQUENCE`.
- **Non-mapping adapter input fails closed.** `to_odometry_candidate(None |
  list | int | object)` returns an invalid candidate with an explicit error and
  never raises.
- **Contract string semantics.** When arbitration/child-frame resolution flags
  are set, the corresponding string must be non-empty after `strip()` and — for
  the authoritative channel — in the adapter allow-list. A whitespace-only value,
  an out-of-allow-list channel, or a resolved value present while its flag is
  false all raise `EVIDENCE_CONTRACT_INVALID`.
- **Covariance / dynamic flags always contradict in R1.** Because the model
  carries no covariance values and no typed dynamic-evidence object, an asserted
  `covariance_available` always raises `COVARIANCE_EVIDENCE_CONTRADICTION` and an
  asserted `dynamic_motion_evidence_available` always raises
  `DYNAMIC_EVIDENCE_CONTRADICTION`. Numeric spread (micro-noise, constant
  velocity, cross-channel deltas) is an observation, never dynamic proof.

**R2 is required** before any of the withheld axes can change: it must introduce
**versioned evidence models** (a real covariance model with provenance, a typed
dynamic-motion-evidence object with displacement ground truth, and physical
axis/scale/sign validation). Until then, the boundary holds unconditionally.

The current-fixture result is unchanged: the same eleven blockers in the same
order, `NOT_READY`, `publication_capability = WITHHELD_BY_R1_BOUNDARY`.

## 11. R1C — malformed-sequence and mapping exception paths closed

MVP-ODOM-TF-R1C removes further input paths where a malformed sequence or a
defective mapping could raise instead of returning a fail-closed report --
specifically the *sample-shape* and *sequence-iteration* paths (a non-Mapping
sample, a Mapping whose `get()` raises, a candidate sequence whose iterator
raises). It does not close every value-normalization path inside an
otherwise-well-formed `Mapping`; see section 12 (R1D) for the paths R1C left
open. The `Never raises on malformed input` contract now holds for the cases
above, and the R1 non-publishable boundary is unchanged.

- **Channels derived from valid candidates only.** An invalid candidate can
  carry `source_channel = None` (e.g. from a non-mapping input). The report's
  `channels` are now built solely from **valid** candidates restricted to the
  adapter allow-list, so a mixed valid/invalid sequence never sorts `None`
  against `str`. `channels` is always a deterministic `tuple[str, ...]` with no
  `None`/int/object; a mixed sequence reports only the valid channel(s), and a
  fully-invalid sequence reports `channels = ()`. `candidate_count` and
  `candidate_invalid_count` are unchanged by this.
- **Broken iterables fail closed.** Materializing the candidate sequence now
  catches ordinary exceptions (`except Exception`), so an iterable whose
  `__iter__`/`__next__` raises `ValueError`/`RuntimeError` yields a fail-closed
  `EMPTY_OR_INVALID_SEQUENCE` report (bounded message, no secrets or large
  `repr()`), never a propagated exception. `BaseException`,
  `KeyboardInterrupt`, `SystemExit`, and `GeneratorExit` are never swallowed.
- **Strict Mapping and protected extraction.** `to_odometry_candidate` now
  requires a real `collections.abc.Mapping` — an object that merely exposes a
  `get()` method is not sufficient — and wraps the field extraction fail-closed,
  so a defective `Mapping` subclass whose `get()` raises still returns an invalid
  candidate with a bounded error message instead of propagating.
- **Strict numeric components (readiness gate only).** The readiness gate's
  own structural validator (`assess_odom_tf_readiness`) rejects `bool`
  wherever a real number is required (position, velocity, rpy, quaternion,
  `yaw_speed`) via a private, gate-local check; `True`/`False` no longer pass
  as `1`/`0` there. This did **not** yet extend to the adapter's own shared
  numeric helpers in `validation.py`: `to_odometry_candidate` could still
  build a `valid=True` candidate carrying a `bool` component, relying on this
  gate-local check to catch it later -- a real, if narrow, contradiction of
  the adapter's own contract. R1D (section 12) closes that gap at the source.

## 12. R1D — malformed payload normalization paths closed

MVP-ODOM-TF-R1D closes the residual paths where a `Mapping` sample with
malformed *values* -- not a malformed sample shape, which R1C already
covered -- could make `to_odometry_candidate()` raise, or let a `bool` pass as
a valid number. R1C hardened field **extraction** (a non-Mapping input, a
`Mapping` whose `get()` raises, a broken candidate-sequence iterator); it did
not close every **value-normalization** path for the fields once extracted
from an otherwise well-formed `Mapping`. The R1 non-publishable boundary and
the current-fixture result are unchanged (the same eleven blockers,
`NOT_READY`, `publication_capability = WITHHELD_BY_R1_BOUNDARY`).

- **`imu_quaternion` / `imu_rpy` are required and validated before
  `tuple()`.** Previously
  `quaternion_tuple = tuple(quaternion) if quaternion else (0.0, 0.0, 0.0, 0.0)`
  ran unconditionally: a truthy non-iterable (e.g. `imu_quaternion = True`)
  reached `tuple(True)` and raised `TypeError`, and a missing value silently
  defaulted to a zero orientation on a `valid=True` candidate instead of being
  rejected. Both fields are now validated with the same fail-closed,
  exception-safe shape/finiteness check used for position/velocity (list/tuple
  of the exact length, finite non-bool components) *before* any `tuple()`
  conversion; a missing, wrong-length, non-finite, or non-sequence value
  yields an invalid candidate, never an exception. A `valid=True` candidate's
  quaternion must additionally have a non-zero norm.
- **`bool` rejected as a number everywhere, in both the adapter and the
  readiness gate.** `is_finite_number()` used bare `math.isfinite()`, and
  `bool` is a subclass of `int` in Python, so `True`/`False` passed as `1`/`0`.
  This let a `bool` in position, velocity, yaw_speed, or an IMU vector produce
  a `valid=True` adapter candidate that only the readiness gate's separate,
  stricter structural check would later reject -- the adapter's own contract
  was violated in the meantime (see the corrected claim in section 11).
  `is_finite_number()` now explicitly rejects `bool` before checking
  `math.isfinite()`, and `all_finite()` and the new `is_finite_vector()` helper
  share that fix, so `_is_reliable_imu_vector()` (gyro/accel reliability) and
  the adapter's own position/velocity/yaw_speed/quaternion/rpy checks all
  reject `bool` consistently, matching the readiness gate. No NumPy was
  introduced.
- **Timestamps validated instead of silently defaulted.** `stamp_sec` and
  `stamp_nanosec` were previously coerced to `0` on any non-`int` value
  (including `bool`) rather than invalidating the candidate, and
  `receipt_wall_utc_ns` was passed through completely unchecked. All three are
  now validated as non-negative, non-bool integers (`stamp_nanosec`
  additionally bounded to `[0, 999999999]`; `receipt_wall_utc_ns` may be
  `None`); a malformed timestamp yields `valid=False` instead of a silently
  substituted default.
- **Exception-safe by construction, not by patchwork.** The shared vector
  helper (`is_finite_vector`) and `all_finite()` fail closed against a
  defective sequence (e.g. a list subclass whose `__iter__` raises) on their
  own, and the adapter's validation/construction step is wrapped in a final
  `except Exception` that converts any residual ordinary exception into an
  invalid candidate. `BaseException`, `KeyboardInterrupt`, `SystemExit`, and
  `GeneratorExit` are never swallowed. Error messages stay bounded (field name
  and exception type only, never a full `repr()` of the offending value).

The real MFR-R6 fixtures are unaffected: all 160 samples already carry
finite, non-bool position/velocity/yaw_speed, a unit-norm `imu_quaternion`,
and a well-formed `imu_rpy`, with valid (zero) timestamps, so they remain
`valid=True` and the readiness gate's result is unchanged (same eleven
blockers, same two channels, `publication_capability =
WITHHELD_BY_R1_BOUNDARY`).

## 13. R1D-R1 — invalid-candidate normalization and IMU fault isolation

An independent pre-push audit of the R1D local commit (`490c2c49...`) found
two reproducible defects before any push, both closed here without touching
the R1D commit itself. The R1 non-publishable boundary and the real-fixture
result are unchanged (same eleven blockers, `NOT_READY`,
`publication_capability = WITHHELD_BY_R1_BOUNDARY`).

- **Invalid-candidate timestamp fields are now normalized.** `_invalid()`
  used bare `isinstance(x, int)` for `receipt_monotonic_ns` /
  `message_stamp_sec` / `message_stamp_nanosec` -- which accepts `bool`
  unchanged, since `bool` is a subclass of `int` -- and passed
  `receipt_wall_utc_ns` through with no validation at all. An invalid
  candidate could therefore store a literal `True`/`False` where the model
  declares `int`, or an arbitrary, non-JSON-serializable object where it
  declares `int | None`. All four fields are now normalized through
  `is_nonnegative_int` (which excludes `bool`), with canonical `0` / `None`
  fallbacks and `message_stamp_nanosec` additionally range-checked; every
  invalid candidate is now a well-typed, deterministic, JSON-serializable
  `OdometryCandidate` regardless of how malformed the input was.
  `source_channel` was intentionally left untouched -- no reproducible
  defect was found there.
- **A pathological auxiliary gyro/accelerometer no longer invalidates the
  whole candidate.** The former `_is_reliable_imu_vector()` called
  `len(values)` unprotected; a value whose `__len__` raised propagated an
  exception that the adapter's function-wide `except Exception` then caught,
  demoting the *entire* candidate to `valid=False` even when
  position/velocity/yaw/orientation were all valid -- contradicting the
  R1A-established, R1D-restated contract that a malformed/unreliable
  auxiliary sensor must only degrade its own reliability flag. A single
  fail-closed classifier, `_classify_imu_vector()` /
  `_imu_reliability_and_warning()`, replaces it: it distinguishes `MISSING` /
  `MALFORMED` / `NON_FINITE` / `ALL_ZERO` / `RELIABLE` in one narrow `try`
  block (the only place `len()`/iteration is attempted on that value), and
  only ever feeds the sensor's own reliability flag and warning text.
- **The function-wide `except Exception` safety net is removed.** R1D
  introduced a `try`/`except Exception` wrapping the adapter's entire
  validation-and-construction body as a catch-all. Now that every
  payload-dependent operation is protected at its own narrow, purpose-built
  helper (`is_finite_vector` via `_vector_error` for position/velocity/
  quaternion/rpy, `_classify_imu_vector` for the auxiliary IMU vectors), that
  blanket boundary is no longer needed and has been removed, so a genuine
  internal programming bug elsewhere in the function can no longer be
  silently converted into an "invalid candidate" result. `BaseException`,
  `KeyboardInterrupt`, `SystemExit`, and `GeneratorExit` were never caught by
  the removed boundary either, and remain uncaught.

The real MFR-R6 fixtures are unaffected: none of their 160 samples exercise
either defect, so they remain `valid=True` with the readiness gate's result
unchanged.
