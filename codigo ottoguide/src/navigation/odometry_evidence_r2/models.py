"""Typed, immutable, fail-closed data model for ODOM/TF R2-P0/P0A physical
evidence ingestion.

Separate from odometry_candidate_adapter (R1): R1's OdometryCandidate is left
untouched and remains the R1 baseline/regression contract. Nothing here
imports rclpy, nav_msgs, geometry_msgs, tf2_ros, cyclonedds, unitree_sdk2py,
socket, requests, or httpx, and nothing here performs network or live-SDK
I/O. Every dataclass is frozen (immutable) and every field is validated in
`__post_init__` (structural/cross-field invariants) and by `validation.py`
helpers (field-level type/format checks) -- construction itself is the
fail-closed boundary; nothing downstream needs to re-check these values.

SCHEMA_VERSION follows this package, not R1's. P0A raises it from 2.0.0-p0
to 2.0.1-p0a (section 11.1) -- existing 2.0.0-p0 outputs are never
overwritten in place; the P0A CLI writes to its own output directory.
"""
from dataclasses import dataclass, field

from .validation import (
    EvidenceValidationError,
    STATUS_VALUES,
    GROUND_TRUTH_VALUES,
    SESSION_TYPE_VALUES,
    is_bounded_int,
    is_finite_number,
    is_non_empty_str,
    is_relative_portable_path,
    is_sha256_hex,
    validate_ground_truth,
    validate_session_type,
    validate_status,
)

SCHEMA_VERSION = "2.0.1-p0a"

_CONFIDENCE_PREFIXES = ("HIGH", "MEDIUM", "LOW")


def _check_evidence_id(evidence_id) -> None:
    if not is_non_empty_str(evidence_id):
        raise EvidenceValidationError(f"evidence_id must be a non-empty str: {evidence_id!r}")


def _check_confidence(confidence) -> None:
    if not is_non_empty_str(confidence) or not confidence.startswith(_CONFIDENCE_PREFIXES):
        raise EvidenceValidationError(
            f"confidence must be a non-empty str starting with HIGH/MEDIUM/LOW: {confidence!r}"
        )


def _check_session_id(session_id) -> None:
    if not is_non_empty_str(session_id):
        raise EvidenceValidationError(f"session_id must be a non-empty str: {session_id!r}")


def _check_boot_id(boot_id) -> None:
    if boot_id is not None and not is_non_empty_str(boot_id):
        raise EvidenceValidationError(
            f"boot_id must be None or a non-empty str (explicit unknown, never ''): {boot_id!r}"
        )


def _check_source_files_and_hashes(source_files, source_sha256, *, allow_empty=False) -> None:
    if type(source_files) is not tuple or type(source_sha256) is not tuple:
        raise EvidenceValidationError("source_files and source_sha256 must be tuples")
    if len(source_files) != len(source_sha256):
        raise EvidenceValidationError(
            f"source_files/source_sha256 length mismatch: "
            f"{len(source_files)} files vs {len(source_sha256)} hashes"
        )
    if not allow_empty and len(source_files) == 0:
        raise EvidenceValidationError("source_files/source_sha256 must not be empty")
    for path in source_files:
        if not is_relative_portable_path(path):
            raise EvidenceValidationError(f"non-portable source_files entry: {path!r}")
    for digest in source_sha256:
        if not is_sha256_hex(digest):
            raise EvidenceValidationError(f"non-sha256 source_sha256 entry: {digest!r}")


def _check_limitations(limitations) -> None:
    if type(limitations) is not tuple:
        raise EvidenceValidationError("limitations must be a tuple[str, ...]")
    for item in limitations:
        if type(item) is not str:
            raise EvidenceValidationError(f"non-string limitations entry: {item!r}")


def _check_sample_count(sample_count, *, allow_none=False) -> None:
    if sample_count is None:
        if allow_none:
            return
        raise EvidenceValidationError("sample_count must not be None here")
    if not is_bounded_int(sample_count, minimum=0):
        raise EvidenceValidationError(f"sample_count must be an int >= 0: {sample_count!r}")


def _check_finite_or_none(value, *, field_name) -> None:
    if value is not None and not is_finite_number(value):
        raise EvidenceValidationError(f"{field_name} must be None or a finite number: {value!r}")


def _check_schema_version(schema_version) -> None:
    if schema_version != SCHEMA_VERSION:
        raise EvidenceValidationError(
            f"schema_version must be exactly {SCHEMA_VERSION!r}, got {schema_version!r}"
        )


