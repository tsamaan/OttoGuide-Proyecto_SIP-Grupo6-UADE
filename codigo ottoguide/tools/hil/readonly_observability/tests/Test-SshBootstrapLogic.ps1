<#
  WEB-HIL-R1B — Test-SshBootstrapLogic.ps1
  Prueba OFFLINE (sin SSH real, sin robot, sin red real) de la logica de pinning de
  host key y de las reglas de instalacion de clave publica. No requiere Get-NetAdapter
  real: simula multiples adaptadores/vecinos como datos, ejerciendo el helper REAL de
  produccion Select-OttoGuideVerifiedCandidate (OttoGuideSshBootstrapHelpers.ps1) --
  el mismo que usa Resolve-OttoGuideTarget.ps1 -- nunca un selector paralelo
  reimplementado en el test, y ejerce Write-OttoGuideHostKeyPin.ps1 real contra un
  SshRoot de sandbox.

  Cubre (ver checkpoint FASE G / FASE F de WEB-HIL-R1B):
   1. recorrido de mas de un adaptador simulado
   2. seleccion unicamente por fingerprint
   3. rechazo de fingerprint distinto
   4. generacion de entrada "ottoguide-companion ssh-ed25519 <KEY>"
   5. no modificacion de un known_hosts global simulado
   6. escritura atomica (temp + rename, sin dejar .tmp huerfano)
   7. rechazo de una entrada alias existente con clave diferente (sin -Force)
   8. comando de instalacion sin precedencia ambigua ('&&'/'||')
   9. ausencia de 'ssh unitree@<Target>' literal en el script de instalacion
  10. uso de '-F ... generated_target.conf' en el script de instalacion
  11. generacion temporal de clave ED25519 realmente sin passphrase
  12. manifiesto remoto con diez hashes
  13. (R2E) duplicacion de fingerprint SIN preferencia -> FAIL_CLOSED_AMBIGUOUS (Status=AMBIGUOUS),
      NUNCA se elige el primero de una lista ambigua
  13b.(R2E) la misma ambiguedad CON -PreferredInterfaceAlias -> desambigua deterministicamente
  13c.(R2E) -PreferredInterfaceAlias ausente entre candidatos -> PREFERENCE_NOT_FOUND
  13d.(R2E) preferencia valida sin el fingerprint esperado -> PREFERENCE_FINGERPRINT_MISMATCH
  13e.(R2E) -PreferredIfIndex desambigua igual que -PreferredInterfaceAlias
  14. (R1B) candidato sin clave (fingerprint $null) -> nunca matchea
  15. (R1B) candidato con fingerprint vacio ('') -> nunca matchea

  Uso: powershell -ExecutionPolicy Bypass -File Test-SshBootstrapLogic.ps1
  Exit code 0 = PASS, !=0 = FAIL.
#>
$ErrorActionPreference = 'Stop'
$repoRoot = Resolve-Path (Join-Path $PSScriptRoot '..')
$notebookDir = Join-Path $repoRoot 'notebook'
$companionDir = Join-Path $repoRoot 'companion'
$fail = @()

. (Join-Path $notebookDir 'OttoGuideSshBootstrapHelpers.ps1')

