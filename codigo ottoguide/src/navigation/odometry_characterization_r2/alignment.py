"""Primary/LF channel alignment within a single session (section 23)."""
import math

from . import statistics as p1stats
from .models import CHARACTERIZATION_SCHEMA_VERSION, ChannelAlignmentMetrics

MIN_PAIRS_FOR_LAG_CANDIDATE = 30
MIN_COVERAGE_FOR_LAG_CANDIDATE = 0.5
MIN_ABS_CORRELATION_FOR_LAG_CANDIDATE = 0.3


def compute_alignment(*, session_id: str, phase: str, primary_samples: tuple,
                       secondary_samples: tuple) -> "ChannelAlignmentMetrics | None":
    if not primary_samples or not secondary_samples:
        return None

    primary_times = [s.receipt_monotonic_ns / 1e9 for s in primary_samples]
    secondary_times = [s.receipt_monotonic_ns / 1e9 for s in secondary_samples]

    primary_intervals = [b - a for a, b in zip(primary_times, primary_times[1:]) if b > a]
    secondary_intervals = [b - a for a, b in zip(secondary_times, secondary_times[1:]) if b > a]
    reference_intervals = primary_intervals + secondary_intervals
    tolerance = (p1stats.median(reference_intervals) if reference_intervals else 0.05) * 1.5
    tolerance = max(tolerance, 0.01)

    pairs = p1stats.nearest_neighbor_pairing(primary_times, secondary_times, tolerance)
    paired_count = len(pairs)
    coverage = paired_count / min(len(primary_samples), len(secondary_samples))

    offsets = [offset for _, _, offset in pairs]
    if offsets:
        offset_median = p1stats.median(offsets)
        offset_p95 = p1stats.percentile([abs(o) for o in offsets], 0.95)
    else:
        offset_median = 0.0
        offset_p95 = 0.0

    position_errors, yaw_errors = [], []
    for i, j, _offset in pairs:
        p_sample = primary_samples[i]
        s_sample = secondary_samples[j]
        dx = p_sample.position[0] - s_sample.position[0]
        dy = p_sample.position[1] - s_sample.position[1]
        dz = p_sample.position[2] - s_sample.position[2]
        position_errors.append(math.sqrt(dx * dx + dy * dy + dz * dz))
        yaw_errors.append(p_sample.yaw_speed - s_sample.yaw_speed)

    def _agg(errors):
        if not errors:
            return None, None, None, None
        return (
            p1stats.mean_absolute_error(errors),
            p1stats.root_mean_square_error(errors),
            p1stats.percentile([abs(e) for e in errors], 0.95),
            max(abs(e) for e in errors),
        )

    position_mae, position_rmse, position_p95, position_max = _agg(position_errors)
    yaw_speed_mae, yaw_speed_rmse, yaw_speed_p95, yaw_speed_max = _agg(yaw_errors)

    correlation = None
    if len(pairs) >= 2:
        primary_yaw = [primary_samples[i].yaw_speed for i, _j, _o in pairs]
        secondary_yaw = [secondary_samples[j].yaw_speed for _i, j, _o in pairs]
        correlation = p1stats.pearson_correlation(primary_yaw, secondary_yaw)

    lag_candidate_ms = None
    lag_status = "UNRESOLVED"
    limitations = [
        "alignment is nearest-neighbor on receipt_monotonic_ns within a documented "
        "tolerance derived from the session's own observed sample periods; message "
        "timestamps are absent/zero in the source and are never used for alignment.",
    ]
    if (
        paired_count >= MIN_PAIRS_FOR_LAG_CANDIDATE
        and coverage >= MIN_COVERAGE_FOR_LAG_CANDIDATE
        and correlation is not None
        and abs(correlation) >= MIN_ABS_CORRELATION_FOR_LAG_CANDIDATE
    ):
        lag_candidate_ms = offset_median * 1000.0
        lag_status = "SUPPORTED_INFERENCE"
        limitations.append(
            f"lag_candidate_ms derived from median pairwise receipt-time offset over "
            f"{paired_count} paired samples (coverage={coverage:.3f}, "
            f"correlation={correlation:.3f}); never elevated beyond a candidate."
        )
    else:
        limitations.append(
            f"no lag candidate produced: paired_count={paired_count}, coverage={coverage:.3f}, "
            f"correlation={correlation!r} did not clear the documented thresholds "
            f"(>={MIN_PAIRS_FOR_LAG_CANDIDATE} pairs, >={MIN_COVERAGE_FOR_LAG_CANDIDATE:.2f} coverage, "
            f">={MIN_ABS_CORRELATION_FOR_LAG_CANDIDATE:.2f} abs correlation)."
        )

    status = "VERIFIED" if coverage >= 0.9 else "PARTIAL"

    return ChannelAlignmentMetrics(
        schema_version=CHARACTERIZATION_SCHEMA_VERSION,
        evidence_id=f"p1.alignment.{session_id}.{phase}",
        session_id=session_id,
        phase=phase,
        primary_sample_count=len(primary_samples),
        secondary_sample_count=len(secondary_samples),
        paired_sample_count=paired_count,
        pairing_coverage=coverage,
        time_offset_median_s=offset_median,
        time_offset_p95_s=offset_p95,
        lag_candidate_ms=lag_candidate_ms,
        lag_status=lag_status,
        position_mae=position_mae,
        position_rmse=position_rmse,
        position_p95=position_p95,
        position_max=position_max,
        yaw_speed_mae_rad_s=yaw_speed_mae,
        yaw_speed_rmse_rad_s=yaw_speed_rmse,
        yaw_speed_p95_rad_s=yaw_speed_p95,
        yaw_speed_max_rad_s=yaw_speed_max,
        correlation_position=correlation,
        status=status,
        limitations=tuple(limitations),
    )
