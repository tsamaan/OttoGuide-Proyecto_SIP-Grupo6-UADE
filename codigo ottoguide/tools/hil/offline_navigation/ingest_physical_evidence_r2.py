#!/usr/bin/env python3
"""OTTOGUIDE -- MVP-ODOM-TF-R2-P0/P0A -- offline physical evidence ingest CLI.

Loads a hash-verified local physical-evidence harvest (R3C/R4/R4B) identified
by a portable descriptor, VERIFIES the harvest against the descriptor's
expected manifest hash + per-file expected hashes (section 11.5, closes
finding F5 -- a modified source file fails closed, it is never silently
accepted with a freshly-computed hash), ingests it through
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
        --generated-utc <ISO-8601 UTC string> \\
        [--harvest-root <path>]

--harvest-root overrides the descriptor's optional harvest_root_hint --
the local root MAY differ between machines (section 11.5).

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
from src.navigation.odometry_evidence_r2.source_manifest import (
    load_descriptor,
    resolve_harvest_root,
    verify_harvest_against_descriptor,
)
from src.navigation.odometry_evidence_r2.validation import EvidenceValidationError

_OUTPUT_DOCUMENTS = {
    "R2_PHYSICAL_EVIDENCE_BUNDLE.json": report.bundle_document,
    "R2_PHYSICAL_EVIDENCE_CLAIMS.json": report.claims_document,
    "R2_CHANNEL_COMPARISON.json": report.channel_comparison_document,
    "R2_TIME_DOMAIN_REPORT.json": report.time_domain_document,
    "R2_INGEST_PROVENANCE.json": report.provenance_document,
    "R2_INGEST_LIMITATIONS.json": report.limitations_document,
}


def run(descriptor_path: Path, output_dir: Path, generated_utc: str,
        harvest_root_override: "Path | None" = None) -> dict:
    descriptor = load_descriptor(descriptor_path)
    harvest_root = resolve_harvest_root(descriptor, descriptor_path, harvest_root_override)
    manifest_verification = verify_harvest_against_descriptor(descriptor, harvest_root)

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
        "manifest_verification": manifest_verification["manifest_verification"],
        "manifest_verified_file_count": manifest_verification["verified_file_count"],
        "harvest_id": manifest_verification["harvest_id"],
        "harvest_root": str(harvest_root),
        "generated_utc_injected": generated_utc,
        "session_count": len(bundle.sessions),
        "time_domain_count": len(bundle.time_domains),
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
    parser.add_argument(
        "--harvest-root", required=False, type=Path, default=None,
        help="Overrides descriptor.harvest_root_hint; the local harvest root "
             "may differ between machines.",
    )
    args = parser.parse_args(argv)

    try:
        summary = run(args.descriptor, args.output_dir, args.generated_utc, args.harvest_root)
    except EvidenceValidationError as exc:
        print(json.dumps({"result": "FAIL", "error": str(exc)}, indent=2, sort_keys=True))
        return 1

    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
