# ODOM/TF R2-P0 — Physical Evidence Contract

## Scope

`src/navigation/odometry_evidence_r2/` ingests already-harvested, hash-verified
physical evidence from three human-operator-driven Unitree G1 sessions
(R3C, R4, R4B) into a typed, immutable, fail-closed model. It is strictly
offline: no network, no ROS, no DDS, no live Unitree SDK. It never publishes
`/odom`, TF, `/scan`, a map, localization, `cmd_vel`, or Nav2.

This package is separate from `odometry_candidate_adapter` (R1). R1 is left
untouched and remains the R1 baseline/regression contract; this package does
not modify `OdometryCandidate` or any R1 file.

## R1 → R2-P0 relationship

R1's claim `DYNAMIC_MOTION_EVIDENCE_MISSING` was correct when R1 was written
— at that time only stationary evidence existed. It is not retroactively
edited. In R2-P0 it is recorded as:

- `R1_DYNAMIC_MOTION_CLAIM = HISTORICALLY_CORRECT`
- `R2_DYNAMIC_MOTION_CLAIM = SUPERSEDED_BY_R3C_R4B_PHYSICAL_EVIDENCE`

R1's non-publishable boundary is unchanged:

```
ODOM_PUBLICATION_READY = false
ODOM_TO_BASE_LINK_TF_READY = false
NAV2_READY = false
PUBLICATION_CAPABILITY = WITHHELD_BY_R1_BOUNDARY
```

## The three ingested sessions

| Session | Type | Movement authority | Ground truth |
|---|---|---|---|
| `hilroute-20260720T194910Z` | R3C_MANUAL_PHYSICAL_ROUTE | human operator | NOT_AVAILABLE |
| `finalharvest-seated-20260720T205406Z` | R4_FINAL_PHYSICAL_HARVEST | n/a (stationary, post-boot) | n/a |
| `gt-r4b-20260720T213222Z` | R4B_FINAL_BEST_EFFORT_GROUND_TRUTH | human operator | BEST_EFFORT_MEASURED |

R3C and R4 belong to **different boot domains** and are never concatenated
into one trajectory (`ResetDiscontinuityEvidence.trajectory_concatenation_permitted`
is hard-enforced `False` at construction). R3C's own boot identity was never
captured on the robot; it is recorded as the sentinel
`R3C_PRE_REBOOT_BOOT_ID_NOT_CAPTURED`, never reused from R4's boot id.

R4B's `left_90_return_invalidated` segment (an operator-reported unintended
additional movement) is ingested but always marked `valid=False`,
`ground_truth_constraint="INVALID"`, and excluded from every axis/yaw/claim
computation. The historical `left_180` phase label says "CW"; the operator's
authoritative correction says the physical turn was left — the label string
is preserved for traceability but is never read as "clockwise".

## What R2-P0 does NOT resolve

These remain exactly as conservative as section 6 of the checkpoint requires:

- `AUTHORITATIVE_SOURCE_CHANNEL = null` (enforced by
  `ChannelComparisonEvidence.__post_init__`; higher sample rate is never
  treated as authority)
- `TRANSLATION_SCALE = UNRESOLVED`, `YAW_SCALE = UNRESOLVED`
- `CHILD_FRAME_ID = UNRESOLVED`, `SOURCE_FRAME_SEMANTICS = PARTIAL`
- `COVARIANCE_PUBLICATION_MODEL_READY = false` (enforced by
  `CovarianceEvidence.__post_init__`)

## Fail-closed guarantees

- No unknown dataclass field is accepted (Python's dataclass `__init__`
  signature rejects unexpected kwargs with `TypeError`).
- `bool` is never accepted where a number or bounded int is expected (bool
  is an `int` subclass in Python; every check gates on `type(x) is int`,
  reusing R1's `normalize_finite_number`/`is_bounded_int` conventions).
- NaN/Infinity/oversized-int-overflow are rejected by
  `validation.is_finite_number` (delegates to R1's `normalize_finite_number`).
- Absolute paths and `..` path-traversal segments are rejected by
  `validation.is_relative_portable_path`; `provenance.build_provenance`
  additionally verifies every source file is actually under the declared
  harvest root before recording its relative path.
- Every provenance record carries a real SHA-256 of the source bytes
  (`provenance.sha256_of_file`), computed at ingest time — never copied from
  a prior report without re-hashing.
- `EvidenceClaim.r2p0_state == "VERIFIED"` requires at least one
  `evidence_ids` reference (enforced at construction).

## Determinism

The CLI (`tools/hil/offline_navigation/ingest_physical_evidence_r2.py`)
takes `--generated-utc` as a required, explicit argument — it never samples
the wall clock internally. Running it twice against the same descriptor,
harvest, and `--generated-utc` produces byte-identical JSON output (verified
in `tests/unit/test_odometry_evidence_r2_cli_determinism.py`).
