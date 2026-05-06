"""
Flujo general:
  1. Modo hibernación: escucha el wake word "Hola Otto" en ciclos de 3 seg
  2. Modo conversación: transcribe preguntas, consulta al LLM y responde con voz
  3. Modo despedida: detecta cuando el visitante se va y vuelve a hibernación

Servicios utilizados (deben estar corriendo via docker compose up):
  - Ollama  (LLM)  → puerto 11434
  - Piper   (TTS)  → puerto 10200, contenedor ottoguide-tts
  - Whisper (STT)  → puerto 9001 en notebook / 9000 en robot

Hardware:
  - Notebook desarrollo: Linux Mint, micrófono interno plughw:1,0
  - Robot Jetson Orin NX: array de 4 micrófonos (configurar en Fase 5)

Autor: Equipo OttoGuide — UADE 2026
"""

import subprocess   # para ejecutar comandos del sistema (arecord, docker, paplay)
import requests     # para llamadas HTTP a Ollama y Whisper
import time         # para sleeps y timeouts
import re           # para expresiones regulares (limpieza de texto)
import os           # para rutas de archivos
import wave         # para leer archivos WAV y medir amplitud
import struct       # para decodificar bytes de audio
import random       # para elegir frases aleatorias
# import json       # descomentar si se usa el fallback manual de UADE


# ─── CONFIGURACIÓN DE PUERTOS ─────────────────────────────────────────────────

STT_PORT = 9001   # notebook: 9001 (Portainer ocupa el 9000) | robot: 9000
# STT_PORT = 9000  # robot Jetson

LLM_PORT = 11434  # Ollama — igual en notebook y robot
TTS_PORT = 10200  # Piper  — igual en notebook y robot

STT_URL = f"http://localhost:{STT_PORT}/asr"
LLM_URL = f"http://localhost:{LLM_PORT}/api/generate"


# ─── CONFIGURACIÓN DE AUDIO ───────────────────────────────────────────────────

MIC_DEVICE   = "plughw:1,0"  # notebook Linux Mint — micrófono interno tarjeta 1
MIC_CHANNELS = "1"           # notebook: mono (1 canal)
# MIC_DEVICE   = "plughw:0,0"  # robot Jetson — confirmar con arecord -l en Fase 5
# MIC_CHANNELS = "1"           # robot Jetson: mono


# ─── WAKE WORD ────────────────────────────────────────────────────────────────
# Variaciones de "Hola Otto" que Whisper puede transcribir incorrectamente.
# Se agregan variaciones fonéticas comunes para mayor tolerancia.

WAKE_WORDS = [
    "hola otto", "hola oto",    
    "ola otto",  "ola oto",     
    "hola auto", "hola a otto", 
    "hola a oto", "oto", "otto" 
]


# ─── THRESHOLD DE SILENCIO ────────────────────────────────────────────────────
# Amplitud mínima para considerar que hay voz real en el audio.
# Evita mandar silencio o ruido de fondo a Whisper.
# Subir si el micrófono capta demasiado ruido ambiente.

SILENCIO_THRESHOLD = 1000


# ─── FILTROS DE FALSOS POSITIVOS ──────────────────────────────────────────────
# Whisper alucina estos textos cuando no hay voz clara en el audio.
# Si alguno de estos aparece en la transcripción, se descarta silenciosamente.

FALSOS_POSITIVOS = [
    "subtitulos", "amara", "suscribite", "suscribete", "suscríbete",
    "youtube", "comunidad", "gracias por ver", "nos valemos",
    "se prevenden", "la edicion", "edicion", "por favor",
    "musica", "música", "like", "me gusta", "compartir", "comentarios"
]


# ─── PALABRAS DE DESPEDIDA ────────────────────────────────────────────────────
# Si el visitante dice alguna de estas palabras, Otto se despide
# y el sistema vuelve al modo hibernación esperando el próximo visitante.

DESPEDIDAS = [
    "chau", "adios", "hasta luego",
    "listo", "eso es todo",
    "no tengo mas preguntas",
    "no tengo otra pregunta", "chao"
]


# ─── FRASES DINÁMICAS ─────────────────────────────────────────────────────────
# Listas de frases aleatorias para que Otto no suene repetitivo.
# random.choice() elige una distinta cada vez.

FRASES_BIENVENIDA = [
    # Se dicen una vez al detectar el wake word
    "Si, decime. cual es tu pregunta.",
    "Claro, te escucho. que queres saber.",
    "Decime, en que te puedo ayudar.",
    "Dale, que pregunta tenes.",
]

