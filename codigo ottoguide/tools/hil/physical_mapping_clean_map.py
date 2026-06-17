#!/usr/bin/env python3
"""Create derived cleaned/cropped occupancy maps without touching raw input."""

from __future__ import annotations

import argparse
import shutil
from collections import deque
from pathlib import Path


def read_yaml(path: Path) -> dict[str, str]:
    data: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if ":" not in line or line.lstrip().startswith("#"):
            continue
        key, value = line.split(":", 1)
        data[key.strip()] = value.strip().strip("'\"")
    return data


def read_pgm(path: Path) -> tuple[list[str], int, int, int, bytearray]:
    raw = path.read_bytes()
    idx = 0
    tokens: list[str] = []
    comments: list[str] = []
    while len(tokens) < 4:
        while raw[idx:idx + 1].isspace():
            idx += 1
        if raw[idx:idx + 1] == b"#":
            end = raw.index(b"\n", idx)
            comments.append(raw[idx:end].decode("ascii", errors="replace"))
            idx = end + 1
            continue
        end = idx
        while end < len(raw) and not raw[end:end + 1].isspace():
            end += 1
        tokens.append(raw[idx:end].decode("ascii"))
        idx = end
    while raw[idx:idx + 1].isspace():
        idx += 1
    if tokens[0] != "P5":
        raise ValueError("only binary P5 PGM maps are supported")
    width, height, maxval = int(tokens[1]), int(tokens[2]), int(tokens[3])
    pixels = bytearray(raw[idx:])
    if len(pixels) != width * height:
        raise ValueError("PGM pixel length does not match dimensions")
    return comments, width, height, maxval, pixels


def write_pgm(path: Path, comments: list[str], width: int, height: int, maxval: int, pixels: bytearray) -> None:
    header = ["P5", *comments, f"{width} {height}", str(maxval)]
    path.write_bytes(("\n".join(header) + "\n").encode("ascii") + bytes(pixels))


def crop_pixels(pixels: bytearray, width: int, crop: tuple[int, int, int, int]) -> tuple[int, int, bytearray]:
    x_min, y_min, x_max, y_max = crop
    if not (0 <= x_min < x_max <= width):
        raise ValueError("invalid crop x bounds")
    height = len(pixels) // width
    if not (0 <= y_min < y_max <= height):
        raise ValueError("invalid crop y bounds")
    new_width = x_max - x_min
    new_height = y_max - y_min
    out = bytearray()
    for y in range(y_min, y_max):
        start = y * width + x_min
        out.extend(pixels[start:start + new_width])
    return new_width, new_height, out


def remove_islands(pixels: bytearray, width: int, max_island: int) -> int:
    height = len(pixels) // width
    seen = bytearray(len(pixels))
    removed = 0
    for idx, value in enumerate(pixels):
        if seen[idx] or value >= 250:
            continue
        component = []
        queue = deque([idx])
        seen[idx] = 1
        while queue:
            cur = queue.popleft()
            component.append(cur)
            x = cur % width
            y = cur // width
            for nx, ny in ((x - 1, y), (x + 1, y), (x, y - 1), (x, y + 1)):
                if nx < 0 or ny < 0 or nx >= width or ny >= height:
                    continue
                nxt = ny * width + nx
                if not seen[nxt] and pixels[nxt] < 250:
                    seen[nxt] = 1
                    queue.append(nxt)
        if len(component) <= max_island:
            for pos in component:
                pixels[pos] = 254
            removed += len(component)
    return removed


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input-yaml", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--crop", nargs=4, type=int, metavar=("X_MIN", "Y_MIN", "X_MAX", "Y_MAX"))
    parser.add_argument("--remove-isolated", action="store_true")
    parser.add_argument("--max-island-size", type=int, default=8)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    input_yaml = Path(args.input_yaml).resolve()
    output_dir = Path(args.output_dir).resolve()
    meta = read_yaml(input_yaml)
    image = (input_yaml.parent / meta["image"]).resolve()
    if not args.crop and not args.remove_isolated:
        print("No crop or cleaning option selected; raw map left untouched.")
        return 0

    comments, width, height, maxval, pixels = read_pgm(image)
    report = [
        "# Cleaning Report",
        "",
        f"- Input YAML: `{input_yaml}`",
        f"- Input PGM: `{image}`",
        "- Raw input was not modified.",
    ]
    if args.crop:
        width, height, pixels = crop_pixels(pixels, width, tuple(args.crop))
        report.append(f"- Crop: `{args.crop}`")
    if args.remove_isolated:
        removed = remove_islands(pixels, width, args.max_island_size)
        report.append(f"- Isolated occupied/unknown pixels whitened: {removed}")
        report.append(f"- Max island size: {args.max_island_size}")

    if args.dry_run:
        print("\n".join(report))
        return 0

    output_dir.mkdir(parents=True, exist_ok=True)
    out_pgm = output_dir / f"{input_yaml.stem}_cleaned.pgm"
    out_yaml = output_dir / f"{input_yaml.stem}_cleaned.yaml"
    write_pgm(out_pgm, comments, width, height, maxval, pixels)
    text = input_yaml.read_text(encoding="utf-8")
    text = text.replace(meta["image"], out_pgm.name, 1)
    out_yaml.write_text(text, encoding="utf-8")
    (output_dir / "CLEANING_REPORT.md").write_text("\n".join(report) + "\n", encoding="utf-8")
    print(f"Wrote derived map: {out_yaml}")
    print("PHYSICAL MAPPING CLEAN MAP PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
