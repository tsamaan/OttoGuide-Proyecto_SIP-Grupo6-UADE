#!/usr/bin/env python3
"""WEB-HIL-R1 — build_portable_package.py

Empaqueta el arbol de codigo ottoguide/tools/hil/readonly_observability/ en un
zip portátil (para el artifact de CI o backup manual), excluyendo node_modules,
__pycache__, *.pyc, .git, venv, claves privadas y estado operativo generado.

Solo biblioteca estandar. No depende de PowerShell ni de bash.

Uso:
  python build_portable_package.py --out OTTOGUIDE_HIL_READONLY_OBSERVABILITY_PORTABLE_R1.zip
"""
from __future__ import annotations
import argparse, fnmatch, hashlib, os, zipfile

EXCLUDE_DIR_NAMES = {"node_modules", "__pycache__", ".git", "venv", "state", "logs"}
EXCLUDE_FILE_PATTERNS = [
    "*.pyc", "*.pyo", "*_pid.json", "known_hosts", "generated_target.conf",
    "id_ed25519*", "connection_proof.json", "last_resolution.json", "target.json",
]


def should_exclude_dir(name):
    return name in EXCLUDE_DIR_NAMES


def should_exclude_file(name):
    return any(fnmatch.fnmatch(name, pat) for pat in EXCLUDE_FILE_PATTERNS)


def build(root, out_path):
    root = os.path.abspath(root)
    entries = []
    with zipfile.ZipFile(out_path, "w", zipfile.ZIP_DEFLATED) as z:
        for base, dirs, files in os.walk(root):
            dirs[:] = [d for d in dirs if not should_exclude_dir(d)]
            for fn in files:
                if should_exclude_file(fn):
                    continue
                full = os.path.join(base, fn)
                arc = os.path.relpath(full, root)
                z.write(full, arc)
                entries.append(arc)
    return entries


def sha256_of(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                     help="raiz a empaquetar (default: readonly_observability/)")
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    entries = build(args.root, args.out)
    digest = sha256_of(args.out)
    print(f"[package] {args.out}")
    print(f"[package] entries={len(entries)}")
    print(f"[package] sha256={digest}")


if __name__ == "__main__":
    main()
