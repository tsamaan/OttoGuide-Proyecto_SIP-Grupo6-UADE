#!/usr/bin/env python3
"""OttoGuide NB-HIL-WEB-R0 — bridge remoto read-only DDS -> HTTP/WebSocket (FASE G).

STRICTLY PASSIVE / READ-ONLY:
  * Crea EXCLUSIVAMENTE DDS DataReader. Nunca DataWriter, LocoClient, SportClient ni
    MotionSwitcher. La ausencia de writers se valida por AST/imports/calls en el static gate
    y por inventario de proceso en runtime — no por un simple contador ficticio.
  * Endpoints permitidos: GET /health, GET /status, GET /content/script,
    GET /telemetry/backfill, WS /ws/telemetry.
  * POST/PUT/PATCH/DELETE -> HTTP 405 {"detail":"READ_ONLY_DEMO"}.

Cada frame lleva: session_id, seq, server_utc, server_monotonic_ns, availability,
source_profile=REAL. Ring buffer >=180 s y >=1800 frames. El stream WS (10 Hz) tambien se
persiste a disco (para respaldo/backfill).

availability se deriva validando el dato real; la card/grafico de BMS y Energia solo se
habilitan si el probe (FASE H) marco bms=true (archivo bms_probe.json).

Uso:
  python ottoguide_readonly_bridge.py --session <id> --out <dir> [--host 127.0.0.1] [--port 8000]
"""
from __future__ import annotations
import argparse, json, math, os, signal, sys, threading, time
from collections import deque

# NB-HIL-CONN-R1 fix: con `from __future__ import annotations`, la anotacion `sock: WebSocket`
# del endpoint /ws/telemetry queda como string y FastAPI la resuelve con get_type_hints contra
# los globals del MODULO. WebSocket se importaba solo dentro de make_app() (scope local), asi que
# la resolucion fallaba y el handshake WS era rechazado con HTTP 403. Importarlo a nivel de modulo
# hace que get_type_hints reconozca el parametro WebSocket y el handshake proceda.
# Import perezoso: solo cuando fastapi este disponible (el bridge se ejecuta en un venv con fastapi;
# recorder/probe no importan este modulo). No crea entidades DDS ni de movimiento.
try:  # pragma: no cover - depende del entorno remoto
    from fastapi import WebSocket, Request
except Exception:  # noqa - entorno sin fastapi (p.ej. import del modulo por un test puro)
    WebSocket = Request = None  # type: ignore

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ottoguide_common import (ensure_sdk_on_path, JOINTS, utc_now, monotonic_ns,
                              number_or_none, scalar_or_none, round_or_none,
                              bmsvoltage_or_none, positive_numeric_or_empty,
                              relative_cell_sum_error)

RING_MIN_SECONDS = 180
RING_MIN_FRAMES = 1800

_lock = threading.Lock()
_state = {
    "lowstate": None, "imu": None, "mode_machine": None,
    "odom": {}, "lf_odom": {}, "lidar": {}, "bms": None,
    "counts": {"lowstate": 0, "odom": 0, "lf_odom": 0, "lidar": 0, "bms": 0},
    "hz": {"lowstate_hz": 0.0, "odom_hz": 0.0, "lf_odom_hz": 0.0, "lidar_hz": 0.0},
    "last_lidar_calc": 0.0,
}
# Invariante read-only: contador de apoyo (NO es la unica prueba; ver static gate + AST).
_dds_writers_created = 0
_ring = deque()           # (seq, frame)
_seq = 0
_session_id = None
_bms_ok = False           # habilitado solo si el probe valido el BMS
# Escalas de conversion fisica decididas por el probe (FASE C2). None hasta cargarse.
_bms_cfg = {"voltage_field": "bmsvoltage", "voltage_scale": 1.0, "current_scale": 1.0,
            "cell_scale": 1.0, "temperature_scale": 1.0}


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


