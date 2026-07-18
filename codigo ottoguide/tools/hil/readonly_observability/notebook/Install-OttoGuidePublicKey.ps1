<#
  WEB-HIL-R1B — Install-OttoGuidePublicKey.ps1
  Instala idempotentemente la clave publica local en ~/.ssh/authorized_keys del
  Companion. Abre UNA sesion SSH interactiva visible; el operador escribe la
  contrasena manualmente en el prompt nativo de OpenSSH.

  Este script NUNCA acepta la contrasena como parametro, no usa sshpass, no la
  lee, no la registra y no la guarda. No asume que ssh-copy-id existe en Windows
  (no se usa).

  Requiere que la host key ya este pineada (Write-OttoGuideHostKeyPin.ps1) ANTES
  de esta sesion interactiva: usa EXCLUSIVAMENTE el alias 'ottoguide' del config
  generado (generated_target.conf), nunca 'usuario@IP' directo, para que la
  verificacion de host key pase siempre por el known_hosts dedicado
  (StrictHostKeyChecking yes) y no por el known_hosts global del usuario.

  FASE E (WEB-HIL-R1B): el transporte por stdin ('$payload | ssh ... "sh -s"') se
  elimino. Ocupar stdin no esta demostrado como seguro/portable junto al prompt
  interactivo nativo de OpenSSH (que TAMBIEN necesita leer de la terminal), y el
  encoding/CRLF de PowerShell hacia el pipe no estaba cubierto por ningun test. Ahora
  TANTO el script remoto fijo COMO la clave publica se codifican en Base64 (alfabeto
  seguro A-Z a-z 0-9 + / =, sin caracteres que un shell pueda reinterpretar) y se pasan
  como argumentos LITERALES del comando remoto (nunca por stdin), dejando el stdin de
  la sesion SSH completamente libre para el prompt de contrasena nativo. El script
  remoto decodifica ambos valores del lado remoto; la clave publica decodificada NUNCA
  se interpola en el texto del comando (solo se compara/imprime via variables de shell
  ya pobladas), por lo que un comentario de clave con espacios o caracteres especiales
  no puede alterar el shell remoto.
#>
param(
  [string]$SshRoot = 'C:\OG\OttoGuide-SSH',
  [string]$IdentityName = 'id_ed25519_ottoguide_robot',
  [string]$RemoteUser = 'unitree',
  [string]$ExpectedFingerprint
)
$ErrorActionPreference = 'Stop'
$here = $PSScriptRoot

$sshDir = Join-Path $env:USERPROFILE '.ssh'
$pubPath = Join-Path $sshDir "$IdentityName.pub"
if (-not (Test-Path $pubPath)) { throw "No existe $pubPath (corre Bootstrap-OttoGuideNotebook.ps1 primero para generar la identidad)." }
$pub = (Get-Content $pubPath -Raw).Trim()
if ($pub -match "[`r`n]") { throw "La clave publica leida contiene saltos de linea inesperados; abortando por seguridad." }

# Orden obligatorio: resolver target -> pinear host key -> generar config. Nunca se
# conecta directo a 'usuario@IP': todo pasa por el alias 'ottoguide' del config
# generado, que fuerza StrictHostKeyChecking contra el known_hosts dedicado.
& (Join-Path $here 'Resolve-OttoGuideTarget.ps1') -SshRoot $SshRoot -ExpectedFingerprint $ExpectedFingerprint | Out-Null
& (Join-Path $here 'Write-OttoGuideHostKeyPin.ps1') -SshRoot $SshRoot | Out-Null
& (Join-Path $here 'Write-OttoGuideSshConfig.ps1') -SshRoot $SshRoot -IdentityName $IdentityName -RemoteUser $RemoteUser | Out-Null
$genConf = Join-Path $SshRoot 'generated_target.conf'

Write-Host "[install-key] Fingerprint de la clave publica a instalar:"
& ssh-keygen -lf $pubPath

