"""Shared helpers for the Motion / QR / Links tests."""

from __future__ import annotations

import time

from fastapi.testclient import TestClient


def motion_client(client: TestClient) -> TestClient:
    """The studio app (routers included by backend/api.py)."""
    assert client.get("/api/motion/options").status_code == 200, "backend/api.py must include the links / qr / motion routers"
    return client


def wait_job(c: TestClient, job_id: int, timeout: float = 300) -> dict:
    t0 = time.time()
    while time.time() - t0 < timeout:
        j = c.get(f"/api/jobs/{job_id}").json()
        if j["status"] in ("done", "failed", "stopped"):
            return j
        time.sleep(0.2)
    raise AssertionError(f"job {job_id} did not finish")


def page_id(c: TestClient, number: int) -> int:
    pages = c.get("/api/pages?chapter_id=1").json()
    return next(p["id"] for p in pages if p["number"] == number)
