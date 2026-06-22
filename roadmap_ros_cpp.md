# ROADMAP: OttoGuide IA — Pipeline de conversación C++ / ROS2 Foxy + Unitree G1-EDU

## CONTEXTO DEL SISTEMA

Robot: Unitree G1-EDU (humanoid)
Computadora onboard: NVIDIA Jetson Orin NX 16GB
OS: Ubuntu 20.04.6 LTS / JetPack R35.3.1 / aarch64
ROS: ROS2 Foxy (instalado en el robot)
SDK C++: unitree_sdk2 (NO está en el repo, hay que clonarlo)
SDK Python: unitree_sdk2_python (está en el repo en codigo ottoguide/libs/)
IP robot: 192.168.123.164
Usuario: unitree / pw: 123

## OBJETIVO

Implementar un pipeline de conversación en español que corra localmente en el Jetson:
  Wake word "Hola Otto" → STT → LLM local → TTS → parlante del robot

Pipeline completo:
  [Micrófonos físicos del robot]
    → ROS2 nodo C++ captura audio via SDK C++ (AudioClient ASR callback)
    → publica en tópico ROS2 /otto/audio_raw (PCM float32)
  [Nodo Python STT]
    → suscribe /otto/audio_raw
    → manda a Whisper HTTP (Docker, puerto 9000)
    → publica texto en /otto/stt_text
  [Nodo Python LLM]
    → suscribe /otto/stt_text
    → detecta wake word "Hola Otto"
    → manda pregunta a Ollama HTTP (Docker, puerto 11434, modelo "otto")
    → publica respuesta en /otto/llm_response
  [Nodo C++ TTS]
    → suscribe /otto/llm_response
    → genera WAV con Piper (Docker, puerto local)
    → reproduce via AudioClient.PlayStream() del SDK C++

## POR QUÉ C++ PARA AUDIO

El Python SDK (unitree_sdk2_python) NO tiene captura de micrófono.
El C++ SDK (unitree_sdk2) SÍ tiene:
  - AudioClient con callback ASR (ROBOT_API_ID_AUDIO_ASR = 1002)
  - Suscripción al tópico DDS rt/audio_msg
  - PlayStream para reproducción de PCM

El resto del pipeline (STT, LLM, orquestación) puede ser Python via ROS2.

## ARQUITECTURA DE NODOS ROS2

Nodo 1 (C++): otto_audio_capture
  - Usa unitree_sdk2 AudioClient
  - Inicializa CycloneDDS en interfaz eth0
  - Callback en rt/audio_msg → publica /otto/audio_raw (sensor_msgs/msg/Audio o std_msgs/msg/UInt8MultiArray)
  - También maneja PlayStream para reproducción

Nodo 2 (Python): otto_stt
  - Suscribe /otto/audio_raw
  - Acumula chunks, detecta silencio via amplitud RMS
  - Manda WAV a Whisper HTTP: POST http://localhost:9000/asr?language=es&task=transcribe
  - Publica /otto/stt_text (std_msgs/msg/String)

Nodo 3 (Python): otto_brain
  - Suscribe /otto/stt_text
  - Detecta wake word "Hola Otto" (Levenshtein, tolerancia 2 errores)
  - Maneja estado: HIBERNACION / ESCUCHANDO / PROCESANDO
  - Manda prompt a Ollama: POST http://localhost:11434/api/generate model="otto"
  - Publica /otto/llm_response (std_msgs/msg/String)

Nodo 4 (C++ o Python): otto_tts
  - Suscribe /otto/llm_response
  - Llama a Piper Docker para generar WAV en español (voz es_MX-gevy-high.onnx)
  - Convierte WAV a PCM 16kHz/mono/16-bit
  - Reproduce via AudioClient.PlayStream("otto", 0, pcm_data)

## TÓPICOS ROS2

/otto/audio_raw     → std_msgs/msg/UInt8MultiArray  (PCM raw del mic)
/otto/stt_text      → std_msgs/msg/String            (texto transcripto)
/otto/llm_response  → std_msgs/msg/String            (respuesta del LLM)
/otto/state         → std_msgs/msg/String            (HIBERNACION/ESCUCHANDO/PROCESANDO)

## SERVICIOS DOCKER REQUERIDOS (en el Jetson)

Whisper STT:
  imagen: onerahmet/openai-whisper-asr-webservice:latest
  puerto: 9000
  env: ASR_MODEL=medium, ASR_ENGINE=faster_whisper, ASR_LANGUAGE=es

