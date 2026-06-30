# Objective

Comparar las carpetas `review-orchestrator-unification` y `pilar-web`, y actualizar el documento técnico Web (`documento-tecnico-ottoguide-web.html`) para reflejar la unificación en el orquestador, eliminando el backend web independiente y actualizando la información de los endpoints y procesos según la "Cápsula de Estado Universal".

## Propuesta de Cambios

### 1. Documentación (`documento-tecnico-ottoguide-web.html`)
Actualizaremos el documento para reflejar la decisión arquitectónica canónica:
- **Sección 2 (Repositorio y estructura):** Eliminar la referencia a `backend/app/` (puerto 3000) y `backend/docker-compose.yaml`. Mencionar que el backend canónico (FastAPI) provee los endpoints en el puerto 8000.
- **Sección 3 (Arquitectura general):** Cambiar el puerto del Robot Back de `:3000` a `:8000`.
- **Sección 4 (Flujo de datos):** Remover la referencia al fallback silencioso (`GET /telemetry`) para cumplir con la prohibición de fallbacks silenciosos en modo real.
- **Sección 5 (Flujo de control):** Eliminar la mención de `ProcessManager` (delegar efectos al `TourOrchestrator`). Reemplazar `/chat/start` con `/content/script`. 
- **Sección 6 (Contrato de API):**
  - Reemplazar endpoints históricos por los canónicos: `GET /content/script`, `POST /content/script/reload`, `POST /tour/start`, `POST /tour/pause`, `POST /emergency`, `GET /status`, `WS /ws/telemetry`.
  - Eliminar explícitamente `/chat/start` (interacción simulada en mock).
  - Eliminar `GET /telemetry` como fallback.
  - Actualizar la semántica de emergencia (`POST /emergency`) para detallar que usa `terminal_safe`, y responde con HTTP `200`, `503` (SERVICE_UNAVAILABLE) o `504` (GATEWAY_TIMEOUT).
- **Sección 10 (Modo mock vs. real):** Separar explícitamente el modo mock del real y documentar que no se permite fallback silencioso a stub en modo real (`SILENT_REAL_FALLBACK = PROHIBITED`).
- **Sección 11 (Configuración):** Actualizar el puerto por defecto de 3000 a 8000. Remover variables del backend web descartado.

### 2. Análisis y Comparación de Carpetas
Basado en el diff y la cápsula:
- **`pilar-web`** contenía un `backend/` propio que duplicaba el control y telemetría. Este se **descarta** completamente.
- El **frontend** de `pilar-web` se mantiene y se configura para apuntar al backend canónico (FastAPI en puerto 8000). 
- Emitiremos un resumen de las diferencias específicas (ej., en `App.jsx`, `config.js`) y confirmaremos que el código integrado en la rama `review-orchestrator-unification` es el que se utilizará como base para el frontend adaptado.

## User Review Required
> [!IMPORTANT]
> - ¿Estás de acuerdo con las modificaciones propuestas para el documento HTML? 
> - ¿Deseas que además de actualizar el HTML, realice modificaciones en el código de React del frontend de la rama de unificación para reflejar los nuevos endpoints (por ej. `config.js`, `robotApi.js`)?
