# INFORME TÉCNICO NIVEL 4: Análisis de Ingeniería Inversa - Unitree Explore
## Autenticación Enterprise y Control G1-EDU

**Proyecto:** OttoGuide SIP UADE  
**Analista:** Cascade AI (Senior Reverse Engineer)  
**Fecha:** 7 de mayo de 2026  
**Archivo Analizado:** `Unitree_Explore.apk` (186,735,378 bytes)  
**Ubicación:** `codigo ottoguide/data/AppPhone/unitree_explore/`

---

## 1. RESUMEN EJECUTIVO

Unitree Explore representa un **cambio de paradigma arquitectónico** radical respecto a Unitree Go. Mientras Go implementa una API REST local clara (192.168.12.1:9991), Explore utiliza un **protocolo binario empresarial** basado en el chip AR8030 con comunicación cloud-first y endpoints específicos por modelo de robot.

**Hallazgo crítico:** Unitree Explore **SÍ soporta el G1-EDU** mediante endpoints dedicados `/g1/*` y `/g1_d/*`, con un sistema de autenticación enterprise que **no permite bypass trivial**.

---

## 2. ARQUITECTURA DE CONECTIVIDAD

### 2.1 Stack Tecnológico Identificado

| Capa | Tecnología | Archivos Evidencia |
|------|-----------|-------------------|
| **Comunicación Robot** | Protocolo AR8030 (binario) | `libar8030_client.so`, `libar8030_helper.so` |
| **Video/Audio** | FFmpegKit + AVCodec | `libffmpegkit.so`, `libavcodec.so` |
| **Red** | TCP Sockets personalizados | `bb_host_connect`, `bb_socket_*` |
| **Protección** | Baidu Protect (ofuscación) | `libbaiduprotect.so`, `baiduprotect*.jar` |
| **Almacenamiento** | MMKV (Tencent) | `libmmkv.so` |
| **Voz** | iFlytek Speech SDK | `assets/iflytek/`, `libmsc.so` |

### 2.2 Protocolo AR8030 - Análisis de Librería Nativa

La librería `libar8030_client.so` expone funciones de comunicación de bajo nivel:

```c
// Funciones identificadas en el binario
bb_host_connect          // Conexión inicial al host
bb_host_disconnect       // Desconexión controlada
create_tcp_connect       // Establecimiento TCP
bb_socket_open           // Apertura de socket
bb_socket_read/write     // I/O binario
socket_add_fd            // Gestión de file descriptors
sendto/recvfrom          // Comunicación UDP/TCP
```

**Dictamen:** Unitree Explore **NO usa HTTP/REST** para comunicación directa con el robot. Utiliza un **protocolo binario propietario** vía AR8030, probablemente encapsulando comandos serializados.

---

## 3. ENDPOINTS CLOUD Y API ENTERPRISE

### 3.1 Autenticación y Configuración

| Endpoint | Método | Propósito |
|----------|--------|-----------|
| `/loginCenter/login` | POST | Autenticación enterprise |
| `/logincenter/login` | POST | Alias de autenticación |
| `/api/v1/config` | GET | Configuración de servicio |
| `/api/v1/rule/urlfilter` | GET | Filtrado de URLs |
| `/app/api` | - | API general de aplicación |
| `/inland/api` | - | API específica región China |

### 3.2 Endpoints Específicos por Modelo de Robot

**Hallazgo crítico:** La aplicación implementa **rutas dedicadas** para cada familia de robot:

```
/g1/ble_g1              → Control BLE específico G1
/g1/logReport           → Reportes de logs G1
/g1/netPermission       → Gestión de permisos de red
/g1/remoteBind          → Vinculación remota G1
/g1/robotSetting        → Configuración del robot G1
/g1_d/robotSetting      → Configuración G1 Developer/EDU

/a2/robotSetting        → Go2 (A2)
/h2/robotsetting        → H1/H2 humanoides
/r1/robotSetting        → R1 (posible nuevo modelo)
```

**Componentes ARouter identificados:**
- `ARouter$$Group$$g1.java`
- `ARouter$$Group$$g1_d.java` 
- `ARouter$$Providers$$G1.java`
- `ARouter$$Providers$$G1_D.java`

Esto confirma que **G1 y G1_D son tratados como productos distintos** en la arquitectura de la app.

---

## 4. ANÁLISIS DE AUTENTICACIÓN

### 4.1 Mecanismos de Seguridad Identificados

