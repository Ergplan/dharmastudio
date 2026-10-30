"""SQLite engine/session (one file data/studio.db) and the data/ folder layout."""

from __future__ import annotations

import os
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from engine.settings import settings

from .models import Base

DATA_DIR: Path = Path(os.environ.get("DHARMA_DATA_DIR") or settings.resolve_data_dir()).resolve()
DATA_DIR.mkdir(parents=True, exist_ok=True)
DB_PATH = DATA_DIR / "studio.db"

engine = create_engine(f"sqlite:///{DB_PATH}", future=True, connect_args={"check_same_thread": False, "timeout": 30})


@event.listens_for(engine, "connect")
def _sqlite_pragmas(dbapi_conn, _record) -> None:  # noqa: ANN001
    cur = dbapi_conn.cursor()
    cur.execute("PRAGMA journal_mode=WAL")
    cur.execute("PRAGMA foreign_keys=ON")
    cur.execute("PRAGMA busy_timeout=30000")
    cur.close()


SessionLocal = sessionmaker(bind=engine, expire_on_commit=False, future=True)


def init_db() -> None:
    Base.metadata.create_all(engine)
    for sub in ("canvases", "candidates", "refs", "silhouettes", "exports", "artifacts", "enhanced", "manuscript"):
        (DATA_DIR / sub).mkdir(parents=True, exist_ok=True)


def get_session() -> Iterator[Session]:
    s = SessionLocal()
    try:
        yield s
    finally:
        s.close()


@contextmanager
def session_scope() -> Iterator[Session]:
    s = SessionLocal()
    try:
        yield s
        s.commit()
    except Exception:
        s.rollback()
        raise
    finally:
        s.close()


def rel(path: Path | str) -> str:
    """Path under data/ -> stored relative path."""
    p = Path(path)
    try:
        return str(p.resolve().relative_to(DATA_DIR))
    except ValueError:
        return str(p)


def abs_path(rel_path: str | None) -> Path | None:
    if not rel_path:
        return None
    p = Path(rel_path)
    return p if p.is_absolute() else DATA_DIR / p


def media_url(rel_path: str | None) -> str | None:
    return f"/media/{rel_path}" if rel_path else None
