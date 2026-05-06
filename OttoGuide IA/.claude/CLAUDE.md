# OttoGuide IA — Contexto para Claude Code

## ¿Qué es este proyecto?

OttoGuide es un MVP académico para la materia de Diseño Thinking en UADE (Universidad Argentina de la Empresa).
Integra un robot humanoide Unitree G1-EDU llamado **Ottoman** para guiar visitas de estudiantes secundarios
en el campus Monserrat (Lima 775, CABA).

Este repositorio contiene **solo la parte de IA** — el sistema de conversación por voz del robot.
La parte de locomoción (caminar, moverse) está en otra carpeta del repo (`codigo ottoguide/`).

---

## Equipo

- **Teo** — líder técnico, integración y IA (este código)
- **Lucas** — Python + SDK Unitree (locomoción)
- **Erika** — voz, diálogos y personalidad de Otto
- **Jorge** — testing y relevamiento físico
- **Martina** — encuestas y análisis

---

## Estado actual del proyecto (Mayo 2026)

### Lo que funciona (probado en notebook)
- **LLM**: Gemma4:e4b corriendo en Ollama con modelo `otto` personalizado via Modelfile
- **STT**: Whisper `medium` transcribiendo en español
- **Wake word**: detección de "Hola Otto" via Whisper (ciclos de 3 seg)
- **Orquestador**: `services/core/main.py` conectando todo el pipeline
- **TTS (notebook)**: Piper con voz `es_MX-gevy-high` (masculina latinoamericana)

### Pendiente
- **TTS (robot)**: migrar de Piper a `AudioClient.TtsMaker()` del SDK de Unitree
- **Deploy al robot**: script `deploy-robot.sh` (Fase 5)
- **Wake word dedicado**: modelo OpenWakeWord "Hola Otto" (post-MVP)
- **RAG**: ChromaDB con documentos institucionales de UADE
- **Enriquecer Modelfile**: Erika y Martina definen contenido

---

## Arquitectura actual

```
[Micrófono] → arecord (host)
    ↓
[Whisper STT] → contenedor Docker ottoguide-stt (puerto 9001 notebook / 9000 robot)
    ↓
[main.py] → detecta "Hola Otto", graba pregunta, llama al LLM
    ↓
[Ollama LLM] → contenedor Docker ottoguide-llm (puerto 11434)
    modelo: otto (Gemma4:e4b + Modelfile)
    ↓
[Piper TTS] → contenedor Docker ottoguide-tts (puerto 10200) ← REEMPLAZAR por SDK
    voz: es_MX-gevy-high.onnx
    ↓
[Parlante] → paplay (notebook) / AudioClient SDK (robot)
```

### Arquitectura objetivo V2 (con SDK)

```
[Array 4 micrófonos Jetson] → arecord
    ↓
[Whisper STT] → Docker (se mantiene)
    ↓
[main.py] → orquestador
    ↓
[Ollama LLM] → Docker (se mantiene)
    ↓
[AudioClient.TtsMaker()] → SDK Unitree nativo ← SIN Docker, SIN Piper
    ↓
[Parlante nativo del robot]
```

---

## Estructura de carpetas

```
OttoGuide IA/
├── docker-compose.yml          ← 3 servicios: llm, tts, stt
├── services/
│   ├── llm/
│   │   └── Modelfile           ← personalidad de Otto (editar para más info UADE)
│   ├── tts/
│   │   ├── Dockerfile          ← fix pathvalidate para imagen oficial
│   │   └── voices/
│   │       └── es_MX-gevy-high.onnx   ← voz activa
│   ├── stt/                    ← sin Dockerfile, usa imagen oficial
│   └── core/
│       ├── main.py             ← orquestador principal (corre en host, no en Docker)
│       └── correcciones_uade.json  ← fallback fonético UADE (Levenshtein es el activo)
├── data/
│   └── uade-docs/              ← PDFs para RAG (futuro)
└── deploy/
    └── deploy-robot.sh         ← pendiente Fase 5
```

---

## docker-compose.yml actual

```yaml
services:
  llm:
    image: ollama/ollama:latest
    container_name: ottoguide-llm
    ports:
      - "11434:11434"
    volumes:
      - ollama_data:/root/.ollama
    restart: unless-stopped
    environment:
      - OLLAMA_HOST=0.0.0.0

  tts:
    build: ./services/tts
    container_name: ottoguide-tts
    ports:
      - "10200:10200"
    volumes:
      - ./services/tts/voices:/data/voices
    restart: unless-stopped
    command: >
      --voice es_MX-gevy-high
      --update-voices
      --download-dir /data/voices

  stt:
    image: onerahmet/openai-whisper-asr-webservice:latest
    container_name: ottoguide-stt
    ports:
      - "9001:9000"        # notebook (Portainer ocupa 9000) | robot: usar 9000:9000
    environment:
      - ASR_MODEL=medium
      - ASR_ENGINE=faster_whisper
      - ASR_LANGUAGE=es
    restart: unless-stopped

volumes:
  ollama_data:
```

---

## Comandos frecuentes

