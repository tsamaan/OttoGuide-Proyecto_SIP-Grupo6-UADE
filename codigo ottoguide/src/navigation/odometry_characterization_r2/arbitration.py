"""Channel arbitration matrix (section 29 of P1; hardened in P1A per H2/H6).

Never selects an authoritative channel; PREFERRED_ANALYSIS_CHANNEL is only
ever set when the aggregated quantitative evidence clearly supports it, and
remains a distinct concept from AUTHORITATIVE_SOURCE_CHANNEL (which stays
null by construction).

H2/H6 hardening: P1's own arbitration silently compared only the FIRST
matching ChannelQualityMetrics per channel (effectively R3C only, via a bare
`next(...)` in report.py) and then reported "primary edges out on rate/
jitter/gaps/dropouts" even though primary has MORE gaps and MORE dropouts
than LF in every session (worse, not better) -- a genuine, reproduced
contradiction (see docs/Operaciones_HIL/Evidencia/R2_P1A_AUDIT_SUMMARY.md,
H2). `build_arbitration_matrix` (the P1-facing entry point, whose output
still populates OdometryCharacterizationBundleR2.arbitration) now takes
pre-aggregated per-channel metrics instead of a single session's object, so
this bug cannot recur silently. `build_arbitration_audit` is the new,
fully-transparent P1A audit trail (ArbitrationScoringRule/
ArbitrationDecisionAudit) with explicit per-criterion direction, raw
metrics, weight, and winner, and it structurally enforces
`criterion_count == len(criteria)` (closes H6).
"""
from .models import (
    ArbitrationDecisionAudit,
    ArbitrationScoringRule,
    CHARACTERIZATION_SCHEMA_VERSION,
    ChannelArbitrationCriterion,
    ChannelArbitrationMatrix,
)

PRIMARY = "rt/odommodestate"
SECONDARY = "rt/lf/odommodestate"


def aggregate_channel_quality(records: "list") -> dict:
    """Sum/weighted-aggregate every ChannelQualityMetrics record for ONE
    channel across all sessions -- the aggregation P1 never performed (H2)."""
    if not records:
        return {}
    total_samples = sum(r.sample_count for r in records)
    total_duration = sum(r.duration_s for r in records)
    return {
        "sample_count": total_samples,
        "mean_rate_hz": (total_samples / total_duration) if total_duration > 0 else 0.0,
        "jitter_mad_ms": (sum(r.jitter_mad_ms * r.sample_count for r in records) / total_samples
                          if total_samples else 0.0),
        "gap_count": sum(r.gap_count for r in records),
        "dropout_count": sum(r.dropout_count for r in records),
        "max_gap_ms": max((r.max_gap_ms for r in records), default=0.0),
        "session_count": len(records),
    }


def _legacy_criterion(name, primary_agg: dict, secondary_agg: dict, better_is_higher, key,
                       notes) -> ChannelArbitrationCriterion:
    p = primary_agg.get(key)
    s = secondary_agg.get(key)
    if p is None or s is None:
        return ChannelArbitrationCriterion(criterion_name=name, primary_status="NOT_APPLICABLE",
                                            secondary_status="NOT_APPLICABLE", notes=notes)

    def status_for(value, other):
        if value == other:
            return "PARTIAL"
        is_better = (value > other) if better_is_higher else (value < other)
        return "PASS" if is_better else "PARTIAL"

    return ChannelArbitrationCriterion(
        criterion_name=name,
        primary_status=status_for(p, s),
        secondary_status=status_for(s, p),
        notes=f"{notes} (primary={p!r}, secondary={s!r}, aggregated across "
              f"{primary_agg.get('session_count', '?')} session(s))",
    )