Ollama LLM:
  imagen: ollama/ollama:latest
  puerto: 11434
  modelo: otto (Gemma4:e4b + Modelfile de personalidad)

Piper TTS:
  imagen: build local desde services/tts/Dockerfile
  entrypoint: tail -f /dev/null  (no usar wyoming service)
  volumen: ./services/tts/voices:/data/voices
  voz: es_MX-gevy-high.onnx

## PASO A PASO DE IMPLEMENTACIÓN

### FASE 1 — Preparar el entorno en el robot

```bash
# Agregar unitree al grupo docker
sudo usermod -aG docker unitree
newgrp docker

# Clonar SDK C++ de Unitree
cd ~/Desktop
git clone https://github.com/unitreerobotics/unitree_sdk2.git

# Instalar dependencias C++
sudo apt install cmake libboost-all-dev -y

# Compilar SDK C++
cd unitree_sdk2
mkdir build && cd build
cmake ..
make -j4
```

### FASE 2 — Levantar servicios Docker

```bash
cd ~/Desktop/Ottoguide/OttoGuide-Proyecto_SIP-Grupo6-UADE/OttoGuide\ IA
docker compose up -d
# Verificar: docker compose ps

# Bajar modelo LLM (primera vez, requiere internet)
docker exec -it ottoguide-llm ollama pull gemma4:e4b
docker cp services/llm/Modelfile ottoguide-llm:/tmp/Modelfile
docker exec -it ottoguide-llm ollama create otto -f /tmp/Modelfile
```

### FASE 3 — Crear paquete ROS2

```bash
cd ~/ros2_ws/src  # o crear workspace si no existe
ros2 pkg create otto_guide --build-type ament_cmake --dependencies rclcpp std_msgs sensor_msgs
```

### FASE 4 — Nodo C++ de captura de audio (otto_audio_capture)

Archivo: otto_guide/src/audio_capture_node.cpp

Estructura:
```cpp
#include "rclcpp/rclcpp.hpp"
#include "std_msgs/msg/u_int8_multi_array.hpp"
#include "unitree/robot/g1/audio/g1_audio_client.hpp"
#include "unitree/robot/channel/channel_factory.hpp"

class AudioCaptureNode : public rclcpp::Node {
public:
  AudioCaptureNode() : Node("otto_audio_capture") {
    pub_ = create_publisher<std_msgs::msg::UInt8MultiArray>("/otto/audio_raw", 10);

    unitree::robot::ChannelFactory::Instance()->Init(0, "eth0");
    audio_client_ = std::make_shared<unitree::robot::g1::AudioClient>();
    audio_client_->SetTimeout(10.0f);
    audio_client_->Init();

    // Suscribir al tópico DDS de audio del robot
    // rt/audio_msg contiene PCM raw de los micrófonos
    audio_subscriber_ = unitree::robot::ChannelSubscriber</* tipo IDL */>( "rt/audio_msg");
    audio_subscriber_.InitChannel([this](auto msg) { this->OnAudioMsg(msg); });
  }

private:
  void OnAudioMsg(/* tipo del mensaje */) {
    // Extraer PCM, publicar en /otto/audio_raw
    auto ros_msg = std_msgs::msg::UInt8MultiArray();
    // ros_msg.data = pcm_data;
    pub_->publish(ros_msg);
  }

  rclcpp::Publisher<std_msgs::msg::UInt8MultiArray>::SharedPtr pub_;
  std::shared_ptr<unitree::robot::g1::AudioClient> audio_client_;
};

int main(int argc, char* argv[]) {
  rclcpp::init(argc, argv);
  rclcpp::spin(std::make_shared<AudioCaptureNode>());
  rclcpp::shutdown();
}
```

NOTA CRÍTICA: El tipo IDL exacto del mensaje rt/audio_msg no está documentado.
Hay que inspeccionarlo en el robot con:
  cd unitree_sdk2 && grep -r "audio_msg" --include="*.hpp" .

### FASE 5 — Nodo Python STT (otto_stt_node.py)

