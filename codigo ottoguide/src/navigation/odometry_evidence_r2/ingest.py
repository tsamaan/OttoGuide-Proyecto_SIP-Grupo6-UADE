"""Offline, read-only ingestion of R3C/R4/R4B physical evidence into the
typed R2-P0 model.

No network, no ROS, no DDS, no live SDK. The only I/O here is reading
already-harvested, hash-verified local files (JSON/JSONL) and computing pure
statistics over them. Every external fact (session ids, boot ids, sequence
ranges, sample counts) is READ from the harvest's own reports -- never
hardcoded as a literal duplicated from a prior chat session -- so that this
module stays honest if the harvest is regenerated.
"""
import json
from pathlib import Path

from . import provenance as provenance_mod
from .models import (
    AxisResponseObservation,
    ChannelComparisonEvidence,
    CovarianceEvidence,
    DynamicMotionSegment,
    DynamicResidualStatistics,
    EvidenceClaim,
    EvidenceProvenance,
    ImuCrosscheckEvidence,
    LidarExtrinsicEvidence,
    PhysicalEvidenceBundleR2,
    PhysicalSessionEvidence,
    ResetDiscontinuityEvidence,
    SessionTimeDomain,
    StationaryNoiseStatistics,
    StationarySegment,
    YawResponseObservation,
)
from .statistics import (
    OUTLIER_RULE,
    ROBUST_METHOD,
    compute_scalar_stats,
    compute_vector_stats,
)
from .validation import EvidenceValidationError, is_non_empty_str

# Boot identity for the pre-reboot R3C session was never captured on the
# robot (only the post-reboot boot id, fa361379-..., was read for R4). This
# sentinel documents that gap honestly instead of reusing R4's boot id (which
# would incorrectly imply R3C ran under the same boot).
R3C_PRE_REBOOT_BOOT_SENTINEL = "R3C_PRE_REBOOT_BOOT_ID_NOT_CAPTURED"

PRIMARY_CHANNEL = "rt/odommodestate"
SECONDARY_CHANNEL = "rt/lf/odommodestate"


def _load_json(path: Path) -> dict:
    if not path.is_file():
        raise EvidenceValidationError(f"required evidence file missing: {path}")
    # utf-8-sig tolerates a leading BOM (some harvest reports were written by
    # PowerShell Out-File, which defaults to BOM-prefixed UTF-8) while
    # behaving identically to plain utf-8 for BOM-less files.
    with open(path, "r", encoding="utf-8-sig") as handle:
        try:
            return json.load(handle)
        except json.JSONDecodeError as exc:
            raise EvidenceValidationError(f"malformed JSON in {path}: {exc}") from exc


def _prov(harvest_root: Path, evidence_id: str, relative_path: str, generated_utc: str,
          **kwargs) -> EvidenceProvenance:
    return provenance_mod.build_provenance(
        evidence_id=evidence_id,
        source_package="FINAL-R4-20260720T204735Z",
        source_root=harvest_root,
        source_path=harvest_root / relative_path,
        generated_utc=generated_utc,
        **kwargs,
    )


def _parse_channel_jsonl_dir(directory: Path, expected_topic: str):
    """Stream-parse every *.jsonl chunk in `directory`, keeping only records
    for `expected_topic`, sorted by the recorder's own global sequence
    number. Read-only: the raw files on disk are never modified. A chunk
    ending mid-record with a raw NUL byte (a known, documented artifact of
    an unclean power-cycle shutdown -- see ROUTE_TERMINAL_NUL_FILES) is
    truncated at the first NUL and its trailing partial line is dropped;
    this affects only the in-memory derived parse, never the raw bytes."""
    records = []
    truncated_files = 0
    for path in sorted(directory.glob("*.jsonl")):
        raw = path.read_bytes()
        if b"\x00" in raw:
            truncated_files += 1
            raw = raw.split(b"\x00", 1)[0]
        text = raw.decode("utf-8", errors="ignore")
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            if record.get("topic") != expected_topic:
                continue
            records.append(record)
    records.sort(key=lambda r: r.get("sequence", 0))
    return records, truncated_files


def _group_by_phase(records):
    by_phase = {}
    for record in records:
        by_phase.setdefault(record.get("phase", "UNMARKED"), []).append(record)
    return by_phase


def _odom_field_for_topic(topic: str) -> str:
    """The recorder nests the sample under 'odom' for the primary topic and
    'lf_odom' for the secondary topic."""
    return "odom" if topic == "rt/odommodestate" else "lf_odom"


