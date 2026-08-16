import copy
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from unittest.mock import patch

import pytest

from src.navigation import odom_bridge_contract
from src.navigation.odometry_contract_r2_p2a.inputs import (
    load_and_validate_p1a,
    load_json_object,
    sha256_file,
    validate_mapping_manifest,
    validate_p1a_document,
)
from src.navigation.odometry_contract_r2_p2a.models import (
    ClaimStrength,
    ContractValidationError,
    ValidatedInput,
    ValidationContext,
)
from src.navigation.odometry_contract_r2_p2a.report import (
    build_documents,
    canonical_json,
)


CODIGO_ROOT = Path(__file__).resolve().parents[2]
REPO_ROOT = CODIGO_ROOT.parent
CLI = (
    CODIGO_ROOT
    / "tools"
    / "hil"
    / "offline_navigation"
    / "build_odom_tf_r2_p2a_contract.py"
)
MAPPING_MANIFEST = (
    REPO_ROOT
    / "docs"
    / "Operaciones_HIL"
    / "Evidencia"
    / "R2_P2A_MAPPING_EVIDENCE_MANIFEST.json"
)
P2A_CLAIMS = (
    REPO_ROOT
    / "docs"
    / "Operaciones_HIL"
    / "Evidencia"
    / "R2_P2A_CLAIMS_LEDGER.json"
)


def required_env(name):
    value = os.environ.get(name)
    assert value, f"required P2A environment variable missing: {name}"
    return Path(value)


@pytest.fixture(scope="module")
def material_inputs():
    return {
        "harvest": required_env("OTTOGUIDE_R2_HARVEST_ROOT"),
        "mapping": required_env("OTTOGUIDE_P2_MAPPING_ROOT"),
        "descriptor": required_env("OTTOGUIDE_R2_P0A_DESCRIPTOR"),
        "p1a": required_env("OTTOGUIDE_R2_P1A_INPUT"),
    }


def _mapping(document, manifest_path, mapping_root):
    return validate_mapping_manifest(
        document,
        manifest_path=manifest_path,
        mapping_root=mapping_root,
    )


def _p1a(path):
    return load_and_validate_p1a(path)


def _input(source_id, path, schema, context, strength):
    return ValidatedInput(
        source_id=source_id,
        schema=schema,
        sha256=sha256_file(path),
        logical_path=(
            "docs/Operaciones_HIL/Evidencia/R2_P2A_CLAIMS_LEDGER.json"
            if path == P2A_CLAIMS
            else "external/portable_descriptor_v2.json"
        ),
        validation_context=context,
        claim_strength=strength,
        limitations=("Bound integration-test input.",),
    )


def _cli_args(inputs, output, manifest=MAPPING_MANIFEST, generated="2026-07-23T12:00:00Z"):
    return [
        sys.executable,
        str(CLI),
        "--evidence-descriptor",
        str(inputs["descriptor"]),
        "--harvest-root",
        str(inputs["harvest"]),
        "--mapping-root",
        str(inputs["mapping"]),
        "--mapping-evidence-manifest",
        str(manifest),
        "--p1a-input",
        str(inputs["p1a"]),
        "--output-dir",
        str(output),
        "--generated-utc",
        generated,
    ]


def test_real_mapping_manifest_is_hash_bound(material_inputs):
    document = load_json_object(MAPPING_MANIFEST, "mapping manifest")
    binding = _mapping(document, MAPPING_MANIFEST, material_inputs["mapping"])
    assert binding.manifest_input.sha256 == hashlib.sha256(
        MAPPING_MANIFEST.read_bytes()
    ).hexdigest()
    assert len(binding.selected_inputs) == 5
    assert all(item.sha256 for item in binding.selected_inputs)
    assert tuple(source_id for source_id, _ in binding.selected_source_categories) == binding.source_ids
    assert {category for _, category in binding.selected_source_categories} == set(binding.file_categories)


