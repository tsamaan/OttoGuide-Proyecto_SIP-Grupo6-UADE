# Local Artifacts Audit Runbook

This runbook keeps OttoGuide evidence organized without deleting local artifacts.

## Goal

Audit `artifacts/` on the Windows notebook, identify heavy files, duplicates, and review candidates, then produce a conservative cleanup plan.

## Run The Audit

From the repository root:

```powershell
python tools/hil/audit_local_artifacts.py --artifacts-dir artifacts
```

Useful variants:

```powershell
python tools/hil/audit_local_artifacts.py --artifacts-dir artifacts --dry-run
python tools/hil/audit_local_artifacts.py --artifacts-dir artifacts --large-threshold-mb 100
python tools/hil/audit_local_artifacts.py --artifacts-dir artifacts --hash-large-files
```

The script writes reports under:

```text
artifacts/_audit/local_artifacts_<RUN_ID>/
```

## Outputs

- `LOCAL_ARTIFACTS_INVENTORY.csv`: complete file inventory with size, dates, hash when calculated, and classification.
- `LOCAL_ARTIFACTS_SUMMARY.md`: totals, extension breakdown, top heavy files, and classification counts.
- `LOCAL_ARTIFACTS_LARGE_FILES.csv`: files above the configured size threshold.
- `LOCAL_ARTIFACTS_DUPLICATES.csv`: exact SHA256 duplicate groups.
- `LOCAL_ARTIFACTS_KEEP_RECOMMENDED.md`: traceable or recent evidence to preserve.
- `LOCAL_ARTIFACTS_QUARANTINE_CANDIDATES.md`: safe-looking temporary candidates only.
- `LOCAL_ARTIFACTS_CLEANUP_PLAN.md`: next actions and safety rules.

## Classification

`KEEP_RECOMMENDED` means the file appears traceable, final, recent, or part of a relevant session. Keep these unless a human explicitly decides otherwise.

`REVIEW_MANUAL` is the default for valuable or risky artifacts. This includes rosbags, map files, large videos, point clouds, heavy files, and folders without clear manifests.

`QUARANTINE_CANDIDATE` means the name or size suggests temporary/debug/test output. Quarantine is still not automatic.

## Quarantine Policy

Do not delete artifacts directly. If cleanup is approved, move candidates into:

```text
artifacts/_quarantine/local_artifacts_<RUN_ID>/
```

The required confirmation phrase is:

```text
CONFIRM LOCAL ARTIFACTS QUARANTINE
```

Quarantine must preserve relative paths and produce a restore manifest. Raw maps, rosbags, and manual review items require a second explicit confirmation.

## Restore

Use the generated quarantine manifest to move files back to their original relative paths. Do not overwrite newer files without inspecting them first.

## Never Auto-Delete

Never automatically delete or quarantine rosbags, `.db3`, `.bag`, `.mcap`, raw `.pgm`/`.yaml` maps, `.mp4` evidence above 10 MB, point clouds, manifests, QA reports, or physical mapping sessions.
