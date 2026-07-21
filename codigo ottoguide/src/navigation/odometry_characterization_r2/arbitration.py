"""Channel arbitration matrix (section 29). Never selects an authoritative
channel; PREFERRED_ANALYSIS_CHANNEL is only ever set when the aggregated
quantitative evidence clearly supports it, and remains a distinct concept
from AUTHORITATIVE_SOURCE_CHANNEL (which stays null by construction)."""
from .models import CHARACTERIZATION_SCHEMA_VERSION, ChannelArbitrationCriterion, ChannelArbitrationMatrix

PRIMARY = "rt/odommodestate"
SECONDARY = "rt/lf/odommodestate"


def _criterion(name, primary_metrics, secondary_metrics, better_is_higher, key, notes) -> ChannelArbitrationCriterion:
    p = getattr(primary_metrics, key, None) if primary_metrics else None
    s = getattr(secondary_metrics, key, None) if secondary_metrics else None
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
        notes=f"{notes} (primary={p!r}, secondary={s!r})",
    )


def build_arbitration_matrix(*, primary_quality, secondary_quality,
                              imu_agreement_count: int, reset_behavior_status: str,
                              provenance_quality_status: str) -> ChannelArbitrationMatrix:
    criteria = [
        _criterion("data_completeness", primary_quality, secondary_quality, True, "sample_count",
                   "higher raw sample count is an observation only, never authority per section 10"),
        _criterion("sample_rate", primary_quality, secondary_quality, True, "mean_rate_hz",
                   "effective mean rate"),
        _criterion("jitter", primary_quality, secondary_quality, False, "jitter_mad_ms",
                   "lower robust jitter (MAD of intervals)"),
        _criterion("gaps", primary_quality, secondary_quality, False, "gap_count",
                   "fewer session-derived gap events"),
        _criterion("dropouts", primary_quality, secondary_quality, False, "dropout_count",
                   "fewer estimated dropped samples"),
    ]
    criteria.append(ChannelArbitrationCriterion(
        criterion_name="imu_consistency",
        primary_status="PARTIAL" if imu_agreement_count > 0 else "NOT_APPLICABLE",
        secondary_status="NOT_APPLICABLE",
        notes="IMU cross-check (section 27) is only computed against the primary channel's "
              "yaw_speed in P1; LF-channel IMU cross-check was not attempted.",
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

    pass_count_primary = sum(1 for c in criteria if c.primary_status == "PASS")
    pass_count_secondary = sum(1 for c in criteria if c.secondary_status == "PASS")
    preferred = None
    if pass_count_primary > pass_count_secondary and pass_count_primary >= 2:
        preferred = PRIMARY
    elif pass_count_secondary > pass_count_primary and pass_count_secondary >= 2:
        preferred = SECONDARY

    return ChannelArbitrationMatrix(
        schema_version=CHARACTERIZATION_SCHEMA_VERSION,
        evidence_id="p1.channel_arbitration_matrix",
        criteria=tuple(criteria),
        preferred_analysis_channel=preferred,
        authoritative_source_channel=None,
        status="PARTIAL",
        limitations=(
            "AUTHORITATIVE_SOURCE_CHANNEL remains null by design -- P1 characterizes, it "
            "never selects a channel for publication.",
            f"PREFERRED_ANALYSIS_CHANNEL={preferred!r} is only a data-driven candidate for "
            "which stream to prefer analyzing further in P2, distinct from and never "
            "conflated with an authoritative-source decision.",
        ),
    )
