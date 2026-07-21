"""MVP-ODOM-TF-R2-P1A -- orchestration for the quantitative audit and
claim-hardening layer on top of P1's characterization bundle.

Builds the P1 bundle unchanged (via report.build_characterization_bundle_
with_sessions, itself unmodified in behavior except the H2 arbitration
aggregation fix inside arbitration.py/report.py), then layers the P1A-only
corrected/hardened evidence on top: SequenceSemantics, DropoutDetectionPolicy,
PairingTimeOffsetMetrics, CausalLagCandidate, Yaw{Angle,Speed}ResidualMetrics,
SegmentEligibility, the corrected ArbitrationDecisionAudit, BootRelationEvidence,
the 10 P1AuditFinding records (H1-H10), and the P1A claims ledger.
"""
import json
from pathlib import Path

from . import arbitration, boot_relation, causal_lag, dropout_semantics, report, segment_eligibility
from .models import (
    CHARACTERIZATION_SCHEMA_VERSION,
    CharacterizationClaim,
    P1ACharacterizationBundle,
    P1AuditFinding,
    YawAngleResidualMetrics,
    YawSpeedResidualMetrics,
)

PRIMARY = "rt/odommodestate"
SECONDARY = "rt/lf/odommodestate"


def _yaw_residuals(alignment_records):
    angle = []
    speed = []
    for a in alignment_records:
        angle.append(YawAngleResidualMetrics(
            schema_version=CHARACTERIZATION_SCHEMA_VERSION,
            evidence_id=f"p1a.yaw_angle_residual.{a.session_id}.{a.phase}",
            session_id=a.session_id, phase=a.phase, yaw_angle_rmse_rad=None,
            status="NOT_AVAILABLE",
            limitations=(
                "no orientation/quaternion field exists in the recorder's odom/lf_odom "
                "stream, and no pose-yaw-angle was derived from position deltas at P1/"
                "P1A; a yaw ANGLE residual cannot be computed (H5).",
            ),
        ))
        speed.append(YawSpeedResidualMetrics(
            schema_version=CHARACTERIZATION_SCHEMA_VERSION,
            evidence_id=f"p1a.yaw_speed_residual.{a.session_id}.{a.phase}",
            session_id=a.session_id, phase=a.phase,
            yaw_speed_rmse_rad_s=a.yaw_speed_rmse_rad_s,
            yaw_speed_mae_rad_s=a.yaw_speed_mae_rad_s,
            sample_count=a.paired_sample_count,
            status=a.status,
            limitations=(
                "renamed from P1's ambiguous 'yaw_rmse' (H5): this is the RMS residual "
                "of instantaneous SportModeState yaw_speed (rad/s) between primary and "
                "LF at paired samples, never an angle.",
            ),
        ))
    return tuple(angle), tuple(speed)


def _pairing_offsets(alignment_records):
    from .models import PairingTimeOffsetMetrics
    out = []
    for a in alignment_records:
        out.append(PairingTimeOffsetMetrics(
            schema_version=CHARACTERIZATION_SCHEMA_VERSION,
            evidence_id=f"p1a.pairing_offset.{a.session_id}.{a.phase}",
            session_id=a.session_id, phase=a.phase,
            paired_sample_count=a.paired_sample_count,
            time_offset_median_s=a.time_offset_median_s,
            time_offset_p95_s=a.time_offset_p95_s,
            status="VERIFIED" if a.paired_sample_count > 0 else "UNRESOLVED",
            limitations=(
                "pure descriptive nearest-neighbor pairing-time offset; NOT a causal-lag "
                "claim (H4) -- see the corresponding CausalLagCandidate record.",
            ),
        ))
    return tuple(out)


