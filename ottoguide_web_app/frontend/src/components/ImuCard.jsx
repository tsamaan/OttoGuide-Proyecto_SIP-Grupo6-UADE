import { Compass } from 'lucide-react'
import MetricCard, { MetricRow } from './MetricCard.jsx'

const f2 = (n) => (n != null ? n.toFixed(2) : '—')
const f3 = (n) => (n != null ? n.toFixed(3) : '—')

export default function ImuCard({ frame }) {
  const imu = frame?.imu || {}
  const rpy = imu.rpy_deg || [null, null, null]
  const acc = imu.accelerometer || [null, null, null]
  const gyr = imu.gyroscope || [null, null, null]
  return (
    <MetricCard title="IMU - Orientacion" icon={<Compass size={18} />}>
      <MetricRow label="Roll" value={rpy[0] != null ? rpy[0].toFixed(1) : '—'} unit="°" />
      <MetricRow label="Pitch" value={rpy[1] != null ? rpy[1].toFixed(1) : '—'} unit="°" />
      <MetricRow label="Yaw" value={rpy[2] != null ? rpy[2].toFixed(1) : '—'} unit="°" />
      <MetricRow label="Aceleracion" value={`x ${f2(acc[0])}  y ${f2(acc[1])}  z ${f2(acc[2])}`} unit="m/s²" />
      <MetricRow label="Giroscopio" value={`x ${f3(gyr[0])}  y ${f3(gyr[1])}  z ${f3(gyr[2])}`} unit="rad/s" />
    </MetricCard>
  )
}
