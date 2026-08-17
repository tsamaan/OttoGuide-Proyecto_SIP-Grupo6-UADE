# WEB-HIL-R1C — Auditoría remota independiente y hardening mínimo

## 1. Alcance

Checkpoint: `WEB-HIL-R1C-REMOTE-INDEPENDENT-AUDIT-AND-MINIMAL-HARDENING`.
Auditoría ejecutada desde un clon nuevo e independiente del mirror
`LucasCap12/OttoGuide-Proyecto_SIP-Grupo6-G1-EDU`, rama
`feature/hil-readonly-observability-portable-r1`, sin reutilizar ningún
workspace de checkpoints previos (R1A/R1B).

## 2. Commit auditado

- **Commit auditado (HEAD inicial):** `e6a81a2850d4862424d9517496fcb1b414498113`
- **Base:** `review/orchestrator-unification` @ `97297169eebf5f6a786033f54ee533d4757eb580`
- **Commit inicial en el rango:** `feat(hil): add portable read-only observability kit`

Verificado en el clon nuevo antes de tocar nada: `HEAD` coincide exactamente,
`parent` coincide exactamente con la base, working tree limpio
(`git status --porcelain=v1 --untracked-files=all` vacío).

## 3. CI remota (GitHub Actions)

`gh` no está disponible ni autenticado en este entorno (verificado en Bash y
PowerShell). Por lo tanto:

```
CI_REMOTE_RESULT = NOT_OBSERVED
```

No se trata como PASS. Ningún run de GitHub Actions fue inspeccionado,
descargado ni verificado como parte de esta auditoría.

## 4. Auditoría offline ejecutada (todo desde el clon nuevo)

- Parse de los 19 scripts `.ps1` bajo `readonly_observability/`: 19/19 OK.
- `Test-WatchdogLogic.ps1`: PASS.
- `Test-SshBootstrapLogic.ps1`: PASS (re-ejecutado tras el fix de manifiesto,
  sigue en PASS).
- `Test-InstallerTransport.ps1`: PASS (incluye los 2 escenarios nuevos de
  BatchMode fail-closed añadidos en esta auditoría).
- `Test-FrontendProfileSelector.ps1`: PASS.
- Tests Python stdlib (`tests/test_*.py`, 5 archivos): 35/35 tests OK.
- `static_gate.py`: `passed: true`, 0 DataWriter, 0 imports de movimiento.
- `bash -n` sobre los 3 scripts de `companion/*.sh`: sin errores de sintaxis.
- `npm ci` en `frontend/app`: OK (advertencias de deprecación de `recharts`
  preexistentes, fuera de alcance).
- Tests frontend (`npm run test`, node:test): 7/7 OK.
- Build REAL y build REPLAY: ambos exitosos, bundles JS con nombres
  distintos.
- Manifiestos `DIST_REAL_SHA256SUMS.txt` / `DIST_REPLAY_SHA256SUMS.txt`:
  ambos `CHECK_RESULT=PASS` contra los builds recién generados.
- `/health` del replay server (fixture real `r0b1_real_frames.jsonl`):
  `read_only_demo: true`, `dds_writers_created: 0`,
  `source_profile: "REPLAY"`.
- Secret scan (patrones de alta confianza: password/passwd/api-key/private
  key/`-----BEGIN`): limpio.
- Portability scan (paths personales, IDEAPA~1, usuario/IP hardcodeado fuera
  de la config por defecto documentada): limpio.
- Generación de paquete portable (`build_portable_package.py`): 84 entradas,
  0 rutas sospechosas (`node_modules`, rutas absolutas, `..`), SHA-256
  reproducible entre corridas.

### Clones adicionales `core.autocrlf`

Dos clones temporales adicionales (`core.autocrlf=true` y
`core.autocrlf=false`), ambos ya eliminados tras la validación:

- `DIST_REAL` manifest: PASS en ambos.
- `DIST_REPLAY` manifest: PASS en ambos.
- Perfil REAL horneado (`VITE_DEPLOYMENT_PROFILE:"real"`): confirmado en
  ambos.