```bash
# Desde OttoGuide IA/

# Levantar stack
docker compose up -d

# Ver estado (alias en ~/.zshrc)
dps

# Ejecutar el orquestador
python3 services/core/main.py

# Aplicar cambios al Modelfile de Otto
docker cp services/llm/Modelfile ottoguide-llm:/tmp/Modelfile
docker exec -it ottoguide-llm ollama create otto -f /tmp/Modelfile

# Probar el LLM directamente
curl http://localhost:11434/api/generate \
  -d '{"model":"otto","prompt":"cuántos pisos tiene el campus","stream":false}' \
  | python3 -c "import sys,json; print(json.load(sys.stdin)['response'])"

# Probar la voz de Piper
docker exec ottoguide-tts sh -c \
  'echo "Hola soy Otto" > /tmp/test.txt && cat /tmp/test.txt | /usr/src/.venv/bin/piper \
  --model /data/voices/es_MX-gevy-high.onnx --output_file /tmp/test.wav' \
  && docker cp ottoguide-tts:/tmp/test.wav /tmp/test.wav && paplay /tmp/test.wav
```

---

## Info técnica del robot

| Campo | Valor |
|---|---|
| IP | 192.168.123.164 |
| SSH | `ssh unitree@192.168.123.164` |
| Password | 123 |
| Usuario | unitree |
| OS | Ubuntu 20.04.6 LTS |
| JetPack | R35.3.1 (aarch64) |
| Docker | 24.0.7 |
| GPU | NVIDIA Ampere 1024 cores |
| RAM | 16GB |
| ⚠️ Problema | unitree NO está en grupo docker — ejecutar: `sudo usermod -aG docker unitree` |

---

## Modelo LLM — Otto

- **Base**: Gemma4:e4b (9.6GB, descargado en volumen Docker `ollama_data`)
- **Personalización**: Modelfile en `services/llm/Modelfile`
- **Nombre del modelo**: `otto`
- **Sin fine-tuning** — solo Modelfile + system prompt
- **Conocimiento actual**: info básica de UADE (incompleto, pendiente reunión con Erika/Martina)

Para actualizar el Modelfile siempre usar:
```bash
docker cp services/llm/Modelfile ottoguide-llm:/tmp/Modelfile && \
docker exec -it ottoguide-llm ollama create otto -f /tmp/Modelfile
```

---

## Bugs conocidos y soluciones

| Bug | Causa | Solución |
|---|---|---|
| LLM devuelve vacío | `num_predict` muy bajo | No usar `num_predict` en options |
| Acentos corruptos en TTS | `echo "texto"` en bash corrompe UTF-8 | Usar archivo `/tmp/otto_texto.txt` con `encoding="utf-8"` |
| Feedback mic/parlante | `arecord` arranca antes que termine el audio | `esperar_fin_audio()` via `pactl list sink-inputs` |
| Whisper en japonés/griego | `language=es` ignorado en body | Pasar en URL: `?language=es&task=transcribe` |
| UADE → "guadi"/"wade" | Whisper transcribe mal siglas | Algoritmo Levenshtein en `similar_a_uade()` |
| STT `Connection reset` | Contenedor Whisper se cae | Ver `docker compose logs stt` |
| Puerto 9000 ocupado | Portainer usa 9000 | Usar `9001:9000` en notebook |

---

## SDK Unitree — Audio

El SDK (`unitree_sdk2_python`) expone `AudioClient` con:
```python
AudioClient.TtsMaker(text, speaker_id)   # TTS nativo
AudioClient.PlayStream(app, stream_id, pcm_data)
AudioClient.SetVolume(volume)
AudioClient.GetVolume()
```

**⚠️ Importante**: 
- Requiere firmware v1.3.0 en el robot
- CycloneDDS por defecto en el Jetson puede estar roto — reinstalar siguiendo unitree_ros2
- El Python SDK tiene features de audio faltantes respecto al C++ SDK (issue abierto)
- Validar soporte español, latencia y calidad ANTES de eliminar Piper

**Variable de entorno para modo robot/notebook**:
```python
USAR_SDK_AUDIO = os.getenv("OTTO_ENV") == "robot"
```

---

## Wake Word

- **Actual (MVP)**: Whisper detecta "Hola Otto" en ciclos de 3 segundos
- **Frases aceptadas**: hola otto, hola oto, ola otto, hola auto, hola a otto, oto, otto
- **Filtro**: frases de más de 4 palabras se descartan (evita conversación ambiente)
- **Cooldown**: 3 segundos después de despedida antes de volver a hibernación
- **Futuro**: modelo OpenWakeWord personalizado (ver `OttoGuide_WakeWord_HolaOtto_V1.html`)

---

## Convenciones del código

- Todo en español (comentarios, variables de configuración, frases de Otto)
- Comentarios `# robot: X` indican el valor a usar en deploy
- Variables de ambiente comentadas con `# robot Jetson` para fácil localización
- Prints con prefijo: `[WAKE]`, `[STT]`, `[LLM]`, `[TTS]`, `[MIC]`, `[HIBERNACION]`
- Funciones con docstring en triple comilla
- Fallbacks comentados con instrucciones claras para activarlos

---

## Documentación del proyecto

Los HTMLs de documentación están en la carpeta `documentacion/` del repo:
- `OttoGuide_LLM_Plan_V2.html` — arquitectura con SDK nativo (versión objetivo)
- `OttoGuide_PasoPaso_V1.html` — registro de implementación fase a fase
- `OttoGuide_Instrucciones_V1.html` — guía de operación con comandos
- `OttoGuide_WakeWord_HolaOtto_V1.html` — plan de wake word dedicado

---

## Archivos de referencia

Leer estos archivos para contexto detallado antes de responder:

@documentacion/OttoGuide_LLM_Plan_V2.html
@documentacion/OttoGuide_PasoPaso_V1.html
@documentacion/OttoGuide_Instrucciones_V1.html
@services/core/main.py
@services/llm/Modelfile
@docker-compose.yml