"""Typed, immutable, fail-closed dataclasses for ODOM/TF R2-P1 channel/time/
motion characterization.

Every dataclass is frozen and kw_only. ``__post_init__`` validates fail-closed
using the shared, already-tested P0A validation primitives -- it never
silently coerces a malformed value (NaN/Infinity, bool-as-number, absolute or
traversal path, invalid sha256, start>end, mixed sessions/boots, a VERIFIED
claim citing only PARTIAL evidence, a nominal value declared calibrated).
"""
from dataclasses import dataclass, field

from src.navigation.odometry_evidence_r2.validation import (
    EvidenceValidationError,
    is_bounded_int,
    is_finite_number,
    is_non_empty_str,
    is_relative_portable_path,
    is_sha256_hex,
    validate_sha256_tuple,
    validate_str_tuple,
)

CHARACTERIZATION_SCHEMA_VERSION = "2.1.1-p1a"

STATUS_VALUES = frozenset({
    "VERIFIED", "SUPPORTED_INFERENCE", "PARTIAL", "PARTIAL_QUANTIFIED",
    "UNRESOLVED", "NOT_AVAILABLE", "NOT_EXECUTED", "INVALID", "BEST_EFFORT_ONLY",
})


def _req(condition: bool, message: str) -> None:
    if not condition:
        raise EvidenceValidationError(message)


def _finite_tuple(value, length: int, name: str) -> None:
    _req(type(value) is tuple and len(value) == length, f"{name} must be a {length}-tuple")
    for component in value:
        _req(is_finite_number(component), f"{name} contains a non-finite/bool component: {component!r}")


def _finite_or_none(value, name: str) -> None:
    if value is None:
        return
    _req(is_finite_number(value), f"{name} must be finite or None, got {value!r}")


def _status(value, name: str = "status") -> None:
    _req(type(value) is str and value in STATUS_VALUES, f"invalid {name}: {value!r}")


def _rel_source_paths(value, name: str = "source_files") -> None:
    _req(type(value) is tuple, f"{name} must be a tuple")
    for p in value:
        _req(is_relative_portable_path(p), f"{name} entry is not a portable relative path: {p!r}")


@dataclass(frozen=True, kw_only=True)
class NormalizedOdomSample:
    schema_version: str
    session_id: str
    boot_id: "str | None"
    channel: str
    sequence: int
    receipt_monotonic_ns: int
    receipt_utc: "str | None"
    phase: str
    position: tuple
    velocity: tuple
    yaw_speed: float
    mode: int
    source_file: str
    source_sha256: str

    def __post_init__(self):
        _req(is_non_empty_str(self.session_id), "session_id must be non-empty str")
        _req(is_non_empty_str(self.channel), "channel must be non-empty str")
        _req(is_bounded_int(self.sequence, minimum=0), "sequence must be a non-negative plain int")
        _req(is_bounded_int(self.receipt_monotonic_ns, minimum=0),
             "receipt_monotonic_ns must be a non-negative plain int")
        _req(is_non_empty_str(self.phase), "phase must be non-empty str")
        _finite_tuple(self.position, 3, "position")
        _finite_tuple(self.velocity, 3, "velocity")
        _req(is_finite_number(self.yaw_speed), "yaw_speed must be finite")
        _req(is_bounded_int(self.mode, minimum=0), "mode must be a non-negative plain int")
        _req(is_relative_portable_path(self.source_file), f"source_file not portable-relative: {self.source_file!r}")
        _req(is_sha256_hex(self.source_sha256), "source_sha256 invalid")


@dataclass(frozen=True, kw_only=True)
class NormalizedLowStateSample:
    """Not one of the section-21 named models, but required to carry
    LowState IMU samples (quaternion/gyroscope/rpy_deg) with the same
    fail-closed discipline as NormalizedOdomSample -- imu.py needs typed,
    validated per-sample IMU records to build ImuAgreementMetrics."""
    schema_version: str
    session_id: str
    sequence: int
    receipt_monotonic_ns: int
    phase: str
    gyroscope: tuple
    rpy_deg: tuple
    source_file: str
    source_sha256: str

    def __post_init__(self):
        _req(is_non_empty_str(self.session_id), "session_id must be non-empty str")
        _req(is_bounded_int(self.sequence, minimum=0), "sequence must be a non-negative plain int")
        _req(is_bounded_int(self.receipt_monotonic_ns, minimum=0), "receipt_monotonic_ns must be non-negative")
        _finite_tuple(self.gyroscope, 3, "gyroscope")
        _finite_tuple(self.rpy_deg, 3, "rpy_deg")
        _req(is_relative_portable_path(self.source_file), "source_file not portable-relative")
        _req(is_sha256_hex(self.source_sha256), "source_sha256 invalid")


