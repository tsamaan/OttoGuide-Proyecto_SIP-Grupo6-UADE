// NB-HIL-WEB-R0 (C5): resumen compacto de telemetria fisica read-only.
// La "Edad ult. frame" usa el tiempo real de recepcion del ultimo frame WebSocket
// (frame._recvMs), NO la edad del LiDAR. Un ticker de 1 Hz refresca esa edad aunque dejen
// de llegar frames (para que un enlace caido se note como edad creciente).
import { useEffect, useState } from 'react'
import { Activity } from 'lucide-react'

const fx = (n, d = 3) => (typeof n === 'number' ? n.toFixed(d) : '—')

export default function LiveRobotSummary({ frame }) {
  const [, tick] = useState(0)
  useEffect(() => {
    const id = setInterval(() => tick((n) => n + 1), 1000)
    return () => clearInterval(id)
  }, [])

  const motors = frame?.motors ?? []
  const rates = frame?.rates ?? {}
  const odom = frame?.odom ?? {}
  const lidar = frame?.lidar ?? {}
  const pos = odom.position ?? []
  const vel = odom.velocity ?? []
  const temps = motors.map((m) => m.temperature).filter((t) => typeof t === 'number')
  const maxTemp = temps.length ? Math.max(...temps) : null

  // Edad real del ultimo frame WS (segundos). null si aun no llego ninguno.
  const frameAgeS = typeof frame?._recvMs === 'number'
    ? Math.max(0, (Date.now() - frame._recvMs) / 1000)
    : null

  const items = [
    ['LowState Hz', fx(rates.lowstate_hz, 1)],
    ['Odom Hz', fx(rates.odom_hz, 1)],
    ['LF Odom Hz', fx(rates.lf_odom_hz, 1)],
    ['LiDAR Hz', fx(rates.lidar_hz, 1)],
    ['Motores', motors.length],
    ['Modo maquina', frame?.modeMachine ?? '—'],
    ['Temp max (°C)', maxTemp ?? '—'],
    ['Pos X / Y / Z', `${fx(pos[0])} / ${fx(pos[1])} / ${fx(pos[2])}`],
    ['Vel X / Y', `${fx(vel[0])} / ${fx(vel[1])}`],
    ['Yaw speed', fx(odom.yaw_speed, 4)],
    ['LiDAR puntos', typeof lidar.points === 'number' ? lidar.points.toLocaleString() : '—'],
    ['Edad ult. frame WS (s)', fx(frameAgeS, 2)],
  ]

  return (
    <section className="card" style={{ marginBottom: '1rem' }}>
      <header className="card-head">
        <span className="card-icon"><Activity size={18} /></span>
        <h3 className="card-title">Resumen de telemetria fisica</h3>
      </header>
      <div className="card-body" style={{ display: 'flex', flexWrap: 'wrap', gap: '0.75rem 1.5rem' }}>
        {items.map(([label, value]) => (
          <div key={label} className="metric-row" style={{ minWidth: '9rem' }}>
            <span className="metric-label">{label}</span>
            <span className="metric-value mono">{value}</span>
          </div>
        ))}
      </div>
    </section>
  )
}
