// NB-HIL-WEB-R0A FASE H — combinacion ordenada de backfill + live (modulo PURO, testeable).
//
// Durante una reconexion se bufferizan los frames live que llegan mientras el GET
// /telemetry/backfill esta en vuelo. Al resolverse, se combinan backfill + buffer live,
// se deduplican por session_id+seq y se ordenan por seq ascendente antes de emitir; luego
// continua el stream live normal.

export function frameKey(f) {
  const sid = f?.session_id ?? f?.sessionId ?? null
  const seq = f?.seq ?? null
  return sid != null && seq != null ? `${sid}#${seq}` : null
}

// Combina y ordena. `seen` es un Set de claves ya emitidas (se respeta y se actualiza).
// Devuelve { ordered, seen }. Frames sin clave (session/seq ausentes) se conservan al final
// en su orden de llegada (no se pueden deduplicar ni ordenar por seq).
export function mergeAndOrder({ backfill = [], live = [], seen = new Set() } = {}) {
  const nextSeen = new Set(seen)
  const keyed = []
  const unkeyed = []
  for (const f of [...backfill, ...live]) {
    if (!f || typeof f !== 'object') continue
    const k = frameKey(f)
    if (k == null) { unkeyed.push(f); continue }
    if (nextSeen.has(k)) continue // duplicado (solapamiento backfill/live o ya emitido)
    nextSeen.add(k)
    keyed.push(f)
  }
  keyed.sort((a, b) => {
    const sa = String(a.session_id ?? a.sessionId ?? '')
    const sb = String(b.session_id ?? b.sessionId ?? '')
    if (sa !== sb) return sa < sb ? -1 : 1
    return (a.seq ?? 0) - (b.seq ?? 0)
  })
  return { ordered: [...keyed, ...unkeyed], seen: nextSeen }
}