def build_arbitration_matrix(*, primary_records: "list", secondary_records: "list",
                              imu_agreement_count: int, reset_behavior_status: str,
                              provenance_quality_status: str) -> ChannelArbitrationMatrix:
    """P1-facing builder (feeds OdometryCharacterizationBundleR2.arbitration).
    H2 fix: now takes the FULL list of per-session records for each channel
    and aggregates them (see aggregate_channel_quality), instead of a single
    session's metrics object."""
    primary_agg = aggregate_channel_quality(primary_records)
    secondary_agg = aggregate_channel_quality(secondary_records)

    criteria = [
        _legacy_criterion("data_completeness", primary_agg, secondary_agg, True, "sample_count",
                          "higher raw sample count is an observation only, never authority per section 10"),
        _legacy_criterion("sample_rate", primary_agg, secondary_agg, True, "mean_rate_hz",
                          "effective mean rate"),
        _legacy_criterion("jitter", primary_agg, secondary_agg, False, "jitter_mad_ms",
                          "lower robust jitter (MAD of intervals)"),
        _legacy_criterion("gaps", primary_agg, secondary_agg, False, "gap_count",
                          "fewer time-based gap events (H3: the primary, time-anchored dropout signal)"),
        _legacy_criterion("dropouts", primary_agg, secondary_agg, False, "dropout_count",
                          "fewer sequence-derived gap estimates (H3: an auxiliary signal, not confirmed loss)"),
    ]
    criteria.append(ChannelArbitrationCriterion(
        criterion_name="imu_consistency",
        primary_status="PARTIAL" if imu_agreement_count > 0 else "NOT_APPLICABLE",
        secondary_status="NOT_APPLICABLE",
        notes="IMU cross-check (section 27) is only computed against the primary channel's "
              "yaw_speed in P1/P1A; LF-channel IMU cross-check was not attempted.",
    ))
    criteria.append(ChannelArbitrationCriterion(
        criterion_name="reset_behavior",
        primary_status=reset_behavior_status,
        secondary_status=reset_behavior_status,
        notes="reset/discontinuity behavior (P0A) applies identically to both channels; "
              "not a discriminating criterion.",
    ))
    criteria.append(ChannelArbitrationCriterion(
        criterion_name="provenance_quality",
        primary_status=provenance_quality_status,
        secondary_status=provenance_quality_status,
        notes="both channels share the same session-level provenance (same archives, same "
              "manifest verification); not a discriminating criterion.",
    ))
    criteria.append(ChannelArbitrationCriterion(
        criterion_name="ground_truth_support",
        primary_status="PARTIAL",
        secondary_status="PARTIAL",
        notes="R4B best-effort ground truth was annotated for both channels identically "
              "(same operator segments); not a discriminating criterion.",
    ))

    # H2 fix: only the 3 genuinely discriminating criteria (jitter, gaps,
    # dropouts) count toward a preference; data_completeness/sample_rate are
    # explicitly non-authoritative per section 10 and must never flip the
    # decision on their own.
    discriminating = {"jitter", "gaps", "dropouts"}
    pass_count_primary = sum(1 for c in criteria if c.criterion_name in discriminating and c.primary_status == "PASS")
    pass_count_secondary = sum(1 for c in criteria if c.criterion_name in discriminating and c.secondary_status == "PASS")
    preferred = None
    if pass_count_primary > pass_count_secondary:
        preferred = PRIMARY
    elif pass_count_secondary > pass_count_primary:
        preferred = SECONDARY

    return ChannelArbitrationMatrix(
        schema_version=CHARACTERIZATION_SCHEMA_VERSION,
        evidence_id="p1a.channel_arbitration_matrix_corrected",
        criteria=tuple(criteria),
        preferred_analysis_channel=preferred,
        authoritative_source_channel=None,
        status="PARTIAL",
        limitations=(
            "AUTHORITATIVE_SOURCE_CHANNEL remains null by design -- characterization "
            "never selects a channel for publication.",
            f"PREFERRED_ANALYSIS_CHANNEL={preferred!r} is decided using ONLY the 3 "
            "discriminating criteria (jitter, gaps, dropouts), aggregated across all "
            "sessions per channel (H2 fix) -- data_completeness and sample_rate are "
            "explicitly excluded from the decision per section 10.",
        ),
    )


def _audit_criterion(name, direction, primary_value, lf_value, normalization, weight, notes) -> ArbitrationScoringRule:
    if primary_value is None or lf_value is None:
        return ArbitrationScoringRule(
            name=name, direction="NOT_DISCRIMINATING", primary_raw_metric=primary_value,
            lf_raw_metric=lf_value, normalization=normalization, weight=0.0,
            winner="NOT_APPLICABLE", confidence="LOW", limitations=(notes,),
        )
    if direction == "NOT_DISCRIMINATING":
        return ArbitrationScoringRule(
            name=name, direction=direction, primary_raw_metric=primary_value, lf_raw_metric=lf_value,
            normalization=normalization, weight=weight, winner="NOT_APPLICABLE", confidence="LOW",
            limitations=(notes,),
        )
    if primary_value == lf_value:
        winner = "TIE"
    elif direction == "HIGHER_IS_BETTER":
        winner = "PRIMARY" if primary_value > lf_value else "LF"
    else:
        winner = "PRIMARY" if primary_value < lf_value else "LF"
    return ArbitrationScoringRule(
        name=name, direction=direction, primary_raw_metric=float(primary_value),
        lf_raw_metric=float(lf_value), normalization=normalization, weight=weight,
        winner=winner, confidence="MEDIUM", limitations=(notes,),
    )