def _collector(sdk_types):
    (DomainParticipant, Topic, DataReader, Qos, Policy,
     LowState_, SportModeState_, PointCloud2_, BmsState_) = sdk_types
    BE = Qos(Policy.Reliability.BestEffort, Policy.Durability.Volatile, Policy.History.KeepLast(8))
    dp = DomainParticipant(0)
    r_low = DataReader(dp, Topic(dp, "rt/lowstate", LowState_), qos=BE)
    r_odom = DataReader(dp, Topic(dp, "rt/odommodestate", SportModeState_), qos=BE)
    r_lf = DataReader(dp, Topic(dp, "rt/lf/odommodestate", SportModeState_), qos=BE)
    r_cloud = DataReader(dp, Topic(dp, "rt/utlidar/cloud_livox_mid360", PointCloud2_), qos=BE)
    r_bms = DataReader(dp, Topic(dp, "rt/lf/bmsstate", BmsState_), qos=BE) if BmsState_ else None

    win_start = time.time()
    win = {"lowstate": 0, "odom": 0, "lf_odom": 0, "lidar": 0}
    while True:
        for s in r_low.take(N=16):
            win["lowstate"] += 1
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
            with _lock:
                _state["lowstate"] = motors
                _state["imu"] = imu
                _state["mode_machine"] = getattr(s, "mode_machine", None)

        def _odom(sample):
            return {
                "position": [round_or_none(scalar_or_none(x), 4) for x in (list(getattr(sample, "position", []) or []))],
                "velocity": [round_or_none(scalar_or_none(x), 4) for x in (list(getattr(sample, "velocity", []) or []))],
                "yaw_speed": round_or_none(number_or_none(sample, "yaw_speed"), 4),
                "mode": getattr(sample, "mode", None),
            }
        for s in r_odom.take(N=16):
            win["odom"] += 1
            with _lock:
                _state["odom"] = _odom(s)
        for s in r_lf.take(N=16):
            win["lf_odom"] += 1
            with _lock:
                _state["lf_odom"] = _odom(s)
        if r_bms:
            for s in r_bms.take(N=8):
                # FASE A2: bmsvoltage escalar o secuencia (primer positivo candidato).
                vfield = _bms_cfg.get("voltage_field") or "bmsvoltage"
                raw_v = bmsvoltage_or_none(getattr(s, vfield, None))
                if raw_v is None:
                    raw_v = (bmsvoltage_or_none(getattr(s, "bmsvoltage", None))
                             or bmsvoltage_or_none(getattr(s, "voltage", None)))
                with _lock:
                    # Se guarda crudo + escalas; la conversion canonica ocurre en build_frame.
                    _state["bms"] = {
                        "raw_voltage": raw_v,
                        "raw_current": number_or_none(s, "current"),
                        "soc": number_or_none(s, "soc"),
                        "soh": number_or_none(s, "soh"),
                        "cycle": number_or_none(s, "cycle"),
                        "manufacturer_date": getattr(s, "manufacturer_date", None),
                        "state": list(getattr(s, "bmsstate", []) or []) if isinstance(getattr(s, "bmsstate", None), (list, tuple)) else ([getattr(s, "bmsstate")] if number_or_none(s, "bmsstate") is not None else []),
                        "raw_cells": [c for c in list(getattr(s, "cell_vol", []) or []) if scalar_or_none(c) is not None],
                        "raw_temps": [t for t in list(getattr(s, "temperature", []) or []) if scalar_or_none(t) is not None],
                    }
                    _state["counts"]["bms"] += 1

        for s in r_cloud.take(N=4):
            win["lidar"] += 1
            now = time.time()
            if now - _state["last_lidar_calc"] >= 0.5:
                _state["last_lidar_calc"] = now
                h = getattr(s, "height", 0) or 0
                w = getattr(s, "width", 0) or 0
                fields = [getattr(f, "name", "?") for f in (getattr(s, "fields", []) or [])]
                frame_id = str(getattr(getattr(s, "header", None), "frame_id", ""))
                with _lock:
                    _state["lidar"] = {"points": int(h * w), "fields": fields, "frame_id": frame_id,
                                       "point_step": getattr(s, "point_step", None), "updated": now}

        now = time.time()
        if now - win_start >= 1.0:
            dt = now - win_start
            with _lock:
                _state["hz"] = {"lowstate_hz": round(win["lowstate"] / dt, 1),
                                "odom_hz": round(win["odom"] / dt, 1),
                                "lf_odom_hz": round(win["lf_odom"] / dt, 1),
                                "lidar_hz": round(win["lidar"] / dt, 1)}
                for k in win:
                    _state["counts"][k] += win[k]
            win = {"lowstate": 0, "odom": 0, "lf_odom": 0, "lidar": 0}
            win_start = now
        time.sleep(0.003)


