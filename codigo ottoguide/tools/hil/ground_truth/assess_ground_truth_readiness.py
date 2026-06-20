#!/usr/bin/env python3
"""Read-only physical readiness assessment for a prepared ground-truth session."""
from __future__ import annotations
import argparse,json
from pathlib import Path
import validate_ground_truth_session as contract

def assess(session:Path,inventory:Path):
    report=contract.validate(session,inventory)
    decision="INVALID" if not report["ok"] else ("GO" if report["physical_ready"] else "NO_GO")
    manifest={};hardware={};route={}
    try:manifest=json.loads((session/"session_manifest.json").read_text(encoding="utf-8"))
    except Exception:pass
    try:hardware=json.loads(inventory.read_text(encoding="utf-8"))
    except Exception:pass
    try:
        if manifest.get("route_spec"):route=json.loads((session/manifest["route_spec"]).read_text(encoding="utf-8"))
    except Exception:pass
    return {"ok":report["ok"],"physical_ready":report["physical_ready"],"decision":decision,"blocking_reasons":report["blocking_reasons"],"warnings":report["warnings"],"route":{"route_id":route.get("route_id"),"route_revision":route.get("route_revision"),"approved_for_phase":route.get("approved_for_phase")},"hardware":{"inventory_id":hardware.get("inventory_id"),"distance":hardware.get("distance_instrument_available",False),"angle":hardware.get("angle_instrument_available",False)},"sync":{"available":hardware.get("sync_marker_available",False),"method":hardware.get("sync_method")},"storage":hardware.get("storage_confirmed",False),"supervision":{"area":hardware.get("supervised_area_confirmed",False),"observer":hardware.get("safety_observer_confirmed",False)},"schema_version":manifest.get("schema_version")}
def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument("session_dir",type=Path);p.add_argument("hardware_inventory",type=Path);p.add_argument("--output",type=Path);a=p.parse_args();result=assess(a.session_dir,a.hardware_inventory);payload=json.dumps(result,indent=2,sort_keys=True)+"\n"
    if a.output:a.output.parent.mkdir(parents=True,exist_ok=True);a.output.write_text(payload,encoding="utf-8")
    print(payload,end="");return 0 if result["ok"] else 1
if __name__=="__main__":raise SystemExit(main())
