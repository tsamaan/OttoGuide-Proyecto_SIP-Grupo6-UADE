#!/usr/bin/env python3
"""Execute transactional sealing with rollback for hardware inventory and human review."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path

import validate_ground_truth_session as contract


def stage_write(path: Path, payload: bytes) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    # Open with safe permissions (0o600) and same filesystem
    fd = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
    except BaseException:
        try:
            os.unlink(path)
        except FileNotFoundError:
            pass
        raise
    return path


def create_backup(target: Path, backup_path: Path) -> bytes | None:
    if target.exists():
        data = target.read_bytes()
        fd = os.open(str(backup_path), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        return data
    return None


def write_direct(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "wb") as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())


def remove_target(path: Path) -> None:
    if path.exists():
        try:
            os.unlink(path)
        except OSError:
            pass


def read_object(path: Path, label: str) -> tuple[dict, bytes]:
    raw = path.read_bytes()
    data = json.loads(raw.decode("utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"{label} must contain a JSON object")
    errors: list[str] = []
    if label == "hardware_inventory":
        contract.validate_inventory(data, errors)
    else:
        contract.validate_review(data, errors)
    if errors:
        raise ValueError(f"{label} structural errors: " + "; ".join(errors))
    return data, raw


def seal(session: Path, inventory_source: Path, review_source: Path, force: bool = False) -> dict:
    # 1. Preparación (15.1)
    before = contract.validate(session)
    if not before["ok"]:
        raise ValueError("session is structurally invalid before sealing: " + "; ".join(before["errors"]))

    inventory, inventory_raw = read_object(inventory_source, "hardware_inventory")
    review, review_raw = read_object(review_source, "human_review")

    inventory_target = session / "calibration" / "hardware_inventory.json"
    review_target = session / "calibration" / "human_review.json"
    manifest_target = session / "session_manifest.json"

    # Pre-existence check unless force
    if not force:
        manifest = json.loads(manifest_target.read_text(encoding="utf-8"))
        if inventory_target.exists() or review_target.exists() or manifest.get("hardware_inventory") or manifest.get("human_review"):
            raise FileExistsError("sealed preflight evidence already exists; use --force to replace it")

    inventory_hash = hashlib.sha256(inventory_raw).hexdigest()
    review_hash = hashlib.sha256(review_raw).hexdigest()

    manifest = json.loads(manifest_target.read_text(encoding="utf-8"))
    updated = dict(manifest)
    updated.update({
        "hardware_inventory": "calibration/hardware_inventory.json",
        "hardware_inventory_sha256": inventory_hash,
        "hardware_inventory_id": inventory["inventory_id"],
        "hardware_inventory_revision": inventory["inventory_revision"],
        "human_review": "calibration/human_review.json",
        "human_review_sha256": review_hash,
        "human_review_id": review["review_id"],
        "human_review_revision": review["review_revision"],
    })
    calibrations = [item for item in updated.get("calibration_files", []) if item not in {"calibration/hardware_inventory.json", "calibration/human_review.json"}]
    updated["calibration_files"] = calibrations + ["calibration/hardware_inventory.json", "calibration/human_review.json"]
    manifest_raw = (json.dumps(updated, indent=2, sort_keys=True) + "\n").encode("utf-8")

    # 2. Paths
    tmp_inventory = inventory_target.parent / ".hardware_inventory.json.stage.tmp"
    tmp_review = review_target.parent / ".human_review.json.stage.tmp"
    tmp_manifest = manifest_target.parent / ".session_manifest.json.stage.tmp"

    bak_inventory = inventory_target.parent / ".hardware_inventory.json.backup.bak"
    bak_review = review_target.parent / ".human_review.json.backup.bak"
    bak_manifest = manifest_target.parent / ".session_manifest.json.backup.bak"

    existed_inventory = inventory_target.exists()
    existed_review = review_target.exists()
    existed_manifest = manifest_target.exists()

    old_inventory_bytes = None
    old_review_bytes = None
    old_manifest_bytes = None

    try:
        # Write staging files (15.2)
        stage_write(tmp_inventory, inventory_raw)
        stage_write(tmp_review, review_raw)
        stage_write(tmp_manifest, manifest_raw)

        # Create backups if targets exist (15.3)
        if existed_inventory:
            old_inventory_bytes = create_backup(inventory_target, bak_inventory)
        if existed_review:
            old_review_bytes = create_backup(review_target, bak_review)
        if existed_manifest:
            old_manifest_bytes = create_backup(manifest_target, bak_manifest)

        # Replace targets (15.4)
        # 1. hardware inventory
        os.replace(tmp_inventory, inventory_target)
        # 2. human review
        os.replace(tmp_review, review_target)
        # 3. manifest
        os.replace(tmp_manifest, manifest_target)

        # 15.5 Validación posterior
        after = contract.validate(session)
        if not after["ok"]:
            raise ValueError("post-write session validation failed: " + "; ".join(after["errors"]))

        # comprobar hashes
        current_inv_hash = hashlib.sha256(inventory_target.read_bytes()).hexdigest()
        current_rev_hash = hashlib.sha256(review_target.read_bytes()).hexdigest()
        if current_inv_hash != inventory_hash or current_rev_hash != review_hash:
            raise ValueError("post-write validation failed: hash mismatch of written targets")

        # comprobar IDs y revisiones
        after_manifest = json.loads(manifest_target.read_text(encoding="utf-8"))
        if (after_manifest.get("hardware_inventory_id") != inventory["inventory_id"] or
            after_manifest.get("hardware_inventory_revision") != inventory["inventory_revision"] or
            after_manifest.get("human_review_id") != review["review_id"] or
            after_manifest.get("human_review_revision") != review["review_revision"]):
            raise ValueError("post-write validation failed: IDs or revisions mismatch in manifest")

        # Clean up temporary and backup files
        temp_remaining = 0
        for p in (tmp_inventory, tmp_review, tmp_manifest, bak_inventory, bak_review, bak_manifest):
            if p.exists():
                try:
                    os.unlink(p)
                except OSError:
                    temp_remaining += 1

        return {
            "ok": True,
            "transaction_completed": True,
            "physical_status_unchanged": before.get("decision") == after.get("decision"),
            "post_seal_decision": after.get("decision"),
            "post_seal_physical_ready": after.get("physical_ready"),
            "hardware_inventory_sha256": inventory_hash,
            "human_review_sha256": review_hash,
            "rollback_performed": False,
            "temporary_files_remaining": temp_remaining
        }

    except BaseException as exc:
        # 15.6 Rollback
        # Restore targets
        if existed_inventory and old_inventory_bytes is not None:
            write_direct(inventory_target, old_inventory_bytes)
        elif not existed_inventory:
            remove_target(inventory_target)

        if existed_review and old_review_bytes is not None:
            write_direct(review_target, old_review_bytes)
        elif not existed_review:
            remove_target(review_target)

        if existed_manifest and old_manifest_bytes is not None:
            write_direct(manifest_target, old_manifest_bytes)
        elif not existed_manifest:
            remove_target(manifest_target)

        # Clean up staging and backups
        for p in (tmp_inventory, tmp_review, tmp_manifest, bak_inventory, bak_review, bak_manifest):
            if p.exists():
                try:
                    os.unlink(p)
                except OSError:
                    pass
        raise exc


def main() -> int:
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument("session_dir",type=Path);parser.add_argument("hardware_inventory",type=Path);parser.add_argument("human_review",type=Path);parser.add_argument("--force",action="store_true");args=parser.parse_args()
    try: result=seal(args.session_dir,args.hardware_inventory,args.human_review,args.force)
    except (OSError,UnicodeError,json.JSONDecodeError,ValueError,FileExistsError) as exc: print(json.dumps({"ok":False,"error":str(exc)},sort_keys=True));return 3
    print(json.dumps(result,indent=2,sort_keys=True));return 0


if __name__=="__main__": raise SystemExit(main())
