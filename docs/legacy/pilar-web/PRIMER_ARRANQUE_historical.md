> Historical document imported from branch `pilar-web`. Some runtime assumptions are obsolete. Do not use this as the canonical launch guide.

# Primer arranque en el robot — OttoGuide Panel

Checklist para buildear y probar el backend **directo en el Unitree G1** por primera vez.
Seguí los pasos en orden: cada uno valida algo antes de pasar al siguiente, así si algo
falla sabés exactamente dónde.

> **Regla de oro:** la imagen se buildea **en el robot (companion PC, ARM64/aarch64)**,
> NO en tu notebook (x86). El `Dockerfile` compila CycloneDDS de forma nativa, así que una
> imagen buildeada en la notebook **no corre** en el robot.

---

## Topología (recordatorio)

| Equipo | IP | Rol |
|---|---|---|
| Notebook (front) | `192.168.123.101` | Corre el frontend con `npm run dev` (puerto 3001) |
| Companion PC (robot) | `192.168.123.164` | Corre el backend con Docker (puerto 8000) |
| Locomotion | `192.168.123.161` | — |

Conexión notebook ↔ robot por **cable RJ45**. El front le pega al backend en
`http://192.168.123.164:8000` (configurable en `frontend/.env` → `VITE_ROBOT_BASE_URL`).

---

## Paso 1 — Build en el robot

En la companion PC, dentro de la carpeta `backend/`:

```bash
docker compose up -d --build
```

- ⏳ Compilar CycloneDDS puede tardar varios minutos. Es normal.
- ✅ El `restart: always` hace que, a partir de acá, el backend arranque solo cada vez
  que se prende el robot.

**Si falla acá** → casi siempre es la compilación de CycloneDDS o `unitree_sdk2py`
(dependencia de sistema faltante o poca memoria durante el build). Es el paso con más
fricción. Guardá el log del error.

---

## Paso 2 — Verificar que el contenedor levanta y el SDK importa

```bash
docker compose logs -f
```

- ✅ Tenés que ver el backend arrancando con uvicorn en el puerto 8000.
- ❌ Si ves un error de `.so` no encontrado al arrancar → es el `LD_LIBRARY_PATH` /
  `CYCLONEDDS_HOME` del stage final del Dockerfile.

Chequeo rápido de que responde:

```bash
curl http://localhost:8000/health
```

---

## Paso 3 — Probar TODO el flujo todavía en MOCK (¡importante!)

Antes de meter datos reales, validá la plomería (red, puertos, CORS) con el mock prendido.

1. Confirmá que en el robot está `MOCK_MODE=true` (es el default del `docker-compose.yaml`).
2. En la **notebook**, levantá el front:
   ```bash
   cd frontend
   npm install      # solo la primera vez
   npm run dev
   ```
3. Abrí el panel (puerto 3001) y confirmá que:
   - ✅ se conecta al backend del robot por el cable,
   - ✅ se ve la **telemetría simulada** moviéndose (motores, gráficos, cards),
   - ✅ salta la alerta de temperatura del motor que el mock calienta a propósito.

Si esto anda, toda la conexión back↔front está OK. Recién ahora vamos a datos reales.

---

## Paso 4 — Pasar a datos reales (MOCK_MODE=false + interfaz DDS)

Este es el paso de los TODO que dependían del robot.

1. **Averiguá el nombre real de la interfaz de red** en la companion PC:
   ```bash
   ip addr
   ```
   Buscá la interfaz que está en la subred `192.168.123.x`. Puede ser `eth0` o tener otro
   nombre (ej. `enpXsY`).
2. Editá `backend/.env`:
   ```
   MOCK_MODE=false
   DDS_INTERFACE=<el nombre que viste en ip addr>
   ```
3. Recreá el contenedor:
   ```bash
   docker compose up -d
   ```
4. Mirá los logs y el panel:
   - ✅ Si entra **telemetría real**, los valores ya no son los del mock.
   - ⚠️ Si la interfaz está mal o no llega data, el lector **cae al mock por timeout** (no
     se rompe el arranque, pero verás un warning en el log). Si pasa esto, revisá el nombre
     de la interfaz.

> **Ruta de `otto_pipeline`:** si el binario no está en `$PATH`, seteá también
> `OTTO_PIPELINE_BIN` en `.env` con la ruta exacta.

---

## Paso 5 — Probar los botones

Con datos reales, probá uno por uno desde el panel:

- ✅ **Iniciar recorrido** → ¿lanza `ottoguide-map start`? ¿el robot arranca el recorrido?
- ✅ **Iniciar charla** → ¿lanza `otto_pipeline`? ¿responde por voz?
- ✅ **Terminar ejecución** → ¿frena lo que esté corriendo (SIGINT / `ottoguide-map stop`)?

> Recordá: por ahora el LLM **se habilita manualmente** con "Iniciar charla". El
> auto-habilitarse al terminar el recorrido quedó como TODO (depende de confirmar el
> subcomando `ottoguide-map status`).

---

## Comandos útiles

```bash
docker compose up -d --build     # buildear y levantar
docker compose logs -f           # ver logs en vivo
docker compose restart           # reiniciar el contenedor
docker compose down              # frenar
docker compose up -d             # levantar (sin rebuild) tras cambiar el .env
```

---

## Resumen de puntos delicados

1. **Build solo en el robot (ARM64)**, nunca en la notebook.
2. Si el contenedor no arranca por un `.so` → `LD_LIBRARY_PATH` / `CYCLONEDDS_HOME`.
3. Probá primero todo en **MOCK** antes de tocar datos reales.
4. El valor de **`DDS_INTERFACE`** se confirma con `ip addr` en la companion PC.
5. Si la interfaz está mal → **cae al mock por timeout**, no se cuelga.

---

## TODOs pendientes (para el operador del robot)

- [ ] Confirmar el nombre real de la interfaz DDS (`ip addr`) y ajustar `DDS_INTERFACE`.
- [ ] Confirmar la ruta de `otto_pipeline` y ajustar `OTTO_PIPELINE_BIN` si hace falta.
- [ ] Si `ottoguide-map` soporta `status`, implementar el polling para habilitar el LLM
      automáticamente al final del recorrido.
