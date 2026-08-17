"""Orchestration + serialization for ODOM/TF R2-P1 (assembles all per-module
metrics into one OdometryCharacterizationBundleR2 and renders deterministic
JSON/CSV documents). No network, no wall-clock reads; `generated_utc` is
always the caller-injected string."""
import json
from pathlib import Path

from src.navigation.odometry_evidence_r2.ingest import (
    R3C_PRE_REBOOT_BOOT_SENTINEL,
    R4B_BOOT_SENTINEL_UNRESOLVED,
)
from src.navigation.odometry_evidence_r2.validation import EvidenceValidationError

from . import alignment, arbitration, channel_quality, imu, motion, segmentation, timebase
from .models import (
    CHARACTERIZATION_SCHEMA_VERSION,
    CharacterizationClaim,
    DynamicResidualStatistics,
    OdometryCharacterizationBundleR2,
)
from .sample_loader import parse_lowstate_topic_dir, parse_lowstate_topic_file, parse_odom_topic_dir, parse_odom_topic_file

PRIMARY = "rt/odommodestate"
SECONDARY = "rt/lf/odommodestate"

R3C_SESSION_ID = "hilroute-20260720T194910Z"
R4_SESSION_ID = "finalharvest-seated-20260720T205406Z"
R4B_SESSION_ID = "gt-r4b-20260720T213222Z"
R4_BOOT_ID = "fa361379-5a30-4da7-bad7-415d6ddc24dd"


def _load_json(path: Path) -> dict:
    with open(path, "r", encoding="utf-8-sig") as handle:
        return json.load(handle)


def _by_phase(samples):
    return segmentation.group_by_phase(samples)


class _RawReparseLedger:
    def __init__(self):
        self.file_hashes = {}
        self.parse_stats = {}

    def add(self, label: str, hashes: dict, stats: dict):
        self.file_hashes.update(hashes)
        self.parse_stats[label] = stats


def _process_r3c(harvest_root: Path, ledger: _RawReparseLedger):
    base = harvest_root / "01_route_raw" / "extracted" / f"run_{R3C_SESSION_ID}" / "recorder_data"
    primary, primary_stats, h1 = parse_odom_topic_dir(base / "odom", PRIMARY, harvest_root, R3C_SESSION_ID, R3C_PRE_REBOOT_BOOT_SENTINEL)
    secondary, secondary_stats, h2 = parse_odom_topic_dir(base / "lf_odom", SECONDARY, harvest_root, R3C_SESSION_ID, R3C_PRE_REBOOT_BOOT_SENTINEL)
    lowstate, lowstate_stats, h3 = parse_lowstate_topic_dir(base / "lowstate", harvest_root, R3C_SESSION_ID)
    ledger.add("r3c.primary", h1, primary_stats)
    ledger.add("r3c.secondary", h2, secondary_stats)
    ledger.add("r3c.lowstate", h3, lowstate_stats)

    primary_phase = _by_phase(primary)
    secondary_phase = _by_phase(secondary)
    lowstate_phase = _by_phase(lowstate)

    stationary = []
    for phase in segmentation.R3C_STATIONARY_PHASES:
        for channel, by_phase in ((PRIMARY, primary_phase), (SECONDARY, secondary_phase)):
            if by_phase.get(phase):
                stationary.append(motion.compute_stationary_window(
                    session_id=R3C_SESSION_ID, channel=channel, phase=phase, samples=by_phase[phase]))

    dynamic = []
    for channel, by_phase in ((PRIMARY, primary_phase), (SECONDARY, secondary_phase)):
        if by_phase.get("ROUTE_ACTIVE"):
            dynamic.append(motion.compute_motion_segment(
                session_id=R3C_SESSION_ID, segment_name="route_active", channel=channel,
                valid=True, ground_truth_constraint="NOT_AVAILABLE", samples=by_phase["ROUTE_ACTIVE"]))

    stationary_count = sum(len(primary_phase.get(p, ())) for p in segmentation.R3C_STATIONARY_PHASES)
    dynamic_count = len(primary_phase.get("ROUTE_ACTIVE", ()))
    quality = [
        channel_quality.compute_channel_quality(
            session_id=R3C_SESSION_ID, channel=PRIMARY, samples=primary,
            stationary_sample_count=stationary_count, dynamic_sample_count=dynamic_count,
            parse_stats=primary_stats),
    ]
    stationary_count_s = sum(len(secondary_phase.get(p, ())) for p in segmentation.R3C_STATIONARY_PHASES)
    dynamic_count_s = len(secondary_phase.get("ROUTE_ACTIVE", ()))
    quality.append(channel_quality.compute_channel_quality(
        session_id=R3C_SESSION_ID, channel=SECONDARY, samples=secondary,
        stationary_sample_count=stationary_count_s, dynamic_sample_count=dynamic_count_s,
        parse_stats=secondary_stats))

    align = []
    for phase in ("PRE_ROUTE_STATIONARY", "ROUTE_ACTIVE", "POST_ROUTE_STATIONARY"):
        a = alignment.compute_alignment(session_id=R3C_SESSION_ID, phase=phase,
                                         primary_samples=primary_phase.get(phase, ()),
                                         secondary_samples=secondary_phase.get(phase, ()))
        if a is not None:
            align.append(a)

    imu_metrics = []
    if primary_phase.get("ROUTE_ACTIVE") and lowstate_phase.get("ROUTE_ACTIVE"):
        m = imu.compute_imu_agreement(session_id=R3C_SESSION_ID, segment_name="route_active",
                                       odom_samples=primary_phase["ROUTE_ACTIVE"],
                                       lowstate_samples=lowstate_phase["ROUTE_ACTIVE"])
        if m is not None:
            imu_metrics.append(m)

    tb = timebase.compute_timebase(
        session_id=R3C_SESSION_ID, samples=primary,
        message_stamp_status="ABSENT_SOURCE_TIMESTAMP_NULL_IN_RECORDER",
        extra_limitations=(
            "no SSH RTT handshake exists for R3C (only R4/R4B captured one); "
            "receipt_utc reflects the remote clock's own non-authoritative epoch.",
        ))

    return dict(stationary=stationary, dynamic=dynamic, quality=quality, alignment=align,
                imu=imu_metrics, timebase=[tb] if tb else [], nominal_scale=[], nominal_yaw=[],
                primary_phase=primary_phase, secondary_phase=secondary_phase, lowstate_phase=lowstate_phase)