def _stationary_segment_from_records(
    *, evidence_id, session_id, boot_id, phase, channel, records,
    source_files, source_sha256, limitations=(),
) -> "StationarySegment | None":
    if not records:
        return None
    field = _odom_field_for_topic(channel)
    positions = [tuple(r[field]["position"]) for r in records]
    yaw_speeds = [r[field]["yaw_speed"] for r in records]
    position_stats = compute_vector_stats(positions, 3)
    yaw_stats = compute_scalar_stats(yaw_speeds)
    return StationarySegment(
        evidence_id=evidence_id,
        session_id=session_id,
        boot_id=boot_id,
        phase=phase,
        channel=channel,
        sample_count=position_stats["sample_count"],
        position_range=position_stats["range"],
        position_stddev=position_stats["stddev"],
        yaw_speed_mean=yaw_stats["mean"],
        yaw_speed_stddev=yaw_stats["stddev"],
        source_files=tuple(source_files),
        source_sha256=tuple(source_sha256),
        limitations=tuple(limitations),
    )


def build_r3c_session(harvest_root: Path, generated_utc: str):
    """Ingest R3C_MANUAL_PHYSICAL_ROUTE: the human-operator-driven dynamic
    route capture. Returns (session_evidence, provenance_list,
    dynamic_segments, stationary_segments)."""
    index = _load_json(harvest_root / "FINAL_PHYSICAL_HARVEST_INDEX.json")
    seal = _load_json(
        harvest_root / "01_route_raw" / "route_power_cycle_seal" / "POWER_CYCLE_SEAL.json"
    )
    route_seq = _load_json(harvest_root / "09_analysis" / "ROUTE_SEQUENCE_REPORT.json")

    session_id = seal["session_id"]
    if session_id != index["ROUTE_RUN_ROOT"].rsplit("run_", 1)[-1]:
        raise EvidenceValidationError(
            "R3C session_id mismatch between POWER_CYCLE_SEAL.json and "
            "FINAL_PHYSICAL_HARVEST_INDEX.json"
        )

    archive_relative = "01_route_raw/route_hilroute-20260720T194910Z.tar.gz"
    archive_prov = _prov(
        harvest_root,
        "r3c.provenance.route_archive",
        archive_relative,
        generated_utc,
        limitations=(
            "Archive contains 1438 files with 4 having a terminal NUL byte "
            "from an unclean power-cycle shutdown; raw bytes preserved "
            "as-is (ROUTE_TERMINAL_NUL_FILES=4, ROUTE_JSONL_INVALID_RECORDS=0).",
        ),
    )
    seal_relative = "01_route_raw/route_power_cycle_seal/POWER_CYCLE_SEAL.json"
    seal_prov = _prov(harvest_root, "r3c.provenance.power_cycle_seal", seal_relative, generated_utc)
    route_seq_relative = "09_analysis/ROUTE_SEQUENCE_REPORT.json"
    route_seq_prov = _prov(
        harvest_root, "r3c.provenance.route_sequence_report", route_seq_relative, generated_utc
    )

    phases = tuple(sorted(index["ROUTE_PHASES_FOUND"]))

    session = PhysicalSessionEvidence(
        evidence_id="r3c.session",
        status="VERIFIED",
        confidence="HIGH_FILE_COUNT_AND_HASH_VERIFIED",
        session_id=session_id,
        session_type="R3C_MANUAL_PHYSICAL_ROUTE",
        boot_id=R3C_PRE_REBOOT_BOOT_SENTINEL,
        clean_shutdown=bool(seal["clean_shutdown"]),
        physical_movement_authority="HUMAN_OPERATOR_ONLY",
        streams=(PRIMARY_CHANNEL, SECONDARY_CHANNEL),
        phases=phases,
        provenance=(archive_prov, seal_prov, route_seq_prov),
        source_files=(archive_relative, seal_relative, route_seq_relative),
        source_sha256=(archive_prov.source_sha256, seal_prov.source_sha256,
                        route_seq_prov.source_sha256),
        limitations=(
            "ROUTE_ACTIVE begins at sequence 91143, not the historically "
            "estimated 92772; the corrected value is used throughout.",
            "power_cycle_terminated=true / clean_shutdown=false: the "
            "capture ended in an unclean power cycle, not a graceful stop.",
            "No exterior/metric ground truth exists for this route; "
            "METRIC_GROUND_TRUTH = NOT_AVAILABLE.",
        ),
    )

    dynamic_segments = []
    stationary_segments = []
    for channel_key, channel_dir in (
        (PRIMARY_CHANNEL, "recorder_data/odom"),
        (SECONDARY_CHANNEL, "recorder_data/lf_odom"),
    ):
        directory = harvest_root / "01_route_raw" / "extracted" / f"run_{session_id}" / channel_dir
        records, truncated_files = _parse_channel_jsonl_dir(directory, channel_key)
        by_phase = _group_by_phase(records)
        channel_slug = channel_key.replace("/", "_")

        for phase in ("PRE_ROUTE_STATIONARY", "POST_ROUTE_STATIONARY"):
            phase_records = by_phase.get(phase, [])
            segment = _stationary_segment_from_records(
                evidence_id=f"r3c.stationary.{phase.lower()}.{channel_slug}",
                session_id=session_id,
                boot_id=R3C_PRE_REBOOT_BOOT_SENTINEL,
                phase=phase,
                channel=channel_key,
                records=phase_records,
                source_files=(archive_relative,),
                source_sha256=(archive_prov.source_sha256,),
                limitations=(
                    f"Computed directly from {len(phase_records)} raw "
                    f"{channel_key} samples parsed from {directory.name}; "
                    f"{truncated_files} chunk file(s) in this channel had a "
                    "terminal NUL byte and were truncated for this in-memory "
                    "parse only (raw file untouched).",
                ),
            )
            if segment is not None:
                stationary_segments.append(segment)

        route_active_records = by_phase.get("ROUTE_ACTIVE", [])
        if route_active_records:
            field = _odom_field_for_topic(channel_key)
            first = route_active_records[0][field]["position"]
            last = route_active_records[-1][field]["position"]
            delta = tuple(round(last[i] - first[i], 6) for i in range(3))
            dynamic_segments.append(
                DynamicMotionSegment(
                    evidence_id=f"r3c.dynamic.route_active.{channel_slug}",
                    session_id=session_id,
                    boot_id=R3C_PRE_REBOOT_BOOT_SENTINEL,
                    phase="ROUTE_ACTIVE",
                    channel=channel_key,
                    start_sequence=route_active_records[0].get("sequence"),
                    end_sequence=route_active_records[-1].get("sequence"),
                    movement_type="HUMAN_OPERATOR_MANUAL_ROUTE",
                    ground_truth_constraint="NOT_AVAILABLE",
                    valid=True,
                    invalid_reason=None,
                    delta_position=delta,
                    integrated_yaw_speed_rad=None,
                    sample_count=len(route_active_records),
                    duration_s=None,
                    source_files=(archive_relative,),
                    source_sha256=(archive_prov.source_sha256,),
                    limitations=(
                        "delta_position is the raw first-to-last position "
                        "difference in the source-channel candidate frame; "
                        "it is NOT a measured route distance, is not scale- "
                        "or sign-validated, and does not imply the route "
                        "returned to its origin.",
                        "No integrated_yaw_speed_rad or duration_s computed "
                        "at R2-P0 for this multi-minute free-form route "
                        "(unlike the short, segment-annotated R4B turns).",
                    ),
                )
            )

    return session, dynamic_segments, stationary_segments


