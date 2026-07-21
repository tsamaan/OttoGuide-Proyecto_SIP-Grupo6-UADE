"""Source manifest / descriptor verification for ODOM/TF R2-P0A
(section 11.5, closes finding F5).

Before any evidence is ingested, the harvest must be verified against an
EXPECTED manifest recorded ahead of time in the portable descriptor. A
modified source file, a modified manifest, or a harvest_id mismatch must
each produce a typed EvidenceValidationError -- never a silently-accepted
new hash. This is the ONLY place besides `provenance.py` that reads harvest
bytes for hashing; both are read-only.
"""
import hashlib
import json
from pathlib import Path

from .validation import (
    EvidenceValidationError,
    is_non_empty_str,
    is_relative_portable_path,
    is_sha256_hex,
)

DESCRIPTOR_SCHEMA_VERSION = "1.0.0-p0a"

_REQUIRED_DESCRIPTOR_FIELDS = (
    "descriptor_schema_version",
    "harvest_id",
    "manifest_relative_path",
    "manifest_sha256",
    "expected_source_files",
    "expected_source_sha256",
)


def sha256_of_file(path: Path) -> str:
    """Read-only hash of a file's bytes."""
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_descriptor(descriptor_path: Path) -> dict:
    """Load and structurally validate a portable descriptor. Fails closed on
    any missing field, wrong schema version, or malformed path/hash entry."""
    if not descriptor_path.is_file():
        raise EvidenceValidationError(f"descriptor not found: {descriptor_path}")
    with open(descriptor_path, "r", encoding="utf-8-sig") as handle:
        try:
            descriptor = json.load(handle)
        except json.JSONDecodeError as exc:
            raise EvidenceValidationError(f"descriptor is not valid JSON: {exc}") from exc

    if type(descriptor) is not dict:
        raise EvidenceValidationError("descriptor must be a JSON object")
    for name in _REQUIRED_DESCRIPTOR_FIELDS:
        if name not in descriptor:
            raise EvidenceValidationError(f"descriptor missing required key: {name}")

    if descriptor["descriptor_schema_version"] != DESCRIPTOR_SCHEMA_VERSION:
        raise EvidenceValidationError(
            f"unsupported descriptor_schema_version: "
            f"{descriptor['descriptor_schema_version']!r} (expected {DESCRIPTOR_SCHEMA_VERSION!r})"
        )
    if not is_non_empty_str(descriptor["harvest_id"]):
        raise EvidenceValidationError("descriptor.harvest_id must be a non-empty str")
    if not is_relative_portable_path(descriptor["manifest_relative_path"]):
        raise EvidenceValidationError(
            f"descriptor.manifest_relative_path is not a portable relative path: "
            f"{descriptor['manifest_relative_path']!r}"
        )
    if not is_sha256_hex(descriptor["manifest_sha256"]):
        raise EvidenceValidationError("descriptor.manifest_sha256 is not a valid sha256 hex digest")

    expected_files = descriptor["expected_source_files"]
    expected_hashes = descriptor["expected_source_sha256"]
    if type(expected_files) is not list or type(expected_hashes) is not list:
        raise EvidenceValidationError("expected_source_files/expected_source_sha256 must be lists")
    if len(expected_files) != len(expected_hashes):
        raise EvidenceValidationError(
            f"expected_source_files/expected_source_sha256 length mismatch: "
            f"{len(expected_files)} vs {len(expected_hashes)}"
        )
    for relative_path in expected_files:
        if not is_relative_portable_path(relative_path):
            raise EvidenceValidationError(f"non-portable expected_source_files entry: {relative_path!r}")
    for digest in expected_hashes:
        if not is_sha256_hex(digest):
            raise EvidenceValidationError(f"invalid expected_source_sha256 entry: {digest!r}")

    return descriptor


def resolve_harvest_root(descriptor: dict, descriptor_path: Path, harvest_root_override: "Path | None") -> Path:
    """The local harvest root may differ between machines -- an explicit
    --harvest-root always wins; otherwise an optional harvest_root_hint in
    the descriptor is used (relative hints are resolved against the
    descriptor's own directory, never assumed absolute on another machine)."""
    if harvest_root_override is not None:
        harvest_root = harvest_root_override
    else:
        hint = descriptor.get("harvest_root_hint")
        if not hint:
            raise EvidenceValidationError(
                "no harvest root available: pass --harvest-root or set "
                "descriptor.harvest_root_hint"
            )
        harvest_root = Path(hint)
        if not harvest_root.is_absolute():
            harvest_root = (descriptor_path.parent / harvest_root).resolve()
    if not harvest_root.is_dir():
        raise EvidenceValidationError(f"harvest_root does not exist: {harvest_root}")
    return harvest_root


def verify_harvest_against_descriptor(descriptor: dict, harvest_root: Path) -> dict:
    """Fail-closed: manifest hash, harvest_id, and every expected source
    file's hash must match exactly. Raises EvidenceValidationError
    aggregating every mismatch found -- a modified source file must never
    be silently accepted with a freshly-computed hash (closes finding F5).
    Returns a small verification summary dict on success."""
    manifest_path = harvest_root / descriptor["manifest_relative_path"]
    if not manifest_path.is_file():
        raise EvidenceValidationError(f"manifest file not found: {manifest_path}")

    actual_manifest_hash = sha256_of_file(manifest_path)
    if actual_manifest_hash != descriptor["manifest_sha256"]:
        raise EvidenceValidationError(
            f"manifest hash mismatch for {manifest_path}: "
            f"expected {descriptor['manifest_sha256']}, got {actual_manifest_hash}"
        )

    with open(manifest_path, "r", encoding="utf-8-sig") as handle:
        try:
            manifest = json.load(handle)
        except json.JSONDecodeError as exc:
            raise EvidenceValidationError(f"manifest is not valid JSON: {exc}") from exc

    manifest_harvest_id = manifest.get("HARVEST_ID")
    if manifest_harvest_id != descriptor["harvest_id"]:
        raise EvidenceValidationError(
            f"harvest_id mismatch: descriptor says {descriptor['harvest_id']!r}, "
            f"manifest says {manifest_harvest_id!r}"
        )

    mismatches = []
    for relative_path, expected_hash in zip(
        descriptor["expected_source_files"], descriptor["expected_source_sha256"]
    ):
        source_path = harvest_root / relative_path
        if not source_path.is_file():
            mismatches.append(f"{relative_path}: file missing")
            continue
        actual_hash = sha256_of_file(source_path)
        if actual_hash != expected_hash:
            mismatches.append(f"{relative_path}: expected {expected_hash}, got {actual_hash}")

    if mismatches:
        raise EvidenceValidationError(
            f"{len(mismatches)} source file(s) failed manifest verification "
            f"(a modified source produces FAIL, never a silently-accepted new hash):\n"
            + "\n".join(mismatches)
        )

    return {
        "manifest_verification": "PASS",
        "harvest_id": descriptor["harvest_id"],
        "verified_file_count": len(descriptor["expected_source_files"]),
    }
