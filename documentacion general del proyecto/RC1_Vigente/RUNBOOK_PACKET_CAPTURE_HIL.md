# RUNBOOK Packet Capture HIL - Unitree Factory Plane

## 1. Objetivo

Capturar trafico real de la app oficial Unitree Go contra el plano factory del robot (`192.168.12.x`) para completar el analisis dinamico pendiente del APK. La captura es pasiva. OttoGuide no debe emitir comandos por `/rest/remote/packet/*` durante este procedimiento.

```text
// @TASK: Capturar trafico factory Unitree Go en HIL fisico.
// @INPUT: Companion PC/controlador principal con acceso RJ45 al plano 192.168.12.x.
// @OUTPUT: Archivo .pcap transferible a estacion local para Wireshark.
// @CONTEXT: Completa analisis dinamico de red pendiente tras integracion estatica RC1.
// @SECURITY: Captura pasiva; no solapar comandos ROS2/DDS con app oficial.
```

## 2. Prerrequisitos

1. Robot energizado y mecanicamente asegurado segun `HIL_TESTING_PROTOCOL.md`.
2. Companion PC o controlador principal conectado por RJ45 al segmento factory `192.168.12.x`.
3. Red ROS2/DDS `192.168.123.x` aislada del plano factory durante la prueba.
4. Acceso SSH estable al host donde se ejecutara `tcpdump`.
5. `tcpdump` instalado.
6. Espacio libre minimo recomendado: `2 GB`.
7. App oficial Unitree Go instalada en el telefono de prueba.
8. Operador con control fisico de emergencia disponible.

Validacion minima:

```bash
// @TASK: Validar herramientas y espacio antes de capturar.
// @INPUT: Host HIL conectado por SSH.
// @OUTPUT: Version de tcpdump y espacio libre disponible.
// @SECURITY: No inicia captura ni toca locomocion.
command -v tcpdump
df -h .
```

## 3. Identificacion de Interfaz

Listar interfaces:

```bash
// @TASK: Listar interfaces de red y direcciones asignadas.
// @INPUT: Sistema Linux de la Companion PC/controlador.
// @OUTPUT: Tabla compacta con interfaz, estado e IP.
// @CONTEXT: Identificar enlace hacia 192.168.12.x.
ip -br addr
```

Identificar ruta hacia el AP factory:

```bash
// @TASK: Resolver interfaz usada para alcanzar 192.168.12.1.
// @INPUT: Host destino factory 192.168.12.1.
// @OUTPUT: Ruta kernel con campo dev=<interfaz>.
// @CONTEXT: La interfaz resultante se usa como PCAP_IFACE.
ip route get 192.168.12.1
```

Listar interfaces reconocidas por `tcpdump`:

```bash
// @TASK: Confirmar nombre de interfaz compatible con tcpdump.
// @INPUT: tcpdump instalado.
// @OUTPUT: Lista numerada de interfaces capturables.
tcpdump -D
```

Exportar interfaz seleccionada:

```bash
// @TASK: Fijar interfaz de captura.
// @INPUT: Valor dev obtenido por ip route get.
// @OUTPUT: Variable PCAP_IFACE lista para tcpdump.
// @CONTEXT: Reemplazar eth0 por la interfaz real.
export PCAP_IFACE="eth0"
```

Validar conectividad basica:

```bash
// @TASK: Validar reachability ICMP hacia plano factory.
// @INPUT: PCAP_IFACE configurada y host 192.168.12.1 alcanzable.
// @OUTPUT: Respuesta ping o falla explicita.
// @SECURITY: No valida comandos de control; solo conectividad IP.
ping -c 3 -I "${PCAP_IFACE}" 192.168.12.1
```

## 4. Preparacion de Captura

Crear directorio de salida:

```bash
// @TASK: Crear directorio local para pcap HIL.
// @INPUT: Sistema de archivos de la Companion PC/controlador.
// @OUTPUT: Directorio ~/ottoguide_pcaps disponible.
mkdir -p "${HOME}/ottoguide_pcaps"
```

Definir nombre de archivo:

```bash
// @TASK: Definir path de captura con timestamp UTC.
// @INPUT: Fecha del sistema.
// @OUTPUT: Variable PCAP_OUT con ruta .pcap.
export PCAP_OUT="${HOME}/ottoguide_pcaps/unitree_factory_$(date -u +%Y%m%dT%H%M%SZ).pcap"
```

Definir puerto SSH usado para control remoto:

```bash
// @TASK: Definir puerto SSH a excluir del pcap.
// @INPUT: Puerto de la sesion SSH activa.
// @OUTPUT: Variable SSH_PORT lista para filtro tcpdump.
// @SECURITY: Evita capturar trafico de administracion propio.
export SSH_PORT="${SSH_PORT:-22}"
```

## 5. Ejecucion de Captura

Comando exacto de captura:

