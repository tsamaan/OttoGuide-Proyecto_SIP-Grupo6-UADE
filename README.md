# OttoGuide — Robot Guía Universitario Autónomo

**MVP UADE 2026 · Unitree G1 EDU 8 · Estado: `RC1_LOCKED` · HIL-Ready**

![Estado](https://img.shields.io/badge/estado-RC1__LOCKED-blue)
![Tests](https://img.shields.io/badge/tests-40%2F40%20passed-brightgreen)
![Hardware](https://img.shields.io/badge/hardware-Unitree%20G1%20EDU%208-orange)
![Stack](https://img.shields.io/badge/stack-FastAPI%20%7C%20ROS2%20%7C%20Ollama-purple)
![Modo](https://img.shields.io/badge/pipeline-100%25%20offline%20%2F%20air--gapped-success)

---

## ¿Qué es OttoGuide?

OttoGuide es un sistema autónomo de guía de visitas universitarias que opera
sobre el robot humanoide **Unitree G1 EDU 8** (29 DOF, 35 kg, llamado **Ottoman**).
Guía a estudiantes secundarios a través del campus Monserrat de la UADE,
navega entre zonas de interés, detecta cuando un visitante quiere interactuar,
responde preguntas con un modelo de lenguaje local y retoma su recorrido.

**El sistema opera 100% air-gapped:** sin cloud, sin WiFi externo, sin APIs de terceros.

---

## Equipo

| Integrante | Rol |
|---|---|
| **Teo** | Líder técnico · integración de sistemas · pipeline IA |
| **Lucas** | Python · SDK Unitree · locomoción autónoma · arquitectura |
| **Erika** | Voz · diálogos · personalidad de Otto |
| **Jorge** | Testing · relevamiento físico del campus |
| **Martina** | Encuestas · análisis de usuarios |

---

## Arquitectura del Sistema

### Planos de red

```
┌─────────────────────────────────────────────────────────────────────┐
│  PLANO AUTÓNOMO (control y navegación)          192.168.123.x        │
│                                                                     │
│  Companion PC (Jetson Orin NX 16GB)                                 │
│  ┌──────────────────────────────────────────┐                       │
│  │  Capa 4 — FastAPI + asyncio              │                       │
│  │  main.py → TourOrchestrator (FSM)        │                       │
│  │  OttoEventBus (Observer async)           │◄─── SIGINT/SIGTERM    │
│  │  src/interaction/ (STT+LLM+TTS)         │     → Graceful Shutdown│
│  ├──────────────────────────────────────────┤                       │
│  │  Capa 3 — Ollama (qwen2.5:3b local)      │  localhost:11434      │
│  ├──────────────────────────────────────────┤                       │
│  │  Capa 2 — ROS2 Humble / Nav2 / AMCL      │  DDS Domain 0        │
│  └───────────────────────┬──────────────────┘                       │
│                          │ CycloneDDS Unicast                       │
│  ┌───────────────────────▼──────────────────┐                       │
│  │  Capa 1 — Unitree G1 EDU 8               │  192.168.123.161      │
│  │  SDK2: LocoClient + AudioClient           │  29 DOF · 35 kg      │
│  │  LiDAR Livox MID360 · RealSense D435i    │  JetPack R35.3.1     │
│  └──────────────────────────────────────────┘                       │
└─────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────┐
│  PLANO FACTORY (diagnóstico read-only)          192.168.12.x         │
│  UnitreeFactoryRestClient → GET /con_check (solo lectura)           │
│  UNITREE_FACTORY_DIAGNOSTICS_ENABLED=false por defecto              │
└─────────────────────────────────────────────────────────────────────┘
```

### Flujo Event-Driven (Interacción ↔ Locomoción)

```
[Micrófono array 4ch] → WakeWordDetector
    │ "Hola Otto" detectado
    ▼
OttoEventBus.publish(INTERACTION_STARTED)
    │
    ▼  (asyncio — sin bloqueo)
TourOrchestrator._on_interaction_started()
    ├─► nav_bridge.cancel_navigation()
    ├─► hardware.move(MotionCommand(v=0))   ← robot se detiene
    ├─► ConversationManager.process()       ← STT → LLM → TTS
    └─► resume_tour()                       ← retoma navegación
```

---

## Mapa de Carpetas

```
OttoGuide-Proyecto_SIP-Grupo6-UADE/
│
├── codigo ottoguide/                  ← Código ejecutable del sistema
│   ├── main.py                        ← Entrypoint único (FastAPI lifespan)
│   ├── src/
│   │   ├── core/                      ← TourOrchestrator (FSM) + EventBus
│   │   ├── interaction/               ← WakeWord · STT · LLM · TTS
│   │   ├── navigation/                ← AsyncNav2Bridge (ROS2/Nav2)
│   │   ├── infrastructure/            ← UnitreeFactoryRestClient
│   │   └── vision/                    ← VisionProcessor (RealSense D435i)
│   ├── hardware/                      ← HAL: real / sim / mock adapters
│   ├── config/                        ← Settings, CycloneDDS, Nav2
│   ├── api/                           ← Router FastAPI + WebSocket telemetría
│   ├── scripts/                       ← preflight, start_robot, deploy, SRE
│   ├── resources/llm/Modelfile        ← Personalidad Otto (Ollama)
│   ├── data/mvp_tour_script.json      ← Guion del tour (hot-reloadable)
│   └── libs/                          ← SDK Unitree + MuJoCo (vendored)
│
├── documentacion general del proyecto/
│   ├── README_RC1_CONSOLIDADO.md      ← Índice maestro documental
│   ├── Arquitectura/                  ← Contratos técnicos vigentes
│   │   ├── ARQUITECTURA_OPERATIVA_RC1.md
│   │   ├── MEMORIA_ARQUITECTONICA_MVP.md
│   │   ├── ROS2_INTEGRATION.md
│   │   └── APK_CONNECTIVITY_ANALYSIS.md
│   ├── Operaciones_HIL/               ← Runbooks y protocolos de campo
│   │   ├── RUNBOOK_STARTUP_RC1.md
│   │   ├── RUNBOOK_DEMO_LOCAL.md
│   │   ├── RUNBOOK_DEPLOY.md
│   │   ├── RUNBOOK_PACKET_CAPTURE_HIL.md
│   │   └── HIL_TESTING_PROTOCOL.md
│   ├── Hardware_Reference/            ← Manuales del proveedor Unitree
│   ├── Investigacion/                 ← Base de decisiones técnicas
│   └── Historico/                     ← Prototipo OttoGuide IA + SITL
│
├── planificacion/                     ← Cronogramas y entregas UADE
└── README.md
```

---

## Guía Rápida de Arranque

### Modo demo local (sin robot físico)

```bash
cd "codigo ottoguide"
ROBOT_MODE=mock bash scripts/demo_interaction_local.sh
```

Verifica en: `http://127.0.0.1:8000/status` · `http://127.0.0.1:8000/dashboard`

### Modo HIL — Hardware real (secuencia completa)

```bash
# 1. Pre-vuelo — valida red, Ollama, mapa y conectividad DDS
bash scripts/preflight_check.sh

# 2. Confirmar en el mando: Develop Mode ON + Position Mode ON

# 3. Arranque del sistema
ROBOT_MODE=real bash scripts/start_robot.sh
```

Ver procedimiento completo en:
`documentacion general del proyecto/Operaciones_HIL/RUNBOOK_STARTUP_RC1.md`

### Parada de emergencia

```bash
# Via API
curl -X POST http://localhost:8000/emergency

# Via hardware (mando Unitree)
L1 + A
```

**Ante `Ctrl+C` o `systemctl stop`:** el sistema ejecuta automáticamente la
secuencia Graceful Shutdown HIL-safe (EventBus → FSM EMERGENCY → MotionCommand(0) → `damp()`).

---

## Estado del Proyecto

| Componente | Estado |
|---|---|
| Navegación autónoma (RC1) | ✅ Operativo — HIL-ready |
| Pipeline IA: Wake Word + STT + LLM + TTS | ✅ Integrado en `src/interaction/` |
| EventBus: Interacción ↔ Locomoción | ✅ Desacoplamiento asíncrono activo |
| Graceful Shutdown HIL-safe | ✅ SIGINT/SIGTERM → `damp()` garantizado |
| Tests de integración | ✅ 40/40 passed |
| TTS nativo SDK Unitree | ✅ `AudioClient.TtsMaker` (patch bug índice aplicado) |
| Deploy al robot Jetson | 🔄 Pendiente validación HIL física |
| Wake word dedicado (OpenWakeWord) | ⏳ Post-MVP |
| RAG con docs UADE | ⏳ Pendiente contenido del equipo |

---

## Known Bugs & Hardware Quirks

| Ítem | Causa | Solución implementada |
|---|---|---|
| **SDK TTS — índice exponencial** | `g1_audio_client.py`: `tts_index += tts_index` (crecimiento 2^n → desbordamiento int32) | Patch directo `+= 1` + guard `INT32_MAX`. Wrapper defensivo en `UnitreeTTSAdapter` detecta regresiones del SDK. |
| **Grupo Docker en Jetson** | `unitree` no está en el grupo `docker` | `sudo usermod -aG docker unitree && newgrp docker` |
| **Whisper transcribe en japonés/griego** | `language=es` ignorado en body HTTP | Pasar en URL: `?language=es&task=transcribe` |
| **Acentos corruptos en TTS** | `echo "texto"` en bash corrompe UTF-8 | Escribir a `/tmp/otto_texto.txt` con `encoding="utf-8"` |
| **UADE → "guadi" / "wade"** | Whisper malinterpreta siglas | Algoritmo Levenshtein (tolerancia 2 errores) en `ConversationManager` |
| **Feedback mic/parlante** | `arecord` inicia antes que termine el audio | `esperar_fin_audio()` via `pactl list sink-inputs` |
| **`SetFsmId(1)` ≠ stand** | FSM_ID=1 es Damp, no bipedestación | Usar `LocoClient.Start()` = `SetFsmId(200)` para bipedestación operativa |
| **SIGKILL no capturable** | `kill -9` no ejecuta el shutdown graceful | Configurar `TimeoutStopSec=5` en la unidad systemd |
| **CycloneDDS en Jetson roto** | Instalación por defecto puede fallar | Reinstalar siguiendo `unitree_ros2` (ver `Hardware_Reference/`) |

---

## Hardware del Robot

| Campo | Valor |
|---|---|
| Módulo de cómputo | Jetson Orin NX 16GB |
| GPU | 1024 cores NVIDIA Ampere (32 Tensor Cores) |
| OS | Ubuntu 20.04.6 LTS · JetPack R35.3.1 |
| Docker | 24.0.7 |
| IP plano autónomo | `192.168.123.164` |
| IP plano factory | `192.168.12.1` |
| SSH | `ssh unitree@192.168.123.164` (pass: `123`) |
| Audio | Array 4 micrófonos + parlante 5W |
| Firmware TTS mínimo | v1.3.0 (para `AudioClient.TtsMaker`) |

---

## Ramas

| Rama | Propósito |
|---|---|
| `desarrollo` | Integración unificada — estado operativo RC1 |
| `echezuria` | Desarrollo locomoción + arquitectura base |
| `teo` | Desarrollo pipeline IA conversacional |

---

## Documentación Técnica

| Documento | Ubicación |
|---|---|
| Arquitectura operativa (contrato técnico) | `documentacion general del proyecto/Arquitectura/ARQUITECTURA_OPERATIVA_RC1.md` |
| Memoria arquitectónica formal (UADE) | `documentacion general del proyecto/Arquitectura/MEMORIA_ARQUITECTONICA_MVP.md` |
| Integración ROS2/DDS/EventBus | `documentacion general del proyecto/Arquitectura/ROS2_INTEGRATION.md` |
| Protocolo HIL (seguridad física) | `documentacion general del proyecto/Operaciones_HIL/HIL_TESTING_PROTOCOL.md` |
| Runbook de arranque completo | `documentacion general del proyecto/Operaciones_HIL/RUNBOOK_STARTUP_RC1.md` |
| Análisis APK conectividad Unitree | `documentacion general del proyecto/Arquitectura/APK_CONNECTIVITY_ANALYSIS.md` |

---

*Seminario de Integración Profesional — UADE 2026*