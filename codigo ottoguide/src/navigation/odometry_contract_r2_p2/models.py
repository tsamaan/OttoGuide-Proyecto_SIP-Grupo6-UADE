"""Typed, pure models for the R2-P2 frame and covariance contract."""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import Enum
from typing import Optional


P2_SCHEMA_VERSION = "2.2.0-p2"


class ContractValidationError(ValueError):
    """Raised when a P2 model would weaken a fail-closed invariant."""


class ValidationContext(str, Enum):
    PHYSICAL_EVIDENCE = "PHYSICAL_EVIDENCE"
    OFFLINE_REPLAY = "OFFLINE_REPLAY"
    SIMULATION = "SIMULATION"
    STRUCTURAL_ONLY = "STRUCTURAL_ONLY"


class FrameClassification(str, Enum):
    CONFIGURED_NAME = "CONFIGURED_NAME"
    SOURCE_LABEL = "SOURCE_LABEL"
    PHYSICAL_EVIDENCE_REFERENCE = "PHYSICAL_EVIDENCE_REFERENCE"
    MAPPING_REFERENCE = "MAPPING_REFERENCE"
    OFFLINE_REPLAY_REFERENCE = "OFFLINE_REPLAY_REFERENCE"
    SIMULATION_MODEL_REFERENCE = "SIMULATION_MODEL_REFERENCE"
    SYNTHETIC_FIXTURE_ONLY = "SYNTHETIC_FIXTURE_ONLY"
    HISTORICAL_DOCUMENTATION = "HISTORICAL_DOCUMENTATION"
    ROS_OUTPUT_CANDIDATE = "ROS_OUTPUT_CANDIDATE"
    UNRESOLVED_ALIAS = "UNRESOLVED_ALIAS"


def _nonempty(value: object, label: str) -> str:
    if type(value) is not str or not value.strip():
        raise ContractValidationError(f"{label} must be a non-empty plain string")
    return value


def _portable_path(value: str, label: str) -> str:
    _nonempty(value, label)
    normalized = value.replace("\\", "/")
    if normalized.startswith("/") or ":" in normalized.split("/")[0]:
        raise ContractValidationError(f"{label} must be relative")
    if any(part in ("", ".", "..") for part in normalized.split("/")):
        raise ContractValidationError(f"{label} must be a normalized relative path")
    return normalized


def _finite_number(value: object, label: str, *, positive: bool = False) -> float:
    if type(value) not in (int, float):
        raise ContractValidationError(f"{label} must be a plain finite number")
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ContractValidationError(f"{label} must be finite") from exc
    if not math.isfinite(number):
        raise ContractValidationError(f"{label} must be finite")
    if positive and number <= 0.0:
        raise ContractValidationError(f"{label} must be greater than zero")
    return number


@dataclass(frozen=True, kw_only=True)
class ProvenanceRef:
    source_id: str
    relative_path: str
    validation_context: ValidationContext
    claim_strength: str
    sha256: Optional[str] = None
    limitations: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _nonempty(self.source_id, "source_id")
        _portable_path(self.relative_path, "relative_path")
        _nonempty(self.claim_strength, "claim_strength")
        if self.sha256 is not None:
            if (
                type(self.sha256) is not str
                or len(self.sha256) != 64
                or self.sha256.lower() != self.sha256
                or any(ch not in "0123456789abcdef" for ch in self.sha256)
            ):
                raise ContractValidationError("sha256 must be lowercase hexadecimal")
        if type(self.limitations) is not tuple or any(
            type(item) is not str or not item.strip() for item in self.limitations
        ):
            raise ContractValidationError("limitations must be non-empty strings")


