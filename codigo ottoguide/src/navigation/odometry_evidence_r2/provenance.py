"""Provenance construction helpers for ODOM/TF R2-P0.

File hashing here is the ONLY I/O in this package, and it is read-only
(open + read bytes + sha256), never a network call and never a write. No
wall-clock is read anywhere in this module -- `generated_utc` is always an
explicit argument supplied by the caller (the CLI), never sampled internally,
so that two runs over the same inputs with the same injected timestamp
produce byte-identical output.
"""
import hashlib
from pathlib import Path

from .models import EvidenceProvenance
from .validation import (
    EvidenceValidationError,
    is_relative_portable_path,
    is_sha256_hex,
    is_non_empty_str,
)


def sha256_of_file(path: Path) -> str:
    """Read-only hash of a file's bytes. Raises EvidenceValidationError
    (fail-closed) if the path does not exist or is not a regular file."""
    if not path.is_file():
        raise EvidenceValidationError(f"source file does not exist: {path}")
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build_provenance(
    *,
    evidence_id: str,
    source_package: str,
    source_root: Path,
    source_path: Path,
    generated_utc: str,
    source_archive_relative_path: "str | None" = None,
    source_archive_sha256: "str | None" = None,
    transformation_script: "str | None" = None,
    transformation_script_sha256: "str | None" = None,
    arguments: "tuple[str, ...]" = (),
    limitations: "tuple[str, ...]" = (),
) -> EvidenceProvenance:
    """Build a single EvidenceProvenance record by hashing `source_path`
    (read-only) and recording its path relative to `source_root`. Fails
    closed on any absolute-path leak or non-sha256 hash."""
    if not is_non_empty_str(evidence_id):
        raise EvidenceValidationError("evidence_id must be a non-empty str")
    if not is_non_empty_str(source_package):
        raise EvidenceValidationError("source_package must be a non-empty str")
    if not is_non_empty_str(generated_utc):
        raise EvidenceValidationError("generated_utc must be a non-empty str")

    try:
        relative_path = source_path.resolve().relative_to(source_root.resolve())
    except ValueError as exc:
        raise EvidenceValidationError(
            f"source_path {source_path} is not under source_root {source_root}"
        ) from exc

    relative_str = relative_path.as_posix()
    if not is_relative_portable_path(relative_str):
        raise EvidenceValidationError(
            f"computed relative path is not portable: {relative_str!r}"
        )

    source_sha256 = sha256_of_file(source_path)

    if source_archive_sha256 is not None and not is_sha256_hex(source_archive_sha256):
        raise EvidenceValidationError(
            f"source_archive_sha256 is not a sha256 hex digest: {source_archive_sha256!r}"
        )
    if transformation_script_sha256 is not None and not is_sha256_hex(
        transformation_script_sha256
    ):
        raise EvidenceValidationError(
            f"transformation_script_sha256 is not a sha256 hex digest: "
            f"{transformation_script_sha256!r}"
        )

    return EvidenceProvenance(
        evidence_id=evidence_id,
        source_package=source_package,
        source_relative_path=relative_str,
        source_sha256=source_sha256,
        source_archive_relative_path=source_archive_relative_path,
        source_archive_sha256=source_archive_sha256,
        transformation_script=transformation_script,
        transformation_script_sha256=transformation_script_sha256,
        arguments=tuple(arguments),
        generated_utc=generated_utc,
        limitations=tuple(limitations),
    )