@dataclass(frozen=True, kw_only=True)
class SampleIntervalStatistics:
    schema_version: str
    session_id: str
    channel: str
    sample_count: int
    duration_s: float
    mean_interval_s: float
    median_interval_s: float
    period_p50_s: float
    period_p95_s: float
    period_p99_s: float
    jitter_mad_s: float
    method: str
    limitations: tuple

    def __post_init__(self):
        _req(self.sample_count >= 1, "sample_count must be >= 1")
        for name in ("duration_s", "mean_interval_s", "median_interval_s", "period_p50_s",
                     "period_p95_s", "period_p99_s", "jitter_mad_s"):
            value = getattr(self, name)
            _req(is_finite_number(value) and value >= 0, f"{name} must be a finite, non-negative number")
        validate_str_tuple(self.limitations)


@dataclass(frozen=True, kw_only=True)
class GapEvent:
    session_id: str
    channel: str
    start_receipt_ns: int
    end_receipt_ns: int
    gap_s: float
    before_sequence: int
    after_sequence: int

    def __post_init__(self):
        _req(self.end_receipt_ns > self.start_receipt_ns, "gap end must be after start (start > end rejected)")
        _req(is_finite_number(self.gap_s) and self.gap_s > 0, "gap_s must be finite and positive")


@dataclass(frozen=True, kw_only=True)
class DropoutEvent:
    session_id: str
    channel: str
    expected_step: int
    observed_step: int
    start_sequence: int
    after_sequence: int
    missing_count_estimate: int

    def __post_init__(self):
        _req(self.after_sequence > self.start_sequence, "dropout end must be after start (start > end rejected)")
        _req(is_bounded_int(self.missing_count_estimate, minimum=0), "missing_count_estimate must be >= 0")


@dataclass(frozen=True, kw_only=True)
class ChannelQualityMetrics:
    schema_version: str
    evidence_id: str
    session_id: str
    channel: str
    sample_count: int
    duration_s: float
    first_receipt_monotonic_ns: int
    last_receipt_monotonic_ns: int
    mean_rate_hz: float
    median_rate_hz: float
    period_p50_ms: float
    period_p95_ms: float
    period_p99_ms: float
    jitter_mad_ms: float
    gap_threshold_ms: float
    gap_threshold_method: str
    max_gap_ms: float
    gap_count: int
    dropout_count: int
    duplicate_sequences: int
    missing_sequence_spans: int
    monotonic_inversions: int
    non_finite_count: int
    stationary_coverage: float
    dynamic_coverage: float
    status: str
    limitations: tuple

    def __post_init__(self):
        _req(is_non_empty_str(self.evidence_id), "evidence_id required")
        _req(self.sample_count >= 1, "ChannelQualityMetrics requires sample_count >= 1")
        _req(self.last_receipt_monotonic_ns >= self.first_receipt_monotonic_ns,
             "last_receipt_monotonic_ns must be >= first (start > end rejected)")
        for name in ("mean_rate_hz", "median_rate_hz", "period_p50_ms", "period_p95_ms", "period_p99_ms",
                     "jitter_mad_ms", "gap_threshold_ms", "max_gap_ms"):
            _req(is_finite_number(getattr(self, name)), f"{name} must be finite")
        for name in ("gap_count", "dropout_count", "duplicate_sequences", "missing_sequence_spans",
                     "monotonic_inversions", "non_finite_count"):
            _req(is_bounded_int(getattr(self, name), minimum=0), f"{name} must be a non-negative plain int")
        for name in ("stationary_coverage", "dynamic_coverage"):
            value = getattr(self, name)
            _req(is_finite_number(value) and 0.0 <= value <= 1.0, f"{name} must be in [0,1]")
        _status(self.status)
        validate_str_tuple(self.limitations)


@dataclass(frozen=True, kw_only=True)
class AlignedChannelPair:
    session_id: str
    primary_sequence: int
    secondary_sequence: int
    primary_receipt_ns: int
    secondary_receipt_ns: int
    time_offset_s: float

    def __post_init__(self):
        _req(is_finite_number(self.time_offset_s), "time_offset_s must be finite")


