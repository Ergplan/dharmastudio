"""Narration: ElevenLabs text-to-speech with character timestamps (eleven_multilingual_v2 for Hindi and English).

POST https://api.elevenlabs.io/v1/text-to-speech/{voice_id}/with-timestamps   (xi-api-key)
     {text, model_id} -> {audio_base64, alignment: {characters, character_start_times_seconds, character_end_times_seconds}}
Without ELEVENLABS_API_KEY there is no narration (captions are timed by length instead).
"""

from __future__ import annotations

import base64
import os
from pathlib import Path
from typing import Any

import httpx

DEFAULT_VOICE = "JBFqnCBsd6RMkjVDRZzb"  # a stock ElevenLabs narrator; set your own voice id in Settings
MODEL = "eleven_multilingual_v2"
USD_PER_1K_CHARS = 0.30  # estimate for the ledger


def key() -> str | None:
    from engine.settings import settings

    return getattr(settings, "elevenlabs_api_key", None) or os.environ.get("ELEVENLABS_API_KEY")


def available() -> bool:
    return bool(key())


def words_from_alignment(al: dict[str, Any]) -> list[tuple[str, float, float]]:
    chars = al.get("characters") or []
    st = al.get("character_start_times_seconds") or []
    en = al.get("character_end_times_seconds") or []
    out: list[tuple[str, float, float]] = []
    cur, s0, e0 = "", None, 0.0
    for ch, s, e in zip(chars, st, en):
        if ch.isspace():
            if cur:
                out.append((cur, s0 or 0.0, e0))
            cur, s0 = "", None
            continue
        if s0 is None:
            s0 = s
        cur += ch
        e0 = e
    if cur:
        out.append((cur, s0 or 0.0, e0))
    return out


def synthesize(text: str, out: Path, voice_id: str | None = None, lang: str = "en") -> dict[str, Any]:
    k = key()
    if not k:
        raise RuntimeError("no ELEVENLABS_API_KEY")
    vid = voice_id or DEFAULT_VOICE
    body = {"text": text, "model_id": MODEL}
    if lang == "hi":
        body["language_code"] = "hi"
    r = httpx.post(f"https://api.elevenlabs.io/v1/text-to-speech/{vid}/with-timestamps?output_format=mp3_44100_128", json=body,
                   headers={"xi-api-key": k, "Content-Type": "application/json"}, timeout=180)
    r.raise_for_status()
    js = r.json()
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(base64.b64decode(js["audio_base64"]))
    words = words_from_alignment(js.get("alignment") or js.get("normalized_alignment") or {})
    dur = words[-1][2] if words else 0.0
    return {"path": out, "words": words, "duration": dur, "cost_usd": round(len(text) / 1000 * USD_PER_1K_CHARS, 4), "voice_id": vid, "model": MODEL}
