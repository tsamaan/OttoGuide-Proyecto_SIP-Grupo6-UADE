"""P2A frame, covariance and object-derived readiness construction."""

from __future__ import annotations

import math
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
    CovarianceStatus,
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
                    CovarianceStatus.MEASURED_ZERO_SOURCE_VARIANCE  # F01
                    if kind is CovarianceEvidenceKind.MEASURED_ZERO_SOURCE_VARIANCE
                    else CovarianceStatus.PARTIAL_QUANTIFIED
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
                status=CovarianceStatus.POSE_ORIENTATION_UNAVAILABLE,  # F01
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
                status=(
                    CovarianceStatus.CROSS_CHANNEL_DIAGNOSTIC  # F01: cross-channel
                    if residual_type == "CROSS_CHANNEL"
                    else CovarianceStatus.SOURCE_RESIDUAL_DIAGNOSTIC  # F01: linear residual
                ),
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
                status=CovarianceStatus.CROSS_CHANNEL_DIAGNOSTIC,  # F01
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
    descriptor_input: ValidatedInput
    p2_claims_input: ValidatedInput
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
        # F11: claims must be a non-empty tuple of exact Claim; each name unique
        if type(self.claims) is not tuple or not self.claims:
            raise ContractValidationError("P2A claims are not exact")
        if any(type(item) is not Claim for item in self.claims):
            raise ContractValidationError("P2A claims are not exact")
        claim_names = [item.name for item in self.claims]
        if len(claim_names) != len(set(claim_names)):
            raise ContractValidationError("P2A claim names must be unique")
        # F12: provenance_inputs must be non-empty with unique source_ids
        if type(self.provenance_inputs) is not tuple or not self.provenance_inputs:
            raise ContractValidationError("P2A material provenance is empty")
        if any(type(item) is not ValidatedInput for item in self.provenance_inputs):
            raise ContractValidationError("P2A material provenance type mismatch")
        if type(self.descriptor_input) is not ValidatedInput:
            raise ContractValidationError("descriptor input type mismatch")
        if type(self.p2_claims_input) is not ValidatedInput:
            raise ContractValidationError("claims ledger input type mismatch")
        if (
            self.descriptor_input.source_id != "r2-p0a-evidence-descriptor"
            or self.descriptor_input.validation_context
            is not ValidationContext.PHYSICAL_EVIDENCE
            or self.descriptor_input.claim_strength
            is not ClaimStrength.PRESERVED_PHYSICAL_EVIDENCE
        ):
            raise ContractValidationError("descriptor input contract mismatch")
        if (
            self.p2_claims_input.source_id != "r2-p2a-claims-ledger"
            or self.p2_claims_input.validation_context
            is not ValidationContext.STRUCTURAL_ONLY
            or self.p2_claims_input.claim_strength is not ClaimStrength.STRUCTURAL_POLICY
        ):
            raise ContractValidationError("claims ledger input contract mismatch")
        source_ids = [item.source_id for item in self.provenance_inputs]
        if len(source_ids) != len(set(source_ids)):
            duplicates = tuple(sorted({item for item in source_ids if source_ids.count(item) > 1}))
            raise ContractValidationError(
                f"P2A provenance source_ids must be unique: duplicates={duplicates}"
            )
        expected_inputs = (
            self.descriptor_input,
            self.p1a.input_ref,
            self.mapping.manifest_input,
            self.p2_claims_input,
        ) + self.mapping.selected_inputs
        if any(type(item) is not ValidatedInput for item in expected_inputs):
            raise ContractValidationError("P2A expected material provenance type mismatch")
        expected_ids_sequence = [item.source_id for item in expected_inputs]
        if len(expected_ids_sequence) != len(set(expected_ids_sequence)):
            duplicates = tuple(
                sorted({item for item in expected_ids_sequence if expected_ids_sequence.count(item) > 1})
            )
            raise ContractValidationError(
                f"P2A expected provenance source_ids must be unique: duplicates={duplicates}"
            )
        expected_by_id = {item.source_id: item for item in expected_inputs}
        actual_by_id = {item.source_id: item for item in self.provenance_inputs}
        expected_ids = set(expected_by_id)
        actual_ids = set(source_ids)
        missing = tuple(sorted(expected_ids - actual_ids))
        extra = tuple(sorted(actual_ids - expected_ids))
        mismatched = tuple(
            sorted(
                source_id
                for source_id in expected_ids & actual_ids
                if actual_by_id[source_id] != expected_by_id[source_id]
            )
        )
        if missing or extra or mismatched:
            raise ContractValidationError(
                "P2A provenance mismatch: "
                f"missing={missing} extra={extra} mismatched={mismatched}"
            )


CONFIGURED_CONTRACT_FRAMES = ("map", "odom", "base_link")


