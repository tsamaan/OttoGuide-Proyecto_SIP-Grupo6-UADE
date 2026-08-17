import { Bot } from 'lucide-react'
import ConnectionBar from './ConnectionBar.jsx'

// NB-HIL-WEB-R0 (perfil real): encabezado minimo. Solo marca + subtitulo fisico + estado.
// Sin toggle de simulacion, sin campo de URL editable (removidos del DOM en ConnectionBar).
export default function Header({ connState }) {
  return (
    <header className="topbar">
      <div className="brand">
        <span className="brand-mark"><Bot size={22} /></span>
        <div className="brand-text">
          <h1>OttoGuide</h1>
          <p>Telemetria fisica en tiempo real</p>
        </div>
      </div>
      <ConnectionBar connState={connState} />
    </header>
  )
}
