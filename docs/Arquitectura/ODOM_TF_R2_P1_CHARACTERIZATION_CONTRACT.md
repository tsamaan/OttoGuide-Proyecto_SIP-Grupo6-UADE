# ODOM/TF R2-P1 — Channel/Time/Motion Characterization Contract

`CHECKPOINT = MVP-ODOM-TF-R2-P1-CHANNEL-TIME-AND-MOTION-CHARACTERIZATION`
`CHARACTERIZATION_SCHEMA_VERSION = 2.1.0-p1`
`BASE_SHA = 110e01558a3a077c156270dfff7d383686b51501` (R2-P0A HEAD)

## Objective

Quantitatively and reproducibly characterize the two physical odometry
channels of the Unitree G1 (`rt/odommodestate`, `rt/lf/odommodestate`),
their timebases, sampling quality, primary/LF dynamic agreement, motion
response, and partial IMU coherence — **without** implementing or
publishing `/odom`, TF, `/scan`, a map, localization, Nav2, or movement.

## What P1 does NOT do

- Does not select `AUTHORITATIVE_SOURCE_CHANNEL` (always `null`).
- Does not resolve `TRANSLATION_SCALE` or `YAW_SCALE` (both remain
  `UNRESOLVED`; only `BEST_EFFORT_ONLY` candidates are produced).
- Does not resolve `CHILD_FRAME_ID` or `SOURCE_FRAME_SEMANTICS` beyond
  P0A's own `PARTIAL`/`UNRESOLVED` state.
- Does not produce a publication-ready covariance model
  (`COVARIANCE_PUBLICATION_MODEL_READY = false`).
- Does not modify P0/P0A code or claims retroactively.
- Does not import ROS, Nav2, DDS, or the live Unitree SDK.

## Package layout

```
src/navigation/odometry_characterization_r2/
  __init__.py         schema version constant
  models.py            frozen, kw_only, fail-closed dataclasses
  sample_loader.py      fail-closed raw JSONL reparse (new topic + full records)
  segmentation.py       phase-run grouping, R4B occurrence-order resolution
  channel_quality.py    rate/jitter/gap/dropout metrics (section 22)
  alignment.py           nearest-neighbor primary/LF pairing (section 23)
  motion.py               stationary windows + dynamic segments + nominal candidates
  imu.py                  LowState/SportModeState sign-agreement cross-check
  timebase.py             per-session timebase characterization
  arbitration.py          channel arbitration matrix (never selects a channel)
  statistics.py           percentile/MAD/robust-gap-threshold/pairing helpers
  report.py               orchestration + JSON/CSV document builders

tools/hil/offline_navigation/characterize_physical_odometry_r2.py   CLI
```

## Reuse of the P0A trust boundary

P1 never duplicates P0A's private, narrow JSONL parser
(`odometry_evidence_r2.ingest._parse_channel_jsonl_dir`, which is scoped to
only two odom topics and reduces every record to position+yaw_speed). It
reuses, unmodified:

- `odometry_evidence_r2.source_manifest` — descriptor load, harvest
  resolution, manifest+per-file hash verification.
- `odometry_evidence_r2.validation` — `EvidenceValidationError`,
  `is_finite_number`, path/sha helpers.
- `odometry_evidence_r2.statistics.compute_scalar_stats` /
  `compute_vector_stats` (re-exported from P1's own `statistics.py`).
- `odometry_evidence_r2.ingest.R3C_PRE_REBOOT_BOOT_SENTINEL` /
  `R4B_BOOT_SENTINEL_UNRESOLVED` (the same documented sentinels, not
  redefined).

P1's `sample_loader.py` implements new parsing code for genuinely new scope:
full records (not reduced to position+yaw_speed), a third topic
(`rt/lowstate`) P0A's parser explicitly rejects, and R4B's raw flat JSONL
files (which P0A never reparsed — P0A's R4B ingestion only read the six
already-derived report JSON files). It is fail-closed on structural
corruption exactly like P0A (non-UTF-8, malformed JSON, non-terminal NUL,
non-finite values, unknown topic) but *counts* rather than aborts on
duplicate/out-of-order sequences, since quantifying such defects is P1's
explicit purpose.

## Raw sources reparsed directly by P1

| Session | Primary/LF odom | LowState |
|---|---|---|
| R3C (`hilroute-...`) | `01_route_raw/extracted/run_.../recorder_data/{odom,lf_odom}/*.jsonl` (104 chunks each) | `recorder_data/lowstate/*.jsonl` |
| R4 (`finalharvest-seated-...`) | `02_postboot_stationary/extracted/postboot_stationary/run_.../recorder_data/{odom,lf_odom}/*.jsonl` (54 chunks) | `recorder_data/lowstate/*.jsonl` |
| R4B (`gt-r4b-...`) | `10_r4b/R4B_{PRIMARY,SECONDARY}_ODOM_RAW.jsonl` (flat) | `10_r4b/R4B_LOWSTATE_RAW.jsonl` |

Every raw file read is hashed at read time and recorded in
`R2_P1_RAW_REPARSE_PROVENANCE.json` — P1's own provenance ledger, additional
to (not a replacement for) the 13-file P0A descriptor which only pins the
outer archive/report level.

## Determinism

`characterize_physical_odometry_r2.py --generated-utc <injected>` never
samples the wall clock or reads the network. Two runs with identical
arguments produce byte-identical output files (verified in
`tests/unit/test_odometry_characterization_r2.py::TestHarvestIntegration::test_cli_two_runs_byte_identical`
and independently via manual CLI invocation this checkpoint).
