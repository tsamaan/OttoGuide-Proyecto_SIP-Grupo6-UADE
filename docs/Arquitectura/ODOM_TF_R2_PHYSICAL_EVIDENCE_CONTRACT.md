# ODOM/TF R2-P0 / P0A — Physical Evidence Contract

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

## P0A — Trust boundary hardening (schema 2.0.1-p0a)

P0A raised `SCHEMA_VERSION` from `2.0.0-p0` to `2.0.1-p0a` and closed ten
audit findings (F1–F10) without changing any R2-P0 claim's substance. Full
detail: `docs/Operaciones_HIL/Evidencia/R2_P0A_TRUST_BOUNDARY_AUDIT.md` and
`docs/Operaciones_HIL/Evidencia/R2_P0A_DELTA_FROM_R2_P0.json`.

- **Parser is fail-closed** (`ingest._parse_channel_jsonl_dir`): strict
  UTF-8, typed errors on malformed JSON/unknown topic/non-positive,
  duplicate, or inverted `sequence`/non-finite values; every parse produces
  a `JsonlParseReport`. A NUL byte is tolerated ONLY if every byte from its
  first occurrence to EOF is NUL and it immediately follows a complete JSON
  line — anything else raises.
- **Every dataclass validates itself** in `__post_init__`: status/ground-truth
  vocabulary, non-empty ids, aligned `source_files`/`source_sha256` (with
  valid sha256 hex + portable relative paths), finite numbers, `bool`
  rejected as a number, `start_sequence <= end_sequence`,
  `valid`/`invalid_reason` coherence.
- **Every session has an explicit `SessionTimeDomain`** — R3C's was missing
  in R2-P0 (finding F3); `PhysicalEvidenceBundleR2.__post_init__` now
  enforces this structurally.
- **R4B's boot relation to R4 is stated as `UNRESOLVED`**, never implied as
  same/different (finding F4) — no direct evidence (boot-id file, uptime
  cross-check) exists for R4B's own boot.
- **The source manifest is enforced before ingest**
  (`source_manifest.verify_harvest_against_descriptor`): the portable
  descriptor now carries `manifest_sha256` and per-file
  `expected_source_sha256`; a modified source file or manifest produces a
  typed `FAIL`, never a silently-accepted new hash (finding F5).
- **Reset/discontinuity is three separate claims**, not one aggregated
  `VERIFIED`: `CROSS_BOOT_DISCONTINUITY_OBSERVED=VERIFIED`,
  `RESET_BEHAVIOR_CHARACTERIZED=PARTIAL`, `EXACT_RESET_INSTANT=UNRESOLVED`
  (finding F6). A bundle-level check also rejects any `VERIFIED` claim that
  cites evidence whose own `status` isn't itself `VERIFIED`.
- **R4B provenance records `DERIVATION_PROVENANCE = PARTIAL`** explicitly on
  every R4B provenance record: only the already-derived report file is
  hashed, not the raw per-sample JSONL/script/arguments (finding F7).
- **`StationaryNoiseStatistics` no longer hardcodes a bare `0.0` mean**:
  `observed_mean` (from the derived report) and `centered_mean` (always
  exactly `(0,0,0)` by construction, governed by `reference_origin_policy`)
  are now distinct, validated fields (finding F8). A single explicit
  `DynamicResidualStatistics(status="NOT_AVAILABLE_IN_P0A")` record replaces
  the previously ambiguous empty tuple for per-segment residuals (deferred
  to R2-P1).
- **Tests are portable**: `OTTOGUIDE_R2_HARVEST_ROOT` replaces every
  hardcoded personal path (finding F9); a static-gate test scans the whole
  R2 test suite for that path substring. Harvest-integration tests fail
  (not skip) if the variable is set but points nowhere.
- **`GroundTruthConstraint`** is a new typed model (mode, nominal
  translation/yaw, uncertainty, source, status) attached to R4B's annotated
  dynamic segments instead of a bare string.
