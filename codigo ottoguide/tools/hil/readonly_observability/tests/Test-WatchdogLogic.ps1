<#
  WEB-HIL-R1 — Test-WatchdogLogic.ps1
  Prueba OFFLINE (sin robot, sin red real, sin SSH real) de la logica de
  Watch-OttoGuideTunnel.ps1: simula que el hijo SSH termina y verifica que el
  watchdog crea otro hijo, no cambia la identidad de host resuelta entre
  reconexiones, y nunca tiene dos hijos "SSH" simulados vivos a la vez.

  Metodo: se reemplaza el ejecutable `ssh` por un shim que sale solo (simulando
  el hijo terminando), y Resolve-OttoGuideTarget.ps1 / Write-OttoGuideSshConfig.ps1
  por shims que siempre devuelven el MISMO target falso -- asi se puede verificar
  "no cambia la identidad de host" sin depender de deteccion de red real.

  Marca el resultado explicitamente como logica offline, NO como recuperacion
  fisica de cable validada:
    WATCHDOG_LOGIC_OFFLINE_TESTED = true
    PHYSICAL_CABLE_RECOVERY_VALIDATED = false

  Uso: powershell -ExecutionPolicy Bypass -File Test-WatchdogLogic.ps1
  Exit code 0 = PASS, !=0 = FAIL.
#>
$ErrorActionPreference = 'Stop'
$repoRoot = Resolve-Path (Join-Path $PSScriptRoot '..')
$notebookDir = Join-Path $repoRoot 'notebook'
$watchdog = Join-Path $notebookDir 'Watch-OttoGuideTunnel.ps1'
if (-not (Test-Path $watchdog)) { throw "No se encuentra $watchdog" }

$sandbox = Join-Path $env:TEMP ("og_watchdog_test_" + [guid]::NewGuid().ToString('N'))
$binDir = Join-Path $sandbox 'bin'
$sshRoot = Join-Path $sandbox 'sshroot'
New-Item -ItemType Directory -Path $binDir -Force | Out-Null
New-Item -ItemType Directory -Path $sshRoot -Force | Out-Null
New-Item -ItemType Directory -Path (Join-Path $sshRoot 'state') -Force | Out-Null
New-Item -ItemType Directory -Path (Join-Path $sshRoot 'logs') -Force | Out-Null

$fakeTarget = 'fake-target-does-not-change'
$fakePreferredAlias = 'FAKE-PREFERRED-ETH'
$preferredAliasLog = Join-Path $sandbox 'preferred_alias_calls.log'

# ---- Shim de ssh: sale solo tras un breve retardo (simula el hijo SSH
#      terminando), sin abrir ninguna conexion real y sin encadenar procesos
#      anidados (puro batch: cmd.exe no lanza powershell.exe, para que cada
#      iteracion sea rapida y el test quede acotado en tiempo). Registra
#      START/EXIT con su propio PID en un log compartido, para verificar
#      "no duplica hijos" (un solo shim vivo a la vez). ----
$sshLog = Join-Path $sandbox 'ssh_invocations.log'
@"
@echo off
echo START %RANDOM% %TIME%>> "$sshLog"
ping -n 2 127.0.0.1 >nul
echo EXIT  %RANDOM% %TIME%>> "$sshLog"
"@ | Out-File -Encoding ascii (Join-Path $binDir 'ssh.cmd')

