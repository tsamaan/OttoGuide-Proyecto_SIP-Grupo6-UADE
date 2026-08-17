# MVP-ODOM-TF-R2-P0 — Physical Evidence Ingest Summary

## What this is

A typed, offline, fail-closed ingestion of the three human-operator-driven
physical capture sessions (R3C, R4, R4B) against the Unitree G1, run against
the locally hash-verified evidence harvest `FINAL-R4-20260720T204735Z`
(`GLOBAL_LOCAL_MANIFEST_VERIFICATION.json`: 3418 files, 0 failures).

No robot, SSH, DDS-live, Unitree-SDK-live, or ROS-graph-live action was
taken to produce this. No `/odom`, TF, `/scan`, map, localization, `cmd_vel`,
or Nav2 was published or executed.

## R1 → R2-P0

R1's boundary (`odometry_candidate_adapter`) is untouched. Its
`DYNAMIC_MOTION_EVIDENCE_MISSING` claim was correct at the time it was
written; R2-P0 records it as historically correct and superseded by R3C/R4B
evidence — see `docs/Operaciones_HIL/Evidencia/R2_P0_CLAIMS_LEDGER.json` for
the full 11-row before/after ledger.

## Sessions ingested

- **R3C** `hilroute-20260720T194910Z` — 190s human-driven route,
  power-cycle-terminated (unclean shutdown), 1438 raw files, 4 with a
  terminal NUL byte (documented, raw untouched). `ROUTE_ACTIVE` begins at
  sequence **91143** (not the historically estimated 92772). Dynamic and
  stationary segments were computed by directly stream-parsing the raw
  per-channel JSONL under `recorder_data/{odom,lf_odom}`.
- **R4** `finalharvest-seated-20260720T205406Z` — post-boot stationary
  baseline, boot id `fa361379-5a30-4da7-bad7-415d6ddc24dd`. A cross-boot
  discontinuity vs. R3C is typed and `VERIFIED`; the exact reset instant is
  `UNRESOLVED` (first post-boot samples were captured ~1805.6s after boot).
  R3C and R4 are never concatenated into one trajectory.
- **R4B** `gt-r4b-20260720T213222Z` — best-effort ground-truth
  forward/turn segments. The accidental-movement interval
  (`left_90_return_invalidated`) is ingested but always `valid=False`,
  `ground_truth_constraint=INVALID`, excluded from every computation. The
  historical `left_180`/"CW" label is preserved for traceability only; the
  operator's authoritative correction (turn was left) is what R2-P0 uses.

## What did NOT change

```
AUTHORITATIVE_SOURCE_CHANNEL = null
TRANSLATION_SCALE = UNRESOLVED
YAW_SCALE = UNRESOLVED
CHILD_FRAME_ID = UNRESOLVED
COVARIANCE_PUBLICATION_MODEL_READY = false
ODOM_PUBLICATION_READY = false
ODOM_TO_BASE_LINK_TF_READY = false
NAV2_READY = false
```

## Where to look

- Code: `codigo ottoguide/src/navigation/odometry_evidence_r2/`
- CLI: `codigo ottoguide/tools/hil/offline_navigation/ingest_physical_evidence_r2.py`
- Tests: `codigo ottoguide/tests/unit/test_odometry_evidence_r2_*.py`
- Fixtures: `codigo ottoguide/tests/fixtures/odom_tf_r2_physical_evidence/`
- Contract: `docs/Arquitectura/ODOM_TF_R2_PHYSICAL_EVIDENCE_CONTRACT.md`
- Data model: `docs/Arquitectura/ODOM_TF_R2_DATA_MODEL.md`
- Claims ledger: `docs/Operaciones_HIL/Evidencia/R2_P0_CLAIMS_LEDGER.json`
- Full CLI outputs, baseline/gate reports and the ingest descriptor: an
  `OttoGuide-R2-Evidence/MVP-ODOM-TF-R2-P0/` folder outside this repository
  (path is machine-local, not recorded here)

## Next checkpoint

`MVP-ODOM-TF-R2-P1-CHANNEL-TIME-AND-MOTION-CHARACTERIZATION` — primary vs LF
lag/frequency/dropout/noise/drift characterization, IMU and timebase
discontinuity analysis. Not started; not authorized by this checkpoint.
