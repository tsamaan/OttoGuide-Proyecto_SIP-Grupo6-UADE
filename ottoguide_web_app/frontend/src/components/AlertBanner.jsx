import { AlertTriangle } from 'lucide-react'

// Banner de temperatura: rojo si algun motor >=60 C, naranja si >=40 C, oculto si todo OK.
export default function AlertBanner({ motors }) {
  if (!motors?.length) return null

  const hot = motors.filter((m) => m.temperature >= 60).map((m) => m.name)
  const warm = motors.filter((m) => m.temperature >= 40 && m.temperature < 60).map((m) => m.name)

  if (hot.length) {
    return (
      <div className="alert-banner is-critical">
        <AlertTriangle size={18} />
        <span>TEMPERATURA CRITICA (&ge;60 &deg;C): {hot.join(', ')}</span>
      </div>
    )
  }
  if (warm.length) {
    return (
      <div className="alert-banner is-warn">
        <AlertTriangle size={18} />
        <span>Temperatura elevada (&ge;40 &deg;C): {warm.join(', ')}</span>
      </div>
    )
  }
  return null
}
