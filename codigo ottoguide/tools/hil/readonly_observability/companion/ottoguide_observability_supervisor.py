#!/usr/bin/env python3
"""OttoGuide NB-HIL-WEB-R0 — supervisor remoto (FASE I).

Supervisa recorder y bridge (ambos read-only). Reglas:
  * restart maximo 1 vez por proceso;
  * delay de 1 s antes del restart;
  * NO sobrescribe archivos anteriores (cada arranque usa logs con sufijo de intento);
  * registra cada restart en supervisor.log.

Se lanza desacoplado de SSH. Preferir `systemd-run --user` cuando este disponible; si no,
fallback a nohup/setsid con stdin=/dev/null y stdout/stderr a archivos (ver deploy script).
El supervisor en si NO crea entidades DDS ni envia movimiento.

Uso:
  python ottoguide_observability_supervisor.py --out <dir> --session <id> [--enable-bms]
"""
from __future__ import annotations
import argparse, json, os, signal, subprocess, sys, time

HERE = os.path.dirname(os.path.abspath(__file__))


def log(out_dir, msg):
    line = f"{time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())} {msg}"
    with open(os.path.join(out_dir, "supervisor.log"), "a", encoding="utf-8") as f:
        f.write(line + "\n")
    print("[supervisor] " + msg, flush=True)


def spawn(name, argv, out_dir, attempt):
    # NO sobrescribir: sufijo de intento en los logs.
    stdout = open(os.path.join(out_dir, f"{name}.attempt{attempt}.out"), "a", buffering=1)
    stderr = open(os.path.join(out_dir, f"{name}.attempt{attempt}.err"), "a", buffering=1)
    devnull = open(os.devnull, "rb")
    kwargs = {}
    if hasattr(os, "setsid"):
        kwargs["preexec_fn"] = os.setsid  # desacople de la sesion/tty
    p = subprocess.Popen(argv, stdin=devnull, stdout=stdout, stderr=stderr, **kwargs)
    return p


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--session", required=True)
    ap.add_argument("--enable-bms", action="store_true")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--python", default=sys.executable)
    args = ap.parse_args()
    os.makedirs(args.out, exist_ok=True)

    py = args.python
    rec_dir = os.path.join(args.out, "recorder_data")
    os.makedirs(rec_dir, exist_ok=True)
    bridge_dir = os.path.join(args.out, "bridge_data")
    os.makedirs(bridge_dir, exist_ok=True)

    procs = {
        "recorder": {
            "argv": [py, os.path.join(HERE, "ottoguide_remote_recorder.py"),
                     "--out", rec_dir, "--session", args.session,
                     "--phase-file", os.path.join(args.out, "current_phase.txt")]
                    + (["--enable-bms"] if args.enable_bms else []),
            "p": None, "restarts": 0, "attempt": 0,
        },
        "bridge": {
            "argv": [py, os.path.join(HERE, "ottoguide_readonly_bridge.py"),
                     "--session", args.session, "--out", bridge_dir,
                     "--host", args.host, "--port", str(args.port),
                     "--bms-probe", os.path.join(args.out, "bms_probe.json")],
            "p": None, "restarts": 0, "attempt": 0,
        },
    }

    for name, d in procs.items():
        d["attempt"] += 1
        d["p"] = spawn(name, d["argv"], args.out, d["attempt"])
        log(args.out, f"started {name} pid={d['p'].pid} attempt={d['attempt']}")
    write_pids(args.out, procs)

    # FASE F3: SIGINT/SIGTERM -> cierre ordenado de los hijos (sin huerfanos).
    stop = {"flag": False}

    def _sig(_signum, _frame):
        stop["flag"] = True
    for _s in (signal.SIGINT, signal.SIGTERM):
        try:
            signal.signal(_s, _sig)
        except (ValueError, OSError):
            pass

    while not stop["flag"]:
        for name, d in procs.items():
            p = d["p"]
            if p and p.poll() is not None:
                log(args.out, f"{name} exited rc={p.returncode}")
                if d["restarts"] < 1:  # restart maximo 1 vez por proceso
                    time.sleep(1)      # delay 1 s
                    d["restarts"] += 1
                    d["attempt"] += 1
                    d["p"] = spawn(name, d["argv"], args.out, d["attempt"])
                    log(args.out, f"restarted {name} pid={d['p'].pid} "
                                  f"restarts={d['restarts']} attempt={d['attempt']}")
                    write_pids(args.out, procs)
                else:
                    log(args.out, f"{name} exceeded restart limit (1); leaving down")
        time.sleep(1)

    # Cierre solicitado: SIGTERM -> espera acotada -> SIGKILL como ultimo recurso.
    log(args.out, "shutdown requested; terminating children (SIGTERM -> wait -> SIGKILL)")
    _shutdown_children(args.out, procs, grace_s=10)


def _shutdown_children(out_dir, procs, grace_s=10):
    for name, d in procs.items():
        p = d["p"]
        if not p or p.poll() is not None:
            continue
        try:
            p.terminate()  # SIGTERM
            log(out_dir, f"SIGTERM -> {name} pid={p.pid}")
        except Exception as e:  # noqa
            log(out_dir, f"SIGTERM failed for {name}: {e}")
    deadline = time.time() + grace_s
    while time.time() < deadline:
        if all((not d["p"]) or d["p"].poll() is not None for d in procs.values()):
            break
        time.sleep(0.2)
    for name, d in procs.items():
        p = d["p"]
        if p and p.poll() is None:
            try:
                p.kill()  # SIGKILL ultimo recurso
                log(out_dir, f"SIGKILL -> {name} pid={p.pid} (no cerro en {grace_s}s)")
            except Exception as e:  # noqa
                log(out_dir, f"SIGKILL failed for {name}: {e}")
    results = {name: (d["p"].poll() if d["p"] else None) for name, d in procs.items()}
    log(out_dir, f"shutdown complete; child rc={results}")


def write_pids(out_dir, procs):
    pids = {"supervisor": os.getpid()}
    for name, d in procs.items():
        pids[name] = d["p"].pid if d["p"] else None
        pids[name + "_restarts"] = d["restarts"]
    tmp = os.path.join(out_dir, "pids.json.tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(pids, f, indent=2)
    os.replace(tmp, os.path.join(out_dir, "pids.json"))


if __name__ == "__main__":
    main()
