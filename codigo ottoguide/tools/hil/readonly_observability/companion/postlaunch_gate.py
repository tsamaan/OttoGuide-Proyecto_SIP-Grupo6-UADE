#!/usr/bin/env python3
"""FASE A5 (R0B hotfix) — gate post-launch (corre en el Companion, tras iniciar el
supervisor). Espera como MAXIMO 15s a que se cumplan TODAS las condiciones:

  pids.json valido; supervisor/recorder/bridge PID vivos;
  recorder_state.json actualizado en los ultimos 3s;
  GET 127.0.0.1:8000/health = 200 con session_id=<sesion actual>,
  read_only_demo=true, dds_writers_created=0.

Si no se cumplen todas dentro del plazo: RESULT=NB_HIL_WEB_R0B_BLOCKED_REMOTE_RUNTIME_STARTUP,
se preservan los logs (no se borra nada) y se sale con codigo !=0 (no iniciar el recorrido).

Solo stdlib (urllib) para no depender de paquetes de terceros en el Companion.

Uso:
  python postlaunch_gate.py --out <REMOTE_RUN_ROOT> --session <id> [--timeout 15]
      [--host 127.0.0.1] [--port 8000]
"""
from __future__ import annotations
import argparse, json, os, sys, time, urllib.error, urllib.request

MAX_WAIT_S = 15.0
RECORDER_STATE_FRESH_S = 3.0
POLL_INTERVAL_S = 0.5


def _pid_alive(pid):
    try:
        pid = int(pid)
    except (TypeError, ValueError):
        return False
    return os.path.exists(f"/proc/{pid}")


def _load_pids(out_dir):
    path = os.path.join(out_dir, "pids.json")
    if not os.path.isfile(path):
        return None, "pids.json ausente"
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        return None, f"pids.json invalido: {e}"
    return data, None


def _recorder_state_fresh(out_dir, now):
    path = os.path.join(out_dir, "recorder_data", "recorder_state.json")
    if not os.path.isfile(path):
        return False, None, "recorder_state.json ausente"
    try:
        mtime = os.path.getmtime(path)
    except OSError as e:
        return False, None, f"stat fallo: {e}"
    age = now - mtime
    return (age <= RECORDER_STATE_FRESH_S), age, None


def _get_health(host, port, timeout_s=2.0):
    url = f"http://{host}:{port}/health"
    try:
        with urllib.request.urlopen(url, timeout=timeout_s) as resp:
            if resp.status != 200:
                return None, f"health status={resp.status}"
            body = json.loads(resp.read().decode("utf-8"))
            return body, None
    except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError) as e:
        return None, f"health unreachable: {e}"


def check_once(out_dir, session, host, port):
    """Evalua todas las condiciones una vez. Devuelve (passed, detail_dict)."""
    now = time.time()
    detail = {}

    pids, pids_err = _load_pids(out_dir)
    detail["pids_json_valid"] = pids is not None
    detail["pids_json_error"] = pids_err

    sup_pid = pids.get("supervisor") if pids else None
    rec_pid = pids.get("recorder") if pids else None
    brg_pid = pids.get("bridge") if pids else None
    detail["supervisor_pid_alive"] = _pid_alive(sup_pid) if pids else False
    detail["recorder_pid_alive"] = _pid_alive(rec_pid) if pids else False
    detail["bridge_pid_alive"] = _pid_alive(brg_pid) if pids else False

    fresh, age, fresh_err = _recorder_state_fresh(out_dir, now)
    detail["recorder_state_fresh"] = fresh
    detail["recorder_state_age_s"] = round(age, 2) if age is not None else None
    detail["recorder_state_error"] = fresh_err

    health, health_err = _get_health(host, port)
    detail["health_reachable"] = health is not None
    detail["health_error"] = health_err
    detail["health_session_id_match"] = bool(health and health.get("session_id") == session)
    detail["health_read_only_demo"] = bool(health and health.get("read_only_demo") is True)
    detail["health_dds_writers_created_zero"] = bool(health and health.get("dds_writers_created") == 0)

    passed = (
        detail["pids_json_valid"]
        and detail["supervisor_pid_alive"]
        and detail["recorder_pid_alive"]
        and detail["bridge_pid_alive"]
        and detail["recorder_state_fresh"]
        and detail["health_reachable"]
        and detail["health_session_id_match"]
        and detail["health_read_only_demo"]
        and detail["health_dds_writers_created_zero"]
    )
    return passed, detail


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True, help="REMOTE_RUN_ROOT (mismo --out del supervisor)")
    ap.add_argument("--session", required=True)
    ap.add_argument("--timeout", type=float, default=MAX_WAIT_S)
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8000)
    args = ap.parse_args()

    start = time.time()
    passed, detail = check_once(args.out, args.session, args.host, args.port)
    while not passed and (time.time() - start) < args.timeout:
        time.sleep(POLL_INTERVAL_S)
        passed, detail = check_once(args.out, args.session, args.host, args.port)

    elapsed = round(time.time() - start, 2)
    report = {
        "gate": "POSTLAUNCH_GATE",
        "session_id": args.session,
        "elapsed_s": elapsed,
        "max_wait_s": args.timeout,
        "passed": passed,
        "detail": detail,
        "result": "NB_HIL_WEB_R0B_LIVE_MONITOR_READY" if passed
                  else "NB_HIL_WEB_R0B_BLOCKED_REMOTE_RUNTIME_STARTUP",
    }
    # Preserva logs: solo escribe su propio reporte, no borra ni modifica nada mas.
    out_path = os.path.join(args.out, "POSTLAUNCH_GATE.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)
    print(json.dumps(report, indent=2))
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
