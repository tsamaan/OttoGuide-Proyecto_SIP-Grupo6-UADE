<#
  WEB-HIL-R1B — Resolve-OttoGuideTarget.ps1 (portable, durable host-key pinning)
  Resuelve el target actual del Companion OttoGuide sin depender de una IPv6 concreta,
  el scope %ifIndex, el ifIndex, el nombre del adaptador NI cual adaptador Ethernet
  resulta "el primero" que devuelva Windows. ESTRICTAMENTE READ-ONLY de red: NO
  modifica IPv4, Wi-Fi, rutas ni adaptadores.

  Recorre TODOS los adaptadores Up/802.3 (no solo el primero) y, dentro de cada uno,
  TODOS sus vecinos IPv6 link-local candidatos, recolectando la lista COMPLETA de
  candidatos (no corta al primer match). La decision de CUAL candidato es valido queda
  delegada enteramente a Select-OttoGuideVerifiedCandidate (OttoGuideSshBootstrapHelpers.ps1)
  -- el mismo helper que ejercita Test-SshBootstrapLogic.ps1 -- para que produccion y test
  compartan un unico punto de verdad, nunca un selector paralelo. Nunca elige el primer
  adaptador ni el primer vecino ni el primer host con puerto 22 abierto por default:
  siempre valida fingerprint.

  Devuelve (y persiste) no solo el fingerprint sino la clave publica completa
  (key_type + key_base64), porque Write-OttoGuideHostKeyPin.ps1 la necesita para
  escribir la entrada autoritativa en el known_hosts dedicado.

  Portable: usa $env:USERPROFILE nunca un nombre de usuario fijo; el SSH_ROOT y el
  fingerprint son parametros (con defaults documentados en config/).

  WEB-HIL-R2E: agrega -PreferredInterfaceAlias / -PreferredIfIndex (sin defaults --
  nunca hardcodeados aqui; se pasan como argumento en cada sesion) para eliminar la
  ambiguedad quirofano-detectada entre un adaptador fisico real y un adaptador
  virtual (p.ej. Hyper-V/WSL) que puentea el mismo segmento y por lo tanto tambien
  supera la validacion de fingerprint sin enrutar trafico real. Con preferencia
  dada, SOLO se considera un candidato que coincida con esa interfaz/ifIndex; sin
  preferencia y con mas de un candidato valido, FAIL_CLOSED_AMBIGUOUS_TARGET (nunca
  se elige el primero de una lista ambigua). Tambien agrega -ReUseVerifiedTarget
  para no volver a escanear adaptadores si el target ya persistido en target.json
  sigue siendo functional (ver Test-OttoGuideConnection-equivalente inline abajo).
#>
param(
  [string]$SshRoot = 'C:\OG\OttoGuide-SSH',
  [string]$ExpectedFingerprint,
  [string]$CompanionIPv4 = '192.168.123.164',
  [string]$PreferredInterfaceAlias,
  [System.Nullable[int]]$PreferredIfIndex,
  [switch]$ReUseVerifiedTarget
)
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'OttoGuideSshBootstrapHelpers.ps1')

if (-not $ExpectedFingerprint) {
  $profilePath = Join-Path $PSScriptRoot '..\config\companion.profile.json'
  if (Test-Path $profilePath) {
    $ExpectedFingerprint = (Get-Content $profilePath -Raw | ConvertFrom-Json).ed25519_fingerprint
  }
}
if (-not $ExpectedFingerprint) { throw "Sin ExpectedFingerprint (ni parametro ni config/companion.profile.json)." }

$stateDir = Join-Path $SshRoot 'state'
if (-not (Test-Path $stateDir)) { New-Item -ItemType Directory -Path $stateDir -Force | Out-Null }
$utc = (Get-Date).ToUniversalTime().ToString('yyyy-MM-ddTHH:mm:ssZ')