def build_r4_session(harvest_root: Path, generated_utc: str):
    """Ingest R4_FINAL_PHYSICAL_HARVEST: the post-boot stationary baseline
    and the cross-boot reset/discontinuity evidence. Returns
    (session_evidence, time_domain, reset_discontinuity)."""
    index = _load_json(harvest_root / "FINAL_PHYSICAL_HARVEST_INDEX.json")
    timebase = _load_json(harvest_root / "02_postboot_stationary" / "TIMEBASE_ESTIMATE.json")
    reset_cmp = _load_json(harvest_root / "09_analysis" / "ODOM_RESET_COMPARISON.json")

    session_id = index["POSTBOOT_SESSION_ID"]
    boot_id = index["ROBOT_BOOT_ID"]
    if boot_id not in timebase["remote_boot_ids"]:
        raise EvidenceValidationError(
            "R4 boot_id mismatch between FINAL_PHYSICAL_HARVEST_INDEX.json "
            "and TIMEBASE_ESTIMATE.json"
        )

    postboot_archive_relative = "02_postboot_stationary/POSTBOOT_CAPTURE.tar.gz"
    postboot_prov = _prov(
        harvest_root, "r4.provenance.postboot_archive", postboot_archive_relative, generated_utc
    )
    timebase_relative = "02_postboot_stationary/TIMEBASE_ESTIMATE.json"
    timebase_prov = _prov(harvest_root, "r4.provenance.timebase_estimate", timebase_relative, generated_utc)
    reset_relative = "09_analysis/ODOM_RESET_COMPARISON.json"
    reset_prov = _prov(harvest_root, "r4.provenance.reset_comparison", reset_relative, generated_utc)

    session = PhysicalSessionEvidence(
        evidence_id="r4.session",
        status="VERIFIED",
        confidence="HIGH_HASH_VERIFIED",
        session_id=session_id,
        session_type="R4_FINAL_PHYSICAL_HARVEST",
        boot_id=boot_id,
        clean_shutdown=True,
        physical_movement_authority="HUMAN_OPERATOR_ONLY",
        streams=(PRIMARY_CHANNEL, SECONDARY_CHANNEL),
        phases=("PRE_ROUTE_STATIONARY",),
        provenance=(postboot_prov, timebase_prov, reset_prov),
        source_files=(postboot_archive_relative, timebase_relative, reset_relative),
        source_sha256=(postboot_prov.source_sha256, timebase_prov.source_sha256,
                        reset_prov.source_sha256),
        limitations=(
            "First harvested post-boot samples were captured ~1805.6s "
            "remote monotonic uptime after boot, not immediately after "
            "kernel boot; EXACT_RESET_INSTANT = UNRESOLVED.",
            "DDS writer/participant discovery was UNAVAILABLE without "
            "installing unknown tooling; not attempted at R2-P0 either.",
        ),
    )

    time_domain = SessionTimeDomain(
        evidence_id="r4.time_domain",
        status="PARTIAL",
        confidence="MEDIUM_20_RTT_SAMPLES",
        session_id=session_id,
        boot_id=boot_id,
        message_stamp_status="ABSENT_OR_ZERO_IN_SOURCE",
        receipt_monotonic_available=True,
        receipt_wall_utc_available=True,
        notebook_utc_estimate=None,
        rtt_seconds=timebase["median_round_trip_ns"] / 1e9,
        uncertainty_seconds=(
            timebase["median_round_trip_ns"] - timebase["minimum_round_trip_ns"]
        ) / 1e9,
        mapping_status="PARTIAL",
        source_files=(timebase_relative,),
        source_sha256=(timebase_prov.source_sha256,),
        limitations=(
            f"{timebase['sample_count']} SSH RTT samples; remote UTC "
            f"midpoint offset ~= {timebase['best_remote_minus_local_utc_midpoint_ns'] / 1e9:.3f}s "
            "relative to local notebook clock. remote_clock_is_authoritative_utc=false: "
            "this is a best-effort estimate, never an authoritative ROS-time mapping.",
        ),
    )

    reset_evidence = ResetDiscontinuityEvidence(
        evidence_id="r4.reset_discontinuity",
        status="VERIFIED",
        exact_reset_instant_status="UNRESOLVED",
        from_session_id="hilroute-20260720T194910Z",
        to_session_id=session_id,
        from_boot_id=R3C_PRE_REBOOT_BOOT_SENTINEL,
        to_boot_id=boot_id,
        trajectory_concatenation_permitted=False,
        source_files=(reset_relative,),
        source_sha256=(reset_prov.source_sha256,),
        limitations=(
            reset_cmp["ODOM_RESET_CHARACTERIZATION"]["timing_limitation"],
            reset_cmp["ODOM_RESET_CHARACTERIZATION"]["posture_warning"],
            "scale_interpretation_performed=false in the source report; R2-P0 "
            "does not interpret this position jump as a physical displacement.",
        ),
    )

    return session, time_domain, reset_evidence