def test_different_valid_mapping_manifest_changes_provenance_and_output(material_inputs):
    original_document = load_json_object(MAPPING_MANIFEST, "mapping manifest")
    with tempfile.TemporaryDirectory() as temp:
        mutated_document = copy.deepcopy(original_document)
        old_id = mutated_document["source_ids"][0]
        new_id = f"{old_id}-variant"
        mutated_document["source_ids"][0] = new_id
        mutated_document["selected_sources"][0]["source_id"] = new_id
        mutated_path = Path(temp) / "mapping-variant.json"
        mutated_path.write_text(
            json.dumps(mutated_document, indent=2) + "\n",
            encoding="utf-8",
        )
        original = _mapping(
            original_document,
            MAPPING_MANIFEST,
            material_inputs["mapping"],
        )
        mutated = _mapping(
            mutated_document,
            mutated_path,
            material_inputs["mapping"],
        )
        p1a = _p1a(material_inputs["p1a"])
        descriptor = _input(
            "r2-p0a-evidence-descriptor",
            material_inputs["descriptor"],
            "1.0.0-p0a",
            ValidationContext.PHYSICAL_EVIDENCE,
            ClaimStrength.PRESERVED_PHYSICAL_EVIDENCE,
        )
        p2_claims = _input(
            "r2-p2a-claims-ledger",
            P2A_CLAIMS,
            "2.2.1-p2a",
            ValidationContext.STRUCTURAL_ONLY,
            ClaimStrength.STRUCTURAL_POLICY,
        )
        left = build_documents(
            p1a=p1a,
            mapping=original,
            descriptor_input=descriptor,
            p2_claims_input=p2_claims,
            generated_utc="2026-07-23T12:00:00Z",
        )
        right = build_documents(
            p1a=p1a,
            mapping=mutated,
            descriptor_input=descriptor,
            p2_claims_input=p2_claims,
            generated_utc="2026-07-23T12:00:00Z",
        )
        name = "R2_P2A_MAPPING_EVIDENCE_BINDING.json"
        assert canonical_json(left[name]) != canonical_json(right[name])


@pytest.mark.parametrize("mutation", ["hash", "physical_claim", "missing_source"])
def test_invalid_mapping_manifest_fails_closed(material_inputs, mutation, tmp_path):
    document = load_json_object(MAPPING_MANIFEST, "mapping manifest")
    if mutation == "hash":
        document["selected_sources"][0]["sha256"] = "0" * 64
    elif mutation == "physical_claim":
        document["physical_validation_claim"] = True
    else:
        document["selected_sources"][0]["logical_path"] = "missing/source.csv"
    path = tmp_path / f"{mutation}.json"
    path.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")
    with pytest.raises(ContractValidationError):
        _mapping(document, path, material_inputs["mapping"])


def test_real_p1a_is_validated_and_preference_is_quarantined(material_inputs):
    validation = _p1a(material_inputs["p1a"])
    assert validation.preference_quarantined
    assert validation.authoritative_source_channel is None
    assert validation.preferred_analysis_channel is None
    assert len(validation.stationary_ids) == 10


def test_cli_is_byte_deterministic_and_manifested(material_inputs):
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp)
        outputs = []
        for name in ("one", "two"):
            output = root / name
            result = subprocess.run(
                _cli_args(material_inputs, output),
                capture_output=True,
                text=True,
                timeout=180,
            )
            assert result.returncode == 0, result.stderr
            outputs.append(output)
        names = sorted(path.name for path in outputs[0].iterdir())
        assert names == sorted(path.name for path in outputs[1].iterdir())
        assert len(names) == 15
        for name in names:
            assert (outputs[0] / name).read_bytes() == (outputs[1] / name).read_bytes()
        manifest = (outputs[0] / "CONTENT_MANIFEST.sha256").read_text().splitlines()
        assert len(manifest) == 14
        for line in manifest:
            digest, name = line.split("  ", 1)
            assert hashlib.sha256((outputs[0] / name).read_bytes()).hexdigest() == digest