def _causal_lag_candidates(r3c, r4, r4b):
    candidates = []

    def scan(session_id, phase, primary_run, secondary_run):
        if not primary_run or not secondary_run:
            return
        primary_times = [s.receipt_monotonic_ns / 1e9 for s in primary_run]
        primary_yaw = [s.yaw_speed for s in primary_run]
        secondary_times = [s.receipt_monotonic_ns / 1e9 for s in secondary_run]
        secondary_yaw = [s.yaw_speed for s in secondary_run]
        candidates.append(causal_lag.scan_causal_lag(
            session_id=session_id, phase=phase,
            primary_times=primary_times, primary_yaw_speed=primary_yaw,
            secondary_times=secondary_times, secondary_yaw_speed=secondary_yaw,
        ))

    r3c_primary_phase = r3c["primary_phase"]
    r3c_secondary_phase = r3c["secondary_phase"]
    for phase in ("PRE_ROUTE_STATIONARY", "ROUTE_ACTIVE", "POST_ROUTE_STATIONARY"):
        scan(report.R3C_SESSION_ID, phase, r3c_primary_phase.get(phase), r3c_secondary_phase.get(phase))

    scan(report.R4_SESSION_ID, "PRE_ROUTE_STATIONARY", r4.get("primary_samples"), r4.get("secondary_samples"))

    secondary_segments = r4b["secondary_segments"]
    for segment_name, _valid, _gt, _mt, primary_run in r4b["primary_segments"]:
        if segment_name in secondary_segments:
            scan(report.R4B_SESSION_ID, segment_name, primary_run, secondary_segments[segment_name])

    return tuple(candidates)


def _segment_eligibility_records(r3c, r4b):
    records = [segment_eligibility.r3c_route_active_eligibility(report.R3C_SESSION_ID)]
    for phase in ("PRE_ROUTE_STATIONARY", "POST_ROUTE_STATIONARY"):
        records.append(segment_eligibility.stationary_eligibility(report.R3C_SESSION_ID, phase))
    records.append(segment_eligibility.stationary_eligibility(report.R4_SESSION_ID, "PRE_ROUTE_STATIONARY"))
    for segment_name, _valid, _gt, _mt, _run in r4b["primary_segments"]:
        records.append(segment_eligibility.r4b_segment_eligibility(report.R4B_SESSION_ID, segment_name))
    for phase in ("R4B_STANDING_BASELINE", "R4B_FINAL_STATIONARY"):
        records.append(segment_eligibility.stationary_eligibility(report.R4B_SESSION_ID, phase))
    return tuple(records)


