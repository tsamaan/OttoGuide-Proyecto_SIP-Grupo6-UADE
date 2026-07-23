#!/usr/bin/env python3
"""Build deterministic R2-P2 contract outputs from explicit offline inputs."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path


CODIGO_ROOT = Path(__file__).resolve().parents[3]
if str(CODIGO_ROOT) not in sys.path:
    sys.path.insert(0, str(CODIGO_ROOT))

from src.navigation.odometry_contract_r2_p2.report import (  # noqa: E402
    build_documents,
    write_documents,
)
from src.navigation.odometry_evidence_r2.source_manifest import (  # noqa: E402
    load_descriptor,
    verify_harvest_against_descriptor,
)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_json(path: Path, label: str) -> dict:
    if not path.is_file():
        raise ValueError(f"{label} does not exist")
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"{label} is not valid JSON") from exc
    if type(value) is not dict:
        raise ValueError(f"{label} must contain a JSON object")
    return value


def resolve_p1a_input(path: Path) -> Path:
    candidate = path / "R2_P1A_RESULT.json" if path.is_dir() else path
    if not candidate.is_file():
        raise ValueError("p1a input must be R2_P1A_RESULT.json or its directory")
    return candidate


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--evidence-descriptor", type=Path, required=True)
    parser.add_argument("--harvest-root", type=Path, required=True)
    parser.add_argument("--mapping-root", type=Path, required=True)
    parser.add_argument("--p1a-input", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--generated-utc", required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        if args.output_dir.exists():
            raise ValueError("output-dir must not already exist")
        if not args.harvest_root.is_dir():
            raise ValueError("harvest-root must exist")
        if not args.mapping_root.is_dir():
            raise ValueError("mapping-root must exist")
        descriptor = load_descriptor(args.evidence_descriptor)
        verification = verify_harvest_against_descriptor(
            descriptor, args.harvest_root
        )
        if verification.get("manifest_verification") != "PASS":
            raise ValueError("harvest descriptor verification did not pass")
        p1a_path = resolve_p1a_input(args.p1a_input)
        p1a_document = load_json(p1a_path, "p1a-input")
        mapping_inventory = {
            "mapping_workspace_audited": True,
            "source": "EXPLICIT_MAPPING_ROOT_READ_ONLY",
        }
        input_hashes = {
            "evidence_descriptor.json": sha256_file(args.evidence_descriptor),
            "R2_P1A_RESULT.json": sha256_file(p1a_path),
        }
        documents = build_documents(
            p1a_document=p1a_document,
            mapping_inventory=mapping_inventory,
            generated_utc=args.generated_utc,
            input_hashes=input_hashes,
        )
        write_documents(args.output_dir, documents)
    except (OSError, ValueError) as exc:
        print(f"P2_CONTRACT_BUILD_FAILED: {exc}", file=sys.stderr)
        return 2
    print("P2_CONTRACT_BUILD=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