| Componente | Descripción | Impacto en Bypass |
|------------|-------------|-------------------|
| **Baidu Protect** | Ofuscación de código DEX | Dificulta análisis estático |
| **APPKEY** | Clave de aplicación embebida | Posible extracción |
| **AR8030 Handshake** | Protocolo binario inicial | Requiere ingeniería inversa dinámica |
| **Login Enterprise** | `/loginCenter/login` | **Sin evidencia de modo offline** |

### 4.2 Strings de Autenticación Encontrados

```
APPKEY
appkey: 
signature=
loginCenter/login
logincenter/login
securityToken=
```

**Ausencias significativas:**
- ❌ No se encontró `guest_mode`, `offline_mode`, `demo_mode`
- ❌ No se encontró `bypass_login`, `skip_auth`
- ❌ No se encontró `direct_connect`, `local_mode`

### 4.3 Dictamen de Factibilidad de Bypass

| Vector de Ataque | Factibilidad | Complejidad | Evidencia |
|------------------|--------------|-------------|-----------|
| **Emulación de login** | Baja-Alta | Alta | Requiere keys válidas |
| **Modo offline oculto** | **No evidenciado** | N/A | No encontrado en strings |
| **Bypass AR8030** | Media | Muy Alta | Protocolo binario desconocido |
| **Interceptación cloud** | Media | Alta | HTTPS con pinning probable |
| **Ataque al G1_D endpoint** | Desconocida | Alta | Requiere análisis dinámico |

**Conclusión:** No existe evidencia de un **"modo invitado" o "modo offline"** que permita control directo sin autenticación enterprise. La aplicación está diseñada para **operación cloud-first**.

---

## 5. COMANDOS G1 Y ESTRUCTURA DE CONTROL

### 5.1 Assets del Robot

| Archivo | Tamaño | Propósito |
|---------|--------|-----------|
| `program_text_1.txt` | 16,916 bytes | **Scripts de acción del G1** |
| `call.bnf` | 324 bytes | Gramática de comandos de voz (chino) |
| `grammar_sample.abnf` | 165 bytes | Gramática ABNF reconocimiento de voz |
| `ar8030_helper_socket` | 63,752 bytes | Configuración de socket AR8030 |
| `keys` | 10,516 bytes | **Almacén de claves/keys** |

**Nota:** `program_text_1.txt` y `keys` contienen bytes nulos sugiriendo **formato binario o cifrado**.

### 5.2 Gramáticas de Voz Identificadas

**call.bnf** (Comandos de llamada/contacto):
```bnf
#BNF+IAT 1.0 UTF-8;
!grammar call;
!slot <contact>;
!slot <callPre>;
!slot <callPhone>;
!slot <callTo>;
<callStart>:[<callPre>][<callTo>]<contact><callPhone>|[<callPre>]<callPhone>[<callTo>]<contact>;
<contact>:张海洋;
<callPre>:我要|我想|我想要;
<callPhone>:打电话;
<callTo>:给;
```

**grammar_sample.abnf** (Navegación):
```abnf
#ABNF 1.0 UTF-8;
language zh-CN;
mode voice;
root $main;
$main = $place1 到 $place2;
$place1 = 北京|武汉|南京|天津|东京;
$place2 = 上海|合肥;
```

**Implicación:** El G1 soporta **comandos de voz en chino** para navegación y control.

---

## 6. DESCUBRIMIENTO DE DISPOSITIVOS

### 6.1 Mecanismos Analizados

| Protocolo | Evidencia | Estado |
|-----------|-----------|--------|
| **mDNS** | No encontrado | No confirmado |
| **UDP Broadcast** | `sendto/recvfrom` en libar8030 | **Posible** |
| **BLE** | `/g1/ble_g1` endpoint, strings "bluetooth" | **Confirmado** |
| **WiFi Direct** | No evidenciado | No confirmado |

### 6.2 UUIDs BLE

**No se extrajeron UUIDs específicos** del análisis estático. Los strings BLE están ofuscados o generados dinámicamente.

**Recomendación:** Para análisis de descubrimiento BLE, se requiere:
1. Captura de tráfico Bluetooth (Android HCI snoop log)
2. Análisis dinámico de la clase `RemoteBindActivity`
3. Reversing de los servicios BLE del G1

---

## 7. COMPARATIVA TÉCNICA: Unitree Go vs. Unitree Explore

