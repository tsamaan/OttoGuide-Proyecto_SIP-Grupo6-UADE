import subprocess
import requests
import time
import re
import os
import wave
import struct
import random
# import json  # descomentar si se usa el fallback manual de UADE

# ─── CONFIGURACIÓN ────────────────────────────────────────────────────────────
STT_PORT = 9001   # notebook desarrollo
# STT_PORT = 9000  # robot Jetson

LLM_PORT = 11434
TTS_PORT = 10200

STT_URL = f"http://localhost:{STT_PORT}/asr"
LLM_URL = f"http://localhost:{LLM_PORT}/api/generate"

MIC_DEVICE   = "plughw:1,0"  # notebook Linux Mint — micrófono interno
MIC_CHANNELS = "2"
# MIC_DEVICE   = "plughw:0,0"  # robot Jetson — array de micrófonos
# MIC_CHANNELS = "1"           # robot Jetson

# ─── WAKE WORD ────────────────────────────────────────────────────────────────
# Variaciones de "Hola Otto" que Whisper puede transcribir
WAKE_WORDS = [
    "hola otto", "hola oto",
    "ola otto",  "ola oto",
    "hola auto", "hola a otto",
    "hola a oto", "oto", "otto"
]

# ─── AUDIO ────────────────────────────────────────────────────────────────────
# Amplitud mínima para considerar que hay voz real (evita procesar silencio)
SILENCIO_THRESHOLD = 1000

# ─── FILTROS STT ──────────────────────────────────────────────────────────────
# Textos que Whisper genera por error cuando no hay voz clara
FALSOS_POSITIVOS = [
    "subtitulos", "amara", "suscribite", "suscribete", "suscríbete",
    "youtube", "comunidad", "gracias por ver", "nos valemos",
    "se prevenden", "la edicion", "edicion", "por favor",
    "musica", "música", "like", "me gusta", "compartir", "comentarios"
]

# ─── DESPEDIDAS DEL VISITANTE ─────────────────────────────────────────────────
# Si el visitante dice alguna de estas palabras, Otto se despide y vuelve a hibernación
DESPEDIDAS = [
    "chau", "adios", "hasta luego",
    "listo", "eso es todo",
    "no tengo mas preguntas",
    "no tengo otra pregunta", "chao"
]

# ─── FRASES DINÁMICAS ─────────────────────────────────────────────────────────
# Se eligen al azar para que Otto no suene repetitivo

FRASES_BIENVENIDA = [
    "Si, decime. cual es tu pregunta.",
    "Claro, te escucho. que queres saber.",
    "Decime, en que te puedo ayudar.",
    "Dale, que pregunta tenes.",
]

FRASES_SEGUIR = [
    "Alguna otra consulta.",
    "Tenes alguna otra pregunta.",
    "Hay algo mas que quieras saber.",
    "En que mas te puedo ayudar.",
    "Seguimos. que otra cosa queres saber.",
]

FRASES_DESPEDIDA = [
    "Fue un placer. Cualquier consulta adicional, en el stand de informes te ayudan. Disfruten el recorrido.",
    "Adios. Si tienen mas preguntas, en el stand de informes los esperan. Que disfruten el campus.",
    "Un placer acompanarlos. Recuerden que en el stand de informes pueden resolver cualquier duda. Hasta luego.",
    "Espero haber sido de ayuda. Para cualquier otra consulta, esta el stand de informacion. Bienvenidos a UADE.",
]

# ─── EMOJIS ───────────────────────────────────────────────────────────────────
EMOJI_PATTERN = re.compile(
    "["
    u"\U0001F600-\U0001F64F"
    u"\U0001F300-\U0001F5FF"
    u"\U0001F680-\U0001F9FF"
    u"\U00002700-\U000027BF"
    u"\U0001FA00-\U0001FA6F"
    "]+", flags=re.UNICODE
)


# ─── UTILIDADES ───────────────────────────────────────────────────────────────

def limpiar(texto: str) -> str:
    """Elimina emojis y caracteres problemáticos para el TTS."""
    texto = EMOJI_PATTERN.sub('', texto)
    texto = texto.replace('"', "'").replace('`', "'")
    texto = texto.replace('\n', ' ').replace('\r', '')
    texto = re.sub(r'\s+', ' ', texto).strip()
    return texto


def formatear_para_tts(texto: str) -> str:
    """
    Prepara el texto para que Piper lo lea de forma natural.
    Agrega pausas en oraciones largas y normaliza puntuación.
    """
    texto = limpiar(texto)
    texto = re.sub(r'\. ([A-Z])', r'. \1', texto)
    texto = texto.replace('...', ',')
    palabras = texto.split()
    if len(palabras) > 15:
        mitad = len(palabras) // 2
        palabras.insert(mitad, ',')
        texto = ' '.join(palabras)
    return texto


