# OttoGuide Unitree Capture Bridge

Receive-only bridge for recording Unitree G1 telemetry with ROS 2 Foxy.

```text
Unitree DDS domain 0 / eth0
  -> native SDK2 receive tap
  -> AF_UNIX SOCK_DGRAM
  -> separate ROS 2 process
  -> six /unitree/* topics
  -> ottoguide-map / rosbag2
```

The native process links `libunitree_sdk2.a` explicitly and dynamically resolves only CycloneDDS and system libraries. It creates receive channels for:

- `rt/lowstate` (primary LowState and wireless remote source)
- `rt/secondary_imu`
- `rt/sportmodestate`
- `rt/lf/lowstate` (optional diagnostics only)

## Commands

```bash
./tools/hil/unitree_capture_bridge/scripts/unitree-capture-bridge plan
./tools/hil/unitree_capture_bridge/scripts/unitree-capture-bridge build
./tools/hil/unitree_capture_bridge/scripts/unitree-capture-bridge start
./tools/hil/unitree_capture_bridge/scripts/unitree-capture-bridge status
./tools/hil/unitree_capture_bridge/scripts/unitree-capture-bridge validate
./tools/hil/unitree_capture_bridge/scripts/unitree-capture-bridge stop
```

`start` refuses existing bridge processes, forbidden ROS publishers, Nav2, or SLAM. `stop` acts only on validated PIDs created by this wrapper.

## Safety contract

- Native SDK use is receive-only.
- IPC is local and unidirectional.
- ROS publishers are restricted to the six documented `/unitree/*` topics.
- Remote-control bytes are recorded as human intent and never converted into a command.
- The wrapper never starts locomotion, navigation, localization, or mapping.

See [PROTOCOL.md](PROTOCOL.md) for the wire contract and topic mapping.
