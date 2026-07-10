# AGENTS.md — Reglas de Estructura del Repositorio OttoGuide

## Raíces canónicas

- `docs/` es la **única raíz documental** del repositorio. Toda documentación nueva debe crearse dentro de `docs/`.
- `codigo ottoguide/` es la **raíz del software**: código fuente, scripts, herramientas, configuración runtime, launch files y dependencias vendorizadas.

## Prohibiciones de estructura

- **No recrear** `documentacion general del proyecto/` en ninguna ruta ni profundidad.
- **No recrear** `planificacion/` como directorio independiente fuera de `docs/planning/`.
- **No crear nuevas raíces documentales por pilar** (por ejemplo `docs/domains/motion/`, `docs/domains/ai-voice/`, etc.); la reclasificación semántica profunda está diferida.
- **No crear** `docs/audit/`; la ruta canónica es `docs/audits/`.

## Flujo Git por checkpoints

El repositorio canónico (`tsamaan/OttoGuide-Proyecto_SIP-Grupo6-UADE`) y el mirror
(`LucasCap12/OttoGuide-Proyecto_SIP-Grupo6-G1-EDU`) se sincronizan mediante un flujo de
checkpoints validado repetidamente en el ciclo IA-CXX (R1-R7):

1. **Trabajo local**: crear o modificar contenido en el workspace local, con un único commit
   local por checkpoint una vez que sus propios gates (diff esperado, hash forense si aplica,
   secret scan) pasan.
2. **Revisión local (pre-push review)**: un checkpoint separado revisa el commit local sin
   modificar nada, confirmando diff exacto, ausencia de cambios en archivos protegidos, hash
   forense y secret scan, y emite un veredicto GO/NO-GO.
3. **Push a mirror con confirmación explícita**: solo tras un GO de revisión, un checkpoint de
   staging pide confirmación explícita al usuario (pregunta directa, respuesta afirmativa
   requerida) y ejecuta un único push fast-forward-only, sin force, sin tags, exclusivamente al
   mirror.
4. **Validación**: se verifica el estado del mirror de forma independiente (`git ls-remote`
   propio), sin depender únicamente de una afirmación externa no verificada.
5. **Push a canónico fast-forward con confirmación explícita**: un checkpoint separado pide una
   confirmación explícita nueva (las confirmaciones de checkpoints anteriores no son válidas
   para este push) y ejecuta un único push fast-forward-only, sin force, sin tags,
   exclusivamente al canónico.
6. **Verificación de alineación**: tras el push canónico, se confirma vía `git ls-remote`
   independiente que canónico y mirror quedan en el mismo HEAD.

Todo push a canónico o mirror requiere, sin excepción: preflight (branch, HEAD, working tree
limpio), diff exacto validado contra lo esperado, hash forense de `otto_pipeline.cpp` si el
checkpoint lo toca indirectamente, secret scan high-confidence, confirmación explícita del
usuario pedida en ese mismo checkpoint, fast-forward (nunca force), y sin tags.

## Protocolo por niveles de riesgo

- **Nivel A — documentación pura**: cambios exclusivamente en Markdown/documentación
  (`docs/**`, `AGENTS.md`, `TODO.md`). Riesgo más bajo; puede incluir un commit local por
  checkpoint.
- **Nivel B — código offline de bajo riesgo**: cambios en Python u otro código que no
  compila/ejecuta binarios nativos, sin acceso a red, robot ni hardware.
- **Nivel C — C++ offline, build, ejecución dummy o integración con el supervisor**: incluye
  compilar C++ offline, ejecutar binarios dummy con timeout estricto y autorización explícita
  separada, o integrar un worker C++ con `JsonlInteractionWorkerSupervisor` en modo offline.
  Cada acción de build o ejecución requiere su propia confirmación explícita, incluso dentro
  del mismo checkpoint.
- **Nivel D — robot físico / HIL / movimiento**: cualquier acceso al robot, SSH, ejecución de
  `otto_pipeline.cpp`, movimiento (`/cmd_vel`, `LocoClient.Move`, SDK de locomoción), audio
  real, o modelos reales (Whisper/Ollama/Piper). **Nivel D no puede acelerarse** — no admite
  variantes "-FAST" que salten checkpoints intermedios de verificación, y siempre requiere
  autorización explícita separada de cualquier checkpoint de nivel A-C.

## Fast-track documental de Nivel A

Para reducir latencia operativa durante cierre de MVP, se habilita un fast-track exclusivo para
checkpoints de Nivel A que modifiquen únicamente documentación pura.

### Alcance permitido

El fast-track documental solo aplica si el diff completo toca exclusivamente:

- `docs/**`, excepto `docs/legacy/**`;
- `AGENTS.md`;
- `TODO.md`.

### Alcance prohibido

El fast-track documental queda prohibido si el diff toca cualquier archivo bajo:

- `codigo ottoguide/**`;
- `ottoguide_web_app/**`;
- `docs/legacy/**`;
- cualquier archivo C/C++/Python/JS/TS/shell;
- cualquier configuración runtime;
- cualquier script ejecutable;
- cualquier archivo relacionado con robot, audio, Unitree, ROS, DDS, Nav2, SLAM o HIL.

### Flujo permitido

Un checkpoint fast-track documental puede colapsar revisión, mirror stage y promoción canónica
en un solo checkpoint, siempre que cumpla todos los gates siguientes:

1. preflight local con branch esperado, HEAD esperado y working tree limpio;
2. verificación remota de canónico y mirror antes del cambio;
3. diff acotado exclusivamente a documentación permitida;
4. secret scan high-confidence;
5. commit local único;
6. confirmación explícita literal del usuario en ese mismo checkpoint;
7. push fast-forward-only al mirror;
8. push fast-forward-only al canónico;
9. verificación posterior independiente de que mirror y canónico quedan alineados;
10. reporte de evidencia.

