#!/usr/bin/env python3
"""OttoGuide WEB-HIL-R1 — replay server OFFLINE.

Reproduce frames FISICOS grabados (fixtures/r0b1_real_frames.jsonl, capturados durante la
sesion r0b1-20260717T215047Z) a 10 Hz sobre el MISMO contrato read-only que el bridge del
Companion, para validar la interfaz sin robot y sin DDS.

Garantias:
  * NO importa cyclonedds, unitree_sdk2py, LocoClient, SportClient ni DataWriter/DataReader.
  * NO abre ningun socket DDS ni de red saliente; solo lee un archivo local y sirve
    HTTP/WebSocket en loopback.
  * Marca cada frame con source_profile=REPLAY (NUNCA "REAL" ni "live"); agrega seq/session_id
    propios de esta corrida de replay (session_id siempre con prefijo "replay-").
  * Responde 405 READ_ONLY a POST/PUT/PATCH/DELETE, igual que el bridge fisico.
  * Implementado SOLO con la biblioteca estandar (sin fastapi/uvicorn/websockets) para no
    requerir ninguna instalacion en una Notebook nueva.

Uso:
  python ottoguide_replay_server.py --frames fixtures/r0b1_real_frames.jsonl \
      --host 127.0.0.1 --port 8000 --hz 10
"""
from __future__ import annotations
import argparse, base64, hashlib, json, os, sys, struct, threading, time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

WS_GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"
RING_MAX = 2000

# ---- global replay state (single emitter thread advances seq at HZ) ----
_lock = threading.Lock()
_ring = []                 # list of (seq, frame_dict)
_current = {"seq": 0, "frame": None}
SESSION_ID = None          # set in main(): stable per server run, prefix "replay-"
FRAMES = []                # raw recorded frames
HZ = 10.0
ORIGIN_ALLOW = "http://127.0.0.1:5173"


def _monotonic_ns():
    return time.monotonic_ns()


def _compute_availability(fr):
    """Disponibilidad real derivada del contenido del frame (misma politica que el bridge)."""
    imu = fr.get("imu") or {}
    imu_ok = any(isinstance(imu.get(k), list) and any(isinstance(x, (int, float)) for x in imu.get(k))
                 for k in ("rpy_deg", "accelerometer", "gyroscope"))
    v, a = fr.get("power_v"), fr.get("power_a")
    energy_ok = isinstance(v, (int, float)) or isinstance(a, (int, float))
    bms = fr.get("bms")
    bms_ok = isinstance(bms, dict) and isinstance(bms.get("soc"), (int, float))
    odom = fr.get("odom") or {}
    return {
        "imu": bool(imu_ok),
        "energy": bool(energy_ok),
        "bms": bool(bms_ok),
        "odom": bool(odom.get("position") or odom.get("velocity")),
        "lidar": bool((fr.get("lidar") or {}).get("points")),
        "motors": bool(fr.get("motors")),
    }