def _audit_findings(bundle, boot_relation_evidence, arbitration_audit) -> tuple:
    return (
        P1AuditFinding(
            hypothesis_id="H1", title="Incorrect canonical GitHub slug",
            classification="REPRODUCED",
            evidence=(
                "P1's own context files recorded CANONICAL_REPOSITORY with a hyphen "
                "(tsamaan/OttoGuide-Proyecto-SIP-Grupo6-UADE), copied verbatim from that "
                "checkpoint's prompt; git ls-remote against that slug failed ('Repository "
                "not found').",
                "The corrected slug (tsamaan/OttoGuide-Proyecto_SIP-Grupo6-UADE, underscore) "
                "is reachable and its review/orchestrator-unification branch = "
                "97297169eebf5f6a786033f54ee533d4757eb580, exactly matching CANONICAL_REVIEW_SHA.",
            ),
            fix_applied="P1A's own context/report files use the corrected underscored slug; "
                        "P1's historical report is left untouched per section 24.",
            limitations=("no GitHub write of any kind was performed to reach this conclusion.",),
        ),
        P1AuditFinding(
            hypothesis_id="H2", title="Arbitration contradiction (primary preferred despite worse gaps/dropouts)",
            classification="REPRODUCED",
            evidence=(
                "P1's own final chat report claimed 'primary edges out on rate/jitter/gaps/"
                "dropouts', but primary has MORE gaps and MORE dropouts than LF in all 3 "
                "sessions (worse, not better).",
                "Root cause: report.py's arbitration call used `next(...)` to grab only the "
                "FIRST matching ChannelQualityMetrics per channel (R3C only), never "
                "aggregating across all 3 sessions.",
            ),
            fix_applied="arbitration.py now aggregates every session's ChannelQualityMetrics "
                        f"per channel before scoring; only jitter/gaps/dropouts are weighted "
                        f"(data_completeness/sample_rate excluded per section 10). Recomputed "
                        f"preferred_analysis_channel = {bundle.arbitration.preferred_analysis_channel!r}.",
            limitations=(),
        ),
        P1AuditFinding(
            hypothesis_id="H3", title="Sequence semantics and dropout definition",
            classification="REPRODUCED",
            evidence=(
                "Raw reparse deltas (2,5,10,15,19,22,25,...) confirm `sequence` is a single "
                "counter shared across every recorder topic, not per-channel.",
                "P1's dropout_count was purely sequence-derived, conflating this shared-"
                "counter effect with genuine per-channel sample loss.",
            ),
            fix_applied="Added SequenceSemantics (GLOBAL_ACROSS_ALL_TOPICS, VERIFIED) and "
                        "DropoutDetectionPolicy promoting time-based gap_count to the primary "
                        "signal, relabeling the sequence-based estimate as an auxiliary "
                        "channel_local_sequence_gap_estimate.",
            limitations=("no explicit recorder loss marker was found in the raw JSONL/schema.",),
        ),
        P1AuditFinding(
            hypothesis_id="H4", title="Lag candidate vs. pairing offset conflation",
            classification="REPRODUCED",
            evidence=(
                "P1's lag_candidate_ms was a bare nearest-neighbor pairing-offset median with "
                "correlation/coverage thresholds but no actual multi-lag cross-correlation and "
                "no explicit rejection of 2:1 sample-rate aliasing (primary ~40Hz vs LF ~20Hz).",
            ),
            fix_applied="Added PairingTimeOffsetMetrics (kept, descriptive) and CausalLagCandidate "
                        "(new, runs a real +/-100ms cross-correlation scan and checks for aliasing "
                        "near the ~50ms LF period); CausalLagCandidate.status is pinned to "
                        "UNRESOLVED by the model itself, matching section 21's claims enumeration.",
            limitations=("no bootstrap/repeatability stability check was run this checkpoint.",),
        ),
        P1AuditFinding(
            hypothesis_id="H5", title="Ambiguous yaw_rmse unit",
            classification="REPRODUCED",
            evidence=(
                "P1's 'yaw_rmse'/'yaw_mae' fields were yaw_SPEED (rad/s) residuals but were "
                "never named as such; no yaw ANGLE residual existed at all.",
            ),
            fix_applied="Renamed to yaw_speed_rmse_rad_s/yaw_speed_mae_rad_s in "
                        "ChannelAlignmentMetrics; added YawSpeedResidualMetrics (the real "
                        "computed metric) and YawAngleResidualMetrics (structurally pinned to "
                        "NOT_AVAILABLE -- no orientation data exists).",
            limitations=(),
        ),
        P1AuditFinding(
            hypothesis_id="H6", title="Arbitration criterion count mismatch (7 reported vs 9 serialized)",
            classification="REPRODUCED",
            evidence=("P1's own chat summary said '7 criteria' while the arbitration matrix "
                       "actually serializes 9 named criteria.",),
            fix_applied=f"ArbitrationDecisionAudit.criterion_count is now structurally enforced "
                        f"to equal len(criteria) in the model's __post_init__; this checkpoint's "
                        f"matrix has criterion_count={arbitration_audit.criterion_count}.",
            limitations=(),
        ),
        P1AuditFinding(
            hypothesis_id="H7", title="Invalid segments used without explicit eligibility",
            classification="PARTIAL",
            evidence=(
                "Nominal scale/yaw-gain candidates already correctly excluded invalid segments "
                "(motion.py checks `.valid`).",
                "Alignment and IMU cross-check were computed over invalid R4B segments "
                "(left_90_return_invalidated, forward_x_setup_not_executed) without an "
                "explicit eligibility label.",
            ),
            fix_applied="Added SegmentEligibility per segment (valid_for_channel_alignment=True, "
                        "valid_for_ground_truth=False, valid_for_translation_scale=False, "
                        "valid_for_yaw_gain=False for the two invalid segments) so descriptive "
                        "use is explicit and ground-truth misuse is structurally blocked.",
            limitations=(),
        ),
        P1AuditFinding(
            hypothesis_id="H8", title="R4B/R4 boot relation textual-similarity risk",
            classification="REPRODUCED" if boot_relation_evidence.same_boot_verified else "PARTIAL",
            evidence=(
                f"R4B_TIMEBASE_ESTIMATE.json sha256 matches its entry in "
                f"R4B_LOCAL_SHA256SUMS.txt (hash_verified={boot_relation_evidence.source_b_hash_verified}); "
                f"that file is part of the session's own R4B_LOCAL_HASH_VERIFICATION.json (PASS).",
                f"R4's ROBOT_BOOT_ID is pinned by the P0A descriptor.",
                f"boot_id_a={boot_relation_evidence.boot_id_a!r} == boot_id_b={boot_relation_evidence.boot_id_b!r}",
            ),
            fix_applied=f"BootRelationEvidence.same_boot_verified={boot_relation_evidence.same_boot_verified} "
                        "backed by an explicit hash-verification chain, not bare textual similarity. "
                        "continuous_trajectory_permitted is structurally forced False regardless.",
            limitations=("does not imply same time domain or continuous capture (section 20).",),
        ),
        P1AuditFinding(
            hypothesis_id="H9", title="Yaw variability across best-effort turn segments",
            classification="PARTIAL",
            evidence=(
                "Reproduced ratios: left_90_first=0.424, left_180_operator_corrected=0.919, "
                "left_90_valid_retry_local_baseline=0.684 (integrated SportModeState yaw_speed "
                "vs. operator-nominal yaw, rad).",
                "A pose-yaw-delta basis was never computed (no orientation data); an "
                "integrated-gyro-Z basis is not meaningful because gyroscope units remain "
                "UNRESOLVED (no rad/s or deg/s assumption is permitted).",
            ),
            fix_applied="Bases are now explicitly separated: integrated yaw_speed (rad, real), "
                        "operator nominal yaw (rad, real), segment sample coverage (real); "
                        "pose-yaw-delta and integrated-gyro-Z bases are reported as UNAVAILABLE "
                        "with an explicit reason rather than silently omitted.",
            limitations=("wide ratio spread most plausibly reflects unmeasured operator "
                         "under/over-rotation, not necessarily an odometry gain defect -- see "
                         "next-checkpoint plan.",),
        ),
        P1AuditFinding(
            hypothesis_id="H10", title="P0A parser reuse / bypass audit",
            classification="NOT_REPRODUCED",
            evidence=(
                "sample_loader.py imports source_manifest.py and validation.py from "
                "odometry_evidence_r2 unmodified; it does not import or call "
                "odometry_evidence_r2.ingest._parse_channel_jsonl_dir (P0A's private parser).",
                "P0A's own test suite (287 tests) passes unchanged after all P1A edits, "
                "confirming no P0A behavior was altered.",
            ),
            fix_applied="No fix needed; P1's design (new parsing code for a genuinely new "
                        "topic/full-record scope, reusing only the shared validation/manifest "
                        "layer) was confirmed sound, not a bypass.",
            limitations=(),
        ),
    )