@dataclass(frozen=True, kw_only=True)
class EvidenceProvenance:
    """Where a piece of evidence physically came from and how it was
    produced -- never a claim about what it means."""
    schema_version: str = SCHEMA_VERSION
    evidence_id: str
    source_package: str
    source_relative_path: str
    source_sha256: str
    source_archive_relative_path: "str | None" = None
    source_archive_sha256: "str | None" = None
    transformation_script: "str | None" = None
    transformation_script_sha256: "str | None" = None
    arguments: "tuple[str, ...]" = ()
    generated_utc: str
    limitations: "tuple[str, ...]" = ()

    def __post_init__(self):
        _check_schema_version(self.schema_version)
        _check_evidence_id(self.evidence_id)
        if not is_non_empty_str(self.source_package):
            raise EvidenceValidationError("source_package must be a non-empty str")
        if not is_relative_portable_path(self.source_relative_path):
            raise EvidenceValidationError(
                f"non-portable source_relative_path: {self.source_relative_path!r}"
            )
        if not is_sha256_hex(self.source_sha256):
            raise EvidenceValidationError(f"invalid source_sha256: {self.source_sha256!r}")
        if self.source_archive_sha256 is not None and not is_sha256_hex(self.source_archive_sha256):
            raise EvidenceValidationError(
                f"invalid source_archive_sha256: {self.source_archive_sha256!r}"
            )
        if self.transformation_script_sha256 is not None and not is_sha256_hex(
            self.transformation_script_sha256
        ):
            raise EvidenceValidationError(
                f"invalid transformation_script_sha256: {self.transformation_script_sha256!r}"
            )
        if not is_non_empty_str(self.generated_utc):
            raise EvidenceValidationError("generated_utc must be a non-empty str")
        _check_limitations(self.limitations)


@dataclass(frozen=True, kw_only=True)
class GroundTruthConstraint:
    """Typed nominal ground-truth claim for one operator-attempted motion
    (section 11.2). Never promotes BEST_EFFORT_MEASURED/NOMINAL to MEASURED;
    `mode` and `status` are independently validated against their own
    vocabularies so a caller cannot smuggle a stronger claim through one
    field while leaving the other conservative."""
    schema_version: str = SCHEMA_VERSION
    mode: str
    nominal_translation_m: "float | None"
    nominal_yaw_rad: "float | None"
    measurement_uncertainty: str
    source: str
    status: str
    limitations: "tuple[str, ...]" = ()

    def __post_init__(self):
        _check_schema_version(self.schema_version)
        validate_ground_truth(self.mode)
        validate_status(self.status)
        _check_finite_or_none(self.nominal_translation_m, field_name="nominal_translation_m")
        _check_finite_or_none(self.nominal_yaw_rad, field_name="nominal_yaw_rad")
        if not is_non_empty_str(self.measurement_uncertainty):
            raise EvidenceValidationError("measurement_uncertainty must be a non-empty str")
        if not is_non_empty_str(self.source):
            raise EvidenceValidationError("source must be a non-empty str")
        if self.mode == "MEASURED" and "UNBOUNDED" in self.measurement_uncertainty.upper():
            raise EvidenceValidationError(
                "mode=MEASURED is incompatible with an unbounded measurement_uncertainty"
            )
        _check_limitations(self.limitations)


@dataclass(frozen=True, kw_only=True)
class JsonlParseReport:
    """Audit trail for one _parse_channel_jsonl_dir() call (section 11.3).
    Every count is an int >= 0; on the real, hash-verified harvest every
    count except file_count/record_count/terminal_nul_files/discarded_records
    is expected to be zero."""
    schema_version: str = SCHEMA_VERSION
    directory: str
    expected_topic: str
    file_count: int
    record_count: int
    discarded_records: int
    terminal_nul_files: int
    duplicate_sequences: int
    monotonic_inversions: int
    schema_errors: int

    def __post_init__(self):
        _check_schema_version(self.schema_version)
        if not is_non_empty_str(self.expected_topic):
            raise EvidenceValidationError("expected_topic must be a non-empty str")
        for name in ("file_count", "record_count", "discarded_records", "terminal_nul_files",
                     "duplicate_sequences", "monotonic_inversions", "schema_errors"):
            value = getattr(self, name)
            if not is_bounded_int(value, minimum=0):
                raise EvidenceValidationError(f"{name} must be an int >= 0: {value!r}")