# ============================================================================
# 1-3, 13-15. Seleccion multi-adaptador SOLO por fingerprint, usando el helper
# REAL de produccion (Select-OttoGuideVerifiedCandidate), no una reimplementacion.
# ============================================================================
$expectedFp = 'SHA256:b49bi+OYx/3BYWPsTlMZF1psSs5FW8FnpmFfHpfoDrk'
# NOTA (WEB-HIL-R2E): los candidatos ahora usan 'interface'/'ifindex' (no 'adapter'),
# para que coincidan con las propiedades reales que produce Resolve-OttoGuideTarget.ps1
# y que Select-OttoGuideVerifiedCandidate usa para filtrar por preferencia.
$simulatedCandidates = @(
  [pscustomobject]@{ interface = 'Ethernet';  ifindex = 5; target = 'fe80::1%5';  fingerprint = 'SHA256:WRONG_FIRST_ADAPTER_NEIGHBOR_1' }
  [pscustomobject]@{ interface = 'Ethernet';  ifindex = 5; target = 'fe80::2%5';  fingerprint = 'SHA256:WRONG_FIRST_ADAPTER_NEIGHBOR_2' }
  [pscustomobject]@{ interface = 'Ethernet 2'; ifindex = 7; target = 'fe80::3%7'; fingerprint = $expectedFp }
  [pscustomobject]@{ interface = 'Ethernet 2'; ifindex = 7; target = 'fe80::4%7'; fingerprint = 'SHA256:WRONG_SECOND_ADAPTER_NEIGHBOR' }
)
$adaptersInvolved = ($simulatedCandidates | Select-Object -ExpandProperty interface -Unique)
if ($adaptersInvolved.Count -lt 2) { $fail += "fixture de candidatos no cubre mas de un adaptador (test invalido)" }

$selection = Select-OttoGuideVerifiedCandidate -Candidates $simulatedCandidates -ExpectedFingerprint $expectedFp
if ($selection.Status -ne 'MATCHED') { $fail += "seleccion por fingerprint no encontro el candidato correcto (item 1/2, status=$($selection.Status))" }
elseif ($selection.Candidate.target -ne 'fe80::3%7') { $fail += "seleccion por fingerprint eligio '$($selection.Candidate.target)' en vez de 'fe80::3%7' (no selecciono por fingerprint, item 2)" }
elseif ($selection.Candidate.interface -ne 'Ethernet 2') { $fail += "el candidato correcto estaba en el SEGUNDO adaptador y no fue alcanzado (item 1: no recorre mas de un adaptador)" }

$wrongFp = 'SHA256:THIS_DOES_NOT_MATCH_ANYTHING'
$rejectedSel = Select-OttoGuideVerifiedCandidate -Candidates $simulatedCandidates -ExpectedFingerprint $wrongFp
if ($rejectedSel.Status -eq 'MATCHED') { $fail += "seleccion acepto un fingerprint que no deberia matchear ningun candidato (item 3)" }

# (13, WEB-HIL-R2E) Duplicacion de fingerprint entre dos candidatos SIN preferencia:
# debe ser FAIL_CLOSED_AMBIGUOUS (Status=AMBIGUOUS, Candidate=$null), NUNCA elegir el
# primero de una lista ambigua -- este es exactamente el defecto real que produjo un
# target no enrutable (adaptador Hyper-V/WSL puenteado) en produccion.
$dupCandidates = @(
  [pscustomobject]@{ interface = 'A'; ifindex = 1; target = 'first-dup';  fingerprint = $expectedFp }
  [pscustomobject]@{ interface = 'B'; ifindex = 2; target = 'second-dup'; fingerprint = $expectedFp }
)
$dupSelection = Select-OttoGuideVerifiedCandidate -Candidates $dupCandidates -ExpectedFingerprint $expectedFp
if ($dupSelection.Status -ne 'AMBIGUOUS' -or $dupSelection.Candidate) {
  $fail += "con fingerprints duplicados y SIN preferencia, no se fallo cerrado como AMBIGUOUS (item 13, status=$($dupSelection.Status))"
}
if (@($dupSelection.Matches).Count -ne 2) { $fail += "AMBIGUOUS deberia reportar los 2 candidatos en Matches (item 13)" }

# (13b, WEB-HIL-R2E) La MISMA ambiguedad, pero CON -PreferredInterfaceAlias: debe
# desambiguar deterministicamente al candidato de esa interfaz, nunca FAIL_CLOSED.
$dupWithPref = Select-OttoGuideVerifiedCandidate -Candidates $dupCandidates -ExpectedFingerprint $expectedFp -PreferredInterfaceAlias 'B'
if ($dupWithPref.Status -ne 'MATCHED' -or $dupWithPref.Candidate.target -ne 'second-dup') {
  $fail += "con -PreferredInterfaceAlias 'B', deberia elegir 'second-dup' deterministicamente (item 13b, status=$($dupWithPref.Status) target=$($dupWithPref.Candidate.target))"
}

