import copy
import dataclasses
import hashlib
import json
import math
from pathlib import Path
from types import MappingProxyType

import pytest

from src.navigation.odometry_contract_r2_p2a.contract import (
    ContractEvidenceSet,
    assess_readiness,
    build_claims,
    build_covariance_records,
    build_frame_contracts,
    build_mapping_vocabulary,
    measured_zero_source_variance_preserved,
)
from src.navigation.odometry_contract_r2_p2a.inputs import (
    MappingBinding,
    P1AValidation,
    load_and_validate_p1a,
    validate_mapping_manifest,
    validate_p1a_document,
)
from src.navigation.odometry_contract_r2_p2a.models import (
    BootDomainPolicy,
    ClaimStrength,
    COVARIANCE_DOMAIN_POLICY,
    ContractValidationError,
    CovarianceDomain,
    CovarianceEvidenceKind,
    CovarianceShapePolicy,
    CovarianceStatus,
    FRAME_CONTEXT_POLICY,
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
from src.navigation.odometry_contract_r2_p2a.report import (
    OUTPUT_NAMES,
    build_documents,
    canonical_json,
    write_documents,
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
        "stddev": [1.0, 2.0, 3.0],
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


def _descriptor_input():
    return ValidatedInput(
        source_id="r2-p0a-evidence-descriptor",
        schema="1.0.0-p0a",
        sha256=SHA_B,
        logical_path="tests/descriptor.json",
        validation_context=ValidationContext.PHYSICAL_EVIDENCE,
        claim_strength=ClaimStrength.PRESERVED_PHYSICAL_EVIDENCE,
        limitations=("SYNTHETIC_TEST_ONLY",),
    )


def _claims_input():
    return _input("r2-p2a-claims-ledger")


def _mapping():
    manifest = ValidatedInput(
        source_id="r2-p2a-mapping-evidence-manifest",
        schema="1.0.0-p2a-mapping",
        sha256=SHA_B,
        logical_path="tests/synthetic-mapping.json",
        validation_context=ValidationContext.OFFLINE_REPLAY,
        claim_strength=ClaimStrength.PRESERVED_MAPPING_REFERENCE,
        limitations=("SYNTHETIC_TEST_ONLY",),
    )
    selected = ValidatedInput(
        source_id="synthetic-source",
        schema="1.0.0-p2a-mapping",
        sha256=SHA_B,
        logical_path="tests/synthetic-source.json",
        validation_context=ValidationContext.OFFLINE_REPLAY,
        claim_strength=ClaimStrength.PRESERVED_MAPPING_REFERENCE,
        limitations=("SYNTHETIC_TEST_ONLY",),
    )
    return MappingBinding(
        manifest_input=manifest,
        selected_inputs=(selected,),
        source_ids=("synthetic-source",),
        file_categories=("FRAME_INVENTORY",),
        selected_source_categories=(("synthetic-source", "FRAME_INVENTORY"),),
        session_ids=("synthetic-session",),
        take_ids=("synthetic-take",),
        observed_frame_ids=("utlidar_lidar",),
        observed_topic_ids=("/scan",),
        allowed_claims=("TOPIC_VOCABULARY",),
        prohibited_claims=("PHYSICAL_FRAME_SEMANTICS_VERIFIED",),
        structural_correlation_policy=(
            "odom->base_link:UNRESOLVED_PHYSICAL_SEMANTICS",
        ),
    )


def _claims():
    p1a = _validated_p1a()
    mapping = _mapping()
    frames = build_frame_contracts(p1a=p1a, mapping=mapping, policy_input=_input("policy"))
    covariance = build_covariance_records(p1a)
    return build_claims(
        p1a=p1a,
        mapping=mapping,
        frames=frames,
        covariance=covariance,
        mapping_vocabulary=build_mapping_vocabulary(mapping),
    )


def _documents(mapping=None):
    return build_documents(
        p1a=_validated_p1a(),
        mapping=mapping or _mapping(),
        descriptor_input=_descriptor_input(),
        p2_claims_input=_claims_input(),
        generated_utc="2026-07-23T12:00:00Z",
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
    document = synthetic_p1a()
    document["p1_bundle"]["stationary"][0]["stddev"][0] = 0.0
    records = build_covariance_records(_validated_p1a(document))
    first = next(
        record
        for record in records
        if record.domain is CovarianceDomain.POSE_POSITION_SOURCE_DISPERSION
    )
    assert first.source_values[0] == 0.0
    assert first.variance_candidates[0] == 0.0
    assert first.status is CovarianceStatus.MEASURED_ZERO_SOURCE_VARIANCE
    assert first.evidence_kind is CovarianceEvidenceKind.MEASURED_ZERO_SOURCE_VARIANCE
    assert measured_zero_source_variance_preserved(records) is True


def test_cross_channel_zero_does_not_claim_measured_source_variance():
    records = build_covariance_records(_validated_p1a())
    cross_channel_zero = next(
        record
        for record in records
        if record.domain is CovarianceDomain.CROSS_CHANNEL_RESIDUAL
        and record.source_values == (0.0,)
    )
    assert cross_channel_zero.variance_candidates == (None,)
    assert measured_zero_source_variance_preserved(records) is False


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
        claims=_claims(),
        descriptor_input=_descriptor_input(),
        p2_claims_input=_claims_input(),
        provenance_inputs=(
            _descriptor_input(),
            p1a.input_ref,
            mapping.manifest_input,
            _claims_input(),
            mapping.selected_inputs[0],
        ),
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


# ─── P2C-A NEW TESTS ────────────────────────────────────────────────────────


def test_covariance_status_rejects_plain_string():
    """F01: status field must be CovarianceStatus enum, not str."""
    records = build_covariance_records(_validated_p1a())
    first = records[0]
    with pytest.raises(ContractValidationError, match="status"):
        dataclasses.replace(first, status="MEASURED_ZERO_SOURCE_VARIANCE")


def test_covariance_builder_uses_closed_statuses():
    """F01: builder must produce CovarianceStatus instances, not plain strings."""
    records = build_covariance_records(_validated_p1a())
    for record in records:
        assert type(record.status) is CovarianceStatus


def test_covariance_provenance_context_must_match():
    """F02: all provenance items must share the record's validation_context."""
    p1a = _validated_p1a()
    records = build_covariance_records(p1a)
    first = records[0]  # PHYSICAL_EVIDENCE context
    # Build a ProvenanceRef with a different context
    bad_ref = ProvenanceRef(
        source_id="test",
        schema="test-schema",
        sha256=SHA_A,
        relative_logical_path="tests/source.json",
        path_kind=PathKind.VERSIONED_REPOSITORY_PATH,
        validation_context=ValidationContext.OFFLINE_REPLAY,  # wrong
        claim_strength=ClaimStrength.STRUCTURAL_POLICY,
        limitations=("SYNTHETIC_TEST_ONLY",),
    )
    with pytest.raises(ContractValidationError, match="provenance context mismatch"):
        dataclasses.replace(first, provenance=(bad_ref,))


def test_covariance_value_lengths_must_match():
    """F03: source_values and variance_candidates must have equal length."""
    p1a = _validated_p1a()
    records = build_covariance_records(p1a)
    first = records[0]  # dim=3
    with pytest.raises(ContractValidationError, match="length mismatch"):
        dataclasses.replace(first, variance_candidates=(0.0,))  # len=1 vs len=3


def test_covariance_domain_dimension_must_match():
    """F03: both tuples must have the exact dimension for their domain."""
    p1a = _validated_p1a()
    records = build_covariance_records(p1a)
    first = records[0]  # POSE_POSITION_SOURCE_DISPERSION, dim=3
    with pytest.raises(ContractValidationError):
        # length matches each other but wrong for domain (dim=3 required, 2 given)
        dataclasses.replace(
            first,
            source_values=(0.0, 0.0),
            variance_candidates=(0.0, 0.0),
        )


def test_covariance_empty_value_tuple_is_rejected():
    """F03: empty tuples are never allowed."""
    p1a = _validated_p1a()
    records = build_covariance_records(p1a)
    first = records[0]
    with pytest.raises(ContractValidationError):
        dataclasses.replace(
            first,
            source_values=(),
            variance_candidates=(),
        )


def test_ros_si_matrix_is_rejected_for_physical_context():
    """F04: ros_si_matrix must always be None — not just for PHYSICAL_EVIDENCE."""
    p1a = _validated_p1a()
    records = build_covariance_records(p1a)
    physical = next(r for r in records if r.validation_context is ValidationContext.PHYSICAL_EVIDENCE)
    with pytest.raises(ContractValidationError, match="ROS SI matrix"):
        dataclasses.replace(physical, ros_si_matrix=[[1, 0], [0, 1]])


def test_ros_si_matrix_is_rejected_for_replay_context():
    """F04: ros_si_matrix prohibited for OFFLINE_REPLAY too."""
    p1a = _validated_p1a()
    records = build_covariance_records(p1a)
    # All current records are PHYSICAL_EVIDENCE; mutate context to replay
    base = records[0]
    # We must build a replay-context provenance ref for F02 compliance
    replay_ref = ProvenanceRef(
        source_id="test",
        schema="test-schema",
        sha256=SHA_A,
        relative_logical_path="tests/source.json",
        path_kind=PathKind.VERSIONED_REPOSITORY_PATH,
        validation_context=ValidationContext.OFFLINE_REPLAY,
        claim_strength=ClaimStrength.STRUCTURAL_POLICY,
        limitations=("SYNTHETIC_TEST_ONLY",),
    )
    with pytest.raises(ContractValidationError, match="ROS SI matrix"):
        dataclasses.replace(
            base,
            validation_context=ValidationContext.OFFLINE_REPLAY,
            provenance=(replay_ref,),
            ros_si_matrix=[[1, 0], [0, 1]],
        )


def test_ros_si_matrix_is_rejected_for_simulation_context():
    """F04: ros_si_matrix prohibited for SIMULATION_POLICY too."""
    p1a = _validated_p1a()
    records = build_covariance_records(p1a)
    base = records[0]
    sim_ref = ProvenanceRef(
        source_id="test",
        schema="test-schema",
        sha256=SHA_A,
        relative_logical_path="tests/source.json",
        path_kind=PathKind.VERSIONED_REPOSITORY_PATH,
        validation_context=ValidationContext.SIMULATION_POLICY,
        claim_strength=ClaimStrength.STRUCTURAL_POLICY,
        limitations=("SYNTHETIC_TEST_ONLY",),
    )
    with pytest.raises(ContractValidationError, match="ROS SI matrix"):
        dataclasses.replace(
            base,
            validation_context=ValidationContext.SIMULATION_POLICY,
            provenance=(sim_ref,),
            ros_si_matrix=[[1, 0], [0, 1]],
        )


def test_frame_contract_rejects_cross_context_semantics():
    """F05: mixing semantics across contexts is rejected."""
    p1a = _validated_p1a()
    frames = build_frame_contracts(p1a=p1a, mapping=_mapping(), policy_input=_input("policy"))
    physical = next(f for f in frames if f.validation_context is ValidationContext.PHYSICAL_EVIDENCE)
    # REPLAY semantics in PHYSICAL_EVIDENCE context
    with pytest.raises(ContractValidationError, match="frame policy"):
        dataclasses.replace(
            physical,
            source_semantics=SemanticStatus.REPLAY_POLICY_CANDIDATE,
        )


def test_frame_contract_rejects_structural_only_context():
    """F05: STRUCTURAL_ONLY context is not valid for FrameContract."""
    p1a = _validated_p1a()
    frames = build_frame_contracts(p1a=p1a, mapping=_mapping(), policy_input=_input("policy"))
    physical = next(f for f in frames if f.validation_context is ValidationContext.PHYSICAL_EVIDENCE)
    ref = physical.provenance[0]
    structural_ref = ProvenanceRef(
        source_id=ref.source_id,
        schema=ref.schema,
        sha256=ref.sha256,
        relative_logical_path=ref.relative_logical_path,
        path_kind=ref.path_kind,
        validation_context=ValidationContext.STRUCTURAL_ONLY,
        claim_strength=ref.claim_strength,
        limitations=ref.limitations,
    )
    with pytest.raises(ContractValidationError, match="frame policy"):
        dataclasses.replace(
            physical,
            validation_context=ValidationContext.STRUCTURAL_ONLY,
            provenance=(structural_ref,),
        )


def _make_evidence_set(**overrides):
    """Build a valid ContractEvidenceSet for mutation tests."""
    p1a = _validated_p1a()
    mapping = _mapping()
    policy = _input("policy")
    frames = build_frame_contracts(p1a=p1a, mapping=mapping, policy_input=policy)
    covariance = build_covariance_records(p1a)
    defaults = dict(
        schema_version="2.2.1-p2a",
        p1a=p1a,
        mapping=mapping,
        frames=frames,
        covariance=covariance,
        claims=_claims(),
        descriptor_input=_descriptor_input(),
        p2_claims_input=_claims_input(),
        provenance_inputs=(
            _descriptor_input(),
            p1a.input_ref,
            mapping.manifest_input,
            _claims_input(),
            mapping.selected_inputs[0],
        ),
    )
    defaults.update(overrides)
    return ContractEvidenceSet(**defaults)


def test_duplicate_claim_names_with_same_value_are_rejected():
    """F11: duplicate claim name is rejected even when value is identical."""
    from src.navigation.odometry_contract_r2_p2a.contract import Claim
    claims = _claims()
    first = claims[0]
    duplicate = Claim(name=first.name, value=first.value, context=first.context)
    with pytest.raises(ContractValidationError, match="unique"):
        _make_evidence_set(claims=claims + (duplicate,))


def test_duplicate_claim_names_with_different_values_are_rejected():
    """F11: duplicate claim name is rejected even when values differ."""
    from src.navigation.odometry_contract_r2_p2a.contract import Claim
    claims = _claims()
    first = claims[0]
    conflict = Claim(name=first.name, value=not first.value, context=first.context)
    with pytest.raises(ContractValidationError, match="unique"):
        _make_evidence_set(claims=claims + (conflict,))


def test_duplicate_provenance_source_ids_are_rejected():
    """F12: duplicate source_id in provenance_inputs is rejected."""
    p1a = _validated_p1a()
    mapping = _mapping()
    dup = mapping.selected_inputs[0]
    with pytest.raises(ContractValidationError, match="unique"):
        _make_evidence_set(
            provenance_inputs=(
                _input("r2-p0a-evidence-descriptor"),
                p1a.input_ref,
                mapping.manifest_input,
                _input("r2-p2a-claims-ledger"),
                dup,
                dup,  # duplicate
            )
        )


def test_missing_descriptor_provenance_is_rejected():
    """F13: r2-p0a-evidence-descriptor must be in provenance_inputs."""
    p1a = _validated_p1a()
    mapping = _mapping()
    with pytest.raises(ContractValidationError, match="mismatch"):
        _make_evidence_set(
            provenance_inputs=(
                # missing r2-p0a-evidence-descriptor
                p1a.input_ref,
                mapping.manifest_input,
                _input("r2-p2a-claims-ledger"),
                mapping.selected_inputs[0],
            )
        )


def test_missing_claims_ledger_provenance_is_rejected():
    """F13: r2-p2a-claims-ledger must be in provenance_inputs."""
    p1a = _validated_p1a()
    mapping = _mapping()
    with pytest.raises(ContractValidationError, match="mismatch"):
        _make_evidence_set(
            provenance_inputs=(
                _input("r2-p0a-evidence-descriptor"),
                p1a.input_ref,
                mapping.manifest_input,
                # missing r2-p2a-claims-ledger
                mapping.selected_inputs[0],
            )
        )


def test_missing_selected_mapping_source_is_rejected():
    """F13: every selected mapping source must appear in provenance_inputs."""
    p1a = _validated_p1a()
    mapping = _mapping()
    with pytest.raises(ContractValidationError, match="mismatch"):
        _make_evidence_set(
            provenance_inputs=(
                _input("r2-p0a-evidence-descriptor"),
                p1a.input_ref,
                mapping.manifest_input,
                _input("r2-p2a-claims-ledger"),
                # missing mapping.selected_inputs[0]
            )
        )


def test_extra_provenance_source_is_rejected():
    """F13: extra sources not in the required set are rejected."""
    p1a = _validated_p1a()
    mapping = _mapping()
    with pytest.raises(ContractValidationError, match="mismatch"):
        _make_evidence_set(
            provenance_inputs=(
                _input("r2-p0a-evidence-descriptor"),
                p1a.input_ref,
                mapping.manifest_input,
                _input("r2-p2a-claims-ledger"),
                mapping.selected_inputs[0],
                _input("unexpected-extra"),
            )
        )


def test_complete_material_provenance_is_accepted():
    """F13: exactly the required 5-item provenance set is accepted."""
    evidence = _make_evidence_set()
    assert isinstance(evidence, ContractEvidenceSet)


def test_covariance_domain_policy_is_typed_and_immutable():
    assert type(COVARIANCE_DOMAIN_POLICY) is MappingProxyType
    assert set(COVARIANCE_DOMAIN_POLICY) == set(CovarianceDomain)
    assert all(type(item) is CovarianceShapePolicy for item in COVARIANCE_DOMAIN_POLICY.values())
    with pytest.raises(TypeError):
        COVARIANCE_DOMAIN_POLICY[CovarianceDomain.CROSS_CHANNEL_RESIDUAL] = object()
    with pytest.raises(dataclasses.FrozenInstanceError):
        COVARIANCE_DOMAIN_POLICY[CovarianceDomain.CROSS_CHANNEL_RESIDUAL].dimension = 2


@pytest.mark.parametrize("domain", list(CovarianceDomain))
def test_covariance_builder_obeys_domain_shape_policy(domain):
    records = [item for item in build_covariance_records(_validated_p1a()) if item.domain is domain]
    assert records
    policy = COVARIANCE_DOMAIN_POLICY[domain]
    assert all(len(item.source_values) == policy.dimension for item in records)


def test_covariance_policy_rejects_bool_and_wrong_none_pattern():
    record = build_covariance_records(_validated_p1a())[0]
    with pytest.raises(ContractValidationError):
        dataclasses.replace(record, source_values=(True, 1.0, 1.0))
    with pytest.raises(ContractValidationError, match="finite non-negative"):
        dataclasses.replace(record, source_values=(None, 1.0, 1.0))


def test_frame_context_policy_is_typed_and_immutable():
    assert type(FRAME_CONTEXT_POLICY) is MappingProxyType
    assert ValidationContext.STRUCTURAL_ONLY not in FRAME_CONTEXT_POLICY
    with pytest.raises(TypeError):
        FRAME_CONTEXT_POLICY[ValidationContext.STRUCTURAL_ONLY] = object()
    with pytest.raises(dataclasses.FrozenInstanceError):
        FRAME_CONTEXT_POLICY[ValidationContext.PHYSICAL_EVIDENCE].classifications = ()


@pytest.mark.parametrize("context", list(FRAME_CONTEXT_POLICY))
def test_frame_policy_rejects_each_changed_field(context):
    frames = build_frame_contracts(
        p1a=_validated_p1a(), mapping=_mapping(), policy_input=_input("policy")
    )
    frame = next(item for item in frames if item.validation_context is context)
    replacements = {
        "source_semantics": SemanticStatus.UNRESOLVED,
        "child_semantics": SemanticStatus.UNRESOLVED,
        "translation_scale": ScaleStatus.UNRESOLVED,
        "yaw_scale": ScaleStatus.UNRESOLVED,
        "translation_units": UnitStatus.SOURCE_UNITS_UNRESOLVED,
        "yaw_units": UnitStatus.YAW_SPEED_RAD_S_ONLY,
        "time_policy": TimeDomainPolicy.UNRESOLVED_FOR_ROS_HEADER,
        "boot_policy": BootDomainPolicy.PER_BOOT_NO_CROSS_BOOT_CONCATENATION,
        "source_channel": SourceChannelStatus.UNRESOLVED,
        "classifications": (FrameClassification.UNRESOLVED_ALIAS,),
    }
    for field, candidate in replacements.items():
        if candidate == getattr(frame, field):
            candidate = (
                (FrameClassification.UNRESOLVED_ALIAS,)
                if field == "classifications"
                else next(value for value in type(candidate) if value != candidate)
            )
        with pytest.raises(ContractValidationError, match="frame policy"):
            dataclasses.replace(frame, **{field: candidate})


@pytest.mark.parametrize("field", ["schema", "sha256", "logical_path", "validation_context", "claim_strength", "limitations"])
def test_descriptor_material_substitution_is_rejected(field):
    descriptor = _descriptor_input()
    replacements = {
        "schema": "other-schema", "sha256": SHA_A, "logical_path": "tests/other.json",
        "validation_context": ValidationContext.OFFLINE_REPLAY,
        "claim_strength": ClaimStrength.STRUCTURAL_POLICY,
        "limitations": ("OTHER",),
    }
    substitute = dataclasses.replace(descriptor, **{field: replacements[field]})
    with pytest.raises(ContractValidationError, match="descriptor input contract|mismatched"):
        _make_evidence_set(provenance_inputs=(substitute,) + _make_evidence_set().provenance_inputs[1:])


def test_legacy_material_ids_are_rejected():
    with pytest.raises(ContractValidationError, match="descriptor input contract"):
        _make_evidence_set(descriptor_input=dataclasses.replace(_descriptor_input(), source_id="descriptor"))
    with pytest.raises(ContractValidationError, match="claims ledger input contract"):
        _make_evidence_set(p2_claims_input=dataclasses.replace(_claims_input(), source_id="p2-claims"))


@pytest.mark.parametrize("material", ["claims", "p1a", "mapping_manifest", "selected_source"])
@pytest.mark.parametrize("field", ["schema", "sha256", "logical_path", "validation_context", "claim_strength", "limitations"])
def test_non_descriptor_material_substitution_is_rejected(material, field):
    evidence = _make_evidence_set()
    sources = {
        "claims": evidence.p2_claims_input,
        "p1a": evidence.p1a.input_ref,
        "mapping_manifest": evidence.mapping.manifest_input,
        "selected_source": evidence.mapping.selected_inputs[0],
    }
    source = sources[material]
    replacements = {
        "schema": "other-schema", "sha256": (SHA_B if source.sha256 == SHA_A else SHA_A), "logical_path": "tests/other.json",
        "validation_context": (ValidationContext.STRUCTURAL_ONLY if source.validation_context is not ValidationContext.STRUCTURAL_ONLY else ValidationContext.PHYSICAL_EVIDENCE),
        "claim_strength": (ClaimStrength.STRUCTURAL_POLICY if source.claim_strength is not ClaimStrength.STRUCTURAL_POLICY else ClaimStrength.PRESERVED_PHYSICAL_EVIDENCE),
        "limitations": ("OTHER",),
    }
    substitute = dataclasses.replace(source, **{field: replacements[field]})
    provenance = tuple(substitute if item.source_id == source.source_id else item for item in evidence.provenance_inputs)
    with pytest.raises(ContractValidationError, match=r"mismatched=\("):
        _make_evidence_set(provenance_inputs=provenance)


@pytest.mark.parametrize(
    "field,value",
    [
        ("selected_inputs", ()),
        ("source_ids", ()),
        ("file_categories", ()),
        ("selected_source_categories", ()),
        ("session_ids", ()),
    ],
)
def test_mapping_binding_rejects_empty_direct_construction(field, value):
    with pytest.raises(ContractValidationError):
        dataclasses.replace(_mapping(), **{field: value})


def test_mapping_binding_preserves_category_order_and_rejects_mismatch():
    binding = _mapping()
    assert binding.selected_source_categories == (("synthetic-source", "FRAME_INVENTORY"),)
    with pytest.raises(ContractValidationError):
        dataclasses.replace(binding, selected_source_categories=(("synthetic-source", "UNKNOWN"),))


@pytest.mark.parametrize("mutation", ["missing_category", "unknown_category", "unused_category"])
def test_mapping_manifest_categories_fail_closed(tmp_path, mutation):
    mapping_root = tmp_path / "mapping"
    mapping_root.mkdir()
    source = mapping_root / "source.json"
    source.write_bytes(b"{}\n")
    source_hash = hashlib.sha256(source.read_bytes()).hexdigest()
    manifest = mapping_root / "manifest.sha256"
    manifest.write_text(f"{source_hash}  source.json\n", encoding="utf-8")
    manifest_hash = hashlib.sha256(manifest.read_bytes()).hexdigest()
    document = {
        "schema_version": "1.0.0-p2a-mapping",
        "contains_raw_data": False,
        "contains_personal_absolute_paths": False,
        "physical_validation_claim": False,
        "source_ids": ["source"], "session_ids": ["session"], "take_ids": ["take"],
        "file_categories": ["FRAME_INVENTORY"],
        "observed_frame_ids": ["utlidar_lidar"], "observed_topic_ids": ["/scan"],
        "allowed_claims": ["TOPIC_VOCABULARY"],
        "prohibited_claims": ["PHYSICAL_FRAME_SEMANTICS_VERIFIED", "PHYSICAL_SCALE_VERIFIED", "RIGHT_HANDED_MODEL_VERIFIED", "ROS_REP_103_MODEL_VERIFIED", "UNITY_SCALE_MODEL_VERIFIED"],
        "input_manifests": [{"logical_path": "manifest.sha256", "sha256": manifest_hash}],
        "selected_sources": [{"source_id": "source", "category": "FRAME_INVENTORY", "logical_path": "source.json", "sha256": source_hash, "manifest_path": "manifest.sha256", "manifest_entry_path": "source.json", "validation_context": "OFFLINE_REPLAY", "claim_strength": "PRESERVED_MAPPING_REFERENCE"}],
        "map_artifacts": [],
    }
    if mutation == "missing_category": del document["selected_sources"][0]["category"]
    elif mutation == "unknown_category": document["selected_sources"][0]["category"] = "UNKNOWN"
    else: document["file_categories"].append("UNUSED")
    manifest_path = tmp_path / "mapping.json"
    manifest_path.write_text(json.dumps(document), encoding="utf-8")
    with pytest.raises(ContractValidationError):
        validate_mapping_manifest(document, manifest_path=manifest_path, mapping_root=mapping_root)


def test_p1a_snapshot_is_independent_and_returns_fresh_documents():
    original = synthetic_p1a()
    validated = validate_p1a_document(original, input_sha256=SHA_A)
    original["p1_bundle"]["stationary"][0]["stddev"][0] = 999.0
    first = validated.document
    assert first["p1_bundle"]["stationary"][0]["stddev"][0] == 1.0
    first["p1_bundle"]["dynamic_residuals"][0]["residual_value"] = 999.0
    assert validated.document["p1_bundle"]["dynamic_residuals"][0]["residual_value"] == 0.0


@pytest.mark.parametrize(
    "field",
    ["evidence_id", "session_id", "segment_name", "status", "channel", "residual_type", "unit", "sample_count", "residual_value"],
)
def test_dynamic_residual_missing_field_fails_closed(field):
    document = synthetic_p1a()
    del document["p1_bundle"]["dynamic_residuals"][0][field]
    with pytest.raises(ContractValidationError):
        validate_p1a_document(document, input_sha256=SHA_A)


@pytest.mark.parametrize(
    "field", ["evidence_id", "session_id", "phase", "status", "sample_count", "yaw_speed_rmse_rad_s"]
)
def test_yaw_residual_missing_field_fails_closed(field):
    document = synthetic_p1a()
    del document["yaw_speed_residuals"][0][field]
    with pytest.raises(ContractValidationError):
        validate_p1a_document(document, input_sha256=SHA_A)


def test_load_and_validate_p1a_uses_file_bytes_once(tmp_path, monkeypatch):
    path = tmp_path / "p1a.json"
    path.write_text(json.dumps(synthetic_p1a()), encoding="utf-8")
    calls = 0
    original = type(path).read_bytes
    def counted(self):
        nonlocal calls
        calls += 1
        return original(self)
    monkeypatch.setattr(type(path), "read_bytes", counted)
    assert load_and_validate_p1a(path).input_ref.sha256
    assert calls == 1


def test_write_documents_is_transactional_on_failure(tmp_path, monkeypatch):
    from src.navigation.odometry_contract_r2_p2a import report
    documents = {name: ({"name": name} if name.endswith(".json") else "report\n") for name in OUTPUT_NAMES}
    output = tmp_path / "output"
    original = report._write_output_file
    calls = 0
    def fail_after_first(path, payload):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("controlled write failure")
        original(path, payload)
    monkeypatch.setattr(report, "_write_output_file", fail_after_first)
    with pytest.raises(OSError, match="controlled write failure"):
        write_documents(output, documents)
    assert not output.exists()
    assert list(tmp_path.glob(".output.tmp-*")) == []


def test_write_documents_preserves_existing_output(tmp_path):
    output = tmp_path / "output"
    output.mkdir()
    marker = output / "marker.txt"
    marker.write_text("preserved", encoding="utf-8")
    with pytest.raises(ContractValidationError, match="must not exist"):
        write_documents(output, {})
    assert marker.read_text(encoding="utf-8") == "preserved"


def test_mapping_correlation_is_structural_only_and_non_authoritative():
    correlation = _documents()["R2_P2A_MAPPING_FRAME_CORRELATION.json"]
    assert correlation["policy_kind"] == "STRUCTURAL_POLICY_ONLY"
    assert correlation["selected_source_content_parsed"] is False
    assert correlation["frame_relations_derived_from_content"] is False
    assert correlation["physical_frame_authority"] is False
    assert "derived_from_mapping_manifest_sha256" not in correlation


def test_mapping_metadata_change_does_not_claim_content_derived_relations():
    mapping = _mapping()
    changed_input = dataclasses.replace(
        mapping.selected_inputs[0], limitations=("CHANGED_SYNTHETIC_METADATA",)
    )
    changed = dataclasses.replace(mapping, selected_inputs=(changed_input,))
    original_output = _documents(mapping)["R2_P2A_MAPPING_FRAME_CORRELATION.json"]
    changed_output = _documents(changed)["R2_P2A_MAPPING_FRAME_CORRELATION.json"]
    assert original_output == changed_output
    assert changed_output["frame_relations_derived_from_content"] is False


def test_mapping_vocabulary_separates_configured_and_manifest_observed_frames():
    mapping = dataclasses.replace(
        _mapping(),
        observed_frame_ids=(
            "utlidar_lidar",
            "unitree_secondary_imu",
            "unitree_lowstate_imu",
            "kiss_odom_lidar",
        ),
    )
    vocabulary = _documents(mapping)["R2_P2A_FRAME_VOCABULARY.json"]
    entries = vocabulary["entries"]
    configured = tuple(
        entry["frame_id"]
        for entry in entries
        if entry["provenance_kind"] == "CONFIGURED_CONTRACT_NAME"
    )
    observed = tuple(
        entry["frame_id"]
        for entry in entries
        if entry["provenance_kind"] == "MANIFEST_OBSERVED_FRAME_ID"
    )
    assert configured == ("map", "odom", "base_link")
    assert observed == tuple(sorted(mapping.observed_frame_ids))
    assert "unitree_lowstate_imu" in observed
    assert "unitree_secondary_imu" in observed


def test_mapping_vocabulary_changes_with_manifest_observed_frames():
    original = _mapping()
    changed = dataclasses.replace(original, observed_frame_ids=("synthetic_new_frame",))
    assert canonical_json(
        _documents(original)["R2_P2A_FRAME_VOCABULARY.json"]
    ) != canonical_json(_documents(changed)["R2_P2A_FRAME_VOCABULARY.json"])


def test_mapping_vocabulary_rejects_duplicate_observed_frames():
    with pytest.raises(ContractValidationError, match="observed_frame_ids"):
        dataclasses.replace(_mapping(), observed_frame_ids=("duplicate", "duplicate"))


def test_claims_are_derived_from_validated_arguments_and_keep_boundaries_false():
    import src.navigation.odometry_contract_r2_p2a.contract as contract_module

    assert not hasattr(contract_module, "EXPECTED_CLAIMS")
    p1a = _validated_p1a()
    mapping = _mapping()
    frames = build_frame_contracts(p1a=p1a, mapping=mapping, policy_input=_input("policy"))
    covariance = build_covariance_records(p1a)
    claims = build_claims(
        p1a=p1a,
        mapping=mapping,
        frames=frames,
        covariance=covariance,
        mapping_vocabulary=build_mapping_vocabulary(mapping),
    )
    values = {claim.name: claim.value for claim in claims}
    assert values["MAPPING_MANIFEST_REFERENCE_STRUCTURALLY_VALID"] is True
    assert values["MAPPING_INPUT_HASH_REFERENCES_WELL_FORMED"] is True
    assert values["MAPPING_SELECTED_SOURCE_CONTENT_PARSED"] is False
    assert values["MAPPING_FRAME_RELATIONS_DERIVED_FROM_CONTENT"] is False
    assert values["MAPPING_VOCABULARY_DERIVED_FROM_MANIFEST"] is True
    assert values["FRAME_VALIDATION_CONTEXT_TYPES_EXACT"] is True
    assert values["CURRENT_COVARIANCE_VALUES_FINITE"] is True
    assert values["MEASURED_ZERO_PRESERVED"] is False
    assert "MAPPING_INPUTS_HASH_BOUND" not in values
    assert "ENUM_BYPASS_CLOSED" not in values
    assert "NUMERIC_OVERFLOW_CLOSED" not in values
    for name in (
        "OFFLINE_REPLAY_ADAPTER_READY",
        "OFFLINE_REPLAY_EXECUTION_VALIDATED",
        "SIMULATION_MODEL_BOUND",
        "SIMULATION_ADAPTER_IMPLEMENTED",
        "SIMULATION_EXECUTION_READY",
        "PHYSICAL_ODOM_PUBLICATION_READY",
        "PHYSICAL_TF_PUBLICATION_READY",
    ):
        assert values[name] is False
    assert values["AUTHORITATIVE_SOURCE_CHANNEL"] is None
    assert values["PREFERRED_ANALYSIS_CHANNEL"] is None
    bad_p1a = dataclasses.replace(
        p1a, input_ref=dataclasses.replace(p1a.input_ref, source_id="synthetic-p1a")
    )
    bad_values = {
        claim.name: claim.value
        for claim in build_claims(
            p1a=bad_p1a,
            mapping=mapping,
            frames=frames,
            covariance=covariance,
            mapping_vocabulary=build_mapping_vocabulary(mapping),
        )
    }
    assert bad_values["P1A_INPUT_REFERENCE_STRUCTURALLY_VALID"] is False
    assert bad_values["P2A_CONTRACT_STRUCTURALLY_READY"] is False


def test_synthetic_hashes_do_not_elevate_a_material_binding_claim():
    p1a = _validated_p1a()
    mapping = _mapping()
    synthetic_mapping = dataclasses.replace(
        mapping,
        manifest_input=dataclasses.replace(mapping.manifest_input, sha256=SHA_A),
        selected_inputs=tuple(
            dataclasses.replace(item, sha256=f"{index + 1:064x}")
            for index, item in enumerate(mapping.selected_inputs)
        ),
    )
    frames = build_frame_contracts(
        p1a=p1a,
        mapping=synthetic_mapping,
        policy_input=_claims_input(),
    )
    claims = build_claims(
        p1a=p1a,
        mapping=synthetic_mapping,
        frames=frames,
        covariance=build_covariance_records(p1a),
        mapping_vocabulary=build_mapping_vocabulary(synthetic_mapping),
    )
    values = {claim.name: claim.value for claim in claims}
    assert values["MAPPING_INPUT_HASH_REFERENCES_WELL_FORMED"] is True
    assert "MAPPING_INPUTS_HASH_BOUND" not in values
    assert "MAPPING_INPUTS_MANIFEST_ATTESTED" not in values


def test_readiness_derives_structural_false_from_canonical_claims():
    p1a = _validated_p1a()
    bad_p1a = dataclasses.replace(
        p1a,
        input_ref=dataclasses.replace(p1a.input_ref, source_id="synthetic-p1a"),
    )
    mapping = _mapping()
    policy = _claims_input()
    frames = build_frame_contracts(
        p1a=bad_p1a,
        mapping=mapping,
        policy_input=policy,
    )
    covariance = build_covariance_records(bad_p1a)
    claims = build_claims(
        p1a=bad_p1a,
        mapping=mapping,
        frames=frames,
        covariance=covariance,
        mapping_vocabulary=build_mapping_vocabulary(mapping),
    )
    evidence = ContractEvidenceSet(
        schema_version="2.2.1-p2a",
        p1a=bad_p1a,
        mapping=mapping,
        frames=frames,
        covariance=covariance,
        claims=claims,
        descriptor_input=_descriptor_input(),
        p2_claims_input=policy,
        provenance_inputs=(
            _descriptor_input(),
            bad_p1a.input_ref,
            mapping.manifest_input,
            policy,
        )
        + mapping.selected_inputs,
    )
    assert assess_readiness(evidence).p2a_contract_structurally_ready is False


def test_report_views_use_the_canonical_claim_values():
    documents = _documents()
    claims = {
        claim.name: claim.value
        for claim in documents["R2_P2A_CLAIMS_LEDGER.json"]["claims"]
    }
    result = documents["R2_P2A_RESULT.json"]
    publication = documents["R2_P2A_COVARIANCE_PUBLICATION_CONTRACT.json"]
    readiness = documents["R2_P2A_READINESS.json"]["readiness"]
    assert result["p2a_contract_structurally_ready"] is claims[
        "P2A_CONTRACT_STRUCTURALLY_READY"
    ]
    assert result["mapping_manifest_reference_structurally_valid"] is claims[
        "MAPPING_MANIFEST_REFERENCE_STRUCTURALLY_VALID"
    ]
    assert result["mapping_input_hash_references_well_formed"] is claims[
        "MAPPING_INPUT_HASH_REFERENCES_WELL_FORMED"
    ]
    assert publication["measured_zero_preserved"] is claims[
        "MEASURED_ZERO_PRESERVED"
    ]
    assert readiness.p2a_contract_structurally_ready is claims[
        "P2A_CONTRACT_STRUCTURALLY_READY"
    ]


def test_synthetic_mapping_does_not_assert_material_loader_verification():
    report = _documents()["R2_P2A_REPORT.md"]
    normalized = " ".join(report.split())
    assert "Material file hashes are verified by the loader" not in normalized
    assert "do not attest that external material bytes were read or verified" in normalized


def test_correlation_and_readiness_represent_canonical_claim_values():
    documents = _documents()
    claims = {
        claim.name: claim.value
        for claim in documents["R2_P2A_CLAIMS_LEDGER.json"]["claims"]
    }
    correlation = documents["R2_P2A_MAPPING_FRAME_CORRELATION.json"]
    readiness = documents["R2_P2A_READINESS.json"]["readiness"]
    assert correlation["selected_source_content_parsed"] is claims[
        "MAPPING_SELECTED_SOURCE_CONTENT_PARSED"
    ]
    assert correlation["frame_relations_derived_from_content"] is claims[
        "MAPPING_FRAME_RELATIONS_DERIVED_FROM_CONTENT"
    ]
    for readiness_field, claim_name in (
        ("physical_odom_publication_ready", "PHYSICAL_ODOM_PUBLICATION_READY"),
        ("physical_tf_publication_ready", "PHYSICAL_TF_PUBLICATION_READY"),
        ("offline_replay_adapter_ready", "OFFLINE_REPLAY_ADAPTER_READY"),
        ("offline_replay_execution_validated", "OFFLINE_REPLAY_EXECUTION_VALIDATED"),
        ("simulation_model_bound", "SIMULATION_MODEL_BOUND"),
        ("simulation_adapter_ready", "SIMULATION_ADAPTER_IMPLEMENTED"),
        ("simulation_execution_ready", "SIMULATION_EXECUTION_READY"),
    ):
        assert getattr(readiness, readiness_field) is claims[claim_name]


def test_correlation_follows_a_mutated_canonical_claim(monkeypatch):
    import src.navigation.odometry_contract_r2_p2a.contract as contract_module
    import src.navigation.odometry_contract_r2_p2a.report as report_module

    original_build_claims = contract_module.build_claims

    def mutated_build_claims(**kwargs):
        return tuple(
            dataclasses.replace(claim, value=True)
            if claim.name == "MAPPING_SELECTED_SOURCE_CONTENT_PARSED"
            else claim
            for claim in original_build_claims(**kwargs)
        )

    monkeypatch.setattr(contract_module, "build_claims", mutated_build_claims)
    monkeypatch.setattr(report_module, "build_claims", mutated_build_claims)
    documents = _documents()
    claims = {
        claim.name: claim.value
        for claim in documents["R2_P2A_CLAIMS_LEDGER.json"]["claims"]
    }
    assert claims["MAPPING_SELECTED_SOURCE_CONTENT_PARSED"] is True
    assert documents["R2_P2A_MAPPING_FRAME_CORRELATION.json"][
        "selected_source_content_parsed"
    ] is True


def test_audit_findings_are_derived_and_h15_is_not_evaluated():
    import src.navigation.odometry_contract_r2_p2a.report as report_module

    assert not hasattr(report_module, "AUDIT_STATUSES")
    findings = _documents()["R2_P2A_AUDIT_FINDINGS.json"]["findings"]
    by_id = {finding["hypothesis_id"]: finding for finding in findings}
    assert tuple(by_id) == tuple(f"H{index}" for index in range(1, 16))
    assert by_id["H9"] == {
        "hypothesis_id": "H9",
        "closed": False,
        "status": "OPEN",
        "evidence": "MEASURED_ZERO_VARIANCE_CANDIDATE_PRESERVED",
        "remediation": "MATERIAL_EVIDENCE_NOT_DEMONSTRATED",
    }
    assert all(
        by_id[f"H{index}"]["status"] == "CLOSED"
        for index in tuple(range(1, 9)) + tuple(range(10, 15))
    )
    assert by_id["H15"] == {
        "hypothesis_id": "H15",
        "closed": None,
        "status": "NOT_EVALUATED",
        "evidence": "VERSIONED_UNIFICATION_STATE_VALIDATED_SEPARATELY",
        "remediation": "VERIFY_VERSIONED_AUTHORITY_STATE_IN_REPOSITORY_GATE",
    }


def test_generated_claims_match_versioned_ledger_semantically():
    repo_root = Path(__file__).resolve().parents[3]
    ledger_path = (
        repo_root
        / "docs"
        / "Operaciones_HIL"
        / "Evidencia"
        / "R2_P2A_CLAIMS_LEDGER.json"
    )
    versioned = json.loads(ledger_path.read_text(encoding="utf-8"))
    generated = json.loads(canonical_json(_documents()["R2_P2A_CLAIMS_LEDGER.json"]))
    assert generated == versioned


def test_unification_state_represents_local_unpublished_p2c_candidate():
    repo_root = Path(__file__).resolve().parents[3]
    state_path = repo_root / "docs" / "Arquitectura" / "unification-state.json"
    handoff_path = (
        repo_root / "docs" / "Arquitectura" / "UNIFICACION_RAMAS_Y_HANDOFF.md"
    )
    state = json.loads(state_path.read_text(encoding="utf-8"))
    handoff = handoff_path.read_text(encoding="utf-8")
    assert state["canonical_authority"] == "tsamaan/OttoGuide-Proyecto_SIP-Grupo6-UADE"
    assert state["mirror_staging"] == "LucasCap12/OttoGuide-Proyecto_SIP-Grupo6-G1-EDU"
    assert state["integration_branch"] == "review/orchestrator-unification"
    assert state["remote_integration_head"] == "ca3e8bed6d89316d4b9c2e3aa6bd209f6db5359e"
    assert state["canonical_review_sha"] == "ca3e8bed6d89316d4b9c2e3aa6bd209f6db5359e"
    assert state["mirror_review_sha"] == state["canonical_review_sha"]
    assert state["p2a_baseline_sha"] == "76ecfd782af4a401936076939e0c9c0b55718b4e"
    assert state["p2c_local_candidate_state"] == "LOCAL_UNCOMMITTED_WORKTREE"
    assert state["local_p2c_branch"] == (
        "feature/odom-tf-r2-p2-frame-semantics-covariance-contract"
    )
    assert state["local_p2c_base_head"] == state["p2a_baseline_sha"]
    assert state["p2c_base_sha"] == state["p2a_baseline_sha"]
    assert state["p2c_commit_sha"] is None
    assert state["p2c_remote_branch"] is None
    assert state["p2c_published"] is False
    assert state["p2c_next_checkpoint"] == (
        "MVP-ODOM-TF-R2-P2C-CLAIMS-STATE-R2-INDEPENDENT-AUDIT-R1"
    )
    assert state["source_heads"]["pilar-web"] == (
        "8a5803f5fd8f9bdb08faa5a8bc40a3a5dd709b73"
    )
    assert state["source_heads_status"] == "LIVE_READ_ONLY_VERIFIED_2026-08-15"
    assert state["branch_relations_snapshot"]["historical_snapshot"] is True
    assert state["canonical_default_branches_write"] == "PROHIBITED"
    assert state["main_relation_to_review"] == "NO_COMMON_ANCESTOR"
    assert state["main_policy"] == "DO_NOT_MERGE_OR_REBASE"
    assert "remote_authority" not in state
    assert "local_feature_sha" not in state
    assert "DYNAMIC_HANDOFF_CHECKPOINT" not in state_path.read_text(encoding="utf-8")
    for value in (
        "CANONICAL_AUTHORITY = tsamaan/OttoGuide-Proyecto_SIP-Grupo6-UADE",
        "REMOTE_INTEGRATION_HEAD = ca3e8bed6d89316d4b9c2e3aa6bd209f6db5359e",
        "LOCAL_P2C_BRANCH = feature/odom-tf-r2-p2-frame-semantics-covariance-contract",
        "P2C_LOCAL_CANDIDATE_STATE = LOCAL_UNCOMMITTED_WORKTREE",
        "P2C_COMMIT_SHA = null",
        "P2C_REMOTE_BRANCH = null",
        "P2C_PUBLISHED = false",
        "MAIN_POLICY = DO_NOT_MERGE_OR_REBASE",
    ):
        assert value in handoff
