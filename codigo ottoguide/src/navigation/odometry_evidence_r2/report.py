"""Deterministic JSON serialization for ODOM/TF R2-P0 evidence.

No wall-clock reads, no random ordering: every dict is dumped with
sort_keys=True so two runs over identical inputs (including the same
injected generated_utc) produce byte-identical output.
"""
import dataclasses
import json

from .models import PhysicalEvidenceBundleR2


def to_jsonable(obj):
    """Recursively convert frozen dataclasses (and their tuple/list/dict
    fields) into plain JSON-serializable structures. Tuples become lists;
    everything else is dataclasses.asdict's own recursive behavior."""
    if dataclasses.is_dataclass(obj) and not isinstance(obj, type):
        return dataclasses.asdict(obj)
    if isinstance(obj, (tuple, list)):
        return [to_jsonable(v) for v in obj]
    if isinstance(obj, dict):
        return {k: to_jsonable(v) for k, v in obj.items()}
    return obj


def dumps_deterministic(data) -> str:
    return json.dumps(to_jsonable(data), sort_keys=True, indent=2, ensure_ascii=True) + "\n"


def bundle_document(bundle: PhysicalEvidenceBundleR2) -> str:
    return dumps_deterministic(bundle)


def claims_document(bundle: PhysicalEvidenceBundleR2) -> str:
    return dumps_deterministic({"schema_version": bundle.schema_version, "claims": bundle.claims})


def channel_comparison_document(bundle: PhysicalEvidenceBundleR2) -> str:
    return dumps_deterministic(bundle.channel_comparison)


def time_domain_document(bundle: PhysicalEvidenceBundleR2) -> str:
    return dumps_deterministic({
        "schema_version": bundle.schema_version,
        "time_domains": bundle.time_domains,
    })


def provenance_document(bundle: PhysicalEvidenceBundleR2) -> str:
    provenance_records = []
    for session in bundle.sessions:
        provenance_records.extend(session.provenance)
    return dumps_deterministic({
        "schema_version": bundle.schema_version,
        "provenance": tuple(provenance_records),
    })


def limitations_document(bundle: PhysicalEvidenceBundleR2) -> str:
    all_limitations = list(bundle.limitations)
    for session in bundle.sessions:
        all_limitations.extend(f"[{session.session_id}] {msg}" for msg in session.limitations)
    for segment in bundle.dynamic_segments:
        if segment.limitations:
            all_limitations.extend(f"[{segment.evidence_id}] {msg}" for msg in segment.limitations)
    return dumps_deterministic({
        "schema_version": bundle.schema_version,
        "limitations": all_limitations,
    })
