# Replay RViz

Indice de visualizacion offline para evidencia HIL, rosbags y configuraciones RViz.

## Documentos

| Documento | Uso |
|---|---|
| `RVIZ_REPLAY_TROUBLESHOOTING_2026-06-09.md` | Troubleshooting de replay RViz y configuraciones 2D/cloud. |

## Configuraciones

Las configuraciones RViz versionadas viven en:

```text
codigo ottoguide/tools/hil/rviz/
```

## Uso seguro

- Usar RViz solo para inspeccion offline o replay local.
- No conectar RViz a una sesion fisica con Nav2 activo sin autorizacion explicita.
- No tratar TF identidad o mapas estacionarios como evidencia de navegacion.
