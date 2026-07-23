import copy
import dataclasses
import math

import pytest

from src.navigation.odometry_contract_r2_p2a.contract import (
    ContractEvidenceSet,
    assess_readiness,
    build_claims,
    build_covariance_records,
    build_frame_contracts,
)
from src.navigation.odometry_contract_r2_p2a.inputs import (
    MappingBinding,
    P1AValidation,
    validate_p1a_document,
)
from src.navigation.odometry_contract_r2_p2a.models import (
    ClaimStrength,
    ContractValidationError,
    CovarianceDomain,
    FrameClassification,
    FrameContract,
    PathKind,
    ProvenanceRef,
    ScaleStatus,
    SemanticStatus,
    SourceChannelStatus,
    TimeDomainPolicy,
    UnitStatus,
    ValidatedInput,
    ValidationContext,
)


SYNTHETIC_TEST_ONLY = True
SHA_A = "a" * 64
SHA_B = "b" * 64


def _stationary(index):
    channel = "rt/odommodestate" if index % 2 == 0 else "rt/lf/odommodestate"
    return {
        "schema_version": "2.1.1-p1a",
        "evidence_id": f"synthetic.stationary.{index}",
        "channel": channel,
        "session_id": f"synthetic-session-{index // 2}",
        "phase": f"phase-{index}",
        "sample_count": 2,
        "duration_s": 1.0,
        "stddev": [0.0 if index == 0 else 1.0, 2.0, 3.0],
        "mad": [0.0, 1.0, 1.0],
        "p95_deviation": [0.0, 2.0, 2.0],
    }


def synthetic_p1a():
    return {
        "schema_version": "2.1.1-p1a",
        "audit_findings": [
            {"hypothesis_id": f"H{number}"} for number in range(1, 11)
        ],
        "arbitration_audit": {
            "authoritative_source_channel": None,
            "preferred_analysis_channel": None,
        },
        "boot_relation_evidence": [
            {
                "continuous_capture": False,
                "continuous_trajectory_permitted": False,
                "same_time_domain": False,
            }
        ],
        "p1_bundle": {
            "schema_version": "2.1.1-p1a",
            "stationary": [_stationary(index) for index in range(10)],
            "dynamic_residuals": [
                {
                    "evidence_id": "synthetic.cross",
                    "channel": "BOTH",
                    "session_id": "synthetic-session-0",
                    "segment_name": "phase-0",
                    "residual_type": "CROSS_CHANNEL",
                    "residual_value": 0.0,
                    "sample_count": 2,
                    "status": "VERIFIED",
                    "unit": "source_position_units",
                },
                {
                    "evidence_id": "synthetic.primary",
                    "channel": "rt/odommodestate",
                    "session_id": "synthetic-session-0",
                    "segment_name": "phase-0",
                    "residual_type": "INTERNAL_CONSISTENCY",
                    "residual_value": 1.0,
                    "sample_count": 2,
                    "status": "VERIFIED",
                    "unit": "source_position_units",
                },
            ],
        },
        "yaw_speed_residuals": [
            {
                "evidence_id": "synthetic.yaw",
                "session_id": "synthetic-session-0",
                "phase": "phase-0",
                "sample_count": 2,
                "yaw_speed_rmse_rad_s": 0.0,
                "status": "VERIFIED",
            }
        ],
    }


def _validated_p1a(document=None):
    document = document or synthetic_p1a()
    return validate_p1a_document(document, input_sha256=SHA_A)


def _input(source_id, context=ValidationContext.STRUCTURAL_ONLY):
    return ValidatedInput(
        source_id=source_id,
        schema="test-schema",
        sha256=SHA_B,
        logical_path=f"tests/{source_id}.json",
        validation_context=context,
        claim_strength=ClaimStrength.STRUCTURAL_POLICY,
        limitations=("SYNTHETIC_TEST_ONLY",),
    )


def _mapping():
    manifest = ValidatedInput(
        source_id="synthetic-mapping",
        schema="1.0.0-p2a-mapping",
        sha256=SHA_B,
        logical_path="tests/synthetic-mapping.json",
        validation_context=ValidationContext.OFFLINE_REPLAY,
        claim_strength=ClaimStrength.PRESERVED_MAPPING_REFERENCE,
        limitations=("SYNTHETIC_TEST_ONLY",),
    )
    return MappingBinding(
        manifest_input=manifest,
        selected_inputs=(manifest,),
        source_ids=("synthetic-source",),
        session_ids=("synthetic-session",),
        take_ids=("synthetic-take",),
        observed_frame_ids=("utlidar_lidar",),
        observed_topic_ids=("/scan",),
        allowed_claims=("TOPIC_VOCABULARY",),
        prohibited_claims=("PHYSICAL_FRAME_SEMANTICS_VERIFIED",),
        correlation_edges=("odom->base_link:UNRESOLVED_PHYSICAL_SEMANTICS",),
    )


