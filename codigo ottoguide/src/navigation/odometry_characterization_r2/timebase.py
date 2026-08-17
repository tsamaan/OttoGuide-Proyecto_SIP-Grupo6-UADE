"""Per-session timebase characterization (section 28)."""
from . import statistics as p1stats
from .models import CHARACTERIZATION_SCHEMA_VERSION, TimebaseCharacterization

ORDERING_CLOCK_POLICY_CANDIDATE = "RECEIPT_MONOTONIC_PER_SESSION"
ROS_HEADER_STAMP_POLICY = "UNRESOLVED"


def _ordering_status(samples) -> "tuple[str, int]":
    receipts = [s.receipt_monotonic_ns for s in samples]
    gap_count = 0
    inversions = 0
    if len(receipts) > 1:
        intervals = [b - a for a, b in zip(receipts, receipts[1:])]
        inversions = sum(1 for i in intervals if i < 0)
        positive = [i for i in intervals if i > 0]
        if positive:
            threshold_s, _method = p1stats.robust_gap_threshold([i / 1e9 for i in positive])
            gap_count = sum(1 for i in positive if (i / 1e9) > threshold_s)
    status = "MONOTONIC_NON_DECREASING" if inversions == 0 else "INVERSIONS_OBSERVED"
    return status, gap_count


def compute_timebase(*, session_id: str, samples: tuple, message_stamp_status: str,
                      handshake_rtt_s: "float | None" = None,
                      utc_midpoint_estimate_s: "float | None" = None,
                      offset_uncertainty_s: "float | None" = None,
                      extra_limitations: tuple = ()) -> "TimebaseCharacterization | None":
    if not samples:
        return None
    ordering_status, gap_count = _ordering_status(samples)
    receipt_wall_utc_available = any(s.receipt_utc for s in samples)

    if handshake_rtt_s is not None:
        status = "PARTIAL"
        cross_channel_status = "PARTIAL_BEST_EFFORT_HANDSHAKE"
    else:
        status = "UNRESOLVED"
        cross_channel_status = "UNRESOLVED_NO_HANDSHAKE"

    return TimebaseCharacterization(
        schema_version=CHARACTERIZATION_SCHEMA_VERSION,
        evidence_id=f"p1.timebase.{session_id}",
        session_id=session_id,
        message_stamp_status=message_stamp_status,
        receipt_monotonic_ordering_status=ordering_status,
        receipt_wall_utc_available=receipt_wall_utc_available,
        handshake_rtt_s=handshake_rtt_s,
        utc_midpoint_estimate_s=utc_midpoint_estimate_s,
        offset_uncertainty_s=offset_uncertainty_s,
        gap_count=gap_count,
        cross_channel_comparability_status=cross_channel_status,
        ordering_clock_policy_candidate=ORDERING_CLOCK_POLICY_CANDIDATE,
        ros_header_stamp_policy=ROS_HEADER_STAMP_POLICY,
        status=status,
        limitations=(
            "receipt_monotonic_ns establishes intra-session ordering only; it is "
            "never treated as an authoritative ROS-time mapping (ROS_HEADER_STAMP_POLICY "
            "remains UNRESOLVED).",
        ) + tuple(extra_limitations),
    )
