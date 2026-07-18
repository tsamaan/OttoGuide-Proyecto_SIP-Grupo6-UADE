#!/usr/bin/env python3
"""OttoGuide NB-HIL-WEB-R0 — recorder remoto persistente (FASE F).

STRICTLY PASSIVE / READ-ONLY:
  * Crea EXCLUSIVAMENTE DDS DataReader. Nunca DataWriter, LocoClient, SportClient,
    MotionSwitcher ni comando de movimiento. (Validado por AST en el static gate.)
  * Persiste telemetria a disco en chunks JSONL rotados, sobreviviendo al cierre de SSH.

Topics:
  rt/lowstate, rt/odommodestate, rt/lf/odommodestate, rt/utlidar/cloud_livox_mid360,
  rt/lf/bmsstate (SOLO si --enable-bms tras un probe exitoso).

Caps de persistencia: LowState<=100Hz, Odom<=100Hz, LF Odom todas, LiDAR metadata<=10Hz, BMS todas.
Cada registro lleva: session_id, sequence, receipt_monotonic_ns, receipt_utc, source_timestamp,
topic, phase.

LiDAR keyframes (nube completa comprimida zlib) cuando: dpos>=0.05m OR dyaw>=5deg OR
dt>=2s OR cambio de fase; maximo 2 nubes/seg; limite de disco DEFAULT_FULL_CLOUD_LIMIT.
Al superar el limite: se detienen SOLO los keyframes completos (metadata/lowstate/odom siguen)
y se registra CLOUD_STORAGE_LIMIT_REACHED.

Chunking: rotacion cada 10s; flush+fsync cada 1s; state file atomico; lock de instancia unica.

Uso:
  python ottoguide_remote_recorder.py --out <dir> --session <id> [--enable-bms] \
      [--phase-file <f>] [--cloud-limit-bytes N] [--duration S]
"""
from __future__ import annotations
import argparse, hashlib, json, math, os, signal, sys, threading, time, zlib
try:
    import fcntl  # POSIX (Companion). En Windows no existe -> fallback PID.
except ImportError:  # pragma: no cover
    fcntl = None

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ottoguide_common import (ensure_sdk_on_path, JOINTS, utc_now, monotonic_ns, read_phase,
                              number_or_none, scalar_or_none, round_or_none, angle_wrap,
                              decide_keyframe_trigger, bmsvoltage_or_none)

CHUNK_SECONDS = 10
FLUSH_SECONDS = 1
MAX_CLOUDS_PER_SEC = 2
DEFAULT_FULL_CLOUD_LIMIT = 2 * 1024 * 1024 * 1024  # 2 GiB
KF_DPOS_M = 0.05
KF_DYAW_DEG = 5.0
KF_DT_S = 2.0
CAP_LOWSTATE_HZ = 100.0
CAP_ODOM_HZ = 100.0
CAP_LIDAR_META_HZ = 10.0


def pointcloud_metadata(s):
    """Metadata COMPLETA de un PointCloud2 (FASE D2), sin el payload."""
    hdr = getattr(s, "header", None)
    stamp = getattr(hdr, "stamp", None)
    stamp_val = None
    if stamp is not None:
        sec = getattr(stamp, "sec", None)
        nanosec = getattr(stamp, "nanosec", None)
        if sec is not None:
            stamp_val = {"sec": sec, "nanosec": nanosec}
    fields = []
    for f in (getattr(s, "fields", []) or []):
        fields.append({
            "name": getattr(f, "name", None),
            "offset": getattr(f, "offset", None),
            "datatype": getattr(f, "datatype", None),
            "count": getattr(f, "count", None),
        })
    return {
        "header_stamp": stamp_val,
        "frame_id": str(getattr(hdr, "frame_id", "")) if hdr is not None else "",
        "height": getattr(s, "height", None),
        "width": getattr(s, "width", None),
        "is_bigendian": getattr(s, "is_bigendian", None),
        "point_step": getattr(s, "point_step", None),
        "row_step": getattr(s, "row_step", None),
        "is_dense": getattr(s, "is_dense", None),
        "fields": fields,
    }