@dataclass(frozen=True, kw_only=True)
class PhysicalSessionEvidence:
    schema_version: str = SCHEMA_VERSION
    evidence_id: str
    status: str
    confidence: str
    session_id: str
    session_type: str
    boot_id: "str | None"
    clean_shutdown: bool
    physical_movement_authority: str
    streams: "tuple[str, ...]"
    phases: "tuple[str, ...]"
    provenance: "tuple[EvidenceProvenance, ...]"
    source_files: "tuple[str, ...]"
    source_sha256: "tuple[str, ...]"
    limitations: "tuple[str, ...]" = ()

    def __post_init__(self):
        _check_schema_version(self.schema_version)
        _check_evidence_id(self.evidence_id)
        validate_status(self.status)
        _check_confidence(self.confidence)
        _check_session_id(self.session_id)
        validate_session_type(self.session_type)
        _check_boot_id(self.boot_id)
        if type(self.clean_shutdown) is not bool:
            raise EvidenceValidationError("clean_shutdown must be a plain bool")
        if not is_non_empty_str(self.physical_movement_authority):
            raise EvidenceValidationError("physical_movement_authority must be a non-empty str")
        _check_source_files_and_hashes(self.source_files, self.source_sha256)
        _check_limitations(self.limitations)


@dataclass(frozen=True, kw_only=True)
class SessionTimeDomain:
    schema_version: str = SCHEMA_VERSION
    evidence_id: str
    status: str
    confidence: str
    session_id: str
    boot_id: "str | None"
    message_stamp_status: str
    receipt_monotonic_available: bool
    receipt_wall_utc_available: bool
    notebook_utc_estimate: "str | None"
    rtt_seconds: "float | None"
    uncertainty_seconds: "float | None"
    mapping_status: str
    source_files: "tuple[str, ...]"
    source_sha256: "tuple[str, ...]"
    limitations: "tuple[str, ...]" = ()

    def __post_init__(self):
        _check_schema_version(self.schema_version)
        _check_evidence_id(self.evidence_id)
        validate_status(self.status)
        _check_confidence(self.confidence)
        _check_session_id(self.session_id)
        _check_boot_id(self.boot_id)
        if not is_non_empty_str(self.message_stamp_status):
            raise EvidenceValidationError("message_stamp_status must be a non-empty str")
        if type(self.receipt_monotonic_available) is not bool:
            raise EvidenceValidationError("receipt_monotonic_available must be a plain bool")
        if type(self.receipt_wall_utc_available) is not bool:
            raise EvidenceValidationError("receipt_wall_utc_available must be a plain bool")
        _check_finite_or_none(self.rtt_seconds, field_name="rtt_seconds")
        _check_finite_or_none(self.uncertainty_seconds, field_name="uncertainty_seconds")
        if not is_non_empty_str(self.mapping_status):
            raise EvidenceValidationError("mapping_status must be a non-empty str")
        _check_source_files_and_hashes(self.source_files, self.source_sha256, allow_empty=True)
        _check_limitations(self.limitations)


