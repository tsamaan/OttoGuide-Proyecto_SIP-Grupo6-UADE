# GitHub robot branch validation

## Repo validado

Repo esperado:

```text
https://github.com/tsamaan/OttoGuide-Proyecto_SIP-Grupo6-UADE.git
```

Rama esperada:

```text
robot
```

HEAD esperado (referencia histórica de esta auditoría):

```text
fad510f
```

HEAD canónico vigente al 2026-06-18:

```text
2b7fc5c
```

## Remotos locales

| Remoto | URL observada | Uso |
|---|---|---|
| `origin` / `grupo` / `target-uade` | `https://github.com/tsamaan/OttoGuide-Proyecto_SIP-Grupo6-UADE.git` | Repo canónico del equipo |

Nota GitOps: legacy mirror removed; canonical repository is `https://github.com/tsamaan/OttoGuide-Proyecto_SIP-Grupo6-UADE.git`.

## Estado local

| Check | Resultado |
|---|---|
| Rama local | `robot` |
| HEAD local | `fad510f` |
| Commit HEAD | `tools(hil): mark physical mapping scripts executable` |
| Working tree inicial | Limpio |

## Resultado `git ls-remote`

| Comando | Resultado |
|---|---|
| `git ls-remote target-uade refs/heads/robot` | `fad510f1914c0317b9447555982a0be3d0482f56` |
| `git ls-remote target-uade refs/heads/main` | `3a1f13574e4a27d9aff2bfd38b3659951e8cb264` |
| `git ls-remote https://github.com/tsamaan/OttoGuide-Proyecto_SIP-Grupo6-UADE.git refs/heads/robot` | `fad510f1914c0317b9447555982a0be3d0482f56` |
| `git ls-remote https://github.com/tsamaan/OttoGuide-Proyecto_SIP-Grupo6-UADE.git refs/heads/main` | `3a1f13574e4a27d9aff2bfd38b3659951e8cb264` |

Conclusion Git remota: `GITHUB ROBOT BRANCH VALIDATED` por `git ls-remote`.

## Vista publica GitHub/API

| URL | Resultado |
|---|---|
| `https://github.com/tsamaan/OttoGuide-Proyecto_SIP-Grupo6-UADE` | HTTP 404 |
| `https://github.com/tsamaan/OttoGuide-Proyecto_SIP-Grupo6-UADE/tree/robot` | HTTP 404 |
| `https://github.com/tsamaan/OttoGuide-Proyecto_SIP-Grupo6-UADE/tree/main` | HTTP 404 |
| `https://api.github.com/repos/tsamaan/OttoGuide-Proyecto_SIP-Grupo6-UADE/branches` | JSON `Not Found`, status `404` |
| API branch `robot` | JSON `Not Found`, status `404` |
| API branch `main` | JSON `Not Found`, status `404` |

Interpretacion: Git autenticado/local ve el repo y ramas, pero la vista publica/API anonima no. Posibles causas: repo privado, permisos/autenticacion o diferencia de visibilidad. No se asume causa sin evidencia adicional.

## Archivos esperados encontrados en `target-uade/robot`

| Archivo | Estado |
|---|---|
| `codigo ottoguide/config/cyclonedds.foxy.xml` | Encontrado |
| `codigo ottoguide/ros2_ws/src/ottoguide_livox_sdk_bridge/launch/scan_gate.launch.py` | Encontrado |
| `codigo ottoguide/tools/hil/physical_mapping_route.sh` | Encontrado |
| `codigo ottoguide/tools/hil/physical_mapping_status.sh` | Encontrado |
| `codigo ottoguide/tools/hil/physical_mapping_stop.sh` | Encontrado |
| `codigo ottoguide/tools/hil/physical_mapping_finalize.sh` | Encontrado |
| `codigo ottoguide/tools/hil/physical_mapping_package_for_transfer.sh` | Encontrado |
| `codigo ottoguide/tools/hil/physical_mapping_clean_map.py` | Encontrado |
| `documentacion general del proyecto/Auditorias/LOCAL_ARTIFACTS_AUDIT_RUNBOOK.md` | Reubicado tras consolidacion documental |
| `documentacion general del proyecto/Operaciones_HIL/Mapeo/PHYSICAL_MAPPING_ROUTE_RUNBOOK.md` | Reubicado tras consolidacion documental |
| `codigo ottoguide/tools/hil/audit_local_artifacts.py` | Reubicado tras raiz limpia estricta |
| `.gitignore` | Encontrado |