@dataclass(frozen=True, kw_only=True)
class ChannelAlignmentMetrics:
    schema_version: str
    evidence_id: str
    session_id: str
    phase: str
    primary_sample_count: int
    secondary_sample_count: int
    paired_sample_count: int
    pairing_coverage: float
    time_offset_median_s: float
    time_offset_p95_s: float
    lag_candidate_ms: "float | None"
    lag_status: str
    position_mae: "float | None"
    position_rmse: "float | None"
    position_p95: "float | None"
    position_max: "float | None"
    yaw_speed_mae_rad_s: "float | None"
    yaw_speed_rmse_rad_s: "float | None"
    yaw_speed_p95_rad_s: "float | None"
    yaw_speed_max_rad_s: "float | None"
    correlation_position: "float | None"
    status: str
    limitations: tuple

    def __post_init__(self):
        _req(0.0 <= self.pairing_coverage <= 1.0, "pairing_coverage must be in [0,1]")
        _req(self.paired_sample_count <= min(self.primary_sample_count, self.secondary_sample_count),
             "paired_sample_count cannot exceed either input sample count (no ambiguous reuse)")
        for name in ("position_mae", "position_rmse", "position_p95", "position_max",
                     "yaw_speed_mae_rad_s", "yaw_speed_rmse_rad_s", "yaw_speed_p95_rad_s",
                     "yaw_speed_max_rad_s", "correlation_position", "lag_candidate_ms"):
            _finite_or_none(getattr(self, name), name)
        _status(self.status)
        validate_str_tuple(self.limitations)


@dataclass(frozen=True, kw_only=True)
class StationaryWindowMetrics:
    schema_version: str
    evidence_id: str
    session_id: str
    channel: str
    phase: str
    sample_count: int
    duration_s: float
    observed_mean: tuple
    median: tuple
    stddev: tuple
    mad: tuple
    p95_deviation: tuple
    linear_drift_slope: tuple
    yaw_speed_bias: float
    yaw_drift_slope: float
    outlier_count: int
    reference_origin_policy: str
    status: str
    limitations: tuple

    def __post_init__(self):
        _req(self.sample_count >= 1, "StationaryWindowMetrics requires sample_count >= 1")
        for name in ("observed_mean", "median", "stddev", "mad", "p95_deviation", "linear_drift_slope"):
            _finite_tuple(getattr(self, name), 3, name)
        _req(is_finite_number(self.yaw_speed_bias), "yaw_speed_bias must be finite")
        _req(is_finite_number(self.yaw_drift_slope), "yaw_drift_slope must be finite")
        _req(is_bounded_int(self.outlier_count, minimum=0), "outlier_count must be >= 0")
        _status(self.status)
        validate_str_tuple(self.limitations)


@dataclass(frozen=True, kw_only=True)
class MotionSegmentMetrics:
    schema_version: str
    evidence_id: str
    session_id: str
    segment_name: str
    channel: str
    valid: bool
    ground_truth_constraint: str
    start_position: tuple
    end_position: tuple
    delta_position: tuple
    planar_displacement: float
    dominant_axis: str
    dominant_axis_projection: float
    cross_axis_displacement: float
    path_length_candidate: "float | None"
    start_yaw_speed: "float | None"
    end_yaw_speed: "float | None"
    integrated_yaw_speed_rad: "float | None"
    duration_s: "float | None"
    mean_velocity: "float | None"
    max_velocity: "float | None"
    sample_count: int
    status: str
    limitations: tuple

    def __post_init__(self):
        _req(type(self.valid) is bool, "valid must be a plain bool")
        _req(self.sample_count >= 1, "MotionSegmentMetrics requires sample_count >= 1 (no metric without sample_count)")
        for name in ("start_position", "end_position", "delta_position"):
            _finite_tuple(getattr(self, name), 3, name)
        _req(is_finite_number(self.planar_displacement) and self.planar_displacement >= 0,
             "planar_displacement must be finite and non-negative")
        _req(is_finite_number(self.dominant_axis_projection), "dominant_axis_projection must be finite")
        _req(is_finite_number(self.cross_axis_displacement) and self.cross_axis_displacement >= 0,
             "cross_axis_displacement must be finite and non-negative")
        for name in ("path_length_candidate", "start_yaw_speed", "end_yaw_speed", "integrated_yaw_speed_rad",
                     "duration_s", "mean_velocity", "max_velocity"):
            _finite_or_none(getattr(self, name), name)
        if not self.valid:
            _req(self.ground_truth_constraint in ("INVALID", "NOT_AVAILABLE"),
                 "an invalid segment must not carry an affirmative ground-truth constraint")
        _status(self.status)
        validate_str_tuple(self.limitations)


@dataclass(frozen=True, kw_only=True)
class ImuAgreementMetrics:
    schema_version: str
    evidence_id: str
    session_id: str
    segment_name: str
    sportmode_yaw_speed_sign: "str | None"
    lowstate_gyro_z_sign: "str | None"
    sign_agreement: "bool | None"
    gyro_units_status: str
    rpy_units_status: str
    wrap_events: int
    sample_coverage: float
    status: str
    limitations: tuple

    def __post_init__(self):
        if self.sign_agreement is not None:
            _req(type(self.sign_agreement) is bool, "sign_agreement must be a plain bool or None")
        _req(is_bounded_int(self.wrap_events, minimum=0), "wrap_events must be >= 0")
        _req(0.0 <= self.sample_coverage <= 1.0, "sample_coverage must be in [0,1]")
        _req(self.status != "VERIFIED", "IMU crosscheck must never be elevated to VERIFIED (max PARTIAL_QUANTIFIED)")
        _status(self.status)
        validate_str_tuple(self.limitations)


