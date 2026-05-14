# Reporte Técnico: Análisis de Conectividad Unitree Go APK v1.12.7
## Ingeniería Inversa de Protocolos de Comunicación — OttoGuide Proyecto SIP

**Fecha de análisis:** 7 de mayo de 2026  
**Analista:** Senior Reverse Engineer / Arquitecto de Robótica  
**Versión APK:** 1.12.7 (com.unitree.doggo2)  
**Robot objetivo:** Unitree G1 EDU 8  

---

> **Nota de vigencia RC1:** este documento es análisis pasivo/histórico de `Unitree Go` y del plano factory `192.168.12.x`. No implica ruta operativa primaria para el G1 EDU. `Unitree Explore` es la app oficial G1/G1_D, pero queda fuera de la ruta MVP por AR8030, autenticación enterprise, dependencia cloud y protocolo binario. La ruta primaria sigue siendo `SDK2/DDS Unicast` hacia `192.168.123.161`.

## 1. Resumen Ejecutivo

Este reporte documenta el análisis sistemático de la aplicación "Unitree Go" como referencia secundaria del plano factory `192.168.12.x`. No define la ruta primaria de control del G1 EDU en OttoGuide RC1; la ruta operativa primaria es `SDK2/DDS Unicast` hacia `192.168.123.161`.

Nota RC1 SRE: la app oficial para G1/G1_D es `Unitree Explore`, pero queda fuera del MVP operativo por AR8030, autenticacion enterprise, dependencia cloud y protocolo binario.

### Hallazgos Clave
- **Red bifurcada:** La aplicación opera sobre dos planos de red aislados: el plano factory (192.168.12.x) para control remoto y el plano autónomo (192.168.123.x) para operación nativa.
- **Protocolo híbrido:** REST/HTTP para control de sesión y comandos; UDP para telemetría en tiempo real; DDS para locomoción nativa.
- **Stack moderno:** OkHttp 4.9.0 con HTTP/2, Retrofit 2.x, WebRTC para video.
- **Seguridad:** Sin TLS observado en análisis estático; autenticación mediante handshake de sesión (investigación pendiente).

---

## 2. Matriz de Conectividad

| Dirección IP | Puerto | Protocolo | Función | Estado |
|--------------|--------|-----------|---------|--------|
| 192.168.12.1 | 9991 | HTTP/1.1 o HTTP/2 | Handshake + REST API Factory | **Confirmado** |
| 192.168.12.1 | TBD | UDP | Telemetría real-time (IMU, estado) | **Pendiente** |
| 192.168.123.161 | 7411-7413 | DDS/CycloneDDS | Locomoción nativa (SDK2) | **Operativo OttoGuide** |
| 192.168.12.1 | TBD | WebSocket/WebRTC | Streaming video | **Detectado en APK** |
| 192.168.123.164 | 60001 | HTTPS/WebRTC | Streaming XR teleoperación | **Documentado** |

### Endpoints REST Factory Identificados

```
GET    /con_check                           → Healthcheck / Handshake inicial
POST   /rest/remote/packet/post/startup     → Iniciar sesión de control
POST   /rest/remote/packet/post             → Enviar comandos de movimiento
GET    /rest/remote/packet/pull             → Recibir estado/telemetría
POST   /rest/remote/packet/updateNick       → Cambiar nickname del robot
```

### Endpoints SDK2 Internos (Extraídos de `text1.json`, `text2.json`)

| API | Código | Función |
|-----|--------|---------|
| `rt/api/sport/request` | 1006 | Reset/Stop |
| `rt/api/sport/request` | 1007 | Control luces (VUI) |
| `rt/api/sport/request` | 1009 | Cambio de modo |
| `rt/api/sport/request` | 1016 | Rotación |
| `rt/api/sport/request` | 1017 | Estiramiento |
| `rt/api/sport/request` | 1022 | Saludo/Mano |
| `rt/api/sport/request` | 1031 | Acción programada #1 |
| `rt/api/sport/request` | 1036 | Acción programada #2 |
| `rt/api/vui/request` | 1007 | Iluminación LED |

---

## 3. Secuencia de Inicialización

### 3.1 Flujo de Handshake (App Oficial)

