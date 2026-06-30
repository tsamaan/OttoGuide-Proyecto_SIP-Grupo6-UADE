import { useEffect, useState } from 'react'
import { config } from './config.js'
import { useTelemetry } from './hooks/useTelemetry.js'
import { useRobotStatus } from './hooks/useRobotStatus.js'
import Header from './components/Header.jsx'
import AlertBanner from './components/AlertBanner.jsx'
import EnergyCard from './components/EnergyCard.jsx'
import BatteryCard from './components/BatteryCard.jsx'
import ImuCard from './components/ImuCard.jsx'
import FootForceCard from './components/FootForceCard.jsx'
import MotorsTable from './components/MotorsTable.jsx'
import ChartsGrid from './components/ChartsGrid.jsx'
import ControlPanel from './components/ControlPanel.jsx'

// Preferencias guardadas (no son datos criticos: solo URL y modo).
function loadPref(key, fallback) {
  try {
    const v = localStorage.getItem(key)
    return v === null ? fallback : JSON.parse(v)
  } catch {
    return fallback
  }
}
function savePref(key, value) {
  try { localStorage.setItem(key, JSON.stringify(value)) } catch { /* ignore */ }
}

export default function App() {
  const [mockMode, setMockMode] = useState(() => loadPref('otto_mock', config.mockMode))
  const [baseUrl, setBaseUrl] = useState(() => loadPref('otto_url', config.robotBaseUrl))
  const [tab, setTab] = useState('graficos') // 'tabla' | 'graficos'

  useEffect(() => savePref('otto_mock', mockMode), [mockMode])
  useEffect(() => savePref('otto_url', baseUrl), [baseUrl])

  const { frame, history, connState } = useTelemetry({ mockMode, baseUrl })
  const { status, setStatus, refresh } = useRobotStatus({ mockMode, baseUrl })

  return (
    <div className="app-shell">
      <Header
        mockMode={mockMode}
        onToggleMock={setMockMode}
        baseUrl={baseUrl}
        onChangeBaseUrl={(u) => u && setBaseUrl(u)}
        connState={connState}
      />

      <AlertBanner motors={frame?.motors} />

      <section className="cards-grid">
        <EnergyCard frame={frame} />
        <BatteryCard frame={frame} />
        <ImuCard frame={frame} />
        <FootForceCard frame={frame} />
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
          {tab === 'tabla'
            ? <MotorsTable motors={frame?.motors} />
            : <ChartsGrid history={history} />}
        </div>
      </section>

      <ControlPanel
        mockMode={mockMode}
        baseUrl={baseUrl}
        status={status}
        setStatus={setStatus}
        refresh={refresh}
      />

      <footer className="app-foot">
        OttoGuide · Unitree G1-EDU · backend en el robot (puerto 8000) · front en notebook (puerto 3001)
      </footer>
    </div>
  )
}
