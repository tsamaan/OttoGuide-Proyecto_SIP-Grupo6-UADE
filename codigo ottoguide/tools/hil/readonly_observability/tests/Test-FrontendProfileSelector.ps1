<#
  WEB-HIL-R1B — Test-FrontendProfileSelector.ps1
  Prueba OFFLINE (sin SSH real, sin robot) de Start-OttoGuideFrontend.ps1 -Profile:
  sirve AMBOS builds precompilados (dist-real/, dist-replay/) por separado, en puertos
  distintos, y verifica que el bundle servido efectivamente contiene el badge/perfil
  correcto horneado ("REAL" en dist-real, "REPLAY" en dist-replay) -- nunca declara
  REPLAY si en realidad esta sirviendo el build REAL, ni viceversa.

  Requiere que frontend/dist-real/ y frontend/dist-replay/ ya existan (generados por
  'npm run build:real' / 'npm run build:replay' + generate_dist_manifest.py). Si no
  existen, el test se salta con exit 0 y un aviso (no bloquea offline suites que corren
  antes del paso de build de frontend en CI).

  Uso: powershell -ExecutionPolicy Bypass -File Test-FrontendProfileSelector.ps1
  Exit code 0 = PASS (o SKIP), !=0 = FAIL.
#>
$ErrorActionPreference = 'Stop'
$repoRoot = Resolve-Path (Join-Path $PSScriptRoot '..')
$notebookDir = Join-Path $repoRoot 'notebook'
$frontendDir = Join-Path $repoRoot 'frontend'
$startScript = Join-Path $notebookDir 'Start-OttoGuideFrontend.ps1'
$fail = @()

# ============================================================================
# 1. Verificacion estructural: -Profile existe, ValidateSet real/replay, sin
#    default implicito hacia un directorio ambiguo compartido.
# ============================================================================
$startSrc = Get-Content $startScript -Raw
if ($startSrc -notmatch "\[ValidateSet\('real',\s*'replay'\)\]") {
  $fail += "Start-OttoGuideFrontend.ps1 no declara [ValidateSet('real','replay')] para -Profile (FASE D)"
}
if ($startSrc -notmatch 'dist-real' -or $startSrc -notmatch 'dist-replay') {
  $fail += "Start-OttoGuideFrontend.ps1 no resuelve dist-real/dist-replay por separado (FASE D)"
}
if ($startSrc -match "Join-Path\s+\`$RepoRoot\s+'frontend\\dist'[^-]") {
  $fail += "Start-OttoGuideFrontend.ps1 todavia referencia el directorio ambiguo 'frontend\dist' compartido (FASE C2/D)"
}

$distReal = Join-Path $frontendDir 'dist-real'
$distReplay = Join-Path $frontendDir 'dist-replay'
if (-not (Test-Path (Join-Path $distReal 'index.html')) -or -not (Test-Path (Join-Path $distReplay 'index.html'))) {
  Write-Host "FRONTEND_PROFILE_OFFLINE_TESTED = skipped (dist-real/dist-replay no generados todavia en este checkout)"
  if ($fail.Count -gt 0) { $fail | ForEach-Object { Write-Host "FAIL: $_" }; exit 1 }
  exit 0
}

