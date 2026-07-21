"""Stationary-window and dynamic-motion-segment metrics (sections 24-26)."""
import math

from src.navigation.odometry_evidence_r2.validation import EvidenceValidationError

from . import statistics as p1stats
from .models import (
    CHARACTERIZATION_SCHEMA_VERSION,
    MotionSegmentMetrics,
    NominalScaleCandidate,
    NominalYawGainCandidate,
    StationaryWindowMetrics,
)

REFERENCE_ORIGIN_POLICY = "LOCAL_SEGMENT_BASELINE_NOT_ABSOLUTE_ORIGIN"

# Nominal operator-attempted values, straight from the checkpoint's own
# section 9.3/26 record of what the operator attempted -- NEVER a
# calibrated/measured ground truth.
NOMINAL_TRANSLATION_M = {
    "forward_x_valid_retry": 2.0,
    "forward_y": 1.0,
}
NOMINAL_YAW_RAD = {
    "left_90_first": math.pi / 2,
    "left_180_operator_corrected": math.pi,
    "left_90_valid_retry_local_baseline": math.pi / 2,
}


def compute_stationary_window(*, session_id: str, channel: str, phase: str,
                               samples: tuple) -> StationaryWindowMetrics:
    if not samples:
        raise EvidenceValidationError("cannot compute a stationary window over 0 samples")
    positions = [s.position for s in samples]
    times_s = [s.receipt_monotonic_ns / 1e9 for s in samples]
    duration_s = times_s[-1] - times_s[0] if len(times_s) > 1 else 0.0

    per_axis_mean, per_axis_median, per_axis_stddev, per_axis_mad, per_axis_p95, per_axis_slope = (
        [], [], [], [], [], [],
    )
    for axis in range(3):
        values = [p[axis] for p in positions]
        mean_v = sum(values) / len(values)
        stddev_v = math.sqrt(sum((v - mean_v) ** 2 for v in values) / len(values)) if len(values) > 1 else 0.0
        median_v = p1stats.median(values)
        mad_v = p1stats.mad(values)
        p95_v = p1stats.percentile([abs(v - mean_v) for v in values], 0.95)
        if duration_s > 0:
            slope_v = (values[-1] - values[0]) / duration_s
        else:
            slope_v = 0.0
        per_axis_mean.append(mean_v)
        per_axis_median.append(median_v)
        per_axis_stddev.append(stddev_v)
        per_axis_mad.append(mad_v)
        per_axis_p95.append(p95_v)
        per_axis_slope.append(slope_v)

    yaw_speeds = [s.yaw_speed for s in samples]
    yaw_speed_bias = sum(yaw_speeds) / len(yaw_speeds)
    yaw_drift_slope = (yaw_speeds[-1] - yaw_speeds[0]) / duration_s if duration_s > 0 else 0.0

    outlier_count = 0
    for axis in range(3):
        threshold = 6.0 * per_axis_mad[axis] if per_axis_mad[axis] > 0 else 6.0 * per_axis_stddev[axis]
        if threshold > 0:
            outlier_count += sum(1 for p in positions if abs(p[axis] - per_axis_mean[axis]) > threshold)

    return StationaryWindowMetrics(
        schema_version=CHARACTERIZATION_SCHEMA_VERSION,
        evidence_id=f"p1.stationary.{session_id}.{phase}.{channel.replace('/', '_')}",
        session_id=session_id,
        channel=channel,
        phase=phase,
        sample_count=len(samples),
        duration_s=duration_s,
        observed_mean=tuple(per_axis_mean),
        median=tuple(per_axis_median),
        stddev=tuple(per_axis_stddev),
        mad=tuple(per_axis_mad),
        p95_deviation=tuple(per_axis_p95),
        linear_drift_slope=tuple(per_axis_slope),
        yaw_speed_bias=yaw_speed_bias,
        yaw_drift_slope=yaw_drift_slope,
        outlier_count=outlier_count,
        reference_origin_policy=REFERENCE_ORIGIN_POLICY,
        status="VERIFIED",
        limitations=(
            "observed_mean/median/stddev/mad/p95_deviation are direct descriptive "
            "statistics of the segment's own raw position samples, computed by "
            "reparsing raw JSONL (section 19) rather than reused from P0A's derived "
            "reports; this is NOT a validated covariance matrix.",
        ),
    )


def _dominant_axis(delta):
    magnitudes = [abs(v) for v in delta[:2]]  # planar (x,y) only; z ~ constant height
    if magnitudes[0] >= magnitudes[1]:
        return "x", delta[0], abs(delta[1])
    return "y", delta[1], abs(delta[0])


