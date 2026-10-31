"""One text-model interface for every agent: `ask_json(role, system, user, images=[])`.

The role (script_writer / prompt_writer / critic) maps to a model chosen on the Project screen and stored in
Project.settings.models. Claude models go through the Messages API, gpt-* models through the OpenAI Responses API
with JSON output. Same prompts, same fallbacks: when the chosen provider has no key the caller's fallback runs.
"""

from __future__ import annotations

import base64
import json
from pathlib import Path
from typing import Any, Callable

from .claude_agent import claude_ask_json, extract_json
from .settings import settings

TEXT_ROLES = ("script_writer", "prompt_writer", "critic")
IMAGE_ROLE = "image"

CLAUDE_MODELS = ["claude-sonnet-4-5", "claude-opus-4-1"]
OPENAI_MODELS = ["gpt-5", "gpt-5-mini", "gpt-6.1-sol", "gpt-5.5"]
IMAGE_MODELS = {"sunburst": "openai", "gemini-nb21": "gemini", "gemini-pro": "gemini"}

ROLE_DEFAULTS = {"script_writer": "claude", "prompt_writer": "openai", "critic": "claude", "image": "sunburst"}

# the model chosen per role lives in Project.settings.models; this module is told it through `set_selected`
_selected: dict[str, str] = {}


def set_selected(models: dict[str, str] | None) -> None:
    _selected.clear()
    _selected.update({k: v for k, v in (models or {}).items() if v})


def providers() -> dict[str, bool]:
    k = settings.key_status()
    return {"anthropic": k["anthropic"], "openai": k["openai"], "gemini": k["gemini"], "topaz": k["topaz"]}


MODEL_LABELS = {
    "claude-sonnet-4-5": ("Claude Sonnet 4.5", "anthropic", ""),
    "claude-opus-4-1": ("Claude Opus 4.1", "anthropic", "slower, deeper"),
    "gpt-5": ("OpenAI GPT-5", "openai", ""),
    "gpt-5-mini": ("OpenAI GPT-5 mini", "openai", "fast, cheap"),
    "gpt-6.1-sol": ("OpenAI GPT-6.1 Sol", "openai", "vision; the painted-page text check default"),
    "gpt-5.5": ("OpenAI GPT-5.5", "openai", "vision; the text check fallback"),
    "sunburst": ("Sunburst (OpenAI)", "openai", "≈ $0.04 per 1536×1024 high image"),
    "gemini-nb21": ("Gemini NB 2.1", "gemini", "≈ $0.03 per image"),
    "gemini-pro": ("Gemini Pro", "gemini", "≈ $0.13 per image"),
}


def _choice(mid: str) -> dict[str, str]:
    label, prov, note = MODEL_LABELS[mid]
    return {"id": mid, "label": label, "provider": prov, "note": note}


def choices() -> dict[str, list[str]]:
    """Choices available per role — only from providers whose key is present (SPEC §8)."""
    p = providers()
    text = (CLAUDE_MODELS if p["anthropic"] else []) + (OPENAI_MODELS if p["openai"] else [])
    image = (["sunburst"] if p["openai"] else []) + (["gemini-nb21", "gemini-pro"] if p["gemini"] else [])
    return {"script_writer": list(text), "prompt_writer": list(text), "critic": list(text), "image": image}


def choice_objects() -> dict[str, list[dict[str, str]]]:
    """Every model per role with its provider; the UI disables the ones whose key is missing in .env."""
    text = [_choice(m) for m in CLAUDE_MODELS + OPENAI_MODELS]
    return {"script_writer": text, "prompt_writer": text, "critic": text, "image": [_choice(m) for m in IMAGE_MODELS]}


def known_model(role: str, mid: str) -> bool:
    return any(c["id"] == mid for c in choice_objects()[role])


