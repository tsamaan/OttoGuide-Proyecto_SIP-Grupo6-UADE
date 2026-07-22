# MVP-ODOM-TF-R2-P1A — Audit Summary

Base: R2-P1 HEAD `16070fbd838a43020c3ed52a347b3f77a5fc4005`.

## Headline: what changed vs. P1

| Claim ID | P1 state | P1A state | Changed |
|---|---|---|---|
| CHANNEL_QUALITY | VERIFIED | VERIFIED | no |
| DROPOUT_CHARACTERIZATION | *(none)* | PARTIAL | new |
| PRIMARY_LF_ALIGNMENT | PARTIAL | PARTIAL | no |
| PAIRING_TIME_OFFSET | *(none)* | SUPPORTED_INFERENCE | new |
| CAUSAL_CHANNEL_LAG | *(none)* | UNRESOLVED | new |
| CHANNEL_ARBITRATION | PARTIAL | PARTIAL | no |
| PREFERRED_ANALYSIS_CHANNEL | *(implicit: rt/odommodestate)* | null | **corrected** |
| YAW_ANGLE_RESIDUAL | *(none)* | UNRESOLVED | new |
| YAW_SPEED_RESIDUAL | *(none, was ambiguous yaw_rmse)* | VERIFIED | new/renamed |
| R4B_BOOT_RELATION_TO_R4 | *(none)* | VERIFIED (SAME_BOOT_VERIFIED) | new |
| TRANSLATION_SCALE / YAW_SCALE | UNRESOLVED | UNRESOLVED | no |
| IMU_CROSSCHECK | PARTIAL_QUANTIFIED | PARTIAL_QUANTIFIED | no |

Full delta: `R2_P1A_CLAIMS_DELTA_FROM_P1.json`.

## The single most important correction: H2

P1's own final report said "primary edges out on rate/jitter/gaps/dropouts."
The real aggregated numbers (summed across R3C, R4, R4B):

| Metric | Primary | LF | Winner |
|---|---|---|---|
| time-gap rate (exposure-normalized) | derived from 18 events | derived from 4 events | **LF** |
| sequence-gap estimate (auxiliary, weight 0) | 694 | 13 | Not scored |
| jitter (weighted mean, ms) | 1.10 | 9.20 | Primary |

The sequence-gap estimates are `AUXILIARY_NOT_CONFIRMED_LOSS` and never affect
preference. The admissible weighted calculation uses jitter and the
exposure-normalized time-gap rate; primary wins jitter and LF wins time gaps,
so `PREFERRED_ANALYSIS_CHANNEL` is correctly `null`. Root cause: the
arbitration call only ever looked at one of three sessions' numbers. Fixed
in `arbitration.py`/`report.py`; both are still non-authoritative
(`AUTHORITATIVE_SOURCE_CHANNEL` stays `null`).

## H1-H10 classification

| # | Title | Classification |
|---|---|---|
| H1 | Incorrect canonical GitHub slug | REPRODUCED |
| H2 | Arbitration contradiction | REPRODUCED |
| H3 | Sequence semantics / dropout definition | REPRODUCED |
| H4 | Lag candidate vs. pairing offset | REPRODUCED |
| H5 | Ambiguous yaw_rmse unit | REPRODUCED |
| H6 | Arbitration criterion count mismatch | REPRODUCED |
| H7 | Invalid segments used without eligibility | PARTIAL |
| H8 | R4B/R4 boot relation | resolved (SAME_BOOT_VERIFIED, hash-chain-backed) |
| H9 | Yaw variability across turn segments | PARTIAL |
| H10 | P0A parser reuse / bypass | NOT_REPRODUCED |

Full evidence and fixes: `R2_P1A_AUDIT_FINDINGS.json`.

## Boot relation (H8) detail

`R4B_TIMEBASE_ESTIMATE.json` sha256 =
`fab067a0d265e83355bd0a5e985f5d7eb73881618774b8dab6661c9d095dd0cf`, matching
its entry in the session's own `R4B_LOCAL_SHA256SUMS.txt` (part of
`R4B_LOCAL_HASH_VERIFICATION.json`, 2098/2098 files, PASS). Its
`remote_boot_ids` field matches R4's P0A-descriptor-pinned `ROBOT_BOOT_ID`
exactly (`fa361379-5a30-4da7-bad7-415d6ddc24dd`). `R4B_BOOT_RELATION_TO_R4 =
SAME_BOOT_VERIFIED`. This does **not** authorize concatenating R4/R4B
trajectories, time domains, or captures — see `R2_P1A_NEXT_CHECKPOINT_PLAN.md`
for the follow-up this opens for P2.
