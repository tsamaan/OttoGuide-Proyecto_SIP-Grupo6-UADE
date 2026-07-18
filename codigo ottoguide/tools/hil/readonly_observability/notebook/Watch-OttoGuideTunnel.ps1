<#
  WEB-HIL-R1 — Watch-OttoGuideTunnel.ps1
  Watchdog real del tunel local->Companion (no un unico hijo SSH suelto):

    - re-resuelve el target ANTES de cada intento de conexion (soporta cable
      desconectado/reconectado, ifIndex cambiado, IPv4 disponible, fallback IPv6);
    - crea UN UNICO hijo SSH por intento;
    - espera su salida (Wait-Process);
    - si el hijo termina, vuelve a resolver y reintenta en <= 2 segundos;
    - registra PID del watchdog y del hijo actual en tunnel_pid.json;
    - NUNCA mata procesos SSH ajenos (solo espera/observa el propio hijo).

  Opciones SSH: BatchMode=yes, ExitOnForwardFailure=yes, ConnectTimeout=3,
  ConnectionAttempts=1, ServerAliveInterval=5, ServerAliveCountMax=2.
#>
param(
  [string]$SshRoot = 'C:\OG\OttoGuide-SSH',
  [string]$IdentityName = 'id_ed25519_ottoguide_robot',
  [string]$RemoteUser = 'unitree',
  [string]$ExpectedFingerprint,
  [int]$LocalPort = 8000,
  [int]$RemotePort = 8000,
  [int]$RetrySeconds = 2
)
$ErrorActionPreference = 'Stop'
$here = $PSScriptRoot
$stateDir = Join-Path $SshRoot 'state'
$logDir = Join-Path $SshRoot 'logs'
foreach ($d in @($stateDir, $logDir)) { if (-not (Test-Path $d)) { New-Item -ItemType Directory -Path $d -Force | Out-Null } }

Write-Host "[watchdog] $(Get-Date -Format o) iniciando (watchdog PID=$PID)"

while ($true) {
  # Re-resolver ANTES de cada intento: soporta cable desconectado/reconectado e ifIndex nuevo.
  try {
    & (Join-Path $here 'Resolve-OttoGuideTarget.ps1') -SshRoot $SshRoot -ExpectedFingerprint $ExpectedFingerprint | Out-Null
    & (Join-Path $here 'Write-OttoGuideHostKeyPin.ps1') -SshRoot $SshRoot | Out-Null
    & (Join-Path $here 'Write-OttoGuideSshConfig.ps1') -SshRoot $SshRoot -IdentityName $IdentityName -RemoteUser $RemoteUser | Out-Null
  } catch {
    Write-Host "[watchdog] $(Get-Date -Format o) no se pudo resolver target ($($_.Exception.Message)); reintentando en ${RetrySeconds}s..."
    Start-Sleep -Seconds $RetrySeconds
    continue
  }

  $genConf = Join-Path $SshRoot 'generated_target.conf'
  $sshArgs = @(
    '-F', $genConf,
    '-o', 'BatchMode=yes',
    '-o', 'ExitOnForwardFailure=yes',
    '-o', 'ConnectTimeout=3',
    '-o', 'ConnectionAttempts=1',
    '-o', 'ServerAliveInterval=5',
    '-o', 'ServerAliveCountMax=2',
    '-N',
    '-L', "127.0.0.1:${LocalPort}:127.0.0.1:${RemotePort}",
    'ottoguide-batch'
  )
  Write-Host "[watchdog] $(Get-Date -Format o) iniciando UN hijo SSH..."
  $p = Start-Process -FilePath 'ssh' -ArgumentList $sshArgs -PassThru -NoNewWindow `
        -RedirectStandardError (Join-Path $logDir 'tunnel_stderr.log') `
        -RedirectStandardOutput (Join-Path $logDir 'tunnel_stdout.log')
  $pidObj = [ordered]@{ watchdog = $PID; ssh_child = $p.Id; local_port = $LocalPort; remote_port = $RemotePort }
  $pidObj | ConvertTo-Json | Out-File -Encoding ascii (Join-Path $stateDir 'tunnel_pid.json')
  Write-Host "[watchdog] ssh_child PID=$($p.Id)  L${LocalPort}->${RemotePort}"

  Wait-Process -Id $p.Id -ErrorAction SilentlyContinue
  Write-Host "[watchdog] $(Get-Date -Format o) hijo SSH (PID=$($p.Id)) termino. Reintentando en ${RetrySeconds}s..."
  Start-Sleep -Seconds $RetrySeconds
}
