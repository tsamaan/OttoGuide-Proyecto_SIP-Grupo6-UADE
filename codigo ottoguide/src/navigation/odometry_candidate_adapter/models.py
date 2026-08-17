"""Internal data model for MFR-R6 / ODOM-R1.

OdometryCandidate is NOT nav_msgs/Odometry. It carries no ROS dependency and
is never published anywhere. It exists to let an offline adapter reason about
SportModeState_ samples with an explicit, auditable set of contractual gaps
(timestamp, frame, covariance) rather than silently assuming they are solved.
"""
from dataclasses import dataclass, field


@dataclass(frozen=True)
class OdometryCandidate:
    valid: bool
    source_channel: str
    receipt_monotonic_ns: int
    receipt_wall_utc_ns: "int | None"
    timestamp_policy: str
    message_stamp_sec: int
    message_stamp_nanosec: int
    frame_id: str
    child_frame_id: "str | None"
    position_xyz: "tuple[float, float, float]"
    velocity_xyz: "tuple[float, float, float]"
    yaw_speed: float
    orientation_quaternion_xyzw: "tuple[float, float, float, float]"
    rpy: "tuple[float, float, float]"
    covariance_policy: str
    covariance_available: bool
    gyro_reliable: bool
    accel_reliable: bool
    warnings: "list[str]" = field(default_factory=list)
    errors: "list[str]" = field(default_factory=list)
