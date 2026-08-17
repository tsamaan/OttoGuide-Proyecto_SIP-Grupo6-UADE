<#
  WEB-HIL-R1B — OttoGuideSshBootstrapHelpers.ps1
  Helper compartido (dot-source) con la logica REAL de seleccion de candidato SSH por
  fingerprint, extraida de Resolve-OttoGuideTarget.ps1 para que un unico punto de verdad
  sea usado tanto en produccion como en el test offline (Test-SshBootstrapLogic.ps1) --
  nunca un selector paralelo que solo "imite la idea".
#>

function Select-OttoGuideVerifiedCandidate {
  <#
    WEB-HIL-R2E: recibe una lista de candidatos (cada uno con al menos 'target' y
    opcionalmente 'fingerprint'/'interface'/'ifindex') y el fingerprint esperado.
    Devuelve SIEMPRE un objeto de estado (nunca directamente un candidato o $null),
    para que el llamador distinga fail-closed por ambiguedad de fail-closed por
    ausencia de match:

      Status = 'MATCHED'                        -> Candidate tiene el candidato elegido
      Status = 'NO_MATCH'                        -> ningun candidato matchea el fingerprint
      Status = 'AMBIGUOUS'                        -> mas de un candidato matchea SIN
                                                      preferencia de interfaz/ifIndex dada
                                                      (Matches tiene todos los ambiguos)
      Status = 'PREFERENCE_NOT_FOUND'             -> se dio PreferredInterfaceAlias y/o
                                                      PreferredIfIndex pero ningun
                                                      candidato observado coincide con esa
                                                      preferencia (adaptador ausente o sin
                                                      vecinos)
      Status = 'PREFERENCE_FINGERPRINT_MISMATCH'  -> la preferencia SI resolvio candidato(s)
                                                      pero ninguno tiene el fingerprint
                                                      esperado

    Reglas:
      - Un candidato sin 'fingerprint' (clave no obtenida, $null o cadena vacia) NUNCA
        matchea, sin importar el valor esperado.
      - Si 'ExpectedFingerprint' esta vacio/$null, no hay match posible (fail-closed).
      - Con PreferredInterfaceAlias y/o PreferredIfIndex: se filtra PRIMERO a los
        candidatos que coincidan con esa preferencia (ambos, si se dan los dos), y
        SOLO dentro de ese subconjunto se exige fingerprint -- nunca se considera un
        candidato fuera de la preferencia dada, aunque matchee el fingerprint.
      - Sin preferencia: se recolectan TODOS los candidatos cuyo fingerprint matchea.
        Un unico match -> se acepta. Cero matches -> NO_MATCH. Mas de un match ->
        AMBIGUOUS (fail-closed) -- NUNCA se elige el primero de una lista ambigua.
  #>
  param(
    [Parameter(Mandatory = $true)][AllowEmptyCollection()][array]$Candidates,
    [Parameter(Mandatory = $true)][AllowEmptyString()][AllowNull()][string]$ExpectedFingerprint,
    [string]$PreferredInterfaceAlias,
    [System.Nullable[int]]$PreferredIfIndex
  )

  function OG_HasFingerprintMatch($c, $expected) {
    $fp = $null
    if ($c.PSObject.Properties.Match('fingerprint').Count -gt 0) { $fp = $c.fingerprint }
    (-not [string]::IsNullOrEmpty($fp)) -and ($fp -eq $expected)
  }

  $result = [ordered]@{ Status = 'NO_MATCH'; Candidate = $null; Matches = @() }
  if ([string]::IsNullOrEmpty($ExpectedFingerprint)) { return [pscustomobject]$result }

  $hasPreference = (-not [string]::IsNullOrEmpty($PreferredInterfaceAlias)) -or ($null -ne $PreferredIfIndex)

  if ($hasPreference) {
    $preferredPool = @($Candidates | Where-Object {
      $ifaceOk = $true
      if (-not [string]::IsNullOrEmpty($PreferredInterfaceAlias)) {
        $ifaceOk = ($_.PSObject.Properties.Match('interface').Count -gt 0) -and ($_.interface -eq $PreferredInterfaceAlias)
      }
      $idxOk = $true
      if ($null -ne $PreferredIfIndex) {
        $idxOk = ($_.PSObject.Properties.Match('ifindex').Count -gt 0) -and ($_.ifindex -eq $PreferredIfIndex)
      }
      $ifaceOk -and $idxOk
    })
    if ($preferredPool.Count -eq 0) {
      $result.Status = 'PREFERENCE_NOT_FOUND'
      return [pscustomobject]$result
    }
    $preferredMatched = @($preferredPool | Where-Object { OG_HasFingerprintMatch $_ $ExpectedFingerprint })
    if ($preferredMatched.Count -eq 0) {
      $result.Status = 'PREFERENCE_FINGERPRINT_MISMATCH'
      return [pscustomobject]$result
    }
    $result.Status = 'MATCHED'
    $result.Candidate = $preferredMatched[0]
    $result.Matches = $preferredMatched
    return [pscustomobject]$result
  }

  $matched = @($Candidates | Where-Object { OG_HasFingerprintMatch $_ $ExpectedFingerprint })
  if ($matched.Count -eq 0) {
    $result.Status = 'NO_MATCH'
  } elseif ($matched.Count -eq 1) {
    $result.Status = 'MATCHED'
    $result.Candidate = $matched[0]
  } else {
    $result.Status = 'AMBIGUOUS'
    $result.Matches = $matched
  }
  return [pscustomobject]$result
}