# ---- WEB-HIL-R2E: reutilizacion de un target ya verificado (regla 6/7) ----
# Nunca sobrescribe silenciosamente: solo reutiliza si TODAS las condiciones
# pasan; si cualquiera falla, cae al escaneo normal de adaptadores (abajo) en
# vez de fallar duro, para que -ReUseVerifiedTarget sea un atajo, no un nuevo
# modo fragil.
if ($ReUseVerifiedTarget) {
  $existingTargetPath = Join-Path $stateDir 'target.json'
  $genConfPath = Join-Path $SshRoot 'generated_target.conf'
  $khPath = Join-Path $SshRoot 'known_hosts'
  $reuseOk = $false
  try {
    if ((Test-Path $existingTargetPath) -and (Test-Path $genConfPath) -and (Test-Path $khPath)) {
      $existing = Get-Content $existingTargetPath -Raw | ConvertFrom-Json
      $fingerprintOk = $existing.fingerprint -and ($existing.fingerprint -eq $ExpectedFingerprint)
      $keyBase64Ok = $false
      if ($fingerprintOk -and $existing.key_base64) {
        $khLine = Get-Content $khPath | Where-Object { $_ -match '^ottoguide-companion\s+ssh-ed25519\s+(\S+)' } | Select-Object -First 1
        if ($khLine -and ($Matches[1] -eq $existing.key_base64)) { $keyBase64Ok = $true }
      }
      if ($fingerprintOk -and $keyBase64Ok) {
        $probeOut = & cmd /c "ssh -F `"$genConfPath`" ottoguide-batch `"echo AUTH_OK; hostname; whoami`" 2>nul"
        $probeText = ($probeOut -join "`n")
        $authOk = $probeText -match 'AUTH_OK'
        $hostOk = $probeText -match '(?m)^ubuntu$'
        $userOk = $probeText -match '(?m)^unitree$'
        if ($authOk -and $hostOk -and $userOk) { $reuseOk = $true }
      }
    }
  } catch { $reuseOk = $false }

  if ($reuseOk) {
    $existing.utc = $utc
    $existing | ConvertTo-Json | Out-File -Encoding ascii $existingTargetPath
    Write-Host "[resolve] REUSE_VERIFIED_TARGET=true target=$($existing.target) iface=$($existing.interface) ifIndex=$($existing.ifindex) fingerprint=OK"
    $existing.target
    exit 0
  }
  Write-Host "[resolve] REUSE_VERIFIED_TARGET=false (no reutilizable o inexistente) -> escaneo normal de adaptadores."
}

