"""Fail-closed raw JSONL loading for ODOM/TF R2-P1 (section 19).

Reuses (never duplicates) the P0A trust boundary in
``src.navigation.odometry_evidence_r2``: descriptor/manifest verification
(``source_manifest.py``, unmodified) and shared validation primitives
(``validation.py``, unmodified).

P0A's own JSONL parser (``odometry_evidence_r2.ingest._parse_channel_jsonl_dir``)
is private and narrow by design: restricted to the two odom topics, and it
reduces every record to position+yaw_speed only for its evidentiary bundle.
P1 needs full records (sequence, receipt_monotonic_ns, velocity, mode) for
channel-quality/alignment/motion metrics P0A never computed -- and a THIRD
topic, ``rt/lowstate``, that P0A's parser explicitly rejects as unknown, for
the IMU cross-check. Rather than modify or duplicate that private function,
this module implements new parsing code on top of the same shared validation
layer P0A already tested.

Fail-closed on structural corruption exactly like P0A: non-UTF-8 bytes,
malformed JSON, a non-terminal NUL run, a missing/malformed required field,
a non-finite numeric value, or a genuinely unknown topic each abort the
parse. UNLIKE P0A's evidentiary parser -- which aborts the whole directory
parse on any duplicate/out-of-order sequence -- this loader COUNTS
duplicate/out-of-order sequences rather than aborting, because quantifying
such defects is P1's explicit purpose (section 22 channel-quality metrics),
not a reason to discard an entire session's worth of otherwise-valid samples.
"""
import json
from pathlib import Path

from src.navigation.odometry_evidence_r2.source_manifest import (  # noqa: F401 (re-exported for CLI use)
    load_descriptor,
    resolve_harvest_root,
    sha256_of_file,
    verify_harvest_against_descriptor,
)
from src.navigation.odometry_evidence_r2.validation import (
    EvidenceValidationError,
    is_finite_number,
)

from .models import CHARACTERIZATION_SCHEMA_VERSION, NormalizedLowStateSample, NormalizedOdomSample

ODOM_TOPIC_FIELD = {
    "rt/odommodestate": "odom",
    "rt/lf/odommodestate": "lf_odom",
}
LOWSTATE_TOPIC = "rt/lowstate"
_ALL_KNOWN_TOPICS = frozenset(set(ODOM_TOPIC_FIELD) | {LOWSTATE_TOPIC})


def _read_text_fail_closed(path: Path) -> "tuple[str, bool]":
    """Read a JSONL chunk file's text, tolerating only a fully-terminal NUL
    run following a complete line (the documented unclean-power-cycle-
    shutdown artifact P0A also tolerates). Returns (text, had_terminal_nul)."""
    raw = path.read_bytes()
    had_terminal_nul = False
    first_nul = raw.find(b"\x00")
    if first_nul != -1:
        tail = raw[first_nul:]
        if any(b != 0 for b in tail):
            raise EvidenceValidationError(
                f"{path}: non-terminal NUL byte at offset {first_nul} (non-NUL bytes follow it)"
            )
        prefix = raw[:first_nul]
        if prefix and not prefix.endswith(b"\n"):
            raise EvidenceValidationError(
                f"{path}: terminal NUL at offset {first_nul} does not follow a complete JSON line"
            )
        had_terminal_nul = True
        raw = prefix
    try:
        return raw.decode("utf-8"), had_terminal_nul
    except UnicodeDecodeError as exc:
        raise EvidenceValidationError(f"{path}: invalid UTF-8: {exc}") from exc


def _iter_lines(path: Path, text: str):
    for line_no, line in enumerate(text.splitlines(), start=1):
        line = line.strip()
        if not line:
            continue
        try:
            yield line_no, json.loads(line)
        except json.JSONDecodeError as exc:
            raise EvidenceValidationError(f"{path.name}:{line_no}: malformed JSON: {exc}") from exc


def _require_topic(path: Path, line_no: int, record: dict) -> str:
    topic = record.get("topic")
    if topic not in _ALL_KNOWN_TOPICS:
        raise EvidenceValidationError(f"{path.name}:{line_no}: unknown topic {topic!r}")
    return topic