# (13c) -PreferredInterfaceAlias que no existe entre los candidatos -> PREFERENCE_NOT_FOUND.
$prefMissing = Select-OttoGuideVerifiedCandidate -Candidates $dupCandidates -ExpectedFingerprint $expectedFp -PreferredInterfaceAlias 'NoExiste'
if ($prefMissing.Status -ne 'PREFERENCE_NOT_FOUND') {
  $fail += "una preferencia de interfaz ausente entre los candidatos deberia dar PREFERENCE_NOT_FOUND (item 13c, status=$($prefMissing.Status))"
}

# (13d) -PreferredInterfaceAlias que existe pero con fingerprint incorrecto -> PREFERENCE_FINGERPRINT_MISMATCH.
$prefWrongFp = Select-OttoGuideVerifiedCandidate -Candidates $simulatedCandidates -ExpectedFingerprint $wrongFp -PreferredInterfaceAlias 'Ethernet 2'
if ($prefWrongFp.Status -ne 'PREFERENCE_FINGERPRINT_MISMATCH') {
  $fail += "una preferencia valida sin fingerprint correcto deberia dar PREFERENCE_FINGERPRINT_MISMATCH (item 13d, status=$($prefWrongFp.Status))"
}

# (13e) -PreferredIfIndex funciona igual que -PreferredInterfaceAlias.
$dupWithIfIndex = Select-OttoGuideVerifiedCandidate -Candidates $dupCandidates -ExpectedFingerprint $expectedFp -PreferredIfIndex 1
if ($dupWithIfIndex.Status -ne 'MATCHED' -or $dupWithIfIndex.Candidate.target -ne 'first-dup') {
  $fail += "con -PreferredIfIndex 1, deberia elegir 'first-dup' deterministicamente (item 13e, status=$($dupWithIfIndex.Status))"
}

# (14) Candidato sin clave (fingerprint $null, p.ej. ssh-keyscan no respondio): nunca matchea.
$noKeyCandidates = @(
  [pscustomobject]@{ interface = 'A'; ifindex = 1; target = 'no-key-host'; fingerprint = $null }
  [pscustomobject]@{ interface = 'A'; ifindex = 1; target = 'good-host';   fingerprint = $expectedFp }
)
$noKeySelection = Select-OttoGuideVerifiedCandidate -Candidates $noKeyCandidates -ExpectedFingerprint $expectedFp
if ($noKeySelection.Status -ne 'MATCHED' -or $noKeySelection.Candidate.target -ne 'good-host') {
  $fail += "un candidato sin clave (fingerprint `$null) interfirio con la seleccion del candidato valido (item 14)"
}
# Verifica ademas que un candidato SOLO sin clave (sin ningun match posible) no rompe nada.
$onlyNoKey = @([pscustomobject]@{ interface = 'A'; ifindex = 1; target = 'no-key-host'; fingerprint = $null })
if ((Select-OttoGuideVerifiedCandidate -Candidates $onlyNoKey -ExpectedFingerprint $expectedFp).Status -eq 'MATCHED') {
  $fail += "un candidato con fingerprint `$null fue seleccionado como match (item 14)"
}

