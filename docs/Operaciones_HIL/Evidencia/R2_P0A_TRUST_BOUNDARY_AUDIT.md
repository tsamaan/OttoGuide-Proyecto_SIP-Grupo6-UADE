# MVP-ODOM-TF-R2-P0A — Trust Boundary Audit

## Scope

Ten hypothesized findings (F1–F10) against the R2-P0 codebase
(`d1beef0fc3b4ddc1ccf17f67848d0dad96a3cfcb`) were reproduced against the
actual code before any fix was written, then closed in the P0A worktree
(`feature/odom-tf-r2-physical-evidence-ingest` off
`d1beef0f...`/`fix/odom-tf-r2-p0-trust-boundary`).

## Findings

| ID | Hypothesis | Reproduced? | Fix |
|---|---|---|---|
| F1 | Permissive JSONL parser (UTF-8 errors ignored, malformed JSON silently skipped, NUL cut at first occurrence with no terminality check, discards unlogged) | **Yes** — `ingest.py:91` used `errors="ignore"`; malformed lines `continue`d silently | `_parse_channel_jsonl_dir` rewritten fail-closed: strict UTF-8, typed aggregate error on any malformed JSON/unknown topic/bad sequence/missing field/non-finite value; NUL tolerated only if fully terminal and after a complete line; every parse returns a `JsonlParseReport` |
| F2 | Dataclasses accept invalid status/hash/path/NaN/bool/inverted sequences/misaligned file-hash counts directly | **Yes** — only 4 of ~17 dataclasses had any `__post_init__` | Every dataclass now validates in `__post_init__` via shared helpers in `models.py` (`_check_evidence_id`, `_check_confidence`, `_check_source_files_and_hashes`, etc.) |
| F3 | `sessions=3`, `time_domains=2` — R3C time domain absent | **Yes** — confirmed via live bundle build | R3C now gets its own `SessionTimeDomain` (`mapping_status=UNRESOLVED`, no RTT handshake exists for it); `PhysicalEvidenceBundleR2.__post_init__` structurally requires one per session |
| F4 | R4B/R4 boot relation reported as fact when the bundle carries `null` | **Partially "yes"** — no false claim existed, but no explicit `R4B_BOOT_RELATION_TO_R4` state existed either; also `_odom_field_for_topic` silently fell through to `'lf_odom'` for any unrecognized topic | `R4B_BOOT_RELATION_TO_R4 = UNRESOLVED` stated explicitly in `r4b.session`'s limitations; `_odom_field_for_topic` now raises `EvidenceValidationError` for any topic that isn't exactly the two known constants |
| F5 | CLI descriptor had no expected-hash verification; a modified source would be silently re-hashed and accepted | **Yes** — old descriptor only required `harvest_root` | New `source_manifest.py`: descriptor requires `manifest_sha256` + per-file `expected_source_sha256`; CLI calls `verify_harvest_against_descriptor()` before `ingest.build_bundle()`; a tampered file produces `result=FAIL`, exit code 1 |
| F6 | `CROSS_BOOT_DISCONTINUITY_OBSERVED` + `RESET_BEHAVIOR_CHARACTERIZED` aggregated into one `VERIFIED` claim | **Yes** — single `RESET_AND_DISCONTINUITY` claim | Split into `CROSS_BOOT_DISCONTINUITY_OBSERVED=VERIFIED`, `RESET_BEHAVIOR_CHARACTERIZED=PARTIAL`, `EXACT_RESET_INSTANT=UNRESOLVED` |
| F7 | R4B provenance cites the derived report but not raw inputs/script/hash/arguments | **Yes** — by design in R2-P0, undocumented as a limitation | Every R4B `EvidenceProvenance` now carries an explicit `DERIVATION_PROVENANCE = PARTIAL` limitation |
| F8 | `StationaryNoiseStatistics.mean` fixed to `(0.0, 0.0, 0.0)` | **Yes** | `mean` replaced by `observed_mean` (from the derived report) + `centered_mean` (always `(0,0,0)` **by construction**, validated) + `reference_origin_policy` |
| F9 | Non-portable absolute paths hardcoded in 2 test files | **Yes** — `IdeaPad` path literal in both | Replaced with `OTTOGUIDE_R2_HARVEST_ROOT`; a static-gate test scans the whole R2 test suite for the literal |
| F10 | Git worktree `.git` files are absolute-path `gitdir:` pointers | **Yes** — confirmed on all 4 worktrees | Not a code fix (inherent to git worktrees) — this is exactly why section 15 requires a standalone `git bundle`, not a folder copy, for portable continuity |

## What did NOT change

- R1 (`odometry_candidate_adapter`) — untouched, 299 tests still pass.
- Every R2-P0 conservative claim value (`AUTHORITATIVE_SOURCE_CHANNEL=null`,
  `TRANSLATION_SCALE=UNRESOLVED`, `YAW_SCALE=UNRESOLVED`,
  `CHILD_FRAME_ID=UNRESOLVED`, `COVARIANCE_PUBLICATION_MODEL_READY=false`,
  `ODOM_PUBLICATION_READY=false`, `TF_TO_BASE_LINK_READY=false`,
  `NAV2_READY=false`).
- The set of 3 ingested sessions and their session_ids/session_types.
- No robot, SSH, DDS-live, or GitHub write action was taken.

## Verification performed

- R1 baseline: 299 passed (unchanged).
- R2-P0 pre-existing tests (validation/statistics/provenance): 54 passed (unchanged).
- P0A test suite (models/ingest/source_manifest/static_gate/cli_determinism):
  79 passed, 0 skipped, with `OTTOGUIDE_R2_HARVEST_ROOT` set — harvest
  integration genuinely exercised, not skipped.
- CLI run twice against the real harvest via the new descriptor schema:
  byte-identical 6/6 output files.
- Manifest tamper test: appending a byte to `R4B_RESULT.json` in a scratch
  copy of the harvest made the CLI exit 1 with `result=FAIL` and the exact
  file/hash mismatch reported.
