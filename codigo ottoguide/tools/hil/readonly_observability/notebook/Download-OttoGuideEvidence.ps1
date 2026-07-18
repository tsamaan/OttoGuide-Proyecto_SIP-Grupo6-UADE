<#
  WEB-HIL-R1 — Download-OttoGuideEvidence.ps1
  Descarga la evidencia compacta (manifiesto + hashes + estado final) del
  REMOTE_RUN_ROOT via scp. NO descarga el raw completo por defecto (puede ser
  varios GiB); usar -IncludeRaw explicitamente y con criterio.
#>
param(
  [string]$SshRoot = 'C:\OG\OttoGuide-SSH',
  [string]$RemoteRunRoot,
  [string]$LocalDestination = (Join-Path $env:USERPROFILE 'Documents\OttoGuide-HIL-Evidence'),
  [switch]$IncludeRaw
)
$ErrorActionPreference = 'Stop'
$stateDir = Join-Path $SshRoot 'state'
if (-not $RemoteRunRoot) {
  $rrPath = Join-Path $stateDir 'remote_run_root.txt'
  if (Test-Path $rrPath) { $RemoteRunRoot = (Get-Content $rrPath -Raw).Trim() }
}
if (-not $RemoteRunRoot) { throw "Sin RemoteRunRoot." }
$genConf = Join-Path $SshRoot 'generated_target.conf'
if (-not (Test-Path $genConf)) { throw "Sin $genConf (corre Test-OttoGuideConnection.ps1 primero)." }

$dest = Join-Path $LocalDestination ("run_" + (Get-Date).ToUniversalTime().ToString('yyyyMMddTHHmmssZ'))
New-Item -ItemType Directory -Path $dest -Force | Out-Null

$compact = @('SHA256SUMS.txt', 'REMOTE_FILE_MANIFEST.json', 'FINALIZATION_COMPLETE.json',
             'bms_probe.json', 'POSTLAUNCH_GATE.json', 'pids.json')
foreach ($f in $compact) {
  & scp -F $genConf "ottoguide-batch:$RemoteRunRoot/$f" $dest 2>$null
}
& scp -F $genConf "ottoguide-batch:$RemoteRunRoot/recorder_data/recorder_state.json" $dest 2>$null

if ($IncludeRaw) {
  Write-Host "[evidence] -IncludeRaw: descargando raw completo (puede tardar y ocupar mucho espacio)..."
  & scp -F $genConf -r "ottoguide-batch:$RemoteRunRoot/recorder_data" (Join-Path $dest 'recorder_data_raw')
  & scp -F $genConf -r "ottoguide-batch:$RemoteRunRoot/bridge_data" (Join-Path $dest 'bridge_data_raw')
} else {
  Write-Host "[evidence] Raw completo NO descargado (usar -IncludeRaw explicitamente). Sigue preservado en el Companion."
  "REMOTE_RUN_ROOT = $RemoteRunRoot`nSTATUS = preservado en el Companion, no descargado en esta corrida." |
    Out-File -Encoding utf8 (Join-Path $dest 'RAW_RETRIEVAL_PENDING.txt')
}

Write-Host "[evidence] Descargado en: $dest"
$dest
