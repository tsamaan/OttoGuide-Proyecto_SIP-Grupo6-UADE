"""Strict validation and hash binding for P2A material inputs."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

from .models import (
    CHANNELS,
    KNOWN_P1A_SHA256,
    MAPPING_SCHEMA_VERSION,
    P1A_SCHEMA_VERSION,
    ClaimStrength,
    ContractValidationError,
    ValidatedInput,
    ValidationContext,
    canonical_string,
    finite_number,
    logical_path,
    positive_int,
    sha256_string,
)


EXPECTED_AUDIT_IDS = tuple(f"H{number}" for number in range(1, 11))


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError as exc:
        raise ContractValidationError(f"cannot hash input: {path.name}") from exc
    return digest.hexdigest()


def load_json_object(path: Path, label: str) -> dict[str, object]:
    if not path.is_file():
        raise ContractValidationError(f"{label} does not exist")
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ContractValidationError(f"{label} is not valid JSON") from exc
    if type(value) is not dict:
        raise ContractValidationError(f"{label} must be an exact JSON object")
    return value


def _exact_list(value: object, label: str) -> list[object]:
    if type(value) is not list:
        raise ContractValidationError(f"{label} must be an exact list")
    return value


def _exact_dict(value: object, label: str) -> dict[str, object]:
    if type(value) is not dict:
        raise ContractValidationError(f"{label} must be an exact object")
    return value


def _canonical_string_list(value: object, label: str) -> tuple[str, ...]:
    items = _exact_list(value, label)
    result = tuple(canonical_string(item, f"{label}[]") for item in items)
    if len(set(result)) != len(result):
        raise ContractValidationError(f"{label} must be unique")
    return result


def _numeric_vector(value: object, label: str) -> tuple[float, float, float]:
    if type(value) not in (list, tuple):
        raise ContractValidationError(f"{label} must be an exact list or tuple")
    values = value
    if len(values) != 3:
        raise ContractValidationError(f"{label} must contain exactly three values")
    return tuple(  # type: ignore[return-value]
        finite_number(item, f"{label}[]") for item in values
    )


def _manifest_entries(path: Path) -> dict[str, str]:
    entries: dict[str, str] = {}
    try:
        lines = path.read_text(encoding="utf-8-sig").splitlines()
    except (OSError, UnicodeError) as exc:
        raise ContractValidationError("mapping input manifest is unreadable") from exc
    for line in lines:
        if not line:
            continue
        parts = line.split("  ", 1)
        if len(parts) != 2:
            raise ContractValidationError("mapping input manifest line is malformed")
        digest, entry_path = parts
        entry_path = entry_path.removeprefix("*")
        sha256_string(digest, "mapping manifest entry sha256")
        logical_path(entry_path, "mapping manifest entry path")
        if entry_path in entries:
            raise ContractValidationError("mapping input manifest has duplicate paths")
        entries[entry_path] = digest
    if not entries:
        raise ContractValidationError("mapping input manifest is empty")
    return entries


def _material_path(root: Path, relative: str, label: str) -> Path:
    candidate = root.joinpath(*relative.split("/"))
    try:
        resolved = candidate.resolve(strict=True)
    except OSError as exc:
        raise ContractValidationError(f"{label} does not exist") from exc
    if resolved != root and not resolved.is_relative_to(root):
        raise ContractValidationError(f"{label} escapes the mapping root")
    if not resolved.is_file() or candidate.is_symlink():
        raise ContractValidationError(f"{label} must be a regular non-symlink file")
    return resolved


@dataclass(frozen=True, kw_only=True)
class MappingBinding:
    manifest_input: ValidatedInput
    selected_inputs: tuple[ValidatedInput, ...]
    source_ids: tuple[str, ...]
    file_categories: tuple[str, ...]
    selected_source_categories: tuple[tuple[str, str], ...]
    session_ids: tuple[str, ...]
    take_ids: tuple[str, ...]
    observed_frame_ids: tuple[str, ...]
    observed_topic_ids: tuple[str, ...]
    allowed_claims: tuple[str, ...]
    prohibited_claims: tuple[str, ...]
    structural_correlation_policy: tuple[str, ...]

    def __post_init__(self) -> None:
        if type(self.manifest_input) is not ValidatedInput:
            raise ContractValidationError("mapping manifest input type mismatch")
        if (
            self.manifest_input.source_id != "r2-p2a-mapping-evidence-manifest"
            or self.manifest_input.validation_context is not ValidationContext.OFFLINE_REPLAY
            or self.manifest_input.claim_strength
            is not ClaimStrength.PRESERVED_MAPPING_REFERENCE
        ):
            raise ContractValidationError("mapping manifest input contract mismatch")
        if type(self.selected_inputs) is not tuple or not self.selected_inputs:
            raise ContractValidationError("selected_inputs must be a non-empty exact tuple")
        if any(type(item) is not ValidatedInput for item in self.selected_inputs):
            raise ContractValidationError("selected_inputs type mismatch")
        if any(
            item.validation_context is not ValidationContext.OFFLINE_REPLAY
            or item.claim_strength not in (
                ClaimStrength.PRESERVED_MAPPING_REFERENCE,
                ClaimStrength.DERIVED_MAPPING_REFERENCE,
            )
            for item in self.selected_inputs
        ):
            raise ContractValidationError("selected input contract mismatch")
        for name in (
            "source_ids", "file_categories", "session_ids", "take_ids",
            "observed_frame_ids", "observed_topic_ids", "allowed_claims",
            "prohibited_claims", "structural_correlation_policy",
        ):
            value = getattr(self, name)
            if type(value) is not tuple or not value:
                raise ContractValidationError(f"{name} must be a non-empty unique exact tuple")
            exact_string_tuple = _canonical_string_list(list(value), name)
            if exact_string_tuple != value:
                raise ContractValidationError(f"{name} must be a non-empty unique exact tuple")
        selected_ids = tuple(item.source_id for item in self.selected_inputs)
        if self.source_ids != selected_ids:
            raise ContractValidationError("source_ids must match selected_inputs in order")
        if type(self.selected_source_categories) is not tuple or not self.selected_source_categories:
            raise ContractValidationError("selected_source_categories must be a non-empty exact tuple")
        pairs: list[tuple[str, str]] = []
        for pair in self.selected_source_categories:
            if type(pair) is not tuple or len(pair) != 2:
                raise ContractValidationError("selected source category pair must be an exact pair")
            pairs.append((canonical_string(pair[0], "selected category source_id"), canonical_string(pair[1], "selected category")))
        if tuple(source_id for source_id, _ in pairs) != self.source_ids:
            raise ContractValidationError("selected source category IDs must match source_ids in order")
        if any(category not in self.file_categories for _, category in pairs):
            raise ContractValidationError("selected source category is not declared")
        used_categories = {category for _, category in pairs}
        if used_categories != set(self.file_categories):
            raise ContractValidationError("every file category must have a selected source")


def validate_mapping_manifest(
    document: Mapping[str, object],
    *,
    manifest_path: Path,
    mapping_root: Path,
) -> MappingBinding:
    if type(document) is not dict:
        raise ContractValidationError("mapping manifest must be an exact object")
    if document.get("schema_version") != MAPPING_SCHEMA_VERSION:
        raise ContractValidationError("mapping manifest schema mismatch")
    for false_claim in (
        "contains_raw_data",
        "contains_personal_absolute_paths",
        "physical_validation_claim",
    ):
        if document.get(false_claim) is not False:
            raise ContractValidationError(f"{false_claim} must be false")
    source_ids = _canonical_string_list(document.get("source_ids"), "source_ids")
    session_ids = _canonical_string_list(document.get("session_ids"), "session_ids")
    take_ids = _canonical_string_list(document.get("take_ids"), "take_ids")
    file_categories = _canonical_string_list(document.get("file_categories"), "file_categories")
    frame_ids = _canonical_string_list(document.get("observed_frame_ids"), "observed_frame_ids")
    topic_ids = _canonical_string_list(document.get("observed_topic_ids"), "observed_topic_ids")
    allowed = _canonical_string_list(document.get("allowed_claims"), "allowed_claims")
    prohibited = _canonical_string_list(document.get("prohibited_claims"), "prohibited_claims")
    required_prohibitions = {
        "PHYSICAL_FRAME_SEMANTICS_VERIFIED",
        "PHYSICAL_SCALE_VERIFIED",
        "RIGHT_HANDED_MODEL_VERIFIED",
        "ROS_REP_103_MODEL_VERIFIED",
        "UNITY_SCALE_MODEL_VERIFIED",
    }
    if not required_prohibitions.issubset(prohibited):
        raise ContractValidationError("mapping manifest omits required prohibited claims")
    root = mapping_root.resolve(strict=True)
    if not root.is_dir():
        raise ContractValidationError("mapping root must be a directory")
    manifest_rows = _exact_list(document.get("input_manifests"), "input_manifests")
    if not manifest_rows:
        raise ContractValidationError("input_manifests must not be empty")
    verified_manifests: dict[str, dict[str, str]] = {}
    for row_value in manifest_rows:
        row = _exact_dict(row_value, "input_manifest")
        rel = logical_path(row.get("logical_path"), "input_manifest.logical_path")
        if rel in verified_manifests:
            raise ContractValidationError("input manifest logical paths must be unique")
        expected = sha256_string(row.get("sha256"), "input_manifest.sha256")
        source_path = _material_path(root, rel, "mapping input manifest")
        if sha256_file(source_path) != expected:
            raise ContractValidationError(f"mapping input manifest hash mismatch: {rel}")
        verified_manifests[rel] = _manifest_entries(source_path)
    source_rows = _exact_list(document.get("selected_sources"), "selected_sources")
    if not source_rows:
        raise ContractValidationError("selected_sources must not be empty")
    selected: list[ValidatedInput] = []
    selected_categories: list[tuple[str, str]] = []
    seen_sources: set[str] = set()
    seen_paths: set[str] = set()
    for row_value in source_rows:
        row = _exact_dict(row_value, "selected_source")
        source_id = canonical_string(row.get("source_id"), "selected_source.source_id")
        if source_id in seen_sources:
            raise ContractValidationError("selected source IDs must be unique")
        seen_sources.add(source_id)
        rel = logical_path(row.get("logical_path"), "selected_source.logical_path")
        if rel in seen_paths:
            raise ContractValidationError("selected source logical paths must be unique")
        seen_paths.add(rel)
        category = canonical_string(row.get("category"), "selected_source.category")
        if category not in file_categories:
            raise ContractValidationError("selected source category is not declared")
        expected = sha256_string(row.get("sha256"), "selected_source.sha256")
        manifest_rel = logical_path(row.get("manifest_path"), "selected_source.manifest_path")
        entry_rel = logical_path(
            row.get("manifest_entry_path"), "selected_source.manifest_entry_path"
        )
        context_value = row.get("validation_context")
        strength_value = row.get("claim_strength")
        if context_value != ValidationContext.OFFLINE_REPLAY.value:
            raise ContractValidationError("mapping source context must be OFFLINE_REPLAY")
        try:
            strength = ClaimStrength(strength_value)
        except (TypeError, ValueError) as exc:
            raise ContractValidationError("unknown mapping claim strength") from exc
        if strength not in (
            ClaimStrength.PRESERVED_MAPPING_REFERENCE,
            ClaimStrength.DERIVED_MAPPING_REFERENCE,
        ):
            raise ContractValidationError("mapping source claim strength is forbidden")
        source_path = _material_path(root, rel, "mapping source")
        if sha256_file(source_path) != expected:
            raise ContractValidationError(f"mapping source hash mismatch: {rel}")
        entries = verified_manifests.get(manifest_rel)
        if entries is None or entries.get(entry_rel) != expected:
            raise ContractValidationError(f"mapping source is not bound by its manifest: {rel}")
        selected.append(
            ValidatedInput(
                source_id=source_id,
                schema=MAPPING_SCHEMA_VERSION,
                sha256=expected,
                logical_path=rel,
                validation_context=ValidationContext.OFFLINE_REPLAY,
                claim_strength=strength,
                limitations=(
                    "Mapping frequency is not physical evidence.",
                    "Historical or derived mapping cannot authorize odometry.",
                ),
            )
        )
        selected_categories.append((source_id, category))
    if source_ids != tuple(item.source_id for item in selected):
        raise ContractValidationError("source_ids and selected_sources disagree in order")
    if {category for _, category in selected_categories} != set(file_categories):
        raise ContractValidationError("every file category must have a selected source")
    map_artifacts = _exact_list(document.get("map_artifacts"), "map_artifacts")
    artifact_ids: set[str] = set()
    for artifact_value in map_artifacts:
        artifact = _exact_dict(artifact_value, "map_artifact")
        artifact_id = canonical_string(artifact.get("artifact_id"), "map_artifact.artifact_id")
        if artifact_id in artifact_ids:
            raise ContractValidationError("map artifact IDs must be unique")
        artifact_ids.add(artifact_id)
        artifact_category = canonical_string(artifact.get("category"), "map_artifact.category")
        if artifact_category not in file_categories:
            raise ContractValidationError("map artifact category is not declared")
        if artifact.get("navigation_map") is not False:
            raise ContractValidationError("mapping artifact cannot claim navigation-map status")
        if artifact.get("physical_frame_authority") is not False:
            raise ContractValidationError("mapping artifact cannot claim frame authority")
    manifest_digest = sha256_file(manifest_path)
    manifest_input = ValidatedInput(
        source_id="r2-p2a-mapping-evidence-manifest",
        schema=MAPPING_SCHEMA_VERSION,
        sha256=manifest_digest,
        logical_path="docs/Operaciones_HIL/Evidencia/R2_P2A_MAPPING_EVIDENCE_MANIFEST.json",
        validation_context=ValidationContext.OFFLINE_REPLAY,
        claim_strength=ClaimStrength.PRESERVED_MAPPING_REFERENCE,
        limitations=(
            "Sanitized manifest only; no raw mapping recording is embedded.",
            "Physical frame semantics and scale remain unresolved.",
        ),
    )
    configured = {"map", "odom", "base_link", "utlidar_lidar"}
    correlation = (
        "map->odom:POLICY_CANDIDATE_ONLY",
        "odom->base_link:UNRESOLVED_PHYSICAL_SEMANTICS",
        "base_link->utlidar_lidar:MEASUREMENT_NOT_BOUND",
    )
    if "utlidar_lidar" not in frame_ids or not configured:
        raise ContractValidationError("mapping frame inventory lacks required vocabulary")
    return MappingBinding(
        manifest_input=manifest_input,
        selected_inputs=tuple(selected),
        source_ids=source_ids,
        file_categories=file_categories,
        selected_source_categories=tuple(selected_categories),
        session_ids=session_ids,
        take_ids=take_ids,
        observed_frame_ids=frame_ids,
        observed_topic_ids=topic_ids,
        allowed_claims=allowed,
        prohibited_claims=prohibited,
        structural_correlation_policy=correlation,
    )


@dataclass(frozen=True, kw_only=True)
class P1AValidation:
    input_ref: ValidatedInput
    document_json: bytes
    stationary_ids: tuple[str, ...]
    preference_quarantined: bool
    authoritative_source_channel: None
    preferred_analysis_channel: None

    @property
    def document(self) -> dict[str, object]:
        value = json.loads(self.document_json.decode("utf-8"))
        if type(value) is not dict:
            raise ContractValidationError("P1A snapshot changed type")
        return value


def validate_p1a_document(
    document: Mapping[str, object],
    *,
    input_sha256: str,
    _same_byte_binding: bool = False,
) -> P1AValidation:
    if type(document) is not dict:
        raise ContractValidationError("P1A input must be an exact object")
    digest = sha256_string(input_sha256, "P1A input SHA-256")
    if document.get("schema_version") != P1A_SCHEMA_VERSION:
        raise ContractValidationError("P1A schema mismatch")
    p1_bundle = _exact_dict(document.get("p1_bundle"), "p1_bundle")
    if p1_bundle.get("schema_version") != P1A_SCHEMA_VERSION:
        raise ContractValidationError("embedded P1 bundle schema mismatch")
    findings = _exact_list(document.get("audit_findings"), "audit_findings")
    finding_ids = tuple(
        canonical_string(_exact_dict(item, "audit finding").get("hypothesis_id"), "hypothesis_id")
        for item in findings
    )
    if finding_ids != EXPECTED_AUDIT_IDS:
        raise ContractValidationError("P1A findings must be exactly H1-H10 in order")
    arbitration = _exact_dict(document.get("arbitration_audit"), "arbitration_audit")
    if arbitration.get("authoritative_source_channel") is not None:
        raise ContractValidationError("P1A authoritative source channel must be null")
    preference = arbitration.get("preferred_analysis_channel")
    quarantined = False
    if preference is not None:
        if not _same_byte_binding or digest != KNOWN_P1A_SHA256 or preference != CHANNELS[1]:
            raise ContractValidationError("P1A preferred analysis channel must be null")
        quarantined = True
    stationary = _exact_list(p1_bundle.get("stationary"), "p1_bundle.stationary")
    if len(stationary) != 10:
        raise ContractValidationError("P1A stationary record set must contain exactly 10 records")
    stationary_ids: list[str] = []
    for record_value in stationary:
        record = _exact_dict(record_value, "stationary record")
        if record.get("schema_version") != P1A_SCHEMA_VERSION:
            raise ContractValidationError("stationary record schema mismatch")
        evidence_id = canonical_string(record.get("evidence_id"), "stationary.evidence_id")
        stationary_ids.append(evidence_id)
        channel = canonical_string(record.get("channel"), "stationary.channel")
        if channel not in CHANNELS:
            raise ContractValidationError("unknown stationary channel")
        canonical_string(record.get("session_id"), "stationary.session_id")
        canonical_string(record.get("phase"), "stationary.phase")
        positive_int(record.get("sample_count"), "stationary.sample_count")
        finite_number(record.get("duration_s"), "stationary.duration_s", positive=True)
        for vector_name in ("stddev", "mad", "p95_deviation"):
            vector = _numeric_vector(record.get(vector_name), f"stationary.{vector_name}")
            if any(value < 0.0 for value in vector):
                raise ContractValidationError(f"stationary.{vector_name} must be non-negative")
    if len(set(stationary_ids)) != len(stationary_ids):
        raise ContractValidationError("stationary evidence IDs must be unique")
    residuals = _exact_list(p1_bundle.get("dynamic_residuals"), "dynamic_residuals")
    residual_ids: list[str] = []
    for record_value in residuals:
        record = _exact_dict(record_value, "dynamic residual")
        residual_ids.append(canonical_string(record.get("evidence_id"), "residual.evidence_id"))
        canonical_string(record.get("session_id"), "residual.session_id")
        canonical_string(record.get("segment_name"), "residual.segment_name")
        canonical_string(record.get("status"), "residual.status")
        channel = canonical_string(record.get("channel"), "residual.channel")
        residual_type = canonical_string(record.get("residual_type"), "residual.residual_type")
        if channel not in CHANNELS + ("BOTH",):
            raise ContractValidationError("unknown residual channel")
        if residual_type not in ("CROSS_CHANNEL", "INTERNAL_CONSISTENCY"):
            raise ContractValidationError("unknown residual type")
        positive_int(record.get("sample_count"), "residual.sample_count")
        finite_number(record.get("residual_value"), "residual.residual_value", nonnegative=True)
        canonical_string(record.get("unit"), "residual.unit")
    if len(residual_ids) != len(set(residual_ids)):
        raise ContractValidationError("dynamic residual evidence IDs must be unique")
    yaw_records = _exact_list(document.get("yaw_speed_residuals"), "yaw_speed_residuals")
    yaw_ids: list[str] = []
    for record_value in yaw_records:
        record = _exact_dict(record_value, "yaw residual")
        yaw_ids.append(canonical_string(record.get("evidence_id"), "yaw.evidence_id"))
        canonical_string(record.get("session_id"), "yaw.session_id")
        canonical_string(record.get("phase"), "yaw.phase")
        canonical_string(record.get("status"), "yaw.status")
        positive_int(record.get("sample_count"), "yaw.sample_count")
        finite_number(
            record.get("yaw_speed_rmse_rad_s"),
            "yaw.yaw_speed_rmse_rad_s",
            nonnegative=True,
        )
    if len(yaw_ids) != len(set(yaw_ids)):
        raise ContractValidationError("yaw residual evidence IDs must be unique")
    boot_records = _exact_list(document.get("boot_relation_evidence"), "boot_relation_evidence")
    if not boot_records:
        raise ContractValidationError("P1A boot relation evidence is required")
    for record_value in boot_records:
        record = _exact_dict(record_value, "boot relation")
        if record.get("continuous_capture") is not False:
            raise ContractValidationError("cross-session continuous capture is forbidden")
        if record.get("continuous_trajectory_permitted") is not False:
            raise ContractValidationError("cross-boot trajectory concatenation is forbidden")
        if record.get("same_time_domain") is not False:
            raise ContractValidationError("P1A cannot assert a shared time domain")
    input_ref = ValidatedInput(
        source_id="r2-p1a-result",
        schema=P1A_SCHEMA_VERSION,
        sha256=digest,
        logical_path="external/R2_P1A_RESULT.json",
        validation_context=ValidationContext.PHYSICAL_EVIDENCE,
        claim_strength=ClaimStrength.PRESERVED_PHYSICAL_EVIDENCE,
        limitations=(
            "The preserved LF analysis preference is quarantined and not authoritative."
            if quarantined
            else "No preferred or authoritative channel is selected.",
            "P1A does not resolve physical frame semantics or SI scale.",
        ),
    )
    try:
        document_json = (
            json.dumps(document, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)
            + "\n"
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ContractValidationError("P1A document cannot be snapshotted canonically") from exc
    return P1AValidation(
        input_ref=input_ref,
        document_json=document_json,
        stationary_ids=tuple(stationary_ids),
        preference_quarantined=quarantined,
        authoritative_source_channel=None,
        preferred_analysis_channel=None,
    )


def load_and_validate_p1a(path: Path) -> P1AValidation:
    try:
        payload = path.read_bytes()
        document = json.loads(payload.decode("utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ContractValidationError("p1a-input is not valid JSON") from exc
    if type(document) is not dict:
        raise ContractValidationError("P1A input must be an exact object")
    return validate_p1a_document(
        document,
        input_sha256=hashlib.sha256(payload).hexdigest(),
        _same_byte_binding=True,
    )