@dataclass(frozen=True, kw_only=True)
class DynamicMotionSegment:
    schema_version: str = SCHEMA_VERSION
    evidence_id: str
    session_id: str
    boot_id: "str | None"
    phase: str
    channel: str
    start_sequence: "int | None"
    end_sequence: "int | None"
    movement_type: str
    ground_truth_constraint: str
    ground_truth_detail: "GroundTruthConstraint | None" = None
    valid: bool
    invalid_reason: "str | None"
    delta_position: "tuple[float, float, float] | None"
    integrated_yaw_speed_rad: "float | None"
    sample_count: "int | None"
    duration_s: "float | None"
    source_files: "tuple[str, ...]"
    source_sha256: "tuple[str, ...]"
    limitations: "tuple[str, ...]" = ()

    def __post_init__(self):
        _check_schema_version(self.schema_version)
        _check_evidence_id(self.evidence_id)
        _check_session_id(self.session_id)
        _check_boot_id(self.boot_id)
        if not is_non_empty_str(self.phase):
            raise EvidenceValidationError("phase must be a non-empty str")
        if not is_non_empty_str(self.channel):
            raise EvidenceValidationError("channel must be a non-empty str")
        if self.start_sequence is not None and not is_bounded_int(self.start_sequence, minimum=0):
            raise EvidenceValidationError(f"start_sequence must be None or int >= 0: {self.start_sequence!r}")
        if self.end_sequence is not None and not is_bounded_int(self.end_sequence, minimum=0):
            raise EvidenceValidationError(f"end_sequence must be None or int >= 0: {self.end_sequence!r}")
        if self.start_sequence is not None and self.end_sequence is not None:
            if self.start_sequence > self.end_sequence:
                raise EvidenceValidationError(
                    f"start_sequence ({self.start_sequence}) must be <= end_sequence "
                    f"({self.end_sequence})"
                )
        if not is_non_empty_str(self.movement_type):
            raise EvidenceValidationError("movement_type must be a non-empty str")
        validate_ground_truth(self.ground_truth_constraint)
        if self.ground_truth_detail is not None and not isinstance(self.ground_truth_detail, GroundTruthConstraint):
            raise EvidenceValidationError("ground_truth_detail must be None or a GroundTruthConstraint")
        if type(self.valid) is not bool:
            raise EvidenceValidationError("valid must be a plain bool")
        if self.valid and self.invalid_reason is not None:
            raise EvidenceValidationError("a valid segment must have invalid_reason=None")
        if not self.valid and not is_non_empty_str(self.invalid_reason):
            raise EvidenceValidationError("an invalid segment requires a non-empty invalid_reason")
        if self.delta_position is not None:
            if type(self.delta_position) is not tuple or len(self.delta_position) != 3:
                raise EvidenceValidationError("delta_position must be None or a 3-tuple")
            for component in self.delta_position:
                if not is_finite_number(component):
                    raise EvidenceValidationError(f"non-finite delta_position component: {component!r}")
        _check_finite_or_none(self.integrated_yaw_speed_rad, field_name="integrated_yaw_speed_rad")
        _check_sample_count(self.sample_count, allow_none=True)
        _check_finite_or_none(self.duration_s, field_name="duration_s")
        _check_source_files_and_hashes(self.source_files, self.source_sha256)
        _check_limitations(self.limitations)


@dataclass(frozen=True, kw_only=True)
class StationarySegment:
    schema_version: str = SCHEMA_VERSION
    evidence_id: str
    session_id: str
    boot_id: "str | None"
    phase: str
    channel: str
    sample_count: int
    position_range: "tuple[float, float, float]"
    position_stddev: "tuple[float, float, float]"
    yaw_speed_mean: float
    yaw_speed_stddev: float
    source_files: "tuple[str, ...]"
    source_sha256: "tuple[str, ...]"
    limitations: "tuple[str, ...]" = ()

    def __post_init__(self):
        _check_schema_version(self.schema_version)
        _check_evidence_id(self.evidence_id)
        _check_session_id(self.session_id)
        _check_boot_id(self.boot_id)
        if not is_non_empty_str(self.phase):
            raise EvidenceValidationError("phase must be a non-empty str")
        if not is_non_empty_str(self.channel):
            raise EvidenceValidationError("channel must be a non-empty str")
        _check_sample_count(self.sample_count)
        for name, vec in (("position_range", self.position_range), ("position_stddev", self.position_stddev)):
            if type(vec) is not tuple or len(vec) != 3:
                raise EvidenceValidationError(f"{name} must be a 3-tuple")
            for component in vec:
                if not is_finite_number(component):
                    raise EvidenceValidationError(f"non-finite {name} component: {component!r}")
        if not is_finite_number(self.yaw_speed_mean):
            raise EvidenceValidationError(f"yaw_speed_mean must be finite: {self.yaw_speed_mean!r}")
        if not is_finite_number(self.yaw_speed_stddev):
            raise EvidenceValidationError(f"yaw_speed_stddev must be finite: {self.yaw_speed_stddev!r}")
        _check_source_files_and_hashes(self.source_files, self.source_sha256)
        _check_limitations(self.limitations)


@dataclass(frozen=True, kw_only=True)
class AxisResponseObservation:
    schema_version: str = SCHEMA_VERSION
    evidence_id: str
    status: str
    axis: str
    dominant: bool
    evidence_segment_ids: "tuple[str, ...]"
    limitations: "tuple[str, ...]" = ()

    def __post_init__(self):
        _check_schema_version(self.schema_version)
        _check_evidence_id(self.evidence_id)
        validate_status(self.status)
        if not is_non_empty_str(self.axis):
            raise EvidenceValidationError("axis must be a non-empty str")
        if type(self.dominant) is not bool:
            raise EvidenceValidationError("dominant must be a plain bool")
        if type(self.evidence_segment_ids) is not tuple:
            raise EvidenceValidationError("evidence_segment_ids must be a tuple[str, ...]")
        _check_limitations(self.limitations)


