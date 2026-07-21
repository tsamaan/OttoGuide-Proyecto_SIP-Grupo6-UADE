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

CHARACTERIZATION_SCHEMA_VERSION = "2.1.0-p1"

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
    yaw_mae: "float | None"
    yaw_rmse: "float | None"
    yaw_p95: "float | None"
    yaw_max: "float | None"
    correlation_position: "float | None"
    status: str
    limitations: tuple

    def __post_init__(self):
        _req(0.0 <= self.pairing_coverage <= 1.0, "pairing_coverage must be in [0,1]")
        _req(self.paired_sample_count <= min(self.primary_sample_count, self.secondary_sample_count),
             "paired_sample_count cannot exceed either input sample count (no ambiguous reuse)")
        for name in ("position_mae", "position_rmse", "position_p95", "position_max",
                     "yaw_mae", "yaw_rmse", "yaw_p95", "yaw_max", "correlation_position", "lag_candidate_ms"):
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
