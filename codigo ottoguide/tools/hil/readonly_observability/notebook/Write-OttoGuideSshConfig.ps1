<#
  WEB-HIL-R1 — Write-OttoGuideSshConfig.ps1 (portable)
  Genera <SshRoot>\generated_target.conf con dos aliases SSH ('ottoguide' manual,
  'ottoguide-batch' automatico) apuntando al target resuelto por
  Resolve-OttoGuideTarget.ps1. Maneja el escaping del scope IPv6 (%ifIndex) probando
  variantes con `ssh -G` hasta que HostName resuelva exactamente al target real.
  No continua si la config generada no queda verificada.

  Portable: usa $env:USERPROFILE, nunca un nombre de notebook fijo. El nombre de la
  identidad es generico: id_ed25519_ottoguide_robot (SIN sufijo por notebook).
#>
param(
  [string]$SshRoot = 'C:\OG\OttoGuide-SSH',
  [string]$IdentityName = 'id_ed25519_ottoguide_robot',
  [string]$RemoteUser = 'unitree'
)
$ErrorActionPreference = 'Stop'
$stateDir = Join-Path $SshRoot 'state'
$targetPath = Join-Path $stateDir 'target.json'
if (-not (Test-Path $targetPath)) { throw "Sin target resuelto (corre Resolve-OttoGuideTarget.ps1 primero)." }
$target = (Get-Content $targetPath -Raw | ConvertFrom-Json).target
if (-not $target) { throw "target.json sin campo 'target' valido." }

$khost = ("$SshRoot\known_hosts" -replace '\\','/')
$identity = "~/.ssh/$IdentityName"
$genConf = Join-Path $SshRoot 'generated_target.conf'

function New-ConfigText([string]$hostNameValue) {
@"
# GENERADO por Write-OttoGuideSshConfig.ps1 -- NO editar a mano, NO versionar.
Host ottoguide
    HostName $hostNameValue
    User $RemoteUser
    IdentityFile $identity
    IdentitiesOnly yes
    PubkeyAuthentication yes
    UserKnownHostsFile $khost
    HostKeyAlias ottoguide-companion
    StrictHostKeyChecking yes
    HostKeyAlgorithms ssh-ed25519
    UpdateHostKeys no
    BatchMode no
    PreferredAuthentications publickey,password
    ConnectTimeout 3
    ConnectionAttempts 1
    ServerAliveInterval 5
    ServerAliveCountMax 2

Host ottoguide-batch
    HostName $hostNameValue
    User $RemoteUser
    IdentityFile $identity
    IdentitiesOnly yes
    PubkeyAuthentication yes
    UserKnownHostsFile $khost
    HostKeyAlias ottoguide-companion
    StrictHostKeyChecking yes
    HostKeyAlgorithms ssh-ed25519
    UpdateHostKeys no
    BatchMode yes
    PasswordAuthentication no
    KbdInteractiveAuthentication no
    PreferredAuthentications publickey
    RequestTTY no
    ConnectTimeout 3
    ConnectionAttempts 1
    ServerAliveInterval 5
    ServerAliveCountMax 2
"@
}

# El scope IPv6 lleva '%'. En ssh_config, '%' es token de expansion -> se escapa
# como '%%'. Probar la variante escapada primero, luego la literal; conservar la
# que 'ssh -G' resuelva exactamente al target (no asumir la sintaxis de antemano).
$scopeEscaped = $target -replace '%','%%'
$variants = @($scopeEscaped, $target)
$ok = $false
foreach ($v in $variants) {
  New-ConfigText $v | Out-File -Encoding ascii $genConf
  $g = & cmd /c "ssh -F `"$genConf`" -G ottoguide-batch 2>nul"
  $hn = ($g | Select-String -Pattern '^hostname\s+(.+)$').Matches.Groups[1].Value.Trim()
  if ($hn -eq $target) { $ok = $true; break }
}
if (-not $ok) { throw "No se pudo generar una config cuyo 'ssh -G' resuelva HostName=$target." }

# Bloquear ACLs del archivo generado: OpenSSH en Windows rechaza un config incluido
# si es legible por otros usuarios/grupos ('Bad owner or permissions').
$me = "$env:USERDOMAIN\$env:USERNAME"
& icacls $genConf /inheritance:r /grant:r "${me}:F" | Out-Null

$gm = & cmd /c "ssh -F `"$genConf`" -G ottoguide 2>nul"
$hm = ($gm | Select-String -Pattern '^hostname\s+(.+)$').Matches.Groups[1].Value.Trim()
if ($hm -ne $target) { throw "Alias 'ottoguide' resolvio HostName=$hm != $target." }

Write-Host "[config] generated_target.conf verificado. ottoguide y ottoguide-batch -> $target"
$genConf