def test_plain_string_validation_context_bypass_is_closed():
    provenance = ProvenanceRef(
        source_id="test",
        schema="test",
        sha256=SHA_A,
        relative_logical_path="tests/source.json",
        path_kind=PathKind.VERSIONED_REPOSITORY_PATH,
        validation_context=ValidationContext.PHYSICAL_EVIDENCE,
        claim_strength=ClaimStrength.PRESERVED_PHYSICAL_EVIDENCE,
        limitations=("SYNTHETIC_TEST_ONLY",),
    )
    with pytest.raises(ContractValidationError, match="validation_context"):
        FrameContract(
            contract_id="bypass",
            validation_context="PHYSICAL_EVIDENCE",
            source_semantics=SemanticStatus.PARTIAL,
            child_semantics=SemanticStatus.UNRESOLVED,
            translation_scale=ScaleStatus.UNRESOLVED,
            yaw_scale=ScaleStatus.UNRESOLVED,
            translation_units=UnitStatus.SOURCE_UNITS_UNRESOLVED,
            yaw_units=UnitStatus.YAW_SPEED_RAD_S_ONLY,
            time_policy=TimeDomainPolicy.UNRESOLVED_FOR_ROS_HEADER,
            boot_policy="PER_BOOT_NO_CROSS_BOOT_CONCATENATION",
            source_channel=SourceChannelStatus.UNRESOLVED,
            classifications=(FrameClassification.OBSERVED_SOURCE_LABEL,),
            provenance=(provenance,),
            blockers=("BLOCKED",),
        )


def test_plain_string_frame_classification_bypass_is_closed():
    p1a = _validated_p1a()
    frame = build_frame_contracts(
        p1a=p1a,
        mapping=_mapping(),
        policy_input=_input("policy"),
    )[0]
    with pytest.raises(ContractValidationError, match="classification"):
        dataclasses.replace(frame, classifications=("OBSERVED_SOURCE_LABEL",))


@pytest.mark.parametrize("value", ["TYPO", " PARTIAL", "PARTIAL\x00"])
def test_unknown_or_noncanonical_status_is_rejected(value):
    p1a = _validated_p1a()
    frame = build_frame_contracts(
        p1a=p1a,
        mapping=_mapping(),
        policy_input=_input("policy"),
    )[0]
    with pytest.raises((ContractValidationError, TypeError)):
        dataclasses.replace(frame, source_semantics=value)


class HostileList(list):
    pass


class HostileTuple(tuple):
    pass


class BrokenSequence:
    def __len__(self):
        raise RuntimeError("hostile")

    def __getitem__(self, index):
        raise RuntimeError("hostile")


@pytest.mark.parametrize(
    "value",
    [
        HostileList([1.0, 2.0, 3.0]),
        HostileTuple((1.0, 2.0, 3.0)),
        BrokenSequence(),
    ],
)
def test_hostile_or_defective_sequence_fails_closed(value):
    document = synthetic_p1a()
    document["p1_bundle"]["stationary"][0]["stddev"] = value
    with pytest.raises(ContractValidationError):
        validate_p1a_document(document, input_sha256=SHA_A)


def test_exact_tuple_numeric_vector_is_accepted():
    document = synthetic_p1a()
    document["p1_bundle"]["stationary"][0]["stddev"] = (0.0, 0.1, 0.2)
    assert validate_p1a_document(document, input_sha256=SHA_A)


@pytest.mark.parametrize(
    "value",
    [10**10000, math.nan, math.inf, -math.inf, True],
    ids=["huge-int", "nan", "positive-inf", "negative-inf", "bool"],
)
def test_nonrepresentable_nonfinite_and_bool_numbers_are_rejected(value):
    document = synthetic_p1a()
    document["p1_bundle"]["stationary"][0]["stddev"][0] = value
    with pytest.raises(ContractValidationError):
        validate_p1a_document(document, input_sha256=SHA_A)


