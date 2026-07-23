"""Strict models and primitive validators for the R2-P2A contract."""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from enum import Enum
from pathlib import PurePosixPath
from typing import Optional


P2A_SCHEMA_VERSION = "2.2.1-p2a"
P1A_SCHEMA_VERSION = "2.1.1-p1a"
MAPPING_SCHEMA_VERSION = "1.0.0-p2a-mapping"
KNOWN_P1A_SHA256 = "165470ed00ebf69b6b682172c17a7eb9b3b4faf018aaebe21b3f7a1b3d027256"
CHANNELS = ("rt/odommodestate", "rt/lf/odommodestate")
RFC3339_UTC = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z$")
MAX_SIGNED_64 = (1 << 63) - 1


class ContractValidationError(ValueError):
    """A material input or claim violates a P2A invariant."""


class ValidationContext(str, Enum):
    PHYSICAL_EVIDENCE = "PHYSICAL_EVIDENCE"
    OFFLINE_REPLAY = "OFFLINE_REPLAY"
    SIMULATION_POLICY = "SIMULATION_POLICY"
    STRUCTURAL_ONLY = "STRUCTURAL_ONLY"


class FrameClassification(str, Enum):
    CONFIGURED_NAME = "CONFIGURED_NAME"
    OBSERVED_SOURCE_LABEL = "OBSERVED_SOURCE_LABEL"
    MAPPING_REFERENCE = "MAPPING_REFERENCE"
    ROS_OUTPUT_CANDIDATE = "ROS_OUTPUT_CANDIDATE"
    UNRESOLVED_ALIAS = "UNRESOLVED_ALIAS"


class SemanticStatus(str, Enum):
    PARTIAL = "PARTIAL"
    UNRESOLVED = "UNRESOLVED"
    CONFIGURED_NAME_ONLY = "CONFIGURED_NAME_ONLY"
    REPLAY_POLICY_CANDIDATE = "REPLAY_POLICY_CANDIDATE"
    SIMULATION_POLICY_CANDIDATE = "SIMULATION_POLICY_CANDIDATE"
    MODEL_NOT_SELECTED = "MODEL_NOT_SELECTED"
    AXES_NOT_BOUND = "AXES_NOT_BOUND"


class ScaleStatus(str, Enum):
    UNRESOLVED = "UNRESOLVED"
    SOURCE_UNITS_ONLY = "SOURCE_UNITS_ONLY"
    SCALE_DEFINED_BY_FUTURE_MODEL = "SCALE_DEFINED_BY_FUTURE_MODEL"


class UnitStatus(str, Enum):
    SOURCE_UNITS_UNRESOLVED = "SOURCE_UNITS_UNRESOLVED"
    YAW_SPEED_RAD_S_ONLY = "YAW_SPEED_RAD_S_ONLY"
    UNITS_DEFINED_BY_FUTURE_MODEL = "UNITS_DEFINED_BY_FUTURE_MODEL"


class TimeDomainPolicy(str, Enum):
    UNRESOLVED_FOR_ROS_HEADER = "UNRESOLVED_FOR_ROS_HEADER"
    PRESERVE_RECORDED_ORDER_NO_ROS_STAMP = "PRESERVE_RECORDED_ORDER_NO_ROS_STAMP"
    CLOCK_DEFERRED_TO_P3 = "CLOCK_DEFERRED_TO_P3"


class BootDomainPolicy(str, Enum):
    PER_BOOT_NO_CROSS_BOOT_CONCATENATION = "PER_BOOT_NO_CROSS_BOOT_CONCATENATION"
    REPLAY_SESSION_ONLY = "REPLAY_SESSION_ONLY"
    SIMULATION_EPISODE_ONLY = "SIMULATION_EPISODE_ONLY"


class SourceChannelStatus(str, Enum):
    UNRESOLVED = "UNRESOLVED"
    EXPLICIT_INPUT_REQUIRED = "EXPLICIT_INPUT_REQUIRED"
    FUTURE_MODEL_SOURCE = "FUTURE_MODEL_SOURCE"


class ReadinessStage(str, Enum):
    STRUCTURALLY_READY = "STRUCTURALLY_READY"
    NOT_IMPLEMENTED = "NOT_IMPLEMENTED"
    NOT_VALIDATED = "NOT_VALIDATED"
    BLOCKED = "BLOCKED"


