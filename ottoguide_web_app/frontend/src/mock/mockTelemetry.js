// Generador de telemetria simulada en el navegador (modo simulacion del front).
// Permite usar el panel sin backend ni robot. Espeja al mock del backend.
import { G1_JOINT_MAP } from '../data/jointMaps.js'

const ENTRIES = Object.entries(G1_JOINT_MAP).map(([idx, info]) => ({
  index: Number(idx),
  name: info.name,
  group: info.group,
}))
const NUM = ENTRIES.length

let start = performance.now()
const base = ENTRIES.map(() => (Math.random() * 30 - 15))

export function resetMock() {
  start = performance.now()
}

export function mockFrame() {
  const elapsed = (performance.now() - start) / 1000
  const t = elapsed
  const freq = 1.0

  const motors = ENTRIES.map((e, idx) => {
    const phase = idx * ((2 * Math.PI) / NUM)
    const tw = 2 * Math.PI * freq * t
    const angle = base[idx] + 10 * Math.sin(tw + phase)
    const vel = 10 * 2 * Math.PI * freq * Math.cos(tw + phase)
    const torque = 5 * Math.sin(tw + phase) + (Math.random() * 2 - 1)
    // La rodilla izquierda (idx 3) calienta un poco mas, para mostrar colores/alertas.
    const temp =
      idx === 3
        ? Math.round(44 + 6 * Math.sin(elapsed / 8) + (Math.random() * 2 - 1))
        : Math.round(30 + Math.random() * 11)
    return {
      index: e.index,
      name: e.name,
      group: e.group,
      q_rad: +(angle * Math.PI / 180).toFixed(4),
      q_deg: +angle.toFixed(2),
      dq: +vel.toFixed(4),
      ddq: 0,
      tau_est: +torque.toFixed(4),
      temperature: temp,
    }
  })

  const v = +(27.5 + (Math.random() * 0.6 - 0.3)).toFixed(2)
  const a = +(3.5 + (Math.random() * 1.0 - 0.5)).toFixed(2)
  const r = (n) => +(Math.random() * 2 * n - n).toFixed(4)
  const cell = (b) => b + Math.round(Math.random() * 8 - 4)

  return {
    robot: 'G1',
    timestamp: Date.now() / 1000,
    power_v: v,
    power_a: a,
    motors,
    imu: {
      quaternion: [1, 0, 0, 0],
      gyroscope: [r(0.05), r(0.05), r(0.05)],
      accelerometer: [r(0.3), r(0.3), +(9.8 + r(0.05)).toFixed(4)],
      rpy_deg: [+(r(3)).toFixed(2), +(r(3)).toFixed(2), +(r(10)).toFixed(2)],
    },
    foot_force: [0, 1, 2, 3].map(() => Math.round(15 + Math.random() * 40)),
    bms: {
      soc: Math.max(0, 75 - Math.floor(elapsed / 60)),
      cycle: 20,
      current: -3500,
      status: 0,
      mcu_ntc: [30, 31],
      bq_ntc: [29, 30],
      cell_vol: [cell(3520), cell(3518), cell(3525), cell(3530), cell(3522), cell(3519)],
    },
  }
}