@dataclass(frozen=True, kw_only=True)
class FrameSemanticsContract:
    source_frame_label: str
    configured_parent_frame_name: str
    configured_child_frame_name: str
    configured_sensor_frame_name: str
    source_frame_semantics_status: str
    child_frame_semantics_status: str
    transform_direction_status: str
    axis_convention_status: str
    handedness_status: str
    translation_unit_status: str
    yaw_unit_status: str
    translation_scale_status: str
    yaw_scale_status: str
    origin_policy: str
    reset_policy: str
    boot_domain_policy: str
    time_domain_policy: str
    source_channel_status: str
    validation_context: ValidationContext
    provenance: tuple[ProvenanceRef, ...]

    def __post_init__(self) -> None:
        names = (
            self.source_frame_label,
            self.configured_parent_frame_name,
            self.configured_child_frame_name,
            self.configured_sensor_frame_name,
        )
        for index, value in enumerate(names):
            _nonempty(value, f"frame_name[{index}]")
        if len(set(names)) != len(names):
            raise ContractValidationError("source, parent, child, and sensor names must differ")
        for label in (
            "source_frame_semantics_status",
            "child_frame_semantics_status",
            "transform_direction_status",
            "axis_convention_status",
            "handedness_status",
            "translation_unit_status",
            "yaw_unit_status",
            "translation_scale_status",
            "yaw_scale_status",
            "origin_policy",
            "reset_policy",
            "boot_domain_policy",
            "time_domain_policy",
            "source_channel_status",
        ):
            _nonempty(getattr(self, label), label)
        if not self.provenance:
            raise ContractValidationError("frame contract requires provenance")
        if any(
            item.validation_context is not self.validation_context
            for item in self.provenance
        ):
            raise ContractValidationError("provenance context must match frame contract context")
        if self.validation_context is ValidationContext.PHYSICAL_EVIDENCE:
            if self.source_frame_semantics_status not in ("PARTIAL", "UNRESOLVED"):
                raise ContractValidationError(
                    "physical source frame semantics cannot exceed PARTIAL"
                )
            ceilings = {
                "child_frame_semantics_status": "UNRESOLVED",
                "translation_scale_status": "UNRESOLVED",
                "yaw_scale_status": "UNRESOLVED",
                "source_channel_status": "UNRESOLVED",
                "time_domain_policy": "UNRESOLVED_FOR_ROS_HEADER",
                "boot_domain_policy": "PER_BOOT_NO_CROSS_BOOT_CONCATENATION",
            }
            for field_name, expected in ceilings.items():
                if getattr(self, field_name) != expected:
                    raise ContractValidationError(
                        f"physical {field_name} must remain {expected}"
                    )


@dataclass(frozen=True, kw_only=True)
class FrameVocabularyEntry:
    frame: str
    classifications: tuple[FrameClassification, ...]
    paths: tuple[str, ...]
    source: str
    validation_context: ValidationContext
    claim_strength: str
    provenance: tuple[ProvenanceRef, ...]
    limitations: tuple[str, ...]

    def __post_init__(self) -> None:
        _nonempty(self.frame, "frame")
        if not self.classifications or len(set(self.classifications)) != len(
            self.classifications
        ):
            raise ContractValidationError("classifications must be non-empty and unique")
        if not self.paths:
            raise ContractValidationError("vocabulary entry requires paths")
        for path in self.paths:
            _portable_path(path, "paths")
        _nonempty(self.source, "source")
        _nonempty(self.claim_strength, "claim_strength")
        if not self.provenance:
            raise ContractValidationError("vocabulary entry requires provenance")


@dataclass(frozen=True, kw_only=True)
class AxisStatistic:
    axis: str
    stddev_source_units: Optional[float]
    mad_source_units: Optional[float]
    p95_deviation_source_units: Optional[float]

    def __post_init__(self) -> None:
        _nonempty(self.axis, "axis")
        for label in (
            "stddev_source_units",
            "mad_source_units",
            "p95_deviation_source_units",
        ):
            value = getattr(self, label)
            if value is not None:
                _finite_number(value, label)
                if value < 0:
                    raise ContractValidationError(f"{label} cannot be negative")


def validate_covariance_matrix(matrix: tuple[float, ...], *, size: int = 6) -> None:
    if type(matrix) is not tuple or len(matrix) != size * size:
        raise ContractValidationError(f"covariance matrix must have {size * size} entries")
    values = tuple(_finite_number(v, "covariance entry") for v in matrix)
    tolerance = 1e-12
    for row in range(size):
        if values[row * size + row] < 0.0:
            raise ContractValidationError("covariance diagonal cannot be negative")
        for column in range(size):
            if abs(values[row * size + column] - values[column * size + row]) > tolerance:
                raise ContractValidationError("covariance matrix must be symmetric")
    # Cholesky-style PSD check that also handles exact zero pivots.
    lower = [[0.0 for _ in range(size)] for _ in range(size)]
    for row in range(size):
        for column in range(row + 1):
            residual = values[row * size + column] - sum(
                lower[row][k] * lower[column][k] for k in range(column)
            )
            if row == column:
                if residual < -tolerance:
                    raise ContractValidationError("covariance matrix must be PSD")
                lower[row][column] = math.sqrt(max(0.0, residual))
            elif lower[column][column] > tolerance:
                lower[row][column] = residual / lower[column][column]
            elif abs(residual) > tolerance:
                raise ContractValidationError("covariance matrix must be PSD")