@dataclass(frozen=True, kw_only=True)
class TimebaseCharacterization:
    schema_version: str
    evidence_id: str
    session_id: str
    message_stamp_status: str
    receipt_monotonic_ordering_status: str
    receipt_wall_utc_available: bool
    handshake_rtt_s: "float | None"
    utc_midpoint_estimate_s: "float | None"
    offset_uncertainty_s: "float | None"
    gap_count: int
    cross_channel_comparability_status: str
    ordering_clock_policy_candidate: str
    ros_header_stamp_policy: str
    status: str
    limitations: tuple

    def __post_init__(self):
        _req(type(self.receipt_wall_utc_available) is bool, "receipt_wall_utc_available must be a plain bool")
        for name in ("handshake_rtt_s", "utc_midpoint_estimate_s", "offset_uncertainty_s"):
            _finite_or_none(getattr(self, name), name)
        _req(is_bounded_int(self.gap_count, minimum=0), "gap_count must be >= 0")
        _req(self.ros_header_stamp_policy == "UNRESOLVED", "ROS_HEADER_STAMP_POLICY must remain UNRESOLVED in P1")
        _status(self.status)
        validate_str_tuple(self.limitations)


@dataclass(frozen=True, kw_only=True)
class NominalScaleCandidate:
    evidence_id: str
    segment_name: str
    operator_nominal_value_m: float
    observed_value_m: float
    ratio: "float | None"
    ground_truth_mode: str
    uncertainty_status: str
    source_sha256: tuple
    status: str
    limitations: tuple

    def __post_init__(self):
        _req(is_finite_number(self.operator_nominal_value_m), "operator_nominal_value_m must be finite")
        _req(is_finite_number(self.observed_value_m), "observed_value_m must be finite")
        _finite_or_none(self.ratio, "ratio")
        _req(self.status == "BEST_EFFORT_ONLY", "translation scale candidate must never exceed BEST_EFFORT_ONLY")
        validate_sha256_tuple(self.source_sha256)
        validate_str_tuple(self.limitations)


@dataclass(frozen=True, kw_only=True)
class NominalYawGainCandidate:
    evidence_id: str
    segment_name: str
    operator_nominal_yaw_rad: float
    observed_integrated_yaw_rad: float
    ratio: "float | None"
    ground_truth_mode: str
    uncertainty_status: str
    source_sha256: tuple
    status: str
    limitations: tuple

    def __post_init__(self):
        _req(is_finite_number(self.operator_nominal_yaw_rad), "operator_nominal_yaw_rad must be finite")
        _req(is_finite_number(self.observed_integrated_yaw_rad), "observed_integrated_yaw_rad must be finite")
        _finite_or_none(self.ratio, "ratio")
        _req(self.status == "BEST_EFFORT_ONLY", "yaw gain candidate must never exceed BEST_EFFORT_ONLY")
        validate_sha256_tuple(self.source_sha256)
        validate_str_tuple(self.limitations)


@dataclass(frozen=True, kw_only=True)
class ChannelArbitrationCriterion:
    criterion_name: str
    primary_status: str
    secondary_status: str
    notes: str

    def __post_init__(self):
        _req(is_non_empty_str(self.criterion_name), "criterion_name required")
        for value in (self.primary_status, self.secondary_status):
            _req(value in ("PASS", "FAIL", "PARTIAL", "NOT_APPLICABLE", "UNRESOLVED"), f"invalid criterion status: {value!r}")


@dataclass(frozen=True, kw_only=True)
class ChannelArbitrationMatrix:
    schema_version: str
    evidence_id: str
    criteria: tuple
    preferred_analysis_channel: "str | None"
    authoritative_source_channel: "str | None"
    status: str
    limitations: tuple

    def __post_init__(self):
        _req(len(self.criteria) >= 1, "arbitration matrix requires at least one criterion")
        for c in self.criteria:
            _req(isinstance(c, ChannelArbitrationCriterion), "criteria entries must be ChannelArbitrationCriterion")
        _req(self.authoritative_source_channel is None,
             "AUTHORITATIVE_SOURCE_CHANNEL must remain null in P1 -- channel selection is out of scope")
        _req(self.preferred_analysis_channel != self.authoritative_source_channel or
             self.preferred_analysis_channel is None,
             "PREFERRED_ANALYSIS_CHANNEL must be distinct from AUTHORITATIVE_SOURCE_CHANNEL")
        _status(self.status)
        validate_str_tuple(self.limitations)