```python
import rclpy
from rclpy.node import Node
from std_msgs.msg import String, UInt8MultiArray
import numpy as np
import requests
import wave
import io

class OttoSTT(Node):
    def __init__(self):
        super().__init__('otto_stt')
        self.sub = self.create_subscription(UInt8MultiArray, '/otto/audio_raw', self.on_audio, 10)
        self.pub = self.create_publisher(String, '/otto/stt_text', 10)
        self.buffer = []
        self.THRESHOLD = 1000
        self.CHUNK_SIZE = 16000 * 2  # 1 segundo de audio 16kHz 16-bit

    def on_audio(self, msg):
        self.buffer.extend(msg.data)
        if len(self.buffer) >= self.CHUNK_SIZE * 3:  # 3 segundos
            self.process_buffer()

    def process_buffer(self):
        pcm = np.frombuffer(bytes(self.buffer), dtype=np.int16)
        self.buffer = []

        if max(abs(pcm)) < self.THRESHOLD:
            return  # silencio

        # Crear WAV en memoria
        buf = io.BytesIO()
        with wave.open(buf, 'wb') as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(16000)
            wf.writeframes(pcm.tobytes())
        buf.seek(0)

        try:
            r = requests.post(
                "http://localhost:9000/asr?language=es&task=transcribe",
                files={"audio_file": buf},
                timeout=30
            )
            texto = r.text.lower().strip()
            if texto:
                msg_out = String()
                msg_out.data = texto
                self.pub.publish(msg_out)
        except Exception as e:
            self.get_logger().error(f"STT error: {e}")

def main():
    rclpy.init()
    rclpy.spin(OttoSTT())
    rclpy.shutdown()
```

### FASE 6 — Nodo Python LLM/Brain (otto_brain_node.py)

```python
import rclpy
from rclpy.node import Node
from std_msgs.msg import String
import requests
import re

WAKE_WORDS = ["hola otto", "hola oto", "ola otto", "ola oto", "hola auto", "otto", "oto"]

def similar_a_uade(palabra):
    objetivo = "uade"
    p = palabra.lower()
    if p == objetivo: return True
    if len(p) < 3 or len(p) > 7: return False
    m, n = len(objetivo), len(p)
    dp = [[0]*(n+1) for _ in range(m+1)]
    for i in range(m+1): dp[i][0] = i
    for j in range(n+1): dp[0][j] = j
    for i in range(1, m+1):
        for j in range(1, n+1):
            if objetivo[i-1] == p[j-1]: dp[i][j] = dp[i-1][j-1]
            else: dp[i][j] = 1 + min(dp[i-1][j], dp[i][j-1], dp[i-1][j-1])
    return dp[m][n] <= 2

class OttoBrain(Node):
    def __init__(self):
        super().__init__('otto_brain')
        self.sub = self.create_subscription(String, '/otto/stt_text', self.on_text, 10)
        self.pub = self.create_publisher(String, '/otto/llm_response', 10)
        self.state = "HIBERNACION"  # HIBERNACION / ESCUCHANDO

    def on_text(self, msg):
        texto = msg.data

        if self.state == "HIBERNACION":
            if len(texto.split()) <= 4 and any(w in texto for w in WAKE_WORDS):
                self.state = "ESCUCHANDO"
                out = String(); out.data = "Si, decime. cual es tu pregunta."
                self.pub.publish(out)
            return

        if self.state == "ESCUCHANDO":
            if any(d in texto for d in ["chau", "adios", "hasta luego", "listo"]):
                out = String(); out.data = "Fue un placer. Disfruten el recorrido."
                self.pub.publish(out)
                self.state = "HIBERNACION"
                return

            # Corregir UADE
            palabras = [("UADE" if similar_a_uade(re.sub(r'[^\w]','',w.lower())) else w) for w in texto.split()]
            pregunta = ' '.join(palabras)

            try:
                r = requests.post(
                    "http://localhost:11434/api/generate",
                    json={"model": "otto", "prompt": pregunta, "stream": False},
                    timeout=120
                )
                respuesta = r.json().get("response", "").strip()
                if respuesta:
                    out = String(); out.data = respuesta
                    self.pub.publish(out)
            except Exception as e:
                self.get_logger().error(f"LLM error: {e}")

def main():
    rclpy.init()
    rclpy.spin(OttoBrain())
    rclpy.shutdown()
```

### FASE 7 — Nodo C++ TTS (otto_tts_node.cpp)

