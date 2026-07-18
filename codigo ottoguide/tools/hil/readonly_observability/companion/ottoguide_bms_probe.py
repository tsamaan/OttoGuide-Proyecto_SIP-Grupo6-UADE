#!/usr/bin/env python3
"""OttoGuide NB-HIL-WEB-R0A — probe BMS read-only con descubrimiento de schema (FASE C).

Crea SOLO un DataReader sobre rt/lf/bmsstate (unitree_hg.msg.dds_.BmsState_). Captura <=20
mensajes y decide si el BMS es apto para visualizacion, DESCUBRIENDO el schema real y
EVALUANDO escalas por coherencia (no asume unidades, no asume mcu_ntc/bq_ntc).

Escribe <out>/bms_probe.json con:
  accepted, schema_observed, voltage_field, voltage_scale, current_scale, cell_scale,
  temperature_scale, coherent_samples, rejection_reasons.

Aceptar solo si >=5 mensajes coherentes con las cotas fisicas:
  0<=SOC<=100 ; 20<=pack_voltage_v<=100 ; abs(current_a)<=100 ; 2.0<=cada celda<=5.0 V ;
  temperatura en [-40,125] C.
"""
from __future__ import annotations
import argparse, json, os, sys, time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ottoguide_common import (ensure_sdk_on_path, utc_now, bmsvoltage_or_none,
                              positive_numeric_or_empty, relative_cell_sum_error)

MAX_MSGS = 20
MIN_COHERENT = 5
VOLTAGE_FIELDS = ("bmsvoltage", "pack_voltage", "voltage", "pack_voltage_v")
VOLTAGE_SCALES = (1.0, 0.001)          # V directo o mV->V
CURRENT_SCALES = (1.0, 0.001)          # A directo o mA->A
CELL_SCALES = (1.0, 0.001)             # V directo o mV->V
TEMP_SCALES = (1.0, 0.1)               # C directo o deci-C->C


def _num(x):
    return x if isinstance(x, (int, float)) and not isinstance(x, bool) else None


def _describe(obj):
    """Schema observado: atributos publicos, tipo Python, longitud si es array, muestra cruda."""
    schema = {}
    for name in dir(obj):
        if name.startswith("_"):
            continue
        try:
            val = getattr(obj, name)
        except Exception:
            continue
        if callable(val):
            continue
        entry = {"type": type(val).__name__}
        if isinstance(val, (list, tuple)):
            entry["len"] = len(val)
            entry["raw_sample"] = list(val)[:6]
        elif isinstance(val, (int, float, str, bool)) or val is None:
            entry["raw"] = val
        else:
            entry["raw"] = str(val)[:60]
        schema[name] = entry
    return schema


def _get_voltage_raw(s):
    """FASE A2: bmsvoltage (y candidatos equivalentes) pueden llegar como escalar o como
    secuencia; bmsvoltage_or_none maneja ambos casos (secuencia -> primer positivo)."""
    for f in VOLTAGE_FIELDS:
        v = bmsvoltage_or_none(getattr(s, f, None))
        if v is not None:
            return f, v
    return None, None


