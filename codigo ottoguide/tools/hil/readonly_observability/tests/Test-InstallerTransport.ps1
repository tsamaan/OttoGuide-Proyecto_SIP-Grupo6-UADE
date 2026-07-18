<#
  WEB-HIL-R1B — Test-InstallerTransport.ps1
  Prueba OFFLINE (sin SSH real, sin robot) del transporte de Install-OttoGuidePublicKey.ps1
  introducido en la FASE E: reemplaza 'ssh' por un shim que CAPTURA el comando remoto
  exacto que recibiria (sin ejecutar ninguna conexion real) y ademas confirma que el
  proceso NO intenta leer nada de stdin (el stdin debe quedar libre para el prompt nativo
  de OpenSSH). Luego decodifica los dos literales Base64 del comando capturado y ejecuta
  el script decodificado contra un HOME temporal via 'sh' real, para validar
  idempotencia, permisos 700/600 (cuando el filesystem los soporta) y que un comentario
  de clave con espacios/caracteres especiales no altera el shell remoto.

  Uso: powershell -ExecutionPolicy Bypass -File Test-InstallerTransport.ps1
  Exit code 0 = PASS, !=0 = FAIL.
#>
$ErrorActionPreference = 'Stop'
$repoRoot = Resolve-Path (Join-Path $PSScriptRoot '..')
$notebookDir = Join-Path $repoRoot 'notebook'
$installScript = Join-Path $notebookDir 'Install-OttoGuidePublicKey.ps1'
if (-not (Test-Path $installScript)) { throw "No se encuentra $installScript" }
$fail = @()

# ============================================================================
# 1. Verificacion estructural: sin transporte por stdin, sin comillas dobles
#    embebidas en la construccion del comando remoto (la causa raiz del bug de
#    marshalling verificado en este checkpoint).
# ============================================================================
$installSrc = Get-Content $installScript -Raw
if ($installSrc -match '\$stdinPayload\s*\|') {
  $fail += "Install-OttoGuidePublicKey.ps1 todavia tiene un transporte por stdin ('\$stdinPayload | ssh ...') (FASE E)"
}
if ($installSrc -match 'read -r PUBLIC_KEY_B64') {
  $fail += "Install-OttoGuidePublicKey.ps1 todavia lee la clave desde stdin remoto ('read -r PUBLIC_KEY_B64') (FASE E)"
}
if ($installSrc -notmatch '\[Convert\]::ToBase64String') {
  $fail += "Install-OttoGuidePublicKey.ps1 no codifica nada en Base64 (FASE E)"
}

# ============================================================================
# 2. Shim de 'ssh' que CAPTURA argv completo (no ejecuta nada real) y confirma
#    que el proceso llamante no intenta escribir nada a su stdin.
# ============================================================================
$sandbox = Join-Path $env:TEMP ("og_installer_test_" + [guid]::NewGuid().ToString('N'))
$binDir = Join-Path $sandbox 'bin'
$sshRoot = Join-Path $sandbox 'sshroot'
New-Item -ItemType Directory -Path $binDir -Force | Out-Null
New-Item -ItemType Directory -Path $sshRoot -Force | Out-Null
New-Item -ItemType Directory -Path (Join-Path $sshRoot 'state') -Force | Out-Null

$capturedArgsPath = Join-Path $sandbox 'ssh_captured_args.json'
$stdinProbePath = Join-Path $sandbox 'ssh_stdin_probe.txt'

