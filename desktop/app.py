"""Dharma Studio.app — native Mac entry point.

Starts the studio server on a free localhost port inside this process and shows it in a native window
(pywebview / WebKit). Projects live in ~/Library/Application Support/Dharma Studio; API keys live in the
macOS Keychain (service "Dharma Studio"), entered from Project → Keys inside the app. No Terminal, no pip.
"""

from __future__ import annotations

import os
import socket
import sys
import threading
import time
from pathlib import Path

APP_NAME = "Dharma Studio"
KEY_NAMES = ("OPENAI_API_KEY", "ANTHROPIC_API_KEY", "GEMINI_API_KEY", "TOPAZ_API_KEY")


def support_dir() -> Path:
    if sys.platform == "darwin":
        d = Path.home() / "Library" / "Application Support" / APP_NAME
    else:
        d = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share")) / "dharma-studio"
    d.mkdir(parents=True, exist_ok=True)
    return d


def bundle_root() -> Path:
    """Where engine/, backend/ and frontend/dist live: the PyInstaller bundle, or the repo when run from source."""
    return Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))


def load_keys_from_keychain() -> None:
    kf = support_dir() / "keys.env"  # fallback store when no Keychain is available
    if kf.exists():
        for ln in kf.read_text().splitlines():
            if "=" in ln:
                k, v = ln.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())
    try:
        import keyring
    except Exception:  # noqa: BLE001
        return
    for name in KEY_NAMES:
        if os.environ.get(name):
            continue
        try:
            v = keyring.get_password(APP_NAME, name)
        except Exception:  # noqa: BLE001
            v = None
        if v:
            os.environ[name] = v


def restore_seed_art(data: Path) -> None:
    from PIL import Image

    src = bundle_root() / "engine" / "seed_art"
    dst = data / "ch1_candidates"
    dst.mkdir(parents=True, exist_ok=True)
    for f in sorted(src.glob("*.jpg")):
        out = dst / f"{f.stem}.png"
        if not out.exists():
            Image.open(f).save(out)


def free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def wait_up(port: int, timeout: float = 60) -> bool:
    t0 = time.time()
    while time.time() - t0 < timeout:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.5):
                return True
        except OSError:
            time.sleep(0.2)
    return False


def main() -> None:
    root = str(bundle_root())
    if root not in sys.path:
        sys.path.insert(0, root)  # from source: make backend/ and engine/ importable
    data = support_dir() / "data"
    data.mkdir(parents=True, exist_ok=True)
    os.environ["DHARMA_DATA_DIR"] = str(data)
    os.environ["DHARMA_DESKTOP"] = "1"
    os.environ.setdefault("PIP_USE_DEPRECATED", "legacy-certs")
    load_keys_from_keychain()
    restore_seed_art(data)

    from backend import db  # noqa: E402  (after env is set)

    if not (data / "studio.db").exists():
        from backend import seed

        seed.run()

    import uvicorn

    from backend.api import app

    port = int(os.environ.get("DHARMA_PORT") or free_port())
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    threading.Thread(target=server.run, daemon=True).start()
    if not wait_up(port):
        raise SystemExit("Dharma Studio server did not start")
    url = f"http://127.0.0.1:{port}/"

    if "--headless" in sys.argv:  # smoke test / CI: serve until killed
        print(url, flush=True)
        while True:
            time.sleep(3600)

    import webview

    webview.create_window(APP_NAME, url, width=1600, height=1000, min_size=(1200, 760))
    webview.start()
    server.should_exit = True
    _ = db  # keep import


if __name__ == "__main__":
    main()