def canonical_bms(raw):
    """FASE C3: contrato canonico del BMS. Convierte crudo->fisico con las escalas del probe.
    power_w = voltage_v * current_a (conserva el signo). Ausencias permanecen null."""
    if not _bms_ok or not isinstance(raw, dict):
        return None, None, None
    vs = _bms_cfg.get("voltage_scale") or 1.0
    cs = _bms_cfg.get("current_scale") or 1.0
    cells_sc = _bms_cfg.get("cell_scale") or 1.0
    ts = _bms_cfg.get("temperature_scale")
    v = raw.get("raw_voltage")
    a = raw.get("raw_current")
    voltage_v = round(v * vs, 3) if isinstance(v, (int, float)) else None
    current_a = round(a * cs, 3) if isinstance(a, (int, float)) else None
    power_w = round(voltage_v * current_a, 2) if (voltage_v is not None and current_a is not None) else None
    # FASE A2: ignora no numericos, cero y negativos (una celda Li-ion nunca es <=0V).
    cells_valid = positive_numeric_or_empty(raw.get("raw_cells") or [])
    cells = [round(c * cells_sc, 3) for c in cells_valid]
    temps = ([round(t * ts, 2) for t in (raw.get("raw_temps") or []) if isinstance(t, (int, float))]
             if ts else [])
    bms = {
        "soc": raw.get("soc"), "soh": raw.get("soh"),
        "voltage_v": voltage_v, "current_a": current_a, "power_w": power_w,
        "temperature_c": temps, "cell_vol_v": cells,
        # FASE A2: no asumir que la escala es correcta solo porque entra en rango.
        "relative_cell_sum_error": relative_cell_sum_error(voltage_v, cells),
        "cycle": raw.get("cycle"), "manufacturer_date": raw.get("manufacturer_date"),
        "state": raw.get("state") or [],
    }
    return bms, voltage_v, current_a


def _availability(fr):
    imu = fr.get("imu") or {}
    imu_ok = any(isinstance(imu.get(k), list) and any(isinstance(x, (int, float)) for x in imu.get(k))
                 for k in ("rpy_deg", "accelerometer", "gyroscope"))
    bms = fr.get("bms")
    bms_ok = _bms_ok and isinstance(bms, dict) and isinstance(bms.get("soc"), (int, float))
    v, a = fr.get("power_v"), fr.get("power_a")
    energy_ok = bms_ok and (isinstance(v, (int, float)) or isinstance(a, (int, float)))
    odom = fr.get("odom") or {}
    return {"imu": bool(imu_ok), "energy": bool(energy_ok), "bms": bool(bms_ok),
            "odom": bool(odom.get("position") or odom.get("velocity")),
            "lidar": bool((fr.get("lidar") or {}).get("points")),
            "motors": bool(fr.get("motors"))}


