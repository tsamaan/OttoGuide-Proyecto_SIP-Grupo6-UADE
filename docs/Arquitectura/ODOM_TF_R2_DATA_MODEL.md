# ODOM/TF R2-P0 — Data Model

All dataclasses live in `src/navigation/odometry_evidence_r2/models.py`, are
`@dataclass(frozen=True, kw_only=True)`, and are constructed only by
`ingest.py` (or tests) after validation. `SCHEMA_VERSION = "2.0.0-p0"`.

## Common fields (section 14.1)

Most records carry: `schema_version`, `evidence_id`, `status`, `confidence`,
`source_files`, `source_sha256`, `session_id` / `boot_id` where applicable,
`limitations`. `EvidenceProvenance` is the one exception — it is a low-level
fact record (what file, what hash, what script produced it), not itself a
claim, so it has no `status`/`confidence`.

## Status vocabulary (section 14.2)

`VERIFIED | SUPPORTED_INFERENCE | PARTIAL | UNRESOLVED | NOT_AVAILABLE | NOT_EXECUTED | INVALID | SUPERSEDED`

## Ground-truth vocabulary (section 13.4)

`MEASURED | BEST_EFFORT_MEASURED | NOMINAL | OPERATOR_ANNOTATED | NOT_AVAILABLE | INVALID`

`validation.validate_ground_truth` rejects any other string. Nothing in this
package promotes `NOMINAL`/`BEST_EFFORT_MEASURED` to `MEASURED`.

## Models

| Class | Purpose | Hard-enforced invariant |
|---|---|---|
| `EvidenceProvenance` | source file + hash + transformation script + injected `generated_utc` | — |
| `PhysicalSessionEvidence` | one ingested session (R3C/R4/R4B) | `session_type` restricted to the 3 known values |
| `SessionTimeDomain` | message stamp / receipt monotonic / receipt UTC / RTT for one session+boot | — |
| `DynamicMotionSegment` | one motion interval (route phase or R4B annotated segment) | — |
| `StationarySegment` | one stationary window's position/yaw-speed dispersion | — |
| `AxisResponseObservation` | translation-axis response claim | — |
| `YawResponseObservation` | yaw-sign response claim | — |
| `ChannelComparisonEvidence` | primary vs LF comparison | `authoritative_source_channel` must be `None` |
| `ImuCrosscheckEvidence` | LowState IMU vs integrated SportModeState yaw_speed | — |
| `ResetDiscontinuityEvidence` | cross-boot discontinuity | `from_boot_id != to_boot_id`; `trajectory_concatenation_permitted` must be `False` |
| `LidarExtrinsicEvidence` | LiDAR frame/extrinsic candidates | — |
| `StationaryNoiseStatistics` | dispersion stats over a stationary window | — |
| `DynamicResidualStatistics` | per-segment residual stats | — |
| `CovarianceEvidence` | bounds what a future covariance model may claim | `publication_model_ready` must be `False`; must cite ≥1 statistics record |
| `EvidenceClaim` | one row of the R1→V19→R2-P0 claims ledger | `r2p0_state == "VERIFIED"` requires ≥1 `evidence_ids` |
| `PhysicalEvidenceBundleR2` | the full ingested bundle | — |

## Pipeline (`ingest.py`)

```
harvest_root, generated_utc
        │
        ├─ build_r3c_session   → PhysicalSessionEvidence, [DynamicMotionSegment], [StationarySegment]
        ├─ build_r4_session    → PhysicalSessionEvidence, SessionTimeDomain, ResetDiscontinuityEvidence
        ├─ build_r4b_session   → PhysicalSessionEvidence, [DynamicMotionSegment], [StationarySegment],
        │                        ChannelComparisonEvidence, ImuCrosscheckEvidence, LidarExtrinsicEvidence,
        │                        SessionTimeDomain, [StationaryNoiseStatistics]
        ├─ build_axis_and_yaw_observations
        ├─ build_covariance_evidence
        ├─ build_claims          (11-row static ledger, section 6)
        └─ build_bundle          → PhysicalEvidenceBundleR2
```

R3C's stationary/dynamic segments are computed by actually stream-parsing
the raw per-channel JSONL chunks under
`01_route_raw/extracted/run_<session>/recorder_data/{odom,lf_odom}/*.jsonl`
(grouped by each record's own `phase` tag) — not copied from a prior
session's derived report. R4B reuses the already-derived
`R4B_CHANNEL_COMPARISON.json` (itself hash-verified as part of the harvest)
rather than re-parsing ~56k raw R4B records, since that derivation was
already produced and verified in a prior checkpoint.

## Serialization (`report.py`)

`dumps_deterministic()` calls `dataclasses.asdict()` (tuples become JSON
arrays) then `json.dumps(..., sort_keys=True, indent=2)`. No wall clock, no
random iteration order (every `set()` comprehension used during ingestion is
wrapped in `sorted()` before being stored) — two runs over the same inputs
and the same injected `generated_utc` are byte-identical.
