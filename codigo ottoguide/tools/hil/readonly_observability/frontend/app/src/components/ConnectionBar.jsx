import { Wifi, WifiOff } from 'lucide-react'
import { config } from '../config.js'

// NB-HIL-WEB-R0 (perfil real/replay): barra de conexion read-only.
// C2 — se eliminan del DOM: el checkbox "Modo simulacion" y el campo editable de URL.
// Solo se muestran el badge de perfil (REAL / REPLAY) y el estado de conexion, reducido a
// tres textos: Conectado | Reconectando | Sin conexion.
const STATE_TEXT = {
  connected: 'Conectado',
  connecting: 'Reconectando',
  reconnecting: 'Reconectando',
  error: 'Sin conexion',
}

export default function ConnectionBar({ connState }) {
  const live = connState === 'connected'
  const label = STATE_TEXT[connState] || 'Sin conexion'

  return (
    <div className="conn-bar">
      <span className={`pill profile-pill ${config.isReal ? 'profile-real' : 'profile-dev'}`}>
        {config.profileLabel}
      </span>
      <div className={`conn-state ${live ? 'is-live' : 'is-down'}`}>
        {live ? <Wifi size={15} /> : <WifiOff size={15} />}
        {label}
      </div>
    </div>
  )
}
