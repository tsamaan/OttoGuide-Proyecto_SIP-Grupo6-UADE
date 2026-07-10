# IA-CXX-R14B — Cobertura mock de rechazo semántico y timeout

## Objetivo

Cerrar los dos gaps de protocolo identificados en R14/R14A que quedaban sin cobertura desde R11:

- `ERR_SEMANTIC_REJECTED` (modelado en el protocolo desde R11, nunca implementado en el shim).
- `interaction_timeout` (evento existente en el protocolo desde R5, nunca emitido por el shim).

Este checkpoint implementa ambos caminos como rutas mock determinísticas dentro de
`otto_jsonl_shim.cpp`, sin tocar producción Python ni `otto_pipeline.cpp`.

## Diseño ALT_2_INTERACTION_ID_RESERVED

Seleccionado en R14A (`IA_CXX_R14A_DECISION.md`) entre 4 alternativas evaluadas. El shim mock
reconoce dos valores reservados de `interaction_id` en el comando `activate` y, según cuál
reciba, dispara determinísticamente una de las dos rutas nuevas en vez del flujo feliz:

```text
interaction_id == "itx-r14-semantic-reject"
  -> command_accepted -> failed (interaction_id no-nulo, code="ERR_SEMANTIC_REJECTED",
     message no vacío) -> supervisor vuelve a READY

interaction_id == "itx-r14-timeout"
  -> command_accepted -> interaction_timeout (interaction_id no-nulo, payload estable
     y finito) -> supervisor vuelve a READY

cualquier otro interaction_id -> flujo feliz sin cambios (idéntico a R11/R12A/R13A)
```

## interaction_id reservados

```text
itx-r14-semantic-reject
itx-r14-timeout
```

Ambos están reservados exclusivamente para este mecanismo de cobertura mock offline. No son ni
serán identifiers de producción: la integración real con `otto_pipeline.cpp` (cuando se diseñe,
como `OPTION_B`, diferida en R14) usará su propio mecanismo de generación de `interaction_id`,
nunca estos literales hardcodeados.

## Por qué no se tocó Python

`runtime_port.py` ya acepta `failed` con cualquier `code` no vacío/acotado (sin restricción
sobre el valor específico) y `interaction_timeout` como evento de interacción sin requisitos de
payload adicionales — confirmado por inspección directa en R14A antes de escribir ningún código.
`jsonl_worker_supervisor.py` ya procesa correctamente ambos eventos según su `interaction_id`:
`FAILED` con `interaction_id` no-nulo y `INTERACTION_TIMEOUT` devuelven el supervisor a `READY`;
solo `FAILED` con `interaction_id=null` se trata como fallo de proceso. Ningún archivo Python fue
modificado en este checkpoint.

## Por qué no se tocó otto_pipeline.cpp

El alcance de R14B es exclusivamente cobertura de protocolo en el shim *mock*. Acercarse a la
lógica real de `otto_pipeline.cpp` (p. ej. el algoritmo real de validación semántica) se
identificó como riesgo en R14A (`RISK_5`) y queda explícitamente fuera de este checkpoint y
prohibido por el prompt que lo generó.

## Por qué no hay sleeps largos

El timeout es *simulado*: el shim emite `interaction_timeout` de inmediato al reconocer el
`interaction_id` reservado, sin esperar ningún intervalo real. Esto evita alargar los tests y
evita cualquier interacción con `heartbeat_timeout_s` (default 5.0s en
`jsonl_worker_supervisor.py`) — mitigación de `RISK_2` de R14A.

## Cobertura C++

`shim_mock_protocol_smoke.cpp` agrega:

- `static_assert` de los wire-strings `failed` e `interaction_timeout`.
- Caso de rechazo semántico: verifica `event == "failed"`, `interaction_id` no-nulo con el valor
  reservado, y `payload.code == "ERR_SEMANTIC_REJECTED"`.
- Caso de timeout: verifica `event == "interaction_timeout"` e `interaction_id` no-nulo con el
  valor reservado.
- Ambos casos verifican ausencia de saltos de línea embebidos y de literales NaN/Infinity.

## Cobertura Python

`test_u3d_cxx_jsonl_shim_supervisor.py` agrega:

- `test_activate_with_reserved_id_emits_semantic_rejection`: activa con
  `interaction_id="itx-r14-semantic-reject"`, espera `failed` con `interaction_id` no-nulo,
  `payload["code"] == "ERR_SEMANTIC_REJECTED"`, mensaje no vacío, confirma ausencia de eventos
  del flujo feliz (`transcript_ready`, `response_ready`, `playback_completed`), y confirma que
  el supervisor vuelve a `READY` (el worker no termina).
- `test_activate_with_reserved_id_emits_interaction_timeout`: análogo para
  `interaction_id="itx-r14-timeout"` y evento `interaction_timeout`.
- Los 4 tests preexistentes (R12A/R13A) permanecen sin cambios, incluyendo las aserciones
  literales de payload `"hola otto"` / `"respuesta mock"` (R13A).

## Gates

- Smoke C++ y pytest offline nuevos pasan.
- Flujo feliz R13 intacto (mismos 4 tests, mismas aserciones de payload).
- Sin sleeps largos en ningún camino nuevo.
- Build y pytest exit code 0.
- Secret scan de alta confianza sin coincidencias.
- Hash de `otto_pipeline.cpp` sin cambios.
- Sin robot, SSH, audio real, Unitree, Whisper/Ollama/Piper reales.
- Sin `/cmd_vel`, `/odom`, `/tf`.
- Commit local sin push.

## Limitaciones

- Este mecanismo es exclusivamente para el shim *mock*; no define cómo la integración real con
  `otto_pipeline.cpp` determinará semánticamente cuándo rechazar una interacción o cuándo
  declarar un timeout real — eso queda para un checkpoint futuro de integración real
  (`OPTION_B`, diferida en R14).
- Los `interaction_id` reservados son literales de test; cualquier extensión futura de este
  mecanismo (más rutas mock) debería seguir el mismo patrón de prefijo `itx-r14-*` o definir un
  nuevo prefijo igualmente documentado, para evitar colisiones accidentales.

## No robot / no audio / no Unitree / no modelos reales / no /cmd_vel / no /odom / no /tf

Confirmado: este checkpoint no usó robot, SSH, audio real, micrófono, parlantes, Whisper real,
Ollama real, Piper real, Unitree SDK, ni publicó `/cmd_vel`, `/odom`, ni `/tf`. Todo el trabajo
fue compilación y ejecución offline de un binario mock más pruebas Python contra ese binario.
