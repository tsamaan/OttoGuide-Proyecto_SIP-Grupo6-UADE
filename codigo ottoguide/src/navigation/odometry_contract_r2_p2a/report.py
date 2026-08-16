"""Deterministic P2A document generation."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
from dataclasses import asdict, is_dataclass
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Mapping

from .contract import (
    EXECUTION_BLOCKERS,
    PHYSICAL_BLOCKERS,
    ContractEvidenceSet,
    assess_readiness,
    build_claims,
    build_covariance_records,
    build_frame_contracts,
    build_mapping_vocabulary,
)
from .inputs import MappingBinding, P1AValidation
from .models import (
    P2A_SCHEMA_VERSION,
    ClaimStrength,
    ContractValidationError,
    CovarianceDomain,
    CovarianceRecord,
    CovarianceStatus,
    FrameContract,
    ReadinessContract,
    ValidatedInput,
    ValidationContext,
)


OUTPUT_NAMES = (
    "R2_P2A_RESULT.json",
    "R2_P2A_AUDIT_FINDINGS.json",
    "R2_P2A_FRAME_VOCABULARY.json",
    "R2_P2A_FRAME_SEMANTICS_CONTRACT.json",
    "R2_P2A_MAPPING_EVIDENCE_BINDING.json",
    "R2_P2A_MAPPING_FRAME_CORRELATION.json",
    "R2_P2A_COVARIANCE_SOURCE_EVIDENCE.json",
    "R2_P2A_COVARIANCE_DOMAIN_MATRIX.json",
    "R2_P2A_COVARIANCE_PUBLICATION_CONTRACT.json",
    "R2_P2A_READINESS.json",
    "R2_P2A_BLOCKERS.json",
    "R2_P2A_CLAIMS_LEDGER.json",
    "R2_P2A_PROVENANCE.json",
    "R2_P2A_REPORT.md",
)

CLAIMS_LIMITATIONS = (
    "SOURCE_FRAME_SEMANTICS_PARTIAL",
    "CHILD_FRAME_ID_UNRESOLVED",
    "TRANSLATION_SCALE_UNRESOLVED",
    "YAW_SCALE_UNRESOLVED",
    "COVARIANCE_ROS_SI_MATRIX_UNAVAILABLE",
    "NO_FUTURE_HARDWARE_REVALIDATION_EXPECTED",
)


def jsonable(value: object) -> object:
    if isinstance(value, Enum):
        return value.value
    if is_dataclass(value):
        return jsonable(asdict(value))
    if isinstance(value, Mapping):
        return {str(key): jsonable(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [jsonable(item) for item in value]
    return value


def canonical_json(value: object) -> bytes:
    return (
        json.dumps(jsonable(value), indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    ).encode("utf-8")


def derive_audit_findings(
    *,
    evidence: ContractEvidenceSet,
    readiness: ReadinessContract,
    generated_utc: str,
) -> list[dict[str, object]]:
    if type(evidence) is not ContractEvidenceSet or type(readiness) is not ReadinessContract:
        raise ContractValidationError("audit findings require validated contracts")
    claims = {claim.name: claim.value for claim in evidence.claims}
    checks = {
        "H1": all(type(frame.validation_context) is ValidationContext for frame in evidence.frames),
        "H2": all(type(record.status) is CovarianceStatus for record in evidence.covariance),
        "H3": type(evidence.mapping) is MappingBinding,
        "H4": claims["MAPPING_MANIFEST_REFERENCE_STRUCTURALLY_VALID"] is True,
        "H5": claims["MAPPING_INPUT_HASH_REFERENCES_WELL_FORMED"] is True,
        "H6": evidence.p1a.input_ref.schema == "2.1.1-p1a",
        "H7": claims["CURRENT_COVARIANCE_VALUES_FINITE"] is True,
        "H8": all(
            type(record.source_values) is tuple
            and type(record.variance_candidates) is tuple
            for record in evidence.covariance
        ),
        "H9": claims["MEASURED_ZERO_PRESERVED"] is True,
        "H10": claims["CROSS_CHANNEL_EVIDENCE_SEPARATED"] is True,
        "H11": all(
            record.channel == "CROSS_CHANNEL"
            for record in evidence.covariance
            if record.domain is CovarianceDomain.TWIST_ANGULAR_YAW_RATE_RESIDUAL
        ),
        "H12": (
            claims["SIMULATION_POLICY_STRUCTURALLY_READY"] is True
            and readiness.simulation_model_bound is False
            and readiness.simulation_execution_ready is False
        ),
        "H13": readiness.p2a_contract_structurally_ready is True,
        "H14": _is_canonical_generated_utc(generated_utc),
    }
    evidence_labels = {
        "H1": "EXACT_VALIDATION_CONTEXT_ENUMS",
        "H2": "EXACT_COVARIANCE_STATUS_ENUMS",
        "H3": "STRUCTURAL_MAPPING_BINDING",
        "H4": "MAPPING_MANIFEST_REFERENCE_STRUCTURALLY_VALID",
        "H5": "MAPPING_INPUT_HASH_REFERENCES_WELL_FORMED",
        "H6": "P1A_SCHEMA_AND_INPUT_REFERENCE_STRUCTURALLY_VALID",
        "H7": "CURRENT_COVARIANCE_VALUES_FINITE",
        "H8": "EXACT_IMMUTABLE_COVARIANCE_TUPLES",
        "H9": "MEASURED_ZERO_VARIANCE_CANDIDATE_PRESERVED",
        "H10": "CROSS_CHANNEL_DOMAIN_SEPARATED",
        "H11": "YAW_RATE_RESIDUALS_CROSS_CHANNEL",
        "H12": "SIMULATION_POLICY_ONLY_NO_MODEL_OR_EXECUTION",
        "H13": "READINESS_FROM_VALIDATED_EVIDENCE_SET",
        "H14": "CANONICAL_INJECTED_RFC3339_UTC",
    }
    findings = [
        {
            "hypothesis_id": hypothesis_id,
            "closed": closed,
            "status": "CLOSED" if closed else "OPEN",
            "evidence": evidence_labels[hypothesis_id],
            "remediation": (
                "NONE_REQUIRED"
                if closed
                else "MATERIAL_EVIDENCE_NOT_DEMONSTRATED"
            ),
        }
        for hypothesis_id, closed in checks.items()
    ]
    findings.append(
        {
            "hypothesis_id": "H15",
            "closed": None,
            "status": "NOT_EVALUATED",
            "evidence": "VERSIONED_UNIFICATION_STATE_VALIDATED_SEPARATELY",
            "remediation": "VERIFY_VERSIONED_AUTHORITY_STATE_IN_REPOSITORY_GATE",
        }
    )
    return findings


def _is_canonical_generated_utc(value: object) -> bool:
    if type(value) is not str:
        return False
    try:
        datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ")
    except ValueError:
        return False
    return len(value) == 20


def build_documents(
    *,
    p1a: P1AValidation,
    mapping: MappingBinding,
    descriptor_input: ValidatedInput,
    p2_claims_input: ValidatedInput,
    generated_utc: str,
) -> dict[str, object]:
    frames = build_frame_contracts(
        p1a=p1a,
        mapping=mapping,
        policy_input=p2_claims_input,
    )
    covariance = build_covariance_records(p1a)
    mapping_vocabulary = build_mapping_vocabulary(mapping)
    claims = build_claims(
        p1a=p1a,
        mapping=mapping,
        frames=frames,
        covariance=covariance,
        mapping_vocabulary=mapping_vocabulary,
    )
    claim_values = {claim.name: claim.value for claim in claims}
    provenance_inputs = (
        descriptor_input,
        p1a.input_ref,
        mapping.manifest_input,
        p2_claims_input,
    ) + mapping.selected_inputs
    evidence = ContractEvidenceSet(
        schema_version=P2A_SCHEMA_VERSION,
        p1a=p1a,
        mapping=mapping,
        frames=frames,
        covariance=covariance,
        claims=claims,
        descriptor_input=descriptor_input,
        p2_claims_input=p2_claims_input,
        provenance_inputs=provenance_inputs,
    )
    readiness = assess_readiness(evidence)
    domain_matrix = []
    for domain in CovarianceDomain:
        records = [record for record in covariance if record.domain is domain]
        domain_matrix.append(
            {
                "domain": domain,
                "record_count": len(records),
                "channels": sorted({record.channel for record in records}),
                "units": sorted({record.unit for record in records}),
                "publication_ready": False,
                "ros_si_matrix": None,
            }
        )
    findings = derive_audit_findings(
        evidence=evidence,
        readiness=readiness,
        generated_utc=generated_utc,
    )
    mapping_binding = {
        "schema_version": P2A_SCHEMA_VERSION,
        "mapping_manifest_schema": mapping.manifest_input.schema,
        "mapping_manifest_sha256": mapping.manifest_input.sha256,
        "mapping_manifest_reference_structurally_valid": claim_values[
            "MAPPING_MANIFEST_REFERENCE_STRUCTURALLY_VALID"
        ],
        "mapping_input_hash_references_well_formed": claim_values[
            "MAPPING_INPUT_HASH_REFERENCES_WELL_FORMED"
        ],
        "source_ids": mapping.source_ids,
        "file_categories": mapping.file_categories,
        "selected_source_categories": mapping.selected_source_categories,
        "session_ids": mapping.session_ids,
        "take_ids": mapping.take_ids,
        "observed_frame_ids": mapping.observed_frame_ids,
        "observed_topic_ids": mapping.observed_topic_ids,
        "selected_sources": mapping.selected_inputs,
        "allowed_claims": mapping.allowed_claims,
        "prohibited_claims": mapping.prohibited_claims,
        "physical_validation_claim": False,
    }
    vocabulary = {
        "schema_version": P2A_SCHEMA_VERSION,
        "configured_contract_frames": ("map", "odom", "base_link"),
        "manifest_observed_frames": mapping.observed_frame_ids,
        "entries": mapping_vocabulary,
    }
    result = {
        "schema_version": P2A_SCHEMA_VERSION,
        "result": "MVP_ODOM_TF_R2_P2A_COMPLETE_WITH_LIMITATIONS",
        "generated_utc_injected": generated_utc,
        "robot_access_status": "PERMANENTLY_UNAVAILABLE",
        "future_hardware_revalidation": "NOT_EXPECTED",
        "p2a_contract_structurally_ready": claim_values[
            "P2A_CONTRACT_STRUCTURALLY_READY"
        ],
        "mapping_manifest_reference_structurally_valid": claim_values[
            "MAPPING_MANIFEST_REFERENCE_STRUCTURALLY_VALID"
        ],
        "mapping_input_hash_references_well_formed": claim_values[
            "MAPPING_INPUT_HASH_REFERENCES_WELL_FORMED"
        ],
        "mapping_selected_source_content_parsed": claim_values[
            "MAPPING_SELECTED_SOURCE_CONTENT_PARSED"
        ],
        "mapping_frame_relations_derived_from_content": claim_values[
            "MAPPING_FRAME_RELATIONS_DERIVED_FROM_CONTENT"
        ],
        "mapping_vocabulary_derived_from_manifest": claim_values[
            "MAPPING_VOCABULARY_DERIVED_FROM_MANIFEST"
        ],
        "p1a_input_reference_structurally_valid": claim_values[
            "P1A_INPUT_REFERENCE_STRUCTURALLY_VALID"
        ],
        "p1a_preference_quarantined": p1a.preference_quarantined,
        "source_frame_semantics": "PARTIAL",
        "child_frame_id": "UNRESOLVED",
        "translation_scale": "UNRESOLVED",
        "yaw_scale": "UNRESOLVED",
        "authoritative_source_channel": claim_values["AUTHORITATIVE_SOURCE_CHANNEL"],
        "preferred_analysis_channel": claim_values["PREFERRED_ANALYSIS_CHANNEL"],
        "covariance_ros_si_matrix": None,
        "physical_odom_publication_ready": claim_values[
            "PHYSICAL_ODOM_PUBLICATION_READY"
        ],
        "physical_tf_publication_ready": claim_values[
            "PHYSICAL_TF_PUBLICATION_READY"
        ],
    }
    publication = {
        "schema_version": P2A_SCHEMA_VERSION,
        "covariance_source_unit_evidence": "PARTIAL_QUANTIFIED",
        "covariance_ros_si_matrix": None,
        "publication_model_ready": False,
        "publication_status": "WITHHELD_BY_P2A_BOUNDARY",
        "measured_zero_preserved": claim_values["MEASURED_ZERO_PRESERVED"],
        "cross_channel_evidence_separated": claim_values[
            "CROSS_CHANNEL_EVIDENCE_SEPARATED"
        ],
    }
    provenance = {
        "schema_version": P2A_SCHEMA_VERSION,
        "inputs": provenance_inputs,
        "raw_outputs_included": False,
        "personal_paths_included": False,
        "new_physical_validation": False,
        "path_kinds": [
            "EXTERNAL_INPUT_MANIFEST_PATH",
            "VERSIONED_REPOSITORY_PATH",
        ],
    }
    report = f"""# ODOM/TF R2-P2A contract audit and hardening