class CovarianceDomain(str, Enum):
    POSE_POSITION_SOURCE_DISPERSION = "POSE_POSITION_SOURCE_DISPERSION"
    POSE_ORIENTATION_UNAVAILABLE = "POSE_ORIENTATION_UNAVAILABLE"
    TWIST_LINEAR_RESIDUAL = "TWIST_LINEAR_RESIDUAL"
    TWIST_ANGULAR_YAW_RATE_RESIDUAL = "TWIST_ANGULAR_YAW_RATE_RESIDUAL"
    CROSS_CHANNEL_RESIDUAL = "CROSS_CHANNEL_RESIDUAL"


class CovarianceEvidenceKind(str, Enum):
    MEASURED_SOURCE_STATISTIC = "MEASURED_SOURCE_STATISTIC"
    MEASURED_ZERO_SOURCE_VARIANCE = "MEASURED_ZERO_SOURCE_VARIANCE"
    UNAVAILABLE = "UNAVAILABLE"
    CROSS_CHANNEL_DIAGNOSTIC = "CROSS_CHANNEL_DIAGNOSTIC"


class ClaimStrength(str, Enum):
    PRESERVED_PHYSICAL_EVIDENCE = "PRESERVED_PHYSICAL_EVIDENCE"
    PARTIAL_QUANTIFIED = "PARTIAL_QUANTIFIED"
    PRESERVED_MAPPING_REFERENCE = "PRESERVED_MAPPING_REFERENCE"
    DERIVED_MAPPING_REFERENCE = "DERIVED_MAPPING_REFERENCE"
    STRUCTURAL_POLICY = "STRUCTURAL_POLICY"


class PublicationStatus(str, Enum):
    NOT_PUBLICATION_READY = "NOT_PUBLICATION_READY"
    WITHHELD_BY_P2A_BOUNDARY = "WITHHELD_BY_P2A_BOUNDARY"


class PathKind(str, Enum):
    LOGICAL_OUTPUT_PATH = "LOGICAL_OUTPUT_PATH"
    EXTERNAL_INPUT_MANIFEST_PATH = "EXTERNAL_INPUT_MANIFEST_PATH"
    VERSIONED_REPOSITORY_PATH = "VERSIONED_REPOSITORY_PATH"


def exact_enum(value: object, enum_type: type[Enum], label: str) -> None:
    if type(value) is not enum_type:
        raise ContractValidationError(f"{label} must be exact {enum_type.__name__}")


def canonical_string(value: object, label: str) -> str:
    if type(value) is not str or not value:
        raise ContractValidationError(f"{label} must be a non-empty plain string")
    if value != value.strip() or "\x00" in value:
        raise ContractValidationError(f"{label} must use canonical whitespace and no NUL")
    if any(ord(char) < 32 or ord(char) == 127 for char in value):
        raise ContractValidationError(f"{label} contains a control character")
    return value


def logical_path(value: object, label: str) -> str:
    path = canonical_string(value, label)
    if "\\" in path or path.startswith("/") or ":" in path.split("/")[0]:
        raise ContractValidationError(f"{label} must be a relative POSIX path")
    parts = path.split("/")
    if any(part in ("", ".", "..") for part in parts):
        raise ContractValidationError(f"{label} contains an unsafe path segment")
    if PurePosixPath(path).as_posix() != path:
        raise ContractValidationError(f"{label} is not canonical")
    return path


def sha256_string(value: object, label: str) -> str:
    if type(value) is not str or not value:
        raise ContractValidationError(f"{label} must be lowercase SHA-256")
    digest = canonical_string(value, label)
    if len(digest) != 64 or digest.lower() != digest:
        raise ContractValidationError(f"{label} must be lowercase SHA-256")
    if any(char not in "0123456789abcdef" for char in digest):
        raise ContractValidationError(f"{label} must be lowercase SHA-256")
    return digest


def finite_number(
    value: object,
    label: str,
    *,
    nonnegative: bool = False,
    positive: bool = False,
) -> float:
    if type(value) not in (int, float):
        raise ContractValidationError(f"{label} must be a plain number")
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ContractValidationError(f"{label} must be representable") from exc
    if not math.isfinite(number):
        raise ContractValidationError(f"{label} must be finite")
    if nonnegative and number < 0.0:
        raise ContractValidationError(f"{label} must be non-negative")
    if positive and number <= 0.0:
        raise ContractValidationError(f"{label} must be positive")
    return number