def test_generated_claims_and_provenance_are_consistent(material_inputs):
    document = load_json_object(MAPPING_MANIFEST, "mapping manifest")
    mapping = _mapping(document, MAPPING_MANIFEST, material_inputs["mapping"])
    documents = build_documents(
        p1a=_p1a(material_inputs["p1a"]),
        mapping=mapping,
        descriptor_input=_input(
            "r2-p0a-evidence-descriptor",
            material_inputs["descriptor"],
            "1.0.0-p0a",
            ValidationContext.PHYSICAL_EVIDENCE,
            ClaimStrength.PRESERVED_PHYSICAL_EVIDENCE,
        ),
        p2_claims_input=_input(
            "r2-p2a-claims-ledger",
            P2A_CLAIMS,
            "2.2.1-p2a",
            ValidationContext.STRUCTURAL_ONLY,
            ClaimStrength.STRUCTURAL_POLICY,
        ),
        generated_utc="2026-07-23T12:00:00Z",
    )
    versioned_claims = load_json_object(P2A_CLAIMS, "P2A claims ledger")
    generated_claims = json.loads(
        canonical_json(documents["R2_P2A_CLAIMS_LEDGER.json"])
    )
    assert generated_claims["claims"] == versioned_claims["claims"]
    assert generated_claims == versioned_claims
    claim_values = {
        claim["name"]: claim["value"] for claim in generated_claims["claims"]
    }
    assert claim_values["MEASURED_ZERO_PRESERVED"] is False
    assert claim_values["MAPPING_INPUT_HASH_REFERENCES_WELL_FORMED"] is True
    assert "MAPPING_INPUTS_HASH_BOUND" not in claim_values
    result = documents["R2_P2A_RESULT.json"]
    publication = documents["R2_P2A_COVARIANCE_PUBLICATION_CONTRACT.json"]
    assert result["mapping_input_hash_references_well_formed"] is claim_values[
        "MAPPING_INPUT_HASH_REFERENCES_WELL_FORMED"
    ]
    assert publication["measured_zero_preserved"] is claim_values[
        "MEASURED_ZERO_PRESERVED"
    ]
    correlation = documents["R2_P2A_MAPPING_FRAME_CORRELATION.json"]
    assert correlation["policy_kind"] == "STRUCTURAL_POLICY_ONLY"
    assert correlation["selected_source_content_parsed"] is False
    assert correlation["frame_relations_derived_from_content"] is False
    assert correlation["physical_frame_authority"] is False
    vocabulary = documents["R2_P2A_FRAME_VOCABULARY.json"]
    observed = {
        entry["frame_id"]
        for entry in vocabulary["entries"]
        if entry["provenance_kind"] == "MANIFEST_OBSERVED_FRAME_ID"
    }
    assert observed == set(mapping.observed_frame_ids)
    assert {"unitree_lowstate_imu", "unitree_secondary_imu"}.issubset(observed)
    findings = documents["R2_P2A_AUDIT_FINDINGS.json"]["findings"]
    h9 = next(item for item in findings if item["hypothesis_id"] == "H9")
    assert h9["closed"] is False
    assert h9["status"] == "OPEN"
    h15 = next(item for item in findings if item["hypothesis_id"] == "H15")
    assert h15["closed"] is None
    assert h15["status"] == "NOT_EVALUATED"
    provenance = documents["R2_P2A_PROVENANCE.json"]
    assert provenance["personal_paths_included"] is False
    assert provenance["raw_outputs_included"] is False
    assert all(item.sha256 for item in provenance["inputs"])
    assert len({item.source_id for item in provenance["inputs"]}) == len(
        provenance["inputs"]
    )


@pytest.mark.parametrize(
    "generated",
    [
        "x",
        "2026-07-23 12:00:00Z",
        "2026-07-23T12:00:00+00:00",
        "2026-02-30T12:00:00Z",
        " 2026-07-23T12:00:00Z",
    ],
)
def test_cli_rejects_invalid_generated_utc_without_traceback(
    material_inputs, generated, tmp_path
):
    result = subprocess.run(
        _cli_args(material_inputs, tmp_path / "output", generated=generated),
        capture_output=True,
        text=True,
        timeout=180,
    )
    assert result.returncode == 2
    assert "Traceback" not in result.stderr


def test_cli_rejects_output_inside_mapping_input(material_inputs):
    forbidden = material_inputs["mapping"] / "__p2a_forbidden_output__"
    assert not forbidden.exists()
    result = subprocess.run(
        _cli_args(material_inputs, forbidden),
        capture_output=True,
        text=True,
        timeout=180,
    )
    assert result.returncode == 2
    assert not forbidden.exists()