@dataclass(frozen=True, kw_only=True)
class YawResponseObservation:
    schema_version: str = SCHEMA_VERSION
    evidence_id: str
    status: str
    sign_candidate: str
    evidence_segment_ids: "tuple[str, ...]"
    limitations: "tuple[str, ...]" = ()

    def __post_init__(self):
        _check_schema_version(self.schema_version)
        _check_evidence_id(self.evidence_id)
        validate_status(self.status)
        if not is_non_empty_str(self.sign_candidate):
            raise EvidenceValidationError("sign_candidate must be a non-empty str")
        if type(self.evidence_segment_ids) is not tuple:
            raise EvidenceValidationError("evidence_segment_ids must be a tuple[str, ...]")
        _check_limitations(self.limitations)


@dataclass(frozen=True, kw_only=True)
class ChannelComparisonEvidence:
    schema_version: str = SCHEMA_VERSION
    evidence_id: str
    status: str
    primary_channel: str
    secondary_channel: str
    primary_sample_count: "int | None"
    secondary_sample_count: "int | None"
    authoritative_source_channel: None
    primary_analysis_stream_candidate: bool
    arbitration_status: str
    observations: "tuple[str, ...]"
    source_files: "tuple[str, ...]"
    source_sha256: "tuple[str, ...]"
    limitations: "tuple[str, ...]" = ()

    def __post_init__(self):
        _check_schema_version(self.schema_version)
        _check_evidence_id(self.evidence_id)
        validate_status(self.status)
        if self.authoritative_source_channel is not None:
            raise EvidenceValidationError(
                "authoritative_source_channel must remain null in R2-P0/P0A"
            )
        if not is_non_empty_str(self.primary_channel) or not is_non_empty_str(self.secondary_channel):
            raise EvidenceValidationError("primary_channel/secondary_channel must be non-empty str")
        if self.primary_sample_count is not None and not is_bounded_int(self.primary_sample_count, minimum=0):
            raise EvidenceValidationError("primary_sample_count must be None or int >= 0")
        if self.secondary_sample_count is not None and not is_bounded_int(self.secondary_sample_count, minimum=0):
            raise EvidenceValidationError("secondary_sample_count must be None or int >= 0")
        if type(self.primary_analysis_stream_candidate) is not bool:
            raise EvidenceValidationError("primary_analysis_stream_candidate must be a plain bool")
        _check_source_files_and_hashes(self.source_files, self.source_sha256)
        _check_limitations(self.limitations)


@dataclass(frozen=True, kw_only=True)
class ImuCrosscheckEvidence:
    schema_version: str = SCHEMA_VERSION
    evidence_id: str
    status: str
    session_id: str
    stationary_bias_observed: bool
    dynamic_response_observed: bool
    sign_agreement: str
    source_files: "tuple[str, ...]"
    source_sha256: "tuple[str, ...]"
    limitations: "tuple[str, ...]" = ()

    def __post_init__(self):
        _check_schema_version(self.schema_version)
        _check_evidence_id(self.evidence_id)
        validate_status(self.status)
        _check_session_id(self.session_id)
        if type(self.stationary_bias_observed) is not bool or type(self.dynamic_response_observed) is not bool:
            raise EvidenceValidationError("stationary_bias_observed/dynamic_response_observed must be plain bool")
        if not is_non_empty_str(self.sign_agreement):
            raise EvidenceValidationError("sign_agreement must be a non-empty str")
        _check_source_files_and_hashes(self.source_files, self.source_sha256)
        _check_limitations(self.limitations)


@dataclass(frozen=True, kw_only=True)
class ResetDiscontinuityEvidence:
    schema_version: str = SCHEMA_VERSION
    evidence_id: str
    status: str
    exact_reset_instant_status: str
    from_session_id: str
    to_session_id: str
    from_boot_id: str
    to_boot_id: str
    trajectory_concatenation_permitted: bool
    source_files: "tuple[str, ...]"
    source_sha256: "tuple[str, ...]"
    limitations: "tuple[str, ...]" = ()

    def __post_init__(self):
        _check_schema_version(self.schema_version)
        _check_evidence_id(self.evidence_id)
        validate_status(self.status)
        if not is_non_empty_str(self.exact_reset_instant_status):
            raise EvidenceValidationError("exact_reset_instant_status must be a non-empty str")
        _check_session_id(self.from_session_id)
        _check_session_id(self.to_session_id)
        if not is_non_empty_str(self.from_boot_id) or not is_non_empty_str(self.to_boot_id):
            raise EvidenceValidationError("from_boot_id/to_boot_id must be non-empty str")
        if type(self.trajectory_concatenation_permitted) is not bool:
            raise EvidenceValidationError("trajectory_concatenation_permitted must be a plain bool")
        if self.trajectory_concatenation_permitted:
            raise EvidenceValidationError(
                "trajectory_concatenation_permitted must be false: R3C and R4 "
                "belong to different boot domains and must never be treated "
                "as one continuous trajectory"
            )
        if self.from_boot_id == self.to_boot_id:
            raise EvidenceValidationError(
                "ResetDiscontinuityEvidence requires two distinct boot_id values"
            )
        _check_source_files_and_hashes(self.source_files, self.source_sha256)
        _check_limitations(self.limitations)


