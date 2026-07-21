"""H4 audit: separate a pure pairing-time offset (descriptive) from a
causal-lag candidate (which requires real cross-correlation evidence and an
explicit sample-rate-aliasing check before it could ever be promoted).

Primary runs at ~40Hz, LF at ~20Hz -- almost exactly a 2:1 ratio. Any
lag-scan method that just picks the single nearest-neighbor offset is
vulnerable to aliasing: a peak near a multiple of the LF sampling period
(~50ms) does not distinguish "real causal delay" from "which of the two
candidate LF samples happened to be nearest." This module performs an
actual multi-lag cross-correlation scan on the paired yaw_speed signal and
explicitly checks for that failure mode. Per section 21's claims
enumeration, CAUSAL_CHANNEL_LAG has no non-UNRESOLVED value in this
checkpoint -- CausalLagCandidate.status is pinned to UNRESOLVED by the
model itself (models.py), regardless of what this scan finds.
"""
from . import statistics as p1stats
from .models import CausalLagCandidate

SCAN_HALF_WINDOW_MS = 100.0
SCAN_STEP_MS = 5.0
ALIASING_PERIOD_MS = 50.0  # ~1/20Hz LF sampling period
ALIASING_TOLERANCE_MS = 5.0


def _resample_secondary_at_lag(primary_times, secondary_times, secondary_values, lag_s):
    """Nearest-value lookup of secondary_values at (primary_time + lag_s)
    for each primary_time, restricted to lookups within half the median LF
    period (a tolerance derived from the data, not a hidden constant)."""
    if not secondary_times:
        return []
    tolerance = (p1stats.median([b - a for a, b in zip(secondary_times, secondary_times[1:])])
                 if len(secondary_times) > 1 else 0.05) * 0.6
    resampled = []
    j = 0
    n = len(secondary_times)
    for t in primary_times:
        target = t + lag_s
        while j + 1 < n and abs(secondary_times[j + 1] - target) <= abs(secondary_times[j] - target):
            j += 1
        if abs(secondary_times[j] - target) <= tolerance:
            resampled.append(secondary_values[j])
        else:
            resampled.append(None)
    return resampled


def scan_causal_lag(*, session_id: str, phase: str, primary_times, primary_yaw_speed,
                     secondary_times, secondary_yaw_speed) -> CausalLagCandidate:
    lags_ms = []
    correlations = []
    lag = -SCAN_HALF_WINDOW_MS
    while lag <= SCAN_HALF_WINDOW_MS + 1e-9:
        resampled = _resample_secondary_at_lag(primary_times, secondary_times, secondary_yaw_speed, lag / 1000.0)
        pairs = [(p, s) for p, s in zip(primary_yaw_speed, resampled) if s is not None]
        correlation = None
        if len(pairs) >= 10:
            xs = [p for p, _s in pairs]
            ys = [s for _p, s in pairs]
            correlation = p1stats.pearson_correlation(xs, ys)
        lags_ms.append(round(lag, 3))
        correlations.append(correlation)
        lag += SCAN_STEP_MS

    valid = [(l, c) for l, c in zip(lags_ms, correlations) if c is not None]
    peak_lag = peak_corr = zero_corr = None
    aliasing_risk = "NOT_APPLICABLE"
    rejection_reason = "insufficient paired samples across the scan window"
    if valid:
        peak_lag, peak_corr = max(valid, key=lambda lc: lc[1])
        zero_matches = [c for l, c in valid if abs(l) < 1e-6]
        zero_corr = zero_matches[0] if zero_matches else None

        near_harmonic = any(
            abs(abs(peak_lag) - k * ALIASING_PERIOD_MS) <= ALIASING_TOLERANCE_MS
            for k in (1, 2, 3)
        )
        flat_across_harmonics = False
        harmonic_corrs = [c for l, c in valid if any(
            abs(abs(l) - k * ALIASING_PERIOD_MS) <= ALIASING_TOLERANCE_MS for k in (0, 1, 2, 3)
        )]
        if len(harmonic_corrs) >= 2:
            spread = max(harmonic_corrs) - min(harmonic_corrs)
            flat_across_harmonics = spread < 0.05

        if near_harmonic and flat_across_harmonics:
            aliasing_risk = "HIGH"
            rejection_reason = (
                f"peak correlation lag ({peak_lag} ms) sits near a multiple of the LF "
                f"sampling period ({ALIASING_PERIOD_MS} ms) and correlation is nearly flat "
                "across neighboring harmonics -- consistent with 2:1 sample-rate aliasing, "
                "not a genuine causal delay."
            )
        elif peak_corr is None or peak_corr < 0.3:
            aliasing_risk = "LOW"
            rejection_reason = f"peak correlation too weak ({peak_corr!r}) to support any lag claim."
        elif zero_corr is not None and (peak_corr - zero_corr) < 0.05:
            aliasing_risk = "MEDIUM"
            rejection_reason = (
                f"peak correlation ({peak_corr:.3f}) is not meaningfully higher than the "
                f"zero-lag correlation ({zero_corr:.3f}); no stable causal delay signature."
            )
        else:
            aliasing_risk = "LOW"
            rejection_reason = (
                "no cross-correlation confirmation protocol (bootstrap stability, "
                "independent-segment repeatability, confidence interval) was run this "
                "checkpoint; per section 21 CAUSAL_CHANNEL_LAG remains UNRESOLVED "
                "regardless of the observed peak."
            )

    return CausalLagCandidate(
        schema_version="2.1.1-p1a",
        evidence_id=f"p1a.causal_lag.{session_id}.{phase}",
        session_id=session_id,
        phase=phase,
        scan_lags_ms=tuple(lags_ms),
        scan_correlations=tuple(correlations),
        peak_lag_ms=peak_lag,
        peak_correlation=peak_corr,
        zero_lag_correlation=zero_corr,
        aliasing_risk=aliasing_risk,
        sample_rate_ratio="PRIMARY_APPROX_40HZ_LF_APPROX_20HZ_RATIO_2_TO_1",
        rejection_reason=rejection_reason,
        status="UNRESOLVED",
        limitations=(
            "CAUSAL_CHANNEL_LAG is pinned to UNRESOLVED in this checkpoint regardless of "
            "scan results (section 21); this record exists to make the underlying scan "
            "transparent and auditable, not to promote a lag value.",
            f"scan window +/-{SCAN_HALF_WINDOW_MS}ms in {SCAN_STEP_MS}ms steps; aliasing "
            f"period assumed {ALIASING_PERIOD_MS}ms from the LF channel's ~20Hz rate.",
        ),
    )