def positive_int(value: object, label: str) -> int:
    if type(value) is not int or value < 1 or value > MAX_SIGNED_64:
        raise ContractValidationError(
            f"{label} must be a positive signed-64 plain integer"
        )
    return value


def exact_string_tuple(value: object, label: str, *, allow_empty: bool = False) -> tuple[str, ...]:
    if type(value) is not tuple:
        raise ContractValidationError(f"{label} must be an exact tuple")
    if not allow_empty and not value:
        raise ContractValidationError(f"{label} must not be empty")
    result = tuple(canonical_string(item, f"{label}[]") for item in value)
    if len(set(result)) != len(result):
        raise ContractValidationError(f"{label} must be unique")
    return result


@dataclass(frozen=True, kw_only=True)
class ProvenanceRef:
    source_id: str
    schema: str
    sha256: str
    relative_logical_path: str
    path_kind: PathKind
    validation_context: ValidationContext
    claim_strength: ClaimStrength
    limitations: tuple[str, ...]

    def __post_init__(self) -> None:
        canonical_string(self.source_id, "source_id")
        canonical_string(self.schema, "schema")
        sha256_string(self.sha256, "sha256")
        logical_path(self.relative_logical_path, "relative_logical_path")
        exact_enum(self.path_kind, PathKind, "path_kind")
        exact_enum(self.validation_context, ValidationContext, "validation_context")
        exact_enum(self.claim_strength, ClaimStrength, "claim_strength")
        exact_string_tuple(self.limitations, "limitations")


@dataclass(frozen=True, kw_only=True)
class FrameContract:
    contract_id: str
    validation_context: ValidationContext
    source_semantics: SemanticStatus
    child_semantics: SemanticStatus
    translation_scale: ScaleStatus
    yaw_scale: ScaleStatus
    translation_units: UnitStatus
    yaw_units: UnitStatus
    time_policy: TimeDomainPolicy
    boot_policy: BootDomainPolicy
    source_channel: SourceChannelStatus
    classifications: tuple[FrameClassification, ...]
    provenance: tuple[ProvenanceRef, ...]
    blockers: tuple[str, ...]

    def __post_init__(self) -> None:
        canonical_string(self.contract_id, "contract_id")
        exact_enum(self.validation_context, ValidationContext, "validation_context")
        exact_enum(self.source_semantics, SemanticStatus, "source_semantics")
        exact_enum(self.child_semantics, SemanticStatus, "child_semantics")
        exact_enum(self.translation_scale, ScaleStatus, "translation_scale")
        exact_enum(self.yaw_scale, ScaleStatus, "yaw_scale")
        exact_enum(self.translation_units, UnitStatus, "translation_units")
        exact_enum(self.yaw_units, UnitStatus, "yaw_units")
        exact_enum(self.time_policy, TimeDomainPolicy, "time_policy")
        exact_enum(self.boot_policy, BootDomainPolicy, "boot_policy")
        exact_enum(self.source_channel, SourceChannelStatus, "source_channel")
        if type(self.classifications) is not tuple or not self.classifications:
            raise ContractValidationError("classifications must be a non-empty exact tuple")
        if any(type(item) is not FrameClassification for item in self.classifications):
            raise ContractValidationError("classification enum bypass")
        if len(set(self.classifications)) != len(self.classifications):
            raise ContractValidationError("classifications must be unique")
        if type(self.provenance) is not tuple or not self.provenance:
            raise ContractValidationError("frame contract requires provenance")
        if any(type(item) is not ProvenanceRef for item in self.provenance):
            raise ContractValidationError("frame provenance must be exact")
        if any(item.validation_context is not self.validation_context for item in self.provenance):
            raise ContractValidationError("frame provenance context mismatch")
        exact_string_tuple(self.blockers, "blockers")


