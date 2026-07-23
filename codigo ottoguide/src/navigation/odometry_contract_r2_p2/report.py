"""Deterministic P2 report construction and serialization helpers."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, is_dataclass
from enum import Enum
from pathlib import Path
from typing import Mapping

from .covariance import (
    PHYSICAL_COVARIANCE_BLOCKERS,
    build_physical_source_unit_evidence,
    covariance_context_contracts,
)
from .frame_semantics import (
    frame_vocabulary,
    physical_frame_contract,
    replay_frame_contract,
    simulation_frame_contract,
)
from .models import P2_SCHEMA_VERSION
from .readiness import PHYSICAL_BLOCKERS, assess_p2_readiness


OUTPUT_NAMES = (
    "R2_P2_RESULT.json",
    "R2_P2_FRAME_VOCABULARY.json",
    "R2_P2_FRAME_SEMANTICS_CONTRACT.json",
    "R2_P2_MAPPING_FRAME_CORRELATION.json",
    "R2_P2_FRAME_BLOCKERS.json",
    "R2_P2_COVARIANCE_SOURCE_UNIT_EVIDENCE.json",
    "R2_P2_COVARIANCE_CONTEXTS.json",
    "R2_P2_COVARIANCE_PUBLICATION_CONTRACT.json",
    "R2_P2_COVARIANCE_BLOCKERS.json",
    "R2_P2_READINESS.json",
    "R2_P2_CLAIMS_LEDGER.json",
    "R2_P2_PROVENANCE.json",
    "R2_P2_REPORT.md",
)


def jsonable(value):
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
    p1a_document: Mapping[str, object],
    mapping_inventory: Mapping[str, object],
    generated_utc: str,
    input_hashes: Mapping[str, str],
) -> dict[str, object]:
    if type(generated_utc) is not str or not generated_utc.strip():
        raise ValueError("generated_utc must be explicitly injected")
    physical = physical_frame_contract()
    replay = replay_frame_contract()
    simulation = simulation_frame_contract()
    vocabulary = frame_vocabulary()
    covariance_evidence = build_physical_source_unit_evidence(p1a_document)
    readiness = assess_p2_readiness(
        frame_contract_complete=True,
        covariance_contract_complete=True,
        mapping_inventory_available=bool(mapping_inventory.get("mapping_workspace_audited")),
    )
    claims = [
        {
            "claim": "FRAME_CONTRACT_STRUCTURALLY_COMPLETE",
            "value": True,
            "context": "STRUCTURAL_ONLY",
        },
        {
            "claim": "COVARIANCE_CONTRACT_STRUCTURALLY_COMPLETE",
            "value": True,
            "context": "STRUCTURAL_ONLY",
        },
        {"claim": "SOURCE_FRAME_SEMANTICS", "value": "PARTIAL", "context": "PHYSICAL_EVIDENCE"},
        {"claim": "CHILD_FRAME_ID", "value": "UNRESOLVED", "context": "PHYSICAL_EVIDENCE"},
        {"claim": "TRANSLATION_SCALE", "value": "UNRESOLVED", "context": "PHYSICAL_EVIDENCE"},
        {"claim": "YAW_SCALE", "value": "UNRESOLVED", "context": "PHYSICAL_EVIDENCE"},
        {"claim": "AUTHORITATIVE_SOURCE_CHANNEL", "value": None, "context": "PHYSICAL_EVIDENCE"},
        {"claim": "PREFERRED_ANALYSIS_CHANNEL", "value": None, "context": "PHYSICAL_EVIDENCE"},
        {
            "claim": "COVARIANCE_SOURCE_UNIT_EVIDENCE",
            "value": "PARTIAL_QUANTIFIED",
            "context": "PHYSICAL_EVIDENCE",
        },
        {"claim": "COVARIANCE_ROS_SI_MATRIX", "value": None, "context": "PHYSICAL_EVIDENCE"},
        {
            "claim": "COVARIANCE_PUBLICATION_MODEL_READY",
            "value": False,
            "context": "PHYSICAL_EVIDENCE",
        },
        {
            "claim": "PHYSICAL_ODOM_PUBLICATION_READY",
            "value": False,
            "context": "PHYSICAL_EVIDENCE",
        },
        {"claim": "PHYSICAL_TF_PUBLICATION_READY", "value": False, "context": "PHYSICAL_EVIDENCE"},
    ]
    result = {
        "schema_version": P2_SCHEMA_VERSION,
        "result": "MVP_ODOM_TF_R2_P2_COMPLETE_WITH_LIMITATIONS",
        "generated_utc_injected": generated_utc,
        "robot_access_status": "PERMANENTLY_UNAVAILABLE",
        "validation_strategy": "PRESERVED_PHYSICAL_EVIDENCE_OFFLINE_REPLAY_MAPPING_AND_SIMULATION",
        "mapping_workspace_audited": True,
        "frame_contract_structurally_complete": True,
        "covariance_contract_structurally_complete": True,
        "limitations": list(PHYSICAL_BLOCKERS),
    }
    mapping_correlation = {
        "schema_version": P2_SCHEMA_VERSION,
        "source": "READ_ONLY_MAPPING_INVENTORY",
        "frequency_is_evidence": False,
        "edges": [
            {"edge": "map->odom", "mapping_reference": True, "physical_status": "UNRESOLVED"},
            {"edge": "odom->base_link", "mapping_reference": True, "physical_status": "UNRESOLVED"},
            {
                "edge": "base_link->utlidar_lidar",
                "mapping_reference": True,
                "physical_status": "PARTIAL",
            },
            {
                "edge": "base_link->imu_link/livox_imu",
                "mapping_reference": True,
                "physical_status": "UNRESOLVED_ALIAS",
            },
        ],
    }
    publication_contract = {
        "schema_version": P2_SCHEMA_VERSION,
        "physical_source_unit_evidence": "PARTIAL_QUANTIFIED",
        "ros_si_matrix": None,
        "off_diagonal_status": "UNRESOLVED_NOT_ASSUMED_ZERO",
        "publication_model_ready": False,
        "legacy_placeholders_are_evidence": False,
        "forbidden_unknown_markers": [0, 999],
    }
    provenance = {
        "schema_version": P2_SCHEMA_VERSION,
        "inputs": [
            {"id": key, "sha256": value, "path": f"inputs/{key}"}
            for key, value in sorted(input_hashes.items())
        ],
        "raw_outputs_included": False,
        "personal_paths_included": False,
        "new_physical_validation": False,
    }
    report_md = f"""# ODOM/TF R2-P2 frame and covariance contract

