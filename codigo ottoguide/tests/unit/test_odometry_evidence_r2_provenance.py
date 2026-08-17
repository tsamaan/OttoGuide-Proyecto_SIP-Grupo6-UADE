"""Unit tests for src.navigation.odometry_evidence_r2.provenance."""
import hashlib
import tempfile
import unittest
from pathlib import Path

from src.navigation.odometry_evidence_r2.provenance import build_provenance, sha256_of_file
from src.navigation.odometry_evidence_r2.validation import EvidenceValidationError


class TestShaOfFile(unittest.TestCase):
    def test_hash_matches_hashlib(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "sample.txt"
            path.write_bytes(b"hello world")
            expected = hashlib.sha256(b"hello world").hexdigest()
            self.assertEqual(sha256_of_file(path), expected)

    def test_missing_file_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(EvidenceValidationError):
                sha256_of_file(Path(tmp) / "does_not_exist.txt")


class TestBuildProvenance(unittest.TestCase):
    def test_relative_path_recorded_no_absolute_leak(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "subdir").mkdir()
            source = root / "subdir" / "evidence.json"
            source.write_text("{}", encoding="utf-8")

            prov = build_provenance(
                evidence_id="test.evidence",
                source_package="TEST-PKG",
                source_root=root,
                source_path=source,
                generated_utc="2026-07-21T00:00:00Z",
            )
            self.assertEqual(prov.source_relative_path, "subdir/evidence.json")
            self.assertNotIn(str(root), prov.source_relative_path)
            self.assertEqual(len(prov.source_sha256), 64)

    def test_path_outside_root_rejected(self):
        with tempfile.TemporaryDirectory() as tmp_a, tempfile.TemporaryDirectory() as tmp_b:
            root = Path(tmp_a)
            outside = Path(tmp_b) / "outside.json"
            outside.write_text("{}", encoding="utf-8")
            with self.assertRaises(EvidenceValidationError):
                build_provenance(
                    evidence_id="test.evidence",
                    source_package="TEST-PKG",
                    source_root=root,
                    source_path=outside,
                    generated_utc="2026-07-21T00:00:00Z",
                )

    def test_empty_generated_utc_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "evidence.json"
            source.write_text("{}", encoding="utf-8")
            with self.assertRaises(EvidenceValidationError):
                build_provenance(
                    evidence_id="test.evidence",
                    source_package="TEST-PKG",
                    source_root=root,
                    source_path=source,
                    generated_utc="",
                )

    def test_invalid_archive_hash_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "evidence.json"
            source.write_text("{}", encoding="utf-8")
            with self.assertRaises(EvidenceValidationError):
                build_provenance(
                    evidence_id="test.evidence",
                    source_package="TEST-PKG",
                    source_root=root,
                    source_path=source,
                    generated_utc="2026-07-21T00:00:00Z",
                    source_archive_sha256="not-a-valid-hash",
                )


if __name__ == "__main__":
    unittest.main()
