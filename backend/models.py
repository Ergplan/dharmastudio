"""SPEC §3 tables. SQLite via SQLAlchemy 2; images on disk under data/ (paths stored relative to data/)."""

from __future__ import annotations

import enum
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def now() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class Project(Base):
    __tablename__ = "project"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    title: Mapped[str] = mapped_column(String(200))
    author: Mapped[str] = mapped_column(String(200), default="")
    manuscript_pdf: Mapped[str | None] = mapped_column(String(500), nullable=True)
    settings: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)

    volumes: Mapped[list["Volume"]] = relationship(back_populates="project", order_by="Volume.number")
    characters: Mapped[list["Character"]] = relationship(back_populates="project", order_by="Character.id")


class Volume(Base):
    __tablename__ = "volume"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("project.id"))
    number: Mapped[int] = mapped_column(Integer)
    title: Mapped[str] = mapped_column(String(200), default="")
    canvas_id: Mapped[int | None] = mapped_column(ForeignKey("canvas.id"), nullable=True)
    era_default: Mapped[str] = mapped_column(String(40), default="treta")
    typography: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)  # engine/typography.py setting; None = default
    page_mode: Mapped[str | None] = mapped_column(String(20), nullable=True)  # painted | shards; None = default (Volume 1 painted)

    project: Mapped[Project] = relationship(back_populates="volumes")
    canvas: Mapped["Canvas | None"] = relationship()
    chapters: Mapped[list["Chapter"]] = relationship(back_populates="volume", order_by="Chapter.number")


class Canvas(Base):
    __tablename__ = "canvas"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    key: Mapped[str] = mapped_column(String(40), unique=True)
    name: Mapped[str] = mapped_column(String(120))
    paper_texture: Mapped[str] = mapped_column(String(300), default="")  # path under data/
    ink: Mapped[str] = mapped_column(String(20), default="#3a2d1a")
    gutter: Mapped[str] = mapped_column(String(20), default="paper")
    caption_style: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    marginalia_style: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    preview: Mapped[str] = mapped_column(String(300), default="")


class Chapter(Base):
    __tablename__ = "chapter"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    volume_id: Mapped[int] = mapped_column(ForeignKey("volume.id"))
    number: Mapped[int] = mapped_column(Integer)
    title: Mapped[str] = mapped_column(String(200), default="")
    text: Mapped[str] = mapped_column(Text, default="")
    pages_from: Mapped[int | None] = mapped_column(Integer, nullable=True)
    pages_to: Mapped[int | None] = mapped_column(Integer, nullable=True)

    volume: Mapped[Volume] = relationship(back_populates="chapters")
    pages: Mapped[list["Page"]] = relationship(back_populates="chapter", order_by="Page.number", cascade="all, delete-orphan")


class Character(Base):
    __tablename__ = "character"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("project.id"))
    name: Mapped[str] = mapped_column(String(120))
    form_key: Mapped[str] = mapped_column(String(80), unique=True)
    look: Mapped[str] = mapped_column(Text, default="")
    locked: Mapped[bool] = mapped_column(Boolean, default=False)
    primary_ref_id: Mapped[int | None] = mapped_column(Integer, nullable=True)

    project: Mapped[Project] = relationship(back_populates="characters")
    refs: Mapped[list["CharacterRef"]] = relationship(back_populates="character", order_by="CharacterRef.id", cascade="all, delete-orphan")


class CharacterRef(Base):
    __tablename__ = "character_ref"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    character_id: Mapped[int] = mapped_column(ForeignKey("character.id"))
    path: Mapped[str] = mapped_column(String(300))
    provider: Mapped[str] = mapped_column(String(40), default="upload")
    prompt: Mapped[str] = mapped_column(Text, default="")
    is_primary: Mapped[bool] = mapped_column(Boolean, default=False)
    approved: Mapped[bool] = mapped_column(Boolean, default=False)

    character: Mapped[Character] = relationship(back_populates="refs")


class PageStatus(str, enum.Enum):
    empty = "empty"
    draft = "draft"
    generating = "generating"
    review = "review"
    approved = "approved"


class Page(Base):
    __tablename__ = "page"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    chapter_id: Mapped[int] = mapped_column(ForeignKey("chapter.id"))
    number: Mapped[int] = mapped_column(Integer)
    beat: Mapped[str | None] = mapped_column(String(20), nullable=True)
    status: Mapped[str] = mapped_column(String(20), default=PageStatus.empty.value)
    canvas_override: Mapped[int | None] = mapped_column(ForeignKey("canvas.id"), nullable=True)
    marginalia: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    seed: Mapped[int] = mapped_column(Integer, default=7)
    is_opener: Mapped[bool] = mapped_column(Boolean, default=False)
    epigraph: Mapped[str] = mapped_column(Text, default="")
    epigraph_hi: Mapped[str] = mapped_column(Text, default="")
    artifacts: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)  # {"en": path, "hi": path} written on approve
    typography_override: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)  # partial setting over the volume's
    ink_dissolve: Mapped[bool | None] = mapped_column(Boolean, nullable=True)  # None = auto (on for calm pages on painted canvases)
    manuscript: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)  # {auto, verses[], figures[]}; None = auto
    page_mode: Mapped[str | None] = mapped_column(String(20), nullable=True)  # painted | shards; None = the volume's
    # painted-page mode: {spec, candidates[{id, path, prompt, attempt, verification, verdict, ...}], selected_id}
    painted: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)

    chapter: Mapped[Chapter] = relationship(back_populates="pages")
    panels: Mapped[list["Panel"]] = relationship(back_populates="page", order_by="Panel.n", cascade="all, delete-orphan")


