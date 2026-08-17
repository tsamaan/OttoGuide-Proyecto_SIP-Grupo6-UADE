# ODOM/TF R2-P1A — Characterization Audit Contract

`CHECKPOINT = MVP-ODOM-TF-R2-P1A-QUANTITATIVE-AUDIT-AND-CLAIM-HARDENING`
`CHARACTERIZATION_SCHEMA_VERSION = 2.1.1-p1a`
`P1A_BASE_SHA = 16070fbd838a43020c3ed52a347b3f77a5fc4005` (R2-P1 HEAD)

## Objective

Audit, reproduce, and harden exclusively the **math, semantics, units,
scoring, provenance, and claims** P1 already produced — no frames,
covariance, ROS, TF, Nav2, or simulation started here (still deferred to P2
and beyond).

## New/hardened modules (additive to P1's package)

```
src/navigation/odometry_characterization_r2/
  dropout_semantics.py    H3: SequenceSemantics + DropoutDetectionPolicy
  causal_lag.py             H4: cross-correlation scan, CausalLagCandidate (pinned UNRESOLVED)
  boot_relation.py           H8: hash-verified BootRelationEvidence
  segment_eligibility.py     H7: per-segment eligibility for 7 purposes
  p1a_audit.py                orchestration: builds P1ACharacterizationBundle
                               on top of report.build_characterization_bundle_with_sessions

  models.py  (extended, not replaced)  -- 12 new dataclasses (section 14)
  arbitration.py (extended)  -- H2/H6: aggregation fix + ArbitrationDecisionAudit
  alignment.py (extended)    -- H5: yaw_speed_* field renaming
  report.py (extended)       -- H2 fix in the arbitration call site;
                                 build_characterization_bundle_with_sessions
                                 (new, additive) exposes raw session data for P1A

tools/hil/offline_navigation/audit_odom_characterization_r2_p1a.py   new CLI
```

## What changed vs. what didn't

P1's own `OdometryCharacterizationBundleR2` structure, `build_
characterization_bundle()`'s public signature, and every existing field
name except the yaw_* rename in `ChannelAlignmentMetrics` are **unchanged**.
`build_characterization_bundle_with_sessions()` is a strict additive
superset (same bundle + hashes, plus a third dict of raw per-session data)
that the old function now delegates to internally.

`arbitration.build_arbitration_matrix()`'s signature changed from
`primary_quality`/`secondary_quality` (single objects) to
`primary_records`/`secondary_records` (lists) — this was the actual H2 bug
fix, not a compatibility-preserving addition, since the bug was in how
the P1 bundle's own `arbitration` field was computed.

## The 10 audit findings (H1-H10)

See `R2_P1A_AUDIT_FINDINGS.json` for the full evidence/fix-applied record
per hypothesis, and `docs/Operaciones_HIL/Evidencia/R2_P1A_AUDIT_SUMMARY.md`
for the narrative summary. Six were REPRODUCED and fixed (H1 informational,
H2, H3, H4, H5, H6), one PARTIAL and fixed (H7), one resolved with a genuine
hash-verification chain (H8), one PARTIAL/documented (H9), and one
NOT_REPRODUCED — confirming P1's design was sound (H10).

## Determinism

`audit_odom_characterization_r2_p1a.py --generated-utc <injected>` never
samples the wall clock or reads the network. Two runs with identical
arguments produce byte-identical output files (verified via manual CLI
invocation and `test_cli_two_runs_byte_identical`).