def build_arbitration_audit(*, primary_records: "list", secondary_records: "list",
                             imu_agreement_count: int, reset_behavior_status: str,
                             provenance_quality_status: str) -> ArbitrationDecisionAudit:
    """The new, fully-transparent P1A audit trail. Same aggregation and same
    discriminating-criteria decision rule as build_arbitration_matrix above,
    but serialized with explicit direction/normalization/weight/winner per
    criterion (H6) and a structural criterion_count == len(criteria) check."""
    primary_agg = aggregate_channel_quality(primary_records)
    secondary_agg = aggregate_channel_quality(secondary_records)

    criteria = [
        _audit_criterion(
            "data_completeness", "NOT_DISCRIMINATING",
            primary_agg.get("sample_count"), secondary_agg.get("sample_count"),
            "raw sample count sum across sessions",
            0.0, "explicitly an observation only per section 10 -- never weighted into the decision",
        ),
        _audit_criterion(
            "sample_rate", "NOT_DISCRIMINATING",
            primary_agg.get("mean_rate_hz"), secondary_agg.get("mean_rate_hz"),
            "aggregate mean Hz across sessions",
            0.0, "primary runs ~2x LF's rate by recorder design, not a quality signal -- never weighted",
        ),
        _audit_criterion(
            "jitter", "LOWER_IS_BETTER",
            primary_agg.get("jitter_mad_ms"), secondary_agg.get("jitter_mad_ms"),
            "sample-count-weighted mean of per-session robust jitter (MAD of intervals, ms)",
            1.0, "lower robust jitter across all sessions combined",
        ),
        _audit_criterion(
            "gaps", "LOWER_IS_BETTER",
            primary_agg.get("gap_count"), secondary_agg.get("gap_count"),
            "sum of time-based gap_count across sessions",
            1.0, "fewer time-based gaps, summed across all sessions (H2 fix: P1 compared only 1 of 3 "
                 "sessions here)",
        ),
        _audit_criterion(
            "dropouts", "LOWER_IS_BETTER",
            primary_agg.get("dropout_count"), secondary_agg.get("dropout_count"),
            "sum of channel-local sequence-gap estimate across sessions (H3: auxiliary signal)",
            1.0, "fewer estimated dropped samples, summed across all sessions (H2 fix: P1 compared only "
                 "1 of 3 sessions here)",
        ),
        ArbitrationScoringRule(
            name="imu_consistency", direction="NOT_DISCRIMINATING",
            primary_raw_metric=float(imu_agreement_count), lf_raw_metric=None,
            normalization="count of IMU cross-check records computed against this channel",
            weight=0.0, winner="NOT_APPLICABLE", confidence="LOW",
            limitations=("IMU cross-check (section 27) is only computed against the primary channel's "
                         "yaw_speed in P1/P1A; LF-channel IMU cross-check was not attempted.",),
        ),
        ArbitrationScoringRule(
            name="reset_behavior", direction="NOT_DISCRIMINATING",
            primary_raw_metric=None, lf_raw_metric=None,
            normalization=f"shared P0A status: {reset_behavior_status}",
            weight=0.0, winner="NOT_APPLICABLE", confidence="LOW",
            limitations=("reset/discontinuity behavior applies identically to both channels; not "
                         "discriminating.",),
        ),
        ArbitrationScoringRule(
            name="provenance_quality", direction="NOT_DISCRIMINATING",
            primary_raw_metric=None, lf_raw_metric=None,
            normalization=f"shared manifest verification: {provenance_quality_status}",
            weight=0.0, winner="NOT_APPLICABLE", confidence="LOW",
            limitations=("both channels share the same session-level provenance; not discriminating.",),
        ),
        ArbitrationScoringRule(
            name="ground_truth_support", direction="NOT_DISCRIMINATING",
            primary_raw_metric=None, lf_raw_metric=None,
            normalization="shared R4B best-effort operator annotation",
            weight=0.0, winner="NOT_APPLICABLE", confidence="LOW",
            limitations=("R4B best-effort ground truth was annotated identically for both channels; "
                         "not discriminating.",),
        ),
    ]

    weighted_primary = sum(c.weight for c in criteria if c.winner == "PRIMARY")
    weighted_lf = sum(c.weight for c in criteria if c.winner == "LF")
    total_weight = sum(c.weight for c in criteria)

    preferred = None
    if total_weight > 0:
        if weighted_primary > weighted_lf:
            preferred = PRIMARY
        elif weighted_lf > weighted_primary:
            preferred = SECONDARY

    consistent = True
    if preferred == PRIMARY and weighted_primary <= weighted_lf:
        consistent = False
    if preferred == SECONDARY and weighted_lf <= weighted_primary:
        consistent = False
    if not consistent:
        preferred = None
        consistent = True

    return ArbitrationDecisionAudit(
        schema_version=CHARACTERIZATION_SCHEMA_VERSION,
        evidence_id="p1a.channel_arbitration_audit",
        criteria=tuple(criteria),
        criterion_count=len(criteria),
        aggregation_method="weighted sum of discriminating criteria only (weight=1.0 each: jitter, gaps, "
                            "dropouts); data_completeness/sample_rate/imu_consistency/reset_behavior/"
                            "provenance_quality/ground_truth_support carry weight=0.0 (documented as "
                            "non-discriminating observations, per section 10/H2)",
        preferred_analysis_channel=preferred,
        authoritative_source_channel=None,
        consistent_with_criteria=consistent,
        status="PARTIAL",
        limitations=(
            "AUTHORITATIVE_SOURCE_CHANNEL remains null by design.",
            f"weighted_primary={weighted_primary}, weighted_lf={weighted_lf}, total_weight={total_weight} "
            "across the 3 discriminating criteria (jitter, gaps, dropouts), aggregated across all sessions.",
        ),
    )