@dataclass(frozen=True, kw_only=True)
class DynamicResidualStatistics:
    schema_version: str
    evidence_id: str
    session_id: str
    segment_name: str
    channel: str
    residual_type: str
    residual_value: "float | None"
    unit: str
    sample_count: "int | None"
    status: str
    limitations: tuple

    def __post_init__(self):
        _req(self.residual_type in ("CROSS_CHANNEL", "INTERNAL_CONSISTENCY", "GROUND_TRUTH", "NOT_AVAILABLE"),
             f"invalid residual_type: {self.residual_type!r}")
        _finite_or_none(self.residual_value, "residual_value")
        if self.sample_count is not None:
            _req(is_bounded_int(self.sample_count, minimum=0), "sample_count must be >= 0 or None")
        _status(self.status)
        validate_str_tuple(self.limitations)


@dataclass(frozen=True, kw_only=True)
class CharacterizationClaim:
    claim_id: str
    status: str
    evidence_ids: tuple
    reason: str
    confidence: str

    def __post_init__(self):
        _req(is_non_empty_str(self.claim_id), "claim_id required")
        _status(self.status)
        validate_str_tuple(self.evidence_ids, allow_empty_tuple=False)
        _req(is_non_empty_str(self.reason), "reason required")
        _req(self.confidence in ("HIGH", "MEDIUM", "LOW"), f"invalid confidence: {self.confidence!r}")
        if self.status == "VERIFIED":
            _req(
                not any(marker in self.reason.upper() for marker in ("ONLY PARTIAL", "PARTIAL-ONLY")),
                "a VERIFIED claim must not be justified solely by PARTIAL evidence",
            )


@dataclass(frozen=True, kw_only=True)
class OdometryCharacterizationBundleR2:
    schema_version: str
    generated_utc_injected: str
    channel_quality: tuple
    alignment: tuple
    stationary: tuple
    motion: tuple
    imu: tuple
    timebase: tuple
    nominal_scale: tuple
    nominal_yaw: tuple
    arbitration: "ChannelArbitrationMatrix"
    dynamic_residuals: tuple
    claims: tuple
    limitations: tuple

    def __post_init__(self):
        _req(is_non_empty_str(self.generated_utc_injected), "generated_utc_injected must be a non-empty injected string")
        _req(isinstance(self.arbitration, ChannelArbitrationMatrix), "arbitration must be a ChannelArbitrationMatrix")
        _req(self.arbitration.authoritative_source_channel is None,
             "bundle-level invariant: AUTHORITATIVE_SOURCE_CHANNEL must remain null")
        claim_ids = {c.claim_id for c in self.claims}
        for c in self.claims:
            _req(is_non_empty_str(c.claim_id), "every claim requires a claim_id")
        validate_str_tuple(self.limitations)


# =====================================================================
# MVP-ODOM-TF-R2-P1A -- quantitative audit and claim-hardening models.
# Additive to the P1 models above; nothing above this line was removed.
# =====================================================================

SEQUENCE_SEMANTICS_VALUES = frozenset({
    "GLOBAL_ACROSS_ALL_TOPICS", "CHANNEL_LOCAL", "FILE_LOCAL", "UNKNOWN",
})

GAP_CLASSIFICATION_VALUES = frozenset({
    "TIME_GAP", "EXPECTED_CADENCE_MISS", "RECORDER_GLOBAL_SEQUENCE_GAP",
    "CHANNEL_LOCAL_SEQUENCE_GAP", "FILE_BOUNDARY", "PHASE_BOUNDARY",
    "INTENTIONAL_INACTIVITY", "UNKNOWN",
})


@dataclass(frozen=True, kw_only=True)
class SequenceSemantics:
    """H3: the recorder's `sequence` field is a single counter shared across
    every topic it emits (odom, lf_odom, lowstate, bms, lidar, events, ...),
    never a per-channel counter. Determined empirically by P1 (irregular
    per-channel deltas: 2,5,10,15,19,22,25...) and re-confirmed here against
    raw evidence. A per-channel sequence SPAN must never be read as a
    per-channel sample-loss count on its own."""
    evidence_id: str
    session_id: str
    classification: str
    evidence_summary: str
    status: str
    limitations: tuple

    def __post_init__(self):
        _req(self.classification in SEQUENCE_SEMANTICS_VALUES,
             f"invalid sequence semantics classification: {self.classification!r}")
        _req(is_non_empty_str(self.evidence_summary), "evidence_summary required")
        _status(self.status)
        validate_str_tuple(self.limitations)