@dataclass(frozen=True, kw_only=True)
class LidarExtrinsicEvidence:
    schema_version: str = SCHEMA_VERSION
    evidence_id: str
    status: str
    source_frame_semantics_status: str
    child_frame_id_status: str
    candidate_transform_available: bool
    source_files: "tuple[str, ...]"
    source_sha256: "tuple[str, ...]"
    limitations: "tuple[str, ...]" = ()

    def __post_init__(self):
        _check_schema_version(self.schema_version)
        _check_evidence_id(self.evidence_id)
        validate_status(self.status)
        if not is_non_empty_str(self.source_frame_semantics_status):
            raise EvidenceValidationError("source_frame_semantics_status must be a non-empty str")
        if not is_non_empty_str(self.child_frame_id_status):
            raise EvidenceValidationError("child_frame_id_status must be a non-empty str")
        if type(self.candidate_transform_available) is not bool:
            raise EvidenceValidationError("candidate_transform_available must be a plain bool")
        _check_source_files_and_hashes(self.source_files, self.source_sha256)
        _check_limitations(self.limitations)


@dataclass(frozen=True, kw_only=True)
class StationaryNoiseStatistics:
    """Dispersion statistics for a stationary window. `observed_mean` is the
    raw sample mean in the source-channel candidate frame (an absolute
    position claim); `centered_mean` is always (0,0,0) by construction --
    it exists only to make explicit that variance/stddev characterize
    dispersion around the segment's OWN local baseline, governed by
    `reference_origin_policy`. Neither is ever silently substituted for the
    other (closes finding F8: a hardcoded 0.0 must never masquerade as an
    absolute-position claim)."""
    schema_version: str = SCHEMA_VERSION
    evidence_id: str
    session_id: str
    channel: str
    sample_count: int
    window_description: str
    observed_mean: "tuple[float, float, float]"
    centered_mean: "tuple[float, float, float]"
    reference_origin_policy: str
    variance: "tuple[float, ...]"
    stddev: "tuple[float, ...]"
    robust_method: str
    outlier_rule: str
    source_files: "tuple[str, ...]"
    source_sha256: "tuple[str, ...]"
    limitations: "tuple[str, ...]" = ()

    def __post_init__(self):
        _check_schema_version(self.schema_version)
        _check_evidence_id(self.evidence_id)
        _check_session_id(self.session_id)
        if not is_non_empty_str(self.channel):
            raise EvidenceValidationError("channel must be a non-empty str")
        _check_sample_count(self.sample_count)
        if not is_non_empty_str(self.window_description):
            raise EvidenceValidationError("window_description must be a non-empty str")
        for name, vec in (("observed_mean", self.observed_mean), ("centered_mean", self.centered_mean)):
            if type(vec) is not tuple or len(vec) != 3:
                raise EvidenceValidationError(f"{name} must be a 3-tuple")
            for component in vec:
                if not is_finite_number(component):
                    raise EvidenceValidationError(f"non-finite {name} component: {component!r}")
        if self.centered_mean != (0.0, 0.0, 0.0):
            raise EvidenceValidationError("centered_mean must be exactly (0.0, 0.0, 0.0) by construction")
        if not is_non_empty_str(self.reference_origin_policy):
            raise EvidenceValidationError("reference_origin_policy must be a non-empty str")
        for name, vec in (("variance", self.variance), ("stddev", self.stddev)):
            if type(vec) is not tuple:
                raise EvidenceValidationError(f"{name} must be a tuple")
            for component in vec:
                if not is_finite_number(component):
                    raise EvidenceValidationError(f"non-finite {name} component: {component!r}")
        if not is_non_empty_str(self.robust_method) or not is_non_empty_str(self.outlier_rule):
            raise EvidenceValidationError("robust_method/outlier_rule must be non-empty str")
        _check_source_files_and_hashes(self.source_files, self.source_sha256)
        _check_limitations(self.limitations)