FRASES_SEGUIR = [
    # Se dicen después de responder cada pregunta
    "Alguna otra consulta.",
    "Tenes alguna otra pregunta.",
    "Hay algo mas que quieras saber.",
    "En que mas te puedo ayudar.",
    "Seguimos. que otra cosa queres saber.",
]

FRASES_DESPEDIDA = [
    # Se dicen cuando el visitante se despide
    "Fue un placer. Cualquier consulta adicional, en el stand de informes te ayudan. Disfruten el recorrido.",
    "Adios. Si tienen mas preguntas, en el stand de informes los esperan. Que disfruten el campus.",
    "Un placer acompanarlos. Recuerden que en el stand de informes pueden resolver cualquier duda. Hasta luego.",
    "Espero haber sido de ayuda. Para cualquier otra consulta, esta el stand de informacion. Bienvenidos a UADE.",
]


# ─── PATRÓN DE EMOJIS ─────────────────────────────────────────────────────────
# Regex para detectar y eliminar emojis del texto antes de mandarlo a Piper.
# Piper los lee como caracteres extraños o directamente falla.

EMOJI_PATTERN = re.compile(
    "["
    u"\U0001F600-\U0001F64F"  # emoticonos de caras
    u"\U0001F300-\U0001F5FF"  # símbolos y pictogramas
    u"\U0001F680-\U0001F9FF"  # transporte y símbolos adicionales
    u"\U00002700-\U000027BF"  # dingbats
    u"\U0001FA00-\U0001FA6F"  # símbolos extendidos
    "]+", flags=re.UNICODE
)


# ─── UTILIDADES ───────────────────────────────────────────────────────────────

def limpiar(texto: str) -> str:
    """
    Elimina emojis y caracteres problemáticos del texto.
    Se aplica antes de mandar texto a Piper TTS.
    """
    texto = EMOJI_PATTERN.sub('', texto)          # eliminar emojis
    texto = texto.replace('"', "'").replace('`', "'")  # comillas problemáticas en shell
    texto = texto.replace('\n', ' ').replace('\r', '')  # saltos de línea
    texto = re.sub(r'\s+', ' ', texto).strip()    # espacios múltiples
    return texto


def formatear_para_tts(texto: str) -> str:
    """
    Prepara el texto para que Piper lo lea de forma más natural.
    - Agrega una coma (pausa) en oraciones largas de más de 15 palabras
    - Normaliza puntos y puntos suspensivos
    """
    texto = limpiar(texto)
    texto = re.sub(r'\. ([A-Z])', r'. \1', texto)  # espacio tras punto seguido de mayúscula
    texto = texto.replace('...', ',')               # puntos suspensivos → pausa natural
    palabras = texto.split()
    if len(palabras) > 15:
        # insertar coma al medio para generar pausa natural en oraciones largas
        mitad = len(palabras) // 2
        palabras.insert(mitad, ',')
        texto = ' '.join(palabras)
    return texto


def similar_a_uade(palabra: str) -> bool:
    """
    Detecta si una palabra es fonéticamente similar a 'UADE'
    usando distancia de Levenshtein con tolerancia de hasta 2 errores.

    Cubre variaciones como: guadi, huade, wady, uadee, wade, etc.
    El algoritmo calcula cuántas operaciones (inserción, eliminación,
    sustitución) se necesitan para transformar la palabra en 'uade'.
    Si son 2 o menos, se considera una variación válida.
    """
    objetivo = "uade"
    p = palabra.lower()

    if p == objetivo:           # coincidencia exacta — retorno rápido
        return True

    if len(p) < 3 or len(p) > 7:  # descartar palabras muy cortas o largas
        return False

    # Matriz de programación dinámica para distancia de Levenshtein
    m, n = len(objetivo), len(p)
    dp = [[0] * (n + 1) for _ in range(m + 1)]
    for i in range(m + 1): dp[i][0] = i  # costo de eliminar todos los chars del objetivo
    for j in range(n + 1): dp[0][j] = j  # costo de insertar todos los chars de p
    for i in range(1, m + 1):
        for j in range(1, n + 1):
            if objetivo[i - 1] == p[j - 1]:
                dp[i][j] = dp[i - 1][j - 1]  # sin costo si los chars son iguales
            else:
                dp[i][j] = 1 + min(
                    dp[i - 1][j],      # eliminación
                    dp[i][j - 1],      # inserción
                    dp[i - 1][j - 1]   # sustitución
                )

    return dp[m][n] <= 2  # tolerancia de 2 errores fonéticos