@dataclass(frozen=True, kw_only=True)
class DropoutDetectionPolicy:
    """H3: the corrected, documented policy P1A uses to classify a gap.
    TIME_GAP (monotonic receipt-time exceeding the channel's own robust
    threshold) is the PRIMARY, most trustworthy signal. A sequence-derived
    span is only ever an auxiliary corroborating signal, and is explicitly
    RELABELED here as `channel_local_sequence_gap_estimate` rather than
    `dropout_count`, since the underlying counter is shared across topics
    (see SequenceSemantics) and cannot alone prove a sample was lost."""
    schema_version: str
    evidence_id: str
    primary_signal: str
    secondary_signal: str
    time_gap_method: str
    time_gap_threshold_method: str
    sequence_gap_caveat: str
    status: str
    limitations: tuple

    def __post_init__(self):
        _req(self.primary_signal == "TIME_GAP", "primary dropout signal must be TIME_GAP")
        _req(is_non_empty_str(self.secondary_signal), "secondary_signal required")
        _req(is_non_empty_str(self.time_gap_method), "time_gap_method required")
        _req(is_non_empty_str(self.sequence_gap_caveat), "sequence_gap_caveat required")
        _status(self.status)
        validate_str_tuple(self.limitations)


@dataclass(frozen=True, kw_only=True)
class PairingTimeOffsetMetrics:
    """H4: the pure, descriptive nearest-neighbor pairing-time offset between
    two already-aligned channels -- NOT a claim about causal lag. Always
    derivable whenever samples exist to pair."""
    schema_version: str
    evidence_id: str
    session_id: str
    phase: str
    paired_sample_count: int
    time_offset_median_s: float
    time_offset_p95_s: float
    status: str
    limitations: tuple

    def __post_init__(self):
        _req(self.paired_sample_count >= 0, "paired_sample_count must be >= 0")
        _req(is_finite_number(self.time_offset_median_s), "time_offset_median_s must be finite")
        _req(is_finite_number(self.time_offset_p95_s), "time_offset_p95_s must be finite")
        _status(self.status)
        validate_str_tuple(self.limitations)


@dataclass(frozen=True, kw_only=True)
class CausalLagCandidate:
    """H4: a candidate causal lag between primary and LF channels, derived
    from a real cross-correlation scan (never a bare pairing-offset reuse).
    `status` is pinned to UNRESOLVED by construction in this checkpoint --
    per section 21's own claims enumeration, CAUSAL_CHANNEL_LAG has no
    non-UNRESOLVED value listed, so this model structurally forbids ever
    promoting a causal-lag claim here, regardless of what the scan finds."""
    schema_version: str
    evidence_id: str
    session_id: str
    phase: str
    scan_lags_ms: tuple
    scan_correlations: tuple
    peak_lag_ms: "float | None"
    peak_correlation: "float | None"
    zero_lag_correlation: "float | None"
    aliasing_risk: str
    sample_rate_ratio: str
    rejection_reason: str
    status: str
    limitations: tuple

    def __post_init__(self):
        _req(len(self.scan_lags_ms) == len(self.scan_correlations),
             "scan_lags_ms and scan_correlations must be the same length")
        for v in self.scan_lags_ms:
            _req(is_finite_number(v), "scan_lags_ms entries must be finite")
        for v in self.scan_correlations:
            if v is not None:
                _req(is_finite_number(v), "scan_correlations entries must be finite or None")
        _finite_or_none(self.peak_lag_ms, "peak_lag_ms")
        _finite_or_none(self.peak_correlation, "peak_correlation")
        _finite_or_none(self.zero_lag_correlation, "zero_lag_correlation")
        _req(self.aliasing_risk in ("LOW", "MEDIUM", "HIGH", "NOT_APPLICABLE"),
             f"invalid aliasing_risk: {self.aliasing_risk!r}")
        _req(is_non_empty_str(self.rejection_reason), "rejection_reason required")
        _req(self.status == "UNRESOLVED",
             "CausalLagCandidate.status must be UNRESOLVED in this checkpoint (section 21)")
        validate_str_tuple(self.limitations)


@dataclass(frozen=True, kw_only=True)
class YawAngleResidualMetrics:
    """H5: yaw ANGLE residual (radians) between primary and LF. Structurally
    UNAVAILABLE in P1/P1A: SportModeState's recorder stream carries no
    orientation/quaternion field, and no pose-yaw-angle was ever derived
    from position deltas (that would require its own documented method,
    e.g. atan2 of consecutive velocity vectors, which was not implemented
    here) -- so this model can only ever be constructed with status
    NOT_AVAILABLE, never a numeric value."""
    schema_version: str
    evidence_id: str
    session_id: str
    phase: str
    yaw_angle_rmse_rad: "float | None"
    status: str
    limitations: tuple

    def __post_init__(self):
        _req(self.status == "NOT_AVAILABLE", "yaw angle residual must remain NOT_AVAILABLE (no orientation data)")
        _req(self.yaw_angle_rmse_rad is None, "yaw_angle_rmse_rad must be None while status is NOT_AVAILABLE")
        validate_str_tuple(self.limitations)