def _decorate(raw, seq):
    fr = dict(raw)
    fr["seq"] = seq
    fr["session_id"] = SESSION_ID
    fr["source_profile"] = "REPLAY"       # nunca marca REAL/live
    fr["read_only_demo"] = True
    fr["server_utc"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    fr["server_monotonic_ns"] = _monotonic_ns()
    fr["availability"] = _compute_availability(fr)
    return fr


def _emitter():
    seq = 0
    i = 0
    period = 1.0 / HZ
    while True:
        raw = FRAMES[i % len(FRAMES)]
        i += 1
        seq += 1
        fr = _decorate(raw, seq)
        with _lock:
            _current["seq"] = seq
            _current["frame"] = fr
            _ring.append((seq, fr))
            if len(_ring) > RING_MAX:
                del _ring[: len(_ring) - RING_MAX]
        time.sleep(period)


def _backfill(after_seq, limit):
    with _lock:
        out = [fr for (s, fr) in _ring if s > after_seq]
    return out[:limit]


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *a):  # quieter logs
        sys.stderr.write("[replay] " + (a[0] % a[1:]) + "\n")

    def _cors(self):
        self.send_header("Access-Control-Allow-Origin", ORIGIN_ALLOW)
        self.send_header("Access-Control-Allow-Methods", "GET")
        self.send_header("Access-Control-Allow-Headers", "*")

    def _json(self, obj, code=200):
        body = json.dumps(obj).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self._cors()
        self.end_headers()
        self.wfile.write(body)

    def _reject_mutation(self):
        self._json({"detail": "READ_ONLY"}, code=405)

    def do_POST(self):   self._reject_mutation()
    def do_PUT(self):    self._reject_mutation()
    def do_PATCH(self):  self._reject_mutation()
    def do_DELETE(self): self._reject_mutation()

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path
        # WebSocket upgrade?
        if path == "/ws/telemetry" and self.headers.get("Upgrade", "").lower() == "websocket":
            return self._serve_ws()
        if path == "/health":
            with _lock:
                seq = _current["seq"]
            return self._json({"status": "ok", "read_only_demo": True, "source_profile": "REPLAY",
                               "dds_writers_created": 0, "seq": seq, "session_id": SESSION_ID})
        if path == "/status":
            return self._json({"state": "replay", "source_profile": "REPLAY", "operational_ready": False,
                               "readiness_errors": ["REPLAY: offline recorded frames"],
                               "script_loaded": True, "script_version": "replay"})
        if path == "/content/script":
            return self._json({"version": "replay", "waypoints": [], "read_only_demo": True})
        if path == "/telemetry/backfill":
            q = parse_qs(parsed.query)
            after = int((q.get("after_seq") or ["0"])[0] or 0)
            limit = int((q.get("limit") or ["1800"])[0] or 1800)
            return self._json(_backfill(after, min(limit, RING_MAX)))
        return self._json({"detail": "not found"}, code=404)

    # ---- minimal RFC6455 server (text frames only, unmasked server->client) ----
    def _serve_ws(self):
        key = self.headers.get("Sec-WebSocket-Key")
        if not key:
            return self._json({"detail": "bad ws handshake"}, code=400)
        accept = base64.b64encode(hashlib.sha1((key + WS_GUID).encode()).digest()).decode()
        self.send_response(101)
        self.send_header("Upgrade", "websocket")
        self.send_header("Connection", "Upgrade")
        self.send_header("Sec-WebSocket-Accept", accept)
        self.end_headers()
        conn = self.connection
        conn.setblocking(False)
        last_sent = 0
        try:
            while True:
                # drain any client control frame (close) without blocking
                try:
                    data = conn.recv(4096)
                    if data == b"":
                        break  # client closed
                    if data and (data[0] & 0x0F) == 0x8:
                        break  # close opcode
                except (BlockingIOError, InterruptedError):
                    pass
                except OSError:
                    break
                with _lock:
                    seq = _current["seq"]
                    frame = _current["frame"]
                if frame is not None and seq != last_sent:
                    last_sent = seq
                    if not self._ws_send(conn, json.dumps(frame)):
                        break
                time.sleep(1.0 / HZ / 2)
        finally:
            try:
                conn.setblocking(True)
            except OSError:
                pass

    @staticmethod
    def _ws_send(conn, text):
        payload = text.encode("utf-8")
        header = bytearray([0x81])  # FIN + text
        n = len(payload)
        if n < 126:
            header.append(n)
        elif n < 65536:
            header.append(126); header += struct.pack(">H", n)
        else:
            header.append(127); header += struct.pack(">Q", n)
        try:
            conn.sendall(bytes(header) + payload)
            return True
        except OSError:
            return False


def main():
    global FRAMES, SESSION_ID, HZ
    ap = argparse.ArgumentParser()
    ap.add_argument("--frames", default=os.path.join(os.path.dirname(__file__), "fixtures", "r0b1_real_frames.jsonl"))
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--hz", type=float, default=10.0)
    ap.add_argument("--session-id", default=None)
    args = ap.parse_args()

    HZ = args.hz
    SESSION_ID = args.session_id or ("replay-" + hashlib.sha1(args.frames.encode()).hexdigest()[:10])
    with open(args.frames, "r", encoding="utf-8") as f:
        FRAMES = [json.loads(line) for line in f if line.strip()]
    if not FRAMES:
        print("no frames loaded", file=sys.stderr); sys.exit(2)
    print(f"[replay] loaded {len(FRAMES)} frames, session={SESSION_ID}, hz={HZ}", flush=True)

    threading.Thread(target=_emitter, daemon=True).start()
    srv = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"[replay] serving read-only replay on http://{args.host}:{args.port} "
          f"(WS /ws/telemetry, GET /health /status /content/script /telemetry/backfill)", flush=True)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