# (15) Candidato con fingerprint vacio (''): tampoco debe matchear NUNCA, incluso si
# ExpectedFingerprint tambien estuviera vacio (fail-closed, no "vacio == vacio").
$emptyFpCandidates = @([pscustomobject]@{ interface = 'A'; ifindex = 1; target = 'empty-fp-host'; fingerprint = '' })
if ((Select-OttoGuideVerifiedCandidate -Candidates $emptyFpCandidates -ExpectedFingerprint '').Status -eq 'MATCHED') {
  $fail += "un candidato con fingerprint vacio matcheo contra un ExpectedFingerprint vacio (item 15, debe ser fail-closed)"
}
if ((Select-OttoGuideVerifiedCandidate -Candidates $emptyFpCandidates -ExpectedFingerprint $expectedFp).Status -eq 'MATCHED') {
  $fail += "un candidato con fingerprint vacio matcheo contra el fingerprint esperado real (item 15)"
}

# Verificacion estructural: el script real NO debe elegir 'el primer adaptador'
# (Select-Object -First 1 sobre adaptadores) ni 'el primer vecino' sin chequear
# fingerprint, Y debe usar el helper compartido (no un selector paralelo).
$resolveSrc = Get-Content (Join-Path $notebookDir 'Resolve-OttoGuideTarget.ps1') -Raw
if ($resolveSrc -notmatch 'Select-OttoGuideVerifiedCandidate') {
  $fail += "Resolve-OttoGuideTarget.ps1 no usa el helper compartido Select-OttoGuideVerifiedCandidate (FASE F: no debe reimplementar un selector paralelo)"
}
if ($resolveSrc -match 'Get-NetAdapter[^\n]*\|\s*Where-Object[^\n]*\|\s*Select-Object\s+-First\s+1') {
  $fail += "Resolve-OttoGuideTarget.ps1 todavia usa 'Select-Object -First 1' sobre adaptadores (item 1)"
}
if ($resolveSrc -notmatch 'foreach\s*\(\s*\$eth\s+in\s+\$ethAdapters\s*\)') {
  $fail += "Resolve-OttoGuideTarget.ps1 no recorre explicitamente todos los adaptadores en un foreach (item 1)"
}
if ($resolveSrc -notmatch 'key_base64') {
  $fail += "Resolve-OttoGuideTarget.ps1 no persiste key_base64 (clave publica completa, no solo el fingerprint)"
}

# ============================================================================
# 4-7. Write-OttoGuideHostKeyPin.ps1 REAL contra un SshRoot de sandbox
# ============================================================================
$sandbox = Join-Path $env:TEMP ("og_sshboot_test_" + [guid]::NewGuid().ToString('N'))
$sshRoot = Join-Path $sandbox 'sshroot'
$stateDir = Join-Path $sshRoot 'state'
New-Item -ItemType Directory -Path $stateDir -Force | Out-Null

$pinScript = Join-Path $notebookDir 'Write-OttoGuideHostKeyPin.ps1'

# Write-OttoGuideHostKeyPin.ps1 (FASE G, WEB-HIL-R1B) ahora RECALCULA el fingerprint
# SHA256 real desde key_base64 (nunca confia ciegamente en el campo 'fingerprint' de
# target.json); las fixtures deben ser Base64 valido con un fingerprint que
# efectivamente le corresponda, calculado con el MISMO algoritmo que el script real.
function Get-TestSha256Fingerprint([byte[]]$bytes) {
  $sha256 = [System.Security.Cryptography.SHA256]::Create()
  try { return "SHA256:" + ([Convert]::ToBase64String($sha256.ComputeHash($bytes)).TrimEnd('=')) }
  finally { $sha256.Dispose() }
}
$fakeKeyBytes = [System.Text.Encoding]::UTF8.GetBytes('FAKEKEYFORTESTONLYNOTAREALHOSTKEYVALUE1234567890')
$fakeKeyB64 = [Convert]::ToBase64String($fakeKeyBytes)
$fakeKeyFingerprint = Get-TestSha256Fingerprint $fakeKeyBytes

$targetObj = [ordered]@{
  target = 'fe80::3%7'; interface = 'Ethernet 2'; ifindex = 7
  utc = (Get-Date).ToUniversalTime().ToString('o')
  key_type = 'ssh-ed25519'; key_base64 = $fakeKeyB64; fingerprint = $fakeKeyFingerprint
}
$targetObj | ConvertTo-Json | Out-File -Encoding ascii (Join-Path $stateDir 'target.json')