```bash
// @TASK: Capturar trafico Unitree factory relevante.
// @INPUT: PCAP_IFACE, PCAP_OUT, SSH_PORT.
// @OUTPUT: Archivo .pcap con trafico host 192.168.12.1 TCP/9991 y UDP.
// @CONTEXT: Aisla handshake /con_check, REST factory y telemetria UDP.
// @SECURITY: Excluye SSH; captura pasiva sin inyeccion de paquetes.
sudo tcpdump -i "${PCAP_IFACE}" -s 0 -nn -w "${PCAP_OUT}" \
  "host 192.168.12.1 and (tcp port 9991 or udp) and not tcp port ${SSH_PORT}"
```

Modo recomendado con rotacion por tiempo:

```bash
// @TASK: Capturar durante 5 minutos y cerrar automaticamente.
// @INPUT: PCAP_IFACE, PCAP_OUT, SSH_PORT.
// @OUTPUT: .pcap cerrado sin requerir Ctrl+C.
// @CONTEXT: Preferido para sesiones repetibles.
timeout 300 sudo tcpdump -i "${PCAP_IFACE}" -s 0 -nn -w "${PCAP_OUT}" \
  "host 192.168.12.1 and (tcp port 9991 or udp) and not tcp port ${SSH_PORT}"
```

Validar archivo resultante:

```bash
// @TASK: Verificar existencia y tamano del pcap.
// @INPUT: PCAP_OUT.
// @OUTPUT: Metadata de archivo y conteo preliminar de paquetes.
ls -lh "${PCAP_OUT}"
tcpdump -nn -r "${PCAP_OUT}" | head -40
```

## 6. Operacion Movil Durante Captura

Secuencia estricta:

1. Iniciar `tcpdump` antes de abrir la app Unitree Go.
2. Conectar el telefono a la red oficial/factory requerida por Unitree Go.
3. Abrir Unitree Go.
4. Esperar handshake inicial. Objetivo esperado: trafico hacia `192.168.12.1:9991`, incluyendo `/con_check`.
5. Navegar hasta pantalla de control remoto o estado.
6. Mantener la app activa al menos `60 s` para capturar telemetria basal.
7. Ejecutar una accion minima de movimiento solo si el robot esta mecanicamente asegurado.
8. Registrar minuto/segundo exacto de cada accion en una nota externa.
9. Cerrar la app o desconectar telefono.
10. Detener `tcpdump` con `Ctrl+C` si no se uso `timeout`.

Restricciones:

```text
// @SECURITY: No ejecutar /tour/start durante captura con app oficial activa.
// @SECURITY: No publicar comandos ROS2 /cmd_vel ni /cmd_vel_nav durante operacion movil.
// @SECURITY: No mezclar control remoto manual, app oficial y OttoGuide autonomous control.
// @CONTEXT: La captura busca observar protocolo factory, no validar locomocion OttoGuide.
```

## 7. Extraccion a Estacion Local

Desde la estacion local de desarrollo:

```bash
// @TASK: Copiar pcap desde Companion PC/controlador a estacion local.
// @INPUT: Usuario SSH, host remoto y ruta PCAP_OUT.
// @OUTPUT: Archivo .pcap disponible para Wireshark local.
// @CONTEXT: Reemplazar unitree@192.168.123.161 y ruta por valores reales.
scp unitree@192.168.123.161:/home/unitree/ottoguide_pcaps/unitree_factory_YYYYMMDDTHHMMSSZ.pcap .
```

Si el acceso de gestion ocurre por otra IP:

```bash
// @TASK: Copiar pcap usando IP administrativa alternativa.
// @INPUT: IP SSH real de la Companion PC/controlador.
// @OUTPUT: .pcap local.
scp unitree@<IP_ADMINISTRATIVA>:/home/unitree/ottoguide_pcaps/*.pcap .
```

Validar integridad local:

```bash
// @TASK: Confirmar lectura offline del pcap.
// @INPUT: Archivo .pcap copiado.
// @OUTPUT: Primeros paquetes decodificados.
tcpdump -nn -r unitree_factory_YYYYMMDDTHHMMSSZ.pcap | head -40
```

## 8. Analisis Offline en Wireshark

Filtros iniciales:

```text
ip.addr == 192.168.12.1
tcp.port == 9991
udp && ip.addr == 192.168.12.1
http.request.uri contains "con_check"
http2
```

Objetivos de analisis:

1. Confirmar handshake `GET /con_check`.
2. Identificar si `/rest/remote/packet/*` usa HTTP/1.1, HTTP/2 cleartext o encapsulacion adicional.
3. Identificar puertos UDP, frecuencia, direccion y tamanos de payload.
4. Correlacionar timestamps con acciones moviles registradas.
5. Documentar si existe puente observable entre `192.168.12.x` y `192.168.123.x`.
6. No derivar comandos OttoGuide hasta entender autenticacion, ACKs y payloads.

## 9. Cierre Operativo

Checklist final:

- [ ] `tcpdump` detenido.
- [ ] `.pcap` existe y tiene tamano mayor que `0`.
- [ ] `.pcap` fue copiado a estacion local.
- [ ] Acciones moviles registradas con timestamps.
- [ ] OttoGuide no ejecuto `/tour/start` durante captura.
- [ ] No hubo control simultaneo ROS2/DDS y app oficial.
- [ ] Hallazgos cargados en `APK_CONNECTIVITY_ANALYSIS.md`.
