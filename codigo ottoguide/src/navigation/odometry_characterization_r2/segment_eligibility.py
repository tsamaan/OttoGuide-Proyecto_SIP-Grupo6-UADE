"""H7 audit: explicit per-segment eligibility.

P1 already correctly excluded invalid segments from nominal scale/yaw-gain
candidates (`motion.compute_nominal_scale_candidate`/
`compute_nominal_yaw_gain_candidate` both check `.valid`), but it computed
alignment and IMU cross-check over EVERY R4B segment regardless of
validity -- including `left_90_return_invalidated` and
`forward_x_setup_not_executed`. That is legitimate for descriptive channel-
synchrony purposes (both channels are still time-synchronized during an
invalid segment), but P1 never said so explicitly. This module makes every
segment's eligibility for every purpose an explicit, typed record so a
claim can never again silently cite an ineligible segment.
"""
from .models import SegmentEligibility

VALID_MOTION_SEGMENTS = frozenset({
    "forward_x_valid_retry", "forward_y", "left_90_first",
    "left_180_operator_corrected", "left_90_valid_retry_local_baseline",
})
INVALID_MOTION_SEGMENTS = frozenset({
    "forward_x_setup_not_executed", "left_90_return_invalidated",
})
SCALE_ELIGIBLE_SEGMENTS = frozenset({"forward_x_valid_retry", "forward_y"})
YAW_GAIN_ELIGIBLE_SEGMENTS = frozenset({
    "left_90_first", "left_180_operator_corrected", "left_90_valid_retry_local_baseline",
})

_INVALID_REASONS = {
    "forward_x_setup_not_executed": "operator alignment/setup repositioning only; no intended translation executed",
    "left_90_return_invalidated": "operator reported unintended additional movement during this interval",
}


def r4b_segment_eligibility(session_id: str, segment_name: str) -> SegmentEligibility:
    if segment_name in VALID_MOTION_SEGMENTS:
        return SegmentEligibility(
            evidence_id=f"p1a.segment_eligibility.{session_id}.{segment_name}",
            session_id=session_id, segment_name=segment_name,
            valid_for_descriptive_analysis=True,
            valid_for_channel_alignment=True,
            valid_for_timebase=True,
            valid_for_imu_sign=True,
            valid_for_ground_truth=True,
            valid_for_translation_scale=segment_name in SCALE_ELIGIBLE_SEGMENTS,
            valid_for_yaw_gain=segment_name in YAW_GAIN_ELIGIBLE_SEGMENTS,
            invalid_reason=None,
            baseline_scope="R4B_FINAL_BEST_EFFORT_GROUND_TRUTH",
        )
    if segment_name in INVALID_MOTION_SEGMENTS:
        return SegmentEligibility(
            evidence_id=f"p1a.segment_eligibility.{session_id}.{segment_name}",
            session_id=session_id, segment_name=segment_name,
            valid_for_descriptive_analysis=True,
            valid_for_channel_alignment=True,
            valid_for_timebase=True,
            valid_for_imu_sign=True,
            valid_for_ground_truth=False,
            valid_for_translation_scale=False,
            valid_for_yaw_gain=False,
            invalid_reason=_INVALID_REASONS[segment_name],
            baseline_scope="R4B_FINAL_BEST_EFFORT_GROUND_TRUTH",
        )
    raise ValueError(f"unrecognized R4B segment for eligibility: {segment_name!r}")


def r3c_route_active_eligibility(session_id: str) -> SegmentEligibility:
    return SegmentEligibility(
        evidence_id=f"p1a.segment_eligibility.{session_id}.route_active",
        session_id=session_id, segment_name="route_active",
        valid_for_descriptive_analysis=True,
        valid_for_channel_alignment=True,
        valid_for_timebase=True,
        valid_for_imu_sign=True,
        valid_for_ground_truth=False,
        valid_for_translation_scale=False,
        valid_for_yaw_gain=False,
        invalid_reason="NOT_AVAILABLE: R3C has no metric ground truth (human-driven free-form route)",
        baseline_scope="R3C_MANUAL_PHYSICAL_ROUTE",
    )


def stationary_eligibility(session_id: str, phase: str) -> SegmentEligibility:
    return SegmentEligibility(
        evidence_id=f"p1a.segment_eligibility.{session_id}.{phase}",
        session_id=session_id, segment_name=phase,
        valid_for_descriptive_analysis=True,
        valid_for_channel_alignment=True,
        valid_for_timebase=True,
        valid_for_imu_sign=True,
        valid_for_ground_truth=False,
        valid_for_translation_scale=False,
        valid_for_yaw_gain=False,
        invalid_reason="stationary window: no motion to use as scale/yaw-gain ground truth",
        baseline_scope="STATIONARY_WINDOW",
    )
