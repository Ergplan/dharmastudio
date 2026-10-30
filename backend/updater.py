"""In-app updater for Dharma Studio.app.

The CI build stamps desktop/build_info.json ({build, sha, built_at}) into the bundle and uploads the same file and
DharmaStudio.dmg to the GitHub release tagged `latest`. The app compares build numbers; to update it downloads the
.dmg, mounts it, copies the new app beside the old one, and hands over to a small detached shell script that waits
for this process to exit, swaps the bundles, and relaunches. Projects and keys live outside the bundle
(~/Library/Application Support/Dharma Studio and the Keychain), so they are untouched.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path
from typing import Any

import httpx

REPO = os.environ.get("DHARMA_UPDATE_REPO", "Ergplan/dharmastudio")
RELEASE_BASE = f"https://github.com/{REPO}/releases/download/latest"
INFO_URL = f"{RELEASE_BASE}/build_info.json"
DMG_URL = f"{RELEASE_BASE}/DharmaStudio.dmg"
UA = {"User-Agent": "DharmaStudio-Updater/1.0"}

_state: dict[str, Any] = {"phase": "idle", "progress": 0.0, "message": "", "latest": None, "checked_at": None}
_lock = threading.Lock()


def _bundle_root() -> Path:
    return Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))


def current() -> dict[str, Any]:
    info = {"build": 0, "sha": "dev", "built_at": None}
    for p in (_bundle_root() / "desktop" / "build_info.json", Path(__file__).resolve().parent.parent / "desktop" / "build_info.json"):
        if p.exists():
            try:
                info.update(json.loads(p.read_text()))
                break
            except Exception:  # noqa: BLE001
                pass
    app = app_bundle()
    info["desktop"] = bool(os.environ.get("DHARMA_DESKTOP"))
    info["updatable"] = bool(app) and sys.platform == "darwin"
    info["app_path"] = str(app) if app else None
    return info


def app_bundle() -> Path | None:
    """…/Dharma Studio.app when running frozen inside a bundle, else None."""
    if not getattr(sys, "frozen", False):
        return None
    exe = Path(sys.executable).resolve()
    for parent in exe.parents:
        if parent.suffix == ".app":
            return parent
    return None


def check(timeout: float = 15) -> dict[str, Any]:
    cur = current()
    try:
        r = httpx.get(INFO_URL, headers=UA, timeout=timeout, follow_redirects=True)
        r.raise_for_status()
        latest = r.json()
    except Exception as e:  # noqa: BLE001
        with _lock:
            _state.update(checked_at=time.time(), message=f"could not reach GitHub: {e.__class__.__name__}")
        return {"current": cur, "latest": None, "available": False, "error": str(e)[:200]}
    # a source checkout (build 0) never offers updates; a packaged app updates to any higher build number
    available = cur["build"] > 0 and int(latest.get("build", 0)) > int(cur["build"])
    with _lock:
        _state.update(latest=latest, checked_at=time.time(), message="")
    return {"current": cur, "latest": latest, "available": bool(available)}


def status() -> dict[str, Any]:
    with _lock:
        return dict(_state)


def _set(**kw: Any) -> None:
    with _lock:
        _state.update(kw)


def apply_async() -> dict[str, Any]:
    cur = current()
    if not cur["updatable"]:
        return {"ok": False, "reason": "Updates install only in the packaged Mac app (Dharma Studio.app)."}
    with _lock:
        if _state["phase"] in ("downloading", "installing"):
            return {"ok": True, "already": True}
        _state.update(phase="downloading", progress=0.0, message="Downloading the latest build…")
    threading.Thread(target=_apply, daemon=True).start()
    return {"ok": True}


def _apply() -> None:
    app = app_bundle()
    if app is None:
        _set(phase="error", message="Not running from Dharma Studio.app")
        return
    work = Path(tempfile.mkdtemp(prefix="dharma-update-"))
    dmg = work / "DharmaStudio.dmg"
    try:
        with httpx.stream("GET", DMG_URL, headers=UA, timeout=600, follow_redirects=True) as r:
            r.raise_for_status()
            total = int(r.headers.get("content-length") or 0)
            got = 0
            with open(dmg, "wb") as fh:
                for chunk in r.iter_bytes(1 << 20):
                    fh.write(chunk)
                    got += len(chunk)
                    if total:
                        _set(progress=round(0.8 * got / total, 3))
        _set(phase="installing", progress=0.82, message="Preparing the new version…")
        mnt = work / "mnt"
        mnt.mkdir()
        subprocess.run(["hdiutil", "attach", "-nobrowse", "-readonly", "-mountpoint", str(mnt), str(dmg)], check=True, capture_output=True)
        try:
            src = next(mnt.glob("*.app"))
            staged = app.parent / f".{app.stem}.update.app"
            if staged.exists():
                shutil.rmtree(staged)
            subprocess.run(["ditto", str(src), str(staged)], check=True, capture_output=True)
        finally:
            subprocess.run(["hdiutil", "detach", str(mnt), "-quiet"], capture_output=True)
        subprocess.run(["xattr", "-dr", "com.apple.quarantine", str(staged)], capture_output=True)
        _set(progress=0.95, message="Restarting into the new version…")
        script = work / "swap.sh"
        script.write_text(
            "#!/bin/bash\n"
            f"while kill -0 {os.getpid()} 2>/dev/null; do sleep 0.3; done\n"
            f'old="{app}"; new="{staged}"; bak="{app.parent}/.{app.stem}.previous.app"\n'
            'rm -rf "$bak"; mv "$old" "$bak" && mv "$new" "$old" && rm -rf "$bak" || { [ -d "$bak" ] && [ ! -d "$old" ] && mv "$bak" "$old"; }\n'
            'open "$old"\n'
            f'rm -rf "{work}"\n'
        )
        script.chmod(0o755)
        subprocess.Popen(["/bin/bash", str(script)], start_new_session=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        _set(phase="restarting", progress=1.0)
        time.sleep(0.8)
        os._exit(0)
    except Exception as e:  # noqa: BLE001
        _set(phase="error", message=f"Update failed: {e}"[:300])