- Perfil REPLAY horneado (`VITE_DEPLOYMENT_PROFILE:"replay"`): confirmado en
  ambos.
- Bundles REAL/REPLAY distintos (no byte-idénticos): confirmado en ambos.

## 5. Defectos confirmados y correcciones realizadas

### A. Documentación arquitectónica desactualizada — DOCUMENTATION

`docs/Arquitectura/HIL_READONLY_OBSERVABILITY_BOUNDARY.md` todavía
referenciaba el directorio obsoleto `frontend/dist/` (pre-R1B), sin
mencionar el selector explícito `-Profile real|replay`. Corregido: ahora
referencia `frontend/dist-real/` y `frontend/dist-replay/` por separado,
explica el selector explícito de `Start-OttoGuideFrontend.ps1`, y corrige el
conteo del runtime (9 archivos funcionales + 1 script de descubrimiento = 10
archivos con hash verificado).

### B. Comentario impreciso del deployment — DOCUMENTATION

El encabezado de `notebook/Deploy-OttoGuideObservability.ps1` no enumeraba
explícitamente los tres componentes transferidos (9 archivos funcionales +
`discover_companion_python.sh` + `REMOTE_RUNTIME_SHA256SUMS.txt`). Corregido
solo el comentario; sin cambio de comportamiento funcional (el cuerpo del
script ya operaba correctamente sobre esos mismos archivos).

### C. Instalador no fallaba cerrado en verificación BatchMode — MAJOR

`notebook/Install-OttoGuidePublicKey.ps1` terminaba con `Write-Warning` y
código de salida 0 cuando la verificación BatchMode post-instalación fallaba
(`$LASTEXITCODE -ne 0`), en vez de abortar. Esto permitía que el script
reportara éxito aparente aun cuando la instalación de la clave pública no
quedó realmente confirmada. Corregido: ahora `throw` explícito con mensaje
`"BatchMode fallo despues de instalar la clave publica..."` cuando el rc es
distinto de cero.

Se añadió a `tests/Test-InstallerTransport.ps1` un bloque de prueba nuevo
(sección 6) con dos escenarios aislados (shim de `ssh` con contador de
invocaciones para distinguir instalación vs. verificación BatchMode):

- BatchMode exit 0 → el script debe completar sin lanzar. Verificado: PASS.
- BatchMode exit != 0 → el script debe lanzar (`throw`) con el mensaje
  esperado. Verificado: PASS (antes de esta corrección, este escenario
  habría pasado incorrectamente con exit 0).
- Confirmado adicionalmente en ambos escenarios: ninguna variable de entorno
  de contraseña presente, sin `ssh usuario@IP` directo (cubierto
  estructuralmente en la sección 1 del mismo test), stdin libre (sonda no
  bloqueante de la sección 2b).

### D. CI no verificaba el build comprometido antes de reconstruir — MAJOR

El job Windows de `.github/workflows/hil-readonly-observability-portable.yml`
iba directo a `npm ci` y a los builds sin antes confirmar que los artifacts
YA comprometidos por git (`frontend/dist-real/`, `frontend/dist-replay/`)
coincidieran con sus propios manifiestos. Se añadió un paso nuevo
("Verify COMMITTED dist-real/dist-replay manifests (before any rebuild)")
inmediatamente después de `setup-python` y antes de `setup-node`/`npm ci`,
que ejecuta `generate_dist_manifest.py --check` contra ambos directorios tal
como quedaron en el checkout de git, sin mezclar REAL y REPLAY. Verificado
localmente contra el clon auditado: ambos `CHECK_RESULT=PASS`.

### E. Manifiesto de hashes remotos desactualizado — BLOCKER (encontrado en auditoría adicional sección 7, no en la lista de correcciones confirmadas original, pero corregido por ser bloqueante y estar dentro del alcance permitido)