Result: `COMPLETE_WITH_LIMITATIONS`.

The P2 contract is structurally ready for offline replay and for a future
simulation adapter. Configured frame names are kept separate from physical
semantics. Mapping material is a read-only provenance source and is not
promoted to physical validation.

Physical publication remains blocked: source-frame semantics are PARTIAL;
child-frame semantics, channel authority, translation/yaw scale and ROS header
stamp policy are unresolved. Stationary and dynamic quantities remain in source
units. No ROS SI covariance matrix exists and legacy 0/999 placeholders are not
evidence.

Generated UTC was explicitly injected as `{generated_utc}`. No robot, ROS, DDS,
Nav2, mapping process or simulator was executed.
"""
    return {
        "R2_P2_RESULT.json": result,
        "R2_P2_FRAME_VOCABULARY.json": {"schema_version": P2_SCHEMA_VERSION, "entries": vocabulary},
        "R2_P2_FRAME_SEMANTICS_CONTRACT.json": {
            "schema_version": P2_SCHEMA_VERSION,
            "physical": physical,
            "offline_replay": replay,
            "simulation": simulation,
        },
        "R2_P2_MAPPING_FRAME_CORRELATION.json": mapping_correlation,
        "R2_P2_FRAME_BLOCKERS.json": {
            "schema_version": P2_SCHEMA_VERSION,
            "blockers": list(PHYSICAL_BLOCKERS),
        },
        "R2_P2_COVARIANCE_SOURCE_UNIT_EVIDENCE.json": {
            "schema_version": P2_SCHEMA_VERSION,
            "status": "PARTIAL_QUANTIFIED",
            "records": covariance_evidence,
        },
        "R2_P2_COVARIANCE_CONTEXTS.json": {
            "schema_version": P2_SCHEMA_VERSION,
            "contexts": covariance_context_contracts(),
        },
        "R2_P2_COVARIANCE_PUBLICATION_CONTRACT.json": publication_contract,
        "R2_P2_COVARIANCE_BLOCKERS.json": {
            "schema_version": P2_SCHEMA_VERSION,
            "blockers": list(PHYSICAL_COVARIANCE_BLOCKERS),
        },
        "R2_P2_READINESS.json": {"schema_version": P2_SCHEMA_VERSION, "readiness": readiness},
        "R2_P2_CLAIMS_LEDGER.json": {"schema_version": P2_SCHEMA_VERSION, "claims": claims},
        "R2_P2_PROVENANCE.json": provenance,
        "R2_P2_REPORT.md": report_md,
    }


def write_documents(output_dir: Path, documents: Mapping[str, object]) -> None:
    output_dir.mkdir(parents=True, exist_ok=False)
    if set(documents) != set(OUTPUT_NAMES):
        raise ValueError("document set does not match the P2 output contract")
    for name in OUTPUT_NAMES:
        path = output_dir / name
        value = documents[name]
        if name.endswith(".json"):
            path.write_bytes(canonical_json(value))
        else:
            path.write_text(str(value), encoding="utf-8", newline="\n")
    lines = []
    for name in OUTPUT_NAMES:
        digest = hashlib.sha256((output_dir / name).read_bytes()).hexdigest()
        lines.append(f"{digest}  {name}\n")
    (output_dir / "CONTENT_MANIFEST.sha256").write_text(
        "".join(lines), encoding="utf-8", newline="\n"
    )
