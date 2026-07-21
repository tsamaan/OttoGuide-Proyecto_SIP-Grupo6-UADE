"""Offline, read-only quantitative characterization of the two ODOM/TF R2
physical channels (rt/odommodestate, rt/lf/odommodestate): sampling quality,
primary/LF alignment, stationary noise, dynamic motion segments, IMU
cross-check, timebase, channel arbitration and dynamic residual statistics.

MVP-ODOM-TF-R2-P1-CHANNEL-TIME-AND-MOTION-CHARACTERIZATION. Builds on top of
(imports, never duplicates or modifies) the P0A trust boundary in
``src.navigation.odometry_evidence_r2`` (validation, source_manifest,
statistics). No ROS, no Nav2, no DDS, no live SDK, no network. Never selects
an authoritative source channel.
"""

CHARACTERIZATION_SCHEMA_VERSION = "2.1.0-p1"
