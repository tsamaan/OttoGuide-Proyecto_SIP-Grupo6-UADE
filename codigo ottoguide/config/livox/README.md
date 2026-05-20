# Livox MID360 SDK2 configuration

This directory contains versionable Livox SDK2 configuration files for OttoGuide HIL mapping.

## Files

- `mid360_sdk2_bridge.json`: stable SDK2 configuration for the Livox MID360 mounted on the Unitree G1 EDU robot.

## Known HIL network

- Robot host IP: `192.168.123.164`
- Livox MID360 IP: `192.168.123.120`
- Multicast: `224.1.1.5`

## Purpose

This config is intended for the future minimal SDK2 to ROS 2 bridge:

```text
Livox MID360 ? SDK2 bridge ? /utlidar/cloud ? pointcloud_to_laserscan ? /scan
```

## Notes

* This file was derived from a runtime-tested temporary config under `logs/`.
* Runtime logs and temporary configs under `logs/` must not be committed.
* Do not modify `config/cyclonedds.xml` as part of this config change.
* Do not modify `livox_ros_driver2` as part of this config change.
