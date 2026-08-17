<#
  WEB-HIL-R1A — Bootstrap-OttoGuideNotebook.ps1
  Prepara una Notebook nueva para conectarse al Companion OttoGuide:

    1. crea <SshRoot> (por defecto C:\OG\OttoGuide-SSH) con state/ y logs/;
    2. genera localmente una identidad ED25519 dedicada
       (~/.ssh/id_ed25519_ottoguide_robot) SI NO EXISTE -- nunca la sobreescribe,
       via New-OttoGuideEd25519KeyNoPassphrase (OttoGuideKeygenHelpers.ps1), que
       intenta una forma de 'ssh-keygen -N' y VERIFICA el resultado real antes de
       confiar en 'exit 0' (no asume que una unica invocacion funciona en todas
       las versiones de PowerShell/OpenSSH);
    3. crea <SshRoot>\known_hosts vacio (el pinning REAL de la host key, con la
       clave publica completa verificada contra el fingerprint esperado, lo hace
       Write-OttoGuideHostKeyPin.ps1 DESPUES de Resolve-OttoGuideTarget.ps1 -- este
       bootstrap NO pinea nada por si mismo).

  Flujo completo documentado (ver runbook):
    bootstrap identidad local (este script)
    -> Resolve-OttoGuideTarget.ps1        (resuelve target + valida fingerprint)
    -> Write-OttoGuideHostKeyPin.ps1      (pinea la host key en known_hosts dedicado)
    -> Write-OttoGuideSshConfig.ps1       (genera generated_target.conf)
    -> Install-OttoGuidePublicKey.ps1     (instala la clave publica del cliente, si falta)
    -> Test-OttoGuideConnection.ps1       (prueba BatchMode)

  No instala nada, no requiere admin, no toca Wi-Fi/IPv4/rutas. Usa siempre
  $env:USERPROFILE -- nunca un nombre de notebook fijo.
#>
param(
  [string]$SshRoot = 'C:\OG\OttoGuide-SSH',
  [string]$IdentityName = 'id_ed25519_ottoguide_robot'
)
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'OttoGuideKeygenHelpers.ps1')

foreach ($d in @($SshRoot, (Join-Path $SshRoot 'state'), (Join-Path $SshRoot 'logs'))) {
  if (-not (Test-Path $d)) { New-Item -ItemType Directory -Path $d -Force | Out-Null; Write-Host "[bootstrap] creado $d" }
}

$sshDir = Join-Path $env:USERPROFILE '.ssh'
if (-not (Test-Path $sshDir)) { New-Item -ItemType Directory -Path $sshDir -Force | Out-Null }
$keyPath = Join-Path $sshDir $IdentityName
$pubPath = "$keyPath.pub"

if (Test-Path $keyPath) {
  Write-Host "[bootstrap] Identidad ya existe: $keyPath (no se sobreescribe)"
} else {
  Write-Host "[bootstrap] Generando identidad ED25519 dedicada: $keyPath"
  $hostTag = "ottoguide-observability-$env:COMPUTERNAME"
  New-OttoGuideEd25519KeyNoPassphrase -KeyPath $keyPath -Comment $hostTag
}

Write-Host "[bootstrap] Fingerprint de la clave publica local (para instalar en el Companion):"
& ssh-keygen -lf $pubPath

$khost = Join-Path $SshRoot 'known_hosts'
if (-not (Test-Path $khost)) {
  New-Item -ItemType File -Path $khost -Force | Out-Null
  Write-Host "[bootstrap] known_hosts dedicado creado (vacio): $khost"
}
# Restringir ACLs: OpenSSH en Windows rechaza un config/known_hosts legible por otros.
$me = "$env:USERDOMAIN\$env:USERNAME"
& icacls $khost /inheritance:r /grant:r "${me}:F" | Out-Null

Write-Host ""
Write-Host "[bootstrap] Listo. known_hosts dedicado creado VACIO -- el pinning real de la"
Write-Host "host key lo hace Write-OttoGuideHostKeyPin.ps1, no este script."
Write-Host ""
Write-Host "[bootstrap] Siguientes pasos (orden obligatorio, ver runbook):"
Write-Host "  1) Resolve-OttoGuideTarget.ps1     (resuelve target + valida fingerprint)"
Write-Host "  2) Write-OttoGuideHostKeyPin.ps1   (pinea la host key en known_hosts dedicado)"
Write-Host "  3) Write-OttoGuideSshConfig.ps1    (genera generated_target.conf)"
Write-Host "  4) A) Companion ya tiene la clave publica -> Test-OttoGuideConnection.ps1"
Write-Host "     B) Companion sin la clave publica aun   -> Install-OttoGuidePublicKey.ps1"