def _process_r4(harvest_root: Path, ledger: _RawReparseLedger):
    base = harvest_root / "02_postboot_stationary" / "extracted" / "postboot_stationary" / f"run_{R4_SESSION_ID}" / "recorder_data"
    primary, primary_stats, h1 = parse_odom_topic_dir(base / "odom", PRIMARY, harvest_root, R4_SESSION_ID, R4_BOOT_ID)
    secondary, secondary_stats, h2 = parse_odom_topic_dir(base / "lf_odom", SECONDARY, harvest_root, R4_SESSION_ID, R4_BOOT_ID)
    lowstate, lowstate_stats, h3 = parse_lowstate_topic_dir(base / "lowstate", harvest_root, R4_SESSION_ID)
    ledger.add("r4.primary", h1, primary_stats)
    ledger.add("r4.secondary", h2, secondary_stats)
    ledger.add("r4.lowstate", h3, lowstate_stats)

    stationary = []
    if primary:
        stationary.append(motion.compute_stationary_window(
            session_id=R4_SESSION_ID, channel=PRIMARY, phase="PRE_ROUTE_STATIONARY", samples=primary))
    if secondary:
        stationary.append(motion.compute_stationary_window(
            session_id=R4_SESSION_ID, channel=SECONDARY, phase="PRE_ROUTE_STATIONARY", samples=secondary))

    quality = []
    if primary:
        quality.append(channel_quality.compute_channel_quality(
            session_id=R4_SESSION_ID, channel=PRIMARY, samples=primary,
            stationary_sample_count=len(primary), dynamic_sample_count=0, parse_stats=primary_stats))
    if secondary:
        quality.append(channel_quality.compute_channel_quality(
            session_id=R4_SESSION_ID, channel=SECONDARY, samples=secondary,
            stationary_sample_count=len(secondary), dynamic_sample_count=0, parse_stats=secondary_stats))

    align = []
    a = alignment.compute_alignment(session_id=R4_SESSION_ID, phase="PRE_ROUTE_STATIONARY",
                                     primary_samples=primary, secondary_samples=secondary)
    if a is not None:
        align.append(a)

    imu_metrics = []
    if primary and lowstate:
        m = imu.compute_imu_agreement(session_id=R4_SESSION_ID, segment_name="postboot_stationary",
                                       odom_samples=primary, lowstate_samples=lowstate)
        if m is not None:
            imu_metrics.append(m)

    handshake_rtt = None
    utc_midpoint = None
    uncertainty = None
    try:
        tb_estimate = _load_json(harvest_root / "02_postboot_stationary" / "TIMEBASE_ESTIMATE.json")
        handshake_rtt = tb_estimate["median_round_trip_ns"] / 1e9
        utc_midpoint = tb_estimate["best_remote_minus_local_utc_midpoint_ns"] / 1e9
        uncertainty = (tb_estimate["median_round_trip_ns"] - tb_estimate["minimum_round_trip_ns"]) / 1e9
    except (OSError, KeyError):
        pass

    tb = timebase.compute_timebase(
        session_id=R4_SESSION_ID, samples=primary if primary else secondary,
        message_stamp_status="ABSENT_OR_ZERO_IN_SOURCE",
        handshake_rtt_s=handshake_rtt, utc_midpoint_estimate_s=utc_midpoint, offset_uncertainty_s=uncertainty,
        extra_limitations=(
            "remote_clock_is_authoritative_utc=false in the source handshake report; "
            "this is a best-effort estimate, never an authoritative ROS-time mapping.",
        ))

    return dict(stationary=stationary, dynamic=[], quality=quality, alignment=align,
                imu=imu_metrics, timebase=[tb] if tb else [], nominal_scale=[], nominal_yaw=[],
                primary_samples=primary, secondary_samples=secondary, lowstate_samples=lowstate)