def test_output_symlink_is_rejected_before_writing(material_inputs, tmp_path):
    module_path = "tools.hil.offline_navigation.build_odom_tf_r2_p2a_contract"
    module = __import__(module_path, fromlist=["validate_output_location"])
    output = tmp_path / "prospective"
    with patch.object(Path, "is_symlink", return_value=True):
        with pytest.raises(ContractValidationError, match="symlink"):
            module.validate_output_location(
                output,
                harvest_root=material_inputs["harvest"],
                mapping_root=material_inputs["mapping"],
                inputs=(material_inputs["descriptor"],),
            )


def test_unification_state_has_durable_p2c_lifecycle_boundaries():
    document = json.loads(
        (REPO_ROOT / "docs/Arquitectura/unification-state.json").read_text(
            encoding="utf-8-sig"
        )
    )
    assert document["canonical_authority"] == (
        "tsamaan/OttoGuide-Proyecto_SIP-Grupo6-UADE"
    )
    assert document["mirror_staging"] == (
        "LucasCap12/OttoGuide-Proyecto_SIP-Grupo6-G1-EDU"
    )
    assert document["p2a_baseline_sha"] == (
        "76ecfd782af4a401936076939e0c9c0b55718b4e"
    )
    assert document["schema_version"] == 3
    assert document["p2c_payload"]["commit_sha"] == (
        "2b4b1a58fb522dac9a7bacbda0823b885ef28119"
    )
    assert document["p2c_payload"]["parent_sha"] == document["p2a_baseline_sha"]
    assert document["p2c_mirror_publication_event"]["scope"] == (
        "MIRROR_FEATURE_ONLY"
    )
    assert document["p2c_preintegration_snapshot"]["kind"] == "HISTORICAL_SNAPSHOT"
    assert document["p2c_live_resolution"]["embedded_current_head_prohibited"] is True
    resolution = document["p2c_live_resolution"]
    mirror_url = "https://github.com/LucasCap12/OttoGuide-Proyecto_SIP-Grupo6-G1-EDU.git"
    canonical_url = "https://github.com/tsamaan/OttoGuide-Proyecto_SIP-Grupo6-UADE.git"
    assert mirror_url in resolution["mirror_feature"]["command"]
    assert "refs/heads/feature/odom-tf-r2-p2-frame-semantics-covariance-contract" in resolution["mirror_feature"]["command"]
    assert mirror_url in resolution["mirror_review"]["command"]
    assert "refs/heads/review/orchestrator-unification" in resolution["mirror_review"]["command"]
    assert canonical_url in resolution["canonical_review"]["command"]
    assert "refs/heads/review/orchestrator-unification" in resolution["canonical_review"]["command"]
    for resolver in resolution.values():
        if isinstance(resolver, dict) and "command" in resolver:
            assert "git ls-remote mirror" not in resolver["command"]
            assert "git ls-remote canonical" not in resolver["command"]
    assert document["p2c_transition_policy"]["canonical_fast_forward_only_after_mirror"] is True
    for obsolete in (
        "p2c_local_candidate_state",
        "p2c_commit_sha",
        "p2c_published",
        "p2c_next_checkpoint",
    ):
        assert obsolete not in document


def test_legacy_activation_remains_false_and_has_no_productive_true_callers():
    flags = odom_bridge_contract.OdomBridgeSafetyFlags(True, True, True, "validated")
    source = odom_bridge_contract.OdomSourceAssessment(
        source_kind=odom_bridge_contract.OdomSourceKind.POSE_TWIST_VALIDATED,
        has_pose_xy=True,
        has_yaw=True,
        has_twist=True,
        frequency_hz=100.0,
        notes="P2A legacy call-site audit",
    )
    with pytest.warns(DeprecationWarning):
        assert not odom_bridge_contract.activation_allowed(flags, source)
    callers = []
    for path in (CODIGO_ROOT / "src").rglob("*.py"):
        if path.name == "odom_bridge_contract.py":
            continue
        if "activation_allowed(" in path.read_text(encoding="utf-8-sig"):
            callers.append(path.relative_to(CODIGO_ROOT).as_posix())
    assert callers == []
