<#
  WEB-HIL-R1A — OttoGuideKeygenHelpers.ps1
  Helper compartido (dot-source) para generar una identidad ED25519 sin passphrase
  de forma compatible entre versiones de PowerShell/OpenSSH en Windows.

  No asume que una unica forma de invocar 'ssh-keygen -N ...' funciona en todas las
  combinaciones: intenta la forma primaria y VERIFICA el resultado real (que la
  clave privada generada efectivamente no pida passphrase, via 'ssh-keygen -y -P ""'
  sin bloquear en un prompt); si la verificacion falla, reintenta con una forma
  alternativa antes de rendirse.
#>

function New-OttoGuideEd25519KeyNoPassphrase {
  param(
    [Parameter(Mandatory = $true)][string]$KeyPath,
    [Parameter(Mandatory = $true)][string]$Comment
  )
  $ErrorActionPreference = 'Stop'
  $pubPath = "$KeyPath.pub"

  function Test-KeyHasNoPassphrase([string]$path) {
    # 'ssh-keygen -y -P ""' deriva la clave publica desde la privada usando una
    # passphrase vacia explicita; si la clave SI tiene passphrase, esto falla con
    # rc!=0 en vez de quedarse esperando input interactivo (no bloquea).
    $derived = & cmd /c "ssh-keygen -y -f `"$path`" -P `"`" 2>nul"
    return ($LASTEXITCODE -eq 0 -and $derived)
  }

  # Intento 1: '-N' con comilla vacia literal (forma validada en Windows OpenSSH
  # reciente + PowerShell 5.1: el shell nativo la pasa como passphrase vacia).
  Remove-Item $KeyPath -Force -ErrorAction SilentlyContinue
  Remove-Item $pubPath -Force -ErrorAction SilentlyContinue
  & ssh-keygen -t ed25519 -f $KeyPath -N '""' -C $Comment | Out-Null
  $attempt1Ok = ($LASTEXITCODE -eq 0 -and (Test-Path $KeyPath) -and (Test-Path $pubPath) -and (Test-KeyHasNoPassphrase $KeyPath))

  if ($attempt1Ok) {
    Write-Host "[keygen] Identidad generada sin passphrase (forma primaria): $KeyPath"
    return
  }

  Write-Warning "[keygen] Forma primaria de ssh-keygen no verifico 'sin passphrase'; reintentando con forma alternativa (cmd /c aislado)."

  # Intento 2: aislar completamente via cmd /c con comillas escapadas para el shell
  # de cmd.exe, evitando cualquier reinterpretacion de argumentos por PowerShell.
  Remove-Item $KeyPath -Force -ErrorAction SilentlyContinue
  Remove-Item $pubPath -Force -ErrorAction SilentlyContinue
  & cmd /c "ssh-keygen -t ed25519 -f `"$KeyPath`" -N `"`" -C `"$Comment`"" | Out-Null
  $attempt2Ok = ($LASTEXITCODE -eq 0 -and (Test-Path $KeyPath) -and (Test-Path $pubPath) -and (Test-KeyHasNoPassphrase $KeyPath))

  if (-not $attempt2Ok) {
    throw "No se pudo generar una identidad ED25519 verificablemente sin passphrase en $KeyPath tras 2 intentos (formas de ssh-keygen incompatibles con este entorno)."
  }
  Write-Host "[keygen] Identidad generada sin passphrase (forma alternativa cmd /c): $KeyPath"
}