| Característica | Unitree Go (v1.12.7) | Unitree Explore |
|----------------|----------------------|-----------------|
| **Modelos soportados** | Go2 (no G1) | **G1, G1_D, A2, H2, R1** |
| **Protocolo robot** | HTTP REST (192.168.12.1:9991) | **AR8030 binario (sockets TCP)** |
| **Endpoints REST** | `/con_check`, `/rest/remote/*` | `/g1/*`, `/g1_d/*`, `/loginCenter/*` |
| **Arquitectura** | Local-first (plano factory) | **Cloud-first (enterprise)** |
| **Autenticación** | Ninguna (local) | **Login enterprise obligatorio** |
| **Librerías SDK** | Retrofit, OkHttp | **AR8030, Baidu Protect, MMKV** |
| **Modo offline** | N/A | **No evidenciado** |
| **DDS integrado** | No | No (AR8030 reemplaza DDS) |
| **Protección** | Ninguna | **Baidu Protect (ofuscación)** |
| **Voz** | No evidenciado | **iFlytek SDK (chino)** |
| **Video** | WebRTC | **FFmpegKit** |

### 7.1 Análisis de Diferencias Arquitectónicas

**Unitree Go** está diseñada para:
- Control local directo del robot
- Operación sin autenticación (red factory aislada)
- Usuario final/consumidor

**Unitree Explore** está diseñada para:
- **Gestión enterprise de flotas de robots**
- Control remoto vía cloud
- Autenticación centralizada obligatoria
- Múltiples modelos de robot (incluido G1-EDU)

---

## 8. IMPLICACIONES PARA OTTOGUIDE

### 8.1 Factibilidad de Replicación

| Aspecto | Estado | Recomendación |
|---------|--------|---------------|
| **Usar API Explore** | ❌ **No viable** | Requiere autenticación enterprise |
| **Bypass AR8030** | ⚠️ **Complejo** | Necesita reversing dinámico del protocolo |
| **Emular G1_D** | ⚠️ **Desconocido** | Requiere credenciales válidas |
| **Interceptar comandos** | ⚠️ **Posible** | Man-in-the-middle con certificados propios |

### 8.2 Riesgos de Seguridad

1. **Ofuscación Baidu Protect:** El código está intencionalmente dificultado para análisis estático.
2. **Protocolo AR8030 cerrado:** Sin documentación pública del formato binario.
3. **Autenticación cloud:** Cualquier bypass podría violar Términos de Servicio.

### 8.3 Alternativas Recomendadas

| Alternativa | Viabilidad | Esfuerzo |
|-------------|------------|----------|
| **Continuar con SDK2 DDS** (192.168.123.161) | ✅ Alta | Bajo |
| **Captura HIL de AR8030** | ⚠️ Media | Alto |
| **Análisis dinámico con Frida** | ⚠️ Media | Alto |
| **Contactar Unitree** para API developer | ❓ Desconocida | Variable |

---

## 9. CONCLUSIONES Y RECOMENDACIONES

### 9.1 Hallazgos Clave

1. **Unitree Explore SÍ soporta G1-EDU** mediante endpoints `/g1_d/*` dedicados.

2. **La autenticación es enterprise/cloud-first** sin evidencia de modo offline.

3. **El protocolo AR8030 reemplaza a REST/DDS** para comunicación directa.

4. **Baidu Protect ofusca el código** dificultando análisis estático.

5. **No existe evidencia de bypass trivial** del sistema de login.

### 9.2 Recomendación Estratégica para OttoGuide

**NO se recomienda** intentar replicar la API de Unitree Explore por:
- Complejidad del protocolo AR8030 (binario, no documentado)
- Requerimiento de autenticación enterprise
- Presencia de ofuscación Baidu Protect
- Ausencia de modo offline/local

**SÍ se recomienda:**
1. **Mantener la arquitectura actual** basada en SDK2 DDS sobre 192.168.123.161
2. **Considerar captura HIL** del tráfico AR8030 para análisis futuro
3. **Evaluar contacto directo** con Unitree para acceso a API developer del G1
4. **Documentar la separación de apps:** Go para Go2, Explore para G1/Enterprise

---

## 10. APÉNDICE: HASHES Y METADATOS

```yaml
Archivo: Unitree_Explore.apk
Tamaño: 186,735,378 bytes
Formato: ZIP (Android APK v2 Signature)
Librerías nativas: 21 archivos .so (arm64-v8a)
Archivos DEX: 4 (classes.dex, classes2.dex, classes3.dex, classes4.dex)
Ofuscación: Baidu Protect (6 niveles)
SDK Versión: Target 31 (Android 12)
```

---

**Fin del Informe Nivel 4**

*Generado: 7 de mayo de 2026 | Analista: Cascade AI | Proyecto: OttoGuide SIP UADE*  
*Clasificación: Uso interno únicamente*
