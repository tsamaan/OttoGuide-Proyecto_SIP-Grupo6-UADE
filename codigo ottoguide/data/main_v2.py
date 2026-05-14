"""
OttoGuide IA — Orquestador V2 (Async)
======================================

Versión asíncrona del orquestador de conversación de Otto.
Usa asyncio + aiohttp para mayor eficiencia y preparación
para integración con el SDK nativo de Unitree.

Diferencias con main.py (V1):
  - Todo async/await — no hay llamadas bloqueantes en el event loop
  - aiohttp para llamadas HTTP a Ollama y Whisper
  - subprocess async para arecord y piper
  - Preparado para reemplazar TTS por AudioClient del SDK de Unitree

Servicios requeridos (docker compose up):
  - Ollama  (LLM)  → puerto 11434
  - Whisper (STT)  → puerto 9001 notebook / 9000 robot
  - Piper   (TTS)  → contenedor ottoguide-tts

Autor: Equipo OttoGuide — UADE 2026
"""

from __future__ import annotations

import asyncio
import re
import os
import random
import struct
import wave
from typing import Optional

import aiohttp


# ─── CONFIGURACIÓN ────────────────────────────────────────────────────────────

STT_PORT = 9001   # notebook desarrollo
# STT_PORT = 9000  # robot Jetson

LLM_PORT = 11434
TTS_PORT = 10200

STT_URL = f"http://localhost:{STT_PORT}/asr"
LLM_URL = f"http://localhost:{LLM_PORT}/api/generate"

MIC_DEVICE   = "plughw:1,0"  # notebook Linux Mint
MIC_CHANNELS = "2"
# MIC_DEVICE   = "plughw:0,0"  # robot Jetson — confirmar con arecord -l
# MIC_CHANNELS = "1"           # robot Jetson

# Entorno: "notebook" usa Docker TTS | "robot" usa SDK AudioClient
OTTO_ENV = os.getenv("OTTO_ENV", "notebook")

# ─── WAKE WORD ────────────────────────────────────────────────────────────────

WAKE_WORDS = [
    "hola otto", "hola oto",
    "ola otto",  "ola oto",
    "hola auto", "hola a otto",
    "hola a oto", "oto", "otto"
]

# ─── AUDIO ────────────────────────────────────────────────────────────────────

SILENCIO_THRESHOLD = 1000

# ─── FILTROS STT ──────────────────────────────────────────────────────────────

FALSOS_POSITIVOS = [
    "subtitulos", "amara", "suscribite", "suscribete", "suscríbete",
    "youtube", "comunidad", "gracias por ver", "nos valemos",
    "se prevenden", "la edicion", "edicion", "por favor",
    "musica", "música", "like", "me gusta", "compartir", "comentarios"
]

# ─── DESPEDIDAS ───────────────────────────────────────────────────────────────

DESPEDIDAS = [
    "chau", "adios", "hasta luego",
    "listo", "eso es todo",
    "no tengo mas preguntas",
    "no tengo otra pregunta", "chao"
]

# ─── FRASES DINÁMICAS ─────────────────────────────────────────────────────────

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