# ============================================================================
# 2. Falla explicitamente si falta index.html en el directorio resuelto.
# ============================================================================
$missingProfileSandbox = Join-Path $env:TEMP ("og_frontend_missing_" + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path (Join-Path $missingProfileSandbox 'frontend') -Force | Out-Null
try {
  & $startScript -RepoRoot $missingProfileSandbox -SshRoot (Join-Path $missingProfileSandbox 'sshroot') -Port 18099 -Profile real 2>$null
  $fail += "Start-OttoGuideFrontend.ps1 no lanzo error con dist-real/index.html ausente (FASE D, item: fallar si falta index.html)"
} catch {
  # esperado: debe fallar
} finally {
  Remove-Item -Recurse -Force $missingProfileSandbox -ErrorAction SilentlyContinue
}

# ============================================================================
# 3. Servir AMBOS perfiles reales por separado y verificar el badge horneado.
# ============================================================================
function Get-JsAssetPath([string]$distDir) {
  $js = Get-ChildItem (Join-Path $distDir 'assets') -Filter '*.js' -ErrorAction SilentlyContinue | Select-Object -First 1
  if (-not $js) { return $null }
  return $js.FullName
}

$realJs = Get-JsAssetPath $distReal
$replayJs = Get-JsAssetPath $distReplay
if (-not $realJs) { $fail += "no se encontro el bundle .js en dist-real/assets" }
if (-not $replayJs) { $fail += "no se encontro el bundle .js en dist-replay/assets" }

if ($realJs -and $replayJs) {
  $realContent = Get-Content $realJs -Raw
  $replayContent = Get-Content $replayJs -Raw
  if ($realContent -notmatch 'VITE_DEPLOYMENT_PROFILE:"real"') {
    $fail += 'dist-real/assets/*.js no tiene VITE_DEPLOYMENT_PROFILE:"real" horneado (perfil incorrecto o build viejo, FASE C2)'
  }
  if ($replayContent -notmatch 'VITE_DEPLOYMENT_PROFILE:"replay"') {
    $fail += 'dist-replay/assets/*.js no tiene VITE_DEPLOYMENT_PROFILE:"replay" horneado (perfil incorrecto o build viejo, FASE C2)'
  }
  if ($realContent -eq $replayContent) {
    $fail += "dist-real y dist-replay tienen bundles JS byte-identicos (regresion del bug de env-substitution, FASE C2)"
  }
}

# 4. Servir HTTP real (sirviendo ambos perfiles por separado en puertos distintos) y
#    verificar via HTTP que cada uno responde con SU propio bundle.
$stateSandbox = Join-Path $env:TEMP ("og_frontend_serve_" + [guid]::NewGuid().ToString('N'))
$sshRootReal = Join-Path $stateSandbox 'sshroot_real'
$sshRootReplay = Join-Path $stateSandbox 'sshroot_replay'
New-Item -ItemType Directory -Path $sshRootReal -Force | Out-Null
New-Item -ItemType Directory -Path $sshRootReplay -Force | Out-Null

$portReal = 18100
$portReplay = 18101
$pidReal = $null
$pidReplay = $null
try {
  $pidReal = & $startScript -RepoRoot $repoRoot -SshRoot $sshRootReal -Port $portReal -Profile real
  $pidReplay = & $startScript -RepoRoot $repoRoot -SshRoot $sshRootReplay -Port $portReplay -Profile replay
  Start-Sleep -Milliseconds 800

  $realHtml = $null; $replayHtml = $null
  try { $realHtml = (Invoke-WebRequest -UseBasicParsing -Uri "http://127.0.0.1:$portReal/index.html" -TimeoutSec 5).Content } catch { $fail += "GET http://127.0.0.1:$portReal/index.html fallo: $($_.Exception.Message)" }
  try { $replayHtml = (Invoke-WebRequest -UseBasicParsing -Uri "http://127.0.0.1:$portReplay/index.html" -TimeoutSec 5).Content } catch { $fail += "GET http://127.0.0.1:$portReplay/index.html fallo: $($_.Exception.Message)" }

  if ($realHtml -and $replayHtml -and $realHtml -eq $replayHtml) {
    $fail += "index.html servido en el puerto REAL y en el puerto REPLAY es byte-identico (item: no declarar REPLAY si se sirve REAL)"
  }

  $realJsName = Split-Path $realJs -Leaf
  $replayJsName = Split-Path $replayJs -Leaf
  $realJsHttp = $null; $replayJsHttp = $null
  try { $realJsHttp = (Invoke-WebRequest -UseBasicParsing -Uri "http://127.0.0.1:$portReal/assets/$realJsName" -TimeoutSec 5).Content } catch { $fail += "GET del bundle JS REAL via HTTP fallo: $($_.Exception.Message)" }
  try { $replayJsHttp = (Invoke-WebRequest -UseBasicParsing -Uri "http://127.0.0.1:$portReplay/assets/$replayJsName" -TimeoutSec 5).Content } catch { $fail += "GET del bundle JS REPLAY via HTTP fallo: $($_.Exception.Message)" }

  if ($realJsHttp -and $realJsHttp -notmatch 'VITE_DEPLOYMENT_PROFILE:"real"') {
    $fail += "el bundle servido por HTTP en el puerto REAL no contiene el perfil 'real' horneado (item: REAL_UI_PROFILE)"
  }
  if ($replayJsHttp -and $replayJsHttp -notmatch 'VITE_DEPLOYMENT_PROFILE:"replay"') {
    $fail += "el bundle servido por HTTP en el puerto REPLAY no contiene el perfil 'replay' horneado (item: REPLAY_UI_PROFILE)"
  }

  # 5. frontend_pid.json debe registrar el perfil servido explicitamente.
  $pidJsonReal = Get-Content (Join-Path $sshRootReal 'state\frontend_pid.json') -Raw | ConvertFrom-Json
  if ($pidJsonReal.profile -ne 'real') { $fail += "frontend_pid.json (instancia REAL) no registra profile='real' (registro: '$($pidJsonReal.profile)')" }
  $pidJsonReplay = Get-Content (Join-Path $sshRootReplay 'state\frontend_pid.json') -Raw | ConvertFrom-Json
  if ($pidJsonReplay.profile -ne 'replay') { $fail += "frontend_pid.json (instancia REPLAY) no registra profile='replay' (registro: '$($pidJsonReplay.profile)')" }
} finally {
  foreach ($procId in @($pidReal, $pidReplay)) {
    if ($procId) { Stop-Process -Id $procId -Force -ErrorAction SilentlyContinue }
  }
  Remove-Item -Recurse -Force $stateSandbox -ErrorAction SilentlyContinue
}

if ($fail.Count -gt 0) {
  Write-Host "FRONTEND_PROFILE_OFFLINE_TESTED = false"
  $fail | ForEach-Object { Write-Host "FAIL: $_" }
  exit 1
}

Write-Host "FRONTEND_PROFILE_OFFLINE_TESTED = true"
Write-Host "REAL_UI_PROFILE = REAL"
Write-Host "REPLAY_UI_PROFILE = REPLAY"
Write-Host "[test] PASS - dist-real y dist-replay servidos por separado, cada uno con su badge/perfil correcto,"
Write-Host "[test]        bundles JS distintos, frontend_pid.json registra el perfil servido."
exit 0
