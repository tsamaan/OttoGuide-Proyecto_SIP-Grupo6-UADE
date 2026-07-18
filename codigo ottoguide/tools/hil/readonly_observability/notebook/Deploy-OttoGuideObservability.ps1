<#
  WEB-HIL-R1 — Deploy-OttoGuideObservability.ps1 (fail-closed, portable)
  Transfiere EXCLUSIVAMENTE los 9 archivos de la allowlist del Companion runtime +
  su manifiesto de hashes, valida hashes remotos (sha256sum -c), ejecuta el static
  gate propagando el exit code, corre el probe BMS, arranca el supervisor
  desacoplado y EXIGE que postlaunch_gate.py pase antes de declarar listo.

  El interprete Python remoto se resuelve SIEMPRE en runtime via
  companion/discover_companion_python.sh -- ningun path de venv se fija como
  autoridad permanente en este script.
#>
param(
  [string]$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')),
  [string]$SshRoot = 'C:\OG\OttoGuide-SSH',
  [string]$IdentityName = 'id_ed25519_ottoguide_robot',
  [string]$RemoteUser = 'unitree',
  [string]$ExpectedFingerprint,
  [string]$RemoteBase = '/home/unitree/OttoGuide-Agent-Runs/LIVE_OBSERVABILITY_HIL_R1',
  [string]$SessionId
)
$ErrorActionPreference = 'Stop'
$here = $PSScriptRoot
$companionDir = Join-Path $RepoRoot 'companion'
$stateDir = Join-Path $SshRoot 'state'
if (-not $SessionId) { $SessionId = 'hilr1-' + (Get-Date).ToUniversalTime().ToString('yyyyMMddTHHmmssZ') }

& (Join-Path $here 'Resolve-OttoGuideTarget.ps1') -SshRoot $SshRoot -ExpectedFingerprint $ExpectedFingerprint | Out-Null
& (Join-Path $here 'Write-OttoGuideHostKeyPin.ps1') -SshRoot $SshRoot | Out-Null
& (Join-Path $here 'Write-OttoGuideSshConfig.ps1') -SshRoot $SshRoot -IdentityName $IdentityName -RemoteUser $RemoteUser | Out-Null
$genConf = Join-Path $SshRoot 'generated_target.conf'
function Invoke-RemoteCmd([string]$cmd) { & ssh -F $genConf ottoguide-batch $cmd }

$RemoteRunRoot = "$RemoteBase/run_$SessionId"
$sums = Join-Path $companionDir 'REMOTE_RUNTIME_SHA256SUMS.txt'
if (-not (Test-Path $sums)) { throw "Falta $sums." }

$allowlist = @(
  'ottoguide_bms_probe.py', 'ottoguide_common.py', 'ottoguide_observability_supervisor.py',
  'ottoguide_readonly_bridge.py', 'ottoguide_remote_recorder.py', 'postlaunch_gate.py',
  'static_gate.py', 'finalize_remote_session.sh', 'start_remote_supervisor.sh'
)
$discoverScript = 'discover_companion_python.sh'
$transferFiles = @($allowlist + 'REMOTE_RUNTIME_SHA256SUMS.txt' + $discoverScript) | ForEach-Object { Join-Path $companionDir $_ }
$missing = $transferFiles | Where-Object { -not (Test-Path $_) }
if ($missing) { throw "Archivo(s) ausente(s), abortando antes de SSH: $($missing -join ', ')" }

Write-Host "[deploy] REMOTE_RUN_ROOT=$RemoteRunRoot session=$SessionId"
Invoke-RemoteCmd "mkdir -p '$RemoteRunRoot/remote_runtime'"

& scp -F $genConf $transferFiles "ottoguide-batch:$RemoteRunRoot/remote_runtime/"
if ($LASTEXITCODE -ne 0) { throw "scp del runtime fallo (rc=$LASTEXITCODE)" }

# ---- hashes fail-closed: los 10 archivos transferidos (9 de la allowlist funcional
# DDS-readonly + discover_companion_python.sh) tienen integridad verificada antes de
# ejecutar CUALQUIERA de ellos, incluido el propio discover_companion_python.sh ----
Write-Host "[deploy] Verificando hashes remotos (sha256sum -c, 10 archivos)..."
Invoke-RemoteCmd "cd '$RemoteRunRoot/remote_runtime' && sha256sum -c REMOTE_RUNTIME_SHA256SUMS.txt"
if ($LASTEXITCODE -ne 0) { throw "HASH MISMATCH en el Companion (rc=$LASTEXITCODE). Deployment DETENIDO (fail-closed). No se ejecuta discover_companion_python.sh ni ningun otro script hasta que el hash coincida." }
Write-Host "[deploy] Hashes remotos OK (REMOTE_HASH_MATCH=10, REMOTE_HASH_MISMATCH=0)."