# --- (5) known_hosts GLOBAL simulado: debe quedar intacto ---
$fakeGlobalKnownHosts = Join-Path $sandbox 'fake_global_known_hosts'
"github.com ssh-ed25519 AAAAUNRELATEDGLOBALENTRY" | Out-File -Encoding ascii $fakeGlobalKnownHosts
$globalHashBefore = (Get-FileHash $fakeGlobalKnownHosts -Algorithm SHA256).Hash

& $pinScript -SshRoot $sshRoot
if ($LASTEXITCODE -ne 0 -and $null -ne $LASTEXITCODE) { $fail += "Write-OttoGuideHostKeyPin.ps1 (primera corrida) fallo inesperadamente" }

$khost = Join-Path $sshRoot 'known_hosts'
if (-not (Test-Path $khost)) { $fail += "Write-OttoGuideHostKeyPin.ps1 no creo known_hosts dedicado" }
else {
  $lines = Get-Content $khost
  $entry = $lines | Where-Object { $_ -match '^ottoguide-companion\s+ssh-ed25519\s+' }
  if (-not $entry) { $fail += "known_hosts dedicado no contiene la entrada 'ottoguide-companion ssh-ed25519 <KEY>' (item 4)" }
  elseif ($entry -notmatch [regex]::Escape($fakeKeyB64)) { $fail += "la entrada pineada no contiene la clave publica esperada (item 4)" }
  # (5) nunca la IP/IPv6 como autoridad
  $ipLines = $lines | Where-Object { $_ -match '^fe80::' -or $_ -match '^\d+\.\d+\.\d+\.\d+' }
  if ($ipLines) { $fail += "known_hosts dedicado contiene una entrada indexada por IP en vez de alias fijo (item 4/5)" }
}

# (5) known_hosts GLOBAL simulado no debe haber sido tocado
$globalHashAfter = (Get-FileHash $fakeGlobalKnownHosts -Algorithm SHA256).Hash
if ($globalHashAfter -ne $globalHashBefore) { $fail += "known_hosts global simulado fue modificado (item 5)" }

# (6) escritura atomica: no debe quedar un known_hosts.tmp huerfano
if (Test-Path "$khost.tmp") { $fail += "quedo un known_hosts.tmp huerfano tras la escritura atomica (item 6)" }

# Segunda corrida con MISMA clave: debe ser idempotente (no falla, no duplica linea)
& $pinScript -SshRoot $sshRoot
if ($LASTEXITCODE -ne 0 -and $null -ne $LASTEXITCODE) { $fail += "Write-OttoGuideHostKeyPin.ps1 (corrida idempotente) fallo inesperadamente" }
$linesAfterSecondRun = @(Get-Content $khost | Where-Object { $_ -match '^ottoguide-companion\s' })
if ($linesAfterSecondRun.Count -ne 1) { $fail += "la segunda corrida con la MISMA clave duplico o elimino la entrada 'ottoguide-companion' (esperado 1, encontrado $($linesAfterSecondRun.Count))" }