def build_frame():
    global _seq
    with _lock:
        motors = _state["lowstate"] or []
        imu = _state["imu"] or {}
        lidar = dict(_state["lidar"])
        hz = dict(_state["hz"])
        odom = dict(_state["odom"])
        lf_odom = dict(_state["lf_odom"])
        mode_machine = _state["mode_machine"]
        raw_bms = _state["bms"] if _bms_ok else None
        _seq += 1
        seq = _seq
    if lidar.get("updated"):
        lidar["age_s"] = round(time.time() - lidar.pop("updated"), 2)
    bms, power_v, power_a = canonical_bms(raw_bms)
    fr = {
        "timestamp": time.time(), "fsm_state": "OBSERVING", "current_waypoint_id": "N/A",
        "battery_level": None, "nlp_intent": "DISABLED", "nlp_source_pipeline": "N/A",
        "nlp_answer_preview": "", "robot": "G1", "read_only_demo": True,
        "mode_machine": mode_machine, "motors": motors, "imu": imu,
        # FASE C3: power_v/power_a reflejan el BMS canonico; null cuando el probe no paso.
        "power_v": power_v, "power_a": power_a, "foot_force": None, "bms": bms,
        "odom": odom, "lf_odom": lf_odom, "lidar": lidar, "rates": hz,
        "session_id": _session_id, "seq": seq, "server_utc": utc_now(),
        "server_monotonic_ns": monotonic_ns(), "source_profile": "REAL",
    }
    fr["availability"] = _availability(fr)
    return fr


def ring_add(fr, persist_fh):
    with _lock:
        _ring.append((fr["seq"], fr))
        # mantener >=180s Y >=1800 frames
        now = fr["timestamp"]
        while len(_ring) > RING_MIN_FRAMES and (now - _ring[0][1]["timestamp"]) > RING_MIN_SECONDS:
            _ring.popleft()
    if persist_fh:
        persist_fh.write(json.dumps(fr, separators=(",", ":")) + "\n")


def backfill(after_seq, limit):
    with _lock:
        return [fr for (s, fr) in _ring if s > after_seq][:limit]


STATUS = {
    "state": "observing", "source_profile": "REAL", "operational_ready": False,
    "readiness_errors": ["READ_ONLY: movement authority unavailable"],
    "navigation_backend_resolved": "disabled", "navigation_started": False,
    "script_loaded": True, "script_version": "observability-r0", "script_waypoint_count": 0,
}


def make_app():
    from fastapi import FastAPI, WebSocket, Request
    from fastapi.responses import JSONResponse
    from fastapi.middleware.cors import CORSMiddleware
    app = FastAPI(title="OttoGuide read-only observability bridge")
    app.add_middleware(CORSMiddleware, allow_origins=["http://127.0.0.1:5173", "http://localhost:5173"],
                       allow_credentials=False, allow_methods=["GET"], allow_headers=["*"])

    @app.middleware("http")
    async def _block_mutations(request: Request, call_next):
        if request.method in ("POST", "PUT", "PATCH", "DELETE"):
            return JSONResponse(status_code=405, content={"detail": "READ_ONLY_DEMO"})
        return await call_next(request)

    @app.get("/health")
    async def health():
        with _lock:
            counts = dict(_state["counts"]); hz = dict(_state["hz"]); ring_n = len(_ring)
        return {"status": "ok", "read_only_demo": True, "source_profile": "REAL",
                "dds_writers_created": _dds_writers_created, "session_id": _session_id,
                "seq": _seq, "ring_frames": ring_n, "bms_enabled": _bms_ok,
                "counts": counts, "rates": hz}

    @app.get("/status")
    async def status():
        return STATUS

    @app.get("/content/script")
    async def script():
        return {"version": "observability-r0", "waypoints": [], "read_only_demo": True}

    @app.get("/telemetry/backfill")
    async def tb(after_seq: int = 0, limit: int = 1800):
        return backfill(after_seq, min(limit, RING_MIN_FRAMES * 2))

    @app.websocket("/ws/telemetry")
    async def ws(sock: WebSocket):
        import asyncio
        await sock.accept()
        try:
            while True:
                await sock.send_text(json.dumps(_LATEST["frame"] or build_frame()))
                await asyncio.sleep(0.1)
        except Exception:
            return

    return app


