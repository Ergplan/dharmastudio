"""Claude Messages API call used by engine.llm. Prompts live in engine/*.md; JSON only comes back."""

from __future__ import annotations

import base64
import json
import re
from pathlib import Path
from typing import Any

from .settings import settings

PROMPT_DIR = Path(__file__).resolve().parent

CONTRACT = (
    "\n\nContract: read the input, do the work, write results by id, never invent a fact that is not in the input "
    "or the book. Answer with JSON only, no prose around it."
)


def load_prompt(name: str) -> str:
    p = PROMPT_DIR / f"{name}.md"
    return (p.read_text(encoding="utf-8") if p.exists() else "") + CONTRACT


def extract_json(text: str) -> Any:
    text = text.strip()
    m = re.search(r"```(?:json)?\s*(.*?)```", text, re.S)
    if m:
        text = m.group(1)
    starts = [i for i in (text.find("{"), text.find("[")) if i >= 0]
    start = min(starts) if starts else 0
    return json.loads(text[start:])


def _image_block(p: Path) -> dict[str, Any]:
    data = base64.b64encode(p.read_bytes()).decode()
    media = "image/png" if p.suffix.lower() == ".png" else "image/jpeg"
    return {"type": "image", "source": {"type": "base64", "media_type": media, "data": data}}


def claude_ask_json(system: str, user: str, images: list[Path] | None = None, model: str | None = None, max_tokens: int = 8000) -> Any:
    """One Messages API call. Raises when no key is configured; callers handle fallbacks through engine.llm."""
    if settings.dry_run_agents:
        raise RuntimeError("ANTHROPIC_API_KEY missing")
    import anthropic

    client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
    content: list[dict[str, Any]] = [_image_block(p) for p in (images or [])]
    content.append({"type": "text", "text": user})
    msg = client.messages.create(model=model or settings.agent_model, max_tokens=max_tokens, system=system, messages=[{"role": "user", "content": content}])
    text = "".join(getattr(b, "text", "") for b in msg.content)
    return extract_json(text)
