# Physical Mapping Route Runbook

This runbook prepares repeatable physical 2D mapping for OttoGuide on the Unitree G1 EDU. It does not validate autonomous navigation.

## Safety Scope

- Do not run Nav2 against hardware in this session.
- Do not publish `/cmd_vel`.
- Do not move the robot from scripts.
- Move the robot manually and under human supervision only.
- Do not include transport to the start point in the final route map.
- Preserve raw maps and rosbags. Create cleaned or cropped maps only as derived copies.

## SSH

From Windows PowerShell:

```powershell
ssh -i "$env:USERPROFILE\.ssh\id_ed25519_ottoguide_robot" unitree@192.168.123.164
```

If the ROS selector appears, choose `1` for Foxy.

## Baseline Checks

On the robot:

```bash
hostname
whoami
pwd
ip -br addr
ip route
date
uname -a
```

Validate the internal HIL network before touching anything:

```bash
ping -c 3 192.168.123.161
ping -c 3 192.168.123.101
```

Do not modify `eth0` or the `192.168.123.0/24` route if these work.

## Internet USB Check

Inspect interfaces without changing routes:

```bash
ip -br addr
ip route
lsusb || true
nmcli device status || true
ping -c 3 8.8.8.8 || true
ping -c 3 github.com || true
curl -I --max-time 10 https://github.com || true
```

If a USB interface exists but has no IP, request approval before DHCP on that USB interface only:

```bash
sudo dhclient -v <USB_IFACE>
```

## Repo Sync

```bash
cd "/home/unitree/Desktop/Ottoguide/OttoGuide-Proyecto_SIP-Grupo6-UADE"
git status --short --branch --untracked-files=all
git branch --show-current
git rev-parse --short HEAD
git fetch origin robot
git rev-list --left-right --count HEAD...origin/robot
```

Fast-forward only if tracked files are clean:

```bash
git merge --ff-only origin/robot
```

Never use `git reset --hard`, `git clean`, rebase, or stash without explicit authorization.

## ROS Environment

```bash
set +u
source /opt/ros/foxy/setup.bash
set -u
echo "ROS_DISTRO=$ROS_DISTRO"
echo "RMW_IMPLEMENTATION=${RMW_IMPLEMENTATION:-}"
echo "ROS_DOMAIN_ID=${ROS_DOMAIN_ID:-}"
echo "CYCLONEDDS_URI=${CYCLONEDDS_URI:-}"
```

## Preflight

From:

```bash
cd "/home/unitree/Desktop/Ottoguide/OttoGuide-Proyecto_SIP-Grupo6-UADE/codigo ottoguide"
```

Run:

```bash
"codigo ottoguide/tools/hil/physical_mapping_route.sh" --preflight-only
```

The preflight records baseline state and checks `/utlidar/cloud`, `/scan`, `/tf`, `/tf_static`, optional `/odom`, `/map`, `/map_metadata`, `/livox/imu`, and `/cmd_vel` info without publishing anything.

## TF And LiDAR Diagnostics

Before mapping, capture:

```bash
ros2 run tf2_tools view_frames || true
timeout 10s ros2 run tf2_ros tf2_echo base_link utlidar_lidar || true
timeout 10s ros2 run tf2_ros tf2_echo map base_link || true
timeout 10s ros2 run tf2_ros tf2_echo odom base_link || true
```

If TF, odom, scan, cloud, or LiDAR orientation looks wrong, stop at diagnostics. Do not start navigation.

## Start Mapping

Only start after the operator confirms the robot is already at the real start point.

Manual mode:

```bash
"codigo ottoguide/tools/hil/physical_mapping_route.sh" --mode start --route-label "ruta_real_mvp_lima3_lima2"
```

Timed 30 minute mode:

```bash
"codigo ottoguide/tools/hil/physical_mapping_route.sh" --mode timed --duration 1800 --route-label "ruta_real_mvp_lima3_lima2"
```

The script starts `ros2 bag record` in the background, stores the PID, and closes timed runs with SIGINT. It never uses `timeout` around `ros2 bag record`.

## Status

```bash
"codigo ottoguide/tools/hil/physical_mapping_status.sh"
```

Watch `/cmd_vel` publishers, `/scan`, `/utlidar/cloud`, TF, odom, map growth, SLAM warnings, and dynamic obstacles.

## Stop

```bash
"codigo ottoguide/tools/hil/physical_mapping_stop.sh"
```

This sends SIGINT to the recorded rosbag PID and does not kill drivers or unrelated processes.

## Finalize

```bash
"codigo ottoguide/tools/hil/physical_mapping_finalize.sh"
```

Finalize runs `ros2 bag info`, exports a raw map with `map_saver_cli` if `/map` is active, writes session `README.md`, file sizes, and hashes.

## Package And Copy

```bash
"codigo ottoguide/tools/hil/physical_mapping_package_for_transfer.sh"
```

The package is written to `/tmp/physical_mapping_route_<RUN_ID>.tar.gz`, and the script prints the Windows `scp` command.

## Map Cleaning

Raw files under `maps/raw/` are immutable evidence. Derived maps can be created under `maps/cleaned/`:

```bash
python3 "codigo ottoguide/tools/hil/physical_mapping_clean_map.py" \
  --input-yaml artifacts/physical_mapping_route_<RUN_ID>/maps/raw/ottoguide_route_real_<RUN_ID>.yaml \
  --output-dir artifacts/physical_mapping_route_<RUN_ID>/maps/cleaned \
  --crop 0 0 400 400
```

Any crop or isolated-pixel cleanup must be documented in `CLEANING_REPORT.md` and visually reviewed offline before future navigation work.

## What This Does Not Validate

- Autonomous navigation.
- AMCL localization quality.
- Safe physical Nav2 execution.
- Correct final waypoints.
- LiDAR inversion correction unless TF evidence proves it.

## Troubleshooting

- Missing `/scan` or `/utlidar/cloud`: stop before mapping and inspect LiDAR/bridge launch.
- Missing `/tf` or `/tf_static`: stop before mapping and inspect robot state/static transforms.
- Missing `/odom`: mapping can be diagnostic only; do not claim navigation readiness.
- Unexpected `/cmd_vel` publisher: report immediately and stop progression.
- `/map` missing at finalize: preserve rosbag and export offline later.
- Dynamic people/obstacles: document in session README and keep raw map unchanged.
