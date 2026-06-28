import { useEffect, useState } from 'react'
import { Wifi, WifiOff, FlaskConical } from 'lucide-react'

const STATE_TEXT = {
  mock: 'Simulacion', connecting: 'Conectando…', connected: 'Conectado',
  polling: 'Conectado (polling)', reconnecting: 'Reconectando…', error: 'Sin conexion',
}

export default function ConnectionBar({ mockMode, onToggleMock, baseUrl, onChangeBaseUrl, connState }) {
  const [draft, setDraft] = useState(baseUrl)
  useEffect(() => setDraft(baseUrl), [baseUrl])

  const live = connState === 'connected' || connState === 'polling' || connState === 'mock'

  return (
    <div className="conn-bar">
      <label className="toggle">
        <input type="checkbox" checked={mockMode} onChange={(e) => onToggleMock(e.target.checked)} />
        <FlaskConical size={15} /> Modo simulacion
      </label>

      <div className={`conn-state ${live ? 'is-live' : 'is-down'}`}>
        {live ? <Wifi size={15} /> : <WifiOff size={15} />}
        {STATE_TEXT[connState] || connState}
      </div>

      <div className="url-field" title={mockMode ? 'Desactiva la simulacion para usar el robot' : ''}>
        <span className="url-label">Robot</span>
        <input
          type="text"
          value={draft}
          disabled={mockMode}
          spellCheck={false}
          onChange={(e) => setDraft(e.target.value)}
          onBlur={() => onChangeBaseUrl(draft.trim())}
          onKeyDown={(e) => { if (e.key === 'Enter') onChangeBaseUrl(draft.trim()) }}
          placeholder="http://192.168.123.164:3000"
        />
      </div>
    </div>
  )
}
