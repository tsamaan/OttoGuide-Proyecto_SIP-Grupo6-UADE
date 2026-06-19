# Synthetic IPC emitter

Offline development tool. Emits the same AF_UNIX `SOCK_DGRAM` protocol-version-1
datagrams the native tap (`unitree_capture_tap.cpp`) produces on
`/tmp/ottoguide_unitree_capture.sock`, without a robot, without ROS, and
without the Unitree SDK. Pure Python standard library.

Use it to exercise the ROS2 bridge node (`ottoguide_unitree_capture_bridge`)
or the protocol parser end-to-end on a development machine.

## Normal mode

```bash
python3 synthetic_ipc_emitter.py \
  --socket /tmp/ottoguide_unitree_capture.sock \
  --duration 10 \
  --lowstate-hz 50 \
  --secondary-imu-hz 100 \
  --sport-hz 10 \
  --health-hz 1
```

`--duration 0` (or negative) runs until `SIGINT`/`SIGTERM`, shutting down
cleanly and printing final counters.

All packet values are deterministic by default (neutral joystick: all axes
zero, `keys=0`; identity quaternion; gravity-only accelerometer) so repeated
runs are reproducible.

## Dry-run mode

```bash
python3 synthetic_ipc_emitter.py --dry-run --duration 1
```

Generates and JSON round-trips packets without opening a socket. Useful to
validate the tool itself on a machine where the bridge isn't running.

## Negative cases

Negative cases are never mixed into the normal stream — each run sends
**exactly one** malformed datagram and exits, so a single bad packet's effect
on the receiver can be observed in isolation:

```bash
python3 synthetic_ipc_emitter.py --negative-case truncated
python3 synthetic_ipc_emitter.py --negative-case invalid-json
python3 synthetic_ipc_emitter.py --negative-case invalid-version
python3 synthetic_ipc_emitter.py --negative-case nan
python3 synthetic_ipc_emitter.py --negative-case missing-field
python3 synthetic_ipc_emitter.py --negative-case wrong-type
```

Combine with `--dry-run` to print the malformed payload instead of sending it.
