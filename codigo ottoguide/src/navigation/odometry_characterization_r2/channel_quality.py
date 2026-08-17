"""Per session/channel sampling-quality metrics (section 22)."""
from src.navigation.odometry_evidence_r2.validation import EvidenceValidationError

from . import statistics as p1stats
from .models import CHARACTERIZATION_SCHEMA_VERSION, ChannelQualityMetrics


def compute_channel_quality(*, session_id: str, channel: str, samples: tuple,
                             stationary_sample_count: int, dynamic_sample_count: int,
                             parse_stats: dict) -> ChannelQualityMetrics:
    if not samples:
        raise EvidenceValidationError("cannot compute channel quality over 0 samples")
    if any(s.session_id != session_id for s in samples):
        raise EvidenceValidationError("all samples must share the same session_id (no cross-session mixing)")
    if any(s.channel != channel for s in samples):
        raise EvidenceValidationError("all samples must share the same channel (no cross-channel mixing)")
    boot_ids = {s.boot_id for s in samples}
    if len(boot_ids) > 1:
        raise EvidenceValidationError(f"samples span more than one boot_id (no cross-boot mixing): {boot_ids!r}")

    receipts_ns = [s.receipt_monotonic_ns for s in samples]
    intervals_s = [
        (b - a) / 1e9 for a, b in zip(receipts_ns, receipts_ns[1:]) if b > a
    ]
    total = len(samples)
    if not intervals_s:
        # Degenerate single-sample or all-simultaneous-receipt session: report
        # zeroed rate/jitter rather than dividing by zero.
        duration_s = 0.0
        mean_rate = 0.0
        median_rate = 0.0
        period_p50 = period_p95 = period_p99 = jitter_mad = 0.0
        gap_threshold_ms = 0.0
        gap_threshold_method = p1stats.GAP_THRESHOLD_METHOD
        max_gap_ms = 0.0
        gap_count = 0
    else:
        duration_s = (receipts_ns[-1] - receipts_ns[0]) / 1e9
        mean_rate = (total - 1) / duration_s if duration_s > 0 else 0.0
        median_interval = p1stats.median(intervals_s)
        median_rate = 1.0 / median_interval if median_interval > 0 else 0.0
        period_p50 = p1stats.percentile(intervals_s, 0.50) * 1000.0
        period_p95 = p1stats.percentile(intervals_s, 0.95) * 1000.0
        period_p99 = p1stats.percentile(intervals_s, 0.99) * 1000.0
        jitter_mad = p1stats.mad(intervals_s) * 1000.0
        threshold_s, gap_threshold_method = p1stats.robust_gap_threshold(intervals_s)
        gap_threshold_ms = threshold_s * 1000.0
        max_gap_ms = max(intervals_s) * 1000.0
        gap_count = sum(1 for i in intervals_s if i > threshold_s)

    sequences_sorted = sorted(s.sequence for s in samples)
    dropout_count = 0
    missing_sequence_spans = 0
    if len(sequences_sorted) >= 3:
        try:
            step = p1stats.modal_positive_step(sequences_sorted)
        except EvidenceValidationError:
            step = None
        if step:
            deltas = [b - a for a, b in zip(sequences_sorted, sequences_sorted[1:])]
            # A span is "missing" when its delta is a clean multiple (>=2x)
            # of the session's own observed modal step -- i.e. at least one
            # whole expected sample-worth of this channel's own cadence is
            # absent, not merely ordinary jitter around the modal step.
            missing_sequence_spans = sum(1 for d in deltas if d >= 2 * step)
            dropout_count = sum((d // step) - 1 for d in deltas if d >= 2 * step)

    total_span = stationary_sample_count + dynamic_sample_count
    stationary_coverage = (stationary_sample_count / total) if total else 0.0
    dynamic_coverage = (dynamic_sample_count / total) if total else 0.0
    stationary_coverage = min(stationary_coverage, 1.0)
    dynamic_coverage = min(dynamic_coverage, 1.0)

    return ChannelQualityMetrics(
        schema_version=CHARACTERIZATION_SCHEMA_VERSION,
        evidence_id=f"p1.channel_quality.{session_id}.{channel.replace('/', '_')}",
        session_id=session_id,
        channel=channel,
        sample_count=total,
        duration_s=duration_s,
        first_receipt_monotonic_ns=receipts_ns[0],
        last_receipt_monotonic_ns=receipts_ns[-1],
        mean_rate_hz=mean_rate,
        median_rate_hz=median_rate,
        period_p50_ms=period_p50,
        period_p95_ms=period_p95,
        period_p99_ms=period_p99,
        jitter_mad_ms=jitter_mad,
        gap_threshold_ms=gap_threshold_ms,
        gap_threshold_method=gap_threshold_method,
        max_gap_ms=max_gap_ms,
        gap_count=gap_count,
        dropout_count=dropout_count,
        duplicate_sequences=parse_stats.get("duplicate_sequences", 0),
        missing_sequence_spans=missing_sequence_spans,
        monotonic_inversions=parse_stats.get("monotonic_inversions", 0),
        non_finite_count=0,
        stationary_coverage=stationary_coverage,
        dynamic_coverage=dynamic_coverage,
        status="VERIFIED",
        limitations=(
            "gap/dropout thresholds are derived per-session from the channel's own "
            f"observed interval distribution ({gap_threshold_method}), never a fixed "
            "hidden constant.",
            "sequence is a session-wide counter shared across all recorder topics, "
            "not a per-channel counter starting at 1 -- 'missing_sequence_spans' is "
            "computed relative to this channel's own observed modal step between "
            "consecutive samples, not relative to a per-channel unit increment.",
        ),
    )
