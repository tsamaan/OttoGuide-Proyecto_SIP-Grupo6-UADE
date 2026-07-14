import { Component, createElement } from 'react'

// Defensa en profundidad para paneles de telemetria. Si un panel hijo lanza durante el
// render (p. ej. un campo del contrato del backend que cambie en el futuro y no este
// contemplado), el ErrorBoundary muestra un fallback local en lugar de derribar toda la
// aplicacion (Header, tarjetas de estado y ControlPanel siguen vivos porque quedan fuera
// del boundary en App.jsx). No sustituye datos ni activa mock: solo aisla el fallo.
//
// Escrito con createElement (sin JSX) para que sea un modulo .js puro, importable tanto por
// el build de Vite como por los tests de node:test (que no transforman JSX).
export default class ErrorBoundary extends Component {
  constructor(props) {
    super(props)
    this.state = { hasError: false, message: '' }
  }

  static getDerivedStateFromError(error) {
    return { hasError: true, message: error?.message ? String(error.message) : 'render error' }
  }

  componentDidCatch(error, info) {
    // eslint-disable-next-line no-console
    console.error('[ErrorBoundary] panel de telemetria fallo:', error, info)
  }

  render() {
    if (this.state.hasError) {
      const label = this.props.label || 'Panel de telemetria'
      return createElement(
        'div',
        { className: 'charts-panel' },
        createElement(
          'div',
          { className: 'charts-empty' },
          `${label} no disponible: el contenido fallo al renderizar y se aislo para no ` +
            'afectar el resto de la interfaz.'
        )
      )
    }
    return this.props.children
  }
}