def _has_temp(raw):
    return any(r_["temps"] for r_ in raw)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--timeout", type=float, default=12.0)
    args = ap.parse_args()
    os.makedirs(args.out, exist_ok=True)
    out_path = os.path.join(args.out, "bms_probe.json")

    result = {
        "utc": utc_now(), "topic": "rt/lf/bmsstate", "type": "unitree_hg.msg.dds_.BmsState_",
        "captured": 0, "schema_observed": None, "voltage_field": None,
        "voltage_scale": None, "current_scale": None, "cell_scale": None,
        "temperature_scale": None, "coherent_samples": 0, "accepted": False,
        "rejection_reasons": [], "samples": [],
    }

    sdk = ensure_sdk_on_path()
    if not sdk:
        result["rejection_reasons"].append("sdk_not_found")
        json.dump(result, open(out_path, "w"), indent=2)
        print("[bms-probe] SDK not found -> accepted=false", flush=True)
        return

    try:
        from cyclonedds.domain import DomainParticipant
        from cyclonedds.topic import Topic
        from cyclonedds.sub import DataReader
        from cyclonedds.qos import Qos, Policy
        from unitree_sdk2py.idl.unitree_hg.msg.dds_ import BmsState_
    except Exception as e:  # noqa
        result["rejection_reasons"].append(f"import_error:{e}")
        json.dump(result, open(out_path, "w"), indent=2)
        print(f"[bms-probe] import error -> accepted=false: {e}", flush=True)
        return

    BE = Qos(Policy.Reliability.BestEffort, Policy.Durability.Volatile, Policy.History.KeepLast(20))
    dp = DomainParticipant(0)
    r = DataReader(dp, Topic(dp, "rt/lf/bmsstate", BmsState_), qos=BE)

    raw = []  # dicts crudos {vfield, v, current, soc, soh, cells[], temps[], cycle}
    deadline = time.time() + args.timeout
    while result["captured"] < MAX_MSGS and time.time() < deadline:
        for s in r.take(N=8):
            if result["captured"] >= MAX_MSGS:
                break
            if result["schema_observed"] is None:
                result["schema_observed"] = _describe(s)
            result["captured"] += 1
            vfield, vraw = _get_voltage_raw(s)
            cells_raw = [c for c in list(getattr(s, "cell_vol", []) or []) if _num(c) is not None]
            # FASE A2: validacion fisica de celdas ignora no numericos, cero y negativos.
            cells = positive_numeric_or_empty(cells_raw)
            # Temperatura: se preservan todos los valores numericos (0 y negativos son
            # lecturas fisicas validas en Celsius, a diferencia de un voltaje de celda).
            temps = [t for t in list(getattr(s, "temperature", []) or []) if _num(t) is not None]
            raw.append({
                "vfield": vfield, "v": vraw, "current": _num(getattr(s, "current", None)),
                "soc": _num(getattr(s, "soc", None)), "soh": _num(getattr(s, "soh", None)),
                "cells": cells, "cells_raw": cells_raw, "temps": temps,
                "cycle": _num(getattr(s, "cycle", None)),
            })
        time.sleep(0.05)

    if not raw:
        result["rejection_reasons"].append("no_messages")
        json.dump(result, open(out_path, "w"), indent=2)
        print("[bms-probe] no BMS messages -> accepted=false", flush=True)
        return

    vfields = [r_["vfield"] for r_ in raw if r_["vfield"]]
    result["voltage_field"] = max(set(vfields), key=vfields.count) if vfields else None

    def best_scale(scales, extract, lo, hi, per_element=False):
        best = (None, -1)
        for sc in scales:
            cnt = 0
            for r_ in raw:
                vals = extract(r_)
                if vals is None:
                    continue
                if per_element:
                    if vals and all(lo <= (x * sc) <= hi for x in vals):
                        cnt += 1
                elif lo <= (vals * sc) <= hi:
                    cnt += 1
            if cnt > best[1]:
                best = (sc, cnt)
        return best

    v_scale, v_ok = best_scale(VOLTAGE_SCALES, lambda r_: r_["v"], 20, 100)
    c_scale, c_ok = best_scale(CURRENT_SCALES,
                               lambda r_: (abs(r_["current"]) if r_["current"] is not None else None), 0, 100)
    cell_scale, cell_ok = best_scale(CELL_SCALES, lambda r_: (r_["cells"] or None), 2.0, 5.0, per_element=True)
    t_scale, t_ok = best_scale(TEMP_SCALES, lambda r_: (r_["temps"] or None), -40, 125, per_element=True)

    result["voltage_scale"] = v_scale
    result["current_scale"] = c_scale
    result["cell_scale"] = cell_scale
    result["temperature_scale"] = t_scale if _has_temp(raw) else None

    coherent = 0
    for r_ in raw:
        ok = True
        if not (r_["soc"] is not None and 0 <= r_["soc"] <= 100):
            ok = False
        if not (r_["v"] is not None and v_scale and 20 <= r_["v"] * v_scale <= 100):
            ok = False
        if not (r_["current"] is not None and c_scale is not None and abs(r_["current"] * c_scale) <= 100):
            ok = False
        if not (r_["cells"] and cell_scale and all(2.0 <= c * cell_scale <= 5.0 for c in r_["cells"])):
            ok = False
        if r_["temps"] and t_scale and not all(-40 <= t * t_scale <= 125 for t in r_["temps"]):
            ok = False
        if ok:
            coherent += 1
        if len(result["samples"]) < 5:
            voltage_v = round(r_["v"] * v_scale, 3) if (r_["v"] is not None and v_scale) else None
            cells_v = [round(c * cell_scale, 3) for c in r_["cells"]] if cell_scale else []
            result["samples"].append({
                "voltage_v": voltage_v,
                "current_a": round(r_["current"] * c_scale, 3) if (r_["current"] is not None and c_scale is not None) else None,
                "soc": r_["soc"],
                "cells_v": cells_v[:4],
                "cells_v_raw": [round(c * cell_scale, 3) for c in r_["cells_raw"][:4]] if cell_scale else [],
                "temps_c": [round(t * t_scale, 2) for t in r_["temps"][:4]] if t_scale else [],
                # FASE A2: no asumir que la escala es correcta solo porque entra en rango;
                # chequeo independiente cuando pack y celdas son comparables.
                "relative_cell_sum_error": relative_cell_sum_error(voltage_v, cells_v),
                "coherent": ok,
            })

    result["coherent_samples"] = coherent
    result["accepted"] = coherent >= MIN_COHERENT
    if not result["accepted"]:
        result["rejection_reasons"].append(f"coherent={coherent}<{MIN_COHERENT}")
        for label, ok in (("voltage", v_ok), ("current", c_ok), ("cells", cell_ok)):
            if ok < MIN_COHERENT:
                result["rejection_reasons"].append(f"{label}_coherent={ok}")

    json.dump(result, open(out_path, "w"), indent=2)
    print(f"[bms-probe] captured={result['captured']} coherent={coherent} "
          f"accepted={result['accepted']} v_scale={v_scale} c_scale={c_scale} "
          f"cell_scale={cell_scale} t_scale={result['temperature_scale']}", flush=True)


if __name__ == "__main__":
    main()
