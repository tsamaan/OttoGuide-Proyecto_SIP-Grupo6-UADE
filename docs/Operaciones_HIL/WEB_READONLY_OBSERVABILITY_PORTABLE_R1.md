# WEB Read-Only Observability — Runbook portátil (R1)

Herramienta HIL read-only para abrir un dashboard Web con telemetría física
real de un Unitree G1, o un replay offline de frames reales grabados. Ver
límites arquitectónicos en
`docs/Arquitectura/HIL_READONLY_OBSERVABILITY_BOUNDARY.md`.

Todos los scripts viven en
`codigo ottoguide/tools/hil/readonly_observability/`. Los ejemplos usan
`%USERPROFILE%`/`$env:USERPROFILE`; ningún comando depende del nombre de una
Notebook ni de un usuario en particular.

---

## Ruta A — Solo replay (sin robot, sin SSH)

```powershell
# 1. clone
git clone <mirror-url> ottoguide
cd ottoguide

$Tool = "codigo ottoguide\tools\hil\readonly_observability"

# 2. bootstrap local (crea C:\OG\OttoGuide-SSH\state, logs; no requiere robot)
powershell -ExecutionPolicy Bypass -File "$Tool\notebook\Bootstrap-OttoGuideNotebook.ps1"

# 3. instalar requisitos de replay: NINGUNO. El replay server usa solo la
#    biblioteca estandar de Python (ver replay\requirements-replay.txt).

# 4. iniciar replay
powershell -ExecutionPolicy Bypass -File "$Tool\notebook\Start-OttoGuideReplay.ps1"

# 5. servir frontend (build REPLAY precompilado, dist-replay/ -- WEB-HIL-R1B FASE D:
#    selector explicito, nunca el build REAL por default implicito)
powershell -ExecutionPolicy Bypass -File "$Tool\notebook\Start-OttoGuideFrontend.ps1" -Profile replay

# 6. abrir dashboard
start http://127.0.0.1:5173
```

El dashboard mostrará `REPLAY` (nunca `REAL`) con los 10 frames físicos
grabados en `replay/fixtures/r0b1_real_frames.jsonl`, repetidos en loop a
10 Hz.

---

## Ruta B — Notebook nueva + Companion ya configurado

Cuando la clave pública de esta Notebook ya está en
`~/.ssh/authorized_keys` del Companion (por ejemplo, reutilizando una
identidad ya instalada).

```powershell
$Tool = "codigo ottoguide\tools\hil\readonly_observability"

# 1. clone (si no se hizo antes)
git clone <mirror-url> ottoguide; cd ottoguide

# 2. bootstrap (genera identidad SI NO EXISTE; no la sobreescribe)
powershell -ExecutionPolicy Bypass -File "$Tool\notebook\Bootstrap-OttoGuideNotebook.ps1"

# 3. preflight de conexion (resuelve target, valida fingerprint, prueba batch auth)
powershell -ExecutionPolicy Bypass -File "$Tool\notebook\Test-OttoGuideConnection.ps1" `
  -ExpectedFingerprint (Get-Content "$Tool\config\companion.profile.json" | ConvertFrom-Json).ed25519_fingerprint

# 4. desplegar el runtime read-only (hashes + static gate + BMS probe + supervisor + postlaunch gate)
powershell -ExecutionPolicy Bypass -File "$Tool\notebook\Deploy-OttoGuideObservability.ps1" `
  -RepoRoot "$Tool" `
  -ExpectedFingerprint (Get-Content "$Tool\config\companion.profile.json" | ConvertFrom-Json).ed25519_fingerprint

# 5. tunel (dejar corriendo en su propia ventana/consola; es un loop)
powershell -ExecutionPolicy Bypass -File "$Tool\notebook\Watch-OttoGuideTunnel.ps1" `
  -ExpectedFingerprint (Get-Content "$Tool\config\companion.profile.json" | ConvertFrom-Json).ed25519_fingerprint

# 6. frontend (en otra consola; build REAL, dist-real/ -- rutas fisicas siempre -Profile real)
powershell -ExecutionPolicy Bypass -File "$Tool\notebook\Start-OttoGuideFrontend.ps1" -Profile real

# 7. abrir
start http://127.0.0.1:5173
```

La interfaz mostrará "Sin conexión" hasta que el túnel levante, y cambiará
sola a "Conectado" cuando el WebSocket haga el handshake (101).