def similar_a_uade(palabra: str) -> bool:
    """
    Detecta si una palabra es fonéticamente similar a 'UADE'
    usando distancia de Levenshtein con tolerancia de hasta 2 errores.
    Cubre variaciones como: guadi, huade, wady, uadee, etc.
    """
    objetivo = "uade"
    p = palabra.lower()

    if p == objetivo:
        return True

    if len(p) < 3 or len(p) > 7:
        return False

    m, n = len(objetivo), len(p)
    dp = [[0] * (n + 1) for _ in range(m + 1)]
    for i in range(m + 1): dp[i][0] = i
    for j in range(n + 1): dp[0][j] = j
    for i in range(1, m + 1):
        for j in range(1, n + 1):
            if objetivo[i - 1] == p[j - 1]:
                dp[i][j] = dp[i - 1][j - 1]
            else:
                dp[i][j] = 1 + min(dp[i - 1][j], dp[i][j - 1], dp[i - 1][j - 1])

    return dp[m][n] <= 2


def corregir_transcripcion(texto: str) -> str:
    """
    Recorre cada palabra de la transcripción y reemplaza
    cualquier variación fonética de UADE por la sigla correcta.

    MÉTODO ACTIVO: algoritmo de Levenshtein (automático, sin mantenimiento).

    MÉTODO ALTERNATIVO (fallback manual): si el algoritmo falla, comentar
    el bloque activo y descomentar el bloque al final del archivo.
    Requiere services/core/correcciones_uade.json con la lista de variaciones.
    """
    palabras = texto.split()
    palabras_corregidas = []
    for palabra in palabras:
        palabra_limpia = re.sub(r'[^\w]', '', palabra.lower())
        if similar_a_uade(palabra_limpia):
            palabras_corregidas.append("UADE")
        else:
            palabras_corregidas.append(palabra)
    return ' '.join(palabras_corregidas)


# ─── FUNCIONES PRINCIPALES ────────────────────────────────────────────────────

