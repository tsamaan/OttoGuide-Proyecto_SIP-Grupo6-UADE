<#
  WEB-HIL-R2E — Test-RemoteRuntimeManifest.ps1
  Verifica que REMOTE_RUNTIME_SHA256SUMS.txt tenga exactamente 10 entradas y que
  cada una coincida con el SHA-256 binario real del archivo correspondiente en
  companion/. Tambien detecta CRLF en cualquiera de los diez desplegables (deben
  ser LF puro, gobernado por companion/.gitattributes). Read-only: no modifica
  ningun archivo. Exit 0 solo si 10/10 coinciden y CRLF_DEPLOYABLE_FILES = 0.
#>
param(
  [string]$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..'))
)
$ErrorActionPreference = 'Stop'
$companionDir = Join-Path $RepoRoot 'companion'
$sumsPath = Join-Path $companionDir 'REMOTE_RUNTIME_SHA256SUMS.txt'

if (-not (Test-Path $sumsPath)) {
  Write-Host "[manifest-test] FALTA $sumsPath"
  exit 1
}

$sumsBytes = [System.IO.File]::ReadAllBytes($sumsPath)
$sumsText = [System.Text.Encoding]::UTF8.GetString($sumsBytes)
$lines = $sumsText -split "`n" | Where-Object { $_.Trim().Length -gt 0 }

$entries = @()
foreach ($line in $lines) {
  $line = $line.TrimEnd("`r")
  $parts = $line -split '\s+\*', 2
  if ($parts.Count -ne 2) {
    Write-Host "[manifest-test] Linea con formato invalido: '$line'"
    exit 1
  }
  $entries += [pscustomobject]@{ hash = $parts[0].Trim(); file = $parts[1].Trim() }
}

if ($entries.Count -ne 10) {
  Write-Host "[manifest-test] Se esperaban exactamente 10 entradas, se encontraron $($entries.Count)."
  exit 1
}

$sha256 = [System.Security.Cryptography.SHA256]::Create()
$mismatches = @()
$crlfFiles = @()

foreach ($e in $entries) {
  $fp = Join-Path $companionDir $e.file
  if (-not (Test-Path $fp)) {
    $mismatches += "$($e.file): ARCHIVO AUSENTE"
    continue
  }
  $bytes = [System.IO.File]::ReadAllBytes($fp)
  $hashBytes = $sha256.ComputeHash($bytes)
  $hashHex = -join ($hashBytes | ForEach-Object { $_.ToString('x2') })
  if ($hashHex -ne $e.hash) {
    $mismatches += "$($e.file): esperado=$($e.hash) actual=$hashHex"
  }
  # deteccion CRLF binaria: 0x0D 0x0A en los bytes reales del archivo
  $hasCrlf = $false
  for ($i = 0; $i -lt $bytes.Length - 1; $i++) {
    if ($bytes[$i] -eq 0x0D -and $bytes[$i+1] -eq 0x0A) { $hasCrlf = $true; break }
  }
  if ($hasCrlf) { $crlfFiles += $e.file }
}
$sha256.Dispose()

$matchCount = $entries.Count - $mismatches.Count
Write-Host "[manifest-test] LOCAL_RUNTIME_HASH = $matchCount/$($entries.Count)"
Write-Host "[manifest-test] CRLF_DEPLOYABLE_FILES = $($crlfFiles.Count)"

if ($mismatches.Count -gt 0) {
  Write-Host "[manifest-test] MISMATCHES:"
  $mismatches | ForEach-Object { Write-Host "  - $_" }
}
if ($crlfFiles.Count -gt 0) {
  Write-Host "[manifest-test] CRLF DETECTADO EN:"
  $crlfFiles | ForEach-Object { Write-Host "  - $_" }
}

if ($mismatches.Count -gt 0 -or $crlfFiles.Count -gt 0) {
  Write-Host "[manifest-test] RESULT = FAIL"
  exit 1
}

Write-Host "[manifest-test] RESULT = PASS (10/10 hash match, 0 CRLF)"
exit 0
