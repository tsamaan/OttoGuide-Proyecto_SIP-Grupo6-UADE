# Dato crudo remoto — pendiente de descarga

```text
REMOTE_RUN_ROOT =
/home/unitree/OttoGuide-Agent-Runs/LIVE_OBSERVABILITY_R0B1/run_r0b1-20260717T215047Z

STATUS =
preservado en el Companion durante la última sesión física
(2026-07-17, checkpoint NB-HIL-CONN-R1-DURABLE-SSH-AND-R0B1-LIVE-RESUME),
pero NO descargado ni verificado localmente en este checkpoint
(WEB-HIL-R1-PORTABLE-CONSOLIDATION-AND-MIRROR-BRANCH).
```

Solo se preservaron localmente 10 frames de muestra
(`REMOTE_LIVE_FRAMES_10.jsonl`, también usados como fixture de replay en
`replay/fixtures/r0b1_real_frames.jsonl`) y el estado compacto (health,
status, manifiestos de hash, gate estático). El raw completo —chunks JSONL de
LowState/odom/LiDAR a resolución completa y nubes LiDAR comprimidas— **no**
tiene copia local verificada.

## Acción requerida en la próxima sesión física

Antes de limpiar o rotar cualquier run en el Companion:

1. Conectar con `notebook/Test-OttoGuideConnection.ps1`.
2. Ejecutar `notebook/Download-OttoGuideEvidence.ps1 -RemoteRunRoot
   /home/unitree/OttoGuide-Agent-Runs/LIVE_OBSERVABILITY_R0B1/run_r0b1-20260717T215047Z
   -IncludeRaw` para traer el raw completo.
3. Verificar los hashes descargados contra `SHA256SUMS.txt` del propio
   `REMOTE_RUN_ROOT` (generado por `finalize_remote_session.sh`).
4. Solo después de una descarga y verificación exitosas, considerar limpiar
   el run remoto — y únicamente con autorización explícita separada (este
   checkpoint no autoriza borrar nada en el Companion).

No afirmar en ningún documento derivado que "el raw completo está preservado
localmente" hasta que este procedimiento se complete y se registre aquí.
