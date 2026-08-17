#!/usr/bin/env python3
"""OTTOGUIDE -- MVP-ODOM-TF-R2-P1 -- offline channel/time/motion
characterization CLI.

Verifies the harvest against the P0A portable descriptor (same trust
boundary as ingest_physical_evidence_r2.py, reused unmodified), reparses the
raw R3C/R4/R4B JSONL directly (never reuses P0A's already-derived numbers),
and writes deterministic JSON/CSV reports to --output-dir. Read-only against
the harvest; writes only inside --output-dir. No network, no ROS, no DDS, no
live Unitree SDK, no wall-clock read (--generated-utc is always injected).
Never selects an authoritative source channel.

Usage:
    python characterize_physical_odometry_r2.py \\
        --evidence-descriptor <portable_descriptor.json> \\
        --harvest-root <path> \\
        --output-dir <output_directory> \\
        --generated-utc <ISO-8601 UTC string>
"""
import argparse
import hashlib
import json
import sys
from pathlib import Path

_CODIGO_ROOT = Path(__file__).resolve().parents[3]
if str(_CODIGO_ROOT) not in sys.path:
    sys.path.insert(0, str(_CODIGO_ROOT))

from src.navigation.odometry_characterization_r2 import report
from src.navigation.odometry_evidence_r2.source_manifest import (
    load_descriptor,
    resolve_harvest_root,
    verify_harvest_against_descriptor,
)
from src.navigation.odometry_evidence_r2.validation import EvidenceValidationError

_JSON_DOCUMENTS = {
    "R2_P1_CHANNEL_QUALITY.json": report.channel_quality_document,
    "R2_P1_PRIMARY_LF_ALIGNMENT.json": report.alignment_document,
    "R2_P1_STATIONARY_CHARACTERIZATION.json": report.stationary_document,
    "R2_P1_MOTION_SEGMENT_METRICS.json": report.motion_document,
    "R2_P1_IMU_AGREEMENT.json": report.imu_document,
    "R2_P1_TIMEBASE_CHARACTERIZATION.json": report.timebase_document,
    "R2_P1_CHANNEL_ARBITRATION_MATRIX.json": report.arbitration_document,
    "R2_P1_DYNAMIC_RESIDUALS.json": report.dynamic_residuals_document,
    "R2_P1_CLAIMS_LEDGER.json": report.claims_document,
    "R2_P1_NOMINAL_CANDIDATES.json": report.nominal_candidates_document,
}
_CSV_DOCUMENTS = {
    "R2_P1_CHANNEL_QUALITY.csv": report.channel_quality_csv,
    "R2_P1_PRIMARY_LF_ALIGNMENT.csv": report.alignment_csv,
    "R2_P1_MOTION_SEGMENT_METRICS.csv": report.motion_csv,
}