def _process_r4b(harvest_root: Path, ledger: _RawReparseLedger):
    base = harvest_root / "10_r4b"
    primary, primary_stats, h1 = parse_odom_topic_file(base / "R4B_PRIMARY_ODOM_RAW.jsonl", PRIMARY, harvest_root, R4B_SESSION_ID, None)
    secondary, secondary_stats, h2 = parse_odom_topic_file(base / "R4B_SECONDARY_ODOM_RAW.jsonl", SECONDARY, harvest_root, R4B_SESSION_ID, None)
    lowstate, lowstate_stats, h3 = parse_lowstate_topic_file(base / "R4B_LOWSTATE_RAW.jsonl", harvest_root, R4B_SESSION_ID)
    ledger.add("r4b.primary", h1, primary_stats)
    ledger.add("r4b.secondary", h2, secondary_stats)
    ledger.add("r4b.lowstate", h3, lowstate_stats)

    primary_segments = segmentation.r4b_named_segments(primary)
    secondary_segments = {name: run for name, valid, gt, mt, run in segmentation.r4b_named_segments(secondary)}
    lowstate_by_phase = _by_phase(lowstate)

    dynamic = []
    nominal_scale = []
    nominal_yaw = []
    imu_metrics = []
    for segment_name, valid, gt_mode, _movement_type, primary_run in primary_segments:
        m_primary = motion.compute_motion_segment(
            session_id=R4B_SESSION_ID, segment_name=segment_name, channel=PRIMARY,
            valid=valid, ground_truth_constraint=gt_mode, samples=primary_run)
        dynamic.append(m_primary)

        if segment_name in secondary_segments:
            m_secondary = motion.compute_motion_segment(
                session_id=R4B_SESSION_ID, segment_name=segment_name, channel=SECONDARY,
                valid=valid, ground_truth_constraint=gt_mode, samples=secondary_segments[segment_name])
            dynamic.append(m_secondary)

        source_hashes = tuple(sorted(set(h1.values()) | set(h2.values())))
        scale_candidate = motion.compute_nominal_scale_candidate(
            segment_name=segment_name, motion_metrics=m_primary, source_sha256=source_hashes)
        if scale_candidate is not None:
            nominal_scale.append(scale_candidate)
        yaw_candidate = motion.compute_nominal_yaw_gain_candidate(
            segment_name=segment_name, motion_metrics=m_primary, source_sha256=source_hashes)
        if yaw_candidate is not None:
            nominal_yaw.append(yaw_candidate)

        matching_lowstate = [s for s in lowstate if primary_run[0].sequence <= s.sequence <= primary_run[-1].sequence]
        if matching_lowstate:
            imu_metric = imu.compute_imu_agreement(
                session_id=R4B_SESSION_ID, segment_name=segment_name,
                odom_samples=primary_run, lowstate_samples=tuple(matching_lowstate))
            if imu_metric is not None:
                imu_metrics.append(imu_metric)

    stationary = []
    for phase, run in segmentation.r4b_stationary_windows(primary).items():
        stationary.append(motion.compute_stationary_window(
            session_id=R4B_SESSION_ID, channel=PRIMARY, phase=phase, samples=run))
    for phase, run in segmentation.r4b_stationary_windows(secondary).items():
        stationary.append(motion.compute_stationary_window(
            session_id=R4B_SESSION_ID, channel=SECONDARY, phase=phase, samples=run))

    total_primary = len(primary)
    stationary_count = sum(len(r) for r in segmentation.r4b_stationary_windows(primary).values())
    dynamic_count = sum(len(run) for _n, _v, _g, _m, run in primary_segments)
    quality = [channel_quality.compute_channel_quality(
        session_id=R4B_SESSION_ID, channel=PRIMARY, samples=primary,
        stationary_sample_count=stationary_count, dynamic_sample_count=dynamic_count,
        parse_stats=primary_stats)]
    stationary_count_s = sum(len(r) for r in segmentation.r4b_stationary_windows(secondary).values())
    dynamic_count_s = sum(len(secondary_segments.get(n, ())) for n, _v, _g, _m, _r in primary_segments)
    quality.append(channel_quality.compute_channel_quality(
        session_id=R4B_SESSION_ID, channel=SECONDARY, samples=secondary,
        stationary_sample_count=stationary_count_s, dynamic_sample_count=dynamic_count_s,
        parse_stats=secondary_stats))

    align = []
    for segment_name, _valid, _gt, _mt, primary_run in primary_segments:
        if segment_name in secondary_segments:
            a = alignment.compute_alignment(session_id=R4B_SESSION_ID, phase=segment_name,
                                             primary_samples=primary_run,
                                             secondary_samples=secondary_segments[segment_name])
            if a is not None:
                align.append(a)

    handshake_rtt = utc_midpoint = uncertainty = None
    boot_relation_note = (
        "BOOT_RELATION_TO_R4 remains UNRESOLVED per checkpoint policy for the claims "
        "ledger; note for human review: R4B_TIMEBASE_ESTIMATE.json's own "
        f"remote_boot_ids=[{R4_BOOT_ID!r}] is identical to R4's ROBOT_BOOT_ID -- this "
        "is a new observation surfaced by P1's raw reparse (P0A never read this file), "
        "but is reported here as evidence for a human/P2 decision, not used to change "
        "the fixed BOOT_RELATION_TO_R4=UNRESOLVED claim in this checkpoint."
    )
    try:
        tb_estimate = _load_json(base / "R4B_TIMEBASE_ESTIMATE.json")
        handshake_rtt = tb_estimate["median_round_trip_ns"] / 1e9
        utc_midpoint = tb_estimate["best_remote_minus_local_utc_midpoint_ns"] / 1e9
        uncertainty = (tb_estimate["median_round_trip_ns"] - tb_estimate["minimum_round_trip_ns"]) / 1e9
    except (OSError, KeyError):
        boot_relation_note = (
            "BOOT_RELATION_TO_R4 remains UNRESOLVED: no direct evidence available."
        )

    tb = timebase.compute_timebase(
        session_id=R4B_SESSION_ID, samples=primary, message_stamp_status="ABSENT",
        handshake_rtt_s=handshake_rtt, utc_midpoint_estimate_s=utc_midpoint, offset_uncertainty_s=uncertainty,
        extra_limitations=(boot_relation_note,))

    return dict(stationary=stationary, dynamic=dynamic, quality=quality, alignment=align,
                imu=imu_metrics, timebase=[tb] if tb else [], nominal_scale=nominal_scale, nominal_yaw=nominal_yaw,
                primary_segments=primary_segments, secondary_segments=secondary_segments,
                lowstate_samples=lowstate, primary_samples=primary, secondary_samples=secondary)


