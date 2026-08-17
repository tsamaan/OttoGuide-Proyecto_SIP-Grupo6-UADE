import { useState } from 'react'
import { useTelemetry } from './hooks/useTelemetry.js'
import Header from './components/Header.jsx'
import AlertBanner from './components/AlertBanner.jsx'
import EnergyCard from './components/EnergyCard.jsx'
import BatteryCard from './components/BatteryCard.jsx'
import ImuCard from './components/ImuCard.jsx'
import MotorsTable from './components/MotorsTable.jsx'
import ChartsGrid from './components/ChartsGrid.jsx'
import LiveRobotSummary from './components/LiveRobotSummary.jsx'
import ErrorBoundary from './components/ErrorBoundary.js'

// NB-HIL-WEB-R0 (perfil real/replay): monitor fisico read-only.
// C2 — eliminados del DOM: banner "MONITOR EN VIVO — SOLO LECTURA", texto "Sin autoridad de
// movimiento", ControlPanel y todos sus botones (tour / interaccion / emergencia), toggle de
// simulacion y campo de URL editable. La seguridad reside en el bridge (405 a toda mutacion),
// no en un aviso visual. mockMode queda fijo en false: nunca se hereda un mock previo.
export default function App() {
  const [tab, setTab] = useState('graficos') // 'tabla' | 'graficos'
  const { frame, history, connState } = useTelemetry()

  return (
    <div className="app-shell">
      <Header connState={connState} />

      <AlertBanner motors={frame?.motors} />

      <LiveRobotSummary frame={frame} />

      <section className="cards-grid">
        {/* Cada card decide su propia disponibilidad y devuelve null si no hay dato validado.
            "Fuerza en patas" se oculta por completo (C3). */}
        <EnergyCard frame={frame} />
        <BatteryCard frame={frame} />
        <ImuCard frame={frame} />
      </section>

      <section className="panel">
        <div className="tabs">
          <button className={`tab ${tab === 'tabla' ? 'active' : ''}`} onClick={() => setTab('tabla')}>
            Tabla de motores
          </button>
          <button className={`tab ${tab === 'graficos' ? 'active' : ''}`} onClick={() => setTab('graficos')}>
            Graficos en tiempo real
          </button>
        </div>
        <div className="panel-body">
          <ErrorBoundary label={tab === 'tabla' ? 'Tabla de motores' : 'Graficos en tiempo real'}>
            {tab === 'tabla'
              ? <MotorsTable motors={frame?.motors} />
              : <ChartsGrid history={history} />}
          </ErrorBoundary>
        </div>
      </section>

      <footer className="app-foot">
        OttoGuide · Unitree G1-EDU · monitor fisico read-only · bridge 127.0.0.1:8000
      </footer>
    </div>
  )
}