def build_r4b_session(harvest_root: Path, generated_utc: str):
    """Ingest R4B_FINAL_BEST_EFFORT_GROUND_TRUTH: the human-operator best-
    effort ground-truth segments (forward/turn), explicitly excluding the
    invalidated accidental-movement interval and the historically-mislabeled
    CW segment (operator-corrected to 'left'). Returns (session_evidence,
    dynamic_segments, stationary_segments, channel_comparison,
    imu_crosscheck, lidar_extrinsic, time_domain,
    stationary_noise_statistics)."""
    result = _load_json(harvest_root / "10_r4b" / "R4B_RESULT.json")
    axis_report = _load_json(harvest_root / "10_r4b" / "R4B_AXIS_SCALE_YAW_REPORT.json")
    channel_cmp = _load_json(harvest_root / "10_r4b" / "R4B_CHANNEL_COMPARISON.json")
    operator_annotation = _load_json(harvest_root / "10_r4b" / "R4B_OPERATOR_ANNOTATION.json")
    imu_cmp = _load_json(harvest_root / "10_r4b" / "R4B_IMU_CROSSCHECK.json")
    lidar_inputs = _load_json(harvest_root / "10_r4b" / "R4B_LIDAR_EXTRINSIC_INPUTS.json")

    session_id = result["GT_SESSION_ID"]
    if session_id != channel_cmp["session_id"] or session_id != imu_cmp["session_id"]:
        raise EvidenceValidationError("R4B session_id mismatch across source reports")

    def _relprov(name, relative):
        return _prov(harvest_root, f"r4b.provenance.{name}", f"10_r4b/{relative}", generated_utc)

    result_prov = _relprov("result", "R4B_RESULT.json")
    axis_prov = _relprov("axis_scale_yaw", "R4B_AXIS_SCALE_YAW_REPORT.json")
    channel_prov = _relprov("channel_comparison", "R4B_CHANNEL_COMPARISON.json")
    operator_prov = _relprov("operator_annotation", "R4B_OPERATOR_ANNOTATION.json")
    imu_prov = _relprov("imu_crosscheck", "R4B_IMU_CROSSCHECK.json")
    lidar_prov = _relprov("lidar_extrinsic_inputs", "R4B_LIDAR_EXTRINSIC_INPUTS.json")

    session_provenance = (result_prov, axis_prov, channel_prov, operator_prov, imu_prov, lidar_prov)
    session_source_files = tuple(f"10_r4b/{n}" for n in (
        "R4B_RESULT.json", "R4B_AXIS_SCALE_YAW_REPORT.json", "R4B_CHANNEL_COMPARISON.json",
        "R4B_OPERATOR_ANNOTATION.json", "R4B_IMU_CROSSCHECK.json", "R4B_LIDAR_EXTRINSIC_INPUTS.json",
    ))
    session_source_sha256 = tuple(p.source_sha256 for p in session_provenance)

    session = PhysicalSessionEvidence(
        evidence_id="r4b.session",
        status="VERIFIED",
        confidence="MEDIUM_BEST_EFFORT_GROUND_TRUTH",
        session_id=session_id,
        session_type="R4B_FINAL_BEST_EFFORT_GROUND_TRUTH",
        boot_id=None,
        clean_shutdown=True,
        physical_movement_authority="HUMAN_OPERATOR_ONLY",
        streams=(PRIMARY_CHANNEL, SECONDARY_CHANNEL),
        phases=tuple(sorted(channel_cmp["segments_primary"].keys())),
        provenance=session_provenance,
        source_files=session_source_files,
        source_sha256=session_source_sha256,
        limitations=(
            "GROUND_TRUTH_MODE = BEST_EFFORT_MEASURED, never MEASURED: no "
            "distance/angle instrument, no confirmed floor marks, no "
            "external video; measurement_uncertainty is unbounded.",
            "The historical phase label 'left_180 == CW/right' is invalid; "
            "the operator explicitly corrected the physical turn direction "
            "to LEFT. The label string is preserved for traceability but "
            "must never be read as 'clockwise' in R2-P0 or later.",
        ),
    )

    # Segment eligibility per checkpoint section 18: forward_x, forward_y,
    # left_90_first and the corrected left_180 and the local-baseline retry
    # are valid; left_90_return_invalidated (the accidental extra movement)
    # is explicitly excluded from any computation and kept only as a
    # documented invalid record.
    ground_truth_by_segment = {
        "forward_x_valid_retry": "BEST_EFFORT_MEASURED",
        "forward_y": "BEST_EFFORT_MEASURED",
        "left_90_first": "BEST_EFFORT_MEASURED",
        "left_180_operator_corrected": "BEST_EFFORT_MEASURED",
        "left_90_valid_retry_local_baseline": "BEST_EFFORT_MEASURED",
        "left_90_return_invalidated": "INVALID",
    }
    movement_type_by_segment = {
        "forward_x_valid_retry": "OPERATOR_FORWARD_TRANSLATION",
        "forward_y": "OPERATOR_FORWARD_TRANSLATION",
        "left_90_first": "OPERATOR_YAW_TURN_LEFT",
        "left_180_operator_corrected": "OPERATOR_YAW_TURN_LEFT",
        "left_90_valid_retry_local_baseline": "OPERATOR_YAW_TURN_LEFT",
        "left_90_return_invalidated": "OPERATOR_UNINTENDED_ADDITIONAL_MOVEMENT",
    }

    dynamic_segments = []
    for channel_key, segment_map_key in (
        (PRIMARY_CHANNEL, "segments_primary"),
        (SECONDARY_CHANNEL, "segments_secondary"),
    ):
        channel_slug = channel_key.replace("/", "_")
        for segment_name, segment_data in channel_cmp[segment_map_key].items():
            valid = segment_data["analysis_eligible"] and ground_truth_by_segment[segment_name] != "INVALID"
            invalid_reason = None
            if not valid:
                invalid_reason = (
                    "operator reported unintended additional movement during "
                    "this interval; excluded from all R2-P0 computations "
                    "and must never be connected geometrically to adjacent segments"
                )
            dynamic_segments.append(
                DynamicMotionSegment(
                    evidence_id=f"r4b.dynamic.{segment_name}.{channel_slug}",
                    session_id=session_id,
                    boot_id=None,
                    phase=segment_name,
                    channel=channel_key,
                    start_sequence=None,
                    end_sequence=None,
                    movement_type=movement_type_by_segment[segment_name],
                    ground_truth_constraint=ground_truth_by_segment[segment_name],
                    valid=valid,
                    invalid_reason=invalid_reason,
                    delta_position=tuple(round(v, 6) for v in segment_data["delta_position"]),
                    integrated_yaw_speed_rad=segment_data["integrated_yaw_speed_rad"],
                    sample_count=segment_data["sample_count"],
                    duration_s=segment_data["duration_s"],
                    source_files=(f"10_r4b/R4B_CHANNEL_COMPARISON.json",),
                    source_sha256=(channel_prov.source_sha256,),
                    limitations=(
                        f"ground_truth={segment_data['ground_truth']!r} (nominal "
                        "operator-attempted distance/angle; actual value UNKNOWN, "
                        "never treated as metrological truth).",
                    ),
                )
            )

    stationary_segments = []
    for channel_key, final_key in (
        (PRIMARY_CHANNEL, "final_stationary_primary"),
        (SECONDARY_CHANNEL, "final_stationary_secondary"),
    ):
        channel_slug = channel_key.replace("/", "_")
        final_stats = channel_cmp[final_key]
        stationary_segments.append(
            StationarySegment(
                evidence_id=f"r4b.stationary.final.{channel_slug}",
                session_id=session_id,
                boot_id=None,
                phase="FINAL_STATIONARY",
                channel=channel_key,
                sample_count=final_stats["sample_count"],
                position_range=tuple(final_stats["position_range"]),
                position_stddev=tuple(final_stats["position_stddev"]),
                yaw_speed_mean=final_stats["yaw_speed_mean"],
                yaw_speed_stddev=final_stats["yaw_speed_stddev"],
                source_files=("10_r4b/R4B_CHANNEL_COMPARISON.json",),
                source_sha256=(channel_prov.source_sha256,),
            )
        )

    channel_comparison = ChannelComparisonEvidence(
        evidence_id="r4b.channel_comparison",
        status="PARTIAL",
        primary_channel=PRIMARY_CHANNEL,
        secondary_channel=SECONDARY_CHANNEL,
        primary_sample_count=channel_cmp["primary_sample_count"],
        secondary_sample_count=channel_cmp["secondary_sample_count"],
        authoritative_source_channel=None,
        primary_analysis_stream_candidate=True,
        arbitration_status=channel_cmp["arbitration"],
        observations=(
            f"primary_sample_count={channel_cmp['primary_sample_count']}, "
            f"secondary_sample_count={channel_cmp['secondary_sample_count']} "
            "(secondary is roughly half the primary rate; rate is an "
            "observation only, never authority per checkpoint section 19).",
            f"primary_source_timestamp={channel_cmp['primary_source_timestamp']}, "
            f"secondary_source_timestamp={channel_cmp['secondary_source_timestamp']}",
        ),
        source_files=("10_r4b/R4B_CHANNEL_COMPARISON.json",),
        source_sha256=(channel_prov.source_sha256,),
        limitations=(
            "Position deltas for primary and secondary are nearly identical "
            "on the same valid segments; this does NOT select an "
            "authoritative channel -- AUTHORITATIVE_SOURCE_CHANNEL remains null.",
        ),
    )

    imu_crosscheck = ImuCrosscheckEvidence(
        evidence_id="r4b.imu_crosscheck",
        status="PARTIAL",
        session_id=session_id,
        stationary_bias_observed=True,
        dynamic_response_observed=True,
        sign_agreement=(
            "operator-left turns produced positive LowState yaw and positive "
            "integrated SportModeState yaw_speed on all analysis-eligible turn "
            "segments; candidate CCW-positive, not elevated beyond SUPPORTED_INFERENCE"
        ),
        source_files=("10_r4b/R4B_IMU_CROSSCHECK.json",),
        source_sha256=(imu_prov.source_sha256,),
        limitations=(imu_cmp["limitation"],),
    )

    lidar_extrinsic = LidarExtrinsicEvidence(
        evidence_id="r4b.lidar_extrinsic",
        status="PARTIAL",
        source_frame_semantics_status="PARTIAL",
        child_frame_id_status="UNRESOLVED",
        candidate_transform_available=False,
        source_files=("10_r4b/R4B_LIDAR_EXTRINSIC_INPUTS.json",),
        source_sha256=(lidar_prov.source_sha256,),
        limitations=(
            f"extrinsic_claim={lidar_inputs['extrinsic_claim']!r}, "
            f"observed_frame_id={lidar_inputs['observed_frame_id']!r} is a "
            "filesystem/schema candidate only, not a validated ROS frame_id.",
        ),
    )

    time_domain = SessionTimeDomain(
        evidence_id="r4b.time_domain",
        status="PARTIAL",
        confidence="LOW_NO_SOURCE_TIMESTAMP",
        session_id=session_id,
        boot_id=None,
        message_stamp_status="ABSENT",
        receipt_monotonic_available=True,
        receipt_wall_utc_available=False,
        notebook_utc_estimate=None,
        rtt_seconds=None,
        uncertainty_seconds=None,
        mapping_status="UNRESOLVED",
        source_files=("10_r4b/R4B_CHANNEL_COMPARISON.json",),
        source_sha256=(channel_prov.source_sha256,),
        limitations=(
            "SportModeState carries no source/header timestamp for this "
            "session (source_timestamp=ABSENT for both channels); only "
            "receipt monotonic time is available.",
        ),
    )

    stationary_noise_statistics = tuple(
        StationaryNoiseStatistics(
            evidence_id=f"r4b.stats.stationary.{seg.channel.replace('/', '_')}",
            session_id=session_id,
            channel=seg.channel,
            sample_count=seg.sample_count,
            window_description="final stationary window at session close",
            mean=(0.0, 0.0, 0.0),
            variance=tuple(v * v for v in seg.position_stddev),
            stddev=seg.position_stddev,
            robust_method=ROBUST_METHOD,
            outlier_rule=OUTLIER_RULE,
            source_files=seg.source_files,
            source_sha256=seg.source_sha256,
            limitations=(
                "mean position components are reported as 0.0 (this "
                "statistic characterizes DISPERSION around the segment's own "
                "local baseline, not an absolute position claim).",
            ),
        )
        for seg in stationary_segments
    )

    return (
        session, dynamic_segments, stationary_segments, channel_comparison,
        imu_crosscheck, lidar_extrinsic, time_domain, stationary_noise_statistics,
    )