`companion/REMOTE_RUNTIME_SHA256SUMS.txt` contenía hashes SHA-256 que NO
coincidían con el contenido real de los 7 archivos `.py` listados (los 3
`.sh` sí coincidían). Verificado de forma independiente calculando
`sha256sum` real de cada archivo y comparando contra el manifiesto
comprometido. `notebook/Deploy-OttoGuideObservability.ps1` ejecuta
`sha256sum -c REMOTE_RUNTIME_SHA256SUMS.txt` en el Companion real y aborta
fail-closed ante cualquier mismatch — con el manifiesto tal como estaba
comprometido, el deployment habría fallado siempre en un robot real, en el
primer intento. Ningún test offline existente detectaba esto porque
`Test-SshBootstrapLogic.ps1` solo verificaba propiedades estructurales del
archivo (existe, 10 entradas, incluye el script de descubrimiento), nunca
que los hashes coincidieran con el contenido real. Corregido: manifiesto
regenerado con `sha256sum` real de los 10 archivos; verificado
`sha256sum -c` → 10/10 `OK`. Re-ejecutados `Test-SshBootstrapLogic.ps1` y
`static_gate.py` tras el fix: ambos siguen en PASS, sin regresión.

## 6. Auditoría adicional sin expansión de alcance (solo lectura)

Revisados sin modificación (ningún fallo reproducible encontrado):

- Resolver multiadaptador (`Resolve-OttoGuideTarget.ps1` +
  `OttoGuideSshBootstrapHelpers.ps1`): selección fail-closed por fingerprint
  exacto, sin cortocircuito por adaptador. Sin hallazgos.
- Pin del host key (`Write-OttoGuideHostKeyPin.ps1`): recalcula el
  fingerprint de forma independiente, nunca confía ciegamente en el valor
  declarado. Sin hallazgos.
- Watchdog (`Watch-OttoGuideTunnel.ps1`): re-resuelve el target antes de
  cada intento, sin duplicación de procesos. Sin hallazgos.
- Package builder (`build_portable_package.py`): exclusiones de
  secretos/estado correctas. Sin hallazgos.
- Replay server: sin imports DDS/SDK del robot, solo lee fixture local.
  Sin hallazgos.
- Static gate: robusto para el uso directo del código actual; una
  ofuscación deliberada (getattr dinámico, alias de import) podría
  teóricamente evadir el análisis AST, pero esto es una limitación teórica
  de la herramienta, no un defecto explotado en el código actual —
  clasificado DEFERRED_PHYSICAL / fuera de alcance de este checkpoint
  (ninguna corrección aplicada).
- Bridge read-only (`ottoguide_readonly_bridge.py`): solo importa
  `DataReader`, cero `DataWriter`, mutaciones HTTP devuelven 405. Sin
  hallazgos.
- Evidencia física previa (`docs/Operaciones_HIL/Evidencia/`): no alcanzable
  desde este árbol de auditoría con contenido adicional que revisar más
  allá de lo ya validado en checkpoints anteriores.

## 7. Alcance físico NO validado por este checkpoint

Este checkpoint fue enteramente offline: ningún SSH real al Companion,
ningún acceso al robot físico, ningún DDS físico, ningún movimiento. No se
afirma ni se implica que este checkpoint haya validado:

- Precisión o autoridad de `/odom` como fuente de control.
- TF (transformadas).
- Nav2 ni ningún componente de navegación autónoma.
- Cualquier comportamiento físico del robot más allá de lo ya documentado en
  `docs/Operaciones_HIL/Evidencia/WEB_R0B1_REAL_20260717/` (sesión física
  previa, no repetida ni re-validada aquí).

Esta herramienta es y sigue siendo un observador read-only; ningún hallazgo
o corrección de este checkpoint le otorga autoridad de movimiento, de
navegación, ni la convierte en fuente autoritativa de ningún dato de
navegación.

## 8. Resultado

```
RESULT = WEB_HIL_R1C_REMOTE_AUDITED_AND_HARDENED
```
