#!/usr/bin/env python3
"""Atomically seal hardware inventory and human review into a prepared session."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import tempfile
from pathlib import Path

import validate_ground_truth_session as contract


def atomic_write(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(payload); handle.flush(); os.fsync(handle.fileno())
        os.replace(temporary, path)
    except BaseException:
        try: os.unlink(temporary)
        except FileNotFoundError: pass
        raise


def read_object(path: Path, label: str) -> tuple[dict, bytes]:
    raw = path.read_bytes(); data = json.loads(raw.decode("utf-8"))
    if not isinstance(data, dict): raise ValueError(f"{label} must contain a JSON object")
    errors: list[str] = []
    if label == "hardware_inventory": contract.validate_inventory(data, errors)
    else: contract.validate_review(data, errors)
    if errors: raise ValueError("; ".join(errors))
    return data, raw


def seal(session: Path, inventory_source: Path, review_source: Path, force: bool = False) -> dict:
    before = contract.validate(session)
    if not before["ok"]: raise ValueError("session is structurally invalid before sealing: " + "; ".join(before["errors"]))
    inventory, inventory_raw = read_object(inventory_source, "hardware_inventory")
    review, review_raw = read_object(review_source, "human_review")
    inventory_target = session / "calibration" / "hardware_inventory.json"
    review_target = session / "calibration" / "human_review.json"
    manifest_path = session / "session_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not force and (inventory_target.exists() or review_target.exists() or manifest.get("hardware_inventory") or manifest.get("human_review")):
        raise FileExistsError("sealed preflight evidence already exists; use --force to replace it")
    inventory_hash = hashlib.sha256(inventory_raw).hexdigest(); review_hash = hashlib.sha256(review_raw).hexdigest()
    updated = dict(manifest)
    updated.update({
        "hardware_inventory": "calibration/hardware_inventory.json", "hardware_inventory_sha256": inventory_hash,
        "hardware_inventory_id": inventory["inventory_id"], "hardware_inventory_revision": inventory["inventory_revision"],
        "human_review": "calibration/human_review.json", "human_review_sha256": review_hash,
        "human_review_id": review["review_id"], "human_review_revision": review["review_revision"],
    })
    calibrations = [item for item in updated.get("calibration_files", []) if item not in {"calibration/hardware_inventory.json", "calibration/human_review.json"}]
    updated["calibration_files"] = calibrations + ["calibration/hardware_inventory.json", "calibration/human_review.json"]
    atomic_write(inventory_target, inventory_raw); atomic_write(review_target, review_raw)
    atomic_write(manifest_path, (json.dumps(updated, indent=2, sort_keys=True) + "\n").encode("utf-8"))
    return {"ok": True, "physical_status_unchanged": updated.get("physical_readiness_status"), "hardware_inventory_sha256": inventory_hash, "human_review_sha256": review_hash}


def main() -> int:
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument("session_dir",type=Path);parser.add_argument("hardware_inventory",type=Path);parser.add_argument("human_review",type=Path);parser.add_argument("--force",action="store_true");args=parser.parse_args()
    try: result=seal(args.session_dir,args.hardware_inventory,args.human_review,args.force)
    except (OSError,UnicodeError,json.JSONDecodeError,ValueError,FileExistsError) as exc: print(json.dumps({"ok":False,"error":str(exc)},sort_keys=True));return 3
    print(json.dumps(result,indent=2,sort_keys=True));return 0


if __name__=="__main__": raise SystemExit(main())