def build_p1a_bundle(harvest_root: Path, generated_utc: str) -> "tuple[P1ACharacterizationBundle, dict]":
    bundle, hashes, sessions = report.build_characterization_bundle_with_sessions(harvest_root, generated_utc)
    r3c, r4, r4b = sessions["r3c"], sessions["r4"], sessions["r4b"]

    all_alignment = list(bundle.alignment)
    sequence_semantics = tuple(
        dropout_semantics.build_sequence_semantics(sid)
        for sid in (report.R3C_SESSION_ID, report.R4_SESSION_ID, report.R4B_SESSION_ID)
    )
    dropout_policy = dropout_semantics.build_dropout_detection_policy()
    pairing_offsets = _pairing_offsets(all_alignment)
    causal_candidates = _causal_lag_candidates(r3c, r4, r4b)
    yaw_angle, yaw_speed = _yaw_residuals(all_alignment)
    segment_records = _segment_eligibility_records(r3c, r4b)
    boot_evidence = (boot_relation.audit_r4b_boot_relation(harvest_root),)

    all_quality = list(bundle.channel_quality)
    primary_records = [q for q in all_quality if q.channel == PRIMARY]
    secondary_records = [q for q in all_quality if q.channel == SECONDARY]
    arbitration_audit = arbitration.build_arbitration_audit(
        primary_records=primary_records, secondary_records=secondary_records,
        imu_agreement_count=len(bundle.imu), reset_behavior_status="PARTIAL",
        provenance_quality_status="PASS")

    findings = _audit_findings(bundle, boot_evidence[0], arbitration_audit)

    claims = (
        CharacterizationClaim(claim_id="CHANNEL_QUALITY", status="VERIFIED",
            evidence_ids=tuple(q.evidence_id for q in bundle.channel_quality),
            reason="Unchanged from P1: sampling-rate/jitter metrics computed directly from raw "
                   "JSONL reparse.", confidence="HIGH"),
        CharacterizationClaim(claim_id="DROPOUT_CHARACTERIZATION", status="PARTIAL",
            evidence_ids=(dropout_policy.evidence_id,) + tuple(s.evidence_id for s in sequence_semantics),
            reason="Time-based gap detection promoted to the primary signal (H3); the sequence-"
                   "based estimate is relabeled auxiliary, not confirmed loss.", confidence="MEDIUM"),
        CharacterizationClaim(claim_id="PRIMARY_LF_ALIGNMENT", status="PARTIAL",
            evidence_ids=tuple(a.evidence_id for a in pairing_offsets) or ("p1a.pairing_offset.none",),
            reason="Nearest-neighbor pairing offset computed per phase/segment.", confidence="MEDIUM"),
        CharacterizationClaim(claim_id="PAIRING_TIME_OFFSET", status="SUPPORTED_INFERENCE",
            evidence_ids=tuple(a.evidence_id for a in pairing_offsets) or ("p1a.pairing_offset.none",),
            reason="Descriptive pairing-time offset, distinct from any causal-lag claim (H4).",
            confidence="MEDIUM"),
        CharacterizationClaim(claim_id="CAUSAL_CHANNEL_LAG", status="UNRESOLVED",
            evidence_ids=tuple(c.evidence_id for c in causal_candidates) or ("p1a.causal_lag.none",),
            reason="Cross-correlation scan performed (H4) but no bootstrap/repeatability "
                   "confirmation protocol was run; remains UNRESOLVED per section 21.",
            confidence="LOW"),
        CharacterizationClaim(claim_id="CHANNEL_ARBITRATION", status="PARTIAL",
            evidence_ids=(arbitration_audit.evidence_id,),
            reason="Corrected, fully-aggregated criteria matrix (H2/H6); no authoritative "
                   "channel selected by design.", confidence="MEDIUM"),
        CharacterizationClaim(claim_id="PREFERRED_ANALYSIS_CHANNEL",
            status="SUPPORTED_INFERENCE" if arbitration_audit.preferred_analysis_channel else "UNRESOLVED",
            evidence_ids=(arbitration_audit.evidence_id,),
            reason=f"Corrected weighted decision (H2): preferred_analysis_channel="
                   f"{arbitration_audit.preferred_analysis_channel!r}.", confidence="MEDIUM"),
        CharacterizationClaim(claim_id="AUTHORITATIVE_SOURCE_CHANNEL", status="UNRESOLVED",
            evidence_ids=(arbitration_audit.evidence_id,),
            reason="Channel selection remains out of scope through at least P2.", confidence="HIGH"),
        CharacterizationClaim(claim_id="YAW_ANGLE_RESIDUAL", status="UNRESOLVED",
            evidence_ids=tuple(y.evidence_id for y in yaw_angle) or ("p1a.yaw_angle_residual.none",),
            reason="No orientation data exists in the recorder stream; never computed (H5).",
            confidence="HIGH"),
        CharacterizationClaim(claim_id="YAW_SPEED_RESIDUAL", status="VERIFIED",
            evidence_ids=tuple(y.evidence_id for y in yaw_speed) or ("p1a.yaw_speed_residual.none",),
            reason="Renamed and confirmed (H5): RMS residual of instantaneous yaw_speed between "
                   "primary and LF.", confidence="HIGH"),
        CharacterizationClaim(claim_id="TRANSLATION_SCALE", status="UNRESOLVED",
            evidence_ids=tuple(c.evidence_id for c in bundle.nominal_scale) or ("p1.nominal_scale.none",),
            reason="Unchanged from P1: only best-effort operator-nominal-vs-observed ratios exist.",
            confidence="LOW"),
        CharacterizationClaim(claim_id="YAW_SCALE", status="UNRESOLVED",
            evidence_ids=tuple(c.evidence_id for c in bundle.nominal_yaw) or ("p1.nominal_yaw.none",),
            reason="Unchanged from P1: wide ratio spread (H9), never resolved to a single scale.",
            confidence="LOW"),
        CharacterizationClaim(claim_id="IMU_CROSSCHECK", status="PARTIAL_QUANTIFIED",
            evidence_ids=tuple(m.evidence_id for m in bundle.imu) or ("p1.imu.none",),
            reason="Unchanged from P1: sign-agreement only, gyroscope units unresolved.",
            confidence="MEDIUM"),
        CharacterizationClaim(claim_id="R4B_BOOT_RELATION_TO_R4",
            status="VERIFIED" if boot_evidence[0].same_boot_verified else "UNRESOLVED",
            evidence_ids=(boot_evidence[0].evidence_id,),
            reason="H8: hash-verified boot_id match between R4B_TIMEBASE_ESTIMATE.json and R4's "
                   "P0A-pinned ROBOT_BOOT_ID; does not authorize trajectory/time-domain "
                   "concatenation.", confidence="HIGH" if boot_evidence[0].same_boot_verified else "LOW"),
        CharacterizationClaim(claim_id="SOURCE_FRAME_SEMANTICS", status="PARTIAL",
            evidence_ids=("p0a.r4b.lidar_extrinsic",), reason="Unchanged from P0A/P1.", confidence="LOW"),
        CharacterizationClaim(claim_id="CHILD_FRAME_ID", status="UNRESOLVED",
            evidence_ids=("p0a.r4b.lidar_extrinsic",), reason="Unchanged from P0A/P1.", confidence="LOW"),
        CharacterizationClaim(claim_id="ROS_HEADER_STAMP_POLICY", status="UNRESOLVED",
            evidence_ids=tuple(t.evidence_id for t in bundle.timebase),
            reason="Unchanged from P1.", confidence="HIGH"),
        CharacterizationClaim(claim_id="COVARIANCE_PUBLICATION_MODEL", status="UNRESOLVED",
            evidence_ids=("p0a.covariance",), reason="Unchanged from P0A/P1.", confidence="HIGH"),
    )

    p1a_bundle = P1ACharacterizationBundle(
        schema_version=CHARACTERIZATION_SCHEMA_VERSION,
        generated_utc_injected=generated_utc,
        p1_bundle=bundle,
        audit_findings=findings,
        sequence_semantics=sequence_semantics,
        dropout_policy=dropout_policy,
        pairing_offsets=pairing_offsets,
        causal_lag_candidates=causal_candidates,
        yaw_angle_residuals=yaw_angle,
        yaw_speed_residuals=yaw_speed,
        segment_eligibility=segment_records,
        arbitration_audit=arbitration_audit,
        boot_relation_evidence=boot_evidence,
        claims=claims,
        limitations=(
            "P1A audits and hardens P1's math/semantics/claims; it does not start P2, does "
            "not implement publishers, does not install ROS, and does not select an "
            "authoritative channel.",
        ),
    )
    return p1a_bundle, hashes


