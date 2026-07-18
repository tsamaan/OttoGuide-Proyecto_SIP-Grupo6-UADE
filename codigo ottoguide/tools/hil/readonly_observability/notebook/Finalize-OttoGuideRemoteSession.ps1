<#
  WEB-HIL-R1 — Finalize-OttoGuideRemoteSession.ps1
  Ejecuta finalize_remote_session.sh en el Companion (cierre limpio de recorder/bridge,
  manifiesto + hashes estables) sobre el REMOTE_RUN_ROOT registrado localmente.
  NO borra datos remotos. Preserva la copia remota completa.
#>
param(
  [string]$SshRoot = 'C:\OG\OttoGuide-SSH',
  [string]$IdentityName = 'id_ed25519_ottoguide_robot',
  [string]$RemoteUser = 'unitree',
  [string]$RemoteRunRoot,
  [int]$GraceSeconds = 12
)
$ErrorActionPreference = 'Stop'
$stateDir = Join-Path $SshRoot 'state'
if (-not $RemoteRunRoot) {
  $rrPath = Join-Path $stateDir 'remote_run_root.txt'
  if (Test-Path $rrPath) { $RemoteRunRoot = (Get-Content $rrPath -Raw).Trim() }
}
if (-not $RemoteRunRoot) { throw "Sin RemoteRunRoot (corre Deploy-OttoGuideObservability.ps1 primero o pasa -RemoteRunRoot)." }

$genConf = Join-Path $SshRoot 'generated_target.conf'
if (-not (Test-Path $genConf)) { throw "Sin $genConf (corre Test-OttoGuideConnection.ps1 primero)." }

Write-Host "[finalize] REMOTE_RUN_ROOT=$RemoteRunRoot grace=${GraceSeconds}s"
& ssh -F $genConf ottoguide-batch "bash '$RemoteRunRoot/remote_runtime/finalize_remote_session.sh' '$RemoteRunRoot' $GraceSeconds"
if ($LASTEXITCODE -ne 0) { throw "finalize_remote_session.sh fallo (rc=$LASTEXITCODE)." }
Write-Host "[finalize] OK. Datos remotos preservados (no se borro nada)."