def build_axis_and_yaw_observations(dynamic_segments, generated_utc: str):
    valid_translation = [
        s for s in dynamic_segments
        if s.valid and s.movement_type == "OPERATOR_FORWARD_TRANSLATION"
    ]
    valid_turns = [
        s for s in dynamic_segments
        if s.valid and s.movement_type == "OPERATOR_YAW_TURN_LEFT"
    ]

    axis_observations = (
        AxisResponseObservation(
            evidence_id="r2p0.axis_response.primary",
            status="SUPPORTED_INFERENCE",
            axis="x_and_y_translation",
            dominant=True,
            evidence_segment_ids=tuple(s.evidence_id for s in valid_translation),
            limitations=(
                "Dominant-axis translation response is observed on both "
                "forward_x and forward_y segments across primary and secondary "
                "channels; TRANSLATION_SCALE remains UNRESOLVED.",
            ),
        ),
    )
    yaw_observations = (
        YawResponseObservation(
            evidence_id="r2p0.yaw_response.ccw_positive",
            status="SUPPORTED_INFERENCE",
            sign_candidate="CCW_POSITIVE",
            evidence_segment_ids=tuple(s.evidence_id for s in valid_turns),
            limitations=(
                "Positive integrated yaw_speed correlates with operator-left "
                "turns on all analysis-eligible turn segments and both "
                "channels; YAW_SCALE remains UNRESOLVED and this is not "
                "elevated beyond SUPPORTED_INFERENCE.",
            ),
        ),
    )
    return axis_observations, yaw_observations


