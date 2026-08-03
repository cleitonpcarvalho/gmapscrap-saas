from __future__ import annotations

from io import BytesIO

import requests

from backend.config import get_settings


TRANSCRIPTION_MODEL = "whisper-1"
TRANSCRIPTIONS_URL = "https://api.openai.com/v1/audio/transcriptions"


def transcribe_audio_bytes(audio: bytes, *, filename: str = "audio.ogg", mime_type: str = "audio/ogg") -> str:
    settings = get_settings()
    api_key = settings.openai_api_key.strip()
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY não está configurada no backend.")

    try:
        response = requests.post(
            TRANSCRIPTIONS_URL,
            headers={"Authorization": f"Bearer {api_key}"},
            data={"model": TRANSCRIPTION_MODEL},
            files={"file": (filename, BytesIO(audio), mime_type)},
            timeout=60,
        )
    except requests.RequestException as exc:
        raise RuntimeError(f"OpenAI indisponível para transcrição de áudio: {exc}") from exc

    if response.status_code >= 400:
        raise RuntimeError(f"OpenAI retornou erro {response.status_code}: {response.text[:600]}")

    try:
        data = response.json()
    except ValueError as exc:
        raise RuntimeError("OpenAI retornou uma resposta inválida para transcrição.") from exc

    text = data.get("text") if isinstance(data, dict) else None
    return str(text or "").strip()