def _to_dict(obj):
    if hasattr(obj, "__dataclass_fields__"):
        return {k: _to_dict(getattr(obj, k)) for k in obj.__dataclass_fields__}
    if isinstance(obj, (tuple, list)):
        return [_to_dict(v) for v in obj]
    return obj


def result_document(bundle: P1ACharacterizationBundle) -> str:
    return json.dumps(_to_dict(bundle), indent=2, sort_keys=True) + "\n"


def audit_findings_document(bundle: P1ACharacterizationBundle) -> str:
    return json.dumps([_to_dict(f) for f in bundle.audit_findings], indent=2, sort_keys=True) + "\n"


def dropout_semantics_document(bundle: P1ACharacterizationBundle) -> str:
    return json.dumps({
        "sequence_semantics": [_to_dict(s) for s in bundle.sequence_semantics],
        "dropout_detection_policy": _to_dict(bundle.dropout_policy),
    }, indent=2, sort_keys=True) + "\n"


def channel_quality_corrected_document(bundle: P1ACharacterizationBundle) -> str:
    return json.dumps([_to_dict(q) for q in bundle.p1_bundle.channel_quality], indent=2, sort_keys=True) + "\n"


def channel_quality_corrected_csv(bundle: P1ACharacterizationBundle) -> str:
    header = ("session_id,channel,sample_count,duration_s,mean_rate_hz,time_gap_count,"
              "channel_local_sequence_gap_estimate,confirmed_dropout_count,status\n")
    rows = [header]
    for q in bundle.p1_bundle.channel_quality:
        classification = dropout_semantics.classify_channel_dropouts(
            time_gap_count=q.gap_count, sequence_gap_estimate=q.dropout_count)
        rows.append(f"{q.session_id},{q.channel},{q.sample_count},{q.duration_s:.6f},"
                     f"{q.mean_rate_hz:.6f},{classification['time_gap_count']},"
                     f"{classification['channel_local_sequence_gap_estimate']},"
                     f"{classification['confirmed_dropout_count']},{q.status}\n")
    return "".join(rows)


