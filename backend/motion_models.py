"""Tables for Motion, QR, Links, Seedance takes and site publishing — on the studio's declarative Base, so
`Base.metadata.create_all` creates them with the rest (import this module before init_db)."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from .models import Base, now


class Link(Base):
    """A stable short URL https://cycleofdharma.world/v/{code}. Once print_locked the code is immutable for ever."""

    __tablename__ = "link"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(String(40), unique=True, index=True)
    target_type: Mapped[str] = mapped_column(String(20), default="moment")  # moment | chapter | page | url
    target_ref: Mapped[str] = mapped_column(String(500), default="")  # moment/chapter/page id, or a URL
    destination_override: Mapped[str | None] = mapped_column(String(500), nullable=True)  # e.g. a YouTube URL (302)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    notes: Mapped[str] = mapped_column(Text, default="")
    print_locked: Mapped[bool] = mapped_column(Boolean, default=False)
    scans_note: Mapped[str] = mapped_column(Text, default="")
    check: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)  # last external HEAD check
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)


class QRCode(Base):
    """A saved QR (link + style + size). `test` is the decode test of exactly this url+style (sig); stale = untested."""

    __tablename__ = "qr_code"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    link_id: Mapped[int] = mapped_column(ForeignKey("link.id"))
    name: Mapped[str] = mapped_column(String(120), default="")
    style: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    emblem_path: Mapped[str | None] = mapped_column(String(300), nullable=True)  # uploaded emblem (PNG) under data/
    test: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    test_sig: Mapped[str | None] = mapped_column(String(64), nullable=True)
    approved: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class PageQR(Base):
    """A QR placed on a page (the page element): position and width in page mm; printed in print mode."""

    __tablename__ = "page_qr"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    page_id: Mapped[int] = mapped_column(ForeignKey("page.id"), index=True)
    qr_id: Mapped[int] = mapped_column(ForeignKey("qr_code.id"))
    x_mm: Mapped[float] = mapped_column(Float, default=0.0)
    y_mm: Mapped[float] = mapped_column(Float, default=0.0)
    w_mm: Mapped[float] = mapped_column(Float, default=22.0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class Moment(Base):
    """A page carrying a 30-second film made from its approved panels (and Seedance takes)."""

    __tablename__ = "moment"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    page_id: Mapped[int] = mapped_column(ForeignKey("page.id"), unique=True)
    link_id: Mapped[int | None] = mapped_column(ForeignKey("link.id"), nullable=True)
    qr_id: Mapped[int | None] = mapped_column(ForeignKey("qr_code.id"), nullable=True)
    title_en: Mapped[str] = mapped_column(String(300), default="")
    title_hi: Mapped[str] = mapped_column(String(300), default="")
    shots: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)  # [{panel_id|take_id, source, duration_s, move, focal}]
    narration_en: Mapped[str] = mapped_column(Text, default="")
    narration_hi: Mapped[str] = mapped_column(Text, default="")
    voice: Mapped[str] = mapped_column(String(20), default="none")  # none | elevenlabs
    voice_id: Mapped[str] = mapped_column(String(80), default="")
    music_path: Mapped[str | None] = mapped_column(String(300), nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="draft")  # draft | rendering | review | approved | published
    outputs: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)  # en_16x9, en_9x16, hi_16x9, hi_9x16, poster, poster_9x16
    render_meta: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)


class MotionTake(Base):
    """One Seedance run (or dry run) from a panel's selected image or an uploaded still. Every take is kept."""

    __tablename__ = "motion_take"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    panel_id: Mapped[int | None] = mapped_column(ForeignKey("panel.id"), nullable=True)
    still_path: Mapped[str] = mapped_column(String(300), default="")
    prompt: Mapped[str] = mapped_column(Text, default="")
    params: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)  # duration, resolution, aspect, seed, camera
    provider: Mapped[str] = mapped_column(String(20), default="fal")
    model: Mapped[str] = mapped_column(String(120), default="")
    cost_usd: Mapped[float] = mapped_column(Float, default=0.0)
    path: Mapped[str | None] = mapped_column(String(300), nullable=True)  # the mp4 under data/
    thumb: Mapped[str | None] = mapped_column(String(300), nullable=True)
    seed: Mapped[int | None] = mapped_column(Integer, nullable=True)
    dry_run: Mapped[bool] = mapped_column(Boolean, default=False)
    status: Mapped[str] = mapped_column(String(20), default="queued")  # queued | running | done | failed
    job_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    picked: Mapped[bool] = mapped_column(Boolean, default=False)
    notes: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class SitePublish(Base):
    """Every site build / publish / export, with its result."""

    __tablename__ = "site_publish"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    kind: Mapped[str] = mapped_column(String(20), default="preview")  # preview | publish | zip
    ok: Mapped[bool] = mapped_column(Boolean, default=False)
    result: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


MOTION_TABLES = ("link", "qr_code", "page_qr", "moment", "motion_take", "site_publish")


def ensure_tables(engine) -> None:  # noqa: ANN001
    """Create the motion tables on an existing studio.db (create_all only adds missing tables)."""
    Base.metadata.create_all(engine, tables=[Base.metadata.tables[t] for t in MOTION_TABLES])
