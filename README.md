# OttoGuide Proyect

### CO-Guia de las futuras visitas guiadas universitarias en UADE

---

## ¿Qué es OttoGuide?

OttoGuide integra un robot humanoide **Unitree G1 EDU** (llamado **Ottoman**) para realizar visitas guiadas autónomas en el campus Monserrat de la Universidad Argentina de la Empresa (UADE). El sistema guía a estudiantes secundarios a través del campus, responde preguntas sobre la universidad y presenta las instalaciones de forma interactiva.

El proyecto se divide en dos módulos que trabajan en conjunto:

| Módulo | Descripción | Responsable |
|---|---|---|
| **OttoGuide Autónomo** | Navegación, movimiento y control del robot en el campus | Lucas / Echezuria |
| **OttoGuide IA** | Sistema de conversación por voz — escucha, entiende y responde | Teo |

---

## Equipo

| Integrante | Rol |
|---|---|
| **Teo** | Líder técnico · IA · integración de sistemas |
| **Lucas** | Python · SDK Unitree · locomoción autónoma |
| **Erika** | Voz · diálogos · personalidad de Otto |
| **Jorge** | Testing · relevamiento físico del campus |
| **Martina** | Encuestas · análisis de usuarios |

---

## Estructura del repositorio

```
OttoGuide-Proyecto_SIP-Grupo6-UADE/
│
├── codigo ottoguide/              ← Módulo autónomo (locomoción + backend)
│   ├── src/
│   │   ├── core/                  ← Orquestador de misión (FSM)
│   │   ├── navigation/            ← Bridge con Nav2/ROS2
│   │   ├── interaction/           ← Conversación + audio
│   │   ├── hardware/              ← Abstracción del robot
│   │   └── infrastructure/        ← Cliente REST Unitree
│   ├── scripts/                   ← Scripts de operación HIL
│   ├── config/                    ← CycloneDDS, Nav2, settings
│   ├── deploy/                    ← Servicios systemd
│   └── main.py                    ← Entrada principal del backend
│
├── OttoGuide IA/                  ← Módulo de conversación con IA
│   ├── .claude/CLAUDE.md          ← Contexto para Claude Code
│   ├── docker-compose.yml         ← Stack: Ollama + Whisper + Piper
│   ├── services/
│   │   ├── core/main.py           ← Orquestador de voz (wake word → LLM → TTS)
│   │   ├── llm/Modelfile          ← Personalidad de Otto en Gemma4
│   │   └── tts/                   ← Piper TTS con voz masculina latinoamericana
│   └── documentacion/             ← Docs técnicos del módulo IA
│
├── documentacion general del proyecto/
│   ├── Interaccion/               ← Docs del módulo IA (planes, roadmap)
│   └── Movimiento/                ← Docs del módulo autónomo (RC1, HIL, ROS2)
│
├── planificacion/                 ← Cronogramas y entregas (V1, V2, V3)
├── TODO.md
└── README.md
```

---

## Módulo 1 — OttoGuide Autónomo

Sistema de navegación autónoma basado en **ROS2 + Nav2 + CycloneDDS**. El robot recibe rutas con waypoints del campus y navega de forma segura entre ellos.

**Stack tecnológico:**
- FastAPI (backend de control)
- ROS2 + Nav2 + AMCL (navegación y localización)
- CycloneDDS (comunicación entre procesos)
- SDK Unitree G1 EDU (control del hardware)
- Dashboard web en Vanilla JS

**Estado actual:** RC1 — operativo en hardware real (HIL)

**Arranque rápido:**
```bash
cd "codigo ottoguide"
./scripts/preflight_check.sh    # verificar precondiciones
./scripts/start_robot.sh        # levantar el sistema
```

Ver `documentacion general del proyecto/Movimiento/RC1_Vigente/RUNBOOK_STARTUP_RC1.md` para el proceso completo.

---

## Módulo 2 — OttoGuide IA

Sistema de conversación por voz que permite a Otto escuchar preguntas, procesarlas con un LLM local y responder con voz sintetizada. Funciona **100% offline** dentro del robot.

**Pipeline de voz:**
```
"Hola Otto" → Whisper (STT) → Gemma4:e4b (LLM) → Piper TTS → parlante
```

**Stack tecnológico:**
- **LLM:** Ollama con Gemma4:e4b + Modelfile personalizado
- **STT:** Whisper `medium` en español
- **TTS:** Piper con voz `es_MX-gevy-high` (voz masculina latinoamericana)
- **Wake word:** detección de "Hola Otto" via Whisper
- **Orquestador:** Python en host

**Estado actual:** Pipeline completo funcionando en notebook. Deploy al robot Jetson pendiente.

**Arranque rápido:**
```bash
cd "OttoGuide IA"

# 1. Levantar los contenedores Docker
docker compose up -d

# 2. Ejecutar el orquestador
python3 services/core/main.py
```

Cuando veas `[HIBERNACION] Esperando 'Hola Otto'...` el sistema está listo.

**Requisitos:**
- Docker + Docker Compose
- Python 3.10+
- `requests` instalado (`pip install requests`)

Ver `OttoGuide IA/documentacion/` para documentación técnica detallada.

---

## Hardware — Robot Unitree G1 EDU

| Componente | Detalle |
|---|---|
| Módulo de cómputo | Jetson Orin NX 16GB |
| CPU | ARM Cortex-A78AE · 8 cores · 2GHz |
| GPU | 1024 cores NVIDIA Ampere (32 Tensor Cores) |
| Storage | 2TB |
| Audio | Array 4 micrófonos + parlante 5W |
| OS | Ubuntu 20.04.6 LTS · JetPack R35.3.1 |
| IP local | 192.168.123.164 |
| Conexión | SSH `unitree@192.168.123.164` |

---

## Estado del proyecto

| Componente | Estado |
|---|---|
| Navegación autónoma (RC1) | ✅ Operativo en hardware real |
| Wake word "Hola Otto" | ✅ Funcionando via Whisper |
| LLM local Gemma4 | ✅ Respondiendo con personalidad de Otto |
| TTS voz masculina MX | ✅ Piper es_MX-gevy-high |
| Pipeline completo en notebook | ✅ End-to-end funcionando |
| Deploy al robot Jetson | 🔄 En progreso (Fase 5) |
| TTS nativo SDK Unitree | ⏳ Pendiente validación en robot |
| Wake word dedicado "Hola Otto" | ⏳ Post-MVP (OpenWakeWord) |
| RAG con docs UADE | ⏳ Pendiente contenido del equipo |
| Integración Autónomo + IA | ⏳ V2 en planificación |

---

## Ramas del repositorio

| Rama | Propósito |
|---|---|
| `desarrollo` | Rama de integración principal — contiene ambos módulos actualizados |
| `teo` | Rama de trabajo del módulo IA |
| `echezuria` | Rama de trabajo del módulo autónomo |

**Flujo de trabajo:**
```
teo ───────┐
           ├──→ desarrollo
echezuria ─┘
```

Cada integrante trabaja en su rama y mergea a `desarrollo` cuando tiene algo estable.

---

## Documentación

| Documento | Ubicación |
|---|---|
| Plan técnico LLM V2 | `documentacion general del proyecto/Interaccion/` |
| Paso a paso de implementación | `documentacion general del proyecto/Interaccion/` |
| Instrucciones de levantamiento | `documentacion general del proyecto/Interaccion/` |
| Arquitectura operativa RC1 | `documentacion general del proyecto/Movimiento/RC1_Vigente/` |
| Runbook startup robot | `documentacion general del proyecto/Movimiento/RC1_Vigente/` |
| Planificación del proyecto | `planificacion/V3/` |