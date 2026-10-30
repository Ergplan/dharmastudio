"""Render every callout shape in light, warm and dark parchment to an HTML sheet (and a PNG with --png OUT).

    .venv/bin/python scripts/callout_gallery.py --png docs/screens/callout_shapes.png
"""

from __future__ import annotations

import glob
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from engine import colour as C  # noqa: E402
from engine import typography as T  # noqa: E402
from engine.comic import callouts as CO  # noqa: E402

TEXT = "Hanuman crossed the ocean not merely as a body of water, but a boundary between worlds."
STATE = {"light": "quiet", "warm": "rising", "dark": "peak"}


def sheet() -> str:
    ty = T.resolve()
    r = ty.role("narration", "en")
    size = ty.caption_mm("en")
    cells = []
    kinds = list(CO.KINDS) + ["bubble"]
    for i, kind in enumerate(kinds):
        for j, paper in enumerate(("light", "warm", "dark")):
            state = "ego" if kind == "jagged_dark" and paper == "dark" else ("knowledge" if kind == "cartouche" else STATE[paper])
            pad = (1.8, 2.4) if kind == "oval_vignette" else (3.2, 3.4)
            w = 52.0
            lines = T.wrap_lines(TEXT, r.face, size, w - 2 * pad[1])
            h = len(lines) * size * ty.line_height + 2 * pad[0] + 0.6
            sh = CO.build(kind, w, h, seed=11 + i * 3 + j, state=state, tail_x=w * 0.22)
            ox, oy = CO.tile_offset(i * 3 + j)
            mean = CO.mean_under(paper, ox + pad[1], oy + pad[0], w - 2 * pad[1], h - 2 * pad[0])
            seed = "#f2ede3" if paper == "dark" else "#3a2d1a"
            text = C.rgb_to_hex(C.ensure_contrast(C.hex_to_rgb(seed), mean))
            dark = paper == "dark"
            fill = {"use": f"sx{paper}", "offset": (ox, oy), "edge": "#9c7a4e" if dark else "#f4e9cf", "burn": "#0b0603" if dark else "#4a2e14", "burn_alpha": 0.6 if dark else 0.5}
            svg = CO.svg(sh, f"g{i}{j}", fill, False)
            x, y = 14 + j * 68, 16 + i * 46
            cells.append(f"<div class='cap' style=\"left:{x}mm;top:{y}mm;width:{w}mm;height:{h:.2f}mm;padding:{pad[0]}mm {pad[1]}mm;transform:rotate({sh.rotation}deg);color:{text};"
                         f"font-family:{r.stack};font-size:{size:.2f}mm;line-height:{ty.line_height}\">{svg}<span>{TEXT}</span></div>")
            if j == 0:
                cells.append(f"<div class='lbl' style='left:14mm;top:{y - 6}mm'>{CO.LABELS[kind]} — {CO.NOTES[kind]}</div>")
    css = T.font_face_css([r, ty.role("title", "en")], True)
    H = 16 + len(kinds) * 46 + 2
    return (f"<!doctype html><html><head><meta charset='utf-8'><style>{css}\nbody{{margin:0;background:#2a2622}}"
            f".sheet{{position:relative;width:216mm;height:{H}mm;background:url(data:image/jpeg;base64,{_b64(ROOT / 'engine/textures/page_light.jpg')}) center/cover}}"
            ".cap{position:absolute;box-sizing:border-box;display:flex;align-items:center}.cap>svg{position:absolute;overflow:visible}.cap>span{position:relative}"
            ".cap>svg.co{filter:drop-shadow(0 0.25mm 0.5mm rgba(0,0,0,.35))}"
            f".lbl{{position:absolute;font:2.6mm {ty.role('title', 'en').stack};color:#3a2d1a;letter-spacing:.04em}}</style></head>"
            f"<body><div class='sheet'>{CO.scrap_defs({'light', 'warm', 'dark'}, True)}{''.join(cells)}</div></body></html>")


def _b64(p: Path) -> str:
    import base64

    return base64.b64encode(p.read_bytes()).decode()


if __name__ == "__main__":
    html = sheet()
    if "--png" in sys.argv:
        out = Path(sys.argv[sys.argv.index("--png") + 1])
        from playwright.sync_api import sync_playwright

        exe = next(iter(sorted(glob.glob("/opt/pw-browsers/chromium*/chrome-linux*/chrome"))), None)
        with sync_playwright() as p:
            b = p.chromium.launch(**({"executable_path": exe} if exe else {}))
            pg = b.new_page(device_scale_factor=1.6)
            pg.set_content(html)
            pg.wait_for_timeout(800)
            pg.locator(".sheet").screenshot(path=str(out))
            b.close()
        print(f"wrote {out}")
    else:
        sys.stdout.write(html)