class Panel(Base):
    __tablename__ = "panel"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    page_id: Mapped[int] = mapped_column(ForeignKey("page.id"))
    n: Mapped[int] = mapped_column(Integer)
    kind: Mapped[str] = mapped_column(String(20), default="shard")  # shard | plate
    shape: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)  # {kind, polygon_mm[], edge, z, focal{x,y,scale}}
    image_group: Mapped[str | None] = mapped_column(String(40), nullable=True)
    scene: Mapped[str] = mapped_column(Text, default="")
    scale: Mapped[str] = mapped_column(String(8), default="MS")
    state: Mapped[str] = mapped_column(String(20), default="quiet")
    beat: Mapped[str | None] = mapped_column(String(20), nullable=True)
    weight: Mapped[float] = mapped_column(Float, default=1.0)
    characters: Mapped[list[str]] = mapped_column(JSON, default=list)
    environment: Mapped[str | None] = mapped_column(String(200), nullable=True)
    source_page: Mapped[str] = mapped_column(String(20), default="")
    caption_en: Mapped[str] = mapped_column(Text, default="")
    caption_hi: Mapped[str] = mapped_column(Text, default="")
    balloon_en: Mapped[str] = mapped_column(Text, default="")
    balloon_hi: Mapped[str] = mapped_column(Text, default="")
    speaker: Mapped[str | None] = mapped_column(String(120), nullable=True)
    hi_is_draft: Mapped[bool] = mapped_column(Boolean, default=False)
    selected_candidate_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    locked_shape: Mapped[bool] = mapped_column(Boolean, default=False)
    sfx: Mapped[str | None] = mapped_column(Text, nullable=True, default="")  # lettered sound effect; empty = none
    text_colours: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)  # pinned callout colours; None = auto
    callout_shape: Mapped[str | None] = mapped_column(String(30), nullable=True)  # auto | engine.comic.callouts kind
    balloon_shape: Mapped[str | None] = mapped_column(String(30), nullable=True)

    page: Mapped[Page] = relationship(back_populates="panels")
    candidates: Mapped[list["Candidate"]] = relationship(back_populates="panel", order_by="Candidate.id", cascade="all, delete-orphan")

    @property
    def number(self) -> int:
        return self.page.number * 100 + self.n


class Candidate(Base):
    __tablename__ = "candidate"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    panel_id: Mapped[int] = mapped_column(ForeignKey("panel.id"))
    path: Mapped[str] = mapped_column(String(300))
    provider: Mapped[str] = mapped_column(String(40), default="sunburst")
    model: Mapped[str] = mapped_column(String(80), default="")
    prompt_full: Mapped[str] = mapped_column(Text, default="")
    feedback_used: Mapped[str] = mapped_column(Text, default="")
    cost_usd: Mapped[float] = mapped_column(Float, default=0.0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    qa: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    rejected: Mapped[bool] = mapped_column(Boolean, default=False)

    panel: Mapped[Panel] = relationship(back_populates="candidates")


class Silhouette(Base):
    __tablename__ = "silhouette"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("project.id"))
    path: Mapped[str] = mapped_column(String(300))
    tags: Mapped[list[str]] = mapped_column(JSON, default=list)
    source: Mapped[str] = mapped_column(String(20), default="generated")  # generated | uploaded
    prompt: Mapped[str] = mapped_column(Text, default="")


class JobStatus(str, enum.Enum):
    queued = "queued"
    running = "running"
    done = "done"
    failed = "failed"
    stopped = "stopped"


class Job(Base):
    __tablename__ = "job"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    kind: Mapped[str] = mapped_column(String(40))
    ref_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default=JobStatus.queued.value)
    log: Mapped[str] = mapped_column(Text, default="")
    cost_usd: Mapped[float] = mapped_column(Float, default=0.0)
    # additions to §3: the request, the result (e.g. the PDF path), batch progress and the stop flag
    params: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    result: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    progress: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    stop: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)


class Ledger(Base):
    __tablename__ = "ledger"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    provider: Mapped[str] = mapped_column(String(40))
    usd: Mapped[float] = mapped_column(Float, default=0.0)
    ref: Mapped[str] = mapped_column(String(200), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
