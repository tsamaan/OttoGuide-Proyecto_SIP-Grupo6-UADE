# OttoGuide Map Executable Quickstart

`tools/hil/ottoguide-map` is a field helper for raw office sensor capture on the Unitree G1 companion PC.

Use it when the robot is already powered on, standing/on the floor, stable, the area is clear, and a human operator will move it with the remote control. The script records data only. It does not move the robot and does not publish `/cmd_vel`.

## Quick Commands

```bash
cd "/home/unitree/Desktop/Ottoguide/OttoGuide-Proyecto_SIP-Grupo6-UADE/codigo ottoguide"
./tools/hil/ottoguide-map prep
./tools/hil/ottoguide-map start --label "office_short_remote_control_raw"
./tools/hil/ottoguide-map status
./tools/hil/ottoguide-map stop
./tools/hil/ottoguide-map finalize
./tools/hil/ottoguide-map package
```

Timed capture option:

```bash
./tools/hil/ottoguide-map timed --duration 300 --label "office_short_remote_control_raw"
```

## Raw Capture Vs Mapping

Raw capture records available sensor topics such as `/utlidar/cloud`, `/livox/imu`, and `/scan`. It also records `/tf`, `/odom`, `/map`, `/cmd_vel`, and state/control topics only if they exist.

A complete mapping run needs valid TF and usually `/map`. If `/tf` or `/map` is missing, this tool still records useful raw data, but direct PGM/YAML export is not guaranteed.

## Copy Artifacts

After `package`, copy the tarball from Windows PowerShell using the command printed by the tool, for example:

```powershell
scp -i "$env:USERPROFILE\.ssh\id_ed25519_ottoguide_robot" unitree@192.168.123.164:/tmp/ottoguide_map_<RUN_ID>.tar.gz "C:\Users\lucas\Documents\OttoGuide-Proyecto_SIP-Grupo6-UADE\artifacts\"
```

## Offline Next Steps

Replay the rosbag on the notebook, inspect sensor quality, reconstruct or provide TF if needed, run offline SLAM/map export, then clean/crop maps and validate localization/navigation offline before any autonomous physical navigation.