Result: `COMPLETE_WITH_LIMITATIONS`.

P2A closes the enum and free-form status bypasses, carries structurally valid
mapping and P1A references, and separates position, unavailable orientation,
linear residual, yaw-rate residual and cross-channel domains. The contract
objects carry structural references to external inputs and do not attest that
external material bytes were read or verified.

The current material does not contain a measured-zero source-variance record,
so `MEASURED_ZERO_PRESERVED` remains `false` and H9 remains open. Synthetic
unit coverage of that predicate is not physical evidence.

The preserved P1A LF analysis preference is quarantined because it is not an
authority decision. Both contractual channel fields remain `null`.

Offline replay and simulation are policy-only. No adapter was implemented, no
simulation model was selected, and no execution was validated. Physical ODOM,
TF, ROS covariance and Nav2 remain blocked. Generated UTC: `{generated_utc}`.
"""
    return {
        "R2_P2A_RESULT.json": result,
        "R2_P2A_AUDIT_FINDINGS.json": {
            "schema_version": P2A_SCHEMA_VERSION,
            "findings": findings,
        },
        "R2_P2A_FRAME_VOCABULARY.json": vocabulary,
        "R2_P2A_FRAME_SEMANTICS_CONTRACT.json": {
            "schema_version": P2A_SCHEMA_VERSION,
            "contracts": frames,
            "ros_rep_103_model_verified": False,
            "right_handed_model_verified": False,
            "unity_scale_model_verified": False,
        },
        "R2_P2A_MAPPING_EVIDENCE_BINDING.json": mapping_binding,
        "R2_P2A_MAPPING_FRAME_CORRELATION.json": {
            "schema_version": P2A_SCHEMA_VERSION,
            "policy_kind": "STRUCTURAL_POLICY_ONLY",
            "edges": mapping.structural_correlation_policy,
            "selected_source_content_parsed": claim_values[
                "MAPPING_SELECTED_SOURCE_CONTENT_PARSED"
            ],
            "frame_relations_derived_from_content": claim_values[
                "MAPPING_FRAME_RELATIONS_DERIVED_FROM_CONTENT"
            ],
            "physical_frame_authority": False,
            "limitations": (
                "Selected mapping source contents were not parsed for frame relations.",
                "Structural edges do not establish physical frame semantics or authority.",
            ),
        },
        "R2_P2A_COVARIANCE_SOURCE_EVIDENCE.json": {
            "schema_version": P2A_SCHEMA_VERSION,
            "records": covariance,
        },
        "R2_P2A_COVARIANCE_DOMAIN_MATRIX.json": {
            "schema_version": P2A_SCHEMA_VERSION,
            "domains": domain_matrix,
        },
        "R2_P2A_COVARIANCE_PUBLICATION_CONTRACT.json": publication,
        "R2_P2A_READINESS.json": {
            "schema_version": P2A_SCHEMA_VERSION,
            "readiness": readiness,
        },
        "R2_P2A_BLOCKERS.json": {
            "schema_version": P2A_SCHEMA_VERSION,
            "physical": PHYSICAL_BLOCKERS,
            "implementation_and_execution": EXECUTION_BLOCKERS,
        },
        "R2_P2A_CLAIMS_LEDGER.json": {
            "schema_version": P2A_SCHEMA_VERSION,
            "claims": claims,
            "limitations": CLAIMS_LIMITATIONS,
        },
        "R2_P2A_PROVENANCE.json": provenance,
        "R2_P2A_REPORT.md": report,
    }


def _write_output_file(path: Path, payload: bytes) -> None:
    with path.open("xb") as stream:
        stream.write(payload)
        stream.flush()
        os.fsync(stream.fileno())


def write_documents(output_dir: Path, documents: Mapping[str, object]) -> None:
    if output_dir.exists() or output_dir.is_symlink():
        raise ContractValidationError("output directory must not exist")
    if set(documents) != set(OUTPUT_NAMES):
        raise ContractValidationError("P2A document set mismatch")
    if any(Path(name).name != name or name in ("", ".", "..") for name in documents):
        raise ContractValidationError("P2A document name is unsafe")
    parent = output_dir.parent.resolve(strict=True)
    temporary = Path(tempfile.mkdtemp(prefix=f".{output_dir.name}.tmp-", dir=parent))
    try:
        manifest_lines = []
        for name in OUTPUT_NAMES:
            value = documents[name]
            payload = canonical_json(value) if name.endswith(".json") else str(value).encode("utf-8")
            _write_output_file(temporary / name, payload)
            manifest_lines.append(f"{hashlib.sha256(payload).hexdigest()}  {name}\n")
        manifest_payload = "".join(manifest_lines).encode("utf-8")
        _write_output_file(temporary / "CONTENT_MANIFEST.sha256", manifest_payload)
        expected_names = set(OUTPUT_NAMES) | {"CONTENT_MANIFEST.sha256"}
        if {item.name for item in temporary.iterdir()} != expected_names:
            raise ContractValidationError("temporary P2A document set mismatch")
        for line in manifest_payload.decode("utf-8").splitlines():
            digest, name = line.split("  ", 1)
            if hashlib.sha256((temporary / name).read_bytes()).hexdigest() != digest:
                raise ContractValidationError("temporary P2A manifest verification failed")
        os.replace(temporary, output_dir)
    except Exception:
        shutil.rmtree(temporary, ignore_errors=True)
        raise
