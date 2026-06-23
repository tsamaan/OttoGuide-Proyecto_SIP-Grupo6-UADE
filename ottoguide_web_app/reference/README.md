# reference/ — Material de referencia (NO se ejecuta)

Estos archivos **no forman parte del backend ni del frontend** y no se usan en
tiempo de ejecución. Están acá solo como **fuente para la integración real**,
para que quien implemente los `TODO` tenga el código que ya funciona como guía.

## Archivos

- **`dds_reader.py`** — Lector DDS del monitor PyQt que ya tenemos andando.
  Se suscribe al tópico `rt/lowstate` del robot con `unitree_sdk2py` (rama
  `unitree_hg` para el G1) y arma el diccionario de telemetría.

  Es la referencia del punto **D1** de la integración: para implementar
  `backend/app/services/telemetry_source.py` hay que **portar esta lógica**,
  sacándole toda la parte de PyQt (`QThread`, `pyqtSignal`), convertirla en un
  lector que cachee el último paquete y exponga un `get_frame()` que devuelva
  **exactamente el mismo schema JSON** que produce hoy el mock
  (`backend/app/mock/mock_telemetry.py`).

- **`joint_maps.py`** — Mapa de motores (Go2 / G1) que usa el `dds_reader.py`.
  Sirve para entender cómo se nombran y agrupan los motores. En el monorepo, el
  equivalente ya está en `backend/app/mock/mock_telemetry.py` y en
  `frontend/src/data/jointMaps.js`.

## Importante

- No agregar estos archivos al `Dockerfile` ni importarlos desde `app/`.
- Son solo lectura/guía. El contrato real entre back y front es el **schema JSON
  del frame**, que tiene que quedar idéntico al del mock.
