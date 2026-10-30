"""Art Director tables (same Base as backend/models.py; new tables are created by create_all at startup — additive).

DirectorRun keeps every step of one "Direct this page" (or one page of "Direct chapter"): the brief and its check,
the plan, every prompt, every candidate with its deterministic checks and critic JSON, the revisions, flags and cost.
DirectorCover is one volume's cover/poster: the composed prompt, painted art candidates, the author's uploaded current
cover (stored in the data dir, never in git) and the typeset exports.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, DateTime, Float, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from .models import Base, now


class DirectorRun(Base):
    __tablename__ = "director_run"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    kind: Mapped[str] = mapped_column(String(20), default="page")  # page | chapter
    parent_id: Mapped[int | None] = mapped_column(Integer, nullable=True)  # the chapter run a page run belongs to
    status: Mapped[str] = mapped_column(String(20), default="queued")  # queued|running|done|blocked|stopped|budget|failed
    chapter_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    page_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    page_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    job_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    manuscript: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)  # {label, number, title, book}
    brief: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    check: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    plan: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    prompts: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    candidates: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    steps: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    flags: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    settings: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    estimate: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    cost_usd: Mapped[float] = mapped_column(Float, default=0.0)
    guardrails_sha: Mapped[str] = mapped_column(String(80), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)


class DirectorCover(Base):
    __tablename__ = "director_cover"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    volume_id: Mapped[int] = mapped_column(Integer, unique=True)
    prompt: Mapped[str] = mapped_column(Text, default="")
    prompt_source: Mapped[str] = mapped_column(String(20), default="")
    facts: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    art_path: Mapped[str | None] = mapped_column(String(300), nullable=True)
    art_candidates: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    reference_path: Mapped[str | None] = mapped_column(String(300), nullable=True)
    publisher: Mapped[str] = mapped_column(String(200), default="")
    exports: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)
