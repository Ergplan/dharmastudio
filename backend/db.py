"""SQLite engine/session (one file data/studio.db) and the data/ folder layout."""

from __future__ import annotations

import os
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from engine.settings import settings

from . import motion_models  # noqa: F401  (Motion / QR / Links tables on the same Base)
from .models import Base
from . import director_models  # noqa: E402,F401  — Art Director tables (created additively by create_all)

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


# columns added after a studio.db may already exist: (table, column, SQL type). Added at startup when missing; nothing
# is ever dropped or rewritten.
ADDED_COLUMNS = (
    ("volume", "typography", "JSON"),
    ("page", "typography_override", "JSON"),
    ("panel", "sfx", "TEXT DEFAULT ''"),
    ("panel", "text_colours", "JSON"),
    ("panel", "callout_shape", "VARCHAR(30)"),
    ("panel", "balloon_shape", "VARCHAR(30)"),
    ("page", "ink_dissolve", "BOOLEAN"),
    ("page", "manuscript", "JSON"),
    ("volume", "page_mode", "VARCHAR(20)"),
    ("page", "page_mode", "VARCHAR(20)"),
    ("page", "painted", "JSON"),
)


def migrate() -> list[str]:
    """Light, additive migration for existing studio.db files. Returns the columns it added."""
    from sqlalchemy import inspect, text

    added: list[str] = []
    insp = inspect(engine)
    tables = set(insp.get_table_names())
    with engine.begin() as conn:
        for table, col, sqltype in ADDED_COLUMNS:
            if table not in tables:
                continue
            if col not in {c["name"] for c in insp.get_columns(table)}:
                conn.execute(text(f'ALTER TABLE "{table}" ADD COLUMN "{col}" {sqltype}'))
                added.append(f"{table}.{col}")
    return added


def init_db() -> None:
    Base.metadata.create_all(engine)
    migrate()
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