def provider_of(model: str) -> str:
    if model.startswith("claude"):
        return "anthropic"
    if model.startswith("gpt"):
        return "openai"
    return IMAGE_MODELS.get(model, "openai")


def default_model(role: str) -> str:
    """The role's default, falling back to whatever provider has a key."""
    p = providers()
    if role == IMAGE_ROLE:
        if p["openai"]:
            return "sunburst"
        if p["gemini"]:
            return "gemini-nb21"
        return "sunburst"
    pref = ROLE_DEFAULTS[role]
    if pref == "openai" and p["openai"]:
        return OPENAI_MODELS[0]
    if p["anthropic"]:
        return settings.agent_model if settings.agent_model in CLAUDE_MODELS else CLAUDE_MODELS[0]
    if p["openai"]:
        return OPENAI_MODELS[0]
    return settings.agent_model


def selected() -> dict[str, str]:
    out = {}
    for role in (*TEXT_ROLES, IMAGE_ROLE):
        m = _selected.get(role)
        if not m or (role != IMAGE_ROLE and provider_of(m) not in ("anthropic", "openai")):
            m = default_model(role)
        out[role] = m
    return out


def model_for(role: str) -> str:
    return selected()[role]


def is_available(role: str) -> bool:
    prov = provider_of(model_for(role))
    return providers().get(prov, False)


def _openai_ask_json(system: str, user: str, images: list[Path], model: str) -> Any:
    from openai import OpenAI

    client = OpenAI(api_key=settings.openai_api_key)
    content: list[dict[str, Any]] = []
    for p in images:
        media = "image/png" if p.suffix.lower() == ".png" else "image/jpeg"
        content.append({"type": "input_image", "image_url": f"data:{media};base64,{base64.b64encode(p.read_bytes()).decode()}"})
    content.append({"type": "input_text", "text": user})
    resp = client.responses.create(
        model=model,
        instructions=system,
        input=[{"role": "user", "content": content}],
        text={"format": {"type": "json_object"}},
    )
    text = getattr(resp, "output_text", "") or ""
    if not text:
        for item in getattr(resp, "output", []) or []:
            for c in getattr(item, "content", []) or []:
                text += getattr(c, "text", "") or ""
    return extract_json(text)


def ask_json(role: str, system: str, user: str, images: list[Path] | None = None, fallback: Callable[[], Any] | None = None, max_tokens: int = 8000) -> Any:
    """Route to the role's model. On a missing key (or a provider error when a fallback exists) the fallback runs."""
    model = model_for(role)
    prov = provider_of(model)
    available = providers().get(prov, False)
    if not available:
        if fallback is None:
            raise RuntimeError(f"{role}: no key for {prov} and no fallback")
        return fallback()
    try:
        if prov == "anthropic":
            return claude_ask_json(system, user, images or [], model=model, max_tokens=max_tokens)
        return _openai_ask_json(system, user, images or [], model)
    except Exception:  # noqa: BLE001 — provider failure: degrade to the fallback rather than kill the job
        if fallback is None:
            raise
        return fallback()


def ask_json_models(models: list[str], system: str, user: str, images: list[Path] | None = None, fallback: Callable[[], Any] | None = None,
                    max_tokens: int = 8000) -> tuple[Any, str | None]:
    """Ask the first model in `models` whose provider has a key; on a provider error try the next one (e.g. the
    painted-page text check: gpt-6.1-sol, then gpt-5.5). Returns (answer, model used) — (fallback(), None) when none works."""
    keys = providers()
    for model in models:
        prov = provider_of(model)
        if not keys.get(prov, False):
            continue
        try:
            if prov == "anthropic":
                return claude_ask_json(system, user, images or [], model=model, max_tokens=max_tokens), model
            return _openai_ask_json(system, user, images or [], model), model
        except Exception:  # noqa: BLE001 — try the next model
            continue
    if fallback is None:
        raise RuntimeError(f"no model available among {models}")
    return fallback(), None


def dumps(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False)
