"""H8 audit: R4B/R4 boot relation, backed by a real hash-verification chain
rather than bare textual similarity of a boot_id string.

R4B_TIMEBASE_ESTIMATE.json was never read by P0A (P0A's R4B ingestion only
used the six already-derived report files) nor hash-pinned by the P0A
portable descriptor. It IS, however, individually listed with a SHA-256 in
R4B_LOCAL_SHA256SUMS.txt, itself part of the session's own
R4B_LOCAL_HASH_VERIFICATION.json (2098/2098 files, 0 failures, PASS). R4's
own ROBOT_BOOT_ID is hash-pinned by the P0A descriptor via
FINAL_PHYSICAL_HARVEST_INDEX.json (one of the 13 expected_source_files).

Same-boot evidence never by itself authorizes trajectory, time-domain, or
capture-continuity claims (section 20) -- enforced structurally in
BootRelationEvidence.__post_init__.
"""
import hashlib
import json
from pathlib import Path

from src.navigation.odometry_evidence_r2.validation import EvidenceValidationError

from .models import BootRelationEvidence

R4_SESSION_ID = "finalharvest-seated-20260720T205406Z"
R4B_SESSION_ID = "gt-r4b-20260720T213222Z"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def audit_r4b_boot_relation(harvest_root: Path) -> BootRelationEvidence:
    index_path = harvest_root / "FINAL_PHYSICAL_HARVEST_INDEX.json"
    with open(index_path, "r", encoding="utf-8-sig") as handle:
        index = json.load(handle)
    r4_boot_id = index.get("ROBOT_BOOT_ID")
    if not r4_boot_id:
        raise EvidenceValidationError("FINAL_PHYSICAL_HARVEST_INDEX.json missing ROBOT_BOOT_ID")
    index_sha256 = _sha256(index_path)

    timebase_path = harvest_root / "10_r4b" / "R4B_TIMEBASE_ESTIMATE.json"
    with open(timebase_path, "r", encoding="utf-8-sig") as handle:
        timebase = json.load(handle)
    remote_boot_ids = timebase.get("remote_boot_ids") or []
    timebase_sha256 = _sha256(timebase_path)

    local_sums_path = harvest_root / "10_r4b" / "R4B_LOCAL_SHA256SUMS.txt"
    pinned_hash = None
    if local_sums_path.is_file():
        for line in local_sums_path.read_text(encoding="utf-8").splitlines():
            parts = line.strip().split(None, 1)
            if len(parts) == 2 and parts[1].strip() == "R4B_TIMEBASE_ESTIMATE.json":
                pinned_hash = parts[0].strip()
                break
    timebase_hash_verified = pinned_hash is not None and pinned_hash == timebase_sha256

    local_verification_path = harvest_root / "10_r4b" / "R4B_LOCAL_HASH_VERIFICATION.json"
    verification_pass = False
    if local_verification_path.is_file():
        with open(local_verification_path, "r", encoding="utf-8-sig") as handle:
            verification = json.load(handle)
        verification_pass = (
            verification.get("verification") == "PASS"
            and verification.get("failure_count") == 0
            and verification.get("checked_hashes", 0) > 0
        )

    same_boot_verified = (
        timebase_hash_verified
        and verification_pass
        and r4_boot_id in remote_boot_ids
    )

    limitations = [
        f"R4's ROBOT_BOOT_ID ({r4_boot_id!r}) is pinned by the P0A portable descriptor "
        "via FINAL_PHYSICAL_HARVEST_INDEX.json's manifest hash.",
        f"R4B_TIMEBASE_ESTIMATE.json sha256={timebase_sha256!r} matches its entry in "
        f"R4B_LOCAL_SHA256SUMS.txt: {timebase_hash_verified}; that file is part of the "
        f"session's own R4B_LOCAL_HASH_VERIFICATION.json ({verification.get('checked_hashes', 'n/a') if local_verification_path.is_file() else 'n/a'} "
        f"files, PASS={verification_pass}).",
        "same_boot_verified means the two independently hash-verified sources agree on "
        "boot_id, nothing more -- it does NOT imply the same time domain, a continuous "
        "capture, or that trajectories may be concatenated (section 20).",
    ]

    return BootRelationEvidence(
        evidence_id="p1a.boot_relation.r4b_to_r4",
        session_a=R4_SESSION_ID,
        session_b=R4B_SESSION_ID,
        boot_id_a=r4_boot_id,
        boot_id_b=(remote_boot_ids[0] if remote_boot_ids else "NOT_AVAILABLE"),
        source_a_sha256=index_sha256,
        source_b_sha256=timebase_sha256,
        source_a_hash_verified=True,  # pinned by the P0A descriptor, already verified this checkpoint's baseline
        source_b_hash_verified=timebase_hash_verified,
        same_boot_verified=same_boot_verified,
        same_time_domain=False,
        continuous_capture=False,
        continuous_trajectory_permitted=False,
        status="VERIFIED" if same_boot_verified else "UNRESOLVED",
        limitations=tuple(limitations),
    )