@dataclass(frozen=True, kw_only=True)
class DynamicResidualStatistics:
    """Per-segment residual statistics. In P0A this is either an explicit
    NOT_AVAILABLE_IN_P0A placeholder (deferred to R2-P1, never an ambiguous
    empty structure -- closes finding F8's sibling gap) or a real computed
    record with status PARTIAL/VERIFIED."""
    schema_version: str = SCHEMA_VERSION
    evidence_id: str
    status: str
    session_id: str
    channel: str
    segment_id: str
    sample_count: "int | None"
    reported_translation_norm: "float | None"
    integrated_yaw_speed_rad: "float | None"
    source_files: "tuple[str, ...]"
    source_sha256: "tuple[str, ...]"
    limitations: "tuple[str, ...]" = ()

    def __post_init__(self):
        _check_schema_version(self.schema_version)
        _check_evidence_id(self.evidence_id)
        if self.status not in STATUS_VALUES | {"NOT_AVAILABLE_IN_P0A"}:
            raise EvidenceValidationError(f"invalid status: {self.status!r}")
        _check_session_id(self.session_id)
        if not is_non_empty_str(self.channel):
            raise EvidenceValidationError("channel must be a non-empty str")
        if not is_non_empty_str(self.segment_id):
            raise EvidenceValidationError("segment_id must be a non-empty str")
        _check_sample_count(self.sample_count, allow_none=True)
        _check_finite_or_none(self.reported_translation_norm, field_name="reported_translation_norm")
        _check_finite_or_none(self.integrated_yaw_speed_rad, field_name="integrated_yaw_speed_rad")
        _check_source_files_and_hashes(self.source_files, self.source_sha256, allow_empty=True)
        _check_limitations(self.limitations)


@dataclass(frozen=True, kw_only=True)
class CovarianceEvidence:
    schema_version: str = SCHEMA_VERSION
    evidence_id: str
    status: str
    publication_model_ready: bool
    stationary_stats_ids: "tuple[str, ...]"
    dynamic_stats_ids: "tuple[str, ...]"
    source_files: "tuple[str, ...]"
    source_sha256: "tuple[str, ...]"
    limitations: "tuple[str, ...]" = ()

    def __post_init__(self):
        _check_schema_version(self.schema_version)
        _check_evidence_id(self.evidence_id)
        validate_status(self.status)
        if type(self.publication_model_ready) is not bool:
            raise EvidenceValidationError("publication_model_ready must be a plain bool")
        if self.publication_model_ready:
            raise EvidenceValidationError(
                "CovarianceEvidence.publication_model_ready must be false in "
                "R2-P0/P0A -- no covariance value may be invented or promoted"
            )
        if not self.stationary_stats_ids and not self.dynamic_stats_ids:
            raise EvidenceValidationError(
                "CovarianceEvidence requires at least one referenced "
                "statistics record (a claim of PARTIAL/UNRESOLVED must still "
                "cite the underlying noise/residual evidence it is bounded by)"
            )
        _check_source_files_and_hashes(self.source_files, self.source_sha256, allow_empty=True)
        _check_limitations(self.limitations)


@dataclass(frozen=True, kw_only=True)
class EvidenceClaim:
    schema_version: str = SCHEMA_VERSION
    claim_id: str
    r1_state: str
    v19_state: str
    r2p0_state: str
    reason: str
    evidence_ids: "tuple[str, ...]"
    confidence: str
    limitations: "tuple[str, ...]" = ()

    def __post_init__(self):
        _check_schema_version(self.schema_version)
        if not is_non_empty_str(self.claim_id):
            raise EvidenceValidationError("claim_id must be a non-empty str")
        for name in ("r1_state", "v19_state"):
            if not is_non_empty_str(getattr(self, name)):
                raise EvidenceValidationError(f"{name} must be a non-empty str")
        validate_status(self.r2p0_state)
        if not is_non_empty_str(self.reason):
            raise EvidenceValidationError("reason must be a non-empty str")
        if type(self.evidence_ids) is not tuple:
            raise EvidenceValidationError("evidence_ids must be a tuple[str, ...]")
        _check_confidence(self.confidence)
        if self.r2p0_state == "VERIFIED" and not self.evidence_ids:
            raise EvidenceValidationError(
                f"claim {self.claim_id!r} is VERIFIED but cites no evidence_ids"
            )
        _check_limitations(self.limitations)


