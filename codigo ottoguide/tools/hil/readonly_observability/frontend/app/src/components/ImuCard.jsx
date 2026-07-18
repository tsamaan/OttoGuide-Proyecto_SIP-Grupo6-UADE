import { Compass } from 'lucide-react'
import MetricCard, { MetricRow } from './MetricCard.jsx'

const f2 = (n) => (typeof n === 'number' ? n.toFixed(2) : '—')
const f3 = (n) => (typeof n === 'number' ? n.toFixed(3) : '—')

// C3: la card de IMU se muestra solo con muestra valida (al menos un vector rpy/accel/gyro
// con numeros). Sin muestra valida devuelve null.
function hasValidImu(imu) {
  if (!imu || typeof imu !== 'object') return false
  const vecs = [imu.rpy_deg, imu.accelerometer, imu.gyroscope]
  return vecs.some((v) => Array.isArray(v) && v.some((x) => typeof x === 'number'))
}

export default function ImuCard({ frame }) {
  const imu = frame?.imu || {}
  const avail = frame?.availability || {}
  const notAvailable = !(hasValidImu(imu) && avail.imu !== false)
  const rpy = imu.rpy_deg || [null, null, null]
  const acc = imu.accelerometer || [null, null, null]
  const gyr = imu.gyroscope || [null, null, null]
  return (
    <MetricCard title="IMU - Orientacion" icon={<Compass size={18} />} notAvailable={notAvailable}>
      <MetricRow label="Roll" value={typeof rpy[0] === 'number' ? rpy[0].toFixed(1) : '—'} unit="°" />
      <MetricRow label="Pitch" value={typeof rpy[1] === 'number' ? rpy[1].toFixed(1) : '—'} unit="°" />
      <MetricRow label="Yaw" value={typeof rpy[2] === 'number' ? rpy[2].toFixed(1) : '—'} unit="°" />
      <MetricRow label="Aceleracion" value={`x ${f2(acc[0])}  y ${f2(acc[1])}  z ${f2(acc[2])}`} unit="m/s²" />
      <MetricRow label="Giroscopio" value={`x ${f3(gyr[0])}  y ${f3(gyr[1])}  z ${f3(gyr[2])}`} unit="rad/s" />
    </MetricCard>
  )
}