---

## Ruta C — Notebook nueva + Companion sin clave autorizada

```powershell
$Tool = "codigo ottoguide\tools\hil\readonly_observability"
$Fingerprint = (Get-Content "$Tool\config\companion.profile.json" | ConvertFrom-Json).ed25519_fingerprint

# 1. generar identidad local (no sobreescribe si ya existe)
powershell -ExecutionPolicy Bypass -File "$Tool\notebook\Bootstrap-OttoGuideNotebook.ps1"

# 2. verificar fingerprint ANTES de instalar la clave — Resolve-OttoGuideTarget.ps1
#    solo elige un candidato cuyo fingerprint coincida exactamente (recorriendo
#    TODOS los adaptadores Ethernet Up, no solo el primero); si no hay
#    coincidencia, se detiene (no continua "a ciegas").
powershell -ExecutionPolicy Bypass -File "$Tool\notebook\Resolve-OttoGuideTarget.ps1" `
  -ExpectedFingerprint $Fingerprint

# 2b. pinear la host key verificada en el known_hosts DEDICADO (nunca el global del
#     usuario, nunca indexado por IP -- siempre bajo el alias fijo 'ottoguide-companion').
#     Install-OttoGuidePublicKey.ps1 ya la invoca internamente; se muestra aqui para
#     dejar explicito el orden del flujo.
powershell -ExecutionPolicy Bypass -File "$Tool\notebook\Write-OttoGuideHostKeyPin.ps1"

# 3. instalar la clave publica interactivamente, EXCLUSIVAMENTE via el alias
#    'ottoguide' del config generado (nunca 'usuario@IP' directo, para que la
#    verificacion de host key pase siempre por el known_hosts dedicado ya pineado).
#    El operador escribe la contrasena en el prompt nativo de OpenSSH; el
#    agente/script nunca la ve, no la registra, no la guarda.
powershell -ExecutionPolicy Bypass -File "$Tool\notebook\Install-OttoGuidePublicKey.ps1"

# 4. descubrir Python remoto (se hace automaticamente dentro de Deploy, pero
#    puede probarse por separado):
#    ssh <alias> "companion/discover_companion_python.sh"

# 5. desplegar
powershell -ExecutionPolicy Bypass -File "$Tool\notebook\Deploy-OttoGuideObservability.ps1" `
  -RepoRoot "$Tool" -ExpectedFingerprint $Fingerprint

# 6. tunel + frontend (igual que Ruta B, pasos 5-7)
```

---

## Procedimiento de cierre

```powershell
# 1. finalizar sesion remota (cierre limpio de recorder/bridge, hashes estables;
#    NO borra datos remotos)
powershell -ExecutionPolicy Bypass -File "$Tool\notebook\Finalize-OttoGuideRemoteSession.ps1"

# 2. descargar evidencia compacta (raw completo solo con -IncludeRaw explicito)
powershell -ExecutionPolicy Bypass -File "$Tool\notebook\Download-OttoGuideEvidence.ps1"

# 3. detener procesos locales (frontend, replay, tunel) — solo los propios
powershell -ExecutionPolicy Bypass -File "$Tool\notebook\Stop-OttoGuideLocalSession.ps1"
```

---

## Diagnóstico: recuperación del cable

El watchdog (`Watch-OttoGuideTunnel.ps1`) re-resuelve el target ANTES de cada
intento de conexión y solo crea un hijo SSH a la vez. Si el cable se
desconecta:

1. El hijo SSH actual falla o cuelga; el watchdog espera su salida
   (`Wait-Process`).
2. Al reintentar, `Resolve-OttoGuideTarget.ps1` no encuentra el target (ni
   IPv4 ni el vecino IPv6 anterior) y falla con un mensaje claro; el
   watchdog registra el error y reintenta en ≤2s.
3. Al reconectar el cable, el `ifIndex` puede haber cambiado — el resolver lo
   detecta de nuevo automáticamente en la siguiente iteración (no requiere
   reiniciar el watchdog).
4. Una vez resuelto, el watchdog reconstruye `generated_target.conf` y abre
   un nuevo túnel; el frontend reconecta el WebSocket con backoff propio
   (0.5s → 1s → 2s) y hace backfill ordenado sin recargar la página.