def build_mapping_vocabulary(mapping: MappingBinding) -> tuple[Mapping[str, str], ...]:
    if type(mapping) is not MappingBinding:
        raise ContractValidationError("mapping vocabulary requires a validated binding")
    observed = mapping.observed_frame_ids
    if type(observed) is not tuple or len(observed) != len(set(observed)):
        raise ContractValidationError("mapping observed frame IDs must be unique")
    if set(CONFIGURED_CONTRACT_FRAMES) & set(observed):
        raise ContractValidationError("configured and observed frame vocabularies overlap")
    configured_entries = tuple(
        {
            "frame_id": frame_id,
            "provenance_kind": "CONFIGURED_CONTRACT_NAME",
            "classification": (
                FrameClassification.MAPPING_REFERENCE.value
                if frame_id == "map"
                else FrameClassification.CONFIGURED_NAME.value
            ),
            "physical_semantics": "UNRESOLVED",
        }
        for frame_id in CONFIGURED_CONTRACT_FRAMES
    )
    observed_entries = tuple(
        {
            "frame_id": frame_id,
            "provenance_kind": "MANIFEST_OBSERVED_FRAME_ID",
            "classification": FrameClassification.OBSERVED_SOURCE_LABEL.value,
            "physical_semantics": "UNRESOLVED",
        }
        for frame_id in sorted(observed)
    )
    return configured_entries + observed_entries


def measured_zero_source_variance_preserved(
    covariance: tuple[CovarianceRecord, ...],
) -> bool:
    """Return whether source-dispersion evidence preserves a measured zero."""
    if type(covariance) is not tuple or any(
        type(record) is not CovarianceRecord for record in covariance
    ):
        raise ContractValidationError(
            "measured-zero evaluation requires exact covariance records"
        )
    return any(
        record.domain is CovarianceDomain.POSE_POSITION_SOURCE_DISPERSION
        and record.evidence_kind
        is CovarianceEvidenceKind.MEASURED_ZERO_SOURCE_VARIANCE
        and any(
            source_value == 0.0 and variance_candidate == 0.0
            for source_value, variance_candidate in zip(
                record.source_values,
                record.variance_candidates,
                strict=True,
            )
        )
        for record in covariance
    )


def build_claims(
    *,
    p1a: P1AValidation,
    mapping: MappingBinding,
    frames: tuple[FrameContract, ...],
    covariance: tuple[CovarianceRecord, ...],
    mapping_vocabulary: tuple[Mapping[str, str], ...],
) -> tuple[Claim, ...]:
    if type(p1a) is not P1AValidation or type(mapping) is not MappingBinding:
        raise ContractValidationError("claims require validated material inputs")
    if type(frames) is not tuple or any(type(item) is not FrameContract for item in frames):
        raise ContractValidationError("claims require exact frame contracts")
    if type(covariance) is not tuple or any(
        type(item) is not CovarianceRecord for item in covariance
    ):
        raise ContractValidationError("claims require exact covariance records")
    if type(mapping_vocabulary) is not tuple or not mapping_vocabulary:
        raise ContractValidationError("claims require a mapping vocabulary")
    observed_vocabulary = tuple(
        entry["frame_id"]
        for entry in mapping_vocabulary
        if entry.get("provenance_kind") == "MANIFEST_OBSERVED_FRAME_ID"
    )
    vocabulary_derived = observed_vocabulary == tuple(sorted(mapping.observed_frame_ids))
    frame_contexts = {frame.validation_context for frame in frames}
    replay_ready = ValidationContext.OFFLINE_REPLAY in frame_contexts
    simulation_ready = ValidationContext.SIMULATION_POLICY in frame_contexts
    mapping_manifest_reference_valid = (
        mapping.manifest_input.source_id == "r2-p2a-mapping-evidence-manifest"
        and bool(mapping.selected_inputs)
    )
    mapping_hash_references_well_formed = all(
        type(item.sha256) is str and len(item.sha256) == 64
        for item in (mapping.manifest_input,) + mapping.selected_inputs
    )
    numeric_values = tuple(
        value
        for record in covariance
        for value in record.source_values + record.variance_candidates
        if value is not None
    )
    current_covariance_values_finite = all(
        type(value) in (int, float) and not isinstance(value, bool) and math.isfinite(value)
        for value in numeric_values
    )
    measured_zero_preserved = measured_zero_source_variance_preserved(covariance)
    cross_channel_separated = all(
        record.channel == "CROSS_CHANNEL"
        for record in covariance
        if record.domain in (
            CovarianceDomain.CROSS_CHANNEL_RESIDUAL,
            CovarianceDomain.TWIST_ANGULAR_YAW_RATE_RESIDUAL,
        )
    )
    structurally_ready = (
        mapping_manifest_reference_valid
        and mapping_hash_references_well_formed
        and vocabulary_derived
        and p1a.input_ref.source_id == "r2-p1a-result"
        and frame_contexts
        == {
            ValidationContext.PHYSICAL_EVIDENCE,
            ValidationContext.OFFLINE_REPLAY,
            ValidationContext.SIMULATION_POLICY,
        }
        and bool(covariance)
    )
    values = (
        ("P2A_CONTRACT_STRUCTURALLY_READY", structurally_ready),
        (
            "MAPPING_MANIFEST_REFERENCE_STRUCTURALLY_VALID",
            mapping_manifest_reference_valid,
        ),
        (
            "MAPPING_INPUT_HASH_REFERENCES_WELL_FORMED",
            mapping_hash_references_well_formed,
        ),
        ("MAPPING_SELECTED_SOURCE_CONTENT_PARSED", False),
        ("MAPPING_FRAME_RELATIONS_DERIVED_FROM_CONTENT", False),
        ("MAPPING_VOCABULARY_DERIVED_FROM_MANIFEST", vocabulary_derived),
        (
            "P1A_INPUT_REFERENCE_STRUCTURALLY_VALID",
            p1a.input_ref.source_id == "r2-p1a-result",
        ),
        (
            "FRAME_VALIDATION_CONTEXT_TYPES_EXACT",
            all(
                type(frame.validation_context) is ValidationContext
                for frame in frames
            ),
        ),
        ("CURRENT_COVARIANCE_VALUES_FINITE", current_covariance_values_finite),
        ("MEASURED_ZERO_PRESERVED", measured_zero_preserved),
        ("CROSS_CHANNEL_EVIDENCE_SEPARATED", cross_channel_separated),
        ("OFFLINE_REPLAY_POLICY_STRUCTURALLY_READY", replay_ready),
        ("OFFLINE_REPLAY_ADAPTER_READY", False),
        ("OFFLINE_REPLAY_EXECUTION_VALIDATED", False),
        ("SIMULATION_POLICY_STRUCTURALLY_READY", simulation_ready),
        ("SIMULATION_MODEL_BOUND", False),
        ("SIMULATION_ADAPTER_IMPLEMENTED", False),
        ("SIMULATION_EXECUTION_READY", False),
        ("PHYSICAL_ODOM_PUBLICATION_READY", False),
        ("PHYSICAL_TF_PUBLICATION_READY", False),
        ("AUTHORITATIVE_SOURCE_CHANNEL", p1a.authoritative_source_channel),
        ("PREFERRED_ANALYSIS_CHANNEL", p1a.preferred_analysis_channel),
    )
    physical_names = {
        "PHYSICAL_ODOM_PUBLICATION_READY",
        "PHYSICAL_TF_PUBLICATION_READY",
        "AUTHORITATIVE_SOURCE_CHANNEL",
        "PREFERRED_ANALYSIS_CHANNEL",
    }
    return tuple(
        Claim(
            name=name,
            value=value,
            context=(
                ValidationContext.PHYSICAL_EVIDENCE
                if name in physical_names
                else ValidationContext.STRUCTURAL_ONLY
            ),
        )
        for name, value in values
    )