def pairing_offset_document(bundle: P1ACharacterizationBundle) -> str:
    return json.dumps([_to_dict(p) for p in bundle.pairing_offsets], indent=2, sort_keys=True) + "\n"


def causal_lag_document(bundle: P1ACharacterizationBundle) -> str:
    return json.dumps([_to_dict(c) for c in bundle.causal_lag_candidates], indent=2, sort_keys=True) + "\n"


def alignment_corrected_document(bundle: P1ACharacterizationBundle) -> str:
    return json.dumps([_to_dict(a) for a in bundle.p1_bundle.alignment], indent=2, sort_keys=True) + "\n"


def alignment_corrected_csv(bundle: P1ACharacterizationBundle) -> str:
    header = ("session_id,phase,paired_sample_count,pairing_coverage,position_rmse,"
              "yaw_speed_rmse_rad_s,status\n")
    rows = [header]
    for a in bundle.p1_bundle.alignment:
        rows.append(f"{a.session_id},{a.phase},{a.paired_sample_count},{a.pairing_coverage:.6f},"
                     f"{a.position_rmse if a.position_rmse is not None else ''},"
                     f"{a.yaw_speed_rmse_rad_s if a.yaw_speed_rmse_rad_s is not None else ''},{a.status}\n")
    return "".join(rows)


