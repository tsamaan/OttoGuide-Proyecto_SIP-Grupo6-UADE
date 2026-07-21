"""LowState/SportModeState IMU cross-check (section 27).

The recorder's ``odom``/``lf_odom`` stream (SportModeState reduced view)
carries only position/velocity/yaw_speed/mode -- no quaternion or rpy. A
full-fidelity SportModeState quaternion/rpy sample only exists as a single
static schema-probe capture (02_postboot_stationary/extracted/probe/
SPORTMODESTATE_PRIMARY_RAW.jsonl), not per-sample across the R3C/R4B
sessions. This is an honest, evidence-based limitation, not an oversight:
the SportModeState-side of the cross-check is therefore limited to
yaw_speed sign only; the richer signal (quaternion/rpy) comes from
LowState's own ``imu`` block, which IS present per-sample in every session.

``rpy_deg`` is self-documented in the source field name as degrees;
``gyroscope`` carries no unit label anywhere in the source, schema, or IDL
files inspected -- per section 27's explicit instruction, this module NEVER
assumes rad/s or deg/s for it and never integrates it; only its SIGN is used
for cross-check, which is unit-independent.
"""
from . import statistics as p1stats
from .models import CHARACTERIZATION_SCHEMA_VERSION, ImuAgreementMetrics

PAIRING_TOLERANCE_S = 0.05


def _sign(value: float) -> "str | None":
    if abs(value) < 1e-6:
        return None
    return "POSITIVE" if value > 0 else "NEGATIVE"


def compute_imu_agreement(*, session_id: str, segment_name: str, odom_samples: tuple,
                           lowstate_samples: tuple) -> "ImuAgreementMetrics | None":
    if not odom_samples or not lowstate_samples:
        return None

    odom_times = [s.receipt_monotonic_ns / 1e9 for s in odom_samples]
    lowstate_times = [s.receipt_monotonic_ns / 1e9 for s in lowstate_samples]
    pairs = p1stats.nearest_neighbor_pairing(odom_times, lowstate_times, PAIRING_TOLERANCE_S)
    if not pairs:
        return ImuAgreementMetrics(
            schema_version=CHARACTERIZATION_SCHEMA_VERSION,
            evidence_id=f"p1.imu.{session_id}.{segment_name}",
            session_id=session_id,
            segment_name=segment_name,
            sportmode_yaw_speed_sign=None,
            lowstate_gyro_z_sign=None,
            sign_agreement=None,
            gyro_units_status="UNRESOLVED_NO_UNIT_LABEL_IN_SOURCE",
            rpy_units_status="DEGREES_SELF_LABELED_RPY_DEG",
            wrap_events=0,
            sample_coverage=0.0,
            status="UNRESOLVED",
            limitations=("no odom/lowstate samples could be paired within tolerance for this segment",),
        )

    yaw_speed_signs = [_sign(odom_samples[i].yaw_speed) for i, _j, _o in pairs]
    gyro_z_signs = [_sign(lowstate_samples[j].gyroscope[2]) for _i, j, _o in pairs]

    agree = 0
    compared = 0
    dominant_yaw_sign = None
    dominant_gyro_sign = None
    yaw_counts = {}
    gyro_counts = {}
    for ys, gs in zip(yaw_speed_signs, gyro_z_signs):
        if ys is not None:
            yaw_counts[ys] = yaw_counts.get(ys, 0) + 1
        if gs is not None:
            gyro_counts[gs] = gyro_counts.get(gs, 0) + 1
        if ys is not None and gs is not None:
            compared += 1
            if ys == gs:
                agree += 1
    if yaw_counts:
        dominant_yaw_sign = max(yaw_counts.items(), key=lambda kv: kv[1])[0]
    if gyro_counts:
        dominant_gyro_sign = max(gyro_counts.items(), key=lambda kv: kv[1])[0]

    sign_agreement = None
    if compared >= 5:
        sign_agreement = (agree / compared) >= 0.6

    rpy_yaw_deg = [lowstate_samples[j].rpy_deg[2] for _i, j, _o in pairs]
    rpy_yaw_rad = [v * 3.14159265358979323846 / 180.0 for v in rpy_yaw_deg]
    _unwrapped, wrap_events = p1stats.unwrap_angles(rpy_yaw_rad)

    coverage = len(pairs) / min(len(odom_samples), len(lowstate_samples))

    return ImuAgreementMetrics(
        schema_version=CHARACTERIZATION_SCHEMA_VERSION,
        evidence_id=f"p1.imu.{session_id}.{segment_name}",
        session_id=session_id,
        segment_name=segment_name,
        sportmode_yaw_speed_sign=dominant_yaw_sign,
        lowstate_gyro_z_sign=dominant_gyro_sign,
        sign_agreement=sign_agreement,
        gyro_units_status="UNRESOLVED_NO_UNIT_LABEL_IN_SOURCE",
        rpy_units_status="DEGREES_SELF_LABELED_RPY_DEG",
        wrap_events=wrap_events,
        sample_coverage=min(coverage, 1.0),
        status="PARTIAL_QUANTIFIED",
        limitations=(
            "SportModeState's own quaternion/rpy are not available per-sample in "
            "the recorder stream (only position/velocity/yaw_speed/mode) -- only a "
            "single static schema-probe capture exists; the SportModeState side of "
            "this cross-check is therefore yaw_speed SIGN only, never magnitude.",
            "gyroscope carries no unit label anywhere in the inspected source/schema/"
            "IDL files; only its sign is used here, never its magnitude or an "
            "integrated value (no rad/s or deg/s assumption is made).",
            f"compared={compared} of {len(pairs)} paired samples had both a non-zero "
            "yaw_speed and non-zero gyroscope[2] sign; near-zero (stationary) samples "
            "are excluded from the sign vote.",
        ),
    )
