# IA-CXX-R13A — Fortalecimiento de assertions de payload en el test supervisor↔shim

## Objetivo

Corregir la observación no bloqueante registrada en R12B
(`OBSERVATION_PAYLOAD_TEXT_NOT_ASSERTED`): el test de integración de R12A
(`test_u3d_cxx_jsonl_shim_supervisor.py`) validaba la presencia de los eventos
`TRANSCRIPT_READY`/`RESPONSE_READY` en la secuencia observada, pero no el contenido textual
exacto de sus payloads mock (`"hola otto"` / `"respuesta mock"`).

## Archivos modificados

- `codigo ottoguide/tests/integration/test_u3d_cxx_jsonl_shim_supervisor.py` (modificado) —
  `_collect_until` ahora acumula los `WorkerEventEnvelope` completos en vez de solo sus tipos
  de evento, y `test_activate_reaches_mock_playback_completed` assertea el texto exacto de los
  payloads `transcript_ready`/`response_ready`.
- `docs/Arquitectura/IA_CXX_R13A_PAYLOAD_ASSERTIONS.md` (nuevo, este documento).

Ningún archivo de producción Python (`runtime_port.py`, `jsonl_worker_supervisor.py`,
`worker_supervisor.py`) fue modificado. `otto_jsonl_shim.cpp` y su `CMakeLists.txt` tampoco
fueron modificados. Ningún archivo bajo `docs/legacy/**` fue tocado.

## Cambio técnico

`WorkerEventEnvelope` (definido en `runtime_port.py`, sin cambios) ya expone el campo
`payload: Mapping[str, object]` en el objeto retornado por `supervisor.next_event()`. El test
de R12A descartaba ese campo, quedándose solo con `envelope.event` en la lista `seen`. La
corrección es puramente de test: `_collect_until` retorna ahora la lista de envelopes
completos, y el test deriva de ahí tanto la lista de tipos de evento (para las assertions de
secuencia ya existentes) como los payloads exactos:

```python
transcript_ready = next(
    envelope for envelope in seen if envelope.event is WorkerEventType.TRANSCRIPT_READY
)
assert transcript_ready.payload["text"] == "hola otto"

response_ready = next(
    envelope for envelope in seen if envelope.event is WorkerEventType.RESPONSE_READY
)
assert response_ready.payload["text"] == "respuesta mock"
```

No fue necesario ningún cambio de producción Python, protocolo, ni del shim C++: los payloads
mock ya estaban hardcodeados en `otto_jsonl_shim.cpp` desde R11 (revisado y aprobado en R11B),
y el contrato del protocolo ya transportaba esos valores sin restricciones adicionales.

## Cobertura preservada

Los 4 tests de R12A se mantienen íntegros: `test_start_reaches_ready_with_mock_capabilities`,
`test_health_command_accepted`, `test_activate_reaches_mock_playback_completed` (fortalecido),
`test_close_reaches_closed_state`. La secuencia completa de eventos
(`wake_word_confirmed → capture_started → transcript_ready → response_ready →
playback_started → playback_completed`) sigue validada exactamente igual que en R12A.

## Confirmación de alcance

- No se modificó `runtime_port.py`, `jsonl_worker_supervisor.py` ni `worker_supervisor.py`.
- No se modificó `otto_jsonl_shim.cpp` ni su `CMakeLists.txt`.
- No se modificó `otto_pipeline.cpp` ni ningún archivo bajo `docs/legacy/**`.
- No se usó robot, SSH, audio real, Unitree, ni modelos reales (Whisper/Ollama/Piper).
- No se publicó `/cmd_vel`, `/odom` ni `/tf`.
- El binario `otto_jsonl_shim` usado en la ejecución de este test fue compilado offline en un
  directorio de build aislado dentro de la evidencia del checkpoint, y no fue instalado ni
  dejado en el árbol del repositorio.
