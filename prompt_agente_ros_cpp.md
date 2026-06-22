# PROMPT PARA AGENTE — OttoGuide IA Pipeline C++ / ROS2 Foxy

## ROL

Sos un experto en robótica con ROS2 Foxy, C++17, Python 3.8 y el SDK de Unitree.
Tu tarea es implementar un pipeline de conversación en español para un robot Unitree G1-EDU.
Respondés con código ejecutable. Sin preámbulos. Sin explicaciones no solicitadas.

---

## CONTEXTO DEL HARDWARE

- Robot: Unitree G1-EDU humanoid
- Computadora onboard: NVIDIA Jetson Orin NX 16GB / Ubuntu 20.04.6 / JetPack R35.3.1 / aarch64
- ROS: ROS2 Foxy (instalado)
- IP robot: 192.168.123.164 | usuario: unitree | pw: 123
- Repo del proyecto en robot: /home/unitree/Desktop/Ottoguide/OttoGuide-Proyecto_SIP-Grupo6-UADE
- SDK Python Unitree: disponible en codigo ottoguide/libs/unitree_sdk2_python-master/
- SDK C++ Unitree: HAY QUE CLONARLO → https://github.com/unitreerobotics/unitree_sdk2

---

## OBJETIVO

Implementar un pipeline completo que corra en el Jetson:

  [Micrófonos robot] → [Captura C++ via SDK] → [STT Python/Whisper] → [LLM Python/Ollama] → [TTS C++ via SDK]

El pipeline debe:
1. Escuchar continuamente en modo hibernación
2. Activarse cuando detecta el wake word "Hola Otto" (y variaciones fonéticas)
3. Transcribir la pregunta del visitante
4. Generar respuesta en español con modelo Ollama local llamado "otto"
5. Reproducir la respuesta por los parlantes del robot
6. Volver a modo hibernación cuando el visitante se despide

---

## ARQUITECTURA DE NODOS ROS2

```
Tópicos:
/otto/audio_raw      → std_msgs/msg/UInt8MultiArray  (PCM 16kHz/mono/16-bit)
/otto/stt_text       → std_msgs/msg/String            (texto transcripto)
/otto/llm_response   → std_msgs/msg/String            (respuesta del LLM)
/otto/state          → std_msgs/msg/String            (HIBERNACION/ESCUCHANDO)

Nodos:
1. otto_audio_capture  (C++)    → captura mic via SDK, publica /otto/audio_raw
2. otto_stt            (Python) → suscribe /otto/audio_raw, publica /otto/stt_text
3. otto_brain          (Python) → suscribe /otto/stt_text, publica /otto/llm_response
4. otto_tts            (C++)    → suscribe /otto/llm_response, reproduce via SDK
```

---

## SERVICIOS DOCKER (ya configurados en el repo)

El proyecto tiene un docker-compose.yml en OttoGuide IA/ con:

- Whisper STT: onerahmet/openai-whisper-asr-webservice → puerto 9000
  env: ASR_MODEL=medium, ASR_ENGINE=faster_whisper, ASR_LANGUAGE=es

- Ollama LLM: ollama/ollama → puerto 11434
  modelo personalizado: "otto" (Gemma4:e4b + Modelfile de personalidad de guía UADE)

- Piper TTS: imagen custom local → entrypoint tail -f /dev/null
  volumen con voz: es_MX-gevy-high.onnx (español mexicano masculino)
  llamar via: docker exec ottoguide-tts sh -c 'cat /tmp/texto.txt | piper --model /data/voices/es_MX-gevy-high.onnx --output_file /tmp/out.wav'

---

## LÓGICA DE WAKE WORD

Variaciones aceptadas de "Hola Otto":
  hola otto, hola oto, ola otto, ola oto, hola auto, hola a otto, oto, otto

Filtros:
- Descartar transcripciones de más de 4 palabras en modo hibernación
- Corrección fonética de "UADE" via Levenshtein distancia ≤ 2, longitud 3-7 chars
- Falsos positivos de Whisper a descartar: "subtitulos", "amara", "suscribete", "youtube", "comunidad", "gracias por ver"

Despedidas que vuelven a hibernación:
  chau, adios, hasta luego, listo, eso es todo, no tengo mas preguntas, chao

---

## NODO 1 — otto_audio_capture (C++)

Usa unitree_sdk2 (C++) para capturar audio del array de micrófonos.
Inicializar con: ChannelFactory::Instance()->Init(0, "eth0")
El SDK C++ publica audio en el tópico DDS interno rt/audio_msg.

