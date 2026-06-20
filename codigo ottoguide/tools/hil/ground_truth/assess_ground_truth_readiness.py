#!/usr/bin/env python3
"""Read-only fail-safe readiness decision for sealed ground-truth evidence."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import validate_ground_truth_session as contract

EXIT_CODES = {"GO": 0, "NO_GO": 2, "INVALID": 3}


def assess(session: Path) -> dict:
    return contract.validate(session)


def main() -> int:
    parser=argparse.ArgumentParser(
        description=__doc__,
        epilog="Exit codes: 0=GO, 2=NO_GO, 3=INVALID contract/evidence, 1=unexpected execution error.",
    )
    parser.add_argument("session_dir",type=Path);parser.add_argument("--output",type=Path);args=parser.parse_args()
    try:
        result=assess(args.session_dir);payload=json.dumps(result,indent=2,sort_keys=True)+"\n"
        if args.output: args.output.parent.mkdir(parents=True,exist_ok=True);args.output.write_text(payload,encoding="utf-8")
        print(payload,end="");return EXIT_CODES[result["decision"]]
    except Exception as exc:
        print(json.dumps({"ok":False,"physical_ready":False,"decision":"INVALID","blocking_reasons":["UNEXPECTED_EXECUTION_ERROR"],"error":f"{type(exc).__name__}: {exc}"},sort_keys=True))
        return 1


if __name__=="__main__": raise SystemExit(main())
