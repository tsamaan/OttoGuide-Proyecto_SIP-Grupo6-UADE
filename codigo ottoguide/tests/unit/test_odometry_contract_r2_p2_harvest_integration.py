import json
import os
from pathlib import Path

import pytest

from src.navigation.odometry_contract_r2_p2.covariance import (
    build_physical_source_unit_evidence,
)


HARVEST = os.environ.get("OTTOGUIDE_R2_HARVEST_ROOT")
P1A = os.environ.get("OTTOGUIDE_R2_P1A_INPUT")


@pytest.mark.skipif(
    not HARVEST or not P1A,
    reason="explicit physical evidence and P1A input not provided",
)
def test_real_preserved_evidence_remains_source_unit_only():
    harvest = Path(HARVEST)
    assert (harvest / "GLOBAL_LOCAL_MANIFEST_VERIFICATION.json").is_file()
    verification = json.loads(
        (harvest / "GLOBAL_LOCAL_MANIFEST_VERIFICATION.json").read_text()
    )
    assert verification["verification_pass"] is True
    assert verification["verified_file_count"] == 3418
    p1a_path = Path(P1A)
    if p1a_path.is_dir():
        p1a_path = p1a_path / "R2_P1A_RESULT.json"
    document = json.loads(p1a_path.read_text(encoding="utf-8-sig"))
    evidence = build_physical_source_unit_evidence(document)
    assert evidence
    assert all(record.units == "SOURCE_UNITS_UNRESOLVED" for record in evidence)
    assert all(record.ros_si_matrix is None for record in evidence)
    assert all(record.publication_ready is False for record in evidence)
