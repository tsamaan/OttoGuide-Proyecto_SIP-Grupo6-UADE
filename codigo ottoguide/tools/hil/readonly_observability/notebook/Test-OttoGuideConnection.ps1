<#
  WEB-HIL-R1 — Test-OttoGuideConnection.ps1 (portable)
  Preflight de conexion durable: resuelve el target, valida fingerprint y comprueba
  autenticacion batch + identidad remota + eth0. Escribe connection_proof.json
  (nunca credenciales).
#>
param(
  [string]$SshRoot = 'C:\OG\OttoGuide-SSH',
  [string]$IdentityName = 'id_ed25519_ottoguide_robot',
  [string]$RemoteUser = 'unitree',
  [string]$ExpectedFingerprint,
  [string]$ExpectedHostname = 'ubuntu'
)
$ErrorActionPreference = 'Stop'
$here = $PSScriptRoot
$stateDir = Join-Path $SshRoot 'state'

& (Join-Path $here 'Resolve-OttoGuideTarget.ps1') -SshRoot $SshRoot -ExpectedFingerprint $ExpectedFingerprint | Out-Null
& (Join-Path $here 'Write-OttoGuideHostKeyPin.ps1') -SshRoot $SshRoot | Out-Null
& (Join-Path $here 'Write-OttoGuideSshConfig.ps1') -SshRoot $SshRoot -IdentityName $IdentityName -RemoteUser $RemoteUser | Out-Null

$genConf = Join-Path $SshRoot 'generated_target.conf'
$out = & cmd /c "ssh -F `"$genConf`" ottoguide-batch `"echo AUTH_OK; hostname; whoami; ip -brief address show eth0`" 2>nul"
$text = ($out -join "`n")
$authOk = $text -match 'AUTH_OK'
$hostOk = $text -match ('(?m)^' + [regex]::Escape($ExpectedHostname) + '$')
$userOk = $text -match ('(?m)^' + [regex]::Escape($RemoteUser) + '$')
$eth0Ok = $text -match 'eth0'
$target = (Get-Content (Join-Path $stateDir 'target.json') -Raw | ConvertFrom-Json).target

$proof = [ordered]@{
  utc = (Get-Date).ToUniversalTime().ToString('yyyy-MM-ddTHH:mm:ssZ')
  target = $target; auth_ok = [bool]$authOk; hostname_match = [bool]$hostOk
  user_match = [bool]$userOk; eth0_present = [bool]$eth0Ok
  passed = [bool]($authOk -and $hostOk -and $userOk -and $eth0Ok)
}
$proof | ConvertTo-Json | Out-File -Encoding ascii (Join-Path $stateDir 'connection_proof.json')
$out
if (-not $proof.passed) { Write-Error "Preflight FAILED"; exit 1 }
Write-Host "[test] PASS - ottoguide-batch operativo, eth0 presente."