```
┌─────────────┐     ┌─────────────────┐     ┌──────────────┐
│   Usuario   │────→│  Unitree Go App │────→│ 192.168.12.1 │
└─────────────┘     └─────────────────┘     └──────────────┘
                           │
                           ▼
    ┌────────────────────────────────────────────────────┐
    │ 1. Conexión WiFi a red AP del robot (192.168.12.x) │
    │ 2. GET http://192.168.12.1:9991/con_check         │
    │    └── Verifica disponibilidad del endpoint        │
    │ 3. POST /rest/remote/packet/post/startup          │
    │    └── Establece sesión, posible intercambio token │
    │ 4. Loop keep-alive: GET /rest/remote/packet/pull  │
    │    └── Telemetría + estado de batería, IMU, etc.   │
    │ 5. Comandos: POST /rest/remote/packet/post        │
    │    └── Movimiento, poses, acciones predefinidas    │
    └────────────────────────────────────────────────────┘
```

### 3.2 Secuencia de Comando de Movimiento (Ejemplo Inferido)

```python
# Payload inferido para comando "move" (de text1.json)
{
  "api": "rt/api/sport/request",
  "code": 1006,  # o código específico de acción
  "parameters": {
    "vx": "1",      # Velocidad lineal X
    "vy": "0",      # Velocidad lineal Y
    "vyaw": "0"     # Velocidad angular
  }
}

# Payload para pose (de text1.json)
{
  "api": "rt/api/sport/request",
  "code": 1016,
  "parameters": {
    "roll": "0",
    "pitch": "-0.3141592653589793",  # -18° en radianes
    "yaw": "0",
    "height": "0",
    "seconds": "0.5"
  }
}
```

---

## 4. Estructura de Mensaje

### 4.1 Handshake `/con_check` (Confirmado en OttoGuide RC1)

**Request:**
```http
GET http://192.168.12.1:9991/con_check HTTP/1.1
Host: 192.168.12.1:9991
User-Agent: okhttp/4.9.0
Accept: */*
```

**Response (esperado):**
```http
HTTP/1.1 200 OK
Content-Type: application/json
Content-Length: TBD

{
  "status": "ok",
  "robot_id": "G1-XXXX",
  "firmware_version": "X.X.X"
}
```

### 4.2 Payload de Comando REST (Formato TBD — Requiere Captura Dinámica)

Basado en análisis de clases decompiladas y arquitectura OkHttp/Retrofit:

```
POST /rest/remote/packet/post HTTP/2
Host: 192.168.12.1:9991
Content-Type: application/json  o  application/x-protobuf
Authorization: Bearer <session_token>  # (pendiente confirmar)

{
  "packet_id": "<uuid>",
  "timestamp": <epoch_ms>,
  "type": "movement|pose|action|mode",
  "payload": {
    // Estructura variable según tipo
  }
}
```

### 4.3 Telemetría UDP (Hipótesis)

| Atributo | Valor Esperado |
|----------|----------------|
| IP Destino | `BaseConstant.UDP_IP` (192.168.12.1 o broadcast) |
| Puerto | TBD (8000-9000 range probable) |
| Frecuencia | 50-100 Hz (basado en requerimientos IMU) |
| Formato | Binary packed (posiblemente Protobuf o estructura C) |
| Campos | IMU quaternion, joint positions, battery, temperature |

---

## 5. Stack Tecnológico Identificado

### 5.1 Cliente HTTP
- **OkHttp 4.9.0**: Cliente HTTP moderno con HTTP/2, connection pooling, interceptores
- **Retrofit 2.x**: Abstracción REST sobre OkHttp
- **Gson/Protobuf**: Serialización de payloads (TBD cuál se usa)

### 5.2 Asincronía
- **Kotlin Coroutines**: Para operaciones no-bloqueantes
- **RxJava 3**: Streams reactivos para telemetría continua

### 5.3 UI y Web
- **AgentWeb**: Contenedor web nativo para dashboard Vue.js
- **WebView**: Integración de interfaz web embebida
- **Material Design 3**: Componentes nativos Android

### 5.4 Multimedia
- **WebRTC**: Streaming de video (clase `com.unitree.webrtc.data.repository.RtcRepository`)
- **FFmpegKit**: Procesamiento de audio/video (licencias encontradas)

### 5.5 Reconocimiento de Voz
- **iFlytek**: Motor de reconocimiento de voz chino (archivos `call.bnf`, `grammar_sample.abnf`)
- Gramáticas BNF/ABNF para comandos de voz en chino mandarín

---

## 6. Mapa de Clases Relevantes (APK Decompilado)

```
com.unitree.doggo2/
├── activities/
│   ├── WifiSTAActivity.java          # Gestión WiFi
│   ├── RemoteActivity.java           # Control remoto
│   └── RemoteBindActivity.java       # Pairing
├── viewmodels/
│   └── WebViewModel.kt               # postChunk() para envío de comandos
├── webrtc/
│   └── data/repository/RtcRepository.kt # Streaming video
├── network/
│   ├── BaseConstant.kt               # UDP_IP, constantes de red
│   └── remote/                       # REST API clients
└── services/
    └── ForegroundService.kt          # Keep-alive de sesión
```

