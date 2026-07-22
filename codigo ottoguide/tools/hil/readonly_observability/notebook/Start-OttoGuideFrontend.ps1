<#
  WEB-HIL-R1B — Start-OttoGuideFrontend.ps1 (portable)
  Sirve el build estatico de produccion en 127.0.0.1:<Port>. Solo loopback. Usa Python
  stdlib http.server (sin dependencias extra) -- una Notebook sin Node debe poder servir
  el build precompilado igual.

  FASE D (WEB-HIL-R1B): selector EXPLICITO de perfil ('real'|'replay'), sin default
  implicito ambiguo. real -> frontend/dist-real ; replay -> frontend/dist-replay (ver
  FASE C2: cada perfil tiene su propio directorio de build, nunca comparten 'dist/').
  Falla explicitamente si falta index.html en el directorio resuelto, y registra el
  perfil servido en frontend_pid.json para que no quede implicito cual build esta activo.
#>
param(
  [string]$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')),
  [string]$SshRoot = 'C:\OG\OttoGuide-SSH',
  [int]$Port = 5173,
  [ValidateSet('real', 'replay')]
  [string]$Profile = 'real'
)
$ErrorActionPreference = 'Stop'
$distDirName = if ($Profile -eq 'replay') { 'dist-replay' } else { 'dist-real' }
$dist = Join-Path $RepoRoot "frontend\$distDirName"
if (-not (Test-Path (Join-Path $dist 'index.html'))) {
  throw "No existe $dist\index.html (perfil '$Profile'). Corre 'npm run build:$Profile' en frontend/app primero."
}
$logDir = Join-Path $SshRoot 'logs'
$stateDir = Join-Path $SshRoot 'state'
foreach ($d in @($logDir, $stateDir)) { if (-not (Test-Path $d)) { New-Item -ItemType Directory -Path $d -Force | Out-Null } }

$py = (Get-Command python -ErrorAction SilentlyContinue).Source
if (-not $py) { $py = (Get-Command python3 -ErrorAction SilentlyContinue).Source }
if (-not $py) { throw "Python no encontrado para servir el frontend estatico." }

Write-Host "[frontend] Sirviendo $dist (perfil=$Profile) en http://127.0.0.1:$Port"
$p = Start-Process -FilePath $py -ArgumentList @('-m', 'http.server', "$Port", '--bind', '127.0.0.1') `
      -WorkingDirectory $dist -PassThru -NoNewWindow `
      -RedirectStandardError (Join-Path $logDir 'frontend_stderr.log') `
      -RedirectStandardOutput (Join-Path $logDir 'frontend_stdout.log')
Set-Content -Encoding ascii (Join-Path $stateDir 'frontend_pid.json') (@{ frontend = $p.Id; port = $Port; profile = $Profile } | ConvertTo-Json)
Write-Host "[frontend] PID=$($p.Id) perfil=$Profile."
$p.Id
