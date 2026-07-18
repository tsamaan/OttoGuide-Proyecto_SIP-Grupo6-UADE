#!/usr/bin/env python3
"""MVP-ODOM-TF-R1 offline CLI verifier.

Loads the real MFR-R6 SportModeState fixtures, runs the pure adapter, runs the
new offline readiness gate against the current physical evidence contract, and
prints a single deterministic JSON document to stdout.

Strictly offline: no network, no clock, no hardware, no ROS, no DDS, no file
WRITES (fixtures are read-only). Exit code:

  0  -> the result is exactly the expected, fail-closed outcome
        (offline contract processable, publication + TF withheld, nav2 false).
  1+ -> any internal inconsistency, or an accidental readiness
        (odom/tf/nav2 ready True), which must never happen in this checkpoint.

This tool never authorizes `/odom` or TF publication. A green exit here means
only that the gate correctly refuses to publish, not that publishing is allowed.
"""
import json
import sys
from pathlib import Path

# Resolve the repo's "codigo ottoguide" root so `src...` imports work whether
# this is run from that directory or elsewhere. This tool lives at
# codigo ottoguide/tools/hil/offline_navigation/verify_odom_tf_readiness.py.
_CODIGO_ROOT = Path(__file__).resolve().parents[3]
if str(_CODIGO_ROOT) not in sys.path:
    sys.path.insert(0, str(_CODIGO_ROOT))

from src.navigation.odometry_candidate_adapter import (  # noqa: E402
    assess_odom_tf_readiness,
    to_odometry_candidate,
)
from src.navigation.odometry_candidate_adapter.readiness import (  # noqa: E402
    CLASSIFICATION_CONTRACT_READY,
    OdomTfEvidenceContract,
)

_FIXTURES_DIR = (
    _CODIGO_ROOT / "tests" / "fixtures" / "mfr_r6_sportmodestate"
)
_PRIMARY = _FIXTURES_DIR / "mfr_r6_primary_rt_odommodestate.jsonl"
_SECONDARY = _FIXTURES_DIR / "mfr_r6_secondary_rt_lf_odommodestate.jsonl"


def _load_jsonl(path):
    with path.open(encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def build_report():
    """Load fixtures, run adapter + gate, return the readiness report."""
    primary = _load_jsonl(_PRIMARY)
    secondary = _load_jsonl(_SECONDARY)
    samples = primary + secondary
    candidates = [to_odometry_candidate(s) for s in samples]

    # The evidence contract reflects the CURRENT physical reality: only a
    # stationary capture exists, no channel arbitrated, frame/axis/scale/sign
    # unverified, no covariance, IMU all-zero, no ROS-time mapping, reset
    # behavior uncharacterized. Every field left at its conservative default.
    contract = OdomTfEvidenceContract()
    report = assess_odom_tf_readiness(candidates, contract)
    return report, len(primary), len(secondary)


def _consistency_errors(report, primary_count, secondary_count):
    """Return a list of internal-consistency violations (empty == consistent).

    Any accidental readiness, or a shape that contradicts the checkpoint's
    fixed expectations, is an error that must force a non-zero exit.
    """
    errors = []

    # Fixed invariants for this checkpoint.
    if report.odom_publication_ready:
        errors.append("odom_publication_ready is True (must be False)")
    if report.odom_to_base_link_tf_ready:
        errors.append("odom_to_base_link_tf_ready is True (must be False)")
    if report.nav2_ready:
        errors.append("nav2_ready is True (must always be False)")
    if not report.physical_validation_required:
        errors.append("physical_validation_required is False (must be True)")
    if report.blocker_count < 1:
        errors.append("no BLOCKER present (fail-closed gate must block)")
    if report.classification != CLASSIFICATION_CONTRACT_READY:
        errors.append(
            f"classification {report.classification!r} != expected "
            f"{CLASSIFICATION_CONTRACT_READY!r}"
        )

    # Expected fixture shape (160 samples, two channels, all valid).
    expected_total = primary_count + secondary_count
    if report.candidate_count != expected_total:
        errors.append(
            f"candidate_count {report.candidate_count} != {expected_total}"
        )
    if report.candidate_invalid_count != 0:
        errors.append(
            f"candidate_invalid_count {report.candidate_invalid_count} != 0"
        )
    if len(report.channels) != 2:
        errors.append(f"channels count {len(report.channels)} != 2")

    # offline_contract_ready must be True (input processable) while publication
    # is still withheld -- the two axes must not collapse into one.
    if not report.offline_contract_ready:
        errors.append("offline_contract_ready is False (input is processable)")

    return errors


def main(argv=None):
    report, primary_count, secondary_count = build_report()
    errors = _consistency_errors(report, primary_count, secondary_count)

    out = {
        "checkpoint": "MVP-ODOM-TF-R1",
        "tool": "verify_odom_tf_readiness",
        "fixture_primary_count": primary_count,
        "fixture_secondary_count": secondary_count,
        "report": report.to_dict(),
        "consistency_errors": errors,
        "result": "PASS" if not errors else "FAIL",
    }
    # Deterministic JSON: sorted keys, fixed separators, trailing newline.
    sys.stdout.write(json.dumps(out, indent=2, sort_keys=True) + "\n")
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