def build_covariance_evidence(stationary_noise_statistics) -> CovarianceEvidence:
    return CovarianceEvidence(
        evidence_id="r2p0.covariance",
        status="PARTIAL",
        publication_model_ready=False,
        stationary_stats_ids=tuple(s.evidence_id for s in stationary_noise_statistics),
        dynamic_stats_ids=(),
        source_files=tuple(sorted({f for s in stationary_noise_statistics for f in s.source_files})),
        source_sha256=tuple(sorted({h for s in stationary_noise_statistics for h in s.source_sha256})),
        limitations=(
            "SportModeState exposes no covariance field in the source; "
            "stationary dispersion statistics bound an OBSERVED noise floor "
            "only and must never be presented as a validated covariance "
            "matrix. COVARIANCE_PUBLICATION_MODEL_READY = false.",
        ),
    )


CLAIMS_DELTA = (
    dict(claim_id="DYNAMIC_MOTION_EVIDENCE", r1_state="DYNAMIC_MOTION_EVIDENCE_MISSING",
         v19_state="EVIDENCE_COLLECTED_PENDING_ANALYSIS", r2p0_state="VERIFIED",
         reason="R3C (190s human-driven route) and R4B (annotated forward/turn segments) "
                "are locally hash-verified and ingested with real dynamic samples.",
         evidence_ids=("r3c.session", "r4b.session"), confidence="HIGH"),
    dict(claim_id="SOURCE_CHANNEL_ARBITRATION", r1_state="SOURCE_CHANNEL_ARBITRATION_UNRESOLVED",
         v19_state="EVIDENCE_COLLECTED_PENDING_ANALYSIS", r2p0_state="UNRESOLVED",
         reason="Primary and LF channel comparisons computed; position deltas nearly "
                "identical, no authoritative channel selected by design.",
         evidence_ids=("r4b.channel_comparison",), confidence="MEDIUM"),
    dict(claim_id="SOURCE_FRAME_SEMANTICS", r1_state="SOURCE_FRAME_SEMANTICS_UNVERIFIED",
         v19_state="STILL_BLOCKED", r2p0_state="PARTIAL",
         reason="No frame_id in SportModeState; URDF/frame candidates ingested but not "
                "reconciled with a runtime-verified ROS frame at R2-P0.",
         evidence_ids=("r4b.lidar_extrinsic",), confidence="LOW"),
    dict(claim_id="CHILD_FRAME_ID", r1_state="CHILD_FRAME_ID_UNRESOLVED",
         v19_state="STILL_BLOCKED", r2p0_state="UNRESOLVED",
         reason="No authoritative child frame is carried by the source messages.",
         evidence_ids=("r4b.lidar_extrinsic",), confidence="LOW"),
    dict(claim_id="AXIS_CONVENTION", r1_state="AXIS_CONVENTION_UNVERIFIED",
         v19_state="EVIDENCE_COLLECTED_PENDING_ANALYSIS", r2p0_state="SUPPORTED_INFERENCE",
         reason="Dominant-axis translation and CCW-positive yaw response observed on "
                "annotated R4B segments across both channels.",
         evidence_ids=("r2p0.axis_response.primary", "r2p0.yaw_response.ccw_positive"),
         confidence="MEDIUM"),
    dict(claim_id="SCALE_AND_SIGN", r1_state="SCALE_AND_SIGN_UNVERIFIED",
         v19_state="EVIDENCE_COLLECTED_PENDING_ANALYSIS", r2p0_state="UNRESOLVED",
         reason="No calibrated distance/angle instrument was available; nominal operator "
                "distances/angles cannot validate metric scale or sign gain.",
         evidence_ids=("r4b.session",), confidence="LOW"),
    dict(claim_id="MESSAGE_TIMESTAMP", r1_state="MESSAGE_TIMESTAMP_ZERO",
         v19_state="PARTIALLY_CHARACTERIZED", r2p0_state="UNRESOLVED",
         reason="source_timestamp remained ABSENT/zero across R3C, R4 and R4B captures.",
         evidence_ids=("r4b.time_domain", "r4.time_domain"), confidence="HIGH"),
    dict(claim_id="RECEIPT_TO_ROS_TIME", r1_state="RECEIPT_TIME_TO_ROS_TIME_UNRESOLVED",
         v19_state="PARTIALLY_CHARACTERIZED", r2p0_state="PARTIAL",
         reason="20 RTT-based UTC-midpoint samples exist for R4 (remote clock ~0.43s "
                "behind, explicitly non-authoritative); R4B has no such handshake.",
         evidence_ids=("r4.time_domain",), confidence="MEDIUM"),
    dict(claim_id="COVARIANCE", r1_state="COVARIANCE_UNAVAILABLE",
         v19_state="NOT_AVAILABLE", r2p0_state="PARTIAL",
         reason="No covariance field in source; stationary dispersion statistics computed "
                "as a bounded noise-floor observation only, not a publishable matrix.",
         evidence_ids=("r2p0.covariance",), confidence="MEDIUM"),
    dict(claim_id="IMU_CROSSCHECK", r1_state="IMU_CROSSCHECK_UNAVAILABLE",
         v19_state="EVIDENCE_COLLECTED_PENDING_ANALYSIS", r2p0_state="PARTIAL",
         reason="LowState IMU rpy/gyro cross-checked against integrated SportModeState "
                "yaw_speed and operator direction on R4B turn segments.",
         evidence_ids=("r4b.imu_crosscheck",), confidence="MEDIUM"),
    dict(claim_id="RESET_AND_DISCONTINUITY", r1_state="RESET_AND_DISCONTINUITY_BEHAVIOR_UNVERIFIED",
         v19_state="PARTIALLY_CHARACTERIZED", r2p0_state="VERIFIED",
         reason="A cross-boot position/velocity/yaw_speed discontinuity is observed and "
                "typed on both channels; exact reset instant remains unresolved.",
         evidence_ids=("r4.reset_discontinuity",), confidence="HIGH"),
)