import re as _re
EMOJI_PATTERN = _re.compile(
    "["
    u"\U0001F600-\U0001F64F"
    u"\U0001F300-\U0001F5FF"
    u"\U0001F680-\U0001F9FF"
    u"\U00002700-\U000027BF"
    u"\U0001FA00-\U0001FA6F"
    "]+", flags=_re.UNICODE
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
    """Prepara el texto para que Piper lo lea de forma más natural."""
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
    """Detecta variaciones fonéticas de UADE via Levenshtein (tolerancia 2 errores)."""
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
    """Corrige variaciones fonéticas de UADE usando Levenshtein."""
    palabras = texto.split()
    return ' '.join(
        "UADE" if similar_a_uade(re.sub(r'[^\w]', '', w.lower())) else w
        for w in palabras
    )


def calcular_timeout(pregunta: str) -> float:
    """Calcula el timeout según complejidad de la pregunta. Robot: dividir por 3."""
    palabras = len(pregunta.split())
    if palabras <= 10:
        return 150.0   # robot: ~45s
    elif palabras <= 15:
        return 200.0   # robot: ~60s
    return 300.0       # robot: ~90s


# ─── AUDIO — GRABAR ───────────────────────────────────────────────────────────

async def grabar(duracion: int, path: str) -> None:
    """Graba audio del micrófono de forma asíncrona."""
    proc = await asyncio.create_subprocess_exec(
        "arecord", "-d", str(duracion),
        "-D", MIC_DEVICE, "-f", "S16_LE",
        "-c", MIC_CHANNELS, "-r", "16000", path,
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.DEVNULL,
    )
    await proc.wait()


# ─── STT — TRANSCRIBIR ────────────────────────────────────────────────────────

async def transcribir(path: str, session: aiohttp.ClientSession) -> str:
    """
    Verifica amplitud y manda el audio a Whisper via HTTP async.
    Filtra falsos positivos y corrige variaciones de UADE.
    """
    try:
        # Verificar amplitud — descartar silencio
        with wave.open(path, 'rb') as wf:
            frames = wf.readframes(wf.getnframes())
            samples = struct.unpack(f'{len(frames)//2}h', frames)
            if max(abs(s) for s in samples) < SILENCIO_THRESHOLD:
                return ""

        # Transcribir con Whisper forzando español via URL
        with open(path, "rb") as f:
            data = aiohttp.FormData()
            data.add_field("audio_file", f, filename="audio.wav")
            data.add_field("language", "es")
            data.add_field("task", "transcribe")

            async with session.post(
                f"{STT_URL}?language=es&task=transcribe",
                data=data,
                timeout=aiohttp.ClientTimeout(total=30),
            ) as resp:
                texto = (await resp.text()).lower().strip()

        texto = re.sub(r'[^\w\s]', '', texto)

        # Filtrar alucinaciones de Whisper
        if any(fp in texto for fp in FALSOS_POSITIVOS):
            return ""

        return corregir_transcripcion(texto)

    except Exception as e:
        print(f"[STT] Error: {e}")
        return ""


def es_wake_word(texto: str) -> bool:
    """Verifica si el texto contiene alguna variación del wake word."""
    return any(w in texto for w in WAKE_WORDS)


# ─── LLM — CONSULTAR ──────────────────────────────────────────────────────────

async def preguntar_llm(pregunta: str, session: aiohttp.ClientSession) -> str:
    """
    Envía la pregunta al modelo otto en Ollama via HTTP async.
    Retorna la respuesta formateada para TTS.
    """
    try:
        payload = {
            "model": "otto",
            "prompt": pregunta,
            "stream": False,
        }
        async with session.post(
            LLM_URL,
            json=payload,
            timeout=aiohttp.ClientTimeout(total=calcular_timeout(pregunta)),
            headers={"Content-Type": "application/json; charset=utf-8"},
        ) as resp:
            data = await resp.json()
            respuesta = data.get("response", "").strip()

        if not respuesta:
            return "No tengo esa informacion, pero podes consultarlo en el stand de informes al final del recorrido."

        return formatear_para_tts(respuesta)

    except asyncio.TimeoutError:
        print("[LLM] Timeout")
        return "Perdona, no pude procesar eso."
    except Exception as e:
        print(f"[LLM] Error: {e}")
        return "Perdona, no pude procesar eso."


# ─── TTS — HABLAR ─────────────────────────────────────────────────────────────

async def esperar_fin_audio() -> None:
    """Espera hasta que el parlante deje de reproducir audio via PipeWire."""
    while True:
        proc = await asyncio.create_subprocess_exec(
            "pactl", "list", "sink-inputs",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
        stdout, _ = await proc.communicate()
        if not stdout.strip():
            break
        await asyncio.sleep(0.2)


async def hablar_docker(texto: str) -> None:
    """
    TTS via contenedor Docker ottoguide-tts (Piper).
    Activo cuando OTTO_ENV != 'robot'.
    """
    texto = formatear_para_tts(texto)

    # Escribir a archivo — preserva acentos UTF-8
    with open("/tmp/otto_texto.txt", "w", encoding="utf-8") as f:
        f.write(texto)

    # Copiar al contenedor
    proc = await asyncio.create_subprocess_exec(
        "docker", "cp", "/tmp/otto_texto.txt", "ottoguide-tts:/tmp/otto_texto.txt",
        stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL,
    )
    await proc.wait()

    # Generar WAV con Piper
    proc = await asyncio.create_subprocess_exec(
        "docker", "exec", "ottoguide-tts", "sh", "-c",
        "cat /tmp/otto_texto.txt | /usr/src/.venv/bin/piper "
        "--model /data/voices/es_MX-gevy-high.onnx "
        "--output_file /tmp/respuesta.wav",
        stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL,
    )
    await proc.wait()

    # Copiar WAV de vuelta
    proc = await asyncio.create_subprocess_exec(
        "docker", "cp", "ottoguide-tts:/tmp/respuesta.wav", "/tmp/respuesta.wav",
        stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL,
    )
    await proc.wait()

    # Reproducir
    proc = await asyncio.create_subprocess_exec(
        "paplay", "/tmp/respuesta.wav",
        stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL,
    )
    # No esperamos — fire-and-forget, esperar_fin_audio() detecta el fin real

    await asyncio.sleep(0.3)
    await esperar_fin_audio()
    await asyncio.sleep(0.5)


async def hablar_sdk(texto: str) -> None:
    """
    TTS via SDK nativo de Unitree (AudioClient.TtsMaker).
    Activo cuando OTTO_ENV == 'robot'.

    TODO: implementar cuando se valide soporte de español en el robot.
    Validar: idioma español, latencia, volumen y calidad de voz.

    Referencia SDK:
        from unitree_sdk2py.g1.audio.g1_audio_client import AudioClient
        client = AudioClient()
        client.Init()
        client.TtsMaker(texto, speaker_id=0)
    """
    # Por ahora fallback a Docker hasta validar el SDK en el robot
    print(f"[TTS/SDK] TODO — usando Docker como fallback. texto: '{texto[:50]}'")
    await hablar_docker(texto)


async def hablar(texto: str) -> None:
    """
    Selecciona el backend TTS según OTTO_ENV:
      - 'notebook' → Docker (Piper)
      - 'robot'    → SDK Unitree AudioClient (con fallback a Docker)
    """
    if OTTO_ENV == "robot":
        await hablar_sdk(texto)
    else:
        await hablar_docker(texto)


# ─── LOOP PRINCIPAL ───────────────────────────────────────────────────────────

async def main() -> None:
    """Loop principal async de OttoGuide V2."""

    print("OttoGuide V2 iniciado.")
    print(f"STT: {STT_URL} | LLM: {LLM_URL} | ENV: {OTTO_ENV}")
    print()
    print("[HIBERNACION] Esperando 'Hola Otto'...")

    # Sesión HTTP compartida para toda la ejecución
    async with aiohttp.ClientSession() as session:

        while True:
            # ── MODO HIBERNACIÓN ──────────────────────────────────────────────
            await grabar(duracion=3, path="/tmp/wake_check.wav")
            texto_wake = await transcribir("/tmp/wake_check.wav", session)

            if not texto_wake:
                continue

            # Descartar frases largas — el wake word es siempre corto
            if len(texto_wake.split()) > 4:
                continue

            print(f"[WAKE] Escuche: '{texto_wake}'")

            if not es_wake_word(texto_wake):
                continue

            # ── MODO CONVERSACIÓN ─────────────────────────────────────────────
            print("[WAKE] Hola Otto detectado!")
            await hablar(random.choice(FRASES_BIENVENIDA))

            while True:
                print("[MIC] ON  — habla ahora")
                await grabar(duracion=7, path="/tmp/pregunta.wav")
                print("[MIC] OFF — procesando...")
                pregunta = await transcribir("/tmp/pregunta.wav", session)

                if not pregunta:
                    await hablar("No te escuche bien, podes repetir.")
                    continue

                if any(d in pregunta for d in DESPEDIDAS):
                    await hablar(random.choice(FRASES_DESPEDIDA))
                    await asyncio.sleep(3)
                    break

                print(f"[STT] Pregunta: '{pregunta}'")
                print("[LLM] Procesando...")

                respuesta = await preguntar_llm(pregunta, session)
                print(f"[LLM] Respuesta: '{respuesta[:80]}'")

                await hablar(respuesta)
                await hablar(random.choice(FRASES_SEGUIR))

                print("[LOOP] Esperando otra pregunta o despedida...")

            # ── VUELVE A HIBERNACIÓN ──────────────────────────────────────────
            print()
            print("[HIBERNACION] Esperando 'Hola Otto'...")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nOttoGuide V2 detenido.")
