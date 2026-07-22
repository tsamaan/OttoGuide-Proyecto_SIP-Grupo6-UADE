#!/usr/bin/env python3
"""WEB-HIL-R1B — generate_changeset_evidence.py

Genera evidencia criptografica CORRECTA y sin ambiguedad para un rango de commits git:

  CHANGESET_SHA256SUMS.txt        -- SHA-256 REAL de los bytes de cada blob (64 hex + '  ' + path)
  CHANGESET_GIT_BLOB_OIDS_SHA1.txt -- OIDs de blob de git (SHA-1, 40 hex) para el mismo conjunto

Nunca usa 'git rev-parse HEAD:path' (un OID de blob SHA-1 de git) como si fuera un
SHA-256 -- son dos algoritmos distintos con longitudes distintas (40 vs 64 hex chars) y
NO deben mezclarse en un mismo archivo declarado "SHA256SUMS".

Uso:
  python generate_changeset_evidence.py --repo-root <path> --base <base_sha> --head <head_sha> --out-dir <dir>
  python generate_changeset_evidence.py --repo-root <path> --base <base_sha> --head <head_sha> --out-dir <dir> --check
"""
from __future__ import annotations
import argparse
import hashlib
import subprocess
import sys
from pathlib import Path


def run_git(repo_root: str, args: list[str]) -> str:
    result = subprocess.run(
        ["git", "-C", repo_root] + args,
        capture_output=True, text=True, check=True,
    )
    return result.stdout


def get_diff_files(repo_root: str, base: str, head: str) -> list[str]:
    out = run_git(repo_root, ["diff", "--name-only", f"{base}..{head}"])
    return [line for line in out.splitlines() if line.strip()]


def get_blob_bytes(repo_root: str, head: str, path: str) -> bytes:
    result = subprocess.run(
        ["git", "-C", repo_root, "show", f"{head}:{path}"],
        capture_output=True, check=True,
    )
    return result.stdout


def get_blob_oid(repo_root: str, head: str, path: str) -> str:
    out = run_git(repo_root, ["rev-parse", f"{head}:{path}"])
    return out.strip()


def generate(repo_root: str, base: str, head: str, out_dir: Path):
    files = sorted(get_diff_files(repo_root, base, head))
    sha256_lines = []
    oid_lines = []
    for path in files:
        content = get_blob_bytes(repo_root, head, path)
        digest = hashlib.sha256(content).hexdigest()
        oid = get_blob_oid(repo_root, head, path)
        sha256_lines.append(f"{digest}  {path}")
        oid_lines.append(f"{oid}  {path}")

    sha_path = out_dir / "CHANGESET_SHA256SUMS.txt"
    oid_path = out_dir / "CHANGESET_GIT_BLOB_OIDS_SHA1.txt"
    with open(sha_path, "w", newline="\n") as f:
        f.write("\n".join(sha256_lines) + "\n")
    with open(oid_path, "w", newline="\n") as f:
        f.write("\n".join(oid_lines) + "\n")
    return files, sha_path, oid_path


def check(repo_root: str, head: str, out_dir: Path, expected_file_count: int | None):
    sha_path = out_dir / "CHANGESET_SHA256SUMS.txt"
    oid_path = out_dir / "CHANGESET_GIT_BLOB_OIDS_SHA1.txt"
    problems = []

    if not sha_path.exists():
        problems.append(f"falta {sha_path}")
    if not oid_path.exists():
        problems.append(f"falta {oid_path}")
    if problems:
        for p in problems:
            print(f"CHECK_FAIL: {p}")
        return False

    sha_entries = {}
    with open(sha_path) as f:
        for line in f:
            line = line.rstrip("\n")
            if not line.strip():
                continue
            parts = line.split("  ", 1)
            if len(parts) != 2:
                problems.append(f"linea SHA256 mal formada: {line!r}")
                continue
            digest, path = parts
            if len(digest) != 64:
                problems.append(f"campo SHA256 no tiene 64 chars hex: {digest!r} ({path})")
            if path in sha_entries:
                problems.append(f"path duplicado en CHANGESET_SHA256SUMS.txt: {path}")
            sha_entries[path] = digest

    oid_entries = {}
    with open(oid_path) as f:
        for line in f:
            line = line.rstrip("\n")
            if not line.strip():
                continue
            parts = line.split("  ", 1)
            if len(parts) != 2:
                problems.append(f"linea OID mal formada: {line!r}")
                continue
            oid, path = parts
            if len(oid) != 40:
                problems.append(f"campo OID no tiene 40 chars hex: {oid!r} ({path})")
            if path in oid_entries:
                problems.append(f"path duplicado en CHANGESET_GIT_BLOB_OIDS_SHA1.txt: {path}")
            oid_entries[path] = oid

    if expected_file_count is not None:
        if len(sha_entries) != expected_file_count:
            problems.append(f"CHANGESET_SHA256SUMS.txt tiene {len(sha_entries)} entradas, se esperaban {expected_file_count}")
        if len(oid_entries) != expected_file_count:
            problems.append(f"CHANGESET_GIT_BLOB_OIDS_SHA1.txt tiene {len(oid_entries)} entradas, se esperaban {expected_file_count}")

    if set(sha_entries.keys()) != set(oid_entries.keys()):
        problems.append("los paths de CHANGESET_SHA256SUMS.txt y CHANGESET_GIT_BLOB_OIDS_SHA1.txt no coinciden")

    for path, digest in sha_entries.items():
        try:
            content = get_blob_bytes(repo_root, head, path)
        except subprocess.CalledProcessError:
            problems.append(f"path no existe en HEAD ({head}): {path}")
            continue
        actual = hashlib.sha256(content).hexdigest()
        if actual != digest:
            problems.append(f"SHA256 no coincide para {path}: esperado={digest} actual={actual}")

    for path, oid in oid_entries.items():
        try:
            actual_oid = get_blob_oid(repo_root, head, path)
        except subprocess.CalledProcessError:
            problems.append(f"path no existe en HEAD ({head}) al recalcular OID: {path}")
            continue
        if actual_oid != oid:
            problems.append(f"blob OID no coincide para {path}: esperado={oid} actual={actual_oid}")

    if problems:
        for p in problems:
            print(f"CHECK_FAIL: {p}")
        return False
    return True


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo-root", required=True)
    ap.add_argument("--base", required=True)
    ap.add_argument("--head", required=True)
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--expected-file-count", type=int, default=None)
    args = ap.parse_args()

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    if args.check:
        ok = check(args.repo_root, args.head, out_dir, args.expected_file_count)
        print("CHECK_RESULT=" + ("PASS" if ok else "FAIL"))
        sys.exit(0 if ok else 1)

    files, sha_path, oid_path = generate(args.repo_root, args.base, args.head, out_dir)
    print(f"GENERATED: {sha_path} ({len(files)} files)")
    print(f"GENERATED: {oid_path} ({len(files)} files)")


if __name__ == "__main__":
    main()