Esta lógica está probada **offline** (`tests/Test-WatchdogLogic.ps1`,
`WATCHDOG_LOGIC_OFFLINE_TESTED = true`). La recuperación real ante una
desconexión física **no** se declara validada en este checkpoint
(`PHYSICAL_CABLE_RECOVERY_VALIDATED = false`) — queda para un checkpoint de
Nivel D con robot físico disponible.

## Diagnóstico: scope IPv6

Un vecino IPv6 link-local (`fe80::...`) requiere el scope `%ifIndex` para ser
enrutable en Windows. `ssh_config` interpreta `%` como token de expansión, así
que debe escaparse como `%%`. `Write-OttoGuideSshConfig.ps1` prueba ambas
variantes (`%%ifIndex` y `%ifIndex` literal) y usa `ssh -G` para verificar
cuál resuelve exactamente al target esperado antes de continuar — no asume la
sintaxis de antemano.

Si `ssh -G <alias>` no muestra el `hostname` esperado, revisar:

- que el adaptador Ethernet siga con `Status = Up` (`Get-NetAdapter`);
- que `Get-NetNeighbor -AddressFamily IPv6` liste el vecino como `Reachable`
  (puede requerir un ping multicast a `ff02::1%<ifIndex>` para refrescar la
  tabla de vecinos, que `Resolve-OttoGuideTarget.ps1` ya hace automáticamente).

## Diagnóstico: Python remoto

`companion/discover_companion_python.sh` prueba, en orden: `OTTOGUIDE_PYBIN`
explícito, el venv conocido de una validación anterior (solo como candidato,
no autoridad fija), otros venvs bajo `/home/unitree` (vía `pyvenv.cfg`), y el
`python3` del sistema. Para cada candidato hace un **import real** (no
`find_spec`) de `fastapi`, `uvicorn` y `cyclonedds` (forzando la carga del
binding nativo con `from cyclonedds.domain import DomainParticipant`), y
resuelve `unitree_sdk2py` dinámicamente. Si ninguno pasa, sale con código 4 y
`Deploy-OttoGuideObservability.ps1` aborta antes de transferir nada al puerto
8000 (fail-closed). No instala nada — la solución es preparar manualmente un
entorno con esas dependencias en el Companion.

## Diagnóstico: WebSocket 403

Causa raíz observada en la validación física: con
`from __future__ import annotations`, la anotación `sock: WebSocket` del
endpoint queda como string y FastAPI la resuelve con `get_type_hints` contra
los globals del **módulo**. Si `WebSocket` solo se importa dentro de una
función (scope local), la resolución falla silenciosamente y el handshake se
rechaza con HTTP 403 — incluso para rutas inexistentes, porque Starlette no
diferencia "sin rutas WS registradas" de "ruta WS mal tipada". El fix (ya
aplicado en `companion/ottoguide_readonly_bridge.py`) es importar `WebSocket`
a nivel de módulo. Si se modifica el bridge y el WS vuelve a fallar con 403,
revisar primero las importaciones a nivel de módulo antes de sospechar de
CORS o del túnel.

## Diagnóstico: systemd linger

`companion/start_remote_supervisor.sh` prefiere `systemd-run --user` **solo**
si el usuario tiene *linger* habilitado (`loginctl show-user <user> -p
Linger`); de lo contrario, sin linger, una unidad `--user` transitoria se
destruye en cuanto se cierra la última sesión SSH, matando recorder/bridge.
Sin linger, se usa `setsid nohup` (reparentado a `init`, sobrevive el cierre
de SSH). Para verificar cuál se usó: `cat $REMOTE_RUN_ROOT/supervisor.boot.log`
muestra `linger=yes -> systemd-run` o `linger=no -> setsid+nohup`.

## Rollback

Ningún paso de este runbook modifica IPv4, Wi-Fi, rutas de red, ni borra
datos en el Companion. Para deshacer una sesión local:

```powershell
powershell -ExecutionPolicy Bypass -File "$Tool\notebook\Stop-OttoGuideLocalSession.ps1"
```

Para descartar por completo el estado SSH generado (config, known_hosts,
PIDs) sin tocar la identidad ni el repositorio:

```powershell
Remove-Item -Recurse -Force C:\OG\OttoGuide-SSH\state, C:\OG\OttoGuide-SSH\logs, `
  C:\OG\OttoGuide-SSH\generated_target.conf -ErrorAction SilentlyContinue
```
