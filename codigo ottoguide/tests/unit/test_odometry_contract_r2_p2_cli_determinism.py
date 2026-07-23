import os
from pathlib import Path
import subprocess
import sys
import tempfile

import pytest


HARVEST = os.environ.get("OTTOGUIDE_R2_HARVEST_ROOT")
MAPPING = os.environ.get("OTTOGUIDE_P2_MAPPING_ROOT")
DESCRIPTOR = os.environ.get("OTTOGUIDE_R2_P0A_DESCRIPTOR")
P1A = os.environ.get("OTTOGUIDE_R2_P1A_INPUT")
CLI = (
    Path(__file__).resolve().parents[2]
    / "tools"
    / "hil"
    / "offline_navigation"
    / "build_odom_tf_r2_p2_contract.py"
)


@pytest.mark.skipif(
    not all((HARVEST, MAPPING, DESCRIPTOR, P1A)),
    reason="explicit P2 integration inputs not provided",
)
def test_cli_is_byte_deterministic_and_contains_no_personal_paths():
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp)
        outputs = []
        for name in ("one", "two"):
            out = root / name
            result = subprocess.run(
                [
                    sys.executable,
                    str(CLI),
                    "--evidence-descriptor",
                    DESCRIPTOR,
                    "--harvest-root",
                    HARVEST,
                    "--mapping-root",
                    MAPPING,
                    "--p1a-input",
                    P1A,
                    "--output-dir",
                    str(out),
                    "--generated-utc",
                    "2026-07-23T12:00:00Z",
                ],
                capture_output=True,
                text=True,
                timeout=180,
            )
            assert result.returncode == 0, result.stderr
            outputs.append(out)
        names = sorted(path.name for path in outputs[0].iterdir())
        assert names == sorted(path.name for path in outputs[1].iterdir())
        for name in names:
            left = (outputs[0] / name).read_bytes()
            right = (outputs[1] / name).read_bytes()
            assert left == right
            assert b"C:\\Users\\" not in left
            assert b"C:/Users/" not in left