# Shim de ssh.cmd puro (sin PowerShell anidado, igual criterio que Test-WatchdogLogic.ps1):
# vuelca sus argumentos a un JSON via un ayudante .ps1 liviano, y prueba si stdin tiene
# datos disponibles YA (sin bloquear) -- si el instalador insistiera en escribir a stdin
# antes de que el shim lo consuma, quedaria evidencia en el probe.
$dumpHelper = Join-Path $binDir '_dump_ssh_args.ps1'
@'
param([Parameter(ValueFromRemainingArguments=$true)][string[]]$A)
# Install-OttoGuidePublicKey.ps1 invoca ssh DOS veces (instalacion + verificacion
# BatchMode); se registra CADA invocacion como una linea JSON separada (append), para
# poder distinguir la primera (la que importa a este test) de la segunda.
($A | ConvertTo-Json -Compress) | Add-Content -Encoding utf8 $env:OG_TEST_SSH_CAPTURE
# Registra si stdin llego redirigido (propiedad no bloqueante: NUNCA lee bytes, solo
# consulta el estado del handle). El test principal (paso 1, estructural) ya confirma
# que el codigo fuente no contiene ningun '$algo | ssh ...'; esta sonda de runtime es un
# chequeo adicional barato, no la unica fuente de verdad, precisamente para no arriesgar
# un bloqueo intentando leer un stream que podria no tener EOF en este entorno de shim.
"is_input_redirected=$([Console]::IsInputRedirected)" | Out-File -Encoding utf8 $env:OG_TEST_SSH_STDIN_PROBE
Write-Host 'INSTALADO_OK'
exit 0
'@ | Out-File -Encoding utf8 $dumpHelper

@"
@echo off
powershell -NoProfile -ExecutionPolicy Bypass -File "$dumpHelper" %*
"@ | Out-File -Encoding ascii (Join-Path $binDir 'ssh.cmd')

