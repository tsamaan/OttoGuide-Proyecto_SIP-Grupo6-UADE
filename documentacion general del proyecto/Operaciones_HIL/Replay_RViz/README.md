# Replay RViz

Indice de visualizacion offline para evidencia HIL, rosbags y configuraciones RViz.

## Proposito

Usar RViz para inspeccionar rosbags, clouds, LaserScan y TF sintetico de diagnostico. Esta carpeta no valida navegacion fisica ni mapa navegable.

## Documentos

| Documento | Uso |
|---|---|
| `RVIZ_REPLAY_TROUBLESHOOTING_2026-06-09.md` | Troubleshooting de replay RViz y configuraciones 2D/cloud. |

## Configuraciones

Las configuraciones RViz versionadas viven en:

```text
codigo ottoguide/tools/hil/rviz/
```

## Entradas esperadas

- Rosbag local o replay simulado.
- Config RViz versionada bajo `codigo ottoguide/tools/hil/rviz/`.
- TF real solo si proviene de evidencia HIL; TF identidad solo como diagnostico offline.

## Comandos seguros

```bash
bash "codigo ottoguide/tools/hil/open_rviz_config.sh" 2d
bash "codigo ottoguide/tools/hil/open_rviz_config.sh" current
bash "codigo ottoguide/tools/hil/replay_rosbag_rviz_slow.sh"
```

Guardar capturas de pantalla, logs de replay y configuracion RViz usada como evidencia local.

## Uso seguro

- Usar RViz solo para inspeccion offline o replay local.
- No conectar RViz a una sesion fisica con Nav2 activo sin autorizacion explicita.
- No tratar TF identidad o mapas estacionarios como evidencia de navegacion.
