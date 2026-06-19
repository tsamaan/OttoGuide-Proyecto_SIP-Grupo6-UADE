# Unitree Capture Bridge IPC Protocol v1

## Transport

- Direction: native tap to ROS receiver only.
- Socket: `AF_UNIX`, `SOCK_DGRAM`.
- Path: `/tmp/ottoguide_unitree_capture.sock`.
- Encoding: one UTF-8 JSON object per datagram.
- Maximum accepted datagram: 4096 bytes.
- The sender uses `MSG_DONTWAIT`; failed, partial, or oversized sends increment `n_drop`.

Every packet includes:

```json
{"v":1,"k":"packet_kind","t":123456789}
```

`t` is the tap receipt time in monotonic nanoseconds. It is used for age diagnostics only. ROS headers use the ROS clock at receipt.

## Packet kinds

### `lowstate`

Source: `rt/lowstate` only. Maximum output rate: 50 Hz.

Fields: `ch`, `tick`, `mm`, `lx`, `ly`, `rx`, `ry`, `keys`, `q`, `g`, `a`, and `rpy`.

The optional `rt/lf/lowstate` subscriber contributes only to the health counter `n_lf_ls`; it never supplies remote-control intent.

### `secondary_imu`

Source: `rt/secondary_imu`. Maximum output rate: 100 Hz.

Fields: quaternion `q` in SDK order `[w,x,y,z]`, gyroscope `g`, acceleration `a`, and `rpy`.

### `sport_state`

Source: `rt/sportmodestate`. Maximum output rate: 10 Hz.

Field: unsigned `fsm`.

### `health`

Maximum output rate: 1 Hz. Fields:

- `up`: tap uptime seconds.
- `n_ls`, `n_lf_ls`, `n_simu`, `n_sport`: native receive counters.
- `n_sent`: successful IPC datagrams.
- `n_drop`: failed, partial, or oversized IPC datagrams.

## Wireless remote layout

The installed Unitree header defines `REMOTE_DATA_RX` as a 40-byte union containing `BtnDataStruct`:

| Offset | Field |
|---:|---|
| 0 | `head[2]` |
| 2 | `BtnUnion btn` (`uint16_t`) |
| 4 | `float lx` |
| 8 | `float rx` |
| 12 | `float ry` |
| 16 | `float L2` |
| 20 | `float ly` |
| 24..39 | union padding |

The tap copies all 40 bytes into `unitree::common::REMOTE_DATA_RX`; it does not maintain a second guessed layout.

ROS `Joy` mapping:

```text
axes: [lx, ly, rx, ry]
buttons: [R1, L1, Start, Select, R2, L2, F1, F2,
          A, B, X, Y, Up, Right, Down, Left]
```

## ROS allowlist

| Packet | ROS topic | Type |
|---|---|---|
| `lowstate` | `/unitree/remote_joy` | `sensor_msgs/msg/Joy` |
| `lowstate` | `/unitree/lowstate_imu` | `sensor_msgs/msg/Imu` |
| `lowstate` | `/unitree/lowstate_summary` | `std_msgs/msg/String` |
| `secondary_imu` | `/unitree/secondary_imu` | `sensor_msgs/msg/Imu` |
| `sport_state` | `/unitree/fsm_state` | `std_msgs/msg/UInt32` |
| `health` plus receiver diagnostics | `/unitree/sdk_health` | `diagnostic_msgs/msg/DiagnosticArray` |

No other ROS publisher is created by this package.
