#!/usr/bin/env python3
"""WEB-HIL-R1B — genera el manifiesto SHA-256 + inventario de un build de frontend
precompilado (dist-real/ o dist-replay/), y verifica (--check) un manifiesto existente
contra los bytes reales en disco. Stdlib-only, portable (Windows/Linux/CI)."""
import argparse
import hashlib
import json
import sys
from pathlib import Path


def iter_files(dist_dir: Path):
    for p in sorted(dist_dir.rglob("*")):
        if p.is_file():
            yield p


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def generate(dist_dir: Path, profile: str, build_mode: str, test_result: str):
    files = []
    total_bytes = 0
    for p in iter_files(dist_dir):
        rel = p.relative_to(dist_dir).as_posix()
        size = p.stat().st_size
        digest = sha256_of(p)
        files.append({"path": rel, "size_bytes": size, "sha256": digest})
        total_bytes += size
    inventory = {
        "schema_version": "1.0",
        "phase": "WEB_HIL_R1B_DUAL_PROFILE_BUILD",
        "profile": profile,
        "build_mode": build_mode,
        "out_dir": f"frontend/{dist_dir.name}",
        "test_result": test_result,
        "file_count": len(files),
        "total_bytes": total_bytes,
        "files": files,
    }
    return inventory


def write_outputs(dist_dir: Path, inventory: dict, sums_path: Path, inv_path: Path):
    with open(sums_path, "w", newline="\n") as f:
        for entry in inventory["files"]:
            f.write(f"{entry['sha256']} *{entry['path']}\n")
    with open(inv_path, "w", newline="\n") as f:
        json.dump(inventory, f, indent=2)
        f.write("\n")


def check(dist_dir: Path, sums_path: Path):
    if not sums_path.exists():
        print(f"CHECK_FAIL: {sums_path} no existe")
        return False
    ok = True
    expected = {}
    with open(sums_path, "r") as f:
        for line in f:
            line = line.rstrip("\n")
            if not line.strip():
                continue
            digest, path = line.split(" *", 1)
            expected[path] = digest
    actual_paths = {p.relative_to(dist_dir).as_posix() for p in iter_files(dist_dir)}
    if set(expected.keys()) != actual_paths:
        print(f"CHECK_FAIL: paths no coinciden. esperados={sorted(expected)} actuales={sorted(actual_paths)}")
        ok = False
    for path, digest in expected.items():
        full = dist_dir / path
        if not full.exists():
            print(f"CHECK_FAIL: falta {path}")
            ok = False
            continue
        actual_digest = sha256_of(full)
        if actual_digest != digest:
            print(f"CHECK_FAIL: hash no coincide para {path}: esperado={digest} actual={actual_digest}")
            ok = False
    return ok


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dist-dir", required=True)
    ap.add_argument("--profile", choices=["real", "replay"])
    ap.add_argument("--build-mode", default="")
    ap.add_argument("--test-result", default="")
    ap.add_argument("--sums-out", default=None)
    ap.add_argument("--inventory-out", default=None)
    ap.add_argument("--check", action="store_true", help="solo verifica un manifiesto existente, no regenera")
    args = ap.parse_args()

    dist_dir = Path(args.dist_dir).resolve()
    if not dist_dir.is_dir():
        print(f"ERROR: {dist_dir} no es un directorio")
        sys.exit(2)

    sums_path = Path(args.sums_out) if args.sums_out else dist_dir.parent / f"DIST_{(args.profile or 'unknown').upper()}_SHA256SUMS.txt"
    inv_path = Path(args.inventory_out) if args.inventory_out else dist_dir.parent / f"DIST_{(args.profile or 'unknown').upper()}_INVENTORY.json"

    if args.check:
        ok = check(dist_dir, sums_path)
        print("CHECK_RESULT=" + ("PASS" if ok else "FAIL"))
        sys.exit(0 if ok else 1)

    if not args.profile:
        print("ERROR: --profile es requerido para generar (real|replay)")
        sys.exit(2)

    inventory = generate(dist_dir, args.profile, args.build_mode, args.test_result)
    write_outputs(dist_dir, inventory, sums_path, inv_path)
    print(f"GENERATED: {sums_path.name} ({inventory['file_count']} files, {inventory['total_bytes']} bytes)")
    print(f"GENERATED: {inv_path.name}")


if __name__ == "__main__":
    main()
