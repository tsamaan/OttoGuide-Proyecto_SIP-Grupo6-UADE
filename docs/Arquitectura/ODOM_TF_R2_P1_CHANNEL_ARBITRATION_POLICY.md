# ODOM/TF R2-P1 — Channel Arbitration Policy

## Invariant

```
AUTHORITATIVE_SOURCE_CHANNEL = null   (always, by construction)
PREFERRED_ANALYSIS_CHANNEL   = rt/odommodestate | rt/lf/odommodestate | null
```

`PREFERRED_ANALYSIS_CHANNEL` is enforced (`models.ChannelArbitrationMatrix.__post_init__`)
to never equal `AUTHORITATIVE_SOURCE_CHANNEL` — the two concepts are
structurally distinct. Selecting an authoritative channel for `/odom`
publication is explicitly out of scope through at least P2; this file
documents *only* the data-driven preference signal P1 computes for guiding
which stream a human/P2 checkpoint might analyze further.

## Criteria (see `arbitration.py::build_arbitration_matrix`)

| Criterion | Source | Direction |
|---|---|---|
| `data_completeness` | `ChannelQualityMetrics.sample_count` | higher is better, but is explicitly an observation only (checkpoint section 10: "la frecuencia o cantidad de muestras no determina autoridad física") |
| `sample_rate` | `mean_rate_hz` | higher is better |
| `jitter` | `jitter_mad_ms` | lower is better |
| `gaps` | `gap_count` | lower is better |
| `dropouts` | `dropout_count` | lower is better |
| `imu_consistency` | count of IMU cross-check records against the primary channel | not discriminating (P1 only cross-checks primary; see next-checkpoint plan) |
| `reset_behavior` | shared with both channels | not discriminating |
| `provenance_quality` | shared manifest verification | not discriminating |
| `ground_truth_support` | shared R4B annotation | not discriminating |

`PREFERRED_ANALYSIS_CHANNEL` is only set when one channel clears at least 2
`PASS` criteria more than the other; otherwise it remains `null`. This
threshold is intentionally conservative — a single-criterion edge is not
treated as a preference signal.

## Why this is a *policy* document, not a decision record

Every field driving this matrix is itself `PARTIAL`/`VERIFIED`-but-narrow
evidence from P1 (see `R2_P1_CHANNEL_ARBITRATION_MATRIX.json`). A future
checkpoint (P2+) that wants to actually select an authoritative channel must
do so as an explicit, separately-authorized action — this document and its
matrix output are inputs to that future decision, not the decision itself.