def test_measured_zero_is_preserved_as_zero_variance():
    records = build_covariance_records(_validated_p1a())
    first = next(
        record
        for record in records
        if record.domain is CovarianceDomain.POSE_POSITION_SOURCE_DISPERSION
    )
    assert first.source_values[0] == 0.0
    assert first.variance_candidates[0] == 0.0
    assert first.status == "MEASURED_ZERO_SOURCE_VARIANCE"


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("sample_count", 0),
        ("sample_count", True),
        ("sample_count", 10**10000),
        ("duration_s", 0.0),
        ("duration_s", -1.0),
        ("channel", "unknown"),
    ],
    ids=[
        "zero-sample-count",
        "bool-sample-count",
        "huge-sample-count",
        "zero-duration",
        "negative-duration",
        "unknown-channel",
    ],
)
def test_invalid_stationary_metadata_is_rejected(field, value):
    document = synthetic_p1a()
    document["p1_bundle"]["stationary"][0][field] = value
    with pytest.raises(ContractValidationError):
        validate_p1a_document(document, input_sha256=SHA_A)


def test_cross_channel_residual_is_not_replicated():
    records = build_covariance_records(_validated_p1a())
    cross = [
        record
        for record in records
        if record.domain is CovarianceDomain.CROSS_CHANNEL_RESIDUAL
    ]
    assert len(cross) == 1
    assert cross[0].channel == "CROSS_CHANNEL"


def test_yaw_residual_is_a_cross_channel_yaw_rate_domain():
    records = build_covariance_records(_validated_p1a())
    yaw = [
        record
        for record in records
        if record.domain is CovarianceDomain.TWIST_ANGULAR_YAW_RATE_RESIDUAL
    ]
    assert len(yaw) == 1
    assert yaw[0].channel == "CROSS_CHANNEL"
    assert yaw[0].unit == "rad/s"


def test_p1a_schema_and_audit_ids_are_exact():
    document = synthetic_p1a()
    document["schema_version"] = "wrong"
    with pytest.raises(ContractValidationError, match="schema"):
        validate_p1a_document(document, input_sha256=SHA_A)
    document = synthetic_p1a()
    document["audit_findings"].pop()
    with pytest.raises(ContractValidationError, match="H1-H10"):
        validate_p1a_document(document, input_sha256=SHA_A)


def test_p1a_authoritative_channel_non_null_is_rejected():
    document = synthetic_p1a()
    document["arbitration_audit"]["authoritative_source_channel"] = "rt/odommodestate"
    with pytest.raises(ContractValidationError, match="authoritative"):
        validate_p1a_document(document, input_sha256=SHA_A)


def test_p1a_preferred_channel_non_null_is_rejected_without_known_hash_binding():
    document = synthetic_p1a()
    document["arbitration_audit"]["preferred_analysis_channel"] = (
        "rt/lf/odommodestate"
    )
    with pytest.raises(ContractValidationError, match="preferred"):
        validate_p1a_document(document, input_sha256=SHA_A)


def test_simulation_policy_has_no_bound_model_or_verified_geometry():
    frames = build_frame_contracts(
        p1a=_validated_p1a(),
        mapping=_mapping(),
        policy_input=_input("policy"),
    )
    simulation = next(
        frame
        for frame in frames
        if frame.validation_context is ValidationContext.SIMULATION_POLICY
    )
    assert simulation.source_semantics is SemanticStatus.SIMULATION_POLICY_CANDIDATE
    assert simulation.child_semantics is SemanticStatus.MODEL_NOT_SELECTED
    assert simulation.translation_scale is ScaleStatus.SCALE_DEFINED_BY_FUTURE_MODEL


def test_readiness_requires_validated_object_and_derives_false_execution_states():
    p1a = _validated_p1a()
    mapping = _mapping()
    policy = _input("policy")
    frames = build_frame_contracts(p1a=p1a, mapping=mapping, policy_input=policy)
    covariance = build_covariance_records(p1a)
    evidence = ContractEvidenceSet(
        schema_version="2.2.1-p2a",
        p1a=p1a,
        mapping=mapping,
        frames=frames,
        covariance=covariance,
        claims=build_claims(),
        provenance_inputs=(_input("descriptor"), p1a.input_ref, mapping.manifest_input, policy),
    )
    readiness = assess_readiness(evidence)
    assert readiness.p2a_contract_structurally_ready
    assert readiness.offline_replay_policy_structurally_ready
    assert readiness.simulation_policy_structurally_ready
    assert not readiness.offline_replay_adapter_ready
    assert not readiness.simulation_model_bound
    assert not readiness.simulation_execution_ready
    with pytest.raises(ContractValidationError):
        assess_readiness(True)


def test_provenance_without_hash_is_rejected():
    with pytest.raises(ContractValidationError, match="SHA-256"):
        dataclasses.replace(_input("source"), sha256="")
