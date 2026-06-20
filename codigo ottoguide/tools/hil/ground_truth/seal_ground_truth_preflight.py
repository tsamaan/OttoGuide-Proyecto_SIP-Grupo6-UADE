#!/usr/bin/env python3
"""Execute transactional sealing with rollback for hardware inventory and human review."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path

import validate_ground_truth_session as contract


class ContractError(ValueError):
    pass


class EvidenceError(ValueError):
    pass


class LockError(FileExistsError):
    pass


class OperationalError(OSError):
    pass


class CleanupError(OperationalError):
    pass


class TransactionError(Exception):
    def __init__(self,
                 original_error: Exception,
                 error_category: str,
                 transaction_id: str,
                 rollback_performed: bool,
                 rollback_verified: bool,
                 rollback_failures: list[str],
                 temp_remaining: int,
                 bak_remaining: int,
                 lock_released: bool):
        super().__init__(str(original_error))
        self.original_error = original_error
        self.error_category = error_category
        self.transaction_id = transaction_id
        self.rollback_performed = rollback_performed
        self.rollback_verified = rollback_verified
        self.rollback_failures = rollback_failures
        self.temp_remaining = temp_remaining
        self.bak_remaining = bak_remaining
        self.lock_released = lock_released


def is_allowed_evidence_error(err: str) -> bool:
    if err.startswith("hardware_inventory:") or err.startswith("human_review:"):
        return True
    evidence_fields = [
        "hardware_inventory", "hardware_inventory_sha256", "hardware_inventory_id", "hardware_inventory_revision",
        "human_review", "human_review_sha256", "human_review_id", "human_review_revision"
    ]
    for field in evidence_fields:
        if f"manifest: {field}" in err:
            return True
        if f"manifest: missing required field {field}" in err:
            return True
        if f"manifest: missing required sealed field {field}" in err:
            return True
        if f"manifest: missing field {field}" in err:
            return True
    if "manifest: sealed evidence must be complete" in err:
        return True
    if "manifest: calibration_files must include hardware_inventory" in err:
        return True
    if "manifest: calibration_files must include human_review" in err:
        return True
    return False


def validate_reseal_base(session: Path) -> dict:
    res = contract.validate(session)
    if res["ok"]:
        return res
    for err in res["errors"]:
        if not is_allowed_evidence_error(err):
            raise ValueError(f"session has non-evidence structural errors: {err}")
    return res


def restore_file(target: Path, existed: bool, old_bytes: bytes | None, transaction_id: str, failures: list[str]) -> None:
    if existed:
        if old_bytes is None:
            failures.append(f"Cannot restore {target.name}: original bytes are missing")
            return
        tmp_path = target.parent / f".{target.name}.{transaction_id}.rollback.tmp"
        try:
            fd = os.open(str(tmp_path), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            try:
                with os.fdopen(fd, "wb") as handle:
                    handle.write(old_bytes)
                    handle.flush()
                    os.fsync(handle.fileno())
            except Exception as e:
                failures.append(f"Failed to write rollback file for {target.name}: {e}")
                return

            os.replace(tmp_path, target)

            try:
                dir_fd = os.open(str(target.parent), os.O_RDONLY)
                try:
                    os.fsync(dir_fd)
                finally:
                    os.close(dir_fd)
            except Exception:
                pass

            if not target.exists() or target.read_bytes() != old_bytes:
                failures.append(f"Rollback verification failed for {target.name}: bytes mismatch")
        except Exception as e:
            failures.append(f"Rollback failed to restore {target.name}: {e}")
    else:
        if target.exists():
            try:
                os.unlink(target)
            except Exception as e:
                failures.append(f"Failed to delete newly created target {target.name}: {e}")
        if target.exists():
            failures.append(f"Target {target.name} still exists after rollback deletion attempt")


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
    transaction_id = hashlib.sha256(os.urandom(16)).hexdigest()[:16]
    lock_acquired = False
    rollback_performed = False
    rollback_verified = False
    rollback_failures = []
    targets_modified = False

    inventory_target = session / "calibration" / "hardware_inventory.json"
    review_target = session / "calibration" / "human_review.json"
    manifest_target = session / "session_manifest.json"
    lock_path = session / "calibration" / ".gtseal.lock"

    tmp_inventory = inventory_target.parent / f".hardware_inventory.json.{transaction_id}.stage.tmp"
    tmp_review = review_target.parent / f".human_review.json.{transaction_id}.stage.tmp"
    tmp_manifest = manifest_target.parent / f".session_manifest.json.{transaction_id}.stage.tmp"

    bak_inventory = inventory_target.parent / f".hardware_inventory.json.{transaction_id}.backup.bak"
    bak_review = review_target.parent / f".human_review.json.{transaction_id}.backup.bak"
    bak_manifest = manifest_target.parent / f".session_manifest.json.{transaction_id}.backup.bak"

    existed_inventory = inventory_target.exists()
    existed_review = review_target.exists()
    existed_manifest = manifest_target.exists()

    old_inventory_bytes = None
    old_review_bytes = None
    old_manifest_bytes = None
    before_report = None

    try:
        # 1. Preparación
        before_report = contract.validate(session)
        if force:
            validate_reseal_base(session)
        else:
            if not before_report["ok"]:
                raise ValueError("session is structurally invalid before sealing: " + "; ".join(before_report["errors"]))

        # Lock acquisition via O_EXCL
        try:
            lock_fd = os.open(str(lock_path), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            os.close(lock_fd)
            lock_acquired = True
        except FileExistsError:
            raise FileExistsError(f"Sealing transaction is already in progress: lock file {lock_path} exists")

        manifest = json.loads(manifest_target.read_text(encoding="utf-8"))
        status_before = manifest.get("physical_readiness_status", "NOT_REVIEWED")

        # Pre-existence check unless force
        if not force:
            if existed_inventory or existed_review or manifest.get("hardware_inventory") or manifest.get("human_review"):
                raise FileExistsError("sealed preflight evidence already exists; use --force to replace it")

        inventory, inventory_raw = read_object(inventory_source, "hardware_inventory")
        review, review_raw = read_object(review_source, "human_review")

        inventory_hash = hashlib.sha256(inventory_raw).hexdigest()
        review_hash = hashlib.sha256(review_raw).hexdigest()

        # Build manifest update
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

        # Save old bytes
        if existed_inventory:
            old_inventory_bytes = inventory_target.read_bytes()
        if existed_review:
            old_review_bytes = review_target.read_bytes()
        if existed_manifest:
            old_manifest_bytes = manifest_target.read_bytes()

        # Create backups if targets exist (15.3)
        if existed_inventory:
            create_backup(inventory_target, bak_inventory)
        if existed_review:
            create_backup(review_target, bak_review)
        if existed_manifest:
            create_backup(manifest_target, bak_manifest)

        # Write staging files (15.2)
        stage_write(tmp_inventory, inventory_raw)
        stage_write(tmp_review, review_raw)
        stage_write(tmp_manifest, manifest_raw)

        targets_modified = True
        # Replace targets (15.4)
        # 1. hardware inventory
        os.replace(tmp_inventory, inventory_target)
        # 2. human review
        os.replace(tmp_review, review_target)
        # 3. manifest (logical commit point)
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

        status_after = after_manifest.get("physical_readiness_status", "NOT_REVIEWED")

        # Clean up temporary and backup files
        temp_remaining = 0
        bak_remaining = 0
        for p in (tmp_inventory, tmp_review, tmp_manifest):
            if p.exists():
                try:
                    os.unlink(p)
                except Exception:
                    temp_remaining += 1
        for p in (bak_inventory, bak_review, bak_manifest):
            if p.exists():
                try:
                    os.unlink(p)
                except Exception:
                    bak_remaining += 1

        # Release lock
        lock_released = False
        if lock_acquired:
            if lock_path.exists():
                try:
                    os.unlink(lock_path)
                    lock_released = True
                except Exception:
                    pass
            else:
                lock_released = True
        else:
            lock_released = True

        if temp_remaining != 0 or bak_remaining != 0 or not lock_released:
            reasons = []
            if temp_remaining != 0:
                reasons.append(f"{temp_remaining} temporary files remaining")
            if bak_remaining != 0:
                reasons.append(f"{bak_remaining} backup files remaining")
            if not lock_released:
                reasons.append("lock file could not be released")
            raise CleanupError("Cleanup failed: " + ", ".join(reasons))

        return {
            "ok": True,
            "transaction_id": transaction_id,
            "transaction_completed": True,
            "physical_readiness_status_before": status_before,
            "physical_readiness_status_after": status_after,
            "physical_status_unchanged": status_before == status_after,
            "post_seal_decision": after.get("decision"),
            "post_seal_physical_ready": after.get("physical_ready"),
            "hardware_inventory_sha256": inventory_hash,
            "human_review_sha256": review_hash,
            "rollback_performed": False,
            "rollback_verified": False,
            "rollback_failures": [],
            "temporary_files_remaining": temp_remaining,
            "backup_files_remaining": bak_remaining,
            "lock_released": lock_released
        }

    except Exception as original_error:
        rollback_performed = True

        # Perform verified rollback
        # 1. Restore targets if they were modified
        if targets_modified:
            restore_file(inventory_target, existed_inventory, old_inventory_bytes, transaction_id, rollback_failures)
            restore_file(review_target, existed_review, old_review_bytes, transaction_id, rollback_failures)
            restore_file(manifest_target, existed_manifest, old_manifest_bytes, transaction_id, rollback_failures)

        # 2. Clean up temporary and backup files
        temp_remaining = 0
        bak_remaining = 0
        for p in (tmp_inventory, tmp_review, tmp_manifest):
            if p.exists():
                try:
                    os.unlink(p)
                except Exception as e:
                    rollback_failures.append(f"Failed to delete temp file {p.name}: {e}")
                    temp_remaining += 1
        for p in (bak_inventory, bak_review, bak_manifest):
            if p.exists():
                try:
                    os.unlink(p)
                except Exception as e:
                    rollback_failures.append(f"Failed to delete backup file {p.name}: {e}")
                    bak_remaining += 1

        # 3. Release lock
        lock_released = False
        if lock_acquired:
            if lock_path.exists():
                try:
                    os.unlink(lock_path)
                    lock_released = True
                except Exception as e:
                    rollback_failures.append(f"Failed to delete lock file: {e}")
            else:
                lock_released = True
        else:
            lock_released = True

        # 4. Final validation of restored state if manifest exists and is readable
        if existed_manifest and manifest_target.is_file():
            try:
                restored_report = contract.validate(session)
                if before_report is not None:
                    # Compare ok, decision, physical_ready, errors, blocking_reasons
                    # Normalizar listas mediante ordenamiento
                    ok_match = restored_report.get("ok") == before_report.get("ok")
                    decision_match = restored_report.get("decision") == before_report.get("decision")
                    ready_match = restored_report.get("physical_ready") == before_report.get("physical_ready")

                    errors_before = sorted(before_report.get("errors", []))
                    errors_restored = sorted(restored_report.get("errors", []))
                    errors_match = errors_before == errors_restored

                    blockers_before = sorted(before_report.get("blocking_reasons", []))
                    blockers_restored = sorted(restored_report.get("blocking_reasons", []))
                    blockers_match = blockers_before == blockers_restored

                    if not (ok_match and decision_match and ready_match and errors_match and blockers_match):
                        rollback_failures.append(
                            f"Restored session state is not logically equivalent to state before transaction. "
                            f"Before: ok={before_report.get('ok')}, decision={before_report.get('decision')}, ready={before_report.get('physical_ready')}, errors={errors_before}, blockers={blockers_before}. "
                            f"Restored: ok={restored_report.get('ok')}, decision={restored_report.get('decision')}, ready={restored_report.get('physical_ready')}, errors={errors_restored}, blockers={blockers_restored}."
                        )
            except Exception as e:
                rollback_failures.append(f"Failed to validate restored session: {e}")

        rollback_verified = (len(rollback_failures) == 0)

        # Classification rules:
        if not rollback_verified:
            category = "ROLLBACK"
        elif targets_modified:
            category = "OPERATIONAL"
        elif isinstance(original_error, (FileExistsError, ValueError, json.JSONDecodeError, UnicodeError)):
            category = "CONTRACT"
        else:
            category = "OPERATIONAL"

        try:
            class_name = f"Transaction{type(original_error).__name__}"
            dynamic_class = type(class_name, (TransactionError, type(original_error)), {})
            raise dynamic_class(
                original_error=original_error,
                error_category=category,
                transaction_id=transaction_id,
                rollback_performed=rollback_performed,
                rollback_verified=rollback_verified,
                rollback_failures=rollback_failures,
                temp_remaining=temp_remaining,
                bak_remaining=bak_remaining,
                lock_released=lock_released
            )
        except TypeError:
            raise TransactionError(
                original_error=original_error,
                error_category=category,
                transaction_id=transaction_id,
                rollback_performed=rollback_performed,
                rollback_verified=rollback_verified,
                rollback_failures=rollback_failures,
                temp_remaining=temp_remaining,
                bak_remaining=bak_remaining,
                lock_released=lock_released
            )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("session_dir", type=Path)
    parser.add_argument("hardware_inventory", type=Path)
    parser.add_argument("human_review", type=Path)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    try:
        result = seal(args.session_dir, args.hardware_inventory, args.human_review, args.force)
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0
    except TransactionError as exc:
        if exc.error_category == "CONTRACT":
            exit_code = 3
        else:
            exit_code = 1

        err_res = {
            "ok": False,
            "error_category": exc.error_category,
            "transaction_id": exc.transaction_id,
            "transaction_completed": False,
            "rollback_performed": exc.rollback_performed,
            "rollback_verified": exc.rollback_verified,
            "rollback_failures": exc.rollback_failures,
            "original_error": str(exc.original_error),
            "temporary_files_remaining": exc.temp_remaining,
            "backup_files_remaining": exc.bak_remaining,
            "lock_released": exc.lock_released
        }
        print(json.dumps(err_res, indent=2, sort_keys=True))
        return exit_code
    except Exception as exc:
        print(json.dumps({
            "ok": False,
            "error_category": "OPERATIONAL",
            "error": str(exc)
        }, sort_keys=True))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
