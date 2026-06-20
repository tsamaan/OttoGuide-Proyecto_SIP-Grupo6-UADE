from __future__ import annotations

import asyncio
import shutil
from pathlib import Path


class LocalAudioPlayer:
    """
    @TASK: Reproducir audios locales del recorrido QR.
    @SECURITY: Ejecuta comandos sin shell y valida rutas dentro del proyecto.
    """

    def __init__(
        self,
        *,
        project_root: Path,
        wav_player_cmd: str = "aplay",
        mp3_player_cmd: str = "mpg123",
    ) -> None:
        self._project_root = project_root.resolve()
        self._wav_player_cmd = wav_player_cmd
        self._mp3_player_cmd = mp3_player_cmd

    async def play(self, audio_path: str) -> Path:
        """
        @TASK: Reproducir un archivo de audio local.
        @OUTPUT: Path absoluto reproducido o excepción controlada.
        """
        full_path = self._resolve_safe_path(audio_path)
        player = self._resolve_player(full_path)

        process = await asyncio.create_subprocess_exec(
            player,
            str(full_path),
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.PIPE,
        )
        _stdout, stderr = await process.communicate()

        if process.returncode != 0:
            error = stderr.decode("utf-8", errors="replace")[:300]
            raise RuntimeError(f"No se pudo reproducir audio {full_path}: {error}")

        return full_path

    def _resolve_safe_path(self, audio_path: str) -> Path:
        candidate = (self._project_root / audio_path).resolve()

        if not str(candidate).startswith(str(self._project_root)):
            raise ValueError(f"Ruta de audio fuera del proyecto: {audio_path}")

        if not candidate.is_file():
            raise FileNotFoundError(f"Audio local no encontrado: {candidate}")

        return candidate

    def _resolve_player(self, full_path: Path) -> str:
        suffix = full_path.suffix.lower()

        if suffix == ".wav":
            command = self._wav_player_cmd
        elif suffix == ".mp3":
            command = self._mp3_player_cmd
        else:
            raise ValueError(f"Formato de audio no soportado: {suffix}. Usar .wav o .mp3.")

        if shutil.which(command) is None:
            raise RuntimeError(f"Comando de audio no disponible: {command}")

        return command