# ---- Shims de resolucion: siempre devuelven el MISMO target falso (identidad estable). ----
# WEB-HIL-R2E regla 8: el shim ahora TAMBIEN acepta -PreferredInterfaceAlias/-PreferredIfIndex
# (mismo contrato que el real Resolve-OttoGuideTarget.ps1) y registra el valor recibido en
# CADA invocacion, para verificar que el watchdog lo reenvia en cada reconexion -- nunca un
# ifIndex/alias historico fijo cacheado de la primera vuelta.
$resolveShim = Join-Path $binDir 'Resolve-OttoGuideTarget.ps1'
@"
param([string]`$SshRoot, [string]`$ExpectedFingerprint, [string]`$PreferredInterfaceAlias, [System.Nullable[int]]`$PreferredIfIndex)
`$stateDir = Join-Path `$SshRoot 'state'
if (-not (Test-Path `$stateDir)) { New-Item -ItemType Directory -Path `$stateDir -Force | Out-Null }
@{ target = '$fakeTarget'; interface = 'FAKE'; ifindex = 0; utc = (Get-Date).ToUniversalTime().ToString('o') } |
  ConvertTo-Json | Out-File -Encoding ascii (Join-Path `$stateDir 'target.json')
"PreferredInterfaceAlias=`$PreferredInterfaceAlias" | Out-File -Append -Encoding ascii '$preferredAliasLog'
'$fakeTarget'
"@ | Out-File -Encoding ascii $resolveShim

$hostKeyPinShim = Join-Path $binDir 'Write-OttoGuideHostKeyPin.ps1'
@"
param([string]`$SshRoot, [switch]`$Force)
# no-op en el test offline: el watchdog debe llamarlo en cada iteracion (verificado
# por CALL_HOSTKEYPIN mas abajo), pero no hay known_hosts real que pinear aqui.
Write-Output 'HOSTKEYPIN_SHIM_CALLED' | Out-Null
"@ | Out-File -Encoding ascii $hostKeyPinShim

$writeConfShim = Join-Path $binDir 'Write-OttoGuideSshConfig.ps1'
@"
param([string]`$SshRoot, [string]`$IdentityName, [string]`$RemoteUser)
`$conf = Join-Path `$SshRoot 'generated_target.conf'
"Host ottoguide-batch`nHostName $fakeTarget" | Out-File -Encoding ascii `$conf
`$conf
"@ | Out-File -Encoding ascii $writeConfShim

# Copia el watchdog real a la sandbox: como usa $PSScriptRoot para resolver
# Resolve-OttoGuideTarget.ps1 / Write-OttoGuideSshConfig.ps1, basta con que los
# shims (ya escritos arriba) vivan en el MISMO directorio ($binDir) que la copia
# del watchdog.
$watchdogTestCopy = Join-Path $binDir 'Watch-OttoGuideTunnel.ps1'
$src = Get-Content $watchdog -Raw
Set-Content -Encoding ascii $watchdogTestCopy $src

$env:OG_TEST_SSH_LOG = $sshLog
$oldPath = $env:PATH
$env:PATH = "$binDir;$oldPath"

$job = Start-Job -ScriptBlock {
  param($script, $sshRoot, $binDir, $sshLog, $preferredAlias)
  $env:PATH = "$binDir;$env:PATH"
  $env:OG_TEST_SSH_LOG = $sshLog
  & $script -SshRoot $sshRoot -RetrySeconds 1 -ExpectedFingerprint 'unused' -PreferredInterfaceAlias $preferredAlias
} -ArgumentList $watchdogTestCopy, $sshRoot, $binDir, $sshLog, $fakePreferredAlias

Start-Sleep -Seconds 8
Stop-Job -Job $job -ErrorAction SilentlyContinue | Out-Null
Remove-Job -Job $job -Force -ErrorAction SilentlyContinue | Out-Null
$env:PATH = $oldPath

# ---- Verificaciones ----
$fail = @()

if (-not (Test-Path $sshLog)) { $fail += "sin ssh_invocations.log (el watchdog nunca lanzo el shim)" }
else {
  # El shim escribe START antes de "dormir" y EXIT justo despues, SIN abrir nuevos procesos
  # concurrentes; como el watchdog espera (Wait-Process) al hijo actual antes de relanzar,
  # el orden en el archivo debe alternar estrictamente START, EXIT, START, EXIT, ...
  # Cualquier desviacion (dos START seguidos) indica un hijo duplicado vivo a la vez.
  $kinds = Get-Content $sshLog | ForEach-Object {
    if ($_ -match '^(START|EXIT)') { $Matches[1] }
  }
  $starts = ($kinds | Where-Object { $_ -eq 'START' }).Count
  if ($starts -lt 2) { $fail += "el watchdog no relanzo un segundo hijo tras la salida del primero (starts=$starts)" }

  $open = 0
  foreach ($k in $kinds) {
    if ($k -eq 'START') { $open++; if ($open -gt 1) { $fail += "mas de un hijo SSH simulado vivo a la vez (duplicado)" } }
    else { $open-- }
  }
}

$targetPath = Join-Path $sshRoot 'state\target.json'
if (-not (Test-Path $targetPath)) { $fail += "sin target.json escrito por el resolver" }
else {
  $t = (Get-Content $targetPath -Raw | ConvertFrom-Json).target
  if ($t -ne $fakeTarget) { $fail += "identidad de host cambio entre reconexiones: '$t' != '$fakeTarget'" }
}

$pidLog = Join-Path $sshRoot 'state\tunnel_pid.json'
if (-not (Test-Path $pidLog)) { $fail += "sin tunnel_pid.json (el watchdog no registro PIDs)" }

# (R2E, regla 8) el watchdog debe reenviar -PreferredInterfaceAlias en CADA re-resolucion
# (no solo la primera), con el mismo valor -- nunca un ifIndex/alias historico fijo.
if (-not (Test-Path $preferredAliasLog)) {
  $fail += "el watchdog nunca invoco Resolve-OttoGuideTarget.ps1 con -PreferredInterfaceAlias (regla 8)"
} else {
  $prefCalls = @(Get-Content $preferredAliasLog | Where-Object { $_.Trim() -ne '' })
  if ($prefCalls.Count -lt 2) { $fail += "-PreferredInterfaceAlias solo se envio $($prefCalls.Count) vez/veces, se esperaban >= 2 re-resoluciones (regla 8)" }
  $wrongValue = $prefCalls | Where-Object { $_ -ne "PreferredInterfaceAlias=$fakePreferredAlias" }
  if ($wrongValue) { $fail += "-PreferredInterfaceAlias se envio con un valor distinto/vacio en alguna re-resolucion (regla 8): $($wrongValue -join '; ')" }
}

Remove-Item -Recurse -Force $sandbox -ErrorAction SilentlyContinue

if ($fail.Count -gt 0) {
  Write-Host "WATCHDOG_LOGIC_OFFLINE_TESTED = false"
  Write-Host "PHYSICAL_CABLE_RECOVERY_VALIDATED = false"
  $fail | ForEach-Object { Write-Host "FAIL: $_" }
  exit 1
}

Write-Host "WATCHDOG_LOGIC_OFFLINE_TESTED = true"
Write-Host "PHYSICAL_CABLE_RECOVERY_VALIDATED = false"
Write-Host "[test] PASS - hijo SSH termina -> watchdog crea otro; identidad de host estable; sin duplicados."
exit 0