---

## 7. Análisis de Seguridad

### 7.1 Observaciones
1. **Sin TLS aparente:** El análisis estático no revela certificados ni configuración HTTPS para el plano factory.
2. **Redes aisladas:** Separación física/lógica entre control remoto (192.168.12.x) y navegación autónoma (192.168.123.x) implementa defensa en profundidad.
3. **Handshake básico:** `con_check` proporciona validación de conectividad pero no autenticación fuerte observable.

### 7.2 Recomendaciones para OttoGuide
- **No reutilizar** credenciales, tokens ni sesiones de Unitree Go sin auditoría completa.
- **Mantener aislamiento:** El plano factory debe permanecer como fuente de diagnóstico secundaria únicamente.
- **Validar entradas:** Todo dato proveniente de 192.168.12.x debe considerarse no confiable hasta validación.
- **Preferir SDK2 nativo:** Para control operativo, utilizar `LocoClient` sobre DDS (192.168.123.161) en lugar de REST factory.

---

## 8. Recomendaciones para Replicación

### 8.1 Requisitos Técnicos para Cliente Python/C++

```python
# Pseudo-implementación de cliente compatible

class UnitreeGoCompatibleClient:
    """Cliente compatible con protocolo Unitree Go v1.12.7"""
    
    # Constantes de red
    FACTORY_IP = "192.168.12.1"
    FACTORY_PORT = 9991
    SDK_IP = "192.168.123.161"
    
    # Endpoints
    ENDPOINT_HANDSHAKE = "/con_check"
    ENDPOINT_STARTUP = "/rest/remote/packet/post/startup"
    ENDPOINT_COMMAND = "/rest/remote/packet/post"
    ENDPOINT_POLL = "/rest/remote/packet/pull"
    
    def __init__(self):
        self.session = httpx.AsyncClient(http2=True)  # HTTP/2 como OkHttp
        self.session.headers.update({
            "User-Agent": "okhttp/4.9.0",  # Spoofing opcional
            "Accept": "application/json"
        })
        self.udp_socket = None  # Para telemetría
        self.session_token = None
    
    async def handshake(self) -> bool:
        """GET /con_check → bool"""
        response = await self.session.get(
            f"http://{self.FACTORY_IP}:{self.FACTORY_PORT}{self.ENDPOINT_HANDSHAKE}"
        )
        return response.status_code == 200
    
    async def start_session(self) -> str:
        """POST /startup → session_token (formato TBD)"""
        # REQUIERE: Análisis dinámico para determinar payload
        pass
    
    async def send_command(self, cmd_type: str, params: dict):
        """POST /rest/remote/packet/post"""
        # REQUIERE: Formato de payload real desde captura
        pass
    
    async def poll_state(self) -> dict:
        """GET /rest/remote/packet/pull"""
        # REQUIERE: Estructura de respuesta real
        pass
```

### 8.2 Dependencias Recomendadas

```toml
# pyproject.toml
[dependencies]
httpx = { version = ">=0.27.0", extras = ["http2"] }  # HTTP/2 support
protobuf = ">=4.25.0"  # Si payloads son protobuf
cyclonedds = ">=0.1.0"  # Para DDS nativo alternativo
asyncio-mqtt = ">=0.16.0"  # Si se detecta MQTT
websockets = ">=12.0"  # Para WebSocket/WebRTC
```

### 8.3 Herramientas de Verificación

```bash
# 1. Validar conectividad básica (implementado en OttoGuide RC1)
curl -v http://192.168.12.1:9991/con_check

# 2. Captura de tráfico para análisis dinámico
sudo tcpdump -i <iface> -s 0 -w unitree_traffic.pcap \
  "host 192.168.12.1 and (tcp port 9991 or udp)"

# 3. Análisis con Wireshark
# - Filtrar: ip.addr == 192.168.12.1 && tcp.port == 9991
# - Verificar: http.request.uri contains "con_check"
# - Inspeccionar: Payloads POST en /rest/remote/packet/post
```

---

## 9. Próximos Pasos y Bloqueadores

### 9.1 Pendientes Críticos

| Tarea | Prioridad | Bloqueador |
|-------|-----------|------------|
| Captura dinámica HIL | **Alta** | Requiere robot físico + app oficial |
| Identificar `BaseConstant.UDP_IP` | **Alta** | Requiere decompilación DEX más profunda o captura |
| Formato payload REST | **Alta** | Requiere MITM proxy o packet capture |
| Secuencia de autenticación | Media | Requiere análisis de startup handshake |
| Heartbeat/keep-alive | Media | Requiere captura prolongada (>60s) |