def new_stats() -> dict:
    return dict(
        file_count=0, record_count=0, discarded_records=0, terminal_nul_files=0,
        duplicate_sequences=0, monotonic_inversions=0, schema_errors=0,
    )


def _parse_odom_records(paths, expected_topic, harvest_root: Path, session_id: str,
                         boot_id: "str | None", stats: dict, file_hashes: dict):
    field = ODOM_TOPIC_FIELD[expected_topic]
    samples = []
    last_sequence = None
    for path in paths:
        stats["file_count"] += 1
        rel = path.relative_to(harvest_root).as_posix()
        file_hashes[rel] = sha256_of_file(path)
        text, had_nul = _read_text_fail_closed(path)
        if had_nul:
            stats["terminal_nul_files"] += 1
        for line_no, record in _iter_lines(path, text):
            topic = _require_topic(path, line_no, record)
            if topic != expected_topic:
                stats["discarded_records"] += 1
                continue
            sequence = record.get("sequence")
            if type(sequence) is not int or sequence <= 0:
                stats["schema_errors"] += 1
                raise EvidenceValidationError(
                    f"{path.name}:{line_no}: sequence must be a positive int, got {sequence!r}"
                )
            receipt_ns = record.get("receipt_monotonic_ns")
            if type(receipt_ns) is not int or receipt_ns < 0:
                stats["schema_errors"] += 1
                raise EvidenceValidationError(
                    f"{path.name}:{line_no}: receipt_monotonic_ns must be a non-negative int"
                )
            payload = record.get(field)
            position = payload.get("position") if type(payload) is dict else None
            velocity = payload.get("velocity") if type(payload) is dict else None
            yaw_speed = payload.get("yaw_speed") if type(payload) is dict else None
            mode = payload.get("mode") if type(payload) is dict else None
            if (
                type(payload) is not dict
                or type(position) is not list or len(position) != 3
                or type(velocity) is not list or len(velocity) != 3
                or yaw_speed is None or mode is None
            ):
                stats["schema_errors"] += 1
                raise EvidenceValidationError(f"{path.name}:{line_no}: malformed '{field}' payload")
            numeric_values = list(position) + list(velocity) + [yaw_speed]
            if not all(is_finite_number(v) for v in numeric_values) or type(mode) is bool or type(mode) is not int:
                stats["schema_errors"] += 1
                raise EvidenceValidationError(f"{path.name}:{line_no}: non-finite/malformed numeric value in '{field}'")

            if last_sequence is not None and sequence == last_sequence:
                stats["duplicate_sequences"] += 1
                continue
            if last_sequence is not None and sequence < last_sequence:
                stats["monotonic_inversions"] += 1
                continue
            last_sequence = sequence
            stats["record_count"] += 1
            samples.append(NormalizedOdomSample(
                schema_version=CHARACTERIZATION_SCHEMA_VERSION,
                session_id=session_id,
                boot_id=boot_id,
                channel=expected_topic,
                sequence=sequence,
                receipt_monotonic_ns=receipt_ns,
                receipt_utc=record.get("receipt_utc"),
                phase=record.get("phase") or "UNMARKED",
                position=tuple(float(v) for v in position),
                velocity=tuple(float(v) for v in velocity),
                yaw_speed=float(yaw_speed),
                mode=int(mode),
                source_file=rel,
                source_sha256=file_hashes[rel],
            ))
    samples.sort(key=lambda s: s.sequence)
    return tuple(samples)


def parse_odom_topic_dir(directory: Path, expected_topic: str, harvest_root: Path,
                          session_id: str, boot_id: "str | None"):
    """Parse every ``*.jsonl`` chunk in ``directory`` for ``expected_topic``.
    Returns (samples, stats_dict, file_hashes_dict)."""
    if expected_topic not in ODOM_TOPIC_FIELD:
        raise EvidenceValidationError(f"unknown odom topic: {expected_topic!r}")
    stats = new_stats()
    file_hashes = {}
    samples = _parse_odom_records(sorted(directory.glob("*.jsonl")), expected_topic,
                                   harvest_root, session_id, boot_id, stats, file_hashes)
    return samples, stats, file_hashes