def assess_readiness(evidence: ContractEvidenceSet) -> ReadinessContract:
    if type(evidence) is not ContractEvidenceSet:
        raise ContractValidationError("readiness requires a validated ContractEvidenceSet")
    expected_claims = build_claims(
        p1a=evidence.p1a,
        mapping=evidence.mapping,
        frames=evidence.frames,
        covariance=evidence.covariance,
        mapping_vocabulary=build_mapping_vocabulary(evidence.mapping),
    )
    if evidence.claims != expected_claims:
        raise ContractValidationError("claims ledger is inconsistent")
    provenance_by_id = {item.source_id: item for item in evidence.provenance_inputs}
    p1a_provenance = provenance_by_id.get(evidence.p1a.input_ref.source_id)
    if p1a_provenance is None or evidence.p1a.input_ref.sha256 != p1a_provenance.sha256:
        raise ContractValidationError("P1A provenance hash mismatch")
    if evidence.mapping.manifest_input.sha256 not in {
        item.sha256 for item in evidence.provenance_inputs
    }:
        raise ContractValidationError("mapping provenance hash missing")
    claim_values = {claim.name: claim.value for claim in evidence.claims}
    return ReadinessContract(
        p2a_contract_structurally_ready=(
            claim_values["P2A_CONTRACT_STRUCTURALLY_READY"] is True
        ),
        offline_replay_policy_structurally_ready=(
            claim_values["OFFLINE_REPLAY_POLICY_STRUCTURALLY_READY"] is True
        ),
        simulation_policy_structurally_ready=(
            claim_values["SIMULATION_POLICY_STRUCTURALLY_READY"] is True
        ),
        physical_odom_publication_ready=(
            claim_values["PHYSICAL_ODOM_PUBLICATION_READY"] is True
        ),
        physical_tf_publication_ready=(
            claim_values["PHYSICAL_TF_PUBLICATION_READY"] is True
        ),
        offline_replay_adapter_ready=(
            claim_values["OFFLINE_REPLAY_ADAPTER_READY"] is True
        ),
        offline_replay_execution_validated=(
            claim_values["OFFLINE_REPLAY_EXECUTION_VALIDATED"] is True
        ),
        simulation_model_bound=(
            claim_values["SIMULATION_MODEL_BOUND"] is True
        ),
        simulation_adapter_ready=(
            claim_values["SIMULATION_ADAPTER_IMPLEMENTED"] is True
        ),
        simulation_execution_ready=(
            claim_values["SIMULATION_EXECUTION_READY"] is True
        ),
        nav2_simulation_ready=False,
        blockers=PHYSICAL_BLOCKERS + EXECUTION_BLOCKERS,
    )