def _dynamic_residuals(r3c, r4b) -> "tuple[DynamicResidualStatistics, ...]":
    residuals = []
    by_segment_channel = {}
    for m in r4b["dynamic"]:
        by_segment_channel.setdefault(m.segment_name, {})[m.channel] = m
    for segment_name, by_channel in by_segment_channel.items():
        p = by_channel.get(PRIMARY)
        s = by_channel.get(SECONDARY)
        if p is not None and s is not None:
            residual_value = abs(p.planar_displacement - s.planar_displacement)
            residuals.append(DynamicResidualStatistics(
                schema_version=CHARACTERIZATION_SCHEMA_VERSION,
                evidence_id=f"p1.residual.cross_channel.{segment_name}",
                session_id=R4B_SESSION_ID, segment_name=segment_name, channel="BOTH",
                residual_type="CROSS_CHANNEL", residual_value=residual_value, unit="meters",
                sample_count=min(p.sample_count, s.sample_count), status="VERIFIED",
                limitations=("difference between two non-authoritative candidate channels, "
                             "never presented as an absolute physical error.",),
            ))
    for m in r4b["dynamic"]:
        if m.valid and m.path_length_candidate is not None:
            residual_value = abs(m.path_length_candidate - m.planar_displacement)
            residuals.append(DynamicResidualStatistics(
                schema_version=CHARACTERIZATION_SCHEMA_VERSION,
                evidence_id=f"p1.residual.internal_consistency.{m.segment_name}.{m.channel.replace('/', '_')}",
                session_id=R4B_SESSION_ID, segment_name=m.segment_name, channel=m.channel,
                residual_type="INTERNAL_CONSISTENCY", residual_value=residual_value, unit="meters",
                sample_count=m.sample_count, status="VERIFIED",
                limitations=("mean-velocity*duration path-length candidate vs. straight-line "
                             "planar displacement of the same channel/segment; a large residual "
                             "indicates non-straight-line motion or velocity-field noise, not error "
                             "against any ground truth.",),
            ))
    return tuple(residuals)


