"""The studio's own PDF engine: Google's "chrome-headless-shell" from Chrome for Testing, downloaded once into the
studio's data folder on first export. No Google Chrome install needed. Same Chromium print pipeline as the tests,
so the PDF honours @page size (176 x 266 mm with bleed), backgrounds and embedded fonts.
"""

from __future__ import annotations

import io
import os
import platform
import shutil
import stat
import subprocess
import sys
import threading
import zipfile
from pathlib import Path
from typing import Callable

import httpx

KNOWN_GOOD = "https://googlechromelabs.github.io/chrome-for-testing/last-known-good-versions-with-downloads.json"
UA = {"User-Agent": "DharmaStudio/1.0"}
_lock = threading.Lock()


def _platform_key() -> str:
    mach = platform.machine().lower()
    if sys.platform == "darwin":
        return "mac-arm64" if mach in ("arm64", "aarch64") else "mac-x64"
    if sys.platform.startswith("linux"):
        return "linux64"
    return "win64"


def engine_dir() -> Path:
    base = os.environ.get("DHARMA_DATA_DIR")
    root = Path(base).parent if base else Path.home() / ".dharma-studio"
    d = root / "pdf-engine"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _binary_in(d: Path) -> Path | None:
    for p in d.rglob("chrome-headless-shell"):
        if p.is_file():
            return p
    for p in d.rglob("chrome-headless-shell.exe"):
        return p
    return None


def installed() -> Path | None:
    return _binary_in(engine_dir())


def ensure(progress: Callable[[float, str], None] | None = None) -> Path:
    """Return the headless-shell binary, downloading it (~90 MB, once) if missing."""
    with _lock:
        b = installed()
        if b:
            return b
        say = progress or (lambda f, m: None)
        say(0.0, "Fetching the PDF engine (one time, about 90 MB)…")
        meta = httpx.get(KNOWN_GOOD, headers=UA, timeout=60, follow_redirects=True).json()
        stable = meta["channels"]["Stable"]
        key = _platform_key()
        url = next(d["url"] for d in stable["downloads"]["chrome-headless-shell"] if d["platform"] == key)
        buf = io.BytesIO()
        with httpx.stream("GET", url, headers=UA, timeout=900, follow_redirects=True) as r:
            r.raise_for_status()
            total = int(r.headers.get("content-length") or 0)
            got = 0
            for chunk in r.iter_bytes(1 << 20):
                buf.write(chunk)
                got += len(chunk)
                if total:
                    say(0.9 * got / total, f"Fetching the PDF engine… {got >> 20} of {total >> 20} MB")
        d = engine_dir()
        tmp = d / f"v{stable['version']}.part"
        if tmp.exists():
            shutil.rmtree(tmp)
        with zipfile.ZipFile(buf) as z:
            for info in z.infolist():
                z.extract(info, tmp)
                mode = (info.external_attr >> 16) & 0o777
                if mode:
                    os.chmod(tmp / info.filename, mode)
        final = d / f"v{stable['version']}"
        if final.exists():
            shutil.rmtree(final)
        tmp.rename(final)
        b = _binary_in(final)
        if not b:
            raise RuntimeError("PDF engine download did not contain chrome-headless-shell")
        b.chmod(b.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
        if sys.platform == "darwin":
            subprocess.run(["xattr", "-dr", "com.apple.quarantine", str(final)], capture_output=True)
        say(1.0, "PDF engine ready.")
        return b


def print_to_pdf(binary: Path, html_path: Path, out_pdf: Path) -> None:
    subprocess.run(
        [str(binary), "--headless", "--disable-gpu", "--no-sandbox", "--no-pdf-header-footer", "--hide-scrollbars",
         "--virtual-time-budget=4000", f"--print-to-pdf={out_pdf}", html_path.resolve().as_uri()],
        check=True, timeout=600, capture_output=True,
    )
