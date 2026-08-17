# ODOM/TF R2-P1A — Arbitration and Units Policy

## Arbitration (H2/H6 hardening)

### The bug that was fixed

P1's `report.py` computed `primary_quality`/`secondary_quality` via
`next((q for q in all_quality if q.channel == X), None)` — grabbing only
the FIRST `ChannelQualityMetrics` match per channel (R3C, since sessions
were concatenated R3C+R4+R4B). Every other session's numbers were silently
discarded from the arbitration decision, while P1's own final report
claimed "primary edges out on ... gaps/dropouts" — the opposite of what the
aggregated numbers actually show (primary has more of both, in every
session).

### The fix

`arbitration.aggregate_channel_quality()` sums/weights every session's
metrics per channel before any criterion is scored. Only 2 criteria are
weighted into the decision (`jitter` and time gaps normalized per minute of
channel exposure, weight=1.0 each). The sequence-gap estimate is auxiliary,
not confirmed loss, and has weight=0.0 so it cannot duplicate the time-gap
signal;
`data_completeness` and `sample_rate` are recorded with weight=0.0 — sample
count/rate differences are a design artifact (primary runs ~2x LF's rate),
never a quality signal (checkpoint section 10).

### Criterion transparency (H6)

Every criterion is now an `ArbitrationScoringRule` with an explicit
`direction`, both channels' raw metric, `normalization`, `weight`, and
`winner`. `ArbitrationDecisionAudit.criterion_count` is asserted equal to
`len(criteria)` in `__post_init__` — this can never again silently drift
from the constructor call sites, closing H6's "7 reported, 9 serialized"
mismatch permanently (not just for the current run).

## Units (H5 hardening)

| Old P1 name | New name | Unit | Status |
|---|---|---|---|
| `yaw_mae`/`yaw_rmse`/`yaw_p95`/`yaw_max` | `yaw_speed_{mae,rmse,p95,max}_rad_s` | rad/s | computed, real |
| *(did not exist)* | `YawAngleResidualMetrics.yaw_angle_rmse_rad` | rad | structurally `None`/`NOT_AVAILABLE` |

`YawAngleResidualMetrics.__post_init__` raises `EvidenceValidationError` if
anyone ever tries to construct it with a non-`None` value while status is
`NOT_AVAILABLE` — enforcing that "no orientation data exists in the
recorder stream" stays true in code, not just in a docstring.

## Pairing offset vs. causal lag (H4 hardening)

- `PairingTimeOffsetMetrics`: pure descriptive nearest-neighbor time
  offset. No claim about causality.
- `CausalLagCandidate`: a real +/-100ms, 5ms-step cross-correlation scan of
  paired yaw_speed signals (`causal_lag.scan_causal_lag`), with an explicit
  check for aliasing near the LF channel's ~50ms sampling period (primary
  ~40Hz : LF ~20Hz is almost exactly 2:1). `status` is pinned to
  `UNRESOLVED` in the model itself — no code path can construct this record
  with any other status, matching section 21's claims enumeration.

## Boot relation (H8 hardening)

`BootRelationEvidence.same_boot_verified` requires BOTH sources to be
independently hash-verified (`source_a_hash_verified` /
`source_b_hash_verified`) AND `boot_id_a == boot_id_b` — never resolved by
bare textual similarity. `continuous_trajectory_permitted` is asserted
`False` unconditionally in `__post_init__`: same-boot evidence, however
strong, never by itself authorizes concatenating trajectories, time
domains, or captures (checkpoint section 20).
