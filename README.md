# OttoGuide

**Tree content status:** `FINAL_RELEASE_TREE`

OttoGuide es un proyecto académico de robot guía para UADE sobre hardware Unitree G1 EDU. Este repositorio conserva el software integrado, la aplicación web, contratos offline, tooling operativo y la evidencia necesaria para entregar y auditar el proyecto sin convertir evidencia histórica u offline en afirmaciones de operación física actual.

El estado de publicación Git (`feature`, `review`, `main`, mirror y canonical) es deliberadamente **dinámico** y no se embebe en este README. Para saber qué refs apuntan actualmente a este árbol hay que consultar GitHub.

## Visión y alcance académico

El MVP original definió un piloto en UADE Monserrat por Lima 3 y Lima 2, con cinco paradas de diálogo predefinidas, IA local/offline durante el recorrido estructurado, interacción libre sólo al finalizarlo y un modelo híbrido en el que Ottoman complementa al guía humano.

Quedaron explícitamente fuera del MVP:

- recorridos por otros pisos o campus;
- respuestas abiertas ilimitadas durante el recorrido estructurado;
- integración con sistemas internos de UADE;
- soporte multiidioma.

Estas son decisiones de alcance del producto académico; no prueban que el recorrido físico o la autonomía hayan sido validados por este árbol.

## Implementado

- Núcleo robótico, runtime, configuración, herramientas y tests bajo `codigo ottoguide/`.
- Aplicación web integrada bajo `ottoguide_web_app/`.
- Contratos offline ODOM/TF P2/P2A/P2C con semántica explícita de frames, covarianza, readiness, claims y provenance.
- Arquitectura de interacción supervisada y mecanismos de seguridad/versionado documentados.
- Documentación, auditorías, HIL histórico y provenance de unificación bajo `docs/`.

## Validado offline

El árbol incluye tests y evidencia offline para los contratos que efectivamente ejercita. En particular, P2C fija límites de software y provenance para ODOM/TF.

`VALIDADO_OFFLINE` no equivale a publicación física de sensores, ejecución Nav2, SLAM físico ni autonomía del robot.

## Validación física histórica

Existen sesiones históricas con observaciones del entorno Unitree, sensores e integración. Se preservan bajo `docs/Operaciones_HIL/` y documentación relacionada.

Esa evidencia conserva valor de provenance, pero **no recertifica** automáticamente este árbol exacto.

## No validado físicamente por este árbol

No se reclama como validado actualmente:

- publicación física de `/odom`, `/tf`, `/tf_static` o `/map`;
- navegación autónoma Nav2;
- SLAM/map actual ni recorrido físico completo;
- audio o cámara reales del árbol final;
- comportamiento DDS/ROS en vivo del árbol final;
- despliegue físico exacto de este Git tree.

Cualquier claim físico futuro requiere una sesión HIL nueva y explícitamente autorizada.

## Estructura

```text
.
|- AGENTS.md
|- README.md
|- TODO.md
|- .github/
|- codigo ottoguide/
|- ottoguide_web_app/
`- docs/
```

`docs/` es la única raíz documental propia. `codigo ottoguide/` y `ottoguide_web_app/` son las dos raíces de software establecidas.

## Modelo Git de entrega

La historia completa de desarrollo e integración se conserva en:

```text
review/orchestrator-unification
```

La entrega final usa:

```text
main = SINGLE_ROOT_FINAL_RELEASE
```

El commit final de `main` debe ser un root sin padres cuyo tree sea exactamente el mismo árbol final auditado que conserva `review`. Mirror y canonical deben terminar con el mismo SHA/tree.

La secuencia y los gates están definidos en [`docs/Arquitectura/CIERRE_FINAL_MVP.md`](docs/Arquitectura/CIERRE_FINAL_MVP.md). El estado remoto concreto se verifica en GitHub y no forma parte de la verdad estática de este archivo.

## Estado de desarrollo

```text
BRANCH_RECONCILIATION = CLOSED
PRODUCTIVE_DEVELOPMENT = CLOSED
ACTIVE_PRODUCTIVE_NEXT_ACTION = NO_FURTHER_PRODUCTIVE_DEVELOPMENT
```

Las ramas históricas permanecen como provenance. Su existencia no constituye trabajo pendiente ni autorización para reabrir desarrollo.
