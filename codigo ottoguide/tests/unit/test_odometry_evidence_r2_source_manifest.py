"""Unit tests for src.navigation.odometry_evidence_r2.source_manifest
(section 11.5, closes finding F5): descriptor loading, harvest-root
relocation, and fail-closed manifest/hash verification."""
import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from src.navigation.odometry_evidence_r2 import source_manifest as sm
from src.navigation.odometry_evidence_r2.validation import EvidenceValidationError


def _sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    digest.update(path.read_bytes())
    return digest.hexdigest()


def _make_harvest(root: Path):
    root.mkdir(parents=True, exist_ok=True)
    manifest_path = root / "FINAL_PHYSICAL_HARVEST_INDEX.json"
    manifest_path.write_text(json.dumps({"HARVEST_ID": "TEST-HARVEST-1"}), encoding="utf-8")
    source_path = root / "some_report.json"
    source_path.write_text(json.dumps({"value": 1}), encoding="utf-8")
    return manifest_path, source_path


def _make_descriptor(root: Path, manifest_path: Path, source_path: Path, **overrides) -> dict:
    descriptor = {
        "descriptor_schema_version": sm.DESCRIPTOR_SCHEMA_VERSION,
        "harvest_id": "TEST-HARVEST-1",
        "manifest_relative_path": manifest_path.name,
        "manifest_sha256": _sha256_of(manifest_path),
        "expected_source_files": [source_path.name],
        "expected_source_sha256": [_sha256_of(source_path)],
        "harvest_root_hint": str(root),
    }
    descriptor.update(overrides)
    return descriptor