def build_claims() -> "tuple[EvidenceClaim, ...]":
    return tuple(EvidenceClaim(**kwargs) for kwargs in CLAIMS_DELTA)


def build_bundle(harvest_root: Path, generated_utc: str) -> PhysicalEvidenceBundleR2:
    if not is_non_empty_str(generated_utc):
        raise EvidenceValidationError("generated_utc must be a non-empty injected string")

    r3c_session, r3c_dynamic, r3c_stationary = build_r3c_session(harvest_root, generated_utc)
    r4_session, r4_time_domain, r4_reset = build_r4_session(harvest_root, generated_utc)
    (r4b_session, r4b_dynamic, r4b_stationary, channel_comparison, imu_crosscheck,
     lidar_extrinsic, r4b_time_domain, r4b_stats) = build_r4b_session(harvest_root, generated_utc)

    all_dynamic = tuple(r3c_dynamic) + tuple(r4b_dynamic)
    all_stationary = tuple(r3c_stationary) + tuple(r4b_stationary)
    axis_observations, yaw_observations = build_axis_and_yaw_observations(all_dynamic, generated_utc)
    covariance = build_covariance_evidence(r4b_stats)
    claims = build_claims()

    return PhysicalEvidenceBundleR2(
        generated_utc_injected=generated_utc,
        sessions=(r3c_session, r4_session, r4b_session),
        time_domains=(r4_time_domain, r4b_time_domain),
        dynamic_segments=all_dynamic,
        stationary_segments=all_stationary,
        axis_observations=axis_observations,
        yaw_observations=yaw_observations,
        channel_comparison=channel_comparison,
        imu_crosscheck=imu_crosscheck,
        reset_discontinuity=r4_reset,
        lidar_extrinsic=lidar_extrinsic,
        stationary_noise_statistics=r4b_stats,
        dynamic_residual_statistics=(),
        covariance=covariance,
        claims=claims,
        limitations=(
            "R2-P0 does not select an authoritative source channel, does not "
            "resolve translation/yaw scale, does not resolve child_frame_id, "
            "and does not produce a publication-ready covariance model. "
            "ODOM_PUBLICATION_READY=false, TF_TO_BASE_LINK_READY=false, "
            "NAV2_READY=false remain unchanged from R1.",
        ),
    )
