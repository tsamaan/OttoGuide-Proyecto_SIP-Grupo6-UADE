#!/usr/bin/env python3
"""OTTOGUIDE -- MVP-ODOM-TF-R2-P0 -- offline physical evidence ingest CLI.

Loads a hash-verified local physical-evidence harvest (R3C/R4/R4B) and a
descriptor identifying it, ingests it through
src.navigation.odometry_evidence_r2, and writes six deterministic JSON
reports to --output-dir. Read-only against the harvest; WRITES only inside
--output-dir.

No network, no ROS, no DDS, no live Unitree SDK. Does NOT publish /odom, TF,
/scan, a map, localization, cmd_vel, or Nav2 -- see
docs/Arquitectura/ODOM_TF_R2_PHYSICAL_EVIDENCE_CONTRACT.md.

Usage:
    python ingest_physical_evidence_r2.py \\
        --descriptor <portable_descriptor.json> \\
        --output-dir <output_directory> \\
        --generated-utc <ISO-8601 UTC string>

--generated-utc is REQUIRED and is never sampled from the wall clock
internally: running this CLI twice with the same --descriptor, --output-dir
contents pointed at the same harvest, and the same --generated-utc value
must produce byte-identical output files (see
tests/unit/test_odometry_evidence_r2_cli_determinism.py).
"""
import argparse
import json
import sys
from pathlib import Path

_CODIGO_ROOT = Path(__file__).resolve().parents[3]
if str(_CODIGO_ROOT) not in sys.path:
    sys.path.insert(0, str(_CODIGO_ROOT))

from src.navigation.odometry_evidence_r2 import ingest, report
from src.navigation.odometry_evidence_r2.validation import EvidenceValidationError


def _load_descriptor(descriptor_path: Path) -> dict:
    if not descriptor_path.is_file():
        raise EvidenceValidationError(f"descriptor not found: {descriptor_path}")
    with open(descriptor_path, "r", encoding="utf-8-sig") as handle:
        try:
            descriptor = json.load(handle)
        except json.JSONDecodeError as exc:
            raise EvidenceValidationError(
                f"descriptor is not valid JSON: {descriptor_path}: {exc}"
            ) from exc
    if type(descriptor) is not dict:
        raise EvidenceValidationError("descriptor must be a JSON object")
    if "harvest_root" not in descriptor:
        raise EvidenceValidationError("descriptor missing required key: harvest_root")
    return descriptor


def _resolve_harvest_root(descriptor: dict, descriptor_path: Path) -> Path:
    harvest_root_value = descriptor["harvest_root"]
    if type(harvest_root_value) is not str or not harvest_root_value:
        raise EvidenceValidationError("descriptor.harvest_root must be a non-empty string")
    harvest_root = Path(harvest_root_value)
    if not harvest_root.is_absolute():
        harvest_root = (descriptor_path.parent / harvest_root).resolve()
    if not harvest_root.is_dir():
        raise EvidenceValidationError(f"harvest_root does not exist: {harvest_root}")
    return harvest_root


_OUTPUT_DOCUMENTS = {
    "R2_PHYSICAL_EVIDENCE_BUNDLE.json": report.bundle_document,
    "R2_PHYSICAL_EVIDENCE_CLAIMS.json": report.claims_document,
    "R2_CHANNEL_COMPARISON.json": report.channel_comparison_document,
    "R2_TIME_DOMAIN_REPORT.json": report.time_domain_document,
    "R2_INGEST_PROVENANCE.json": report.provenance_document,
    "R2_INGEST_LIMITATIONS.json": report.limitations_document,
}


def run(descriptor_path: Path, output_dir: Path, generated_utc: str) -> dict:
    descriptor = _load_descriptor(descriptor_path)
    harvest_root = _resolve_harvest_root(descriptor, descriptor_path)

    bundle = ingest.build_bundle(harvest_root, generated_utc)

    output_dir.mkdir(parents=True, exist_ok=True)
    written = []
    for filename, builder in _OUTPUT_DOCUMENTS.items():
        document_text = builder(bundle)
        out_path = output_dir / filename
        out_path.write_text(document_text, encoding="utf-8", newline="\n")
        written.append(filename)

    return {
        "result": "PASS",
        "tool": "ingest_physical_evidence_r2",
        "harvest_root": str(harvest_root),
        "generated_utc_injected": generated_utc,
        "session_count": len(bundle.sessions),
        "dynamic_segment_count": len(bundle.dynamic_segments),
        "stationary_segment_count": len(bundle.stationary_segments),
        "claim_count": len(bundle.claims),
        "authoritative_source_channel": bundle.channel_comparison.authoritative_source_channel,
        "covariance_publication_model_ready": bundle.covariance.publication_model_ready,
        "odom_publication_ready": False,
        "tf_publication_ready": False,
        "nav2_ready": False,
        "files_written": written,
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--descriptor", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument(
        "--generated-utc", required=True,
        help="Injected ISO-8601 UTC timestamp; never sampled from the wall clock "
             "internally, so re-running with the same value is byte-deterministic.",
    )
    args = parser.parse_args(argv)

    try:
        summary = run(args.descriptor, args.output_dir, args.generated_utc)
    except EvidenceValidationError as exc:
        print(json.dumps({"result": "FAIL", "error": str(exc)}, indent=2, sort_keys=True))
        return 1

    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
