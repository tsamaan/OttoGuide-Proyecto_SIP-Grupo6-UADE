from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional


class OdomSourceKind(Enum):
    LOWSTATE_ONLY = "lowstate_only"
    SPORTMODESTATE_ONLY = "sportmodestate_only"
    IMU_ONLY = "imu_only"
    JOINTS_ONLY = "joints_only"
    POSE_TWIST_VALIDATED = "pose_twist_validated"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class OdomBridgeSafetyFlags:
    enable_odom_bridge: bool
    hil_session_confirmed: bool
    odom_source_validated: bool
    odom_source_name: Optional[str]


@dataclass(frozen=True)
class OdomFrameContract:
    odom_frame: str = "odom"
    base_frame: str = "base_link"
    lidar_frame: str = "utlidar_lidar"


@dataclass(frozen=True)
class OdomCovariancePolicy:
    pose_covariance: tuple[float, ...]
    twist_covariance: tuple[float, ...]


@dataclass(frozen=True)
class OdomSourceAssessment:
    source_kind: OdomSourceKind
    has_pose_xy: bool
    has_yaw: bool
    has_twist: bool
    frequency_hz: Optional[float]
    notes: str


def is_source_acceptable_for_odom(source: OdomSourceAssessment) -> bool:
    if source.source_kind is not OdomSourceKind.POSE_TWIST_VALIDATED:
        return False
    return source.has_pose_xy and source.has_yaw and source.has_twist


def activation_allowed(
    flags: OdomBridgeSafetyFlags,
    source: OdomSourceAssessment,
) -> bool:
    return (
        flags.enable_odom_bridge
        and flags.hil_session_confirmed
        and flags.odom_source_validated
        and bool(flags.odom_source_name and flags.odom_source_name.strip())
        and is_source_acceptable_for_odom(source)
    )


def default_conservative_covariance() -> OdomCovariancePolicy:
    pose = [0.0] * 36
    pose[0] = 0.50
    pose[7] = 0.50
    pose[14] = 999.0
    pose[21] = 999.0
    pose[28] = 999.0
    pose[35] = 0.10

    twist = [0.0] * 36
    twist[0] = 0.50
    twist[7] = 999.0
    twist[14] = 999.0
    twist[21] = 999.0
    twist[28] = 999.0
    twist[35] = 0.10

    return OdomCovariancePolicy(
        pose_covariance=tuple(pose),
        twist_covariance=tuple(twist),
    )


def validate_frame_contract(frames: OdomFrameContract) -> None:
    values = (frames.odom_frame, frames.base_frame, frames.lidar_frame)
    if any(not value or not value.strip() for value in values):
        raise ValueError("odom, base, and lidar frames must be non-empty")
    normalized = tuple(value.strip() for value in values)
    if len(set(normalized)) != len(normalized):
        raise ValueError("odom, base, and lidar frames must be distinct")