function Get-Ed25519HostKey([string]$hostArg) {
  # Se ejecuta via cmd /c: en PowerShell 5.1, una native command con stderr (banner
  # informativo normal de ssh-keyscan) bajo ErrorActionPreference=Stop puede abortar
  # el script. Aislar via cmd /c evita ese problema sin cambiar el comportamiento real.
  # Devuelve [pscustomobject]@{ key_type; key_base64; fingerprint } o $null.
  $tmp = Join-Path $env:TEMP ("ogks_" + [guid]::NewGuid().ToString('N') + '.txt')
  try {
    & cmd /c "ssh-keyscan -T 4 -t ed25519 `"$hostArg`" > `"$tmp`" 2>nul" | Out-Null
    if (-not (Test-Path $tmp) -or (Get-Item $tmp).Length -eq 0) { return $null }
    $rawLine = (Get-Content $tmp | Where-Object { $_ -match '\Sssh-ed25519\S*\s+ssh-ed25519\s+\S+' -or $_ -match '^\S+\s+ssh-ed25519\s+\S+' } | Select-Object -First 1)
    $fpLine = & cmd /c "ssh-keygen -lf `"$tmp`" -E sha256 2>nul"
    if (-not $rawLine -or -not ($fpLine -match '(SHA256:[A-Za-z0-9+/]+)')) { return $null }
    $parts = $rawLine -split '\s+'
    # formato scan: "<host> ssh-ed25519 <base64>"
    $idx = [array]::IndexOf($parts, 'ssh-ed25519')
    if ($idx -lt 0 -or ($idx + 1) -ge $parts.Length) { return $null }
    [pscustomobject]@{
      key_type    = 'ssh-ed25519'
      key_base64  = $parts[$idx + 1]
      fingerprint = $Matches[1]
    }
  } finally {
    Remove-Item $tmp -Force -ErrorAction SilentlyContinue
  }
}

$candidates = @()
$candidateKeys = @{}  # target -> keyInfo completo (key_type/key_base64/fingerprint), por candidato
$ethAdapters = @()

# 1. IPv4 primero (TCP 22).
$ipv4ok = $false
try { $ipv4ok = (Test-NetConnection -ComputerName $CompanionIPv4 -Port 22 -WarningAction SilentlyContinue).TcpTestSucceeded } catch {}
if ($ipv4ok) {
  $keyInfo = Get-Ed25519HostKey $CompanionIPv4
  $candidates += [pscustomobject]@{ target = $CompanionIPv4; interface = 'IPv4'; ifindex = $null; fingerprint = $keyInfo.fingerprint }
  $candidateKeys[$CompanionIPv4] = @{ interface = 'IPv4'; ifindex = $null; keyInfo = $keyInfo }
}

# 2. Fallback IPv6 link-local: recorrer TODOS los adaptadores Up/802.3 (no solo el
#    primero que devuelva Get-NetAdapter), y dentro de cada uno TODOS sus vecinos
#    IPv6 link-local candidatos. Se recolectan TODOS los candidatos (no se corta al
#    primer match) para que Select-OttoGuideVerifiedCandidate sea el UNICO punto que
#    decide, sobre la lista completa, igual que en el test offline.
if (-not $ipv4ok -or -not ($candidates | Where-Object { $_.fingerprint -eq $ExpectedFingerprint })) {
  $ethAdapters = @(Get-NetAdapter | Where-Object { $_.Status -eq 'Up' -and $_.MediaType -eq '802.3' })
  foreach ($eth in $ethAdapters) {
    $ifIndex = $eth.ifIndex
    try { & ping -6 -n 2 "ff02::1%$ifIndex" | Out-Null } catch {}  # provoca deteccion de vecinos (read-only)
    $neighbors = Get-NetNeighbor -InterfaceIndex $ifIndex -AddressFamily IPv6 -ErrorAction SilentlyContinue |
      Where-Object { $_.IPAddress -like 'fe80::*' -and $_.State -ne 'Permanent' -and $_.LinkLayerAddress }
    foreach ($n in $neighbors) {
      $hostArg = "$($n.IPAddress)%$ifIndex"
      $keyInfo = Get-Ed25519HostKey $hostArg
      $candidates += [pscustomobject]@{ target = $hostArg; interface = $eth.Name; ifindex = $ifIndex; fingerprint = $keyInfo.fingerprint }
      $candidateKeys[$hostArg] = @{ interface = $eth.Name; ifindex = $ifIndex; keyInfo = $keyInfo }
    }
  }
}

$selection = Select-OttoGuideVerifiedCandidate -Candidates $candidates -ExpectedFingerprint $ExpectedFingerprint `
  -PreferredInterfaceAlias $PreferredInterfaceAlias -PreferredIfIndex $PreferredIfIndex
$chosen = $null; $chosenIface = $null; $chosenIfIndex = $null; $chosenKey = $null
if ($selection.Status -eq 'MATCHED') {
  $selected = $selection.Candidate
  $meta = $candidateKeys[$selected.target]
  $chosen = $selected.target; $chosenIface = $meta.interface; $chosenIfIndex = $meta.ifindex; $chosenKey = $meta.keyInfo
}
$candidates = @($candidates | ForEach-Object { [pscustomobject]@{ target = $_.target; interface = $_.interface; ifindex = $_.ifindex; fingerprint = $_.fingerprint; match = ($_.fingerprint -eq $ExpectedFingerprint -and -not [string]::IsNullOrEmpty($_.fingerprint)) } })

$resolution = [ordered]@{
  utc = $utc; chosen_target = $chosen; interface = $chosenIface; ifindex = $chosenIfIndex
  expected_fingerprint = $ExpectedFingerprint; ipv4_tcp22 = $ipv4ok
  preferred_interface_alias = $PreferredInterfaceAlias; preferred_ifindex = $PreferredIfIndex
  selection_status = $selection.Status
  adapters_scanned = @($ethAdapters | ForEach-Object { $_.Name })
  candidates = $candidates
}
$resolution | ConvertTo-Json -Depth 6 | Out-File -Encoding ascii (Join-Path $stateDir 'last_resolution.json')

if (-not $chosen) {
  switch ($selection.Status) {
    'AMBIGUOUS' {
      $ambiguousSummary = ($selection.Matches | ForEach-Object { "$($_.interface)(ifIndex=$($_.ifindex))=$($_.target)" }) -join '; '
      Write-Error "FAIL_CLOSED_AMBIGUOUS_TARGET: $($selection.Matches.Count) candidatos distintos coinciden con el fingerprint $ExpectedFingerprint sin -PreferredInterfaceAlias/-PreferredIfIndex para desambiguar. Candidatos: $ambiguousSummary"
      exit 3
    }
    'PREFERENCE_NOT_FOUND' {
      Write-Error "FAIL_CLOSED: la preferencia (PreferredInterfaceAlias='$PreferredInterfaceAlias' PreferredIfIndex=$PreferredIfIndex) no coincide con ningun candidato observado (adaptadores recorridos: $($ethAdapters.Count))."
      exit 4
    }
    'PREFERENCE_FINGERPRINT_MISMATCH' {
      Write-Error "FAIL_CLOSED: la interfaz/ifIndex preferida existe pero no expone el fingerprint esperado $ExpectedFingerprint."
      exit 5
    }
    default {
      Write-Error "No se resolvio ningun target cuyo fingerprint ED25519 coincida con $ExpectedFingerprint (adaptadores recorridos: $($ethAdapters.Count), candidatos IPv6: $($candidates.Count))."
      exit 2
    }
  }
}

$targetObj = [ordered]@{
  target = $chosen; interface = $chosenIface; ifindex = $chosenIfIndex; utc = $utc
  key_type = $chosenKey.key_type; key_base64 = $chosenKey.key_base64; fingerprint = $chosenKey.fingerprint
}
$targetPath = Join-Path $stateDir 'target.json'
$tmpPath = "$targetPath.tmp"
$targetObj | ConvertTo-Json | Out-File -Encoding ascii $tmpPath
Move-Item -Force $tmpPath $targetPath

Write-Host "[resolve] target=$chosen iface=$chosenIface ifIndex=$chosenIfIndex fingerprint=OK"
$chosen