```cpp
// Suscribe /otto/llm_response
// Llama a Piper via system() o popen() para generar WAV
// Lee el WAV y lo manda con AudioClient.PlayStream()

#include "rclcpp/rclcpp.hpp"
#include "std_msgs/msg/string.hpp"
#include "unitree/robot/g1/audio/g1_audio_client.hpp"
#include <fstream>
#include <cstdlib>

class OttoTTS : public rclcpp::Node {
public:
  OttoTTS() : Node("otto_tts") {
    sub_ = create_subscription<std_msgs::msg::String>(
      "/otto/llm_response", 10,
      [this](const std_msgs::msg::String::SharedPtr msg) { this->on_response(msg); }
    );
    unitree::robot::ChannelFactory::Instance()->Init(0, "eth0");
    audio_ = std::make_shared<unitree::robot::g1::AudioClient>();
    audio_->SetTimeout(10.0f);
    audio_->Init();
  }

private:
  void on_response(const std_msgs::msg::String::SharedPtr msg) {
    std::string texto = msg->data;

    // Escribir texto a archivo temporal
    std::ofstream f("/tmp/otto_texto.txt");
    f << texto;
    f.close();

    // Generar WAV con Piper via Docker
    system("docker cp /tmp/otto_texto.txt ottoguide-tts:/tmp/otto_texto.txt");
    system("docker exec ottoguide-tts sh -c 'cat /tmp/otto_texto.txt | "
           "/usr/src/.venv/bin/piper --model /data/voices/es_MX-gevy-high.onnx "
           "--output_file /tmp/respuesta.wav'");
    system("docker cp ottoguide-tts:/tmp/respuesta.wav /tmp/respuesta.wav");

    // Reproducir via SDK
    play_wav("/tmp/respuesta.wav");
  }

  void play_wav(const std::string& path) {
    // Leer WAV y enviar PCM en chunks
    // Formato requerido: 16kHz, mono, 16-bit signed
    // AudioClient.PlayStream("otto", 0, pcm_chunk)
    // Ver SDK C++ unitree_sdk2/example/g1/audio/ para implementación completa
  }

  rclcpp::Subscription<std_msgs::msg::String>::SharedPtr sub_;
  std::shared_ptr<unitree::robot::g1::AudioClient> audio_;
};

int main(int argc, char* argv[]) {
  rclcpp::init(argc, argv);
  rclcpp::spin(std::make_shared<OttoTTS>());
  rclcpp::shutdown();
}
```

### FASE 8 — Launch file ROS2

Archivo: otto_guide/launch/otto_pipeline.launch.py

```python
from launch import LaunchDescription
from launch_ros.actions import Node

def generate_launch_description():
    return LaunchDescription([
        Node(package='otto_guide', executable='audio_capture_node', name='otto_audio_capture'),
        Node(package='otto_guide', executable='otto_stt_node', name='otto_stt'),
        Node(package='otto_guide', executable='otto_brain_node', name='otto_brain'),
        Node(package='otto_guide', executable='otto_tts_node', name='otto_tts'),
    ])
```

Ejecutar:
```bash
source /opt/ros/foxy/setup.bash
cd ~/ros2_ws && colcon build --packages-select otto_guide
source install/setup.bash
ros2 launch otto_guide otto_pipeline.launch.py
```

## BLOQUEANTE CRÍTICO ANTES DE IMPLEMENTAR

El tipo IDL exacto del mensaje rt/audio_msg del G1 NO está documentado públicamente.
Hay que inspeccionarlo directamente en el robot:

```bash
ssh unitree@192.168.123.164
cd ~/Desktop && git clone https://github.com/unitreerobotics/unitree_sdk2.git
grep -r "audio_msg\|AudioMsg\|audio_data" unitree_sdk2/include --include="*.hpp" -l
```

Sin conocer ese tipo, el nodo C++ de captura no se puede completar.
Alternativa de puente mientras tanto: usar arecord -D pulse directo en el nodo C++ de captura
y evitar el callback DDS de audio, manteniendo el resto de la arquitectura ROS2 igual.

## MODELFILE DE OTTO (LLM)

El modelo "otto" se crea así en el robot:
```bash
docker exec -it ottoguide-llm ollama pull gemma4:e4b
docker cp OttoGuide\ IA/services/llm/Modelfile ottoguide-llm:/tmp/Modelfile
docker exec -it ottoguide-llm ollama create otto -f /tmp/Modelfile
```

El Modelfile define la personalidad de Otto: robot guía del campus Monserrat de UADE,
Buenos Aires. Responde en español rioplatense, respuestas cortas (máx 3 oraciones),
nunca usa emojis, menciona "UADE" siempre como sigla.

## DEPENDENCIAS ADICIONALES PARA EL AGENTE

- unitree_sdk2 C++: https://github.com/unitreerobotics/unitree_sdk2
- ROS2 Foxy ya instalado en el robot
- Python packages en el Jetson: requests, numpy, rclpy (ya en ROS2 Foxy)
- Docker + imágenes: onerahmet/openai-whisper-asr-webservice, ollama/ollama
- Piper TTS: imagen custom desde services/tts/Dockerfile del repo