def _first_temp(t):
    if t is None:
        return None
    if isinstance(t, (list, tuple)):
        for v in t:
            if v is not None:
                return v
        return None
    try:
        return list(t)[0]
    except TypeError:
        return t


class Chunker:
    """Escribe registros JSONL en chunks rotados cada CHUNK_SECONDS, con flush/fsync 1Hz."""

    def __init__(self, out_dir, kind):
        self.dir = os.path.join(out_dir, kind)
        os.makedirs(self.dir, exist_ok=True)
        self.kind = kind
        self.fh = None
        self.chunk_start = 0.0
        self.last_flush = 0.0
        self.index = 0
        self.count = 0

    def _open_new(self, now):
        if self.fh:
            self._close()
        self.index += 1
        name = f"{self.kind}_{self.index:06d}.jsonl"
        self.path = os.path.join(self.dir, name)
        self.fh = open(self.path, "a", encoding="utf-8", buffering=1)
        self.chunk_start = now

    def _close(self):
        try:
            self.fh.flush(); os.fsync(self.fh.fileno()); self.fh.close()
        except OSError:
            pass
        self.fh = None

    def write(self, rec, now):
        if self.fh is None or (now - self.chunk_start) >= CHUNK_SECONDS:
            self._open_new(now)
        self.fh.write(json.dumps(rec, separators=(",", ":")) + "\n")
        self.count += 1
        if (now - self.last_flush) >= FLUSH_SECONDS:
            try:
                self.fh.flush(); os.fsync(self.fh.fileno())
            except OSError:
                pass
            self.last_flush = now

    def close(self):
        if self.fh:
            self._close()


def dir_size(path):
    total = 0
    for base, _, fs in os.walk(path):
        for n in fs:
            try:
                total += os.path.getsize(os.path.join(base, n))
            except OSError:
                pass
    return total


def _pid_alive_is_recorder(pid):
    """True si `pid` esta vivo Y su command line corresponde al recorder."""
    try:
        pid = int(pid)
    except (TypeError, ValueError):
        return False
    cmd_path = f"/proc/{pid}/cmdline"
    if not os.path.exists(cmd_path):
        return False  # PID ausente -> no esta vivo
    try:
        with open(cmd_path, "rb") as f:
            cmd = f.read().replace(b"\x00", b" ").decode(errors="ignore")
        return "ottoguide_remote_recorder" in cmd  # comando corresponde al recorder
    except OSError:
        return False


def acquire_lock(out_dir):
    """FASE F1: lock de instancia unica. Prefiere fcntl.flock; si no, PID con recuperacion
    SOLO cuando el PID esta ausente o su comando no es el recorder. Nunca borra un lock vivo.
    Devuelve (fd_or_handle, lock_path)."""
    lock = os.path.join(out_dir, "recorder.lock")
    if fcntl is not None:
        fd = os.open(lock, os.O_CREAT | os.O_RDWR)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            os.close(fd)
            print(f"[recorder] another instance holds flock on {lock}; exiting", file=sys.stderr)
            sys.exit(3)
        os.ftruncate(fd, 0)
        os.write(fd, str(os.getpid()).encode())
        os.fsync(fd)
        return fd, lock
    # Fallback PID (p.ej. Windows): recuperar solo si el titular no esta vivo/no es recorder.
    if os.path.exists(lock):
        try:
            prev = open(lock).read().strip()
        except OSError:
            prev = ""
        if _pid_alive_is_recorder(prev):
            print(f"[recorder] live recorder pid={prev} holds {lock}; exiting", file=sys.stderr)
            sys.exit(3)
        # titular ausente o comando distinto -> recuperar el lock huerfano
    fd = os.open(lock, os.O_CREAT | os.O_TRUNC | os.O_WRONLY)
    os.write(fd, str(os.getpid()).encode())
    return fd, lock


