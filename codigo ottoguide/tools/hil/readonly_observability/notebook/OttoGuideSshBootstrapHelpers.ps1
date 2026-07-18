<#
  WEB-HIL-R1B — OttoGuideSshBootstrapHelpers.ps1
  Helper compartido (dot-source) con la logica REAL de seleccion de candidato SSH por
  fingerprint, extraida de Resolve-OttoGuideTarget.ps1 para que un unico punto de verdad
  sea usado tanto en produccion como en el test offline (Test-SshBootstrapLogic.ps1) --
  nunca un selector paralelo que solo "imite la idea".
#>

function Select-OttoGuideVerifiedCandidate {
  <#
    Recibe una lista de candidatos (cada uno con al menos 'target' y opcionalmente
    'fingerprint') y el fingerprint esperado. Devuelve UNICAMENTE el primer candidato
    (en el orden recibido, que replica el orden real de recorrido adaptador-por-
    adaptador/vecino-por-vecino) cuyo fingerprint coincide EXACTAMENTE con el esperado.

    Reglas:
      - Un candidato sin 'fingerprint' (clave no obtenida, $null o cadena vacia) NUNCA
        matchea, sin importar el valor esperado.
      - Si 'ExpectedFingerprint' esta vacio/$null, no hay match posible (fail-closed).
      - Si multiples candidatos comparten el mismo fingerprint (duplicado), se devuelve
        el PRIMERO en el orden recibido (mismo criterio determinista que produccion:
        primer match en el orden de recorrido, nunca ambiguo).
      - No es sensible al orden de iteracion salvo por el propio orden de la lista
        recibida (no reordena, no prioriza por interfaz/adaptador).
  #>
  param(
    [Parameter(Mandatory = $true)][AllowEmptyCollection()][array]$Candidates,
    [Parameter(Mandatory = $true)][AllowEmptyString()][AllowNull()][string]$ExpectedFingerprint
  )
  if ([string]::IsNullOrEmpty($ExpectedFingerprint)) { return $null }
  foreach ($c in $Candidates) {
    $fp = $null
    if ($c.PSObject.Properties.Match('fingerprint').Count -gt 0) { $fp = $c.fingerprint }
    if ([string]::IsNullOrEmpty($fp)) { continue }
    if ($fp -eq $ExpectedFingerprint) { return $c }
  }
  return $null
}
