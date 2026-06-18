# TODO - Backlog Post-RC1 OttoGuide

Estado: RC1_LOCKED. Este documento opera como backlog de tareas Post-RC1 y requerimientos de validación HIL. No ejecutar refactors funcionales, transacciones Git ni cambios de control físico sin orden explícita.

## Leyenda de estados

- `DONE_CONFIRMED`: tarea ya implementada o validada por auditoría/código.
- `DECIDED_NOT_IMPLEMENT`: tarea descartada por decisión arquitectónica explícita.
- `PENDING_HIL`: requiere robot físico, ROS 2 runtime, sensores o captura HIL.
- `PENDING_DOC`: requiere actualización documental.
- `PENDING_CODE`: requiere cambio de código post-RC1.
- `OBSOLETE`: tarea superada por decisiones posteriores.
- `UNKNOWN_REQUIRES_REVIEW`: no hay evidencia suficiente para clasificar.

## PENDING_HIL

- [PENDING_HIL] Validar en robot fisico que `ottoguide_livox_sdk_bridge` publica `/utlidar/cloud` y `/livox/imu`; luego habilitar conversion `PointCloud2` -> `LaserScan` para `/scan`.
- [PENDING_HIL] Confirmar que `slam_toolbox` publica `/map` dentro de `HIL_READY_TIMEOUT_S`.
- [PENDING_HIL] Registrar duracion real, tamanio de bag y checksums de mapa en cada prueba HIL.
- [PENDING_HIL] Ejecutar `RUNBOOK_PACKET_CAPTURE_HIL.md` con app Unitree Go oficial y guardar `.pcap` de handshake, telemetria basal y accion minima.
- [PENDING_HIL] Extraer valor real de `BaseConstant.UDP_IP` desde bytecode o captura dinamica.
- [PENDING_HIL] Identificar puertos UDP, frecuencia, tamanio y direccion de paquetes factory.
- [PENDING_HIL] Determinar si `/rest/remote/packet/*` usa HTTP/1.1, HTTP/2 cleartext, payload JSON, Protobuf o binario encapsulado.
- [PENDING_HIL] Mapear secuencia de sesion: `/con_check`, `/startup`, `post`, `pull`, ACKs, heartbeats y cierre.
- [PENDING_HIL] Correlacionar telemetria factory con DDS/ROS2: bateria, modo FSM, IMU, odometria y estado de control remoto.
- [PENDING_HIL] Determinar si existe puente observable entre `192.168.12.x` y `192.168.123.x`.
- [PENDING_HIL] Validar fisicamente `unitree_sdk2py.g1.audio.g1_audio_client.AudioClient.TtsMaker(text, speaker_id)` en G1 EDU.
- [PENDING_HIL] Medir idioma soportado, latencia, volumen, calidad y limite de longitud de `TtsMaker`.
- [PENDING_HIL] Validar `AudioClient.SetVolume()` y `GetVolume()` en entorno HIL.
- [PENDING_HIL] Validar `AudioClient.PlayStream()` con WAV PCM mono `16 kHz` usando `example/g1/audio/g1_audio_client_play_wav.py`.
- [PENDING_HIL] Auditar que `/cmd_vel_nav` sea consumido por el controlador fisico esperado antes de navegacion autonoma.
- [PENDING_HIL] Medir latencia real de `Damp()` en robot suspendido.
- [PENDING_HIL] Validar que `ENTER` en `hil_capture_mapping_bundle.sh` cierra recorder antes de guardar mapa; validar `Ctrl+C` como aborto controlado por separado.
- [PENDING_HIL] Validar que `timeout 60 map_saver_cli` es suficiente en mapa UADE real.
- [PENDING_HIL] Validar en sesion fisica fuente real para `/odom` o canal DDS HG con pose/twist corporal.
- [PENDING_HIL] Medir extrinseco `base_link` -> `utlidar_lidar`.
- [PENDING_HIL] Validar presencia, frecuencia y frame semantics de `/tf`, `/tf_static`, `/odom`, `/map` y `/map_metadata` en runtime real.

## PENDING_DOC

- [PENDING_DOC] Auditar `planificacion/` para decidir si se mantiene como carpeta raiz academica o si se documenta su indice interno.
- [PENDING_DOC] Auditar documentacion HTML externa del pilar IA/voz antes de integrarla como documentacion vigente.
- [PENDING_DOC] Incorporar HTML externo `documento-tecnico-ottoguide-movimiento.html` solo si aparece en workspace y aporta valor historico no cubierto por reportes existentes.
- [PENDING_DOC] Documentar resultado de la prueba fisica de mapeo en `HIL_TESTING_PROTOCOL.md`.
- [PENDING_DOC] Documentar autenticacion, tokens, nonce o binding si aparecen en captura.
- [PENDING_DOC] Agregar checklist GO/NO-GO especifico para mapeo con responsable de hardstop.
- [PENDING_DOC] Incorporar resultado de `HIL_DRY_RUN=1` como prerequisito antes de prueba fisica.
- [PENDING_DOC] Actualizar `APK_CONNECTIVITY_ANALYSIS.md` con resultados de `.pcap`.
- [PENDING_DOC] Actualizar `ROS2_INTEGRATION.md` si se integra `AudioClient`.
- [PENDING_DOC] Actualizar `README.md` cuando `UnitreeAudioAdapter` pase de backlog a runtime.
- [PENDING_DOC] Completar replay/SLAM offline con artifact ODOM/TF si se reinyecta una captura posterior o bags con `/scan` + `/tf` + `/odom`.

## PENDING_CODE

