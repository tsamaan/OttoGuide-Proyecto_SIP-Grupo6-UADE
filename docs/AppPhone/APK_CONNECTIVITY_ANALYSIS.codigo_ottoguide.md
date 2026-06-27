# Análisis de Conectividad - Unitree Go APK v1.12.7

## Resumen Ejecutivo

Este documento detalla el analisis de ingenieria inversa del APK de la aplicacion Unitree Go (v1.12.7) como referencia secundaria del plano factory `192.168.12.x`. No documenta la ruta primaria de control del G1 EDU para OttoGuide RC1.

**Hallazgos clave:**
- La aplicación opera en una red separada (192.168.12.1) del stack de navegación autónoma (192.168.123.x)
- Utiliza un stack HTTP moderno (OkHttp 4.9.0, Retrofit 2.x) para control remoto
- Implementa UDP como capa de transporte para telemetría en tiempo real
- Soporta WebRTC para streaming de video
- El protocolo es híbrido: REST para control/estado, UDP para telemetría

**Aclaracion RC1:** Unitree Explore es la app oficial para G1/G1_D, pero queda fuera de la ruta MVP operativa por AR8030, autenticacion enterprise, dependencia cloud y protocolo binario. La ruta primaria de OttoGuide es `SDK2/DDS Unicast` hacia `192.168.123.161`.

## Estado de Integracion RC1

La fase de integracion estatica en Capa 4 fue completada en OttoGuide RC1:

- Se agrego `UnitreeFactoryRestClient` como cliente singleton de diagnostico.
- El cliente esta gobernado por `UNITREE_FACTORY_DIAGNOSTICS_ENABLED`.
- El unico endpoint habilitado es `GET http://192.168.12.1:9991/con_check`.
- El resultado se expone como telemetria secundaria en `/status.factory_rest`.
- No se implementaron comandos sobre `/rest/remote/packet/post/startup`.
- No se implementaron comandos sobre `/rest/remote/packet/post`.
- No se implemento consumo operativo de `/rest/remote/packet/pull`.
- No se reutilizan sesiones, credenciales ni payloads propietarios de Unitree Go.
- El SDK local confirma una ruta nativa de audio independiente del APK: `AudioClient.TtsMaker` para TTS y `AudioClient.PlayStream` para PCM.

Pendiente exclusivo: analisis dinamico de red mediante captura `tcpdump`/Wireshark en HIL fisico. El objetivo pendiente es identificar payloads, puertos UDP, direccion real de `BaseConstant.UDP_IP`, handshake y ACKs sin emitir ordenes desde OttoGuide por el plano factory.

---

## Estructura del APK

### Información General
- **Nombre del paquete**: com.unitree.doggo2
- **Versión**: 1.12.7
- **API target**: 29-35 (AndroidX compatible)
- **Tipo de distribución**: XAPK (incluye splits de idioma y arquitectura)

### Componentes Principales del APK

#### Ficheros Base
- **base.apk** (~60MB decompilados)
  - Implementación principal de la aplicación
  - Contiene 4 archivos DEX (clases Kotlin/Java compiladas) totalizando ~37MB

#### Splits de Configuración
- **Language splits** (20 idiomas): es, en, fr, ja, zh, pt, ru, ko, etc.
- **Architecture split**: arm64_v8a (optimización para ARM de 64 bits)

### Archivos de Configuración
- **AndroidManifest.xml**
  ```
  package: com.unitree.doggo2
  minSdkVersion: 29
  targetSdkVersion: 35
  ```

### Permisos Requeridos
```
INTERNET
ACCESS_WIFI_STATE, CHANGE_WIFI_STATE (gestión de redes)
CAMERA, RECORD_AUDIO (multimedia)
BLUETOOTH, BLUETOOTH_ADMIN, BLUETOOTH_CONNECT, BLUETOOTH_SCAN (BLE)
ACCESS_FINE_LOCATION, NEARBY_WIFI_DEVICES (localización)
FOREGROUND_SERVICE (servicios en primer plano)
```