class TestLoadDescriptor(unittest.TestCase):
    def test_valid_descriptor_loads(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "harvest"
            manifest_path, source_path = _make_harvest(root)
            descriptor_path = Path(tmp) / "descriptor.json"
            descriptor_path.write_text(
                json.dumps(_make_descriptor(root, manifest_path, source_path)), encoding="utf-8"
            )
            descriptor = sm.load_descriptor(descriptor_path)
            self.assertEqual(descriptor["harvest_id"], "TEST-HARVEST-1")

    def test_missing_required_field_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            descriptor_path = Path(tmp) / "descriptor.json"
            descriptor_path.write_text(json.dumps({"harvest_id": "x"}), encoding="utf-8")
            with self.assertRaises(EvidenceValidationError):
                sm.load_descriptor(descriptor_path)

    def test_wrong_schema_version_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "harvest"
            manifest_path, source_path = _make_harvest(root)
            descriptor_path = Path(tmp) / "descriptor.json"
            descriptor_path.write_text(
                json.dumps(_make_descriptor(root, manifest_path, source_path,
                                             descriptor_schema_version="0.0.1")),
                encoding="utf-8",
            )
            with self.assertRaises(EvidenceValidationError):
                sm.load_descriptor(descriptor_path)

    def test_absolute_expected_source_file_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "harvest"
            manifest_path, source_path = _make_harvest(root)
            descriptor_path = Path(tmp) / "descriptor.json"
            bad = _make_descriptor(root, manifest_path, source_path)
            bad["expected_source_files"] = [r"C:\Windows\System32\evil.json"]
            descriptor_path.write_text(json.dumps(bad), encoding="utf-8")
            with self.assertRaises(EvidenceValidationError):
                sm.load_descriptor(descriptor_path)

    def test_path_traversal_expected_source_file_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "harvest"
            manifest_path, source_path = _make_harvest(root)
            descriptor_path = Path(tmp) / "descriptor.json"
            bad = _make_descriptor(root, manifest_path, source_path)
            bad["expected_source_files"] = ["../../etc/passwd"]
            descriptor_path.write_text(json.dumps(bad), encoding="utf-8")
            with self.assertRaises(EvidenceValidationError):
                sm.load_descriptor(descriptor_path)

    def test_files_hashes_length_mismatch_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "harvest"
            manifest_path, source_path = _make_harvest(root)
            descriptor_path = Path(tmp) / "descriptor.json"
            bad = _make_descriptor(root, manifest_path, source_path)
            bad["expected_source_sha256"] = []
            descriptor_path.write_text(json.dumps(bad), encoding="utf-8")
            with self.assertRaises(EvidenceValidationError):
                sm.load_descriptor(descriptor_path)


class TestResolveHarvestRoot(unittest.TestCase):
    def test_explicit_override_wins(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "harvest"
            root.mkdir()
            descriptor = {"harvest_root_hint": "/nonexistent/path"}
            resolved = sm.resolve_harvest_root(descriptor, Path(tmp) / "descriptor.json", root)
            self.assertEqual(resolved, root)

    def test_relative_hint_resolved_against_descriptor_directory(self):
        # Portable descriptor relocation (section 11.5/12): a relative hint
        # must resolve relative to the descriptor's OWN directory, not the
        # current working directory -- this is what makes moving the
        # descriptor + harvest together to another machine work.
        with tempfile.TemporaryDirectory() as tmp:
            descriptor_dir = Path(tmp) / "wherever_the_descriptor_lives"
            descriptor_dir.mkdir()
            harvest_root = descriptor_dir / "harvest_subdir"
            harvest_root.mkdir()
            descriptor = {"harvest_root_hint": "harvest_subdir"}
            resolved = sm.resolve_harvest_root(
                descriptor, descriptor_dir / "descriptor.json", None
            )
            self.assertEqual(resolved.resolve(), harvest_root.resolve())

    def test_missing_hint_and_no_override_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(EvidenceValidationError):
                sm.resolve_harvest_root({}, Path(tmp) / "descriptor.json", None)

    def test_nonexistent_root_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(EvidenceValidationError):
                sm.resolve_harvest_root(
                    {}, Path(tmp) / "descriptor.json", Path(tmp) / "does_not_exist"
                )


class TestVerifyHarvestAgainstDescriptor(unittest.TestCase):
    def test_matching_harvest_passes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "harvest"
            manifest_path, source_path = _make_harvest(root)
            descriptor = _make_descriptor(root, manifest_path, source_path)
            result = sm.verify_harvest_against_descriptor(descriptor, root)
            self.assertEqual(result["manifest_verification"], "PASS")
            self.assertEqual(result["verified_file_count"], 1)

    def test_tampered_source_file_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "harvest"
            manifest_path, source_path = _make_harvest(root)
            descriptor = _make_descriptor(root, manifest_path, source_path)
            source_path.write_text(json.dumps({"value": 999}), encoding="utf-8")
            with self.assertRaises(EvidenceValidationError):
                sm.verify_harvest_against_descriptor(descriptor, root)

    def test_tampered_manifest_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "harvest"
            manifest_path, source_path = _make_harvest(root)
            descriptor = _make_descriptor(root, manifest_path, source_path)
            manifest_path.write_text(json.dumps({"HARVEST_ID": "DIFFERENT"}), encoding="utf-8")
            with self.assertRaises(EvidenceValidationError):
                sm.verify_harvest_against_descriptor(descriptor, root)

    def test_missing_source_file_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "harvest"
            manifest_path, source_path = _make_harvest(root)
            descriptor = _make_descriptor(root, manifest_path, source_path)
            source_path.unlink()
            with self.assertRaises(EvidenceValidationError):
                sm.verify_harvest_against_descriptor(descriptor, root)

    def test_harvest_id_mismatch_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "harvest"
            manifest_path, source_path = _make_harvest(root)
            descriptor = _make_descriptor(root, manifest_path, source_path,
                                           harvest_id="WRONG-HARVEST-ID")
            with self.assertRaises(EvidenceValidationError):
                sm.verify_harvest_against_descriptor(descriptor, root)


if __name__ == "__main__":
    unittest.main()