## Archivos esperados no encontrados en el baseline `target-uade/robot:fad510f`

| Archivo | Resultado |
|---|---|
| `codigo ottoguide/tools/hil/ottoguide-map` | No encontrado en `target-uade/robot:fad510f` |
| `codigo ottoguide/tools/hil/office_sensor_capture.sh` | No encontrado en `target-uade/robot:fad510f` |
| `documentacion general del proyecto/Operaciones_HIL/OTTOGUIDE_MAP_EXECUTABLE_QUICKSTART.md` | No encontrado en `target-uade/robot:fad510f`; reubicado tras consolidacion documental |

Estos archivos fueron reportados como creados en el robot/local runtime, pero no estaban validados como subidos a GitHub en la rama `robot` al momento de auditar el baseline `fad510f`. La sincronizacion posterior debe agregarlos en un nuevo commit.

## Validacion de ejecutable remoto

En el baseline `fad510f`, `git show target-uade/robot:"codigo ottoguide/tools/hil/ottoguide-map"` fallo porque el path no existia en esa rama remota. Por lo tanto no se pudo confirmar en GitHub, antes del commit de sincronizacion, que el ejecutable remoto soporte:

- `prep`
- `start`
- `timed`
- `status`
- `stop`
- `finalize`
- `package`
- `help`

Tampoco se pudo confirmar en esa rama remota pre-sync que ese ejecutable no publique `/cmd_vel`, no mueva el robot, no requiera `/tf`, use SIGINT limpio, genere artifacts, empaquete `.tar.gz` o imprima `scp`.

## Comandos usados

```powershell
git status --short --branch --untracked-files=all
git rev-parse --short HEAD
git log --oneline -12
git remote -v
git branch -vv
git ls-remote target-uade refs/heads/robot
git ls-remote target-uade refs/heads/main
git ls-remote https://github.com/tsamaan/OttoGuide-Proyecto_SIP-Grupo6-UADE.git refs/heads/robot
git ls-remote https://github.com/tsamaan/OttoGuide-Proyecto_SIP-Grupo6-UADE.git refs/heads/main
git fetch target-uade robot
git rev-parse --short target-uade/robot
git log --oneline target-uade/robot -12
git ls-tree -r --name-only target-uade/robot
git show target-uade/robot:"codigo ottoguide/tools/hil/ottoguide-map"
curl.exe -I https://github.com/tsamaan/OttoGuide-Proyecto_SIP-Grupo6-UADE
curl.exe -I https://github.com/tsamaan/OttoGuide-Proyecto_SIP-Grupo6-UADE/tree/robot
curl.exe https://api.github.com/repos/tsamaan/OttoGuide-Proyecto_SIP-Grupo6-UADE/branches/robot
```

## Conclusion

La rama `robot` del repo esperado esta validada por Git remoto autenticado en `fad510f`.

La disponibilidad publica por navegador/API no esta validada porque devuelve 404.

El tooling `physical_mapping_*`, `scan_gate`, CycloneDDS y runbooks principales estan en `target-uade/robot`.

El ejecutable `ottoguide-map`, `office_sensor_capture.sh` y la quickstart `OTTOGUIDE_MAP_EXECUTABLE_QUICKSTART.md` no estaban en `target-uade/robot` a `fad510f`; deben quedar incorporados por el commit de sincronizacion posterior a esta auditoria.