def grabar(duracion: int, path: str):
    """Graba audio del micrófono por N segundos y lo guarda en path."""
    subprocess.run([
        "arecord", "-d", str(duracion),
        "-D", MIC_DEVICE, "-f", "S16_LE",
        "-c", MIC_CHANNELS, "-r", "16000", path
    ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def transcribir(path: str) -> str:
    """
    Verifica que haya voz real en el audio y lo manda a Whisper.
    Filtra falsos positivos y corrige variaciones de UADE.
    """
    try:
        # Verificar amplitud — descartar silencio antes de llamar a Whisper
        with wave.open(path, 'rb') as wf:
            frames = wf.readframes(wf.getnframes())
            samples = struct.unpack(f'{len(frames)//2}h', frames)
            amplitud = max(abs(s) for s in samples)
            if amplitud < SILENCIO_THRESHOLD:
                return ""

        # Transcribir con Whisper forzando español
        with open(path, "rb") as f:
            r = requests.post(
                f"{STT_URL}?language=es&task=transcribe",
                files={"audio_file": f},
                timeout=30
            )
        texto = r.text.lower().strip()
        texto = re.sub(r'[^\w\s]', '', texto)

        # Filtrar alucinaciones de Whisper
        if any(fp in texto for fp in FALSOS_POSITIVOS):
            return ""

        # Corregir variaciones fonéticas de UADE
        texto = corregir_transcripcion(texto)
        return texto

    except Exception as e:
        print(f"[STT] Error: {e}")
        return ""


def es_wake_word(texto: str) -> bool:
    """Verifica si el texto contiene alguna variación del wake word."""
    return any(w in texto for w in WAKE_WORDS)


def calcular_timeout(pregunta: str) -> int:
    """
    Calcula el timeout HTTP según la complejidad de la pregunta.
    En el robot Jetson (GPU) usar valores 3x menores.
    """
    palabras = len(pregunta.split())
    if palabras <= 10:
        return 150   # robot: ~45s
    elif palabras <= 15:
        return 200   # robot: ~60s
    else:
        return 300   # robot: ~90s


def preguntar_llm(pregunta: str) -> str:
    """
    Envía la pregunta al modelo otto en Ollama.
    Devuelve la respuesta formateada para TTS.
    """
    try:
        r = requests.post(
            LLM_URL,
            json={
                "model": "otto",
                "prompt": pregunta,
                "stream": False
            },
            timeout=calcular_timeout(pregunta),
            headers={"Content-Type": "application/json; charset=utf-8"}
        )
        data = r.json()  # parsear una sola vez para evitar problemas de stream
        respuesta = data.get("response", "").strip()

        if not respuesta:
            return "No tengo esa informacion, pero podes consultarlo en el stand de informes al final del recorrido."

        return formatear_para_tts(respuesta)

    except Exception as e:
        print(f"[LLM] Error: {e}")
        return "Perdona, no pude procesar eso."


def esperar_fin_audio():
    """
    Espera hasta que el parlante deje de reproducir audio.
    Consulta PipeWire/PulseAudio hasta que no haya streams activos.
    """
    while True:
        result = subprocess.run(
            ["pactl", "list", "sink-inputs"],
            capture_output=True, text=True
        )
        if not result.stdout.strip():
            break
        time.sleep(0.2)


def hablar(texto: str):
    """
    Pipeline completo de TTS:
    1. Escribe el texto a /tmp para preservar acentos
    2. Copia el archivo al contenedor Piper
    3. Genera el WAV con el modelo gevy
    4. Copia el WAV de vuelta y lo reproduce
    5. Espera que el parlante termine antes de continuar
    """
    texto = formatear_para_tts(texto)
    try:
        # Escribir a archivo temporal — evita corrupción de acentos via echo
        with open("/tmp/otto_texto.txt", "w", encoding="utf-8") as f:
            f.write(texto)

        subprocess.run([
            "docker", "cp",
            "/tmp/otto_texto.txt",
            "ottoguide-tts:/tmp/otto_texto.txt"
        ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

        subprocess.run([
            "docker", "exec", "ottoguide-tts", "sh", "-c",
            "cat /tmp/otto_texto.txt | /usr/src/.venv/bin/piper "
            "--model /data/voices/es_MX-gevy-high.onnx "
            "--output_file /tmp/respuesta.wav"
        ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

        subprocess.run([
            "docker", "cp",
            "ottoguide-tts:/tmp/respuesta.wav",
            "/tmp/respuesta.wav"
        ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

        # Reproducir en background y esperar fin real del audio
        subprocess.Popen(
            ["paplay", "/tmp/respuesta.wav"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
        )
        time.sleep(0.3)       # margen para que paplay registre el stream
        esperar_fin_audio()   # esperar que el parlante quede libre
        time.sleep(0.5)       # margen final antes de activar el micrófono

    except Exception as e:
        print(f"[TTS] Error: {e}")


# ─── LOOP PRINCIPAL ───────────────────────────────────────────────────────────

print("OttoGuide iniciado.")
print(f"STT: {STT_URL} | LLM: {LLM_URL}")
print()
print("[HIBERNACION] Esperando 'Hola Otto'...")

while True:
    # ── MODO HIBERNACIÓN — escucha wake word en ciclos de 3 segundos ──────────
    grabar(duracion=3, path="/tmp/wake_check.wav")
    texto_wake = transcribir("/tmp/wake_check.wav")

    if not texto_wake:
        continue

    # Descartar frases largas — en hibernación solo interesa el wake word corto
    if len(texto_wake.split()) > 4:
        continue

    print(f"[WAKE] Escuche: '{texto_wake}'")

    if not es_wake_word(texto_wake):
        continue

    # ── MODO CONVERSACIÓN — loop activo hasta que el visitante se despida ─────
    print("[WAKE] Hola Otto detectado!")
    hablar(random.choice(FRASES_BIENVENIDA))

    while True:
        print("[MIC] ON  — habla ahora")
        grabar(duracion=7, path="/tmp/pregunta.wav")
        print("[MIC] OFF — procesando...")
        pregunta = transcribir("/tmp/pregunta.wav")

        # Sin audio válido — pedir que repita
        if not pregunta:
            hablar("No te escuche bien, podes repetir.")
            continue

        # Despedida detectada — cerrar conversación y volver a hibernación
        if any(d in pregunta for d in DESPEDIDAS):
            hablar(random.choice(FRASES_DESPEDIDA))
            time.sleep(3)
            break

        print(f"[STT] Pregunta: '{pregunta}'")
        print("[LLM] Procesando...")

        respuesta = preguntar_llm(pregunta)
        print(f"[LLM] Respuesta: '{respuesta}'")

        hablar(respuesta)
        hablar(random.choice(FRASES_SEGUIR))

        print("[LOOP] Esperando otra pregunta o despedida...")

    # ── VUELVE A HIBERNACIÓN ──────────────────────────────────────────────────
    print()
    print("[HIBERNACION] Esperando 'Hola Otto'...")


# ─── FALLBACK MANUAL DE UADE — descomentar si Levenshtein falla ───────────────
#
# def cargar_correcciones() -> dict:
#     """Carga el diccionario de correcciones desde el archivo JSON."""
#     ruta = os.path.join(os.path.dirname(__file__), "correcciones_uade.json")
#     with open(ruta, "r", encoding="utf-8") as f:
#         return json.load(f)["correcciones"]
#
# CORRECCIONES = cargar_correcciones()
#
# def corregir_transcripcion(texto: str) -> str:
#     """
#     Versión manual — usa el archivo correcciones_uade.json.
#     Para activar: comentar la función corregir_transcripcion de arriba
#     y descomentar este bloque completo.
#     """
#     palabras = texto.split()
#     palabras_corregidas = []
#     for palabra in palabras:
#         palabra_limpia = re.sub(r'[^\w]', '', palabra.lower())
#         if palabra_limpia in CORRECCIONES:
#             palabras_corregidas.append(CORRECCIONES[palabra_limpia])
#         else:
#             palabras_corregidas.append(palabra)
#     return ' '.join(palabras_corregidas)
#
# ──────────────────────────────────────────────────────────────────────────────