### Límites

El fast-track documental no autoriza build, ejecución, tests, backend, frontend, robot, SSH,
audio, Unitree, movimiento, `/cmd_vel`, `/odom`, `/tf`, force push, tags, merge, rebase ni PRs.

Cualquier cambio de código, runtime, C++, Python, frontend, robot, audio o HIL vuelve
automáticamente al flujo completo por checkpoints separados.

## Gates para robot físico (Nivel D)

Antes de cualquier acceso al robot físico, movimiento o ejecución de HIL:

- Autorización explícita del usuario, pedida en ese mismo checkpoint, con su propio prompt
  autocontenido.
- Hardstop físico disponible y probado antes de cualquier movimiento.
- Operador responsable presente durante la operación.
- Plan de rollback definido antes de ejecutar.
- Límites explícitos de distancia, velocidad y tiempo para cualquier movimiento.
- No mezclar tareas de robot físico con refactors, reorganización documental ni cambios de
  código no relacionados.
- No ejecutar ninguna acción de robot si el working tree está sucio o el repo no está en el
  estado esperado.

## Cambios de arquitectura

Cualquier cambio de arquitectura de software (orquestador, event bus, módulos runtime, interfaces DDS/ROS 2) requiere revisión humana antes de ser mergeado a `canonical`.

## Estado vigente del ciclo IA-CXX

- **R1-R7**: cerrados. Decisión de arquitectura `CXX_PIPELINE_PRIMARY = true`,
  `PYTHON_REIMPLEMENTATION_PRIMARY = false`, `PYTHON_ROLE = supervisor_control_plane`,
  `CXX_ROLE = physical_conversation_runtime`. Runtime C++ productivo bajo
  `codigo ottoguide/src/interaction/cxx_runtime/`, compilado offline (R5) y ejecutado en modo
  dummy de forma controlada sin cambios versionados (R6). Decisión de implementación vigente:
  `NEXT_IMPLEMENTATION_STRATEGY = CXX_PROTOCOL_COMPLIANT_LOOPBACK_WORKER_FIRST` (R7), documentada
  en `docs/Arquitectura/IA_CXX_R7_JSONL_DISPATCH_LOOP_OR_DUMMY_WORKER_INTEGRATION_PLAN.md`.
- **R8** (próximo checkpoint de código real, no ejecutado): implementar un worker C++ loopback
  protocol-compliant bajo `cxx_runtime/`, que hable JSONL real por stdin/stdout de forma
  simulada (sin audio, sin red, sin modelos, sin Unitree), validado primero de forma aislada y
  luego integrado offline con `JsonlInteractionWorkerSupervisor`.
- `otto_pipeline.cpp` no debe modificarse sin un checkpoint específico dedicado a esa decisión.

## Robot compile-only

- Compilar código C++ directamente en el robot físico puede plantearse como un checkpoint
  separado y explícito (por ejemplo, para verificar el toolchain disponible en ese entorno).
- Un checkpoint de tipo compile-only en el robot **no autoriza ejecutar binarios** producidos
  por esa compilación.
- Un checkpoint de tipo compile-only en el robot **no autoriza ningún movimiento**.
- Todo checkpoint compile-only en el robot debe capturar: versión del toolchain (g++/CMake),
  logs completos de compilación, hash forense de `otto_pipeline.cpp` antes y después, y el
  estado del working tree antes y después.

## Archivos protegidos

Los siguientes archivos no deben modificarse sin un checkpoint específico dedicado a esa
decisión:

- `docs/legacy/interaccionia/Ottoguide_IA/src/otto_audio/cpp/otto_pipeline.cpp`
- `docs/legacy/**` en general (evidencia histórica, skeleton no operativo)
- `docs/legacy/interaccionia/Ottoguide_IA/src/otto_audio/cpp/CMakeLists.txt` (build legacy)
- `docs/legacy/interaccionia/Ottoguide_IA/src/otto_audio/scripts/otto_say.sh`
- `codigo ottoguide/src/interaction/runtime_port.py`
- `codigo ottoguide/src/interaction/jsonl_worker_supervisor.py`
- `codigo ottoguide/src/interaction/worker_supervisor.py`

## Regla de evidencia

Los reportes generados fuera del repositorio (evidencia de checkpoints, auditorías externas)
deben resumirse o incorporarse a documentación versionada dentro de `docs/` antes de tratarse
como fuente autoritativa para decisiones futuras.

## Referencia de rama de revisión

La rama activa de integración es `review/orchestrator-unification` en el remote `mirror`.
El análisis de funcionalidades integradas, wiring del orquestador y tests pendientes se realiza sobre esa rama publicada.

## Continuidad de unificación

- Leer `docs/Arquitectura/UNIFICACION_RAMAS_Y_HANDOFF.md` antes de cualquier tarea de unificación.
- Resolver el HEAD activo con `git rev-parse mirror/review/orchestrator-unification`.
- Resolver el checkpoint del handoff con `git log -1 --format=%H -- docs/Arquitectura/unification-state.json`.
- Al cierre de una etapa con escritura correctamente documentada, el checkpoint del handoff debe coincidir con el HEAD activo.
- Nunca exigir que `unification-state.json` contenga el SHA del mismo commit que contiene el JSON.
- Actualizar el handoff Markdown y `unification-state.json` en cada etapa de unificación con escritura.
- Una auditoría read-only no modifica el handoff.
- No depender de carpetas locales de ramas para reconstruir contexto; usar refs de `mirror`.
- Inspeccionar ramas laterales mediante `git show`, `git diff` o `git log` contra refs `mirror/<branch>`.
- No convertir `audit-reports/` externos en fuente autoritativa sin resumir sus resultados en documentación versionada.