@dataclass(frozen=True, kw_only=True)
class CovarianceEvidence:
    channel: str
    session: str
    units: str
    si_conversion_status: str
    supported_axes: tuple[str, ...]
    unsupported_axes: tuple[str, ...]
    stationary_statistics: tuple[AxisStatistic, ...]
    dynamic_residuals: tuple[float, ...]
    yaw_speed_residual_rad_s: Optional[float]
    sample_count: int
    exposure_s: Optional[float]
    diagonal_candidates_source_unit_squared: tuple[Optional[float], ...]
    off_diagonal_status: str
    symmetry_status: str
    psd_status: str
    validation_context: ValidationContext
    provenance: tuple[ProvenanceRef, ...]
    publication_ready: bool
    blockers: tuple[str, ...]
    ros_si_matrix: Optional[tuple[float, ...]] = None

    def __post_init__(self) -> None:
        _nonempty(self.channel, "channel")
        _nonempty(self.session, "session")
        _nonempty(self.units, "units")
        _nonempty(self.si_conversion_status, "si_conversion_status")
        if type(self.sample_count) is not int or self.sample_count < 0:
            raise ContractValidationError("sample_count must be a non-negative integer")
        if self.exposure_s is not None:
            _finite_number(self.exposure_s, "exposure_s")
            if self.exposure_s < 0:
                raise ContractValidationError("exposure_s cannot be negative")
        if len(self.diagonal_candidates_source_unit_squared) != 6:
            raise ContractValidationError("diagonal candidates must contain six axes")
        for value in self.diagonal_candidates_source_unit_squared:
            if value is not None:
                _finite_number(value, "diagonal candidate", positive=True)
        for value in self.dynamic_residuals:
            _finite_number(value, "dynamic residual")
        if self.yaw_speed_residual_rad_s is not None:
            _finite_number(self.yaw_speed_residual_rad_s, "yaw_speed_residual_rad_s")
        if type(self.publication_ready) is not bool:
            raise ContractValidationError("publication_ready must be bool")
        if self.validation_context is ValidationContext.PHYSICAL_EVIDENCE:
            if self.units != "SOURCE_UNITS_UNRESOLVED":
                raise ContractValidationError("physical source units cannot be promoted to SI")
            if self.ros_si_matrix is not None or self.publication_ready:
                raise ContractValidationError("physical covariance cannot be publication ready")
        if self.ros_si_matrix is not None:
            validate_covariance_matrix(self.ros_si_matrix)


@dataclass(frozen=True, kw_only=True)
class ReadinessContract:
    p2_contract_structurally_ready: bool
    offline_replay_contract_ready: bool
    simulation_contract_ready: bool
    physical_odom_publication_ready: bool
    physical_tf_publication_ready: bool
    simulated_odom_publication_ready: bool
    simulated_tf_publication_ready: bool
    nav2_simulation_readiness: bool
    blockers: tuple[str, ...]

    def __post_init__(self) -> None:
        for field_name in self.__dataclass_fields__:
            if field_name == "blockers":
                continue
            if type(getattr(self, field_name)) is not bool:
                raise ContractValidationError(f"{field_name} must be bool")
        if self.physical_odom_publication_ready or self.physical_tf_publication_ready:
            raise ContractValidationError("P2 cannot authorize physical publication")
        if self.simulated_odom_publication_ready or self.simulated_tf_publication_ready:
            raise ContractValidationError("simulated publication is deferred to P3")
        if self.nav2_simulation_readiness:
            raise ContractValidationError("Nav2 simulation readiness is deferred")
        if not self.blockers:
            raise ContractValidationError("readiness requires explicit blockers")
