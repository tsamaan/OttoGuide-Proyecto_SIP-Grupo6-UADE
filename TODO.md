# TODO - Backlog Tecnico OttoGuide RC1+

## Estado

`RC1_LOCKED`: no ejecutar refactors funcionales durante operacion fisica salvo correcciones de estabilidad HIL. No ejecutar `git add`, `git commit` ni `git push` sin orden explicita.

## HIL Mapping

- Validar en robot fisico que `livox_ros_driver2` publica `/scan`; si no, agregar nodo explicito de conversion Livox `PointCloud2` -> `LaserScan`.
- Confirmar que `slam_toolbox` publica `/map` dentro de `HIL_READY_TIMEOUT_S`.
- Registrar duracion real, tamanio de bag y checksums de mapa en cada prueba HIL.
- Agregar comando de validacion post-captura para inspeccionar `metadata.yaml` del bag MCAP.
- Automatizar reporte de calidad de mapa: resolucion, dimensiones, ocupacion y continuidad.
- Documentar resultado de la prueba fisica de mapeo en `HIL_TESTING_PROTOCOL.md`.

## Unitree APK / Factory Plane

- Ejecutar `RUNBOOK_PACKET_CAPTURE_HIL.md` con app Unitree Go oficial y guardar `.pcap` de handshake, telemetria basal y accion minima.
- Extraer valor real de `BaseConstant.UDP_IP` desde bytecode o captura dinamica.
- Identificar puertos UDP, frecuencia, tamanio y direccion de paquetes factory.
- Determinar si `/rest/remote/packet/*` usa HTTP/1.1, HTTP/2 cleartext, payload JSON, Protobuf o binario encapsulado.
- Mapear secuencia de sesion: `/con_check`, `/startup`, `post`, `pull`, ACKs, heartbeats y cierre.
- Documentar autenticacion, tokens, nonce o binding si aparecen en captura.
- Mantener `UnitreeFactoryRestClient` en modo read-only hasta completar payload/ACK/autenticacion.
- Evaluar parser pasivo de telemetria UDP como fuente secundaria de `/status`, sin control de locomocion.
- Correlacionar telemetria factory con DDS/ROS2: bateria, modo FSM, IMU, odometria y estado de control remoto.
- Determinar si existe puente observable entre `192.168.12.x` y `192.168.123.x`.

## Audio / LLM Voice Output

- Validar fisicamente `unitree_sdk2py.g1.audio.g1_audio_client.AudioClient.TtsMaker(text, speaker_id)` en G1 EDU.
- Medir idioma soportado, latencia, volumen, calidad y limite de longitud de `TtsMaker`.
- Corregir o envolver comportamiento de `AudioClient.tts_index`; el SDK actual hace `self.tts_index += self.tts_index`, lo que mantiene indice `0`.
- Validar `AudioClient.SetVolume()` y `GetVolume()` en entorno HIL.
- Validar `AudioClient.PlayStream()` con WAV PCM mono `16 kHz` usando `example/g1/audio/g1_audio_client_play_wav.py`.
- Crear `UnitreeAudioAdapter` separado de locomocion, con singleton de conexion SDK2 si comparte `ChannelFactoryInitialize`.
- Definir politica de fallback: `AudioClient.TtsMaker` -> Piper local -> silencio controlado.
- Integrar salida del LLM a `AudioClient` solo si no bloquea `TourOrchestrator` ni interfiere con `LocoClient`.
- Agregar tests con mock de `AudioClient` para TTS nativo, volumen y fallback.

## Arquitectura / Refactor Post-RC1

- Consolidar definitivamente `hardware/real_adapter.py` y `src/hardware/robot_hardware_api.py` bajo un solo contrato.
- Formalizar `src/infrastructure/unitree/` como frontera para SDK2, REST factory, UDP factory y audio nativo.
- Evitar imports cruzados entre `api/` legacy y `src/api/`; definir una unica superficie FastAPI.
- Convertir readiness de `/tour/start` en servicio de aplicacion testeable.
- Agregar `/status` extendido con estado de Nav2, mapa cargado, sensores y diagnostico factory.
- Auditar que `/cmd_vel_nav` sea consumido por el controlador fisico esperado antes de navegacion autonoma.
- Agregar metricas de latencia: `Damp()`, `Move()`, Nav2 goal result, AMCL update y telemetria WebSocket.
- Separar MVC formalmente: modelos de dominio, controladores de caso de uso, vistas HTTP/WS.

## Seguridad Operativa

- Mantener prohibicion de control simultaneo: app oficial, control remoto manual y OttoGuide `/tour/start`.
- Agregar checklist GO/NO-GO especifico para mapeo con responsable de hardstop.
- Medir latencia real de `Damp()` en robot suspendido.
- Validar que `Ctrl+C` en `hil_capture_mapping_bundle.sh` cierra recorder antes de guardar mapa.
- Validar que `timeout 60 map_saver_cli` es suficiente en mapa UADE real.
- Incorporar resultado de `HIL_DRY_RUN=1` como prerequisito antes de prueba fisica.

## Documentacion

- Actualizar `APK_CONNECTIVITY_ANALYSIS.md` con resultados de `.pcap`.
- Actualizar `ROS2_INTEGRATION.md` si se integra `AudioClient`.
- Actualizar `README.md` cuando `UnitreeAudioAdapter` pase de backlog a runtime.
- Mantener `TODO.md` como backlog post-RC1 y no como runbook operativo.