def yaw_metrics_audit_document(bundle: P1ACharacterizationBundle) -> str:
    return json.dumps({
        "yaw_angle_residuals": [_to_dict(y) for y in bundle.yaw_angle_residuals],
        "yaw_speed_residuals": [_to_dict(y) for y in bundle.yaw_speed_residuals],
    }, indent=2, sort_keys=True) + "\n"


def yaw_segment_comparison_csv(bundle: P1ACharacterizationBundle) -> str:
    header = "session_id,phase,yaw_angle_rmse_rad,yaw_speed_rmse_rad_s,sample_count,status\n"
    rows = [header]
    angle_by_key = {(y.session_id, y.phase): y for y in bundle.yaw_angle_residuals}
    for s in bundle.yaw_speed_residuals:
        angle = angle_by_key.get((s.session_id, s.phase))
        angle_value = angle.yaw_angle_rmse_rad if angle else ""
        rows.append(f"{s.session_id},{s.phase},{angle_value if angle_value is not None else ''},"
                     f"{s.yaw_speed_rmse_rad_s if s.yaw_speed_rmse_rad_s is not None else ''},"
                     f"{s.sample_count},{s.status}\n")
    return "".join(rows)


def segment_eligibility_document(bundle: P1ACharacterizationBundle) -> str:
    return json.dumps([_to_dict(s) for s in bundle.segment_eligibility], indent=2, sort_keys=True) + "\n"


def arbitration_audit_document(bundle: P1ACharacterizationBundle) -> str:
    return json.dumps(_to_dict(bundle.arbitration_audit), indent=2, sort_keys=True) + "\n"


def arbitration_matrix_corrected_document(bundle: P1ACharacterizationBundle) -> str:
    return json.dumps(_to_dict(bundle.p1_bundle.arbitration), indent=2, sort_keys=True) + "\n"


def boot_relation_audit_document(bundle: P1ACharacterizationBundle) -> str:
    return json.dumps([_to_dict(b) for b in bundle.boot_relation_evidence], indent=2, sort_keys=True) + "\n"


def claims_document(bundle: P1ACharacterizationBundle) -> str:
    return json.dumps([_to_dict(c) for c in bundle.claims], indent=2, sort_keys=True) + "\n"