_LATEST = {"frame": None}


_PERSIST = {"fh": None}
_STOP = threading.Event()


def _emitter(out_dir):
    """Genera un frame a 10 Hz, lo agrega al ring y lo persiste; el WS envia _LATEST."""
    persist = open(os.path.join(out_dir, "ws_stream.jsonl"), "a", encoding="utf-8", buffering=1)
    _PERSIST["fh"] = persist
    last_fsync = 0.0
    try:
        while not _STOP.is_set():
            fr = build_frame()
            _LATEST["frame"] = fr
            ring_add(fr, persist)
            now = time.time()
            if now - last_fsync >= 1.0:
                try:
                    persist.flush(); os.fsync(persist.fileno())
                except OSError:
                    pass
                last_fsync = now
            time.sleep(0.1)
    finally:
        _close_persist()


def _close_persist():
    """FASE F2: cierre limpio de ws_stream.jsonl (flush + fsync + close)."""
    fh = _PERSIST.get("fh")
    if fh:
        try:
            fh.flush(); os.fsync(fh.fileno()); fh.close()
        except OSError:
            pass
        _PERSIST["fh"] = None


def main():
    global _session_id, _bms_ok
    ap = argparse.ArgumentParser()
    ap.add_argument("--session", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--bms-probe", default=None, help="ruta a bms_probe.json (habilita BMS si accepted)")
    args = ap.parse_args()
    os.makedirs(args.out, exist_ok=True)
    _session_id = args.session

    probe_path = args.bms_probe or os.path.join(args.out, "bms_probe.json")
    if os.path.isfile(probe_path):
        try:
            probe = json.load(open(probe_path))
            _bms_ok = bool(probe.get("accepted"))
            if _bms_ok:
                for k in ("voltage_field", "voltage_scale", "current_scale", "cell_scale", "temperature_scale"):
                    if probe.get(k) is not None:
                        _bms_cfg[k] = probe[k]
        except Exception:
            _bms_ok = False
    print(f"[bridge] session={_session_id} bms_enabled={_bms_ok} bms_cfg={_bms_cfg}", flush=True)

    sdk = ensure_sdk_on_path()
    if not sdk:
        print("[bridge] unitree_sdk2_python not found", file=sys.stderr); sys.exit(4)
    from cyclonedds.domain import DomainParticipant
    from cyclonedds.topic import Topic
    from cyclonedds.sub import DataReader
    from cyclonedds.qos import Qos, Policy
    from unitree_sdk2py.idl.unitree_hg.msg.dds_ import LowState_
    from unitree_sdk2py.idl.unitree_go.msg.dds_ import SportModeState_
    from unitree_sdk2py.idl.sensor_msgs.msg.dds_ import PointCloud2_
    BmsState_ = None
    if _bms_ok:
        try:
            from unitree_sdk2py.idl.unitree_hg.msg.dds_ import BmsState_ as _B
            BmsState_ = _B
        except Exception:
            BmsState_ = None
    sdk_types = (DomainParticipant, Topic, DataReader, Qos, Policy,
                 LowState_, SportModeState_, PointCloud2_, BmsState_)

    threading.Thread(target=_collector, args=(sdk_types,), daemon=True).start()
    threading.Thread(target=_emitter, args=(args.out,), daemon=True).start()

    # FASE F2: cierre limpio del ws_stream ante SIGINT/SIGTERM.
    def _sig(_signum, _frame):
        _STOP.set()
        _close_persist()
        raise SystemExit(0)
    for _s in (signal.SIGINT, signal.SIGTERM):
        try:
            signal.signal(_s, _sig)
        except (ValueError, OSError):
            pass

    import uvicorn
    try:
        uvicorn.run(make_app(), host=args.host, port=args.port, log_level="info", workers=1)
    finally:
        _STOP.set()
        _close_persist()


if __name__ == "__main__":
    main()
