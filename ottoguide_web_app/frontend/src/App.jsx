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
import ErrorBoundary from './components/ErrorBoundary.js'

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
  // Perfil "real": ignora localStorage de mock previo (nunca hereda un mock=true guardado
  // de una sesion development anterior) y el toggle queda bloqueado en Header/config.
  const [mockMode, setMockMode] = useState(() =>
    config.deploymentProfile === 'real' ? false : loadPref('otto_mock', config.mockMode)
  )
  const [baseUrl, setBaseUrl] = useState(() => loadPref('otto_url', config.robotBaseUrl))
  const [tab, setTab] = useState('graficos') // 'tabla' | 'graficos'

  useEffect(() => {
    if (config.deploymentProfile !== 'real') savePref('otto_mock', mockMode)
  }, [mockMode])
  useEffect(() => savePref('otto_url', baseUrl), [baseUrl])

  const { frame, history, connState } = useTelemetry({ mockMode, baseUrl })
  const { status, setStatus, refresh, apiReachable } = useRobotStatus({ mockMode, baseUrl })

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
        <EnergyCard frame={frame} mockMode={mockMode} />
        <BatteryCard frame={frame} mockMode={mockMode} />
        <ImuCard frame={frame} mockMode={mockMode} />
        <FootForceCard frame={frame} mockMode={mockMode} />
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
          {!mockMode && (
            <p className="panel-not-available">
              Telemetria rica (motores/graficos) no disponible en el contrato actual del backend canonico.
              Mostrando ultimos datos conocidos (probablemente vacios fuera de mock mode).
            </p>
          )}
          <ErrorBoundary label={tab === 'tabla' ? 'Tabla de motores' : 'Graficos en tiempo real'}>
            {tab === 'tabla'
              ? <MotorsTable motors={frame?.motors} />
              : <ChartsGrid history={history} />}
          </ErrorBoundary>
        </div>
      </section>

      <ControlPanel
        mockMode={mockMode}
        baseUrl={baseUrl}
        status={status}
        apiReachable={apiReachable}
        setStatus={setStatus}
        refresh={refresh}
      />

      <footer className="app-foot">
        OttoGuide · Unitree G1-EDU · companion PC :8000 (FastAPI canonico) · frontend notebook :3001
      </footer>
    </div>
  )
}
