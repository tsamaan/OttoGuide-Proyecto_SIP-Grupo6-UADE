# WEB-R6: launcher no-robot (Windows) para el backend FastAPI cuando se opera junto a la
# UI canonica (ottoguide_web_app/frontend, Vite :3001) en topologia notebook local.
# Este script NO se autoejecuta; el operador lo invoca explicitamente con `pwsh`.
# No ejecutar automaticamente desde ningun hook, CI, u otro script de este repo.

$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$BackendDir = Split-Path -Parent $ScriptDir

if (-not $env:PYTHON_BIN) {
    $env:PYTHON_BIN = "python3.10"
}
if (-not $env:API_PORT) {
    $env:API_PORT = "8000"
}

Remove-Item Env:\RMW_IMPLEMENTATION -ErrorAction SilentlyContinue
Remove-Item Env:\CYCLONEDDS_URI -ErrorAction SilentlyContinue
Remove-Item Env:\ROBOT_NETWORK_INTERFACE -ErrorAction SilentlyContinue

$env:ROBOT_MODE = "mock"
$env:NAVIGATION_BACKEND = "stub"
$env:NAVIGATION_ALLOW_STUB_TOURS = "false"
$env:QR_STATION_TRIGGER_ENABLED = "false"

# WEB-R6: la UI canonica es ottoguide_web_app/frontend (Vite :3001). Estas dos variables
# son la fuente de verdad para que "/" y "/dashboard" redirijan a React (WEB_UI_PUBLIC_URL)
# y para que CORS/WS acepten el origen real del frontend (WEB_UI_ALLOWED_ORIGINS).
if (-not $env:WEB_UI_ALLOWED_ORIGINS) {
    $env:WEB_UI_ALLOWED_ORIGINS = "http://localhost:3001,http://127.0.0.1:3001"
}
if (-not $env:WEB_UI_PUBLIC_URL) {
    $env:WEB_UI_PUBLIC_URL = "http://127.0.0.1:3001"
}

Set-Location $BackendDir

Write-Output "[start_web_backend_mock_py310] PYTHON_BIN=$($env:PYTHON_BIN)"
Write-Output "[start_web_backend_mock_py310] BACKEND_DIR=$BackendDir"
Write-Output "[start_web_backend_mock_py310] ROBOT_MODE=$($env:ROBOT_MODE)"
Write-Output "[start_web_backend_mock_py310] API_PORT=$($env:API_PORT)"
Write-Output "[start_web_backend_mock_py310] WEB_UI_ALLOWED_ORIGINS=$($env:WEB_UI_ALLOWED_ORIGINS)"
Write-Output "[start_web_backend_mock_py310] WEB_UI_PUBLIC_URL=$($env:WEB_UI_PUBLIC_URL)"
Write-Output "[start_web_backend_mock_py310] ROS/DDS/Unitree environment variables were unset."
Write-Output "[start_web_backend_mock_py310] Canonical UI: ottoguide_web_app/frontend (npm run dev, port 3001)."

# Este script deja el entorno listo pero NO invoca python/uvicorn automaticamente
# como parte de este checkpoint (WEB-R6 prohibe ejecutar runtime). El operador debe
# ejecutar manualmente, en una sesion futura autorizada:
#   & $env:PYTHON_BIN main.py
Write-Output "[start_web_backend_mock_py310] Entorno preparado. Ejecucion manual requerida: & `$env:PYTHON_BIN main.py"