@dataclass(frozen=True, kw_only=True)
class YawSpeedResidualMetrics:
    """H5: yaw SPEED residual (rad/s) between primary and LF -- the metric
    P1 actually computed and previously mislabeled as a bare 'yaw_rmse'."""
    schema_version: str
    evidence_id: str
    session_id: str
    phase: str
    yaw_speed_rmse_rad_s: "float | None"
    yaw_speed_mae_rad_s: "float | None"
    sample_count: int
    status: str
    limitations: tuple

    def __post_init__(self):
        _finite_or_none(self.yaw_speed_rmse_rad_s, "yaw_speed_rmse_rad_s")
        _finite_or_none(self.yaw_speed_mae_rad_s, "yaw_speed_mae_rad_s")
        _req(self.sample_count >= 0, "sample_count must be >= 0")
        _status(self.status)
        validate_str_tuple(self.limitations)


@dataclass(frozen=True, kw_only=True)
class SegmentEligibility:
    """H7: explicit per-segment eligibility so a claim can never silently
    cite a segment for a purpose it was never valid for (e.g. using
    left_90_return_invalidated as ground truth)."""
    evidence_id: str
    session_id: str
    segment_name: str
    valid_for_descriptive_analysis: bool
    valid_for_channel_alignment: bool
    valid_for_timebase: bool
    valid_for_imu_sign: bool
    valid_for_ground_truth: bool
    valid_for_translation_scale: bool
    valid_for_yaw_gain: bool
    invalid_reason: "str | None"
    baseline_scope: str

    def __post_init__(self):
        for name in ("valid_for_descriptive_analysis", "valid_for_channel_alignment",
                     "valid_for_timebase", "valid_for_imu_sign", "valid_for_ground_truth",
                     "valid_for_translation_scale", "valid_for_yaw_gain"):
            _req(type(getattr(self, name)) is bool, f"{name} must be a plain bool")
        if not self.valid_for_ground_truth:
            _req(is_non_empty_str(self.invalid_reason) or self.invalid_reason is None,
                 "invalid_reason must be a str or None")
        _req(is_non_empty_str(self.baseline_scope), "baseline_scope required")


@dataclass(frozen=True, kw_only=True)
class ArbitrationScoringRule:
    """H2/H6: one fully-transparent arbitration criterion row -- explicit
    direction, raw metrics for both channels, normalization/weight, and the
    resulting winner, so 'primary is preferred because of X' can never be
    silently contradicted by the underlying numbers again."""
    name: str
    direction: str
    primary_raw_metric: "float | None"
    lf_raw_metric: "float | None"
    normalization: str
    weight: float
    winner: str
    confidence: str
    limitations: tuple

    def __post_init__(self):
        _req(is_non_empty_str(self.name), "name required")
        _req(self.direction in ("HIGHER_IS_BETTER", "LOWER_IS_BETTER", "NOT_DISCRIMINATING"),
             f"invalid direction: {self.direction!r}")
        _finite_or_none(self.primary_raw_metric, "primary_raw_metric")
        _finite_or_none(self.lf_raw_metric, "lf_raw_metric")
        _req(is_non_empty_str(self.normalization), "normalization required")
        _req(is_finite_number(self.weight) and self.weight >= 0, "weight must be finite and >= 0")
        _req(self.winner in ("PRIMARY", "LF", "TIE", "NOT_APPLICABLE"), f"invalid winner: {self.winner!r}")
        _req(self.confidence in ("HIGH", "MEDIUM", "LOW"), f"invalid confidence: {self.confidence!r}")
        validate_str_tuple(self.limitations)


@dataclass(frozen=True, kw_only=True)
class ArbitrationDecisionAudit:
    """H2/H6: the corrected arbitration record. `criterion_count` MUST equal
    `len(criteria)` -- this is enforced structurally so a reported count can
    never again silently drift from what was actually serialized (closes
    H6). `preferred_analysis_channel` must be textually consistent with the
    per-criterion winners (closes H2): it is only set when the weighted
    winner count actually supports it, and is null otherwise."""
    schema_version: str
    evidence_id: str
    criteria: tuple
    criterion_count: int
    aggregation_method: str
    preferred_analysis_channel: "str | None"
    authoritative_source_channel: "str | None"
    consistent_with_criteria: bool
    status: str
    limitations: tuple

    def __post_init__(self):
        _req(len(self.criteria) >= 1, "at least one criterion is required")
        for c in self.criteria:
            _req(isinstance(c, ArbitrationScoringRule), "criteria entries must be ArbitrationScoringRule")
        _req(self.criterion_count == len(self.criteria),
             f"criterion_count ({self.criterion_count}) must equal len(criteria) ({len(self.criteria)})")
        _req(self.authoritative_source_channel is None,
             "AUTHORITATIVE_SOURCE_CHANNEL must remain null -- channel selection is out of scope")
        _req(type(self.consistent_with_criteria) is bool, "consistent_with_criteria must be a plain bool")
        _req(self.consistent_with_criteria,
             "an ArbitrationDecisionAudit must never be constructed in a self-contradictory state")
        _status(self.status)
        validate_str_tuple(self.limitations)