def _claims(r3c, r4, r4b, arbitration_matrix) -> "tuple[CharacterizationClaim, ...]":
    return (
        CharacterizationClaim(claim_id="CHANNEL_QUALITY", status="VERIFIED",
            evidence_ids=tuple(q.evidence_id for q in r3c["quality"] + r4["quality"] + r4b["quality"]),
            reason="Sampling-rate/jitter/gap/dropout metrics computed directly from raw JSONL reparse "
                   "for both channels across all three sessions.", confidence="HIGH"),
        CharacterizationClaim(claim_id="PRIMARY_LF_ALIGNMENT",
            status="PARTIAL",
            evidence_ids=tuple(a.evidence_id for a in r3c["alignment"] + r4["alignment"] + r4b["alignment"]) or ("p1.alignment.none",),
            reason="Nearest-neighbor monotonic alignment computed per phase/segment; coverage and lag "
                   "candidates vary by session and are documented per-metric.", confidence="MEDIUM"),
        CharacterizationClaim(claim_id="CHANNEL_ARBITRATION", status="PARTIAL",
            evidence_ids=(arbitration_matrix.evidence_id,),
            reason="Quantitative criteria matrix computed; no authoritative channel selected by design.",
            confidence="MEDIUM"),
        CharacterizationClaim(claim_id="TRANSLATION_SCALE", status="UNRESOLVED",
            evidence_ids=tuple(c.evidence_id for c in r4b["nominal_scale"]) or ("p1.nominal_scale.none",),
            reason="Only best-effort operator-nominal-vs-observed ratios exist; no calibrated "
                   "instrument was available.", confidence="LOW"),
        CharacterizationClaim(claim_id="YAW_SCALE", status="UNRESOLVED",
            evidence_ids=tuple(c.evidence_id for c in r4b["nominal_yaw"]) or ("p1.nominal_yaw.none",),
            reason="Only best-effort operator-nominal-vs-observed yaw ratios exist; no calibrated "
                   "instrument was available.", confidence="LOW"),
        CharacterizationClaim(claim_id="TIMEBASE_ORDERING", status="PARTIAL",
            evidence_ids=tuple(t.evidence_id for t in r3c["timebase"] + r4["timebase"] + r4b["timebase"]),
            reason="receipt_monotonic ordering verified per-session; ROS_HEADER_STAMP_POLICY remains "
                   "UNRESOLVED throughout.", confidence="MEDIUM"),
        CharacterizationClaim(claim_id="IMU_CROSSCHECK", status="PARTIAL_QUANTIFIED",
            evidence_ids=tuple(m.evidence_id for m in r3c["imu"] + r4["imu"] + r4b["imu"]) or ("p1.imu.none",),
            reason="Sign-agreement between SportModeState yaw_speed and LowState gyroscope[2] "
                   "quantified per available segment; gyroscope units remain unresolved so no "
                   "magnitude/gain claim is made.", confidence="MEDIUM"),
    )