# --- (7) rechazo de fingerprint/clave DISTINTA sin -Force ---
# Tambien Base64 valido con su fingerprint REAL correspondiente (no un fingerprint
# arbitrario que no corresponde a la clave), para probar especificamente el rechazo
# por "distinta a la ya pineada", no un rechazo accidental por inconsistencia interna.
$diffKeyBytes = [System.Text.Encoding]::UTF8.GetBytes('DIFFERENTKEYSIMULATINGROTATIONOOPS9876543210')
$diffKeyB64 = [Convert]::ToBase64String($diffKeyBytes)
$diffKeyFingerprint = Get-TestSha256Fingerprint $diffKeyBytes
$targetObj2 = [ordered]@{
  target = 'fe80::9%9'; interface = 'Ethernet 3'; ifindex = 9
  utc = (Get-Date).ToUniversalTime().ToString('o')
  key_type = 'ssh-ed25519'; key_base64 = $diffKeyB64; fingerprint = $diffKeyFingerprint
}
$targetObj2 | ConvertTo-Json | Out-File -Encoding ascii (Join-Path $stateDir 'target.json')
$rejectedRotation = $false
try {
  & $pinScript -SshRoot $sshRoot 2>$null
  if ($LASTEXITCODE -eq 0) { $rejectedRotation = $false } else { $rejectedRotation = $true }
} catch { $rejectedRotation = $true }
if (-not $rejectedRotation) { $fail += "Write-OttoGuideHostKeyPin.ps1 acepto silenciosamente una clave DISTINTA sin -Force (item 7)" }
$linesAfterRejection = @(Get-Content $khost | Where-Object { $_ -match '^ottoguide-companion\s' })
if ($linesAfterRejection.Count -ne 1 -or $linesAfterRejection[0] -notmatch [regex]::Escape($fakeKeyB64)) {
  $fail += "tras el intento de rotacion rechazado, la entrada original ya no esta intacta (item 7)"
}

Remove-Item -Recurse -Force $sandbox -ErrorAction SilentlyContinue

# ============================================================================
# 8-10. Comando de instalacion: sin precedencia ambigua, sin ssh directo, con -F
# ============================================================================
$installSrc = Get-Content (Join-Path $notebookDir 'Install-OttoGuidePublicKey.ps1') -Raw

# (8) construccion ambigua "A && B && grep ... || echo ... && C" ya no debe existir
if ($installSrc -match 'grep\s+-qxF[^\n]*\|\|[^\n]*echo[^\n]*&&') {
  $fail += "Install-OttoGuidePublicKey.ps1 todavia tiene la construccion ambigua '&&/||' original (item 8)"
}
if ($installSrc -notmatch '(?m)^\s*set\s+-eu\s*$') {
  $fail += "el script remoto de instalacion no usa 'set -eu' (fail-closed, item 8)"
}

# (9) nunca 'ssh unitree@<Target>' directo (ni con la variable RemoteUser/Target interpolada)
if ($installSrc -match 'ssh\s+"\$RemoteUser@\$Target"') {
  $fail += "Install-OttoGuidePublicKey.ps1 todavia usa 'ssh `$RemoteUser@`$Target' directo (item 9)"
}

# (10) debe usar '-F ... generated_target.conf'
if ($installSrc -notmatch '-F\s+\$genConf') {
  $fail += "Install-OttoGuidePublicKey.ps1 no usa '-F `$genConf' (generated_target.conf) para la instalacion (item 10)"
}
if ($installSrc -notmatch 'ssh\s+-F\s+\$genConf\s+ottoguide\b') {
  $fail += "Install-OttoGuidePublicKey.ps1 no invoca el alias 'ottoguide' via -F `$genConf (item 10)"
}

