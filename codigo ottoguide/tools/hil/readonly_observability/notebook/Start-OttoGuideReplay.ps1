<#
  WEB-HIL-R1 — Start-OttoGuideReplay.ps1
  Inicia el replay server offline (replay/ottoguide_replay_server.py) en
  127.0.0.1:<Port>. No requiere robot, SSH ni companion. session_id explicito REPLAY.
#>
param(
  [string]$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')),
  [string]$SshRoot = 'C:\OG\OttoGuide-SSH',
  [int]$Port = 8000,
  [string]$Python
)
$ErrorActionPreference = 'Stop'
$replayDir = Join-Path $RepoRoot 'replay'
$server = Join-Path $replayDir 'ottoguide_replay_server.py'
if (-not (Test-Path $server)) { throw "No existe $server." }
$logDir = Join-Path $SshRoot 'logs'
$stateDir = Join-Path $SshRoot 'state'
foreach ($d in @($logDir, $stateDir)) { if (-not (Test-Path $d)) { New-Item -ItemType Directory -Path $d -Force | Out-Null } }

if (-not $Python) {
  $Python = (Get-Command python -ErrorAction SilentlyContinue).Source
  if (-not $Python) { $Python = (Get-Command python3 -ErrorAction SilentlyContinue).Source }
}
if (-not $Python) { throw "Python no encontrado para el replay server." }

Write-Host "[replay] Iniciando replay server en http://127.0.0.1:$Port (source_profile=REPLAY)"
$p = Start-Process -FilePath $Python -ArgumentList @($server, '--host', '127.0.0.1', '--port', "$Port") `
      -WorkingDirectory $replayDir -PassThru -NoNewWindow `
      -RedirectStandardError (Join-Path $logDir 'replay_stderr.log') `
      -RedirectStandardOutput (Join-Path $logDir 'replay_stdout.log')
Set-Content -Encoding ascii (Join-Path $stateDir 'replay_pid.json') (@{ replay = $p.Id; port = $Port } | ConvertTo-Json)
Write-Host "[replay] PID=$($p.Id)."
$p.Id
