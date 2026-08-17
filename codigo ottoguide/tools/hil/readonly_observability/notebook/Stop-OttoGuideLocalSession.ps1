<#
  WEB-HIL-R1 — Stop-OttoGuideLocalSession.ps1
  Detiene UNICAMENTE los procesos locales lanzados por esta suite (frontend, replay,
  tunel watchdog) leyendo sus PIDs desde <SshRoot>\state\*_pid.json. No mata procesos
  ajenos ni por nombre amplio.
#>
param(
  [string]$SshRoot = 'C:\OG\OttoGuide-SSH'
)
$ErrorActionPreference = 'Continue'
$stateDir = Join-Path $SshRoot 'state'

function Stop-ByPidFile([string]$file, [string]$key, [string]$label) {
  $path = Join-Path $stateDir $file
  if (-not (Test-Path $path)) { Write-Host "[stop] ${label}: sin $file"; return }
  $procPid = (Get-Content $path -Raw | ConvertFrom-Json).$key
  if (-not $procPid) { Write-Host "[stop] ${label}: sin PID registrado"; return }
  $proc = Get-Process -Id $procPid -ErrorAction SilentlyContinue
  if (-not $proc) { Write-Host "[stop] $label PID=$procPid ya no existe"; return }
  Stop-Process -Id $procPid -Force -ErrorAction SilentlyContinue
  Write-Host "[stop] $label PID=$procPid detenido"
}

Stop-ByPidFile 'frontend_pid.json' 'frontend' 'frontend'
Stop-ByPidFile 'replay_pid.json' 'replay' 'replay'
# El watchdog de tunel es un loop: detener el proceso registrado como watchdog (si vive
# en esta consola, Ctrl+C es preferible; esto cubre el caso de watchdog en background).
$tp = Join-Path $stateDir 'tunnel_pid.json'
if (Test-Path $tp) {
  $obj = Get-Content $tp -Raw | ConvertFrom-Json
  foreach ($pair in @(@('watchdog','tunnel watchdog'), @('ssh_child','tunnel ssh_child'))) {
    $procPid = $obj.($pair[0])
    $labelText = $pair[1]
    if ($procPid) {
      $proc = Get-Process -Id $procPid -ErrorAction SilentlyContinue
      if ($proc) { Stop-Process -Id $procPid -Force -ErrorAction SilentlyContinue; Write-Host "[stop] ${labelText} PID=$procPid detenido" }
    }
  }
}
Write-Host "[stop] Sesion local detenida (solo procesos propios)."