def build_characterization_bundle(harvest_root: Path, generated_utc: str) -> "tuple[OdometryCharacterizationBundleR2, dict]":
    bundle, hashes, _sessions = build_characterization_bundle_with_sessions(harvest_root, generated_utc)
    return bundle, hashes


def build_characterization_bundle_with_sessions(
        harvest_root: Path, generated_utc: str) -> "tuple[OdometryCharacterizationBundleR2, dict, dict]":
    """Same as build_characterization_bundle, plus the raw per-session
    phase/segment dicts (r3c/r4/r4b) for P1A's audit layer (SequenceSemantics,
    CausalLagCandidate, SegmentEligibility) -- P1's own behavior/output is
    completely unchanged; this is a strict additive superset."""
    if not generated_utc:
        raise EvidenceValidationError("generated_utc must be a non-empty injected string")

    ledger = _RawReparseLedger()
    r3c = _process_r3c(harvest_root, ledger)
    r4 = _process_r4(harvest_root, ledger)
    r4b = _process_r4b(harvest_root, ledger)

    all_quality = r3c["quality"] + r4["quality"] + r4b["quality"]
    primary_records = [q for q in all_quality if q.channel == PRIMARY]
    secondary_records = [q for q in all_quality if q.channel == SECONDARY]
    # H2 fix: aggregate ALL sessions per channel, not just the first match.
    matrix = arbitration.build_arbitration_matrix(
        primary_records=primary_records, secondary_records=secondary_records,
        imu_agreement_count=len(r3c["imu"] + r4["imu"] + r4b["imu"]),
        reset_behavior_status="PARTIAL", provenance_quality_status="PASS")

    residuals = _dynamic_residuals(r3c, r4b)
    claims = _claims(r3c, r4, r4b, matrix)

    bundle = OdometryCharacterizationBundleR2(
        schema_version=CHARACTERIZATION_SCHEMA_VERSION,
        generated_utc_injected=generated_utc,
        channel_quality=tuple(r3c["quality"] + r4["quality"] + r4b["quality"]),
        alignment=tuple(r3c["alignment"] + r4["alignment"] + r4b["alignment"]),
        stationary=tuple(r3c["stationary"] + r4["stationary"] + r4b["stationary"]),
        motion=tuple(r3c["dynamic"] + r4["dynamic"] + r4b["dynamic"]),
        imu=tuple(r3c["imu"] + r4["imu"] + r4b["imu"]),
        timebase=tuple(r3c["timebase"] + r4["timebase"] + r4b["timebase"]),
        nominal_scale=tuple(r4b["nominal_scale"]),
        nominal_yaw=tuple(r4b["nominal_yaw"]),
        arbitration=matrix,
        dynamic_residuals=residuals,
        claims=claims,
        limitations=(
            "P1 does not select an authoritative source channel, does not resolve "
            "translation/yaw scale, does not resolve child_frame_id, and does not "
            "produce a publication-ready covariance model. ODOM_PUBLICATION_READY=false, "
            "TF_TO_BASE_LINK_READY=false, NAV2_READY=false remain unchanged from P0A.",
        ),
    )
    return bundle, ledger.file_hashes, {"r3c": r3c, "r4": r4, "r4b": r4b}


def _to_dict(obj):
    if hasattr(obj, "__dataclass_fields__"):
        return {k: _to_dict(getattr(obj, k)) for k in obj.__dataclass_fields__}
    if isinstance(obj, (tuple, list)):
        return [_to_dict(v) for v in obj]
    return obj


def bundle_document(bundle: OdometryCharacterizationBundleR2) -> str:
    return json.dumps(_to_dict(bundle), indent=2, sort_keys=True) + "\n"


