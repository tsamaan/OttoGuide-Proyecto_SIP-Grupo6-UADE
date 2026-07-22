<#
  WEB-HIL-R1B — Write-OttoGuideHostKeyPin.ps1
  Pinning durable de la host key del Companion, INDEPENDIENTE de que direccion
  (IPv4 o IPv6 link-local con scope variable) se haya resuelto en esta sesion.

  Lee state\target.json (escrito por Resolve-OttoGuideTarget.ps1, que ya valido el
  fingerprint contra config/companion.profile.json) y escribe una entrada
  AUTORITATIVA en <SshRoot>\known_hosts bajo el alias fijo 'ottoguide-companion'
  (nunca la IP), de forma atomica (archivo temporal + rename) y con ACL restringida
  al usuario actual.

  Reglas:
    - NUNCA usa la IPv4/IPv6 como autoridad criptografica (siempre 'ottoguide-companion').
    - NUNCA toca %USERPROFILE%\.ssh\known_hosts (known_hosts global del usuario).
    - NUNCA acepta un fingerprint distinto al ya validado por el resolver.
    - NUNCA usa StrictHostKeyChecking=accept-new.
    - Si ya existe una entrada para 'ottoguide-companion', la conserva SOLO si su
      fingerprint coincide con el actual; si difiere, aborta (no la sobreescribe
      silenciosamente) y exige -Force explicito para rotarla.
    - IDEMPOTENTE PERO NO PEREZOSO (WEB-HIL-R1B, FASE G): aunque la clave ya coincida,
      SIEMPRE recalcula el fingerprint desde key_base64 (nunca confia ciegamente en
      target.fingerprint), SIEMPRE reaplica la ACL, y SIEMPRE regenera
      host_key_proof.json con un timestamp fresco -- nunca un 'exit 0' temprano que
      salte esas verificaciones. La UNICA operacion que se evita cuando ya coincide es
      la reescritura de la linea en known_hosts (para no perturbar el archivo sin
      necesidad), no el resto de las verificaciones.
#>
param(
  [string]$SshRoot = 'C:\OG\OttoGuide-SSH',
  [switch]$Force
)
$ErrorActionPreference = 'Stop'

$stateDir = Join-Path $SshRoot 'state'
$targetPath = Join-Path $stateDir 'target.json'
if (-not (Test-Path $targetPath)) { throw "Sin target resuelto (corre Resolve-OttoGuideTarget.ps1 primero)." }
$target = Get-Content $targetPath -Raw | ConvertFrom-Json
if (-not $target.key_base64 -or -not $target.fingerprint) {
  throw "target.json no contiene key_base64/fingerprint (regenera con la version actual de Resolve-OttoGuideTarget.ps1)."
}
if ($target.key_type -ne 'ssh-ed25519') {
  throw "target.json tiene key_type='$($target.key_type)', se esperaba 'ssh-ed25519'. Aborta (fail-closed)."
}

# Recalcula el fingerprint SHA256 desde key_base64 en vez de confiar ciegamente en
# target.fingerprint: si ambos difieren, target.json fue corrompido/editado entre
# la resolucion y el pin, y NO se debe continuar.
function Get-Sha256FingerprintFromBase64([string]$keyBase64) {
  $raw = [Convert]::FromBase64String($keyBase64)
  $sha = [System.Security.Cryptography.SHA256]::Create()
  try {
    $hash = $sha.ComputeHash($raw)
    $b64 = [Convert]::ToBase64String($hash).TrimEnd('=')
    return "SHA256:$b64"
  } finally { $sha.Dispose() }
}
$recalculatedFingerprint = Get-Sha256FingerprintFromBase64 $target.key_base64
if ($recalculatedFingerprint -ne $target.fingerprint) {
  throw "El fingerprint recalculado desde key_base64 ($recalculatedFingerprint) no coincide con target.fingerprint ($($target.fingerprint)). target.json inconsistente; aborta (fail-closed)."
}

$alias = 'ottoguide-companion'
$khost = Join-Path $SshRoot 'known_hosts'
if (-not (Test-Path $khost)) { New-Item -ItemType File -Path $khost -Force | Out-Null }

$aliasPattern = '^' + [regex]::Escape($alias) + '\s'
$existingLine = Get-Content $khost -ErrorAction SilentlyContinue | Where-Object { $_ -match $aliasPattern } | Select-Object -First 1
$needsWrite = $true
if ($existingLine) {
  $existingParts = $existingLine -split '\s+'
  $existingKeyB64 = $existingParts[2]
  if ($existingKeyB64 -eq $target.key_base64) {
    Write-Host "[host-key-pin] Entrada existente para '$alias' ya coincide (fingerprint=$recalculatedFingerprint). No se reescribe la linea, pero se reaplican ACL/proof igual."
    $needsWrite = $false
  } elseif (-not $Force) {
    throw "Entrada existente para '$alias' tiene una clave DISTINTA a la resuelta ahora (fingerprint actual=$recalculatedFingerprint). Aborta por seguridad. Pasa -Force solo si confirmaste manualmente la rotacion de la host key del Companion."
  } else {
    Write-Warning "[host-key-pin] -Force: rotando la entrada existente de '$alias'."
  }
}

if ($needsWrite) {
  $newLine = "$alias $($target.key_type) $($target.key_base64)"
  $otherLines = @(Get-Content $khost -ErrorAction SilentlyContinue | Where-Object { $_ -notmatch $aliasPattern -and $_.Trim() -ne '' })
  $finalLines = $otherLines + $newLine

  $tmpPath = "$khost.tmp"
  $finalLines | Out-File -Encoding ascii $tmpPath
  Move-Item -Force $tmpPath $khost
}

# La linea SIEMPRE debe quedar unica (nunca duplicada), exista o no una previa igual.
$verifyLines = @(Get-Content $khost -ErrorAction SilentlyContinue | Where-Object { $_ -match $aliasPattern })
if ($verifyLines.Count -ne 1) {
  throw "Post-condicion violada: known_hosts tiene $($verifyLines.Count) entradas para '$alias' (se esperaba exactamente 1)."
}

# ACL: SIEMPRE se reaplica, no solo cuando se reescribe el archivo.
$me = "$env:USERDOMAIN\$env:USERNAME"
& icacls $khost /inheritance:r /grant:r "${me}:F" | Out-Null
if ($LASTEXITCODE -ne 0) {
  throw "icacls fallo (rc=$LASTEXITCODE) al aplicar la ACL restringida sobre $khost. Aborta (fail-closed): un known_hosts con permisos incorrectos puede ser rechazado por OpenSSH o, peor, ser legible/escribible por otros usuarios."
}

# host_key_proof.json: SIEMPRE se regenera con timestamp fresco, nunca se omite por
# haber tomado la rama 'ya coincide'.
$proof = [ordered]@{
  fingerprint = $recalculatedFingerprint
  key_type    = $target.key_type
  target      = $alias
  interface   = $target.interface
  ifindex     = $target.ifindex
  utc         = (Get-Date).ToUniversalTime().ToString('yyyy-MM-ddTHH:mm:ssZ')
  match       = $true
  entry_rewritten = $needsWrite
}
$proof | ConvertTo-Json | Out-File -Encoding ascii (Join-Path $stateDir 'host_key_proof.json')

Write-Host "[host-key-pin] known_hosts dedicado verificado: $khost (alias=$alias, fingerprint=$recalculatedFingerprint, rewritten=$needsWrite)"