IMPORTANTE: El tipo IDL exacto de rt/audio_msg no está documentado.
Inspeccionarlo así antes de implementar:
  grep -r "audio_msg\|AudioMsg\|audio_data" unitree_sdk2/include --include="*.hpp"

Si no se puede resolver el tipo IDL, usar arecord como fallback:
  arecord -D pulse -f S16_LE -c 2 -r 16000 -d 3 /tmp/chunk.wav
  y publicar el contenido del WAV en /otto/audio_raw

Para reproducción usa AudioClient.PlayStream():
  Formato: 16kHz, mono, 16-bit signed PCM
  Chunks de 3200 bytes (100ms), con sleep de 0.08s entre chunks
  Terminar con AudioClient.PlayStop("otto", 0)

---

## NODO 2 — otto_stt (Python)

- Suscribe /otto/audio_raw (UInt8MultiArray)
- Acumula chunks hasta tener 3 segundos (16000 * 2 * 3 = 96000 bytes)
- Mide amplitud RMS: si max(abs(samples)) < 1000, descartar
- Crear WAV en memoria con wave.open(io.BytesIO(), 'wb')
- POST http://localhost:9000/asr?language=es&task=transcribe con multipart/form-data
- Publicar texto en /otto/stt_text

---

## NODO 3 — otto_brain (Python)

- Suscribe /otto/stt_text
- Estado interno: HIBERNACION o ESCUCHANDO
- En HIBERNACION: solo detecta wake word, máx 4 palabras
- En ESCUCHANDO: manda pregunta al LLM y publica respuesta
- LLM: POST http://localhost:11434/api/generate
  body: {"model": "otto", "prompt": texto, "stream": false}
  timeout dinámico: ≤10 palabras → 120s, ≤15 palabras → 180s, resto → 240s
- Corregir UADE antes de mandar al LLM (Levenshtein)
- Publicar respuesta en /otto/llm_response

---

## NODO 4 — otto_tts (C++)

- Suscribe /otto/llm_response
- Escribir texto a /tmp/otto_texto.txt (UTF-8, sin echo para preservar acentos)
- Llamar a Piper via Docker para generar WAV
- Leer /tmp/respuesta.wav
- Reproducir con AudioClient.PlayStream() en chunks de 3200 bytes

---

## ESTRUCTURA DE ARCHIVOS A CREAR

```
~/ros2_ws/src/otto_guide/
├── CMakeLists.txt
├── package.xml
├── launch/
│   └── otto_pipeline.launch.py
├── src/
│   ├── audio_capture_node.cpp
│   └── tts_node.cpp
└── otto_guide/
    ├── __init__.py
    ├── stt_node.py
    └── brain_node.py
```

---

## COMANDOS DE BUILD Y EJECUCIÓN

```bash
# Fuente ROS2
source /opt/ros/foxy/setup.bash

# Clonar SDK C++ si no está
cd ~/Desktop
git clone https://github.com/unitreerobotics/unitree_sdk2.git
cd unitree_sdk2 && mkdir build && cd build && cmake .. && make -j4

# Build paquete ROS2
cd ~/ros2_ws
colcon build --packages-select otto_guide
source install/setup.bash

# Levantar Docker antes de ejecutar
cd ~/Desktop/Ottoguide/OttoGuide-Proyecto_SIP-Grupo6-UADE/OttoGuide\ IA
docker compose up -d

# Ejecutar pipeline
ros2 launch otto_guide otto_pipeline.launch.py
```

---

## RESTRICCIONES

- No usar TtsMaker() del SDK para TTS — solo soporta chino/inglés, no español
- No usar ROS2 para navegación — ese módulo ya existe separado en codigo ottoguide/
- No modificar codigo ottoguide/ ni los nodos de navegación de Lucas
- No usar cloud APIs — todo local en el Jetson
- No usar OpenAI Whisper cloud — solo el Docker local
- El modelo LLM debe llamarse "otto" — ya está creado con Modelfile de UADE

---

## PUNTO DE PARTIDA RECOMENDADO

1. Clonar unitree_sdk2 en el Jetson
2. Inspeccionar tipo IDL de rt/audio_msg
3. Implementar audio_capture_node.cpp con fallback a arecord si IDL no es claro
4. Implementar stt_node.py y brain_node.py (estos son los más simples)
5. Implementar tts_node.cpp con PlayStream
6. Probar cada nodo individualmente con ros2 topic echo antes de lanzar todo junto