def corregir_transcripcion(texto: str) -> str:
    """
    Recorre cada palabra de la transcripción y reemplaza
    cualquier variación fonética de UADE por la sigla correcta.

    MÉTODO ACTIVO: algoritmo de Levenshtein (automático, sin mantenimiento).

    MÉTODO ALTERNATIVO (fallback manual): si el algoritmo falla, comentar
    esta función y descomentar el bloque al final del archivo.
    Requiere services/core/correcciones_uade.json con la lista de variaciones.
    """
    palabras = texto.split()
    palabras_corregidas = []
    for palabra in palabras:
        palabra_limpia = re.sub(r'[^\w]', '', palabra.lower())  # quitar puntuación
        if similar_a_uade(palabra_limpia):
            palabras_corregidas.append("UADE")  # reemplazar variación por sigla correcta
        else:
            palabras_corregidas.append(palabra)
    return ' '.join(palabras_corregidas)


# ─── FUNCIONES PRINCIPALES ────────────────────────────────────────────────────

def grabar(duracion: int, path: str):
    """
    Graba audio del micrófono por N segundos y lo guarda en path.
    Usa arecord con los parámetros configurados arriba.
    """
    subprocess.run([
        "arecord",
        "-d", str(duracion),    # duración en segundos
        "-D", MIC_DEVICE,       # dispositivo de audio
        "-f", "S16_LE",         # formato: 16-bit signed little endian
        "-c", MIC_CHANNELS,     # canales: 1 (mono) o 2 (estéreo)
        "-r", "16000",          # sample rate: 16kHz (requerido por Whisper)
        path                    # archivo de salida
    ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def transcribir(path: str) -> str:
    """
    Verifica que haya voz real en el audio y lo manda a Whisper.
    
    Pasos:
    1. Medir amplitud máxima — descartar si es silencio
    2. Enviar a Whisper forzando español
    3. Filtrar alucinaciones conocidas de Whisper
    4. Corregir variaciones fonéticas de UADE
    """
    try:
        # Paso 1: verificar que hay voz real antes de llamar a Whisper
        with wave.open(path, 'rb') as wf:
            frames = wf.readframes(wf.getnframes())
            samples = struct.unpack(f'{len(frames)//2}h', frames)
            amplitud = max(abs(s) for s in samples)
            print(f"[DEBUG][STT] amplitud del audio: {amplitud}")
            if amplitud < SILENCIO_THRESHOLD:
                print(f"[DEBUG][STT] descartado por silencio (threshold: {SILENCIO_THRESHOLD})")
                return ""  # silencio — no gastar recursos de Whisper

        # Paso 2: transcribir con Whisper forzando español via parámetros en URL
        with open(path, "rb") as f:
            r = requests.post(
                f"{STT_URL}?language=es&task=transcribe",  # idioma en URL, no en body
                files={"audio_file": f},
                timeout=30
            )

        texto = r.text.lower().strip()
        texto = re.sub(r'[^\w\s]', '', texto)  # eliminar puntuación para comparar

        print(f"[DEBUG][STT] transcripcion raw: '{texto}'")

        # Paso 3: filtrar alucinaciones de Whisper (textos de YouTube, etc.)
        if any(fp in texto for fp in FALSOS_POSITIVOS):
            print(f"[DEBUG][STT] descartado por falso positivo")
            return ""

        # Paso 4: corregir variaciones fonéticas de UADE
        texto = corregir_transcripcion(texto)
        print(f"[DEBUG][STT] transcripcion final: '{texto}'")
        return texto

    except Exception as e:
        print(f"[STT] Error: {e}")
        return ""


def es_wake_word(texto: str) -> bool:
    """Verifica si el texto contiene alguna variación del wake word 'Hola Otto'."""
    return any(w in texto for w in WAKE_WORDS)


def calcular_timeout(pregunta: str) -> int:
    """
    Calcula el timeout HTTP según la complejidad de la pregunta.
    Preguntas más largas → respuestas más largas → más tiempo de generación.
    
    Nota: En el robot Jetson con GPU, los valores pueden reducirse 3x.
    """
    palabras = len(pregunta.split())
    if palabras <= 10:
        return 150   # pregunta corta  | robot: ~45s
    elif palabras <= 15:
        return 200   # pregunta media  | robot: ~60s
    else:
        return 300   # pregunta larga  | robot: ~90s


def preguntar_llm(pregunta: str) -> str:
    """
    Envía la pregunta al modelo 'otto' en Ollama y devuelve la respuesta.
    
    El modelo usa el Modelfile de services/llm/Modelfile que define:
    - La personalidad de Otto
    - El conocimiento base de UADE
    - El tono y estilo de respuesta
    """
    try:
        print(f"[DEBUG][LLM] enviando al modelo: '{pregunta}'")
        r = requests.post(
            LLM_URL,
            json={
                "model": "otto",         # modelo personalizado creado con el Modelfile
                "prompt": pregunta,
                "stream": False          # esperar respuesta completa antes de procesar
            },
            timeout=calcular_timeout(pregunta),
            headers={"Content-Type": "application/json; charset=utf-8"}
        )

        data = r.json()  # parsear una sola vez — evita problemas con el stream de requests
        respuesta = data.get("response", "").strip()

        print(f"[DEBUG][LLM] respuesta raw: '{respuesta[:100]}'")

        if not respuesta:
            # El LLM no generó respuesta — puede pasar si la pregunta está fuera del contexto
            print(f"[DEBUG][LLM] respuesta vacia — usando fallback")
            return "No tengo esa informacion, pero podes consultarlo en el stand de informes al final del recorrido."

        return formatear_para_tts(respuesta)  # formatear antes de mandar a Piper

    except Exception as e:
        print(f"[LLM] Error: {e}")
        return "Perdona, no pude procesar eso."


def esperar_fin_audio():
    """
    Espera hasta que el parlante deje de reproducir audio.
    
    Consulta PipeWire/PulseAudio via pactl hasta que no haya
    sink-inputs activos. Esto evita que el micrófono capture
    la voz de Otto mientras habla (feedback loop).
    """
    while True:
        result = subprocess.run(
            ["pactl", "list", "sink-inputs"],  # listar streams de audio activos
            capture_output=True, text=True
        )
        if not result.stdout.strip():  # sin streams activos = parlante libre
            break
        time.sleep(0.2)  # polling cada 200ms para no sobrecargar la CPU


def hablar(texto: str):
    """
    Pipeline completo de síntesis de voz (TTS):
    1. Formatear texto para lectura natural
    2. Escribir a /tmp/otto_texto.txt (UTF-8) — evita corrupción de acentos via echo
    3. Copiar el archivo al contenedor ottoguide-tts
    4. Borrar el WAV anterior — evita reproducir audio cacheado si Piper falla
    5. Generar WAV con Piper usando la voz es_MX-gevy-high
    6. Copiar el WAV de vuelta a la notebook
    7. Reproducir con paplay en background
    8. Esperar que el parlante termine antes de activar el micrófono
    """
    texto = formatear_para_tts(texto)
    print(f"[DEBUG][TTS] hablando: '{texto[:80]}'")
    try:
        # Escribir texto a archivo para preservar acentos (UTF-8)
        # No usar echo "texto" | piper porque bash corrompe caracteres UTF-8
        with open("/tmp/otto_texto.txt", "w", encoding="utf-8") as f:
            f.write(texto)

        # Copiar el texto al contenedor TTS
        subprocess.run([
            "docker", "cp",
            "/tmp/otto_texto.txt",
            "ottoguide-tts:/tmp/otto_texto.txt"
        ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

        # Borrar el WAV anterior del contenedor y generar el nuevo
        # Si Piper falla, el docker cp va a fallar y no se reproduce nada
        subprocess.run([
            "docker", "exec", "ottoguide-tts", "sh", "-c",
            "rm -f /tmp/respuesta.wav && "
            "cat /tmp/otto_texto.txt | /usr/src/.venv/bin/piper "
            "--model /data/voices/es_MX-gevy-high.onnx "
            "--output_file /tmp/respuesta.wav && "
            "echo '[DEBUG] piper OK' || echo '[DEBUG] piper FALLO'"
        ], stdout=None, stderr=None)  # stdout=None para ver el output de Piper en terminal

        # Copiar el audio generado de vuelta a la notebook
        subprocess.run([
            "docker", "cp",
            "ottoguide-tts:/tmp/respuesta.wav",
            "/tmp/respuesta.wav"
        ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

        # Reproducir en background con paplay (PipeWire)
        subprocess.Popen(
            ["paplay", "/tmp/respuesta.wav"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
        )
        time.sleep(0.3)       # margen para que paplay registre el stream en PipeWire
        esperar_fin_audio()   # esperar que el parlante quede completamente libre
        time.sleep(0.5)       # margen final de seguridad antes de activar el micrófono
        print(f"[DEBUG][TTS] audio terminado")

    except Exception as e:
        print(f"[TTS] Error: {e}")


# ─── LOOP PRINCIPAL ───────────────────────────────────────────────────────────

print("OttoGuide iniciado.")
print(f"STT: {STT_URL} | LLM: {LLM_URL}")
print()
print("[HIBERNACION] Esperando 'Hola Otto'...")

while True:
    # ── MODO HIBERNACIÓN ──────────────────────────────────────────────────────
    # Graba ciclos de 3 segundos buscando el wake word.
    # Si detecta "Hola Otto", pasa al modo conversación.

    grabar(duracion=3, path="/tmp/wake_check.wav")
    texto_wake = transcribir("/tmp/wake_check.wav")

    if not texto_wake:
        continue  # silencio o falso positivo — seguir escuchando

    # Descartar frases largas — el wake word es siempre corto (1-3 palabras)
    # Esto evita activar Otto con conversaciones ambientales largas
    if len(texto_wake.split()) > 4:
        print(f"[DEBUG][WAKE] descartado por largo: '{texto_wake}'")
        continue

    print(f"[WAKE] Escuche: '{texto_wake}'")

    if not es_wake_word(texto_wake):
        print(f"[DEBUG][WAKE] no es wake word — ignorando")
        continue  # se escuchó algo pero no es "Hola Otto"

    # ── MODO CONVERSACIÓN ─────────────────────────────────────────────────────
    # Loop activo: responde preguntas hasta que el visitante se despida.

    print("[WAKE] Hola Otto detectado!")

    frase_bienvenida = random.choice(FRASES_BIENVENIDA)
    print(f"[DEBUG][FRASE] bienvenida elegida: '{frase_bienvenida}'")

    hablar(frase_bienvenida)  # saludar al visitante con frase aleatoria

    while True:
        print("[MIC] ON  — habla ahora")
        grabar(duracion=7, path="/tmp/pregunta.wav")   # grabar la pregunta del visitante
        print("[MIC] OFF — procesando...")
        pregunta = transcribir("/tmp/pregunta.wav")
        print(f"[DEBUG][CONV] pregunta recibida: '{pregunta}'")

        if not pregunta:
            # Sin voz válida — puede ser silencio o ruido
            print(f"[DEBUG][CONV] sin audio valido — pidiendo que repita")
            hablar("No te escuche bien, podes repetir.")

        elif any(d in pregunta for d in DESPEDIDAS):
            # El visitante se va — despedirse y volver a hibernación
            palabra_detectada = [d for d in DESPEDIDAS if d in pregunta]
            print(f"[DEBUG][CONV] despedida detectada: {palabra_detectada}")

            frase_despedida = random.choice(FRASES_DESPEDIDA)
            
            print(f"[DEBUG][FRASE] despedida elegida: '{frase_despedida[:60]}'")
            hablar(frase_despedida)
            time.sleep(3)  # pausa para que el audio termine antes de volver a hibernación
            break          # salir del loop de conversación

        else:
            # Pregunta válida — procesar con el LLM y responder
            print(f"[STT] Pregunta: '{pregunta}'")
            print("[LLM] Procesando...")
            respuesta = preguntar_llm(pregunta)

            print(f"[LLM] Respuesta: '{respuesta[:80]}'")
            hablar(respuesta)  # Otto habla la respuesta del LLM

            # Preguntar si hay más consultas con frase aleatoria
            frase_seguir = random.choice(FRASES_SEGUIR)

            print(f"[DEBUG][FRASE] seguir elegida: '{frase_seguir}'")
            hablar(frase_seguir)

        print("[LOOP] Esperando otra pregunta o despedida...")

    # ── VUELVE A HIBERNACIÓN ──────────────────────────────────────────────────
    print()
    print("[HIBERNACION] Esperando 'Hola Otto'...")


# ─── FALLBACK MANUAL DE UADE — descomentar si Levenshtein falla ───────────────
#
# Para activar:
#   1. Descomentar "import json" arriba
#   2. Comentar la función corregir_transcripcion() de arriba
#   3. Descomentar todo este bloque
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
#     Versión manual — usa correcciones_uade.json en lugar de Levenshtein.
#     Más predecible pero requiere mantenimiento manual de la lista.
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