# PyInstaller spec — builds "Dharma Studio.app" (onedir, windowed). Run from the repo root on macOS:
#   pyinstaller desktop/DharmaStudio.spec --noconfirm
import os
from pathlib import Path
from PyInstaller.utils.hooks import collect_all, collect_submodules

ROOT = Path(os.getcwd())

datas, binaries, hidden = [], [], []
for pkg in ("webview", "uvicorn", "keyring", "anthropic", "openai", "pikepdf", "pypdf"):
    d, b, h = collect_all(pkg)
    datas += d; binaries += b; hidden += h
hidden += collect_submodules("backend") + collect_submodules("engine")
hidden += ["keyring.backends.macOS", "yaml", "multipart", "python_multipart"]


def tree(src, dest, exts=None, skip=("__pycache__",)):
    out = []
    base = ROOT / src
    for p in base.rglob("*"):
        if p.is_dir() or any(s in p.parts for s in skip):
            continue
        if exts and p.suffix.lower() not in exts:
            continue
        out.append((str(p), str(Path(dest) / p.relative_to(base).parent)))
    return out


# non-Python files the engine and the UI need, at the same relative paths as in the repo
datas += tree("engine", "engine", exts={".md", ".yaml", ".yml", ".png", ".jpg", ".ttf", ".otf", ".txt", ".json", ".css", ".pdf"})
datas += tree("frontend/dist", "frontend/dist")
if (ROOT / "desktop" / "build_info.json").exists():
    datas.append((str(ROOT / "desktop" / "build_info.json"), "desktop"))

a = Analysis(
    [str(ROOT / "desktop" / "app.py")],
    pathex=[str(ROOT)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hidden,
    excludes=["playwright", "tkinter", "pytest", "IPython", "matplotlib"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="Dharma Studio", console=False,
          icon=str(ROOT / "desktop" / "icon.icns") if (ROOT / "desktop" / "icon.icns").exists() else None)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name="Dharma Studio")
app = BUNDLE(
    coll,
    name="Dharma Studio.app",
    icon=str(ROOT / "desktop" / "icon.icns") if (ROOT / "desktop" / "icon.icns").exists() else None,
    bundle_identifier="energy.aayuda.dharmastudio",
    info_plist={
        "CFBundleShortVersionString": "1.0.0",
        "CFBundleDisplayName": "Dharma Studio",
        "NSHighResolutionCapable": True,
        "LSMinimumSystemVersion": "14.0",
        "NSAppTransportSecurity": {"NSAllowsLocalNetworking": True},
    },
)
