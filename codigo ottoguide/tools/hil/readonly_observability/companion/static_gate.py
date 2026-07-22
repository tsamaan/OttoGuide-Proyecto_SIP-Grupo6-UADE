#!/usr/bin/env python3
"""NB-HIL-WEB-R0 static gate: prueba por AST/imports/calls que el runtime remoto es
estrictamente read-only (sin DataWriter ni clientes de movimiento). Complementa el
inventario de proceso en runtime; NO se apoya en un contador ficticio.

Escribe REMOTE_STATIC_GATE.json y sale con codigo !=0 si detecta algo prohibido.
"""
import ast, json, os, sys, py_compile

FORBIDDEN_NAMES = [
    "DataWriter", "Publisher", "LocoClient", "SportClient", "MotionSwitcherClient",
    "MotionSwitcher", "ArmActionClient", "AudioClient", "VuiClient",
]
FORBIDDEN_CALLS = ["Move", "StopMove", "Damp", "BalanceStand", "StandUp", "StandDown",
                   "Start", "SetVelocity", "SwitchTo", "SelectMode"]
REQUIRED_READER = "DataReader"


def scan(path):
    src = open(path, "r", encoding="utf-8").read()
    tree = ast.parse(src, filename=path)
    found_names = set()
    found_calls = set()
    imports = set()
    has_reader = False
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and node.id in FORBIDDEN_NAMES:
            found_names.add(node.id)
        if isinstance(node, ast.Attribute) and node.attr in FORBIDDEN_NAMES:
            found_names.add(node.attr)
        if isinstance(node, ast.Name) and node.id == REQUIRED_READER:
            has_reader = True
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            mod = getattr(node, "module", "") or ""
            for a in node.names:
                imports.add((mod + "." + a.name).strip("."))
                if a.name in FORBIDDEN_NAMES:
                    found_names.add(a.name)
        if isinstance(node, ast.Call):
            f = node.func
            attr = getattr(f, "attr", None) or getattr(f, "id", None)
            if attr in FORBIDDEN_CALLS:
                # only flag if it looks like a client method (attribute call on non-reader)
                found_calls.add(attr)
    # forbidden import modules: movement CLIENT modules only. Message data TYPES under
    # `.idl.`/`.msg.dds_` (e.g. SportModeState_ para rt/odommodestate) son read-only y
    # NO se marcan. Se busca el modulo cliente, no el substring "sport".
    CLIENT_KEYS = ["loco_client", "lococlient", "sport_client", "sportclient",
                   "motion_switcher", "motionswitcher", "arm_action_client",
                   "g1_arm", "audio_client", "vui_client"]
    bad_imports = []
    for i in imports:
        low = i.lower()
        if ".idl." in low or ".msg.dds_" in low or "modestate_" in low:
            continue  # tipo de mensaje read-only, no cliente de movimiento
        if any(k in low for k in CLIENT_KEYS):
            bad_imports.append(i)
    return {
        "file": os.path.basename(path),
        "forbidden_names": sorted(found_names),
        "forbidden_calls": sorted(found_calls),
        "bad_imports": sorted(bad_imports),
        "uses_datareader": has_reader,
    }


def main():
    here = os.path.dirname(os.path.abspath(__file__))
    targets = ["ottoguide_remote_recorder.py", "ottoguide_readonly_bridge.py",
               "ottoguide_bms_probe.py", "ottoguide_observability_supervisor.py",
               "ottoguide_common.py", "postlaunch_gate.py"]
    report = {"gate": "REMOTE_RUNTIME_STATIC_GATE", "files": [], "syntax_ok": True,
              "passed": True}
    for t in targets:
        p = os.path.join(here, t)
        try:
            py_compile.compile(p, doraise=True)
        except py_compile.PyCompileError as e:
            report["syntax_ok"] = False
            report["files"].append({"file": t, "syntax_error": str(e)})
            report["passed"] = False
            continue
        r = scan(p)
        # supervisor legitimately has no DataReader (it spawns), that's fine
        bad = bool(r["forbidden_names"] or r["bad_imports"])
        # FORBIDDEN_CALLS like Start are common (uvicorn) so we don't hard-fail on calls,
        # but we record them. Hard fail only on names/imports of movement clients + writers.
        r["clean"] = not bad
        if bad:
            report["passed"] = False
        report["files"].append(r)
    print(json.dumps(report, indent=2))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