@dataclass(frozen=True, kw_only=True)
class PhysicalEvidenceBundleR2:
    schema_version: str = SCHEMA_VERSION
    generated_utc_injected: str
    sessions: "tuple[PhysicalSessionEvidence, ...]"
    time_domains: "tuple[SessionTimeDomain, ...]"
    dynamic_segments: "tuple[DynamicMotionSegment, ...]"
    stationary_segments: "tuple[StationarySegment, ...]"
    axis_observations: "tuple[AxisResponseObservation, ...]"
    yaw_observations: "tuple[YawResponseObservation, ...]"
    channel_comparison: ChannelComparisonEvidence
    imu_crosscheck: ImuCrosscheckEvidence
    reset_discontinuity: ResetDiscontinuityEvidence
    lidar_extrinsic: LidarExtrinsicEvidence
    stationary_noise_statistics: "tuple[StationaryNoiseStatistics, ...]"
    dynamic_residual_statistics: "tuple[DynamicResidualStatistics, ...]"
    covariance: CovarianceEvidence
    claims: "tuple[EvidenceClaim, ...]"
    limitations: "tuple[str, ...]" = ()

    def __post_init__(self):
        _check_schema_version(self.schema_version)
        if not is_non_empty_str(self.generated_utc_injected):
            raise EvidenceValidationError("generated_utc_injected must be a non-empty str")
        if len(self.sessions) != len(self.time_domains):
            # Not a strict 1:1 requirement in general, but P0A requires every
            # session to have an explicit time domain (closes finding F3).
            session_ids = {s.session_id for s in self.sessions}
            time_domain_ids = {t.session_id for t in self.time_domains}
            missing = session_ids - time_domain_ids
            if missing:
                raise EvidenceValidationError(
                    f"sessions without an explicit SessionTimeDomain: {sorted(missing)}"
                )
        known_evidence_ids = {s.evidence_id for s in self.sessions}
        known_evidence_ids |= {t.evidence_id for t in self.time_domains}
        known_evidence_ids |= {s.evidence_id for s in self.dynamic_segments}
        known_evidence_ids |= {s.evidence_id for s in self.stationary_segments}
        known_evidence_ids |= {o.evidence_id for o in self.axis_observations}
        known_evidence_ids |= {o.evidence_id for o in self.yaw_observations}
        known_evidence_ids |= {self.channel_comparison.evidence_id, self.imu_crosscheck.evidence_id,
                                self.reset_discontinuity.evidence_id, self.lidar_extrinsic.evidence_id,
                                self.covariance.evidence_id}
        known_evidence_ids |= {s.evidence_id for s in self.stationary_noise_statistics}
        known_evidence_ids |= {s.evidence_id for s in self.dynamic_residual_statistics}

        # status_by_evidence_id only covers record types that carry a
        # `status` field (sessions, time domains, and the singleton
        # evidence records); DynamicMotionSegment/StationarySegment use
        # `valid` instead and are intentionally excluded from this lookup --
        # a claim citing one of those is not semantically checked here.
        status_by_evidence_id = {s.evidence_id: s.status for s in self.sessions}
        status_by_evidence_id.update({t.evidence_id: t.status for t in self.time_domains})
        status_by_evidence_id.update({o.evidence_id: o.status for o in self.axis_observations})
        status_by_evidence_id.update({o.evidence_id: o.status for o in self.yaw_observations})
        status_by_evidence_id[self.channel_comparison.evidence_id] = self.channel_comparison.status
        status_by_evidence_id[self.imu_crosscheck.evidence_id] = self.imu_crosscheck.status
        status_by_evidence_id[self.reset_discontinuity.evidence_id] = self.reset_discontinuity.status
        status_by_evidence_id[self.lidar_extrinsic.evidence_id] = self.lidar_extrinsic.status
        status_by_evidence_id[self.covariance.evidence_id] = self.covariance.status

        for claim in self.claims:
            unknown = [e for e in claim.evidence_ids if e not in known_evidence_ids]
            if unknown:
                raise EvidenceValidationError(
                    f"claim {claim.claim_id!r} references unknown evidence_ids: {unknown}"
                )
            if claim.r2p0_state == "VERIFIED":
                unsupported = [
                    e for e in claim.evidence_ids
                    if e in status_by_evidence_id and status_by_evidence_id[e] != "VERIFIED"
                ]
                if unsupported:
                    raise EvidenceValidationError(
                        f"claim {claim.claim_id!r} is VERIFIED but cites evidence not "
                        f"itself VERIFIED: "
                        f"{[(e, status_by_evidence_id[e]) for e in unsupported]}"
                    )
        _check_limitations(self.limitations)
