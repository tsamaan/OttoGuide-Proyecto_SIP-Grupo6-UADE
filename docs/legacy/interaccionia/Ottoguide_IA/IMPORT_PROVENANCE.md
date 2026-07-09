# Procedencia de la recuperacion de Ottoguide_IA

## Fuente

Snapshot recuperado de un repositorio independiente entregado
por un integrante del equipo OttoGuide.

Repositorio original:
tsamaan/ottoguide-ia

Rama interna:
main

HEAD interno:
4bf6d394a1bbb2cac14b847bf0eed53411550a78

## Implementacion principal

Archivo:
src/otto_audio/cpp/otto_pipeline.cpp

SHA-256:
0d1cc4567387f4bc41e3705d95c16d80be2e61d76fe2ea99dbe8a9fa6a926bcf

## Estado de validacion

La implementacion fue reportada por el equipo como probada
fisicamente en un robot Unitree G1 EDU.

Esta importacion no repitio pruebas HIL, no accedio al robot
y no ejecuto el codigo recuperado.

## Arquitectura historica

Audio del robot por UDP multicast -> Whisper local -> Ollama local,
modelo "otto" -> Piper local en espanol -> AudioClient.PlayStream ->
parlante integrado del robot.

No utiliza OpenAI, Gemini ni servicios cloud como parte del
pipeline funcional recuperado.

## Exclusiones

No se importaron:

- repositorio .git interno;
- historial Git interno;
- credenciales;
- entorno .venv;
- SDKs y repositorios de terceros;
- builds;
- recordings;
- caches;
- binarios;
- backups operativos.

## Seguridad

El repositorio interno contenia credenciales historicas.
Sus valores no fueron incorporados ni reproducidos.

La publicacion remota permanece condicionada a la confirmacion
de revocacion o rotacion de esas credenciales.

## Relacion con la implementacion unificada

Este snapshot se conserva como referencia funcional HIL historica.

No se asume equivalencia automatica con la implementacion Python
actual ni se conecta al runtime unificado mediante este commit.

## Whitespace histórico preservado

La sustitución del gitlink por archivos normales hace que Git evalúe el
snapshot recuperado como contenido agregado. Por ese motivo,
`git diff --check` informa espacios finales y una línea vacía al final
de archivo que ya estaban presentes en el snapshot original.

No se normalizaron los archivos funcionales para conservar su contenido
byte a byte. En particular, `src/otto_audio/cpp/otto_pipeline.cpp`
mantiene el SHA-256:

`0d1cc4567387f4bc41e3705d95c16d80be2e61d76fe2ea99dbe8a9fa6a926bcf`

La excepción se limita exclusivamente a hallazgos reproducibles contra
el snapshot forense archivado. Cualquier whitespace nuevo continúa
considerándose bloqueante.
