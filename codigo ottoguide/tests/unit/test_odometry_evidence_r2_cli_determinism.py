"""CLI-level determinism test: running ingest_physical_evidence_r2.py twice
over the same descriptor/harvest/--generated-utc must produce byte-identical
output files (checkpoint section 26). Uses subprocess deliberately here --
this is test/build tooling, explicitly outside the pure R2-P0 package the
static import gate covers.

Skipped (not failed) if the local physical-evidence harvest is not present
on this machine.
"""
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

_HARVEST_ROOT = Path(
    r"C:\Users\IdeaPad 3-15IILO5\Documents\OttoGuide-Final-Physical-Harvest"
    r"\FINAL-R4-20260720T204735Z"
)
_CODIGO_ROOT = Path(__file__).resolve().parents[2]
_CLI_PATH = _CODIGO_ROOT / "tools" / "hil" / "offline_navigation" / "ingest_physical_evidence_r2.py"


@unittest.skipUnless(_HARVEST_ROOT.is_dir(), "local physical-evidence harvest not present on this machine")
class TestCliDeterminism(unittest.TestCase):
    def test_two_runs_byte_identical(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            descriptor_path = tmp_path / "descriptor.json"
            descriptor_path.write_text(
                json.dumps({"harvest_root": str(_HARVEST_ROOT)}), encoding="utf-8"
            )
            out1 = tmp_path / "run1"
            out2 = tmp_path / "run2"

            for out_dir in (out1, out2):
                result = subprocess.run(
                    [sys.executable, str(_CLI_PATH),
                     "--descriptor", str(descriptor_path),
                     "--output-dir", str(out_dir),
                     "--generated-utc", "2026-07-21T00:00:00Z"],
                    capture_output=True, text=True, timeout=120,
                )
                self.assertEqual(result.returncode, 0, result.stderr)

            files1 = sorted(p.name for p in out1.glob("*.json"))
            files2 = sorted(p.name for p in out2.glob("*.json"))
            self.assertEqual(files1, files2)
            self.assertGreater(len(files1), 0)
            for name in files1:
                self.assertEqual(
                    (out1 / name).read_bytes(), (out2 / name).read_bytes(),
                    f"{name} differs between runs",
                )

    def test_missing_descriptor_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            result = subprocess.run(
                [sys.executable, str(_CLI_PATH),
                 "--descriptor", str(tmp_path / "does_not_exist.json"),
                 "--output-dir", str(tmp_path / "out"),
                 "--generated-utc", "2026-07-21T00:00:00Z"],
                capture_output=True, text=True, timeout=60,
            )
            self.assertEqual(result.returncode, 1)


if __name__ == "__main__":
    unittest.main()
