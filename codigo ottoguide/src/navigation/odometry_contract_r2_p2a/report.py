"""Deterministic P2A document generation."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, is_dataclass
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
)
from .inputs import MappingBinding, P1AValidation
from .models import (
    P2A_SCHEMA_VERSION,
    ClaimStrength,
    ContractValidationError,
    CovarianceDomain,
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

AUDIT_STATUSES = {
    "H1": "REPRODUCED",
    "H2": "REPRODUCED",
    "H3": "REPRODUCED",
    "H4": "REPRODUCED",
    "H5": "REPRODUCED",
    "H6": "REPRODUCED",
    "H7": "REPRODUCED",
    "H8": "PARTIAL",
    "H9": "REPRODUCED",
    "H10": "REPRODUCED",
    "H11": "REPRODUCED",
    "H12": "REPRODUCED",
    "H13": "REPRODUCED",
    "H14": "REPRODUCED",
    "H15": "REPRODUCED",
}


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
    claims = build_claims()
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
    findings = [
        {
            "hypothesis_id": hypothesis_id,
            "status": status,
            "remediation": {
                "H1": "exact enum identity required",
                "H2": "typed status enums replace free-form strings",
                "H3": "mapping documents derive from a validated manifest",
                "H4": "mapping audit state derives from successful validation",
                "H5": "mapping manifest and selected inputs are SHA-256 bound",
                "H6": "P1A and embedded P1 schemas are exact",
                "H7": "numeric conversion catches overflow and fails closed",
                "H8": "exact containers and finite plain numbers are required",
                "H9": "measured zero produces variance candidate 0.0",
                "H10": "cross-channel residuals have a separate channel domain",
                "H11": "yaw-rate residuals remain cross-channel records",
                "H12": "simulation remains a policy candidate with no model bound",
                "H13": "readiness derives from a validated evidence object",
                "H14": "generated UTC is canonical RFC 3339 UTC",
                "H15": "canonical and mirror roles are explicit in unification state",
            }[hypothesis_id],
        }
        for hypothesis_id, status in AUDIT_STATUSES.items()
    ]
    mapping_binding = {
        "schema_version": P2A_SCHEMA_VERSION,
        "mapping_manifest_schema": mapping.manifest_input.schema,
        "mapping_manifest_sha256": mapping.manifest_input.sha256,
        "mapping_workspace_audited": True,
        "mapping_provenance_bound": True,
        "source_ids": mapping.source_ids,
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
        "entries": [
            {
                "frame_id": "map",
                "classification": "MAPPING_REFERENCE",
                "physical_semantics": "UNRESOLVED",
            },
            {
                "frame_id": "odom",
                "classification": "CONFIGURED_NAME",
                "physical_semantics": "UNRESOLVED",
            },
            {
                "frame_id": "base_link",
                "classification": "CONFIGURED_NAME",
                "physical_semantics": "UNRESOLVED",
            },
            {
                "frame_id": "utlidar_lidar",
                "classification": "OBSERVED_SOURCE_LABEL",
                "physical_semantics": "PARTIAL",
            },
            {
                "frame_id": "kiss_odom_lidar",
                "classification": "MAPPING_REFERENCE",
                "physical_semantics": "UNRESOLVED",
            },
        ],
    }
    result = {
        "schema_version": P2A_SCHEMA_VERSION,
        "result": "MVP_ODOM_TF_R2_P2A_COMPLETE_WITH_LIMITATIONS",
        "generated_utc_injected": generated_utc,
        "robot_access_status": "PERMANENTLY_UNAVAILABLE",
        "future_hardware_revalidation": "NOT_EXPECTED",
        "mapping_workspace_audited": True,
        "mapping_provenance_bound": True,
        "p1a_input_validated": True,
        "p1a_preference_quarantined": p1a.preference_quarantined,
        "source_frame_semantics": "PARTIAL",
        "child_frame_id": "UNRESOLVED",
        "translation_scale": "UNRESOLVED",
        "yaw_scale": "UNRESOLVED",
        "authoritative_source_channel": None,
        "preferred_analysis_channel": None,
        "covariance_ros_si_matrix": None,
        "physical_odom_publication_ready": False,
        "physical_tf_publication_ready": False,
    }
    publication = {
        "schema_version": P2A_SCHEMA_VERSION,
        "covariance_source_unit_evidence": "PARTIAL_QUANTIFIED",
        "covariance_ros_si_matrix": None,
        "publication_model_ready": False,
        "publication_status": "WITHHELD_BY_P2A_BOUNDARY",
        "measured_zero_preserved": True,
        "cross_channel_evidence_separated": all(
            record.channel == "CROSS_CHANNEL"
            for record in covariance
            if record.domain
            in (
                CovarianceDomain.CROSS_CHANNEL_RESIDUAL,
                CovarianceDomain.TWIST_ANGULAR_YAW_RATE_RESIDUAL,
            )
        ),
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

P2A closes the enum and free-form status bypasses, binds mapping provenance to
the sanitized manifest and its real source hashes, validates the preserved P1A
input, preserves measured zero, and separates position, unavailable
orientation, linear residual, yaw-rate residual and cross-channel domains.

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
            "derived_from_mapping_manifest_sha256": mapping.manifest_input.sha256,
            "edges": mapping.correlation_edges,
            "physical_authority": False,
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
        },
        "R2_P2A_PROVENANCE.json": provenance,
        "R2_P2A_REPORT.md": report,
    }


def write_documents(output_dir: Path, documents: Mapping[str, object]) -> None:
    if output_dir.exists() or output_dir.is_symlink():
        raise ContractValidationError("output directory must not exist")
    if set(documents) != set(OUTPUT_NAMES):
        raise ContractValidationError("P2A document set mismatch")
    output_dir.mkdir(parents=True, exist_ok=False)
    for name in OUTPUT_NAMES:
        path = output_dir / name
        value = documents[name]
        if name.endswith(".json"):
            path.write_bytes(canonical_json(value))
        else:
            path.write_text(str(value), encoding="utf-8", newline="\n")
    manifest_lines = []
    for name in OUTPUT_NAMES:
        digest = hashlib.sha256((output_dir / name).read_bytes()).hexdigest()
        manifest_lines.append(f"{digest}  {name}\n")
    (output_dir / "CONTENT_MANIFEST.sha256").write_text(
        "".join(manifest_lines),
        encoding="utf-8",
        newline="\n",
    )
