#!/usr/bin/env python3
"""Build deterministic R2-P2A outputs from explicit, hash-bound offline inputs."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
from pathlib import Path
import sys


CODIGO_ROOT = Path(__file__).resolve().parents[3]
REPOSITORY_ROOT = CODIGO_ROOT.parent
if str(CODIGO_ROOT) not in sys.path:
    sys.path.insert(0, str(CODIGO_ROOT))

from src.navigation.odometry_contract_r2_p2a.inputs import (  # noqa: E402
    load_json_object,
    sha256_file,
    validate_mapping_manifest,
    validate_p1a_document,
)
from src.navigation.odometry_contract_r2_p2a.models import (  # noqa: E402
    ClaimStrength,
    ContractValidationError,
    ValidatedInput,
    ValidationContext,
)
from src.navigation.odometry_contract_r2_p2a.report import (  # noqa: E402
    build_documents,
    jsonable,
    write_documents,
)
from src.navigation.odometry_evidence_r2.source_manifest import (  # noqa: E402
    load_descriptor,
    verify_harvest_against_descriptor,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--evidence-descriptor", required=True, type=Path)
    parser.add_argument("--harvest-root", required=True, type=Path)
    parser.add_argument("--mapping-root", required=True, type=Path)
    parser.add_argument("--mapping-evidence-manifest", required=True, type=Path)
    parser.add_argument("--p1a-input", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--generated-utc", required=True)
    return parser.parse_args()


def validate_generated_utc(value: object) -> str:
    if type(value) is not str or len(value) != 20:
        raise ContractValidationError("generated-utc must be YYYY-MM-DDTHH:MM:SSZ")
    try:
        parsed = datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(
            tzinfo=timezone.utc
        )
    except ValueError as exc:
        raise ContractValidationError(
            "generated-utc must be canonical RFC 3339 UTC"
        ) from exc
    if parsed.strftime("%Y-%m-%dT%H:%M:%SZ") != value:
        raise ContractValidationError("generated-utc is not canonical")
    return value


def resolve_p1a_input(path: Path) -> Path:
    candidate = path / "R2_P1A_RESULT.json" if path.is_dir() else path
    if not candidate.is_file():
        raise ContractValidationError("p1a-input must resolve to R2_P1A_RESULT.json")
    return candidate


def _contains(parent: Path, child: Path) -> bool:
    return child == parent or child.is_relative_to(parent)


def validate_output_location(
    output: Path,
    *,
    harvest_root: Path,
    mapping_root: Path,
    inputs: tuple[Path, ...],
) -> None:
    if output.exists() or output.is_symlink():
        raise ContractValidationError("output-dir must not exist or be a symlink")
    resolved = output.resolve(strict=False)
    repository = REPOSITORY_ROOT.resolve(strict=True)
    harvest = harvest_root.resolve(strict=True)
    mapping = mapping_root.resolve(strict=True)
    if _contains(repository, resolved) or _contains(harvest, resolved) or _contains(
        mapping, resolved
    ):
        raise ContractValidationError("output-dir overlaps a protected input root")
    for input_path in inputs:
        material = input_path.resolve(strict=True)
        if _contains(resolved, material) or _contains(material, resolved):
            raise ContractValidationError("output-dir overlaps a material input")


def main() -> int:
    args = parse_args()
    try:
        generated_utc = validate_generated_utc(args.generated_utc)
        if not args.harvest_root.is_dir() or not args.mapping_root.is_dir():
            raise ContractValidationError("harvest-root and mapping-root must exist")
        p1a_path = resolve_p1a_input(args.p1a_input)
        p2a_claims_path = (
            REPOSITORY_ROOT
            / "docs"
            / "Operaciones_HIL"
            / "Evidencia"
            / "R2_P2A_CLAIMS_LEDGER.json"
        )
        material_paths = (
            args.evidence_descriptor,
            p1a_path,
            args.mapping_evidence_manifest,
            p2a_claims_path,
        )
        validate_output_location(
            args.output_dir,
            harvest_root=args.harvest_root,
            mapping_root=args.mapping_root,
            inputs=material_paths,
        )
        descriptor = load_descriptor(args.evidence_descriptor)
        verification = verify_harvest_against_descriptor(
            descriptor,
            args.harvest_root,
        )
        if verification.get("manifest_verification") != "PASS":
            raise ContractValidationError("harvest descriptor verification failed")
        descriptor_schema = descriptor.get("descriptor_schema_version")
        if descriptor_schema != "1.0.0-p0a":
            raise ContractValidationError("evidence descriptor schema mismatch")
        descriptor_input = ValidatedInput(
            source_id="r2-p0a-evidence-descriptor",
            schema=descriptor_schema,
            sha256=sha256_file(args.evidence_descriptor),
            logical_path="external/portable_descriptor_v2.json",
            validation_context=ValidationContext.PHYSICAL_EVIDENCE,
            claim_strength=ClaimStrength.PRESERVED_PHYSICAL_EVIDENCE,
            limitations=(
                "Descriptor verifies preserved files; it is not new physical evidence.",
            ),
        )
        p1a_document = load_json_object(p1a_path, "p1a-input")
        p1a = validate_p1a_document(
            p1a_document,
            input_sha256=sha256_file(p1a_path),
        )
        mapping_document = load_json_object(
            args.mapping_evidence_manifest,
            "mapping-evidence-manifest",
        )
        mapping = validate_mapping_manifest(
            mapping_document,
            manifest_path=args.mapping_evidence_manifest,
            mapping_root=args.mapping_root,
        )
        p2a_claims_document = load_json_object(p2a_claims_path, "P2A claims ledger")
        if p2a_claims_document.get("schema_version") != "2.2.1-p2a":
            raise ContractValidationError("P2A claims ledger schema mismatch")
        p2a_claims_input = ValidatedInput(
            source_id="r2-p2a-claims-ledger",
            schema="2.2.1-p2a",
            sha256=sha256_file(p2a_claims_path),
            logical_path="docs/Operaciones_HIL/Evidencia/R2_P2A_CLAIMS_LEDGER.json",
            validation_context=ValidationContext.STRUCTURAL_ONLY,
            claim_strength=ClaimStrength.STRUCTURAL_POLICY,
            limitations=(
                "This ledger defines structural claims only and grants no publication.",
            ),
        )
        documents = build_documents(
            p1a=p1a,
            mapping=mapping,
            descriptor_input=descriptor_input,
            p2_claims_input=p2a_claims_input,
            generated_utc=generated_utc,
        )
        generated_claims = jsonable(
            documents["R2_P2A_CLAIMS_LEDGER.json"]
        )
        if p2a_claims_document.get("claims") != generated_claims["claims"]:
            raise ContractValidationError("P2A claims ledger content mismatch")
        write_documents(args.output_dir, documents)
    except (
        ContractValidationError,
        OSError,
        UnicodeError,
        ValueError,
    ) as exc:
        print(f"P2A_CONTRACT_BUILD_FAILED: {exc}", file=sys.stderr)
        return 2
    print("P2A_CONTRACT_BUILD=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