# ---- descubrimiento REAL del interprete remoto (import real, no find_spec).
# Solo se llega aqui DESPUES de que su propio hash haya pasado arriba. ----
Write-Host "[deploy] Descubriendo interprete Python remoto..."
Invoke-RemoteCmd "chmod +x '$RemoteRunRoot/remote_runtime/$discoverScript'"
$RemotePy = (Invoke-RemoteCmd "'$RemoteRunRoot/remote_runtime/$discoverScript'").Trim()
if (-not $RemotePy -or $LASTEXITCODE -ne 0) { throw "No se encontro un interprete remoto con fastapi+uvicorn+cyclonedds(import real)+unitree_sdk2py." }
Write-Host "[deploy] RemotePy=$RemotePy"

# ---- static gate con propagacion real del exit code ----
Write-Host "[deploy] Static gate remoto (exit code propagado)..."
$gateCmd = "cd '$RemoteRunRoot/remote_runtime' && { '$RemotePy' static_gate.py > ../REMOTE_STATIC_GATE.json; rc=`$?; cat ../REMOTE_STATIC_GATE.json; exit `$rc; }"
Invoke-RemoteCmd $gateCmd
if ($LASTEXITCODE -ne 0) { throw "STATIC GATE FALLO (rc=$LASTEXITCODE). No se inicia el supervisor (fail-closed)." }
Write-Host "[deploy] Static gate OK."

Set-Content -Encoding ascii (Join-Path $stateDir 'remote_run_root.txt') $RemoteRunRoot

# ---- probe BMS -> decision automatica de --enable-bms (BMS es opcional; no bloquea la Web) ----
Write-Host "[deploy] Probe BMS (<=20 msgs)..."
Invoke-RemoteCmd "cd '$RemoteRunRoot/remote_runtime' && '$RemotePy' ottoguide_bms_probe.py --out '$RemoteRunRoot' || true"
$acceptedCmd = "grep -oE 'accepted[^a-z]*(true|false)' '" + $RemoteRunRoot + "/bms_probe.json' | head -1"
$acceptedRaw = (Invoke-RemoteCmd $acceptedCmd)
$bmsFlag = ''
if ($acceptedRaw -match 'true') { $bmsFlag = '--enable-bms'; Write-Host "[deploy] BMS ACEPTADO -> se inicia con BMS." }
else { Write-Host "[deploy] BMS no aceptado ($acceptedRaw) -> se inicia SIN BMS (availability.bms/energy=false, sin bloquear la Web)." }

# ---- arrancar supervisor desacoplado ----
Write-Host "[deploy] Arrancando supervisor desacoplado..."
Invoke-RemoteCmd "OTTOGUIDE_PYBIN='$RemotePy' bash '$RemoteRunRoot/remote_runtime/start_remote_supervisor.sh' '$RemoteRunRoot' '$SessionId' $bmsFlag"

# ---- post-launch gate OBLIGATORIO, exit code propagado real (nunca un cat parcial) ----
Write-Host "[deploy] Post-launch gate (max 15s)..."
$gateCmd2 = "'$RemotePy' '$RemoteRunRoot/remote_runtime/postlaunch_gate.py' " +
            "--out '$RemoteRunRoot' --session '$SessionId' --timeout 15 --host 127.0.0.1 --port 8000"
Invoke-RemoteCmd $gateCmd2
if ($LASTEXITCODE -ne 0) {
  Write-Host "[deploy] POSTLAUNCH GATE FALLO (rc=$LASTEXITCODE)."
  Write-Host "[deploy] RESULT = WEB_HIL_R1_BLOCKED_REMOTE_RUNTIME_STARTUP"
  Write-Host "[deploy] Logs preservados en el Companion; NO se inicia el tunel/frontend."
  throw "Post-launch gate fallo (rc=$LASTEXITCODE). Deployment DETENIDO (fail-closed)."
}
Write-Host "[deploy] Post-launch gate OK."
Write-Host "`n[deploy] LISTO. Levanta Watch-OttoGuideTunnel.ps1 y Start-OttoGuideFrontend.ps1."
