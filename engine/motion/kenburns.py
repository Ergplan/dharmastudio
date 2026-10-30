"""Ken Burns shots from an approved panel: eased camera moves over the still, plus a two-layer parallax move.

Every frame is an affine resample of the source (sub-pixel smooth, no zoompan stair-stepping) piped to the bundled
ffmpeg at 24 fps. The same `ShotRenderer` feeds both a stand-alone clip (`render_clip`) and the moment assembly.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from PIL import Image, ImageDraw, ImageFilter

from . import ffmpeg as FF

MOVES = ("push_in", "pull_out", "pan", "orbit", "crane", "static", "parallax")
MOVE_LABELS = {"push_in": "Push in", "pull_out": "Pull out", "pan": "Pan", "orbit": "Orbit", "crane": "Crane", "static": "Static breathing", "parallax": "Parallax (2 layers)"}


def ease(t: float) -> float:
    """Ease in-out (cubic)."""
    t = min(1.0, max(0.0, t))
    return 4 * t * t * t if t < 0.5 else 1 - (-2 * t + 2) ** 3 / 2


@dataclass
class Cam:
    cx: float  # window centre, 0-1 of the source
    cy: float
    zoom: float  # 1 = the largest window of the output aspect that fits the source
    rot: float = 0.0  # degrees


def camera(move: str, t: float, focal: tuple[float, float] = (0.5, 0.5), direction: int = 1) -> Cam:
    fx, fy = focal
    e = ease(t)
    if move == "push_in":
        return Cam(0.5 + (fx - 0.5) * e, 0.5 + (fy - 0.5) * e, 1.0 + 0.22 * e)
    if move == "pull_out":
        return Cam(fx + (0.5 - fx) * e, fy + (0.5 - fy) * e, 1.22 - 0.22 * e)
    if move == "pan":
        return Cam(0.5 + direction * (-0.5 + e) * 0.9, fy, 1.12)  # the window travels across; clamped later
    if move == "orbit":
        a = (e - 0.5) * math.pi * 0.5
        return Cam(fx + math.sin(a) * 0.08 * direction, fy + (1 - math.cos(a)) * 0.04, 1.14 + 0.04 * math.cos(a), rot=-direction * 1.6 * math.sin(a))
    if move == "crane":
        return Cam(fx, 0.5 + (0.6 - 1.2 * e) * 0.5 * direction, 1.14 + 0.06 * e)
    if move == "static":
        return Cam(fx, fy, 1.04 + 0.025 * math.sin(math.pi * t))
    return Cam(fx, fy, 1.06 + 0.12 * e)  # parallax: the background layer's own move


@dataclass
class Shot:
    image: Path
    move: str = "push_in"
    duration: float = 6.0
    focal: tuple[float, float] = (0.5, 0.5)
    direction: int = 1
    mark: str = ""  # e.g. "DRY RUN" in the corner


@dataclass
class ShotRenderer:
    shot: Shot
    size: tuple[int, int]
    _src: Image.Image | None = None
    _fg: Image.Image | None = None
    _mask: Image.Image | None = None
    _mark: Image.Image | None = field(default=None, repr=False)

    def _load(self) -> Image.Image:
        if self._src is None:
            src = Image.open(self.shot.image).convert("RGB")
            # enough pixels for the deepest zoom; never more than ~2x the output
            W, H = self.size
            need = max(W / src.width, H / src.height) * 1.35
            if need < 0.5:  # a very large still: shrink once (the affine resample does any upscaling)
                src = src.resize((max(W, round(src.width * need * 2)), max(H, round(src.height * need * 2))), Image.LANCZOS)
            self._src = src
        return self._src

    def _window(self, cam: Cam, src: Image.Image) -> tuple[float, float, float, float]:
        W, H = self.size
        ar = W / H
        bw, bh = (src.width, src.width / ar) if src.width / src.height < ar else (src.height * ar, src.height)
        ww, wh = bw / cam.zoom, bh / cam.zoom
        cx = min(max(cam.cx * src.width, ww / 2), src.width - ww / 2)
        cy = min(max(cam.cy * src.height, wh / 2), src.height - wh / 2)
        return cx, cy, ww, wh

    def _affine(self, src: Image.Image, cam: Cam) -> Image.Image:
        W, H = self.size
        cx, cy, ww, wh = self._window(cam, src)
        s = ww / W
        a = math.radians(cam.rot)
        ca, sa = math.cos(a) * s, math.sin(a) * s
        # output (x, y) -> source: centre-relative rotation + scale
        c = cx - ca * W / 2 + sa * H / 2
        f = cy - sa * W / 2 - ca * H / 2
        return src.transform((W, H), Image.AFFINE, (ca, -sa, c, sa, ca, f), resample=Image.BICUBIC)

    def frame(self, t: float) -> Image.Image:
        src = self._load()
        sh = self.shot
        if sh.move == "parallax":
            img = self._parallax(src, t)
        else:
            img = self._affine(src, camera(sh.move, t, sh.focal, sh.direction))
        if sh.mark:
            img = img.copy()
            img.paste(self._mark_img(), (12, 12), self._mark_img())
        return img

    def _parallax(self, src: Image.Image, t: float) -> Image.Image:
        """Background: the panel softened, slow move. Foreground: a feathered region around the focal point, moving
        faster and scaling more — the gap reads as depth."""
        fx, fy = self.shot.focal
        if self._fg is None:
            self._fg = src
            m = Image.new("L", src.size, 0)
            rx, ry = src.width * 0.30, src.height * 0.38
            cx, cy = fx * src.width, fy * src.height
            ImageDraw.Draw(m).ellipse([cx - rx, cy - ry, cx + rx, cy + ry], fill=255)
            self._mask = m.filter(ImageFilter.GaussianBlur(min(src.size) * 0.06))
            self._bg = src.filter(ImageFilter.GaussianBlur(max(1, min(src.size) // 400)))
        e = ease(t)
        d = self.shot.direction
        bg = self._affine(self._bg, Cam(fx - 0.02 * d + 0.04 * d * e, fy, 1.06 + 0.04 * e))
        fg_cam = Cam(fx + 0.05 * d - 0.10 * d * e, fy, 1.06 + 0.14 * e)
        fg = self._affine(self._fg, fg_cam)
        mask = self._affine(self._mask.convert("RGB"), fg_cam).convert("L")
        return Image.composite(fg, bg, mask)

    def _mark_img(self) -> Image.Image:
        if self._mark is None:
            from . import textrender as TR

            size = max(12, self.size[1] // 22)
            w = int(TR.text_width(self.shot.mark, size, TR.FONT_URL)) + size
            im = Image.new("RGBA", (w, int(size * 1.6)), (20, 12, 6, 170))
            TR.draw_text(im, self.shot.mark, (w / 2, size * 1.15), size, (242, 196, 90, 255), TR.FONT_URL, anchor="ms")
            self._mark = im
        return self._mark


def render_clip(shot: Shot, out: Path, size: tuple[int, int] = (1920, 1080), fps: int = FF.FPS, quality: str = "full",
                progress: Callable[[float], None] | None = None) -> Path:
    from concurrent.futures import ThreadPoolExecutor

    r = ShotRenderer(shot, size)
    r.frame(0.0)  # load (and build the parallax layers) before the threads start
    n = max(1, round(shot.duration * fps))
    with FF.FrameWriter(out, size, fps, quality) as w, ThreadPoolExecutor(FF.workers()) as ex:
        for i, img in enumerate(ex.map(lambda k: r.frame(k / max(1, n - 1)), range(n))):
            w.write(img)
            if progress and i % 12 == 0:
                progress(i / n)
    return out
