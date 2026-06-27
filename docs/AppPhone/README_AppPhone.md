# AppPhone - Unitree Go Control Application Analysis

## Contenido de esta carpeta

Esta carpeta contiene el analisis y decompilacion de la aplicacion Unitree Go (v1.12.7) como referencia secundaria y pasiva del plano factory `192.168.12.x`. Unitree Go no es la ruta primaria de control del G1 EDU dentro de OttoGuide RC1.

Nota SRE RC1: la app oficial para G1/G1_D es Unitree Explore, pero queda fuera de la ruta MVP operativa por AR8030, autenticacion enterprise, dependencia cloud y protocolo binario. La ruta primaria de control operativo de OttoGuide es `SDK2/DDS Unicast` hacia `192.168.123.161`.

### Archivos y carpetas

| Elemento | Descripción |
|----------|-------------|
| `APK_CONNECTIVITY_ANALYSIS.codigo_ottoguide.md` | **Documento principal reubicado** - Hallazgos de ingeniería inversa sobre conectividad, endpoints REST, stack HTTP y arquitectura de la aplicación |
| `Unitree Go_1.12.7_APKPure.xapk` | Archivo XAPK original descargado (base.apk + splits de idioma/arquitectura) |
| `unitree_go_apk/` | Base APK decompilado a código legible (bytecode DEX → Java/Kotlin) |
| `unitree_go_xapk/` | Estructura XAPK completa con splits de configuración |

---

## Propósito del Análisis

Comprender como se comunica la aplicacion Unitree Go con el plano factory para:
1. **Contexto arquitectónico**: Distinguir entre red de control remoto (192.168.12.1) y red de navegación autónoma (192.168.123.x)
2. **Stack tecnológico**: Identificar HTTP client (OkHttp 4.9.0), REST endpoints, protocolo UDP
3. **Seguridad**: Validar que OttoGuide mantiene aislamiento adecuado de capas de control
4. **Integración futura**: Entender protocolos para posibles mejoras de diagnostico pasivo, sin usar Unitree Go como control primario del G1 EDU

---

## Hallazgos Principales

### Red de Control Remoto
- **IP del robot**: 192.168.12.1:9991
- **Endpoint de validación**: GET http://192.168.12.1:9991/con_check
- **Endpoints REST**: `/rest/remote/packet/{post/startup, post, pull, updateNick}`

### Stack Técnico
- **HTTP**: OkHttp 4.9.0 + Retrofit 2.x + HTTP/2
- **Transporte**: UDP (vía BaseConstant.UDP_IP) + WebRTC (video)
- **UI**: AgentWeb + WebView (dashboard Vue.js)
- **Async**: Kotlin Coroutines + RxJava 3

---

## Documentación

**Análisis detallado completo**: Ver [`APK_CONNECTIVITY_ANALYSIS.codigo_ottoguide.md`](./APK_CONNECTIVITY_ANALYSIS.codigo_ottoguide.md)

**Copia duplicada archivada**: `documentacion general del proyecto/Historico/Duplicados/APK_CONNECTIVITY_ANALYSIS.arquitectura_duplicado.md`

---

## Uso de esta Carpeta

### Para Referencia Rápida
```bash
# Ver análisis de conectividad
cat APK_CONNECTIVITY_ANALYSIS.codigo_ottoguide.md
```

### Para Ingeniería Inversa Adicional
```bash
# Acceder a bytecode decompilado
open unitree_go_apk/
# Buscar clases específicas en com/unitree/...
```

### Para Distribución
```bash
# El XAPK original puede re-instalarse en dispositivo de prueba
Unitree Go_1.12.7_APKPure.xapk  # → Via Google Play o APK installer
```

---

## Próximos Pasos

Para análisis más profundo:
1. [x] Integrar handshake read-only `GET /con_check` en Capa 4 mediante `UnitreeFactoryRestClient`
2. [ ] Extraer valor exacto de `BaseConstant.UDP_IP`
3. [ ] Capturar tráfico con `tcpdump`/Wireshark durante operación HIL
4. [ ] Reverse engineer formatos de payload REST/UDP
5. [ ] Documentar máquina de estados de sesión
6. [ ] Mapear mecanismos de autenticación
7. [ ] Correlacionar audio de app oficial con `AudioClient.TtsMaker` / `PlayStream` del SDK2

---

## Referencia Cruzada

- **Scripts de mapeo**: `codigo ottoguide/scripts/hil_capture_mapping_bundle.sh`
- **Protocolo HIL**: `documentacion general del proyecto/RC1_Vigente/HIL_TESTING_PROTOCOL.md`
- **Memoria técnica**: `memoria/repo/robot_humanoide.md`

---

**Creado**: 5 de mayo de 2026  
**Responsable**: GitHub Copilot  
**Estado**: Análisis estático integrado en Capa 4; pendiente análisis dinámico de red
