import { Bot } from 'lucide-react'
import ConnectionBar from './ConnectionBar.jsx'

export default function Header(props) {
  return (
    <header className="topbar">
      <div className="brand">
        <span className="brand-mark"><Bot size={22} /></span>
        <div className="brand-text">
          <h1>OttoGuide</h1>
          <p>Panel de control y metricas</p>
        </div>
      </div>
      <ConnectionBar {...props} />
    </header>
  )
}
