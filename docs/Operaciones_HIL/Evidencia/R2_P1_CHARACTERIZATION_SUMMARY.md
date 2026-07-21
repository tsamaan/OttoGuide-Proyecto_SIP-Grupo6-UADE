# MVP-ODOM-TF-R2-P1 — Characterization Summary

Base: R2-P0A HEAD `110e01558a3a077c156270dfff7d383686b51501`.

## Headline numbers (this run, `2026-07-21T16:00:00Z` injected)

- Channel-quality records: 6 (primary+LF × R3C/R4/R4B)
- Primary/LF alignment records: 11
- Stationary-window records: 10
- Motion-segment records: 16 (7 R4B named segments × up to 2 channels, plus 2 R3C route_active)
- IMU cross-check records: 9
- Timebase records: 3 (one per session)
- Nominal scale/yaw candidates: 2 / 3
- Dynamic residual records: 17
- Claims: 7 (`CHANNEL_QUALITY`, `PRIMARY_LF_ALIGNMENT`, `CHANNEL_ARBITRATION`,
  `TRANSLATION_SCALE`, `YAW_SCALE`, `TIMEBASE_ORDERING`, `IMU_CROSSCHECK`)
- `AUTHORITATIVE_SOURCE_CHANNEL = null`, `PREFERRED_ANALYSIS_CHANNEL = rt/odommodestate`
  (data-driven, from `R2_P1_CHANNEL_ARBITRATION_MATRIX.json`)

## R4B best-effort scale/yaw candidates (never resolved, never calibrated)

| Segment | Nominal | Observed | Ratio |
|---|---|---|---|
| forward_x_valid_retry | 2.0 m | 2.013 m | 1.006 |
| forward_y | 1.0 m | 1.036 m | 1.036 |
| left_90_first | 90° | 38.2° | 0.424 |
| left_180_operator_corrected | 180° | 165.4° | 0.919 |
| left_90_valid_retry_local_baseline | 90° | 61.6° | 0.684 |

Translation ratios cluster tightly around 1.0 (consistent scale on the
forward segments); yaw ratios are widely spread (0.42–0.92), most plausibly
reflecting best-effort manual turns without an instrument rather than a
odometry gain defect (see `R2_P1_NEXT_CHECKPOINT_PLAN.md`).

## What changed from P0A (see `R2_P1_CLAIMS_DELTA_FROM_P0A.json`)

`IMU_CROSSCHECK` advanced from `PARTIAL` to `PARTIAL_QUANTIFIED` — P0A only
had a qualitative sign-agreement note; P1 quantifies sign agreement and
sample coverage per segment from raw LowState/SportModeState reparse. Six
other claim IDs (`CHANNEL_QUALITY`, `PRIMARY_LF_ALIGNMENT`,
`CHANNEL_ARBITRATION`, `TRANSLATION_SCALE`, `YAW_SCALE`,
`TIMEBASE_ORDERING`) are new in P1 (P0A never computed a quantitative
channel-quality or alignment metric).

## Full detail

See `R2_P1_RESULT.json` (full bundle), the per-topic JSON/CSV files under
`03_OUTPUTS/`, and `R2_P1_LIMITATIONS.md` for the honest boundaries of every
number above (IMU gyroscope units, R4B phase-occurrence disambiguation, the
boot-relation observation P0A never surfaced, etc.).