def write_state(out_dir, state):
    """State file atomico (write temp + os.replace)."""
    tmp = os.path.join(out_dir, "recorder_state.json.tmp")
    dst = os.path.join(out_dir, "recorder_state.json")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(state, f)
        f.flush(); os.fsync(f.fileno())
    os.replace(tmp, dst)


_stop_event = threading.Event()


def _install_signal_handlers():
    """FASE F1: SIGINT/SIGTERM -> stop_event (salida limpia del loop, cierre de chunks)."""
    def _handler(signum, _frame):
        _stop_event.set()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            signal.signal(sig, _handler)
        except (ValueError, OSError):
            pass  # p.ej. si no es el hilo principal


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--session", required=True)
    ap.add_argument("--enable-bms", action="store_true")
    ap.add_argument("--phase-file", default=None)
    ap.add_argument("--cloud-limit-bytes", type=int, default=DEFAULT_FULL_CLOUD_LIMIT)
    ap.add_argument("--duration", type=float, default=0.0, help="0 = hasta SIGINT")
    args = ap.parse_args()

    os.makedirs(args.out, exist_ok=True)
    lock_fd, lock_path = acquire_lock(args.out)
    _install_signal_handlers()
    phase_file = args.phase_file or os.path.join(args.out, "current_phase.txt")

    sdk = ensure_sdk_on_path()
    if not sdk:
        print("[recorder] unitree_sdk2_python not found (resolve_sdk_path)", file=sys.stderr)
        sys.exit(4)
    from cyclonedds.domain import DomainParticipant
    from cyclonedds.topic import Topic
    from cyclonedds.sub import DataReader
    from cyclonedds.qos import Qos, Policy
    from unitree_sdk2py.idl.unitree_hg.msg.dds_ import LowState_
    from unitree_sdk2py.idl.unitree_go.msg.dds_ import SportModeState_
    from unitree_sdk2py.idl.sensor_msgs.msg.dds_ import PointCloud2_
    BmsState_ = None
    if args.enable_bms:
        try:
            from unitree_sdk2py.idl.unitree_hg.msg.dds_ import BmsState_ as _Bms
            BmsState_ = _Bms
        except Exception as e:  # noqa
            print(f"[recorder] BMS type unavailable, continuing without: {e}", file=sys.stderr)

    BE = Qos(Policy.Reliability.BestEffort, Policy.Durability.Volatile, Policy.History.KeepLast(16))
    dp = DomainParticipant(0)
    # READ-ONLY: solo DataReader.
    r_low = DataReader(dp, Topic(dp, "rt/lowstate", LowState_), qos=BE)
    r_odom = DataReader(dp, Topic(dp, "rt/odommodestate", SportModeState_), qos=BE)
    r_lf = DataReader(dp, Topic(dp, "rt/lf/odommodestate", SportModeState_), qos=BE)
    r_cloud = DataReader(dp, Topic(dp, "rt/utlidar/cloud_livox_mid360", PointCloud2_), qos=BE)
    r_bms = DataReader(dp, Topic(dp, "rt/lf/bmsstate", BmsState_), qos=BE) if BmsState_ else None

    ch_low = Chunker(args.out, "lowstate")
    ch_odom = Chunker(args.out, "odom")
    ch_lf = Chunker(args.out, "lf_odom")
    ch_lidar_meta = Chunker(args.out, "lidar_meta")
    ch_bms = Chunker(args.out, "bms")
    ch_events = Chunker(args.out, "events")
    cloud_dir = os.path.join(args.out, "lidar_clouds")
    os.makedirs(cloud_dir, exist_ok=True)

    seq = 0
    counts = {"lowstate": 0, "odom": 0, "lf_odom": 0, "lidar_meta": 0, "bms": 0, "clouds": 0}
    last_write = {"lowstate": 0.0, "odom": 0.0, "lidar_meta": 0.0}
    last_cloud_t = 0.0
    cloud_second = {"sec": 0, "n": 0}
    last_cloud_pos = None
    last_cloud_imu_yaw = None            # FASE D1: orientacion desde IMU, NO yaw_speed
    latest_imu_yaw_rad = None            # ultima orientacion yaw (rad) del LowState IMU
    last_phase = None
    cloud_limit_hit = False
    # FASE D3: contador incremental de bytes de nubes (no os.walk por keyframe).
    cloud_bytes_written = dir_size(cloud_dir)  # tamano real al iniciar (reanudacion)
    last_wireless_sha = None             # FASE E: firma previa del control manual
    heartbeat = 0.0
    start = time.time()
    # FASE A1 (R0B hotfix): latest_odom vive fuera del while principal y NUNCA se
    # reinicia a None por iteracion. Solo un mensaje nuevo en rt/odommodestate lo
    # actualiza. Los keyframes LiDAR pueden así usar la ultima odometria conocida
    # aunque no llegue muestra de odom en la misma iteracion que la nube.
    latest_odom = None

    def rec_common(topic, source_ts):
        nonlocal seq
        seq += 1
        return {
            "session_id": args.session, "sequence": seq,
            "receipt_monotonic_ns": monotonic_ns(), "receipt_utc": utc_now(),
            "source_timestamp": source_ts, "topic": topic, "phase": phase,
        }

    print(f"[recorder] session={args.session} out={args.out} sdk={sdk} bms={'on' if r_bms else 'off'}", flush=True)
    try:
        while not _stop_event.is_set():
            now = time.time()
            phase = read_phase(phase_file)
            phase_changed = phase != last_phase
            if phase_changed:
                ev = {"session_id": args.session, "receipt_utc": utc_now(),
                      "event": "PHASE_MARKER", "phase": phase, "prev": last_phase}
                ch_events.write(ev, now)
                last_phase = phase

            # ---- LowState (cap 100 Hz) ----
            for s in r_low.take(N=32):
                if (now - last_write["lowstate"]) < (1.0 / CAP_LOWSTATE_HZ):
                    continue
                last_write["lowstate"] = now
                motors = []
                ms = getattr(s, "motor_state", []) or []
                for idx, name, group in JOINTS:
                    if idx >= len(ms):
                        break
                    m = ms[idx]
                    q = number_or_none(m, "q")
                    motors.append({
                        "index": idx, "name": name, "group": group,
                        "q_rad": round_or_none(q, 5),
                        "q_deg": round_or_none(q * 180.0 / math.pi, 2) if q is not None else None,
                        "dq": round_or_none(number_or_none(m, "dq"), 5),
                        "ddq": round_or_none(number_or_none(m, "ddq"), 5),
                        "tau_est": round_or_none(number_or_none(m, "tau_est"), 5),
                        "temperature": scalar_or_none(getattr(m, "temperature", None)),
                    })
                imu_obj = getattr(s, "imu_state", None)
                imu = {}
                if imu_obj is not None:
                    rpy = list(getattr(imu_obj, "rpy", []) or [])
                    imu = {
                        "quaternion": [round(x, 5) for x in (getattr(imu_obj, "quaternion", []) or [])],
                        "gyroscope": [round(x, 5) for x in (getattr(imu_obj, "gyroscope", []) or [])],
                        "accelerometer": [round(x, 5) for x in (getattr(imu_obj, "accelerometer", []) or [])],
                        "rpy_deg": [round(x * 180.0 / math.pi, 2) for x in rpy],
                    }
                    # FASE D1: yaw de orientacion (rad) desde el IMU (rpy[2]), no yaw_speed.
                    if len(rpy) >= 3 and isinstance(rpy[2], (int, float)):
                        latest_imu_yaw_rad = angle_wrap(rpy[2])
                # ---- FASE E: firma del control manual (wireless_remote) ----
                wr = getattr(s, "wireless_remote", None)
                wr_len, wr_sha, wr_changed = None, None, None
                if wr is not None:
                    try:
                        wr_bytes = bytes(wr) if not isinstance(wr, (bytes, bytearray)) else bytes(wr)
                    except TypeError:
                        wr_bytes = bytes(list(wr))
                    wr_len = len(wr_bytes)
                    wr_sha = hashlib.sha256(wr_bytes).hexdigest()
                    wr_changed = (last_wireless_sha is not None and wr_sha != last_wireless_sha)
                    last_wireless_sha = wr_sha
                rec = rec_common("rt/lowstate", None)
                rec["mode_machine"] = getattr(s, "mode_machine", None)
                rec["motors"] = motors
                rec["imu"] = imu
                # No se interpretan comandos ni se convierten en autoridad de movimiento.
                rec["wireless_remote_length"] = wr_len
                rec["wireless_remote_sha256"] = wr_sha
                rec["wireless_remote_changed"] = wr_changed
                ch_low.write(rec, now)
                counts["lowstate"] += 1

            # ---- odom / lf_odom ----
            def odom_payload(sample):
                return {
                    "position": [round_or_none(scalar_or_none(x), 4) for x in (list(getattr(sample, "position", []) or []))],
                    "velocity": [round_or_none(scalar_or_none(x), 4) for x in (list(getattr(sample, "velocity", []) or []))],
                    "yaw_speed": round_or_none(number_or_none(sample, "yaw_speed"), 4),
                    "mode": getattr(sample, "mode", None),
                }
            for s in r_odom.take(N=32):
                latest_odom = odom_payload(s)
                if (now - last_write["odom"]) < (1.0 / CAP_ODOM_HZ):
                    continue
                last_write["odom"] = now
                rec = rec_common("rt/odommodestate", None)
                rec["odom"] = latest_odom
                ch_odom.write(rec, now)
                counts["odom"] += 1
            for s in r_lf.take(N=32):  # LF Odom: todas
                rec = rec_common("rt/lf/odommodestate", None)
                rec["lf_odom"] = odom_payload(s)
                ch_lf.write(rec, now)
                counts["lf_odom"] += 1

            # ---- BMS: todas ----
            if r_bms:
                for s in r_bms.take(N=8):
                    rec = rec_common("rt/lf/bmsstate", None)
                    # Se persiste el CRUDO descubierto (sin asumir unidades); la conversion
                    # canonica/escala vive en el bridge segun bms_probe.json. null-real.
                    rec["bms_raw"] = {
                        # FASE A2: bmsvoltage escalar o secuencia (primer positivo candidato).
                        "bmsvoltage": bmsvoltage_or_none(getattr(s, "bmsvoltage", None))
                                      or bmsvoltage_or_none(getattr(s, "voltage", None)),
                        "current": number_or_none(s, "current"),
                        "soc": number_or_none(s, "soc"),
                        "soh": number_or_none(s, "soh"),
                        "cycle": number_or_none(s, "cycle"),
                        "cell_vol": [scalar_or_none(c) for c in list(getattr(s, "cell_vol", []) or [])],
                        "temperature": [scalar_or_none(t) for t in list(getattr(s, "temperature", []) or [])],
                        "manufacturer_date": getattr(s, "manufacturer_date", None),
                    }
                    ch_bms.write(rec, now)
                    counts["bms"] += 1

            # ---- LiDAR: metadata (cap 10 Hz) + keyframes de nube completa ----
            for s in r_cloud.take(N=4):
                pc_meta = pointcloud_metadata(s)
                h = pc_meta["height"] or 0
                w = pc_meta["width"] or 0
                points = int(h * w)
                if (now - last_write["lidar_meta"]) >= (1.0 / CAP_LIDAR_META_HZ):
                    last_write["lidar_meta"] = now
                    rec = rec_common("rt/utlidar/cloud_livox_mid360", None)
                    rec["lidar"] = {"points": points, "frame_id": pc_meta["frame_id"],
                                    "point_step": pc_meta["point_step"],
                                    "fields": [f["name"] for f in pc_meta["fields"]]}
                    ch_lidar_meta.write(rec, now)
                    counts["lidar_meta"] += 1

                # ---- keyframe decision (FASE D1: yaw IMU, no yaw_speed; FASE A1: pos
                # puede venir de una iteracion anterior porque latest_odom persiste) ----
                pos = latest_odom["position"] if latest_odom else None
                imu_yaw = latest_imu_yaw_rad
                trig = decide_keyframe_trigger(now, phase_changed, last_cloud_t, pos,
                                                last_cloud_pos, imu_yaw, last_cloud_imu_yaw,
                                                KF_DT_S, KF_DPOS_M, KF_DYAW_DEG)
                if trig:
                    # rate cap: max 2 clouds/sec
                    cur_sec = int(now)
                    if cloud_second["sec"] != cur_sec:
                        cloud_second["sec"] = cur_sec; cloud_second["n"] = 0
                    if cloud_second["n"] >= MAX_CLOUDS_PER_SEC:
                        pass
                    elif cloud_limit_hit or cloud_bytes_written >= args.cloud_limit_bytes:
                        if not cloud_limit_hit:
                            cloud_limit_hit = True
                            ch_events.write({"session_id": args.session, "receipt_utc": utc_now(),
                                             "event": "CLOUD_STORAGE_LIMIT_REACHED",
                                             "limit_bytes": args.cloud_limit_bytes,
                                             "cloud_bytes_written": cloud_bytes_written}, now)
                        # metadata/lowstate/odom continuan; solo se detienen keyframes completos
                    else:
                        raw = getattr(s, "data", b"") or b""
                        raw_bytes = bytes(raw) if not isinstance(raw, (bytes, bytearray)) else bytes(raw)
                        comp = zlib.compress(raw_bytes, 6)
                        seq_cloud = counts["clouds"] + 1
                        cname = f"cloud_{seq_cloud:06d}.pc2.zlib"
                        with open(os.path.join(cloud_dir, cname), "wb") as cf:
                            cf.write(comp); cf.flush(); os.fsync(cf.fileno())
                        cloud_bytes_written += len(comp)   # FASE D3: contador incremental
                        meta = rec_common("rt/utlidar/cloud_livox_mid360:KEYFRAME", None)
                        meta.update({
                            "cloud_file": cname, "compression": "zlib",
                            "raw_bytes": len(raw_bytes), "compressed_bytes": len(comp),
                            "points": points, "trigger": trig,
                            "odom_position": pos,
                            "odom_velocity": latest_odom["velocity"] if latest_odom else None,
                            "imu_yaw_rad": round_or_none(imu_yaw, 5),
                        })
                        meta.update(pc_meta)  # header_stamp/frame_id/height/width/is_bigendian/point_step/row_step/is_dense/fields
                        ch_events.write(meta, now)
                        counts["clouds"] += 1
                        cloud_second["n"] += 1
                        last_cloud_t = now
                        last_cloud_pos = pos
                        last_cloud_imu_yaw = imu_yaw

            # ---- heartbeat / state (1 Hz) ----
            if (now - heartbeat) >= 1.0:
                heartbeat = now
                write_state(args.out, {
                    "session_id": args.session, "utc": utc_now(), "pid": os.getpid(),
                    "phase": phase, "counts": counts, "cloud_limit_hit": cloud_limit_hit,
                    "cloud_bytes": cloud_bytes_written, "uptime_s": round(now - start, 1),
                    "last_seq": seq,
                })

            if args.duration and (now - start) >= args.duration:
                break
            time.sleep(0.003)
    except KeyboardInterrupt:
        pass
    finally:
        # Cierre limpio: cerrar chunks (flush+fsync en Chunker._close), estado final, liberar lock.
        for c in (ch_low, ch_odom, ch_lf, ch_lidar_meta, ch_bms, ch_events):
            c.close()
        write_state(args.out, {"session_id": args.session, "utc": utc_now(), "pid": os.getpid(),
                               "phase": last_phase, "counts": counts, "final": True,
                               "cloud_bytes": cloud_bytes_written, "last_seq": seq,
                               "clean_shutdown": True})
        try:
            if fcntl is not None:
                fcntl.flock(lock_fd, fcntl.LOCK_UN)
            os.close(lock_fd)
            os.unlink(lock_path)
        except OSError:
            pass
        print(f"[recorder] stopped cleanly. counts={counts}", flush=True)


if __name__ == "__main__":
    main()