def claims_document(bundle: OdometryCharacterizationBundleR2) -> str:
    return json.dumps([_to_dict(c) for c in bundle.claims], indent=2, sort_keys=True) + "\n"


def channel_quality_document(bundle: OdometryCharacterizationBundleR2) -> str:
    return json.dumps([_to_dict(q) for q in bundle.channel_quality], indent=2, sort_keys=True) + "\n"


def channel_quality_csv(bundle: OdometryCharacterizationBundleR2) -> str:
    header = "session_id,channel,sample_count,duration_s,mean_rate_hz,median_rate_hz,jitter_mad_ms,gap_count,dropout_count,duplicate_sequences,monotonic_inversions,status\n"
    rows = [header]
    for q in bundle.channel_quality:
        rows.append(f"{q.session_id},{q.channel},{q.sample_count},{q.duration_s:.6f},{q.mean_rate_hz:.6f},"
                     f"{q.median_rate_hz:.6f},{q.jitter_mad_ms:.6f},{q.gap_count},{q.dropout_count},"
                     f"{q.duplicate_sequences},{q.monotonic_inversions},{q.status}\n")
    return "".join(rows)


def alignment_document(bundle: OdometryCharacterizationBundleR2) -> str:
    return json.dumps([_to_dict(a) for a in bundle.alignment], indent=2, sort_keys=True) + "\n"


def alignment_csv(bundle: OdometryCharacterizationBundleR2) -> str:
    header = ("session_id,phase,paired_sample_count,pairing_coverage,lag_candidate_ms,lag_status,"
              "position_rmse,yaw_speed_rmse_rad_s,status\n")
    rows = [header]
    for a in bundle.alignment:
        rows.append(f"{a.session_id},{a.phase},{a.paired_sample_count},{a.pairing_coverage:.6f},"
                     f"{a.lag_candidate_ms if a.lag_candidate_ms is not None else ''},{a.lag_status},"
                     f"{a.position_rmse if a.position_rmse is not None else ''},"
                     f"{a.yaw_speed_rmse_rad_s if a.yaw_speed_rmse_rad_s is not None else ''},{a.status}\n")
    return "".join(rows)


def stationary_document(bundle: OdometryCharacterizationBundleR2) -> str:
    return json.dumps([_to_dict(s) for s in bundle.stationary], indent=2, sort_keys=True) + "\n"


def motion_document(bundle: OdometryCharacterizationBundleR2) -> str:
    return json.dumps([_to_dict(m) for m in bundle.motion], indent=2, sort_keys=True) + "\n"


def motion_csv(bundle: OdometryCharacterizationBundleR2) -> str:
    header = "session_id,segment_name,channel,valid,planar_displacement,dominant_axis,integrated_yaw_speed_rad,sample_count,status\n"
    rows = [header]
    for m in bundle.motion:
        rows.append(f"{m.session_id},{m.segment_name},{m.channel},{m.valid},{m.planar_displacement:.6f},"
                     f"{m.dominant_axis},{m.integrated_yaw_speed_rad if m.integrated_yaw_speed_rad is not None else ''},"
                     f"{m.sample_count},{m.status}\n")
    return "".join(rows)


def imu_document(bundle: OdometryCharacterizationBundleR2) -> str:
    return json.dumps([_to_dict(m) for m in bundle.imu], indent=2, sort_keys=True) + "\n"


def timebase_document(bundle: OdometryCharacterizationBundleR2) -> str:
    return json.dumps([_to_dict(t) for t in bundle.timebase], indent=2, sort_keys=True) + "\n"


def arbitration_document(bundle: OdometryCharacterizationBundleR2) -> str:
    return json.dumps(_to_dict(bundle.arbitration), indent=2, sort_keys=True) + "\n"


def dynamic_residuals_document(bundle: OdometryCharacterizationBundleR2) -> str:
    return json.dumps([_to_dict(r) for r in bundle.dynamic_residuals], indent=2, sort_keys=True) + "\n"


def nominal_candidates_document(bundle: OdometryCharacterizationBundleR2) -> str:
    return json.dumps({
        "nominal_scale": [_to_dict(c) for c in bundle.nominal_scale],
        "nominal_yaw": [_to_dict(c) for c in bundle.nominal_yaw],
    }, indent=2, sort_keys=True) + "\n"
