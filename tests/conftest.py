"""Tests run against a fresh data dir (a temp copy with the Chapter 1 candidates linked in), seeded once."""

from __future__ import annotations

import os
import shutil
import sys
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

_tmp = Path(tempfile.mkdtemp(prefix="dharma-test-"))
os.environ["DHARMA_DATA_DIR"] = str(_tmp)
src = ROOT / "data" / "ch1_candidates"
if src.exists():
    os.symlink(src, _tmp / "ch1_candidates")
# reuse the textures already generated for the repo (fast); otherwise they are painted at seed time
tex = ROOT / "data" / "canvases"
if tex.exists():
    shutil.copytree(tex, _tmp / "canvases")

from backend import db, seed  # noqa: E402
from backend.api import app  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def seeded() -> dict:
    return seed.run(reset=True)


@pytest.fixture(scope="session")
def client():
    from fastapi.testclient import TestClient

    with TestClient(app) as c:
        yield c


@pytest.fixture()
def session():
    s = db.SessionLocal()
    try:
        yield s
    finally:
        s.close()