def parse_odom_topic_file(path: Path, expected_topic: str, harvest_root: Path,
                           session_id: str, boot_id: "str | None"):
    """Parse a single flat JSONL file (R4B's layout) for ``expected_topic``."""
    if expected_topic not in ODOM_TOPIC_FIELD:
        raise EvidenceValidationError(f"unknown odom topic: {expected_topic!r}")
    stats = new_stats()
    file_hashes = {}
    samples = _parse_odom_records([path], expected_topic, harvest_root, session_id, boot_id,
                                   stats, file_hashes)
    return samples, stats, file_hashes


def _parse_lowstate_records(paths, harvest_root: Path, session_id: str, stats: dict, file_hashes: dict):
    samples = []
    last_sequence = None
    for path in paths:
        stats["file_count"] += 1
        rel = path.relative_to(harvest_root).as_posix()
        file_hashes[rel] = sha256_of_file(path)
        text, had_nul = _read_text_fail_closed(path)
        if had_nul:
            stats["terminal_nul_files"] += 1
        for line_no, record in _iter_lines(path, text):
            topic = _require_topic(path, line_no, record)
            if topic != LOWSTATE_TOPIC:
                stats["discarded_records"] += 1
                continue
            sequence = record.get("sequence")
            if type(sequence) is not int or sequence <= 0:
                stats["schema_errors"] += 1
                raise EvidenceValidationError(f"{path.name}:{line_no}: sequence must be a positive int")
            receipt_ns = record.get("receipt_monotonic_ns")
            if type(receipt_ns) is not int or receipt_ns < 0:
                stats["schema_errors"] += 1
                raise EvidenceValidationError(f"{path.name}:{line_no}: receipt_monotonic_ns must be non-negative")
            imu = record.get("imu")
            gyroscope = imu.get("gyroscope") if type(imu) is dict else None
            rpy_deg = imu.get("rpy_deg") if type(imu) is dict else None
            if (
                type(imu) is not dict
                or type(gyroscope) is not list or len(gyroscope) != 3
                or type(rpy_deg) is not list or len(rpy_deg) != 3
            ):
                stats["schema_errors"] += 1
                raise EvidenceValidationError(f"{path.name}:{line_no}: malformed 'imu' payload")
            if not all(is_finite_number(v) for v in list(gyroscope) + list(rpy_deg)):
                stats["schema_errors"] += 1
                raise EvidenceValidationError(f"{path.name}:{line_no}: non-finite IMU value")

            if last_sequence is not None and sequence == last_sequence:
                stats["duplicate_sequences"] += 1
                continue
            if last_sequence is not None and sequence < last_sequence:
                stats["monotonic_inversions"] += 1
                continue
            last_sequence = sequence
            stats["record_count"] += 1
            samples.append(NormalizedLowStateSample(
                schema_version=CHARACTERIZATION_SCHEMA_VERSION,
                session_id=session_id,
                sequence=sequence,
                receipt_monotonic_ns=receipt_ns,
                phase=record.get("phase") or "UNMARKED",
                gyroscope=tuple(float(v) for v in gyroscope),
                rpy_deg=tuple(float(v) for v in rpy_deg),
                source_file=rel,
                source_sha256=file_hashes[rel],
            ))
    samples.sort(key=lambda s: s.sequence)
    return tuple(samples)


def parse_lowstate_topic_dir(directory: Path, harvest_root: Path, session_id: str):
    stats = new_stats()
    file_hashes = {}
    samples = _parse_lowstate_records(sorted(directory.glob("*.jsonl")), harvest_root, session_id,
                                       stats, file_hashes)
    return samples, stats, file_hashes


def parse_lowstate_topic_file(path: Path, harvest_root: Path, session_id: str):
    stats = new_stats()
    file_hashes = {}
    samples = _parse_lowstate_records([path], harvest_root, session_id, stats, file_hashes)
    return samples, stats, file_hashes