- [PENDING_CODE] Agregar comando de validacion post-captura para inspeccionar `metadata.yaml` del bag MCAP.
- [PENDING_CODE] Automatizar reporte de calidad de mapa: resolucion, dimensiones, ocupacion y continuidad.
- [PENDING_CODE] Corregir o envolver comportamiento de `AudioClient.tts_index`; el SDK actual hace `self.tts_index += self.tts_index`, lo que mantiene indice `0`.
- [PENDING_CODE] Crear `UnitreeAudioAdapter` separado de locomocion, con singleton de conexion SDK2 si comparte `ChannelFactoryInitialize`.
- [PENDING_CODE] Definir politica de fallback: `AudioClient.TtsMaker` -> Piper local -> silencio controlado.
- [PENDING_CODE] Integrar salida del LLM a `AudioClient` solo si no bloquea `TourOrchestrator` ni interfiere con `LocoClient`.
- [PENDING_CODE] Agregar tests con mock de `AudioClient` para TTS nativo, volumen y fallback.
- [PENDING_CODE] Consolidar definitivamente `hardware/real_adapter.py` y `src/hardware/robot_hardware_api.py` bajo un solo contrato.
- [PENDING_CODE] Consolidar `api/` vs `src/api/` y eliminar superficie FastAPI legacy cuando exista plan de migracion validado.
- [PENDING_CODE] Consolidar `hardware/` vs `src/hardware/` sin romper mocks, tests ni adaptadores HIL.
- [PENDING_CODE] Formalizar `src/infrastructure/unitree/` como frontera para SDK2, REST factory, UDP factory y audio nativo.
- [PENDING_CODE] Evitar imports cruzados entre `api/` legacy y `src/api/`; definir una unica superficie FastAPI.
- [PENDING_CODE] Convertir readiness de `/tour/start` en servicio de aplicacion testeable.
- [PENDING_CODE] Agregar `/status` extendido con estado de Nav2, mapa cargado, sensores y diagnostico factory.
- [PENDING_CODE] Agregar metricas de latencia: `Damp()`, `Move()`, Nav2 goal result, AMCL update y telemetria WebSocket.
- [PENDING_CODE] Separar MVC formalmente: modelos de dominio, controladores de caso de uso, vistas HTTP/WS.
- [PENDING_CODE] Implementar `odom_bridge` solo si se confirma una fuente traslacional valida; debe quedar deshabilitado por defecto y no publicar `/cmd_vel`.

## DONE_CONFIRMED

- [DONE_CONFIRMED] Mantener `UnitreeFactoryRestClient` en modo read-only hasta completar payload/ACK/autenticacion.
- [DONE_CONFIRMED] Mantener prohibicion de control simultaneo: app oficial, control remoto manual y OttoGuide `/tour/start`.
- [DONE_CONFIRMED] Mantener `TODO.md` como backlog post-RC1 y no como runbook operativo.
- [DONE_CONFIRMED] Consolidar documentacion propia del proyecto bajo `documentacion general del proyecto/`.
- [DONE_CONFIRMED] Eliminar `docs/` como ubicacion documental vigente.
- [DONE_CONFIRMED] Aplicar raiz limpia con carpetas raiz principales `codigo ottoguide/`, `documentacion general del proyecto/` y `planificacion/`.
- [DONE_CONFIRMED] Mover tooling/config/launch propios bajo `codigo ottoguide/`.
- [DONE_CONFIRMED] Mirror Lucas `main` sincronizado una vez con canónico `robot` en `89c4c7f`.
- [DONE_CONFIRMED] Remotos locales no canonicos eliminados para evitar push accidental.

## DECIDED_NOT_IMPLEMENT

- [DECIDED_NOT_IMPLEMENT] Unitree Explore como ruta MVP operativa: descartada por decision arquitectonica RC1; la app oficial G1/G1_D queda fuera del MVP por AR8030, autenticacion enterprise, dependencia cloud y protocolo binario.

## OBSOLETE

- Sin items existentes clasificados como `OBSOLETE` en esta reestructuracion.

## UNKNOWN_REQUIRES_REVIEW

- [UNKNOWN_REQUIRES_REVIEW] Evaluar parser pasivo de telemetria UDP como fuente secundaria de `/status`, sin control de locomocion.
- [UNKNOWN_REQUIRES_REVIEW] Auditar repo/rama externa del pilar IA/voz (`ottoguide-ia`) antes de cualquier merge o integracion con `audio_bridge.py`.
- [UNKNOWN_REQUIRES_REVIEW] Revisar si `robot_ssh.py` puede convertirse en herramienta sanitizada versionable o debe permanecer local.
- [UNKNOWN_REQUIRES_REVIEW] Evaluar si `LowState`/`SportModeState` aportan datos suficientes para odometria o solo IMU/FSM/joints.

## Reglas de operación

- Este backlog no desbloquea ni bloquea por si solo `RC1_LOCKED`; clasifica trabajo post-RC1 y validaciones HIL pendientes.
- Las tareas `PENDING_HIL` requieren robot fisico, operador responsable, hardstop disponible y autorizacion explicita.
- Las tareas `PENDING_CODE` no deben ejecutarse durante operacion fisica ni sin autorizacion separada de refactor post-RC1.
- Las tareas relacionadas con plano factory deben permanecer read-only hasta que exista evidencia HIL y autorizacion explicita.
- No mezclar reorganizacion documental/tooling con cambios funcionales de audio, ROS package o control fisico.
- Todo cambio de estructura debe preservar rutas en scripts o actualizar referencias con validacion.
- No ejecutar `git add`, `git commit`, `git push`, `merge`, `rebase`, comandos de locomocion, `/cmd_vel`, `LocoClient.Move` ni `/rest/remote/packet/*` desde este backlog.