def compute_motion_segment(*, session_id: str, segment_name: str, channel: str, valid: bool,
                            ground_truth_constraint: str, samples: tuple) -> MotionSegmentMetrics:
    if not samples:
        raise EvidenceValidationError(f"segment {segment_name!r} has 0 samples")
    session_ids = {s.session_id for s in samples}
    if len(session_ids) > 1:
        raise EvidenceValidationError(f"segment {segment_name!r} spans more than one session_id: {session_ids!r}")
    boot_ids = {s.boot_id for s in samples}
    if len(boot_ids) > 1:
        raise EvidenceValidationError(f"segment {segment_name!r} spans more than one boot_id: {boot_ids!r}")
    start = samples[0]
    end = samples[-1]
    delta = tuple(round(end.position[i] - start.position[i], 6) for i in range(3))
    planar_displacement = math.sqrt(delta[0] ** 2 + delta[1] ** 2)
    axis_name, axis_projection, cross_axis = _dominant_axis(delta)

    times_s = [s.receipt_monotonic_ns / 1e9 for s in samples]
    duration_s = times_s[-1] - times_s[0] if len(times_s) > 1 else None
    yaw_speeds = [s.yaw_speed for s in samples]

    integrated_yaw_rad = None
    if duration_s and len(samples) > 1:
        integrated_yaw_rad = 0.0
        for (t_a, y_a), (t_b, y_b) in zip(zip(times_s, yaw_speeds), zip(times_s[1:], yaw_speeds[1:])):
            integrated_yaw_rad += 0.5 * (y_a + y_b) * (t_b - t_a)

    path_length_candidate = None
    velocities = [math.sqrt(s.velocity[0] ** 2 + s.velocity[1] ** 2) for s in samples]
    mean_velocity = sum(velocities) / len(velocities) if velocities else None
    max_velocity = max(velocities) if velocities else None
    if duration_s and mean_velocity is not None:
        path_length_candidate = mean_velocity * duration_s

    limitations = [
        "delta_position/planar_displacement are raw first-to-last position "
        "differences in the source-channel candidate frame; not scale- or "
        "sign-validated, and not a calibrated distance measurement.",
    ]
    if not valid:
        limitations.append(
            "this segment is EXCLUDED from all scale/axis/arbitration analysis; "
            "metrics are computed here only for transparency/audit, never used "
            "as evidence."
        )

    return MotionSegmentMetrics(
        schema_version=CHARACTERIZATION_SCHEMA_VERSION,
        evidence_id=f"p1.motion.{session_id}.{segment_name}.{channel.replace('/', '_')}",
        session_id=session_id,
        segment_name=segment_name,
        channel=channel,
        valid=valid,
        ground_truth_constraint=ground_truth_constraint,
        start_position=start.position,
        end_position=end.position,
        delta_position=delta,
        planar_displacement=planar_displacement,
        dominant_axis=axis_name,
        dominant_axis_projection=axis_projection,
        cross_axis_displacement=cross_axis,
        path_length_candidate=path_length_candidate,
        start_yaw_speed=start.yaw_speed,
        end_yaw_speed=end.yaw_speed,
        integrated_yaw_speed_rad=integrated_yaw_rad,
        duration_s=duration_s,
        mean_velocity=mean_velocity,
        max_velocity=max_velocity,
        sample_count=len(samples),
        status="VERIFIED" if valid else "INVALID",
        limitations=tuple(limitations),
    )


def compute_nominal_scale_candidate(*, segment_name: str, motion_metrics: MotionSegmentMetrics,
                                     source_sha256: tuple) -> "NominalScaleCandidate | None":
    nominal = NOMINAL_TRANSLATION_M.get(segment_name)
    if nominal is None or not motion_metrics.valid:
        return None
    observed = motion_metrics.planar_displacement
    ratio = (observed / nominal) if nominal else None
    return NominalScaleCandidate(
        evidence_id=f"p1.nominal_scale.{segment_name}",
        segment_name=segment_name,
        operator_nominal_value_m=nominal,
        observed_value_m=observed,
        ratio=ratio,
        ground_truth_mode="BEST_EFFORT_MEASURED",
        uncertainty_status="UNBOUNDED_NO_INSTRUMENT",
        source_sha256=source_sha256,
        status="BEST_EFFORT_ONLY",
        limitations=(
            "operator_nominal_value_m is what the operator attempted, not a "
            "calibrated measurement; ratio is a best-effort candidate only, "
            "never used to declare TRANSLATION_SCALE resolved.",
        ),
    )


def compute_nominal_yaw_gain_candidate(*, segment_name: str, motion_metrics: MotionSegmentMetrics,
                                        source_sha256: tuple) -> "NominalYawGainCandidate | None":
    nominal = NOMINAL_YAW_RAD.get(segment_name)
    if nominal is None or not motion_metrics.valid or motion_metrics.integrated_yaw_speed_rad is None:
        return None
    observed = motion_metrics.integrated_yaw_speed_rad
    ratio = (observed / nominal) if nominal else None
    return NominalYawGainCandidate(
        evidence_id=f"p1.nominal_yaw_gain.{segment_name}",
        segment_name=segment_name,
        operator_nominal_yaw_rad=nominal,
        observed_integrated_yaw_rad=observed,
        ratio=ratio,
        ground_truth_mode="BEST_EFFORT_MEASURED",
        uncertainty_status="UNBOUNDED_NO_INSTRUMENT",
        source_sha256=source_sha256,
        status="BEST_EFFORT_ONLY",
        limitations=(
            "operator_nominal_yaw_rad is the operator-attempted turn angle, not a "
            "calibrated measurement; ratio is a best-effort candidate only, "
            "never used to declare YAW_SCALE resolved.",
        ),
    )
