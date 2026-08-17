#!/usr/bin/env python3
"""Conservative local artifacts audit for OttoGuide.

The script inventories artifacts, classifies files for keep/review/quarantine,
and writes reports. It never deletes or moves files.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import os
from collections import defaultdict
from datetime import datetime
from pathlib import Path


HEAVY_REVIEW_EXTS = {".db3", ".bag", ".mcap", ".pgm", ".yaml", ".yml", ".mp4"}
RAW_MAP_EXTS = {".pgm", ".yaml", ".yml"}
ROS_BAG_EXTS = {".db3", ".bag", ".mcap"}
VIDEO_EXTS = {".mp4", ".mov", ".avi", ".mkv"}
POINTCLOUD_EXTS = {".ply", ".pcd"}
EVIDENCE_WORDS = ("manifest", "sha256", "readme", "qa", "handoff", "final", "validated")
SESSION_WORDS = ("physical_mapping", "hil_mapping", "route", "real", "stationary")
QUARANTINE_WORDS = ("tmp", "temp", "debug", "test", "failed", "black", "scratch", "cache")


def human_size(num: int) -> str:
    value = float(num)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if value < 1024 or unit == "TB":
            return f"{value:.1f} {unit}"
        value /= 1024
    return f"{num} B"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def is_inside(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False


def classify(rel: str, ext: str, size: int, has_trace: bool, latest_hint: bool) -> tuple[str, str]:
    lower = rel.lower()
    if ext in ROS_BAG_EXTS:
        return "REVIEW_MANUAL", "rosbag/database artifacts require human review"
    if ext in RAW_MAP_EXTS:
        return "REVIEW_MANUAL", "map files are never moved automatically"
    if ext in VIDEO_EXTS and size > 10 * 1024 * 1024:
        return "REVIEW_MANUAL", "large video evidence requires human review"
    if ext in POINTCLOUD_EXTS:
        return "REVIEW_MANUAL", "point cloud evidence requires human review"
    if has_trace or latest_hint:
        return "KEEP_RECOMMENDED", "traceable evidence or recent/latest session"
    if any(word in lower for word in QUARANTINE_WORDS):
        return "QUARANTINE_CANDIDATE", "temporary/debug/test naming pattern"
    if size == 0:
        return "QUARANTINE_CANDIDATE", "empty artifact"
    if size > 100 * 1024 * 1024:
        return "REVIEW_MANUAL", "heavy artifact without clear traceability"
    return "REVIEW_MANUAL", "manual review by default"


def write_csv(path: Path, rows: list[dict], fields: list[str]) -> None:
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def write_md_list(path: Path, title: str, rows: list[dict], limit: int | None = None) -> None:
    selected = rows[:limit] if limit else rows
    with path.open("w", encoding="utf-8") as fh:
        fh.write(f"# {title}\n\n")
        if not selected:
            fh.write("No entries.\n")
            return
        for row in selected:
            reason = row.get("classification_reason") or row.get("duplicate_group") or ""
            fh.write(f"- `{row['relative_path']}` ({row['human_size']})")
            if reason:
                fh.write(f" - {reason}")
            fh.write("\n")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--artifacts-dir", default="artifacts")
    parser.add_argument("--output-dir")
    parser.add_argument("--hash-large-files", action="store_true")
    parser.add_argument("--large-threshold-mb", type=int, default=100)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    root = Path.cwd()
    artifacts = (root / args.artifacts_dir).resolve()
    if not artifacts.exists():
        raise SystemExit(f"artifacts directory does not exist: {artifacts}")

    run_id = datetime.now().strftime("%Y%m%d_%H%M%S")
    output = Path(args.output_dir) if args.output_dir else artifacts / "_audit" / f"local_artifacts_{run_id}"
    output = output.resolve()

    files: list[Path] = []
    for path in artifacts.rglob("*"):
        if not path.is_file():
            continue
        resolved = path.resolve()
        if is_inside(resolved, artifacts / "_audit") or is_inside(resolved, artifacts / "_quarantine"):
            continue
        if is_inside(resolved, output):
            continue
        files.append(resolved)

    total_size = sum(path.stat().st_size for path in files)
    latest_mtime = max((path.stat().st_mtime for path in files), default=0)
    threshold = args.large_threshold_mb * 1024 * 1024
    by_size: dict[int, list[Path]] = defaultdict(list)
    hash_rows: dict[str, list[str]] = defaultdict(list)
    ext_sizes: dict[str, int] = defaultdict(int)
    ext_counts: dict[str, int] = defaultdict(int)
    rows: list[dict] = []

    for path in files:
        stat = path.stat()
        rel = path.relative_to(artifacts).as_posix()
        ext = path.suffix.lower()
        lower = rel.lower()
        has_trace = any(word in lower for word in EVIDENCE_WORDS)
        latest_hint = any(word in lower for word in SESSION_WORDS) and stat.st_mtime >= latest_mtime - (14 * 24 * 3600)
        classification, reason = classify(rel, ext, stat.st_size, has_trace, latest_hint)
        digest = ""
        if stat.st_size <= threshold or args.hash_large_files:
            digest = sha256(path)
            hash_rows[digest].append(rel)
        by_size[stat.st_size].append(path)
        ext_key = ext or "[no extension]"
        ext_sizes[ext_key] += stat.st_size
        ext_counts[ext_key] += 1
        rows.append(
            {
                "relative_path": rel,
                "full_path": str(path),
                "directory": str(path.parent),
                "name": path.name,
                "extension": ext,
                "size_bytes": stat.st_size,
                "human_size": human_size(stat.st_size),
                "created": datetime.fromtimestamp(stat.st_ctime).isoformat(timespec="seconds"),
                "modified": datetime.fromtimestamp(stat.st_mtime).isoformat(timespec="seconds"),
                "sha256": digest,
                "classification": classification,
                "classification_reason": reason,
            }
        )

    rows.sort(key=lambda item: int(item["size_bytes"]), reverse=True)
    large = [row for row in rows if int(row["size_bytes"]) >= threshold]
    keep = [row for row in rows if row["classification"] == "KEEP_RECOMMENDED"]
    quarantine = [row for row in rows if row["classification"] == "QUARANTINE_CANDIDATE"]
    review = [row for row in rows if row["classification"] == "REVIEW_MANUAL"]
    duplicates = []
    for digest, rels in sorted(hash_rows.items()):
        if digest and len(rels) > 1:
            for rel in rels:
                match = next(row for row in rows if row["relative_path"] == rel)
                duplicate = dict(match)
                duplicate["duplicate_group"] = digest
                duplicates.append(duplicate)

    if args.dry_run:
        print(f"DRY RUN: would write audit to {output}")
    else:
        output.mkdir(parents=True, exist_ok=True)
        fields = list(rows[0].keys()) if rows else [
            "relative_path", "full_path", "directory", "name", "extension", "size_bytes",
            "human_size", "created", "modified", "sha256", "classification", "classification_reason",
        ]
        write_csv(output / "LOCAL_ARTIFACTS_INVENTORY.csv", rows, fields)
        write_csv(output / "LOCAL_ARTIFACTS_LARGE_FILES.csv", large, fields)
        write_csv(output / "LOCAL_ARTIFACTS_DUPLICATES.csv", duplicates, fields + ["duplicate_group"] if duplicates else fields)
        write_md_list(output / "LOCAL_ARTIFACTS_KEEP_RECOMMENDED.md", "Keep Recommended", keep)
        write_md_list(output / "LOCAL_ARTIFACTS_QUARANTINE_CANDIDATES.md", "Quarantine Candidates", quarantine)
        with (output / "LOCAL_ARTIFACTS_CLEANUP_PLAN.md").open("w", encoding="utf-8") as fh:
            fh.write("# Local Artifacts Cleanup Plan\n\n")
            fh.write("No files were moved or deleted by this audit.\n\n")
            fh.write("To quarantine safe candidates, require explicit user confirmation: `CONFIRM LOCAL ARTIFACTS QUARANTINE`.\n\n")
            fh.write("Never quarantine `REVIEW_MANUAL` items without a second, specific review.\n")
        with (output / "LOCAL_ARTIFACTS_SUMMARY.md").open("w", encoding="utf-8") as fh:
            fh.write("# Local Artifacts Summary\n\n")
            fh.write(f"- Artifacts path: `{artifacts}`\n")
            fh.write(f"- Audit path: `{output}`\n")
            fh.write(f"- File count: {len(rows)}\n")
            fh.write(f"- Total size: {human_size(total_size)} ({total_size} bytes)\n")
            fh.write(f"- Large threshold: {args.large_threshold_mb} MB\n")
            fh.write(f"- Keep recommended: {len(keep)}\n")
            fh.write(f"- Quarantine candidates: {len(quarantine)}\n")
            fh.write(f"- Review manual: {len(review)}\n")
            fh.write(f"- Exact duplicate files: {len(duplicates)}\n\n")
            fh.write("## Size By Extension\n\n")
            for ext, count in sorted(ext_counts.items(), key=lambda item: ext_sizes[item[0]], reverse=True):
                fh.write(f"- `{ext}`: {count} files, {human_size(ext_sizes[ext])}\n")
            fh.write("\n## Top 20 Large Files\n\n")
            for row in rows[:20]:
                fh.write(f"- `{row['relative_path']}` - {row['human_size']} - {row['classification']}\n")

    print(f"AUDIT_PATH={output}")
    print(f"TOTAL_FILES={len(rows)}")
    print(f"TOTAL_SIZE={human_size(total_size)}")
    print(f"KEEP_RECOMMENDED={len(keep)}")
    print(f"QUARANTINE_CANDIDATES={len(quarantine)}")
    print(f"REVIEW_MANUAL={len(review)}")
    print(f"DUPLICATE_FILES={len(duplicates)}")
    print("LOCAL ARTIFACTS AUDIT PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