@dataclass(frozen=True, kw_only=True)
class BootRelationEvidence:
    """H8: boot-relation evidence with an explicit, verified integrity
    chain -- never resolved by bare textual similarity of a boot_id
    string. `same_boot_verified` requires BOTH sides' source files to be
    independently hash-verified AND their boot_id strings to match exactly.
    Distinguishes same-boot from same-time-domain/continuous-capture/
    continuous-trajectory, none of which follow automatically (section 20)."""
    evidence_id: str
    session_a: str
    session_b: str
    boot_id_a: str
    boot_id_b: str
    source_a_sha256: str
    source_b_sha256: str
    source_a_hash_verified: bool
    source_b_hash_verified: bool
    same_boot_verified: bool
    same_time_domain: bool
    continuous_capture: bool
    continuous_trajectory_permitted: bool
    status: str
    limitations: tuple

    def __post_init__(self):
        _req(is_sha256_hex(self.source_a_sha256), "source_a_sha256 invalid")
        _req(is_sha256_hex(self.source_b_sha256), "source_b_sha256 invalid")
        for name in ("source_a_hash_verified", "source_b_hash_verified", "same_boot_verified",
                     "same_time_domain", "continuous_capture", "continuous_trajectory_permitted"):
            _req(type(getattr(self, name)) is bool, f"{name} must be a plain bool")
        if self.same_boot_verified:
            _req(self.source_a_hash_verified and self.source_b_hash_verified,
                 "same_boot_verified requires both sources to be independently hash-verified")
            _req(self.boot_id_a == self.boot_id_b,
                 "same_boot_verified requires boot_id_a == boot_id_b")
        _req(not self.continuous_trajectory_permitted,
             "same-boot evidence must never by itself authorize trajectory concatenation (section 20)")
        _status(self.status)
        validate_str_tuple(self.limitations)


@dataclass(frozen=True, kw_only=True)
class P1AuditFinding:
    """One H1-H10 audit finding: hypothesis id, classification, evidence,
    and the concrete fix applied (if any)."""
    hypothesis_id: str
    title: str
    classification: str
    evidence: tuple
    fix_applied: str
    limitations: tuple

    def __post_init__(self):
        _req(is_non_empty_str(self.hypothesis_id), "hypothesis_id required")
        _req(is_non_empty_str(self.title), "title required")
        _req(self.classification in ("REPRODUCED", "NOT_REPRODUCED", "PARTIAL", "INDETERMINATE"),
             f"invalid classification: {self.classification!r}")
        validate_str_tuple(self.evidence, allow_empty_tuple=False)
        _req(is_non_empty_str(self.fix_applied), "fix_applied required")
        validate_str_tuple(self.limitations)


@dataclass(frozen=True, kw_only=True)
class P1ACharacterizationBundle:
    """Top-level P1A bundle: everything from P1's bundle plus the audit
    findings and hardened models. Composition, not replacement -- the P1
    bundle fields are unchanged in shape; this wraps them alongside the new
    P1A-only evidence."""
    schema_version: str
    generated_utc_injected: str
    p1_bundle: "OdometryCharacterizationBundleR2"
    audit_findings: tuple
    sequence_semantics: tuple
    dropout_policy: "DropoutDetectionPolicy"
    pairing_offsets: tuple
    causal_lag_candidates: tuple
    yaw_angle_residuals: tuple
    yaw_speed_residuals: tuple
    segment_eligibility: tuple
    arbitration_audit: "ArbitrationDecisionAudit"
    boot_relation_evidence: tuple
    claims: tuple
    limitations: tuple

    def __post_init__(self):
        _req(is_non_empty_str(self.generated_utc_injected), "generated_utc_injected must be a non-empty injected string")
        _req(isinstance(self.p1_bundle, OdometryCharacterizationBundleR2), "p1_bundle must be the P1 bundle")
        for f in self.audit_findings:
            _req(isinstance(f, P1AuditFinding), "audit_findings entries must be P1AuditFinding")
        _req(len(self.audit_findings) == 10, f"expected exactly 10 audit findings (H1-H10), got {len(self.audit_findings)}")
        _req(isinstance(self.dropout_policy, DropoutDetectionPolicy), "dropout_policy must be a DropoutDetectionPolicy")
        _req(isinstance(self.arbitration_audit, ArbitrationDecisionAudit),
             "arbitration_audit must be an ArbitrationDecisionAudit")
        _req(self.arbitration_audit.authoritative_source_channel is None,
             "bundle-level invariant: AUTHORITATIVE_SOURCE_CHANNEL must remain null")
        validate_str_tuple(self.limitations)
