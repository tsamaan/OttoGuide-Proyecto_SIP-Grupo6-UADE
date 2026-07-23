"""P2A frame, covariance and object-derived readiness construction."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

from .inputs import MappingBinding, P1AValidation
from .models import (
    CHANNELS,
    P2A_SCHEMA_VERSION,
    BootDomainPolicy,
    ClaimStrength,
    ContractValidationError,
    CovarianceDomain,
    CovarianceEvidenceKind,
    CovarianceRecord,
    FrameClassification,
    FrameContract,
    PathKind,
    ProvenanceRef,
    PublicationStatus,
    ReadinessContract,
    ScaleStatus,
    SemanticStatus,
    SourceChannelStatus,
    TimeDomainPolicy,
    UnitStatus,
    ValidatedInput,
    ValidationContext,
    canonical_string,
    finite_number,
    positive_int,
)


PHYSICAL_BLOCKERS = (
    "AUTHORITATIVE_SOURCE_CHANNEL_UNRESOLVED",
    "SOURCE_FRAME_SEMANTICS_PARTIAL",
    "CHILD_FRAME_ID_UNRESOLVED",
    "TRANSLATION_SCALE_UNRESOLVED",
    "YAW_SCALE_UNRESOLVED",
    "ROS_HEADER_STAMP_POLICY_UNRESOLVED",
    "COVARIANCE_SI_CONVERSION_UNAVAILABLE",
    "NO_FUTURE_HARDWARE_REVALIDATION_EXPECTED",
)

EXECUTION_BLOCKERS = (
    "OFFLINE_REPLAY_ADAPTER_NOT_IMPLEMENTED",
    "OFFLINE_REPLAY_EXECUTION_NOT_VALIDATED",
    "SIMULATION_MODEL_NOT_BOUND",
    "SIMULATION_ADAPTER_NOT_IMPLEMENTED",
    "SIMULATION_EXECUTION_NOT_VALIDATED",
    "NAV2_SIMULATION_NOT_STARTED",
)


def provenance_from_input(
    source: ValidatedInput,
    *,
    context: ValidationContext | None = None,
    strength: ClaimStrength | None = None,
) -> ProvenanceRef:
    return ProvenanceRef(
        source_id=source.source_id,
        schema=source.schema,
        sha256=source.sha256,
        relative_logical_path=source.logical_path,
        path_kind=(
            PathKind.VERSIONED_REPOSITORY_PATH
            if source.logical_path.startswith("docs/")
            else PathKind.EXTERNAL_INPUT_MANIFEST_PATH
        ),
        validation_context=context or source.validation_context,
        claim_strength=strength or source.claim_strength,
        limitations=source.limitations,
    )


def build_frame_contracts(
    *,
    p1a: P1AValidation,
    mapping: MappingBinding,
    policy_input: ValidatedInput,
) -> tuple[FrameContract, ...]:
    physical = FrameContract(
        contract_id="physical-evidence-frame-policy",
        validation_context=ValidationContext.PHYSICAL_EVIDENCE,
        source_semantics=SemanticStatus.PARTIAL,
        child_semantics=SemanticStatus.UNRESOLVED,
        translation_scale=ScaleStatus.UNRESOLVED,
        yaw_scale=ScaleStatus.UNRESOLVED,
        translation_units=UnitStatus.SOURCE_UNITS_UNRESOLVED,
        yaw_units=UnitStatus.YAW_SPEED_RAD_S_ONLY,
        time_policy=TimeDomainPolicy.UNRESOLVED_FOR_ROS_HEADER,
        boot_policy=BootDomainPolicy.PER_BOOT_NO_CROSS_BOOT_CONCATENATION,
        source_channel=SourceChannelStatus.UNRESOLVED,
        classifications=(
            FrameClassification.OBSERVED_SOURCE_LABEL,
            FrameClassification.ROS_OUTPUT_CANDIDATE,
        ),
        provenance=(provenance_from_input(p1a.input_ref),),
        blockers=PHYSICAL_BLOCKERS,
    )
    replay = FrameContract(
        contract_id="offline-replay-frame-policy",
        validation_context=ValidationContext.OFFLINE_REPLAY,
        source_semantics=SemanticStatus.REPLAY_POLICY_CANDIDATE,
        child_semantics=SemanticStatus.CONFIGURED_NAME_ONLY,
        translation_scale=ScaleStatus.SOURCE_UNITS_ONLY,
        yaw_scale=ScaleStatus.SOURCE_UNITS_ONLY,
        translation_units=UnitStatus.SOURCE_UNITS_UNRESOLVED,
        yaw_units=UnitStatus.YAW_SPEED_RAD_S_ONLY,
        time_policy=TimeDomainPolicy.PRESERVE_RECORDED_ORDER_NO_ROS_STAMP,
        boot_policy=BootDomainPolicy.REPLAY_SESSION_ONLY,
        source_channel=SourceChannelStatus.EXPLICIT_INPUT_REQUIRED,
        classifications=(
            FrameClassification.MAPPING_REFERENCE,
            FrameClassification.CONFIGURED_NAME,
        ),
        provenance=(provenance_from_input(mapping.manifest_input),),
        blockers=(
            "OFFLINE_REPLAY_ADAPTER_NOT_IMPLEMENTED",
            "OFFLINE_REPLAY_EXECUTION_NOT_VALIDATED",
        ),
    )
    simulation = FrameContract(
        contract_id="simulation-policy-candidate",
        validation_context=ValidationContext.SIMULATION_POLICY,
        source_semantics=SemanticStatus.SIMULATION_POLICY_CANDIDATE,
        child_semantics=SemanticStatus.MODEL_NOT_SELECTED,
        translation_scale=ScaleStatus.SCALE_DEFINED_BY_FUTURE_MODEL,
        yaw_scale=ScaleStatus.SCALE_DEFINED_BY_FUTURE_MODEL,
        translation_units=UnitStatus.UNITS_DEFINED_BY_FUTURE_MODEL,
        yaw_units=UnitStatus.UNITS_DEFINED_BY_FUTURE_MODEL,
        time_policy=TimeDomainPolicy.CLOCK_DEFERRED_TO_P3,
        boot_policy=BootDomainPolicy.SIMULATION_EPISODE_ONLY,
        source_channel=SourceChannelStatus.FUTURE_MODEL_SOURCE,
        classifications=(FrameClassification.ROS_OUTPUT_CANDIDATE,),
        provenance=(
            provenance_from_input(
                policy_input,
                context=ValidationContext.SIMULATION_POLICY,
                strength=ClaimStrength.STRUCTURAL_POLICY,
            ),
        ),
        blockers=(
            "MODEL_NOT_SELECTED",
            "AXES_NOT_BOUND",
            "UNITS_DEFINED_BY_FUTURE_MODEL",
            "SCALE_DEFINED_BY_FUTURE_MODEL",
            "CLOCK_DEFERRED_TO_P3",
        ),
    )
    return (physical, replay, simulation)


def _record_provenance(p1a: P1AValidation) -> tuple[ProvenanceRef, ...]:
    return (provenance_from_input(p1a.input_ref),)


def build_covariance_records(p1a: P1AValidation) -> tuple[CovarianceRecord, ...]:
    document = p1a.document
    p1_bundle = document["p1_bundle"]
    if type(p1_bundle) is not dict:
        raise ContractValidationError("validated P1A bundle changed type")
    records: list[CovarianceRecord] = []
    stationary = p1_bundle["stationary"]
    if type(stationary) is not list:
        raise ContractValidationError("validated stationary set changed type")
    for item_value in stationary:
        if type(item_value) is not dict:
            raise ContractValidationError("validated stationary record changed type")
        item = item_value
        values = tuple(
            finite_number(value, "stationary.stddev", nonnegative=True)
            for value in item["stddev"]
        )
        variances = tuple(value * value for value in values)
        kind = (
            CovarianceEvidenceKind.MEASURED_ZERO_SOURCE_VARIANCE
            if any(value == 0.0 for value in values)
            else CovarianceEvidenceKind.MEASURED_SOURCE_STATISTIC
        )
        channel = item["channel"]
        session = item["session_id"]
        phase = item["phase"]
        if type(channel) is not str or type(session) is not str or type(phase) is not str:
            raise ContractValidationError("validated stationary identifiers changed type")
        sample_count = positive_int(item["sample_count"], "stationary.sample_count")
        exposure = finite_number(item["duration_s"], "stationary.duration_s", positive=True)
        records.append(
            CovarianceRecord(
                evidence_id=f"p2a.position-dispersion.{session}.{phase}.{channel.replace('/', '_')}",
                domain=CovarianceDomain.POSE_POSITION_SOURCE_DISPERSION,
                evidence_kind=kind,
                validation_context=ValidationContext.PHYSICAL_EVIDENCE,
                channel=channel,
                session_id=session,
                segment_id=phase,
                unit="SOURCE_POSITION_UNITS",
                sample_count=sample_count,
                exposure_s=exposure,
                supported_axes=("x", "y", "z"),
                unsupported_axes=("roll", "pitch", "yaw", "off_diagonal"),
                source_values=values,
                variance_candidates=variances,
                status=(
                    "MEASURED_ZERO_SOURCE_VARIANCE"
                    if kind is CovarianceEvidenceKind.MEASURED_ZERO_SOURCE_VARIANCE
                    else "PARTIAL_QUANTIFIED"
                ),
                provenance=_record_provenance(p1a),
                blockers=PHYSICAL_BLOCKERS,
                publication_status=PublicationStatus.NOT_PUBLICATION_READY,
            )
        )
        records.append(
            CovarianceRecord(
                evidence_id=f"p2a.orientation-unavailable.{session}.{phase}.{channel.replace('/', '_')}",
                domain=CovarianceDomain.POSE_ORIENTATION_UNAVAILABLE,
                evidence_kind=CovarianceEvidenceKind.UNAVAILABLE,
                validation_context=ValidationContext.PHYSICAL_EVIDENCE,
                channel=channel,
                session_id=session,
                segment_id=phase,
                unit="UNAVAILABLE",
                sample_count=sample_count,
                exposure_s=exposure,
                supported_axes=(),
                unsupported_axes=("roll", "pitch", "yaw"),
                source_values=(None, None, None),
                variance_candidates=(None, None, None),
                status="POSE_ORIENTATION_UNAVAILABLE",
                provenance=_record_provenance(p1a),
                blockers=PHYSICAL_BLOCKERS,
                publication_status=PublicationStatus.NOT_PUBLICATION_READY,
            )
        )
    residuals = p1_bundle["dynamic_residuals"]
    if type(residuals) is not list:
        raise ContractValidationError("validated residual set changed type")
    for item_value in residuals:
        if type(item_value) is not dict:
            raise ContractValidationError("validated residual record changed type")
        item = item_value
        residual_type = item["residual_type"]
        source_channel = item["channel"]
        if residual_type == "CROSS_CHANNEL":
            domain = CovarianceDomain.CROSS_CHANNEL_RESIDUAL
            kind = CovarianceEvidenceKind.CROSS_CHANNEL_DIAGNOSTIC
            channel = "CROSS_CHANNEL"
        else:
            domain = CovarianceDomain.TWIST_LINEAR_RESIDUAL
            kind = CovarianceEvidenceKind.MEASURED_SOURCE_STATISTIC
            channel = source_channel
        if type(channel) is not str:
            raise ContractValidationError("validated residual channel changed type")
        value = finite_number(item["residual_value"], "residual_value", nonnegative=True)
        records.append(
            CovarianceRecord(
                evidence_id=f"p2a.residual.{item['evidence_id']}",
                domain=domain,
                evidence_kind=kind,
                validation_context=ValidationContext.PHYSICAL_EVIDENCE,
                channel=channel,
                session_id=item["session_id"],
                segment_id=item["segment_name"],
                unit=item["unit"],
                sample_count=positive_int(item["sample_count"], "residual.sample_count"),
                exposure_s=None,
                supported_axes=("cross_channel",) if channel == "CROSS_CHANNEL" else ("linear",),
                unsupported_axes=("ros_covariance_diagonal",),
                source_values=(value,),
                variance_candidates=(None,),
                status=item["status"],
                provenance=_record_provenance(p1a),
                blockers=PHYSICAL_BLOCKERS,
                publication_status=PublicationStatus.NOT_PUBLICATION_READY,
            )
        )
    yaw_records = document["yaw_speed_residuals"]
    if type(yaw_records) is not list:
        raise ContractValidationError("validated yaw record set changed type")
    for item_value in yaw_records:
        if type(item_value) is not dict:
            raise ContractValidationError("validated yaw record changed type")
        item = item_value
        value = finite_number(
            item["yaw_speed_rmse_rad_s"],
            "yaw_speed_rmse_rad_s",
            nonnegative=True,
        )
        records.append(
            CovarianceRecord(
                evidence_id=f"p2a.yaw-rate-residual.{item['evidence_id']}",
                domain=CovarianceDomain.TWIST_ANGULAR_YAW_RATE_RESIDUAL,
                evidence_kind=CovarianceEvidenceKind.CROSS_CHANNEL_DIAGNOSTIC,
                validation_context=ValidationContext.PHYSICAL_EVIDENCE,
                channel="CROSS_CHANNEL",
                session_id=item["session_id"],
                segment_id=item["phase"],
                unit="rad/s",
                sample_count=positive_int(item["sample_count"], "yaw.sample_count"),
                exposure_s=None,
                supported_axes=("yaw_rate",),
                unsupported_axes=("pose_yaw", "ros_covariance_diagonal"),
                source_values=(value,),
                variance_candidates=(None,),
                status=item["status"],
                provenance=_record_provenance(p1a),
                blockers=PHYSICAL_BLOCKERS,
                publication_status=PublicationStatus.NOT_PUBLICATION_READY,
            )
        )
    if not records:
        raise ContractValidationError("covariance evidence set is empty")
    return tuple(records)


@dataclass(frozen=True, kw_only=True)
class Claim:
    name: str
    value: object
    context: ValidationContext

    def __post_init__(self) -> None:
        canonical_string(self.name, "claim.name")
        if type(self.context) is not ValidationContext:
            raise ContractValidationError("claim context enum bypass")


@dataclass(frozen=True, kw_only=True)
class ContractEvidenceSet:
    schema_version: str
    p1a: P1AValidation
    mapping: MappingBinding
    frames: tuple[FrameContract, ...]
    covariance: tuple[CovarianceRecord, ...]
    claims: tuple[Claim, ...]
    provenance_inputs: tuple[ValidatedInput, ...]

    def __post_init__(self) -> None:
        if self.schema_version != P2A_SCHEMA_VERSION:
            raise ContractValidationError("P2A evidence schema mismatch")
        if type(self.p1a) is not P1AValidation or type(self.mapping) is not MappingBinding:
            raise ContractValidationError("P2A validated input type mismatch")
        if type(self.frames) is not tuple or len(self.frames) != 3:
            raise ContractValidationError("P2A requires three context frame contracts")
        if any(type(item) is not FrameContract for item in self.frames):
            raise ContractValidationError("P2A frame type mismatch")
        contexts = {item.validation_context for item in self.frames}
        if contexts != {
            ValidationContext.PHYSICAL_EVIDENCE,
            ValidationContext.OFFLINE_REPLAY,
            ValidationContext.SIMULATION_POLICY,
        }:
            raise ContractValidationError("P2A frame contexts are incomplete")
        if type(self.covariance) is not tuple or not self.covariance:
            raise ContractValidationError("P2A covariance evidence is empty")
        if any(type(item) is not CovarianceRecord for item in self.covariance):
            raise ContractValidationError("P2A covariance type mismatch")
        domains = {item.domain for item in self.covariance}
        if domains != set(CovarianceDomain):
            raise ContractValidationError("P2A covariance domains are incomplete")
        if type(self.claims) is not tuple or any(type(item) is not Claim for item in self.claims):
            raise ContractValidationError("P2A claims are not exact")
        if type(self.provenance_inputs) is not tuple or not self.provenance_inputs:
            raise ContractValidationError("P2A material provenance is empty")
        if any(type(item) is not ValidatedInput for item in self.provenance_inputs):
            raise ContractValidationError("P2A material provenance type mismatch")


EXPECTED_CLAIMS: Mapping[str, object] = {
    "P2A_CONTRACT_STRUCTURALLY_READY": True,
    "MAPPING_PROVENANCE_BOUND": True,
    "P1A_INPUT_VALIDATED": True,
    "ENUM_BYPASS_CLOSED": True,
    "NUMERIC_OVERFLOW_CLOSED": True,
    "MEASURED_ZERO_PRESERVED": True,
    "CROSS_CHANNEL_EVIDENCE_SEPARATED": True,
    "OFFLINE_REPLAY_POLICY_STRUCTURALLY_READY": True,
    "OFFLINE_REPLAY_ADAPTER_READY": False,
    "OFFLINE_REPLAY_EXECUTION_VALIDATED": False,
    "SIMULATION_POLICY_STRUCTURALLY_READY": True,
    "SIMULATION_MODEL_BOUND": False,
    "SIMULATION_ADAPTER_IMPLEMENTED": False,
    "SIMULATION_EXECUTION_READY": False,
    "PHYSICAL_ODOM_PUBLICATION_READY": False,
    "PHYSICAL_TF_PUBLICATION_READY": False,
    "AUTHORITATIVE_SOURCE_CHANNEL": None,
    "PREFERRED_ANALYSIS_CHANNEL": None,
}


def build_claims() -> tuple[Claim, ...]:
    return tuple(
        Claim(
            name=name,
            value=value,
            context=(
                ValidationContext.PHYSICAL_EVIDENCE
                if name
                in {
                    "PHYSICAL_ODOM_PUBLICATION_READY",
                    "PHYSICAL_TF_PUBLICATION_READY",
                    "AUTHORITATIVE_SOURCE_CHANNEL",
                    "PREFERRED_ANALYSIS_CHANNEL",
                }
                else ValidationContext.STRUCTURAL_ONLY
            ),
        )
        for name, value in EXPECTED_CLAIMS.items()
    )


def assess_readiness(evidence: ContractEvidenceSet) -> ReadinessContract:
    if type(evidence) is not ContractEvidenceSet:
        raise ContractValidationError("readiness requires a validated ContractEvidenceSet")
    actual_claims = {claim.name: claim.value for claim in evidence.claims}
    if actual_claims != dict(EXPECTED_CLAIMS):
        raise ContractValidationError("claims ledger is inconsistent")
    provenance_by_id = {item.source_id: item for item in evidence.provenance_inputs}
    p1a_provenance = provenance_by_id.get(evidence.p1a.input_ref.source_id)
    if p1a_provenance is None or evidence.p1a.input_ref.sha256 != p1a_provenance.sha256:
        raise ContractValidationError("P1A provenance hash mismatch")
    if evidence.mapping.manifest_input.sha256 not in {
        item.sha256 for item in evidence.provenance_inputs
    }:
        raise ContractValidationError("mapping provenance hash missing")
    return ReadinessContract(
        p2a_contract_structurally_ready=True,
        offline_replay_policy_structurally_ready=True,
        simulation_policy_structurally_ready=True,
        physical_odom_publication_ready=False,
        physical_tf_publication_ready=False,
        offline_replay_adapter_ready=False,
        offline_replay_execution_validated=False,
        simulation_model_bound=False,
        simulation_adapter_ready=False,
        simulation_execution_ready=False,
        nav2_simulation_ready=False,
        blockers=PHYSICAL_BLOCKERS + EXECUTION_BLOCKERS,
    )
