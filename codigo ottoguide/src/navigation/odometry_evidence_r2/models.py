"""Typed, immutable, fail-closed data model for ODOM/TF R2-P0 physical
evidence ingestion.

Separate from odometry_candidate_adapter (R1): R1's OdometryCandidate is left
untouched and remains the R1 baseline/regression contract. Nothing here
imports rclpy, nav_msgs, geometry_msgs, tf2_ros, cyclonedds, unitree_sdk2py,
socket, requests, or httpx, and nothing here performs network or live-SDK
I/O. Every dataclass is frozen (immutable) and every field is validated by
`validation.py` / `ingest.py` before construction -- these classes hold only
already-canonical values.

SCHEMA_VERSION follows this package, not R1's.
"""
from dataclasses import dataclass, field

SCHEMA_VERSION = "2.0.0-p0"


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
    valid: bool
    invalid_reason: "str | None"
    delta_position: "tuple[float, float, float] | None"
    integrated_yaw_speed_rad: "float | None"
    sample_count: "int | None"
    duration_s: "float | None"
    source_files: "tuple[str, ...]"
    source_sha256: "tuple[str, ...]"
    limitations: "tuple[str, ...]" = ()


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


@dataclass(frozen=True, kw_only=True)
class AxisResponseObservation:
    schema_version: str = SCHEMA_VERSION
    evidence_id: str
    status: str
    axis: str
    dominant: bool
    evidence_segment_ids: "tuple[str, ...]"
    limitations: "tuple[str, ...]" = ()


@dataclass(frozen=True, kw_only=True)
class YawResponseObservation:
    schema_version: str = SCHEMA_VERSION
    evidence_id: str
    status: str
    sign_candidate: str
    evidence_segment_ids: "tuple[str, ...]"
    limitations: "tuple[str, ...]" = ()


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
        if self.authoritative_source_channel is not None:
            raise ValueError(
                "authoritative_source_channel must remain null in R2-P0"
            )


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
        if self.trajectory_concatenation_permitted:
            raise ValueError(
                "trajectory_concatenation_permitted must be false: R3C and R4 "
                "belong to different boot domains and must never be treated "
                "as one continuous trajectory"
            )
        if self.from_boot_id == self.to_boot_id:
            raise ValueError(
                "ResetDiscontinuityEvidence requires two distinct boot_id values"
            )


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


@dataclass(frozen=True, kw_only=True)
class StationaryNoiseStatistics:
    schema_version: str = SCHEMA_VERSION
    evidence_id: str
    session_id: str
    channel: str
    sample_count: int
    window_description: str
    mean: "tuple[float, ...]"
    variance: "tuple[float, ...]"
    stddev: "tuple[float, ...]"
    robust_method: str
    outlier_rule: str
    source_files: "tuple[str, ...]"
    source_sha256: "tuple[str, ...]"
    limitations: "tuple[str, ...]" = ()


@dataclass(frozen=True, kw_only=True)
class DynamicResidualStatistics:
    schema_version: str = SCHEMA_VERSION
    evidence_id: str
    session_id: str
    channel: str
    segment_id: str
    sample_count: int
    reported_translation_norm: "float | None"
    integrated_yaw_speed_rad: "float | None"
    source_files: "tuple[str, ...]"
    source_sha256: "tuple[str, ...]"
    limitations: "tuple[str, ...]" = ()


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
        if self.publication_model_ready:
            raise ValueError(
                "CovarianceEvidence.publication_model_ready must be false in "
                "R2-P0 -- no covariance value may be invented or promoted"
            )
        if not self.stationary_stats_ids and not self.dynamic_stats_ids:
            raise ValueError(
                "CovarianceEvidence requires at least one referenced "
                "statistics record (a claim of PARTIAL/UNRESOLVED must still "
                "cite the underlying noise/residual evidence it is bounded by)"
            )


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
        if self.r2p0_state == "VERIFIED" and not self.evidence_ids:
            raise ValueError(
                f"claim {self.claim_id!r} is VERIFIED but cites no evidence_ids"
            )


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