### Assets Incluidos
- **program_text_1.txt**: Editor visual de comportamientos del robot
- **dist/**: Dashboard Vue.js web para control remoto vía navegador
- **Resources**: Mapas de configuración, tags de identificación

---

## Hallazgos de Conectividad

### Topología de Red

#### Red de Control Remoto (Unitree App)
- **IP del robot/AP**: 192.168.12.1
- **Puerto de validación**: 9991
- **Endpoint de validación**: `GET http://192.168.12.1:9991/con_check`
  - Verifica conectividad básica con el robot
  - Utilizado durante handshake inicial

#### Red de Navegación Autónoma (OttoGuide Stack)
- **IP del módulo de navegación**: 192.168.123.161
- **Middleware HIL G1**: ROS 2 Foxy + CycloneDDS (unicast)
- **Nota Humble**: ROS 2 Humble queda restringido a host de desarrollo, SITL o documentacion historica; no es el runtime nativo HIL del G1 EDU.
- **Independiente** de la red de control remoto

### Endpoints REST

#### Ruta Base
```
POST   /rest/remote/packet/post/startup    → Iniciar sesión
POST   /rest/remote/packet/post             → Enviar comandos
GET    /rest/remote/packet/pull             → Recibir datos/estado
POST   /rest/remote/packet/updateNick       → Cambiar nickname del robot
```

**Protocolo**: HTTP/2 (vía OkHttp 4.9.0)
**Formato**: TBD - requiere análisis de payloads (potencialmente Protocol Buffers o JSON)

### Capa de Transporte

#### HTTP Stack
- **OkHttp 4.9.0**
  - HTTP/2 support
  - Connection pooling
  - Interceptores para logging/seguridad
  - Socket factory personalizado

- **Retrofit 2.x**
  - Abstracción de REST sobre OkHttp
  - Conversión automática de objetos (Gson, Protobuf)

#### UDP
- **Constante**: BaseConstant.UDP_IP
- **Propósito**: Presumiblemente telemetría en tiempo real, IMU, odometría
- **IP exacta**: Requiere extracción adicional de constantes (ver sección Metodología)

#### WebRTC
- **Clases**: com.unitree.webrtc.data.repository.RtcRepository
- **Propósito**: Streaming de video desde cámaras del robot
- **Stack**: Implementación estándar WebRTC con candidate gathering

---

## Stack de Tecnología

### Lenguaje de Programación
- **Kotlin** (lenguaje principal)
- **Java** (librerías heredadas)

### Asincronía y Reactividad
- **Kotlin Coroutines**: Para operaciones asincrónicas
- **RxJava 3**: Para streams reactivos

### UI
- **AgentWeb**: Contenedor web nativo
- **WebView**: Para integrar dashboard Vue.js
- **Material Design 3**: Componentes nativos

### Bases de Datos
- **Room** (probable): Para almacenamiento local
- **SharedPreferences**: Para configuración

### Servicios Externos
- **Firebase**: Analytics, Crashlytics
- **Google Play Services**: Localización, mapas

---

## Componentes Identificados

### Actividades (Activities)
| Componente | Función |
|-----------|---------|
| WifiSTAActivity | Selección y conexión a redes Wi-Fi |
| RemoteActivity | Interfaz de control remoto Bluetooth/WiFi |
| RemoteBindActivity | Pairing y binding del dispositivo remoto |
| AgentWeb Container | Dashboard web integrado |

### ViewModels
- **WebViewModel**: Gestiona estado remoto, postChunk() para envío de comandos

### Servicios
- **ForegroundService** (probable): Mantiene conexión viva
- **BoundService**: Para IPC con actividades

### IPC
- **LocalBroadcastManager**: Comunicación entre componentes

---

## Análisis de Seguridad Preliminar

### Observaciones
1. **Red separada**: Control remoto aislado de navegación (defensa en profundidad)
2. **HTTP/2**: Mejor que HTTP/1.1 pero sin TLS visible en el análisis estático
3. **Permisos limitados**: Sigue principio de menor privilegio
4. **Conectividad validada**: con_check es mecanismo de handshake básico

### Recomendaciones para OttoGuide
- **No reutilizar** credenciales/sesiones de Unitree Go
- **Validar** completamente toda entrada proveniente de la red de control remoto
- **Mantener aislada** la navegación autónoma de la red 192.168.12.1
- **Usar mTLS** si se requiere comunicación encrypted entre módulos

---

## Metodología de Análisis

### Herramientas Utilizadas
1. **APK Decompiler**: Extracción de estructura XAPK
2. **dex2jar / CFR**: Descompilación de bytecode DEX a Java/Kotlin readable
3. **Regex String Extraction**: Búsqueda de patrones de conectividad en binarios

### Proceso
1. Extraer base.apk y splits de config
2. Decompile classes.dex → classes4.dex (~37MB bytecode)
3. Buscar keywords: con_check, 9991, rest/remote/packet, UDP_IP, BaseConstant
4. Mapear clases encontradas a funcionalidad
5. Documentar endpoints y topología de red

### Limitaciones
- Análisis de bytecode no revelará protocolos binarios (requeriría packet sniffing)
- Constantes de IP UDP extraíbles pero requieren búsqueda en BaseConstant
- Formato de payload REST aún TBD (requiere reverse engineering de requests)

---

## Próximos Pasos para Análisis Detallado

1. **Extraer BaseConstant.UDP_IP** valor exacto
2. **Capturar tráfico de red** (tcpdump/Wireshark) durante operación normal
3. **Reverse engineer formatos de payload** REST y UDP
4. **Mapear máquina de estados** de control remoto
5. **Documentar handshake de sesión** y mecanismos de autenticación

---

## Referencias

- **Directorio del análisis**: `codigo ottoguide/data/AppPhone/`
- **Memoria técnica**: `memoria/repo/robot_humanoide.md`
- **Protocolo HIL**: `documentacion general del proyecto/RC1_Vigente/HIL_TESTING_PROTOCOL.md`
- **APK original**: `AppPhone/Unitree Go_1.12.7_APKPure.xapk`
- **Decompilados**: `AppPhone/unitree_go_apk/` (base.apk decompilado)

---

**Análisis completado**: 5 de mayo de 2026
**Integracion estatica Capa 4**: completada en RC1_LOCKED; queda pendiente solo analisis dinamico de red
**Analizador**: GitHub Copilot
**Estado RC1**: Analisis estatico integrado; se requiere packet capture para detalles de protocolo
**Estado**: Análisis estático completado; se recomienda packet capture para detalles de protocolo
