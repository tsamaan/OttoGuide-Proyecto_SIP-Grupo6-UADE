"""CLI-level determinism and manifest-tamper tests: running
ingest_physical_evidence_r2.py twice over the same descriptor/harvest/
--generated-utc must produce byte-identical output files (checkpoint
section 26), and a modified source file must fail closed rather than being
silently accepted (section 11.5 / finding F5). Uses subprocess deliberately
here -- this is test/build tooling, explicitly outside the pure R2-P0
package the static import gate covers.

HARVEST_INTEGRATION_TESTS: opt-in via OTTOGUIDE_R2_HARVEST_ROOT (never a
hardcoded personal path -- closes finding F9). Unset -> skipped. Set but
pointing nowhere -> must fail, not silently skip (section 11.11).
"""
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

_HARVEST_ROOT_ENV = os.environ.get("OTTOGUIDE_R2_HARVEST_ROOT")
_HARVEST_ROOT = Path(_HARVEST_ROOT_ENV) if _HARVEST_ROOT_ENV else None
_CODIGO_ROOT = Path(__file__).resolve().parents[2]
_CLI_PATH = _CODIGO_ROOT / "tools" / "hil" / "offline_navigation" / "ingest_physical_evidence_r2.py"

_EXPECTED_SOURCE_FILES = (
    "FINAL_PHYSICAL_HARVEST_INDEX.json",
    "01_route_raw/route_power_cycle_seal/POWER_CYCLE_SEAL.json",
    "09_analysis/ROUTE_SEQUENCE_REPORT.json",
    "01_route_raw/route_hilroute-20260720T194910Z.tar.gz",
    "02_postboot_stationary/TIMEBASE_ESTIMATE.json",
    "09_analysis/ODOM_RESET_COMPARISON.json",
    "02_postboot_stationary/POSTBOOT_CAPTURE.tar.gz",
    "10_r4b/R4B_RESULT.json",
    "10_r4b/R4B_CHANNEL_COMPARISON.json",
    "10_r4b/R4B_OPERATOR_ANNOTATION.json",
    "10_r4b/R4B_GROUND_TRUTH_SURVEY.json",
    "10_r4b/R4B_IMU_CROSSCHECK.json",
    "10_r4b/R4B_LIDAR_EXTRINSIC_INPUTS.json",
)


def _sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    digest.update(path.read_bytes())
    return digest.hexdigest()


def _build_descriptor(harvest_root: Path) -> dict:
    manifest_relative = "FINAL_PHYSICAL_HARVEST_INDEX.json"
    return {
        "descriptor_schema_version": "1.0.0-p0a",
        "harvest_id": "FINAL-R4-20260720T204735Z",
        "manifest_relative_path": manifest_relative,
        "manifest_sha256": _sha256_of(harvest_root / manifest_relative),
        "expected_source_files": list(_EXPECTED_SOURCE_FILES),
        "expected_source_sha256": [_sha256_of(harvest_root / f) for f in _EXPECTED_SOURCE_FILES],
        "harvest_root_hint": str(harvest_root),
    }


@unittest.skipUnless(
    _HARVEST_ROOT is not None,
    "OTTOGUIDE_R2_HARVEST_ROOT not set; harvest integration tests are opt-in",
)
class TestCliDeterminism(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not _HARVEST_ROOT.is_dir():
            raise RuntimeError(
                f"OTTOGUIDE_R2_HARVEST_ROOT={_HARVEST_ROOT} does not exist; "
                "harvest integration tests must fail here, not silently skip"
            )

    def test_two_runs_byte_identical(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            descriptor_path = tmp_path / "descriptor.json"
            descriptor_path.write_text(
                json.dumps(_build_descriptor(_HARVEST_ROOT)), encoding="utf-8"
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

    def test_tampered_source_file_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            harvest_copy = tmp_path / "harvest"
            # Only copy the small files this test needs to tamper with and
            # verify against -- a full harvest copy would be hundreds of MB.
            (harvest_copy / "10_r4b").mkdir(parents=True)
            for name in ("FINAL_PHYSICAL_HARVEST_INDEX.json", "10_r4b/R4B_RESULT.json"):
                src = _HARVEST_ROOT / name
                dst = harvest_copy / name
                dst.write_bytes(src.read_bytes())

            descriptor = _build_descriptor(_HARVEST_ROOT)
            descriptor["expected_source_files"] = ["10_r4b/R4B_RESULT.json"]
            descriptor["expected_source_sha256"] = [_sha256_of(_HARVEST_ROOT / "10_r4b/R4B_RESULT.json")]
            descriptor_path = tmp_path / "descriptor.json"
            descriptor_path.write_text(json.dumps(descriptor), encoding="utf-8")

            with open(harvest_copy / "10_r4b/R4B_RESULT.json", "a", encoding="utf-8") as handle:
                handle.write("\n// tampered\n")

            result = subprocess.run(
                [sys.executable, str(_CLI_PATH),
                 "--descriptor", str(descriptor_path),
                 "--output-dir", str(tmp_path / "out"),
                 "--generated-utc", "2026-07-21T00:00:00Z",
                 "--harvest-root", str(harvest_copy)],
                capture_output=True, text=True, timeout=60,
            )
            self.assertEqual(result.returncode, 1)
            payload = json.loads(result.stdout)
            self.assertEqual(payload["result"], "FAIL")
            self.assertIn("R4B_RESULT.json", payload["error"])

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