# ============================================================================
# 11. Generacion temporal de clave ED25519 REALMENTE sin passphrase
# ============================================================================
$keygenSandbox = Join-Path $env:TEMP ("og_keygen_test_" + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $keygenSandbox -Force | Out-Null
$testKeyPath = Join-Path $keygenSandbox 'id_ed25519_test'
try {
  . (Join-Path $notebookDir 'OttoGuideKeygenHelpers.ps1')
  New-OttoGuideEd25519KeyNoPassphrase -KeyPath $testKeyPath -Comment 'ottoguide-bootstrap-test' *> (Join-Path $keygenSandbox 'keygen.log')
  if (-not (Test-Path $testKeyPath) -or -not (Test-Path "$testKeyPath.pub")) {
    $fail += "New-OttoGuideEd25519KeyNoPassphrase no genero ambos archivos de la identidad (item 11)"
  } else {
    # confirma que NO pide passphrase: ssh-keygen -y debe derivar la publica sin prompt
    $derivedPub = & cmd /c "ssh-keygen -y -f `"$testKeyPath`" -P `"`" 2>nul"
    if ($LASTEXITCODE -ne 0 -or -not $derivedPub) {
      $fail += "ssh-keygen -y sobre la clave temporal fallo o pidio passphrase (item 11: la clave NO quedo realmente sin passphrase)"
    } else {
      $pubFileContent = (Get-Content "$testKeyPath.pub" -Raw).Trim()
      $derivedTrimmed = ($derivedPub -join ' ').Trim()
      $pubFields = $pubFileContent -split '\s+'
      if ($derivedTrimmed -notmatch [regex]::Escape($pubFields[1])) {
        $fail += "la clave publica derivada de la privada no coincide con el archivo .pub generado (item 11)"
      }
    }
  }
} finally {
  Remove-Item -Recurse -Force $keygenSandbox -ErrorAction SilentlyContinue
}

# Verificacion estructural: Bootstrap-OttoGuideNotebook.ps1 debe usar el helper
# compartido y verificado, no una invocacion inline sin verificar.
$bootstrapSrc = Get-Content (Join-Path $notebookDir 'Bootstrap-OttoGuideNotebook.ps1') -Raw
if ($bootstrapSrc -notmatch 'New-OttoGuideEd25519KeyNoPassphrase') {
  $fail += "Bootstrap-OttoGuideNotebook.ps1 no usa el helper verificado New-OttoGuideEd25519KeyNoPassphrase (item 11)"
}

# ============================================================================
# 12. Manifiesto remoto con DIEZ hashes
# ============================================================================
$sumsPath = Join-Path $companionDir 'REMOTE_RUNTIME_SHA256SUMS.txt'
if (-not (Test-Path $sumsPath)) { $fail += "falta REMOTE_RUNTIME_SHA256SUMS.txt (item 12)" }
else {
  $sumLines = @(Get-Content $sumsPath | Where-Object { $_.Trim() -ne '' })
  if ($sumLines.Count -ne 10) { $fail += "REMOTE_RUNTIME_SHA256SUMS.txt tiene $($sumLines.Count) entradas, se esperaban 10 (item 12)" }
  if (($sumLines | Where-Object { $_ -match 'discover_companion_python\.sh$' }).Count -ne 1) {
    $fail += "REMOTE_RUNTIME_SHA256SUMS.txt no incluye discover_companion_python.sh (item 12)"
  }
  # cada linea: 64 hex chars + ' *' + nombre
  foreach ($l in $sumLines) {
    if ($l -notmatch '^[0-9a-f]{64}\s+\*\S+$') { $fail += "linea de hash con formato invalido: '$l' (item 12)" }
  }
}
$manifestJsonPath = Join-Path $companionDir 'companion_runtime_manifest.json'
if (Test-Path $manifestJsonPath) {
  $manifestJson = Get-Content $manifestJsonPath -Raw | ConvertFrom-Json
  if (-not $manifestJson.hash_verified_files -or @($manifestJson.hash_verified_files).Count -ne 10) {
    $fail += "companion_runtime_manifest.json.hash_verified_files no tiene 10 entradas (item 12)"
  }
}

# ============================================================================
# Resultado
# ============================================================================
if ($fail.Count -gt 0) {
  Write-Host "SSH_BOOTSTRAP_LOGIC_OFFLINE_TESTED = false"
  $fail | ForEach-Object { Write-Host "FAIL: $_" }
  exit 1
}

Write-Host "SSH_BOOTSTRAP_LOGIC_OFFLINE_TESTED = true"
Write-Host "[test] PASS - multi-adaptador por fingerprint, pinning atomico/idempotente/anti-rotacion,"
Write-Host "[test]        instalacion fail-closed sin ssh directo, keygen temporal sin passphrase,"
Write-Host "[test]        manifiesto remoto con 10 hashes."
exit 0
