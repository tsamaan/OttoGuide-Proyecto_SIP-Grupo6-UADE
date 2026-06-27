# Evidencia compacta — Fase 2H.2.4

Resúmenes versionados; no se versionan logs masivos. Los logs completos
quedan en `C:\Users\lucas\OttoGuide_2H24_Evidence_20260622T215356Z\`
(raíz Windows, persistido localmente, no versionado en git).

## Contenido

| Archivo | Contenido |
|---|---|
| `test_summary.json` | Comandos, exit codes y clasificación de las suites Windows/WSL y de los verificadores estáticos. |
| `cleanup_timeout_summary.json` | Corrección TOCTOU, tests asociados, y las corridas E2E de timeout (nivel función y nivel CLI real), con auditoría de procesos. |
| `p0_fixture_summary.json` | Los 8 casos de fixture requeridos contra el pipeline P0 real (collector -> bundle -> manifest -> validador), dry-run, y verificación del wrapper en WSL. |
| `runtime_summary.json` | Diagnóstico + hasta 5 intentos de estabilidad runtime, con la clasificación honesta `PARTIAL` y su causa. |
| `evidence_manifest.json` + `.sha256` | Hash de cada uno de los cuatro resúmenes anteriores, y hash del propio manifest. |

## Resultado consolidado

```text
FASE_2H_2_4 = IMPLEMENTED_PENDING_INDEPENDENT_AUDIT
CLEANUP_RACE = FIXED_AND_TESTED
P0_PIPELINE_OFFLINE = FUNCTIONAL_PENDING_INDEPENDENT_AUDIT
RUNTIME_STABILITY = PARTIAL (causa: ENVIRONMENTAL_TRANSIENT, no
  atribuible a cambios de código de esta fase; cleanup limpio en ambos
  fallos)
P0_PHYSICAL_READ_ONLY = NOT_EXECUTED
PHYSICAL_NAVIGATION = NOT_READY
PHYSICAL_MOVEMENT = NOT_AUTHORIZED
```

Ver `documentacion general del proyecto/Arquitectura/MAIN_RUNTIME_NAVIGATION_SELECTION_2H24_P0_PIPELINE_REPORT.md`
para el reporte completo.

## Verificación de integridad

```bash
# evidence_manifest.sha256 contiene una sola línea con el hash de
# evidence_manifest.json (mismo formato que p0_hash_manifest.sha256);
# compara manualmente, no es el formato que entiende `sha256sum -c`:
test "$(sha256sum evidence_manifest.json | awk '{print $1}')" = "$(cat evidence_manifest.sha256)" && echo OK

python3 -c "
import json, hashlib
m = json.load(open('evidence_manifest.json'))
for f in m['files']:
    actual = hashlib.sha256(open(f['filename'], 'rb').read()).hexdigest()
    assert actual == f['sha256'], f['filename']
print('all hashes match')
"
```