@dataclass(frozen=True, kw_only=True)
class CovarianceRecord:
    evidence_id: str
    domain: CovarianceDomain
    evidence_kind: CovarianceEvidenceKind
    validation_context: ValidationContext
    channel: str
    session_id: str
    segment_id: str
    unit: str
    sample_count: int
    exposure_s: Optional[float]
    supported_axes: tuple[str, ...]
    unsupported_axes: tuple[str, ...]
    source_values: tuple[Optional[float], ...]
    variance_candidates: tuple[Optional[float], ...]
    status: str
    provenance: tuple[ProvenanceRef, ...]
    blockers: tuple[str, ...]
    publication_status: PublicationStatus
    ros_si_matrix: None = None

    def __post_init__(self) -> None:
        canonical_string(self.evidence_id, "evidence_id")
        exact_enum(self.domain, CovarianceDomain, "domain")
        exact_enum(self.evidence_kind, CovarianceEvidenceKind, "evidence_kind")
        exact_enum(self.validation_context, ValidationContext, "validation_context")
        if self.channel not in CHANNELS + ("CROSS_CHANNEL", "NOT_APPLICABLE"):
            raise ContractValidationError("unknown covariance channel")
        canonical_string(self.session_id, "session_id")
        canonical_string(self.segment_id, "segment_id")
        canonical_string(self.unit, "unit")
        positive_int(self.sample_count, "sample_count")
        if self.exposure_s is not None:
            finite_number(self.exposure_s, "exposure_s", positive=True)
        supported = exact_string_tuple(self.supported_axes, "supported_axes", allow_empty=True)
        unsupported = exact_string_tuple(
            self.unsupported_axes, "unsupported_axes", allow_empty=True
        )
        if set(supported) & set(unsupported):
            raise ContractValidationError("supported and unsupported axes overlap")
        if type(self.source_values) is not tuple or type(self.variance_candidates) is not tuple:
            raise ContractValidationError("covariance values must be exact tuples")
        for label, values in (
            ("source_values", self.source_values),
            ("variance_candidates", self.variance_candidates),
        ):
            for value in values:
                if value is not None:
                    finite_number(value, label, nonnegative=True)
        canonical_string(self.status, "status")
        if type(self.provenance) is not tuple or not self.provenance:
            raise ContractValidationError("covariance record requires provenance")
        if any(type(item) is not ProvenanceRef for item in self.provenance):
            raise ContractValidationError("covariance provenance must be exact")
        exact_string_tuple(self.blockers, "blockers")
        exact_enum(self.publication_status, PublicationStatus, "publication_status")
        if self.validation_context is ValidationContext.PHYSICAL_EVIDENCE:
            if self.ros_si_matrix is not None:
                raise ContractValidationError("physical evidence cannot contain an SI matrix")
            if self.publication_status is not PublicationStatus.NOT_PUBLICATION_READY:
                raise ContractValidationError("physical evidence cannot be publication ready")


@dataclass(frozen=True, kw_only=True)
class ValidatedInput:
    source_id: str
    schema: str
    sha256: str
    logical_path: str
    validation_context: ValidationContext
    claim_strength: ClaimStrength
    limitations: tuple[str, ...]

    def __post_init__(self) -> None:
        canonical_string(self.source_id, "source_id")
        canonical_string(self.schema, "schema")
        sha256_string(self.sha256, "sha256")
        logical_path(self.logical_path, "logical_path")
        exact_enum(self.validation_context, ValidationContext, "validation_context")
        exact_enum(self.claim_strength, ClaimStrength, "claim_strength")
        exact_string_tuple(self.limitations, "limitations")


@dataclass(frozen=True, kw_only=True)
class ReadinessContract:
    p2a_contract_structurally_ready: bool
    offline_replay_policy_structurally_ready: bool
    simulation_policy_structurally_ready: bool
    physical_odom_publication_ready: bool
    physical_tf_publication_ready: bool
    offline_replay_adapter_ready: bool
    offline_replay_execution_validated: bool
    simulation_model_bound: bool
    simulation_adapter_ready: bool
    simulation_execution_ready: bool
    nav2_simulation_ready: bool
    blockers: tuple[str, ...]

    def __post_init__(self) -> None:
        for name in self.__dataclass_fields__:
            if name == "blockers":
                continue
            if type(getattr(self, name)) is not bool:
                raise ContractValidationError(f"{name} must be bool")
        if (
            self.physical_odom_publication_ready
            or self.physical_tf_publication_ready
            or self.offline_replay_adapter_ready
            or self.offline_replay_execution_validated
            or self.simulation_model_bound
            or self.simulation_adapter_ready
            or self.simulation_execution_ready
            or self.nav2_simulation_ready
        ):
            raise ContractValidationError("P2A cannot claim implementation or execution readiness")
        exact_string_tuple(self.blockers, "blockers")