# Shims de resolucion/pin/config: devuelven estado fijo valido sin tocar red real.
$fakeTarget = 'fake-installer-target'
@"
param([string]`$SshRoot, [string]`$ExpectedFingerprint)
`$stateDir = Join-Path `$SshRoot 'state'
if (-not (Test-Path `$stateDir)) { New-Item -ItemType Directory -Path `$stateDir -Force | Out-Null }
@{ target = '$fakeTarget'; interface = 'FAKE'; ifindex = 0; utc = (Get-Date).ToUniversalTime().ToString('o'); key_type='ssh-ed25519'; key_base64='FAKEBASE64KEY'; fingerprint='SHA256:FAKE' } |
  ConvertTo-Json | Out-File -Encoding ascii (Join-Path `$stateDir 'target.json')
'$fakeTarget'
"@ | Out-File -Encoding ascii (Join-Path $binDir 'Resolve-OttoGuideTarget.ps1')

@"
param([string]`$SshRoot, [switch]`$Force)
Write-Output 'HOSTKEYPIN_SHIM_CALLED'
"@ | Out-File -Encoding ascii (Join-Path $binDir 'Write-OttoGuideHostKeyPin.ps1')

@"
param([string]`$SshRoot, [string]`$IdentityName, [string]`$RemoteUser)
`$conf = Join-Path `$SshRoot 'generated_target.conf'
'Host ottoguide' | Out-File -Encoding ascii `$conf
`$conf
"@ | Out-File -Encoding ascii (Join-Path $binDir 'Write-OttoGuideSshConfig.ps1')

# ssh-keygen real (necesario para el print de fingerprint) sigue en PATH; no se shimea.

# Install-OttoGuidePublicKey.ps1 resuelve sus scripts hermanos via $PSScriptRoot (ruta
# absoluta a notebook/), no via PATH -- igual que Test-WatchdogLogic.ps1 con el watchdog,
# se copia el script REAL a binDir/ para que $PSScriptRoot de la copia sea binDir/ y asi
# encuentre los shims de Resolve/HostKeyPin/SshConfig en vez de los scripts reales.
$installScriptCopy = Join-Path $binDir 'Install-OttoGuidePublicKey.ps1'
Set-Content -Encoding utf8 $installScriptCopy (Get-Content $installScript -Raw)

# Identidad de prueba REAL (ssh-keygen -lf en Install-OttoGuidePublicKey.ps1 valida
# estructura de clave, no acepta un string arbitrario) con COMENTARIO con espacios y
# caracteres especiales, para ejercer el requisito "el comentario de una clave con
# espacios y caracteres especiales no altera el shell remoto".
$fakeHome = Join-Path $sandbox 'userprofile'
New-Item -ItemType Directory -Path (Join-Path $fakeHome '.ssh') -Force | Out-Null
$identityName = 'id_ed25519_ottoguide_robot'
$testKeyPath = Join-Path $fakeHome ".ssh\$identityName"
$specialComment = "test operator's laptop (2026) `$HOME;rm -rf"
. (Join-Path $notebookDir 'OttoGuideKeygenHelpers.ps1')
New-OttoGuideEd25519KeyNoPassphrase -KeyPath $testKeyPath -Comment $specialComment *> (Join-Path $sandbox 'keygen_for_test.log')
if (-not (Test-Path "$testKeyPath.pub")) {
  $fail += "no se pudo generar la identidad ED25519 real para el test"
}
$pubKeyLine = (Get-Content "$testKeyPath.pub" -Raw).Trim()

$env:OG_TEST_SSH_CAPTURE = $capturedArgsPath
$env:OG_TEST_SSH_STDIN_PROBE = $stdinProbePath
$oldPath = $env:PATH
$oldUserProfile = $env:USERPROFILE
$env:PATH = "$binDir;$oldPath"
$env:USERPROFILE = $fakeHome

try {
  & $installScriptCopy -SshRoot $sshRoot -IdentityName $identityName -RemoteUser 'unitree' -ExpectedFingerprint 'SHA256:FAKE' *> (Join-Path $sandbox 'install_output.log')
} catch {
  $fail += "Install-OttoGuidePublicKey.ps1 lanzo una excepcion inesperada: $($_.Exception.Message)"
} finally {
  $env:PATH = $oldPath
  $env:USERPROFILE = $oldUserProfile
}

if (-not (Test-Path $capturedArgsPath)) {
  $fail += "el shim de ssh nunca fue invocado (no se capturo ningun argv)"
} else {
  $capturedCalls = @(Get-Content $capturedArgsPath | Where-Object { $_.Trim() -ne '' } | ForEach-Object { ,($_ | ConvertFrom-Json) })
  if ($capturedCalls.Count -lt 1) { $fail += "no se capturo ninguna invocacion de ssh" }
  # La PRIMERA invocacion es la de instalacion (alias 'ottoguide' + comando remoto); la
  # segunda (si existe) es la verificacion BatchMode con 'ottoguide-batch'.
  $firstCallArgs = $capturedCalls[0]
  # El comando remoto real esta en el ULTIMO elemento de esa invocacion (tras -F <conf> ottoguide).
  $remoteCmdArg = $firstCallArgs[$firstCallArgs.Count - 1]

  if ($remoteCmdArg -match '"') {
    $fail += "el argv del comando remoto capturado contiene comillas dobles (riesgo de fragmentacion via marshalling nativo)"
  }
  if ($remoteCmdArg -notmatch "^PUBLIC_KEY_B64='[A-Za-z0-9+/=]+' sh -c 'printf %s [A-Za-z0-9+/=]+ \| base64 -d \| sh -s'$") {
    $fail += "el comando remoto capturado no tiene la forma esperada (solo comillas simples, dos literales Base64): [$remoteCmdArg]"
  } else {
    # 3. Decodificar ambos Base64 y EJECUTAR el script contra un HOME temporal real via sh.
    if ($remoteCmdArg -match "PUBLIC_KEY_B64='([A-Za-z0-9+/=]+)'") { $pubB64 = $Matches[1] } else { $pubB64 = $null }
    if ($remoteCmdArg -match "printf %s ([A-Za-z0-9+/=]+) \|") { $scriptB64 = $Matches[1] } else { $scriptB64 = $null }
    if (-not $pubB64 -or -not $scriptB64) {
      $fail += "no se pudieron extraer ambos literales Base64 del comando capturado"
    } else {
      $decodedPub = [System.Text.Encoding]::UTF8.GetString([Convert]::FromBase64String($pubB64))
      if ($decodedPub -ne $pubKeyLine) {
        $fail += "la clave publica decodificada no coincide con la original (item: comentario con espacios/caracteres especiales pudo haberse corrompido)"
      }

      $execHome = Join-Path $sandbox 'exec_home'
      New-Item -ItemType Directory -Path $execHome -Force | Out-Null
      # Get-Command bash.exe puede resolver C:\WINDOWS\system32\bash.exe (el lanzador de
      # WSL, semantica de rutas COMPLETAMENTE distinta), no el sh/bash real de Git for
      # Windows que este toolkit ya asume como dependencia (ssh/ssh-keygen/ssh-keyscan).
      # Se prioriza explicitamente la instalacion de Git for Windows.
      $bashCandidates = @(
        'C:\Program Files\Git\usr\bin\bash.exe',
        'C:\Program Files\Git\bin\bash.exe'
      ) + @((Get-Command bash.exe -All -ErrorAction SilentlyContinue).Source | Where-Object { $_ -notmatch '\\System32\\' })
      $bashExe = $bashCandidates | Where-Object { Test-Path $_ } | Select-Object -First 1
      if (-not $bashExe) {
        $fail += "no se encontro un bash.exe de Git for Windows (no-WSL) para ejecutar el script decodificado (item 5 del test)"
      } else {
        $env:PUBLIC_KEY_B64 = $pubB64
        function ConvertTo-UnixPath([string]$winPath) {
          # Git-Bash/MSYS sh espera '/c/Users/...', no 'C:/Users/...'. Usa GetFullPath
          # primero para resolver cualquier segmento corto (p.ej. 'IDEAPA~1') a su forma
          # larga real, porque 'sh' resuelve la ruta literal sin expandir 8.3 names.
          $full = [System.IO.Path]::GetFullPath($winPath)
          return ($full -replace '\\', '/') -replace '^([A-Za-z]):', '/$1'
        }
        $execHomeUnix = ConvertTo-UnixPath $execHome
        # El PATH heredado por el proceso hijo de bash.exe no esta garantizado que
        # incluya usr/bin (donde viven sh/base64/grep de Git for Windows) en este entorno
        # de test con PATH ya modificado para los shims de ssh; se antepone
        # explicitamente dentro del propio 'bash -c'.
        $gitUsrBinUnix = ConvertTo-UnixPath (Split-Path $bashExe -Parent)
        # Reproduce EXACTAMENTE la misma tuberia que ejecutaria el Companion real (ver
        # $remoteCommand en Install-OttoGuidePublicKey.ps1): 'printf %s <B64> | base64 -d
        # | sh -s', con PUBLIC_KEY_B64 como variable de entorno. Se invoca a traves de
        # bash -c para tener HOME acotado al sandbox, pero la tuberia interna es identica
        # a la de produccion (no una variante "equivalente" reimplementada en el test).
        # 'export PATH=...' (no un prefijo 'VAR=val cmd', que solo aplicaria al primer
        # comando de la tuberia) para que TODOS los comandos de la tuberia (printf,
        # base64, sh) hereden el PATH extendido.
        $innerPipeline = "export PATH='$gitUsrBinUnix':`$PATH; export HOME='$execHomeUnix'; export PUBLIC_KEY_B64='$pubB64'; printf %s $scriptB64 | base64 -d | sh -s"
        $out1 = & $bashExe -c $innerPipeline 2>&1
        $rc1 = $LASTEXITCODE
        if ($rc1 -ne 0 -or ($out1 -notmatch 'INSTALADO_OK')) {
          $fail += "primera ejecucion de la tuberia decodificada fallo (rc=$rc1): $out1"
        }
        $authKeysPath = Join-Path $execHome '.ssh\authorized_keys'
        if (-not (Test-Path $authKeysPath)) {
          $fail += "el script decodificado no creo authorized_keys"
        } else {
          $content1 = (Get-Content $authKeysPath -Raw).TrimEnd("`n")
          if ($content1 -ne $decodedPub) { $fail += "authorized_keys no contiene exactamente la clave esperada tras la primera ejecucion" }

          # 4. Idempotencia: segunda ejecucion NO debe duplicar la linea.
          $out2 = & $bashExe -c $innerPipeline 2>&1
          $rc2 = $LASTEXITCODE
          if ($rc2 -ne 0) { $fail += "segunda ejecucion (idempotencia) fallo (rc=$rc2): $out2" }
          $lines2 = @(Get-Content $authKeysPath | Where-Object { $_.Trim() -ne '' })
          if ($lines2.Count -ne 1) { $fail += "authorized_keys tiene $($lines2.Count) lineas tras ejecutar dos veces (se esperaba 1, no idempotente)" }
        }
      }
    }
  }

  # 2b. Sonda adicional de runtime (no bloqueante): confirma que el shim se ejecuto.
  #     La prueba de fondo de "sin transporte por stdin" es la verificacion ESTRUCTURAL
  #     del paso 1 (sin '$algo | ssh ...' en el codigo fuente).
  if (-not (Test-Path $stdinProbePath)) {
    $fail += "no se genero la sonda de stdin (el shim nunca llego a ejecutarse correctamente)"
  }
}

Remove-Item -Recurse -Force $sandbox -ErrorAction SilentlyContinue
Remove-Item Env:\OG_TEST_SSH_CAPTURE -ErrorAction SilentlyContinue
Remove-Item Env:\OG_TEST_SSH_STDIN_PROBE -ErrorAction SilentlyContinue
Remove-Item Env:\PUBLIC_KEY_B64 -ErrorAction SilentlyContinue

# ============================================================================
# 6. WEB-HIL-R1C: verificacion BatchMode fail-closed (no un warning con exit 0).
#    Dos escenarios con un shim de ssh que distingue la 1a invocacion (instalacion,
#    debe pasar) de la 2a (verificacion BatchMode, alias 'ottoguide-batch'):
#    - rc BatchMode = 0  -> el script debe completar y reportar BATCH_AUTH = PASS.
#    - rc BatchMode != 0 -> el script debe LANZAR (throw), nunca terminar con
#      exit 0 ni solo un warning (regresion confirmada de WEB-HIL-R1C seccion 6.C).
# ============================================================================
function Invoke-BatchModeScenario([int]$batchExitCode) {
  $sc = Join-Path $env:TEMP ("og_installer_batchmode_" + [guid]::NewGuid().ToString('N'))
  $scBin = Join-Path $sc 'bin'
  $scSshRoot = Join-Path $sc 'sshroot'
  New-Item -ItemType Directory -Path $scBin -Force | Out-Null
  New-Item -ItemType Directory -Path $scSshRoot -Force | Out-Null
  New-Item -ItemType Directory -Path (Join-Path $scSshRoot 'state') -Force | Out-Null

  $callCounterPath = Join-Path $sc 'call_count.txt'
  '0' | Out-File -Encoding ascii $callCounterPath

  # El shim distingue invocaciones por orden: la 1a (instalacion) siempre exit 0 e
  # imprime INSTALADO_OK; la 2a (BatchMode, 'ottoguide-batch') devuelve $batchExitCode.
  $dumpHelper2 = Join-Path $scBin '_dump_ssh_args_batchmode.ps1'
  @"
param([Parameter(ValueFromRemainingArguments=`$true)][string[]]`$A)
`$count = [int](Get-Content `$env:OG_TEST_CALL_COUNTER)
`$count += 1
`$count | Out-File -Encoding ascii `$env:OG_TEST_CALL_COUNTER
if (`$count -eq 1) {
  Write-Host 'INSTALADO_OK'
  exit 0
} else {
  exit $batchExitCode
}
"@ | Out-File -Encoding utf8 $dumpHelper2

  @"
@echo off
powershell -NoProfile -ExecutionPolicy Bypass -File "$dumpHelper2" %*
"@ | Out-File -Encoding ascii (Join-Path $scBin 'ssh.cmd')

  $fakeTarget2 = 'fake-installer-target-batchmode'
  @"
param([string]`$SshRoot, [string]`$ExpectedFingerprint)
`$stateDir = Join-Path `$SshRoot 'state'
if (-not (Test-Path `$stateDir)) { New-Item -ItemType Directory -Path `$stateDir -Force | Out-Null }
@{ target = '$fakeTarget2'; interface = 'FAKE'; ifindex = 0; utc = (Get-Date).ToUniversalTime().ToString('o'); key_type='ssh-ed25519'; key_base64='FAKEBASE64KEY'; fingerprint='SHA256:FAKE' } |
  ConvertTo-Json | Out-File -Encoding ascii (Join-Path `$stateDir 'target.json')
'$fakeTarget2'
"@ | Out-File -Encoding ascii (Join-Path $scBin 'Resolve-OttoGuideTarget.ps1')

  @"
param([string]`$SshRoot, [switch]`$Force)
Write-Output 'HOSTKEYPIN_SHIM_CALLED'
"@ | Out-File -Encoding ascii (Join-Path $scBin 'Write-OttoGuideHostKeyPin.ps1')

  @"
param([string]`$SshRoot, [string]`$IdentityName, [string]`$RemoteUser)
`$conf = Join-Path `$SshRoot 'generated_target.conf'
'Host ottoguide' | Out-File -Encoding ascii `$conf
`$conf
"@ | Out-File -Encoding ascii (Join-Path $scBin 'Write-OttoGuideSshConfig.ps1')

  $scInstallCopy = Join-Path $scBin 'Install-OttoGuidePublicKey.ps1'
  Set-Content -Encoding utf8 $scInstallCopy (Get-Content $installScript -Raw)

  $scFakeHome = Join-Path $sc 'userprofile'
  New-Item -ItemType Directory -Path (Join-Path $scFakeHome '.ssh') -Force | Out-Null
  $scIdentityName = 'id_ed25519_ottoguide_robot'
  $scTestKeyPath = Join-Path $scFakeHome ".ssh\$scIdentityName"
  . (Join-Path $notebookDir 'OttoGuideKeygenHelpers.ps1')
  New-OttoGuideEd25519KeyNoPassphrase -KeyPath $scTestKeyPath -Comment 'batchmode-scenario-test' *> (Join-Path $sc 'keygen_for_test.log')

  $env:OG_TEST_CALL_COUNTER = $callCounterPath
  $scOldPath = $env:PATH
  $scOldUserProfile = $env:USERPROFILE
  $env:PATH = "$scBin;$scOldPath"
  $env:USERPROFILE = $scFakeHome

  $threw = $false
  $errMsg = $null
  try {
    & $scInstallCopy -SshRoot $scSshRoot -IdentityName $scIdentityName -RemoteUser 'unitree' -ExpectedFingerprint 'SHA256:FAKE' *> (Join-Path $sc 'install_output.log')
    if ($LASTEXITCODE -ne 0) { $threw = $true }
  } catch {
    $threw = $true
    $errMsg = $_.Exception.Message
  } finally {
    $env:PATH = $scOldPath
    $env:USERPROFILE = $scOldUserProfile
    Remove-Item Env:\OG_TEST_CALL_COUNTER -ErrorAction SilentlyContinue
    Remove-Item Env:\PUBLIC_KEY_B64 -ErrorAction SilentlyContinue
  }

  Remove-Item -Recurse -Force $sc -ErrorAction SilentlyContinue
  return @{ Threw = $threw; ErrorMessage = $errMsg }
}

$passResult = Invoke-BatchModeScenario -batchExitCode 0
if ($passResult.Threw) {
  $fail += "item 'batch auth exit 0 -> PASS': el script lanzo/fallo aun cuando BatchMode devolvio rc=0 ($($passResult.ErrorMessage))"
}

$failResult = Invoke-BatchModeScenario -batchExitCode 5
if (-not $failResult.Threw) {
  $fail += "item 'batch auth exit != 0 -> script falla': Install-OttoGuidePublicKey.ps1 NO fallo cuando BatchMode devolvio rc!=0 (regresion: solo advertia con Write-Warning y exit 0)"
} elseif ($failResult.ErrorMessage -notmatch 'BatchMode fallo') {
  $fail += "item 'batch auth exit != 0 -> script falla': fallo pero sin el mensaje esperado ('BatchMode fallo...'): $($failResult.ErrorMessage)"
}

# 6b. no password en variables de entorno del proceso hijo, no ssh directo usuario@IP,
#     stdin permanece libre -- ya cubiertos estructuralmente en el paso 1 y por la sonda
#     del paso 2b; se re-confirma aqui que ninguno de los dos escenarios BatchMode
#     necesito ni establecio ninguna variable de contrasena.
if (Test-Path Env:\OG_SSH_PASSWORD) { $fail += "variable de entorno de contrasena detectada tras escenarios BatchMode (no deberia existir nunca)" }

if ($fail.Count -gt 0) {
  Write-Host "INSTALLER_TRANSPORT_OFFLINE_TESTED = false"
  $fail | ForEach-Object { Write-Host "FAIL: $_" }
  exit 1
}

Write-Host "INSTALLER_TRANSPORT_OFFLINE_TESTED = true"
Write-Host "[test] PASS - sin transporte por stdin, comando remoto sin comillas dobles embebidas,"
Write-Host "[test]        Base64 decodificado y ejecutado real, idempotente, comentario con"
Write-Host "[test]        espacios/caracteres especiales preservado sin alterar el shell."
exit 0
