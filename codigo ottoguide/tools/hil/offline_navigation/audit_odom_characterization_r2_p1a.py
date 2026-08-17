#!/usr/bin/env python3
"""OTTOGUIDE -- MVP-ODOM-TF-R2-P1A -- quantitative audit and claim-hardening
CLI.

Builds on top of (does not replace) characterize_physical_odometry_r2.py's
P1 bundle -- same descriptor/manifest verification, same raw reparse -- and
adds the P1A audit layer: corrected dropout semantics, pairing-offset vs
causal-lag separation, yaw angle/speed unit separation, segment eligibility,
corrected channel arbitration, boot-relation evidence, and the 10 H1-H10
audit findings. Read-only against the harvest; writes only inside
--output-dir. No network, no ROS, no Nav2, no wall-clock read.

Usage:
    python audit_odom_characterization_r2_p1a.py \\
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

from src.navigation.odometry_characterization_r2 import p1a_audit
from src.navigation.odometry_evidence_r2.source_manifest import (
    load_descriptor,
    resolve_harvest_root,
    verify_harvest_against_descriptor,
)
from src.navigation.odometry_evidence_r2.validation import EvidenceValidationError

_JSON_DOCUMENTS = {
    "R2_P1A_AUDIT_FINDINGS.json": p1a_audit.audit_findings_document,
    "R2_P1A_DROPOUT_SEMANTICS.json": p1a_audit.dropout_semantics_document,
    "R2_P1A_CHANNEL_QUALITY_CORRECTED.json": p1a_audit.channel_quality_corrected_document,
    "R2_P1A_PAIRING_OFFSET_ANALYSIS.json": p1a_audit.pairing_offset_document,
    "R2_P1A_CAUSAL_LAG_ANALYSIS.json": p1a_audit.causal_lag_document,
    "R2_P1A_ALIGNMENT_CORRECTED.json": p1a_audit.alignment_corrected_document,
    "R2_P1A_YAW_METRICS_AUDIT.json": p1a_audit.yaw_metrics_audit_document,
    "R2_P1A_SEGMENT_ELIGIBILITY.json": p1a_audit.segment_eligibility_document,
    "R2_P1A_CHANNEL_ARBITRATION_AUDIT.json": p1a_audit.arbitration_audit_document,
    "R2_P1A_CHANNEL_ARBITRATION_MATRIX_CORRECTED.json": p1a_audit.arbitration_matrix_corrected_document,
    "R2_P1A_BOOT_RELATION_AUDIT.json": p1a_audit.boot_relation_audit_document,
    "R2_P1A_CLAIMS_LEDGER.json": p1a_audit.claims_document,
}
_CSV_DOCUMENTS = {
    "R2_P1A_CHANNEL_QUALITY_CORRECTED.csv": p1a_audit.channel_quality_corrected_csv,
    "R2_P1A_ALIGNMENT_CORRECTED.csv": p1a_audit.alignment_corrected_csv,
    "R2_P1A_YAW_SEGMENT_COMPARISON.csv": p1a_audit.yaw_segment_comparison_csv,
}


def run(descriptor_path: Path, output_dir: Path, generated_utc: str,
        harvest_root_override: "Path | None" = None) -> dict:
    descriptor = load_descriptor(descriptor_path)
    harvest_root = resolve_harvest_root(descriptor, descriptor_path, harvest_root_override)
    manifest_verification = verify_harvest_against_descriptor(descriptor, harvest_root)

    bundle, raw_file_hashes = p1a_audit.build_p1a_bundle(harvest_root, generated_utc)

    output_dir.mkdir(parents=True, exist_ok=True)
    written = []

    (output_dir / "R2_P1A_RESULT.json").write_text(p1a_audit.result_document(bundle), encoding="utf-8", newline="\n")
    written.append("R2_P1A_RESULT.json")

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
        "tool": "audit_odom_characterization_r2_p1a",
        "manifest_verification": manifest_verification["manifest_verification"],
        "raw_files_reparsed_count": len(raw_file_hashes),
        "generated_utc_injected": generated_utc,
        "audit_findings_count": len(bundle.audit_findings),
        "claim_count": len(bundle.claims),
        "arbitration_criterion_count": bundle.arbitration_audit.criterion_count,
        "preferred_analysis_channel": bundle.p1_bundle.arbitration.preferred_analysis_channel,
        "authoritative_source_channel": bundle.arbitration_audit.authoritative_source_channel,
        "r4b_boot_relation_same_boot_verified": bundle.boot_relation_evidence[0].same_boot_verified,
        "files_written": written,
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence-descriptor", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--generated-utc", required=True)
    parser.add_argument("--harvest-root", required=False, type=Path, default=None)
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