# Comando remoto fail-closed, sin precedencia ambigua de '&&'/'||' y SIN depender del
# stdin de la sesion SSH (que debe quedar libre para el prompt de contrasena nativo).
# El script fijo de instalacion y la clave publica viajan AMBOS como literales Base64
# en el propio texto del comando (alfabeto seguro A-Z a-z 0-9 + / =); el lado remoto
# decodifica ambos con 'base64 -d' y ejecuta el script via 'sh -s' alimentado por un
# 'printf' local (no por la terminal), nunca interpolando la clave publica decodificada
# directamente en texto de shell. 'set -eu' hace que cualquier paso fallido aborte con
# exit != 0 en vez de seguir silenciosamente.
$remoteScript = @'
set -eu
PUBLIC_KEY=$(printf '%s' "$PUBLIC_KEY_B64" | base64 -d)
mkdir -p "$HOME/.ssh"
chmod 700 "$HOME/.ssh"
touch "$HOME/.ssh/authorized_keys"
if ! grep -qxF -- "$PUBLIC_KEY" "$HOME/.ssh/authorized_keys"; then
    printf '%s\n' "$PUBLIC_KEY" >> "$HOME/.ssh/authorized_keys"
fi
chmod 600 "$HOME/.ssh/authorized_keys"
grep -qxF -- "$PUBLIC_KEY" "$HOME/.ssh/authorized_keys"
printf '%s\n' INSTALADO_OK
'@
$pubBase64 = [Convert]::ToBase64String([System.Text.Encoding]::UTF8.GetBytes($pub))
$scriptBase64 = [Convert]::ToBase64String([System.Text.Encoding]::UTF8.GetBytes($remoteScript))
# El comando remoto en si NO contiene la clave publica ni el script en texto plano:
# solo dos literales Base64 (solo caracteres A-Z a-z 0-9 + / =) y una tuberia fija.
# PUBLIC_KEY_B64 se exporta como variable de entorno remota para que el script
# decodificado (via el segundo Base64) la lea sin que el propio valor de la clave
# pase nunca por el texto del comando de nivel superior.
#
# IMPORTANTE: el string se construye SIN ninguna comilla doble embebida. PowerShell
# marshalling de argumentos nativos (ssh.exe) NO preserva '"..."' como una unidad si
# el string ya contiene comillas dobles internas -- las reinterpreta y fragmenta el
# argumento en varios (verificado empiricamente: un argv de una sola cadena con "..."
# interno llega a un proceso hijo nativo partido en tokens por espacio). Usando
# EXCLUSIVAMENTE comillas simples en la sintaxis de shell remoto (validas en sh/bash
# para strings sin comillas simples adentro, y el alfabeto Base64 nunca las tiene),
# el argumento completo llega intacto como un unico elemento de argv a ssh.exe.
$remoteCommand = "PUBLIC_KEY_B64='$pubBase64' sh -c 'printf %s $scriptBase64 | base64 -d | sh -s'"

Write-Host "[install-key] Abriendo sesion SSH interactiva a alias 'ottoguide' (target resuelto y host key pineada)..."
Write-Host "[install-key] Cuando OpenSSH pida la contrasena, escribila en ESTA terminal (el agente no la ve ni la registra)."
Write-Host "[install-key] El stdin de esta sesion SSH queda libre para el prompt (WEB-HIL-R1B: sin transporte por stdin)."
& ssh -F $genConf ottoguide $remoteCommand
if ($LASTEXITCODE -ne 0) { throw "Instalacion de la clave publica fallo (rc=$LASTEXITCODE)." }

Write-Host "[install-key] Listo. Verificando auth por clave (BatchMode, alias 'ottoguide-batch')..."
& ssh -F $genConf ottoguide-batch "echo BATCH_AUTH_OK"
if ($LASTEXITCODE -ne 0) { throw "BatchMode fallo despues de instalar la clave publica (rc=$LASTEXITCODE); revisar host key / permisos. Instalacion NO confirmada (fail-closed)." }
Write-Host "[install-key] BATCH_AUTH = PASS"