def run(descriptor_path: Path, output_dir: Path, generated_utc: str,
        harvest_root_override: "Path | None" = None) -> dict:
    descriptor = load_descriptor(descriptor_path)
    harvest_root = resolve_harvest_root(descriptor, descriptor_path, harvest_root_override)
    manifest_verification = verify_harvest_against_descriptor(descriptor, harvest_root)

    bundle, raw_file_hashes = report.build_characterization_bundle(harvest_root, generated_utc)

    output_dir.mkdir(parents=True, exist_ok=True)
    written = []

    full_bundle_text = report.bundle_document(bundle)
    (output_dir / "R2_P1_RESULT.json").write_text(full_bundle_text, encoding="utf-8", newline="\n")
    written.append("R2_P1_RESULT.json")

    source_manifest_doc = json.dumps({
        "manifest_verification": manifest_verification["manifest_verification"],
        "manifest_verified_file_count": manifest_verification["verified_file_count"],
        "harvest_id": manifest_verification["harvest_id"],
        "raw_files_reparsed_count": len(raw_file_hashes),
        "raw_files_reparsed_sha256": dict(sorted(raw_file_hashes.items())),
    }, indent=2, sort_keys=True) + "\n"
    (output_dir / "R2_P1_SOURCE_MANIFEST.json").write_text(source_manifest_doc, encoding="utf-8", newline="\n")
    written.append("R2_P1_SOURCE_MANIFEST.json")

    provenance_doc = json.dumps({
        "generated_utc_injected": generated_utc,
        "harvest_id": manifest_verification["harvest_id"],
        "raw_files_by_relative_path_sha256": dict(sorted(raw_file_hashes.items())),
        "note": "Every raw JSONL file P1 reparsed directly (R3C/R4 chunked directories, "
                "R4B flat files) is hashed at read time; this is P1's own provenance "
                "ledger, distinct from and additional to the 13-file P0A descriptor "
                "which only pins the outer archive/report level.",
    }, indent=2, sort_keys=True) + "\n"
    (output_dir / "R2_P1_RAW_REPARSE_PROVENANCE.json").write_text(provenance_doc, encoding="utf-8", newline="\n")
    written.append("R2_P1_RAW_REPARSE_PROVENANCE.json")

    for filename, builder in _JSON_DOCUMENTS.items():
        (output_dir / filename).write_text(builder(bundle), encoding="utf-8", newline="\n")
        written.append(filename)
    for filename, builder in _CSV_DOCUMENTS.items():
        (output_dir / filename).write_text(builder(bundle), encoding="utf-8", newline="\n")
        written.append(filename)

    content_manifest_lines = []
    for filename in sorted(written):
        digest = hashlib.sha256((output_dir / filename).read_bytes()).hexdigest()
        content_manifest_lines.append(f"{digest}  {filename}\n")
    (output_dir / "CONTENT_MANIFEST.sha256").write_text("".join(content_manifest_lines), encoding="utf-8", newline="\n")
    written.append("CONTENT_MANIFEST.sha256")

    return {
        "result": "PASS",
        "tool": "characterize_physical_odometry_r2",
        "manifest_verification": manifest_verification["manifest_verification"],
        "manifest_verified_file_count": manifest_verification["verified_file_count"],
        "raw_files_reparsed_count": len(raw_file_hashes),
        "harvest_id": manifest_verification["harvest_id"],
        "harvest_root": str(harvest_root),
        "generated_utc_injected": generated_utc,
        "channel_quality_count": len(bundle.channel_quality),
        "alignment_count": len(bundle.alignment),
        "stationary_count": len(bundle.stationary),
        "motion_segment_count": len(bundle.motion),
        "imu_agreement_count": len(bundle.imu),
        "timebase_count": len(bundle.timebase),
        "nominal_scale_candidate_count": len(bundle.nominal_scale),
        "nominal_yaw_candidate_count": len(bundle.nominal_yaw),
        "dynamic_residual_count": len(bundle.dynamic_residuals),
        "claim_count": len(bundle.claims),
        "preferred_analysis_channel": bundle.arbitration.preferred_analysis_channel,
        "authoritative_source_channel": bundle.arbitration.authoritative_source_channel,
        "odom_publication_ready": False,
        "tf_publication_ready": False,
        "nav2_ready": False,
        "files_written": written,
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence-descriptor", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument(
        "--generated-utc", required=True,
        help="Injected ISO-8601 UTC timestamp; never sampled from the wall clock "
             "internally, so re-running with the same value is byte-deterministic.",
    )
    parser.add_argument(
        "--harvest-root", required=False, type=Path, default=None,
        help="Overrides descriptor.harvest_root_hint; the local harvest root may "
             "differ between machines.",
    )
    args = parser.parse_args(argv)

    try:
        summary = run(args.evidence_descriptor, args.output_dir, args.generated_utc, args.harvest_root)
    except EvidenceValidationError as exc:
        print(json.dumps({"result": "FAIL", "error": str(exc)}, indent=2, sort_keys=True))
        return 1

    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
