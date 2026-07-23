"""Covariance evidence extraction without SI or publication promotion."""

from __future__ import annotations

from typing import Mapping, Sequence

from .models import (
    AxisStatistic,
    ContractValidationError,
    CovarianceEvidence,
    ProvenanceRef,
    ValidationContext,
)


PHYSICAL_COVARIANCE_BLOCKERS = (
    "AUTHORITATIVE_SOURCE_CHANNEL_UNRESOLVED",
    "TRANSLATION_SCALE_UNRESOLVED",
    "YAW_SCALE_UNRESOLVED",
    "COVARIANCE_SI_CONVERSION_UNAVAILABLE",
    "COVARIANCE_OFF_DIAGONALS_UNRESOLVED",
    "NO_NEW_HARDWARE_ACCESS",
)


def _plain_nonnegative(value: object) -> float | None:
    if type(value) not in (int, float):
        return None
    number = float(value)
    if number < 0.0:
        return None
    return number


def _vector(record: Mapping[str, object], name: str) -> tuple[float | None, ...]:
    value = record.get(name)
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        return (None, None, None)
    result = tuple(_plain_nonnegative(item) for item in value)
    if len(result) != 3:
        return (None, None, None)
    return result


def build_physical_source_unit_evidence(
    p1a_document: Mapping[str, object],
) -> tuple[CovarianceEvidence, ...]:
    p1_bundle = p1a_document.get("p1_bundle")
    if not isinstance(p1_bundle, Mapping):
        raise ContractValidationError("p1a input must contain p1_bundle")
    stationary = p1_bundle.get("stationary")
    if not isinstance(stationary, Sequence) or isinstance(stationary, (str, bytes)):
        raise ContractValidationError("p1a input must contain stationary records")
    dynamic = p1_bundle.get("dynamic_residuals")
    dynamic_records = dynamic if isinstance(dynamic, Sequence) else ()
    yaw_records = p1a_document.get("yaw_speed_residuals")
    yaw_records = yaw_records if isinstance(yaw_records, Sequence) else ()
    output = []
    for item in stationary:
        if not isinstance(item, Mapping):
            raise ContractValidationError("stationary record must be an object")
        channel = item.get("channel")
        session = item.get("session_id")
        if type(channel) is not str or type(session) is not str:
            raise ContractValidationError("stationary channel/session must be strings")
        stddev = _vector(item, "stddev")
        mad = _vector(item, "mad")
        p95 = _vector(item, "p95_deviation")
        axes = tuple(
            AxisStatistic(
                axis=axis,
                stddev_source_units=stddev[index],
                mad_source_units=mad[index],
                p95_deviation_source_units=p95[index],
            )
            for index, axis in enumerate(("x", "y", "z"))
        )
        variances = tuple(
            None if value is None or value == 0.0 else value * value for value in stddev
        )
        residuals = tuple(
            float(record["residual_value"])
            for record in dynamic_records
            if isinstance(record, Mapping)
            and record.get("session_id") == session
            and record.get("channel") in (channel, "BOTH")
            and type(record.get("residual_value")) in (int, float)
        )
        yaw_values = tuple(
            float(record["yaw_speed_rmse_rad_s"])
            for record in yaw_records
            if isinstance(record, Mapping)
            and record.get("session_id") == session
            and type(record.get("yaw_speed_rmse_rad_s")) in (int, float)
        )
        sample_count = item.get("sample_count")
        exposure = item.get("duration_s")
        output.append(
            CovarianceEvidence(
                channel=channel,
                session=session,
                units="SOURCE_UNITS_UNRESOLVED",
                si_conversion_status="UNAVAILABLE_TRANSLATION_SCALE_UNRESOLVED",
                supported_axes=("x", "y", "z", "yaw_speed"),
                unsupported_axes=("roll_pose", "pitch_pose", "yaw_pose", "off_diagonal"),
                stationary_statistics=axes,
                dynamic_residuals=residuals,
                yaw_speed_residual_rad_s=max(yaw_values) if yaw_values else None,
                sample_count=sample_count if type(sample_count) is int else 0,
                exposure_s=float(exposure) if type(exposure) in (int, float) else None,
                diagonal_candidates_source_unit_squared=(
                    variances[0],
                    variances[1],
                    variances[2],
                    None,
                    None,
                    None,
                ),
                off_diagonal_status="UNRESOLVED_NOT_ASSUMED_ZERO",
                symmetry_status="NO_MATRIX",
                psd_status="NO_MATRIX",
                validation_context=ValidationContext.PHYSICAL_EVIDENCE,
                provenance=(
                    ProvenanceRef(
                        source_id=f"p1a-stationary-{session}-{channel}",
                        relative_path="inputs/R2_P1A_RESULT.json",
                        validation_context=ValidationContext.PHYSICAL_EVIDENCE,
                        claim_strength="PARTIAL_QUANTIFIED_SOURCE_UNITS",
                        limitations=(
                            "Upstream labels are not promoted to SI.",
                            "Stationary dispersion is not a publishable covariance matrix.",
                        ),
                    ),
                ),
                publication_ready=False,
                blockers=PHYSICAL_COVARIANCE_BLOCKERS,
                ros_si_matrix=None,
            )
        )
    if not output:
        raise ContractValidationError("p1a input produced no covariance evidence")
    return tuple(output)


def covariance_context_contracts() -> dict[str, object]:
    return {
        "PHYSICAL_SOURCE_UNIT_EVIDENCE": {
            "validation_context": "PHYSICAL_EVIDENCE",
            "status": "PARTIAL_QUANTIFIED",
            "units": "SOURCE_UNITS_UNRESOLVED",
            "ros_si_matrix": None,
            "publication_ready": False,
        },
        "OFFLINE_REPLAY_COVARIANCE_POLICY": {
            "validation_context": "OFFLINE_REPLAY",
            "policy": "PRESERVE_SOURCE_UNIT_EVIDENCE_NO_SI_PUBLICATION",
            "unknown_value": None,
            "channel_selection": "EXPLICIT_REQUIRED",
            "structurally_ready": True,
        },
        "SIMULATION_COVARIANCE_POLICY": {
            "validation_context": "SIMULATION",
            "simulation_only": True,
            "physical_validation_claim": False,
            "units": "SI_BY_SIMULATION_MODEL_ONLY",
            "supported_axes": ["x", "y", "yaw"],
            "parameters_required": [
                "position_variance_m2",
                "yaw_variance_rad2",
                "linear_velocity_variance_m2_s2",
                "yaw_rate_variance_rad2_s2",
            ],
            "zero_off_diagonal_policy": "ONLY_IF_SIMULATOR_MODEL_DECLARES_INDEPENDENCE",
            "structurally_ready": True,
        },
        "ROS_SI_PUBLICATION_CANDIDATE": {
            "validation_context": "STRUCTURAL_ONLY",
            "matrix": None,
            "ready": False,
            "blockers": list(PHYSICAL_COVARIANCE_BLOCKERS),
        },
    }
