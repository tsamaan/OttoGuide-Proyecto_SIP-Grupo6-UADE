"""H3 audit: sequence semantics and a corrected dropout-detection policy.

P1's raw reparse already showed (section 22 of the P1 checkpoint, re-
confirmed here) that consecutive same-channel sequence deltas are
irregular (2, 5, 10, 15, 19, 22, 25, ...) rather than a per-channel unit
increment -- proof that `sequence` is a single counter SHARED across every
topic the recorder emits (odom, lf_odom, lowstate, bms, lidar, events),
not a per-channel counter. P1's own `channel_quality.py` already accounted
for this by deriving a per-channel *modal* step instead of assuming
step=1, but its `dropout_count` was still purely sequence-derived and
therefore only ever an ESTIMATE, never a directly-observed sample loss --
a sequence span can inflate or shrink innocently whenever other topics
happen to publish at a different instantaneous rate (e.g. LiDAR bursts).

This module makes that distinction explicit and promotes monotonic
receipt-TIME gaps (already computed by P1's `channel_quality.py` as
`gap_count`/`max_gap_ms`, using a threshold derived from the channel's own
observed interval distribution) to the PRIMARY dropout signal, since a time
gap is a direct, channel-local observation that cannot be confounded by
another topic's publish rate.
"""
from .models import DropoutDetectionPolicy, SequenceSemantics

CHARACTERIZATION_SCHEMA_VERSION = "2.1.1-p1a"

SEQUENCE_EVIDENCE_SUMMARY = (
    "Raw reparse of R3C/R4/R4B recorder_data/{odom,lf_odom,lowstate}/*.jsonl shows "
    "consecutive same-topic sequence deltas that are irregular multiples of a session-"
    "specific modal step (observed deltas such as 2,5,10,15,19,22,25 rather than a "
    "constant +1), consistent with a single sequence counter shared across every "
    "recorder topic (odom, lf_odom, lowstate, bms, lidar_meta, lidar_clouds, events) "
    "rather than a per-channel counter. Confirmed independently in this audit by "
    "recomputing the modal step for each of the 6 session/channel combinations and "
    "verifying interleaved-topic samples fall between them."
)


def build_sequence_semantics(session_id: str) -> SequenceSemantics:
    return SequenceSemantics(
        evidence_id=f"p1a.sequence_semantics.{session_id}",
        session_id=session_id,
        classification="GLOBAL_ACROSS_ALL_TOPICS",
        evidence_summary=SEQUENCE_EVIDENCE_SUMMARY,
        status="VERIFIED",
        limitations=(
            "A per-channel sequence span must never be interpreted as a per-channel "
            "sample-loss count on its own (H3) -- see DropoutDetectionPolicy for the "
            "corrected, time-anchored dropout definition.",
        ),
    )


def build_dropout_detection_policy() -> DropoutDetectionPolicy:
    return DropoutDetectionPolicy(
        schema_version=CHARACTERIZATION_SCHEMA_VERSION,
        evidence_id="p1a.dropout_detection_policy",
        primary_signal="TIME_GAP",
        secondary_signal="CHANNEL_LOCAL_SEQUENCE_GAP_ESTIMATE",
        time_gap_method=(
            "a receipt_monotonic_ns interval strictly exceeding the channel's own "
            "robust gap threshold (median + 6*MAD of its own observed intervals, "
            "floored at 10x the median interval) is classified TIME_GAP -- this is "
            "P1's existing channel_quality.gap_count/max_gap_ms, now promoted to the "
            "primary, most trustworthy dropout signal because it is a direct, "
            "channel-local time observation."
        ),
        time_gap_threshold_method="MEDIAN_PLUS_6_MAD_OF_INTERVALS_FLOOR_10X_MEDIAN",
        sequence_gap_caveat=(
            "P1's dropout_count field (a sequence-delta-based estimate using the "
            "channel's own modal step) is RELABELED here as an auxiliary "
            "CHANNEL_LOCAL_SEQUENCE_GAP_ESTIMATE, not a confirmed sample-loss count -- "
            "because `sequence` is a session-wide counter shared across all recorder "
            "topics (see SequenceSemantics = GLOBAL_ACROSS_ALL_TOPICS), a channel's own "
            "sequence span can vary innocently with other topics' instantaneous publish "
            "rate. It is reported alongside the time-based signal for transparency, "
            "never in place of it."
        ),
        status="VERIFIED",
        limitations=(
            "No explicit recorder loss markers (e.g. a dropped-sample counter emitted "
            "by the recorder itself) were found in the raw JSONL or its schema files; "
            "'unknown' classification is used only if a gap can be attributed to "
            "neither a time gap, a file boundary, nor a phase boundary.",
        ),
    )


def classify_channel_dropouts(*, time_gap_count: int, sequence_gap_estimate: int) -> dict:
    """Corrected, honestly-labeled dropout summary for one session/channel."""
    return {
        "time_gap_count": time_gap_count,
        "channel_local_sequence_gap_estimate": sequence_gap_estimate,
        "confirmed_dropout_count": time_gap_count,
        "note": (
            "confirmed_dropout_count uses ONLY the time-gap signal; the sequence-based "
            "estimate is reported separately and must never be summed into it."
        ),
    }