### 9.2 Metodología Recomendada para Análisis Dinámico

1. **Setup HIL:** Robot G1 en modo seguro + AP factory accesible.
2. **Interceptación:** Burp Suite o mitmproxy si no hay certificate pinning.
3. **Captura pasiva:** tcpdump en interfaz de red de la Companion PC.
4. **Correlación:** Timestamp de acciones en app vs. paquetes capturados.
5. **Fuzzing controlado:** Replicar payloads capturados con variaciones sistemáticas.

---

## 10. Referencias Cruzadas

| Documento | Ubicación |
|-----------|-----------|
| Análisis Preliminar APK | `documentacion general del proyecto/AppPhone/APK_CONNECTIVITY_ANALYSIS.codigo_ottoguide.md` |
| Protocolo HIL | `documentacion general del proyecto/Operaciones_HIL/RUNBOOK_PACKET_CAPTURE_HIL.md` |
| Arquitectura RC1 | `documentacion general del proyecto/Arquitectura/ARQUITECTURA_OPERATIVA_RC1.md` |
| Memoria Técnica | `documentacion general del proyecto/Arquitectura/MEMORIA_ARQUITECTONICA_MVP.md` |
| Cliente Implementado | `codigo ottoguide/src/infrastructure/unitree/factory_rest_client.py` |
| APK Decompilado | `codigo ottoguide/data/AppPhone/unitree_go_apk/` |

---

## 11. Conclusión

El análisis estático del APK Unitree Go v1.12.7 ha revelado una arquitectura de red bifurcada con:

1. **Plano Factory (192.168.12.1:9991):** REST API para control remoto vía app oficial. Endpoints identificados pero formatos de payload pendientes de captura dinámica.

2. **Plano Autónomo (192.168.123.161):** DDS/CycloneDDS para control nativo mediante SDK2 (`unitree_hg` IDL). **Esta es la vía operativa recomendada para OttoGuide.**

3. **Telemetría UDP:** Constante `BaseConstant.UDP_IP` identificada pero valor exacto no extraído; requiere análisis dinámico.

4. **Streaming:** WebRTC para video, documentado en referencias del SDK para teleoperación XR.

**Recomendación Estratégica:** OttoGuide debe mantener el `UnitreeFactoryRestClient` en modo **read-only diagnóstico** (GET /con_check únicamente) y canalizar todo el control operativo a través del SDK2 DDS sobre 192.168.123.161. La replicación completa del protocolo factory requiere captura HIL que no está disponible en el alcance actual.

---

## 12. Análisis de Conectividad WiFi y Acceso SSH

### 12.1 Capacidades Wireless del G1 EDU

El robot **SÍ posee conectividad inalámbrica integrada**, confirmado por múltiples fuentes:

| Tecnología | Especificación | Fuente |
|------------|---------------|--------|
| **WiFi** | Wi-Fi 6 (802.11ax) | Manual de usuario G1 |
| **Bluetooth** | Bluetooth 5.2 | Manual de usuario G1 |
| **Chip WiFi** | Realtek RTL8852BU (`rtl8852bu/wlan0` en árbol `/proc`) | APK decompilado + sistema |

**Referencia documental:** `@c:\Users\lucas\Documents\OttoGuide-Proyecto_SIP-Grupo6-UADE\documentacion general del proyecto\Hardware_Reference\G1-Manual-de-usuario-Transcripcion.md:63`:
> *"El G1 posee... **compatible con Wi-Fi 6 y Bluetooth 5.2**, lo que permite una comunicación inalámbrica eficiente y un intercambio de datos optimizado."*

**Componentes identificados en APK:**
- `WifiSTAActivity` — Selección y conexión a redes Wi-Fi
- `RemoteActivity` — Interfaz de control remoto Bluetooth/WiFi
- `RemoteBindActivity` — Pairing y binding del dispositivo remoto

### 12.2 Aislamiento de Planos de Red (Problema Crítico)

**El WiFi integrado del robot NO proporciona acceso SSH al Ubuntu interno.**

La arquitectura del G1 EDU implementa **dos planos de red estrictamente aislados**:

```
┌─────────────────────────────────────────────────────────────────┐
│  PLANO FACTORY (WiFi del robot)          192.168.12.x            │
│  ├── WiFi integrado del G1 (AP mode)                             │
│  ├── IP: 192.168.12.1 (el robot hace de AP/access point)         │
│  ├── App Unitree Go se conecta aqui como referencia factory       │
│  ├── Endpoints REST: /con_check, /rest/remote/packet/*           │
│  └── **NO TIENE SSH AL UBUNTU INTERNO**                          │
│       ↓                                                          │
│       Esta red queda fuera de la ruta primaria OttoGuide RC1      │
└─────────────────────────────────────────────────────────────────┘
                              ╳ Sin puente documentado
┌─────────────────────────────────────────────────────────────────┐
│  PLANO AUTÓNOMO (Ethernet/DDS)          192.168.123.x            │
│  ├── PC2 Ubuntu interno: 192.168.123.164 ← **SSH disponible**    │
│  ├── Módulo locomoción: 192.168.123.161                          │
│  ├── LiDAR: 192.168.123.20 (contrasta con 192.168.123.120 SRE)   │
│  └── Conexión: RJ45 físico o AP externo en Wireless Bridge       │
│       ↓                                                          │
│       **AQUÍ ESTÁ EL UBUNTU ACCESIBLE POR SSH**                  │
└─────────────────────────────────────────────────────────────────┘
```

### 12.3 Matriz de Acceso por Interfaz

| Interfaz | Plano Red | SSH | SDK2/DDS | App Oficial | Uso Recomendado |
|----------|-----------|-----|----------|-------------|-----------------|
| **WiFi integrado G1** | 192.168.12.x | ❌ No | ❌ No | ✅ Sí | Control remoto app |
| **RJ45 (PC2)** | 192.168.123.x | ✅ Sí | ✅ Sí | ❌ No | Desarrollo, ROS2 |
| **AP Externo + Bridge** | 192.168.123.x | ✅ Sí | ✅ Sí | ❌ No | Desarrollo inalámbrico |

### 12.4 Opciones para Desarrollo Sin RJ45 Permanente

Para acceder al Ubuntu interno (`192.168.123.164`) **sin cable RJ45 dedicado**:

#### Opción A: AP Externo en Wireless Bridge (Recomendado por OttoGuide)

Documentado en `@c:\Users\lucas\Documents\OttoGuide-Proyecto_SIP-Grupo6-UADE\documentacion general del proyecto\Operaciones_HIL\HIL_TESTING_PROTOCOL.md:127`:

> *"Conectar PC de desarrollo a la red LAN aislada del Unitree G1 mediante **AP externo en modo Wireless Bridge conectado al RJ45** del robot."*

**Setup:**
```
[G1 RJ45] ──→ [AP Externo: 192.168.123.1] ←──WiFi── [Laptop Dev: 192.168.123.99]
                                    └── Robot SSH: 192.168.123.164 ✓
```

#### Opción B: Mini Router WiFi Montado en Robot (Comunidad)

Según `@c:\Users\lucas\Documents\OttoGuide-Proyecto_SIP-Grupo6-UADE\documentacion general del proyecto\Hardware_Reference\G1-EDU 信息搜集与分析.md:120`:

> *"Para wireless teleoperation... montar un **mini Wi-Fi router en el G1**, conectarlo al RJ45 y alimentarlo por el **puerto 12V** del robot."*

**Hardware disponible en G1:**
| Puerto | Tipo | Especificación |
|--------|------|----------------|
| 12V | XT30UPB-F | 12V/5A (para router WiFi) |
| RJ45 | 1000 BASE-T | Ethernet al PC2 |

### 12.5 Implicaciones para OttoGuide

**Conclusión operativa:**

1. **WiFi integrado del G1 (192.168.12.x):** referencia factory/app Unitree Go para diagnostico pasivo. No es ruta primaria de control del G1 EDU en OttoGuide RC1 y no expone SSH ni SDK2.

2. **Para desarrollo OttoGuide:** Se requiere conexión a la red `192.168.123.x`, ya sea:
   - RJ45 directo (setup laboratorio)
   - AP externo en Wireless Bridge (setup móvil)
   - Mini router WiFi montado en robot (setup campo)

3. **Los endpoints REST del APK no son vía de ejecución shell:** No permiten comandos bash, acceso al filesystem ni gestión de procesos del Ubuntu interno.

4. **Seguridad por aislamiento:** La separación de planos (192.168.12.x vs 192.168.123.x) es una medida de defensa en profundidad que protege el sistema de control autónomo del robot.

---

**Fin del Reporte**

*Generado: 7 de mayo de 2026 | Analista: Cascade AI | Proyecto: OttoGuide SIP UADE*
*Actualizado: 7 de mayo de 2026 | Sección WiFi/SSH agregada*
