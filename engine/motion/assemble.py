"""Assemble a moment film: exactly 30 s at 24 fps (720 frames).

Timeline: a 1.5 s title card on the parchment → the shots (Ken Burns from panels, or Seedance takes) → a 2 s end card
"cycleofdharma.world/v/{code}", every join a 12-frame crossfade. Shot durations are scaled so the whole is exactly
30 s. Burned captions (two-line cues, timed by the narration's words when there are word timings, else by length),
IM Fell English / Tiro Devanagari Hindi on a parchment-tinted box. Audio: narration (from 1.5 s), optional music
ducked -14 dB under the narration, or silence — always an AAC track. H.264 ~3.5 Mbps at 1080p (< 20 MB).
"""

from __future__ import annotations

import collections
import math
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterator

from PIL import Image, ImageDraw, ImageFilter

from . import ffmpeg as FF
from . import kenburns as KB
from . import textrender as TR

TOTAL_S = 30.0
TITLE_S = 1.5
END_S = 2.0
XFADE = 12  # frames
INK = (42, 29, 16)
RUBRIC = (140, 47, 28)
BOX = (239, 228, 201)
MAX_BYTES = 20 * 1024 * 1024
DUCK = 10 ** (-14 / 20)  # -14 dB
MUSIC_GAIN = 0.5


@dataclass
class ShotSpec:
    kind: str = "kenburns"  # kenburns | video
    image: Path | None = None
    video: Path | None = None
    move: str = "push_in"
    duration: float = 6.0
    focal: tuple[float, float] = (0.5, 0.5)
    direction: int = 1


@dataclass
class FilmSpec:
    code: str
    lang: str  # en | hi
    size: tuple[int, int]
    shots: list[ShotSpec]
    title: str
    subtitle: str = ""  # "From The Cycle of Dharma — Book 1, page 9"
    kicker: str = "THE CYCLE OF DHARMA"
    end_url: str = ""
    end_line: str = ""
    narration_text: str = ""
    narration_audio: Path | None = None
    word_times: list[tuple[str, float, float]] | None = None  # relative to the narration's start
    music: Path | None = None
    texture: Path | None = None
    total_s: float = TOTAL_S
    quality: str = "full"
    captions: bool = True


# ---------------------------------------------------------------------------------
# timeline
# ---------------------------------------------------------------------------------


def plan(spec: FilmSpec, fps: int = FF.FPS) -> list[tuple[str, int, int, Any]]:
    """[(kind, start_frame, n_frames, payload)] with 12-frame overlaps, ending exactly at total*fps."""
    total = round(spec.total_s * fps)
    title_n, end_n = round(TITLE_S * fps), round(END_S * fps)
    k = len(spec.shots) + 2
    shots_frames = total + XFADE * (k - 1) - title_n - end_n
    want = [max(0.5, s.duration) for s in spec.shots] or [1.0]
    scale = shots_frames / (sum(want) * fps)
    lens = [max(XFADE * 2 + 1, round(w * fps * scale)) for w in want]
    lens[-1] += shots_frames - sum(lens)
    out = [("title", 0, title_n, None)]
    pos = title_n - XFADE
    for s, n in zip(spec.shots, lens):
        out.append(("shot", pos, n, s))
        pos += n - XFADE
    out.append(("end", pos, end_n, None))
    assert pos + end_n == total, (pos, end_n, total)
    return out


def shot_seconds(spec: FilmSpec, fps: int = FF.FPS) -> list[float]:
    return [n / fps for kind, _, n, _ in plan(spec, fps) if kind == "shot"]


# ---------------------------------------------------------------------------------
# cards
# ---------------------------------------------------------------------------------


def paper(size: tuple[int, int], texture: Path | None) -> Image.Image:
    W, H = size
    if texture and Path(texture).exists():
        tex = Image.open(texture).convert("RGB")
        k = max(W / tex.width, H / tex.height)
        tex = tex.resize((math.ceil(tex.width * k), math.ceil(tex.height * k)), Image.LANCZOS)
        l, t = (tex.width - W) // 2, (tex.height - H) // 2
        img = tex.crop((l, t, l + W, t + H))
    else:
        img = Image.new("RGB", size, BOX)
    # a soft vignette, like the page's burnt edge
    v = Image.new("L", size, 0)
    ImageDraw.Draw(v).rectangle([0, 0, W, H], outline=255, width=max(2, min(W, H) // 14))
    v = v.filter(ImageFilter.GaussianBlur(min(W, H) // 12))
    dark = Image.new("RGB", size, (70, 46, 22))
    return Image.composite(dark, img, v.point(lambda x: int(x * 0.55)))


def _rule(img: Image.Image, cx: float, y: float, w: float, colour: tuple[int, int, int], t: float) -> None:
    d = ImageDraw.Draw(img)
    d.line([cx - w / 2, y, cx - t * 3, y], fill=colour, width=max(1, round(t)))
    d.line([cx + t * 3, y, cx + w / 2, y], fill=colour, width=max(1, round(t)))
    r = t * 2.2
    d.polygon([(cx, y - r), (cx + r, y), (cx, y + r), (cx - r, y)], fill=colour)


def title_card(spec: FilmSpec) -> Image.Image:
    W, H = spec.size
    img = paper(spec.size, spec.texture)
    u = min(W, H) / 1080
    portrait = H > W
    tsize = (92 if not portrait else 84) * u * (1.05 if spec.lang == "hi" else 1)
    lines = TR.wrap(spec.title, tsize, W * 0.82)
    lh = tsize * 1.3
    block = len(lines) * lh
    y0 = H / 2 - block / 2 + tsize * 0.8
    if spec.kicker:
        TR.draw_text(img, spec.kicker, (W / 2, y0 - tsize * 1.5), 30 * u, RUBRIC, TR.FONT_EN, anchor="ms")
        _rule(img, W / 2, y0 - tsize * 1.15, min(W * 0.5, 520 * u), RUBRIC, 2 * u)
    for i, ln in enumerate(lines):
        TR.draw_text(img, ln, (W / 2, y0 + i * lh), tsize, INK, None, anchor="ms")
    if spec.subtitle:
        yb = y0 + (len(lines) - 1) * lh + tsize * 0.95
        _rule(img, W / 2, yb, min(W * 0.5, 520 * u), RUBRIC, 2 * u)
        TR.draw_text(img, spec.subtitle, (W / 2, yb + 56 * u), 34 * u, INK, None, anchor="ms")
    return img


def end_card(spec: FilmSpec) -> Image.Image:
    W, H = spec.size
    img = paper(spec.size, spec.texture)
    u = min(W, H) / 1080
    usize = (64 if W > H else 58) * u
    while TR.text_width(spec.end_url, usize, TR.FONT_URL) > W * 0.88 and usize > 10:
        usize *= 0.94
    cy = H / 2
    if spec.end_line:
        TR.draw_text(img, spec.end_line, (W / 2, cy - usize * 1.25), 36 * u, RUBRIC, None, anchor="ms")
    _rule(img, W / 2, cy - usize * 0.85, min(W * 0.5, 520 * u), RUBRIC, 2 * u)
    TR.draw_text(img, spec.end_url, (W / 2, cy + usize * 0.35), usize, INK, TR.FONT_URL, anchor="ms")
    _rule(img, W / 2, cy + usize * 1.05, min(W * 0.5, 520 * u), RUBRIC, 2 * u)
    TR.draw_text(img, "The Cycle of Dharma", (W / 2, cy + usize * 1.05 + 62 * u), 30 * u, INK, TR.FONT_EN, anchor="ms")
    return img


# ---------------------------------------------------------------------------------
# captions
# ---------------------------------------------------------------------------------


@dataclass
class Cue:
    start: float
    end: float
    lines: list[str]
    img: Image.Image | None = field(default=None, repr=False)


def caption_size(spec: FilmSpec) -> float:
    W, H = spec.size
    u = min(W, H) / 1080
    return (46 if spec.lang == "hi" else 44) * u * (1.0 if W > H else 1.08)


def cues(spec: FilmSpec) -> list[Cue]:
    text = " ".join((spec.narration_text or "").split())
    if not text or not spec.captions:
        return []
    W, _H = spec.size
    size = caption_size(spec)
    maxw = W * (0.80 if W > _H else 0.84)
    lines = TR.wrap(text, size, maxw)
    groups = [lines[i:i + 2] for i in range(0, len(lines), 2)]
    t0, t1 = TITLE_S + 0.25, spec.total_s - END_S - 0.25
    out: list[Cue] = []
    if spec.word_times:
        k = 0
        for g in groups:
            n = len(" ".join(g).split())
            seg = spec.word_times[k:k + n] or spec.word_times[-1:]
            k += n
            out.append(Cue(TITLE_S + seg[0][1], TITLE_S + seg[-1][2] + 0.25, g))
        for a, b in zip(out, out[1:]):
            a.end = min(max(a.end, b.start - 0.05), b.start)
    else:
        lens = [max(1, len(" ".join(g))) for g in groups]
        tot = sum(lens)
        t = t0
        for g, n in zip(groups, lens):
            d = (t1 - t0) * n / tot
            out.append(Cue(t, t + d, g))
            t += d
    for c in out:
        c.end = min(c.end, spec.total_s - END_S)
    return [c for c in out if c.end > c.start]


def cue_image(spec: FilmSpec, cue: Cue) -> Image.Image:
    size = caption_size(spec)
    padx, pady = size * 0.7, size * 0.42
    lh = size * (1.45 if spec.lang == "hi" else 1.32)
    w = max(TR.text_width(ln, size) for ln in cue.lines) + 2 * padx
    h = lh * len(cue.lines) + 2 * pady - (lh - size * 1.15)
    img = Image.new("RGBA", (math.ceil(w), math.ceil(h)), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    r = size * 0.35
    d.rounded_rectangle([0, 0, img.width - 1, img.height - 1], radius=r, fill=(*BOX, 222), outline=(*INK, 150), width=max(1, round(size / 22)))
    for i, ln in enumerate(cue.lines):
        TR.draw_text(img, ln, (img.width / 2, pady + size * (1.0 if spec.lang == "hi" else 0.95) + i * lh), size, (*INK, 255), None, anchor="ms")
    return img


# ---------------------------------------------------------------------------------
# audio
# ---------------------------------------------------------------------------------


def audio_graph(spec: FilmSpec, narr_dur: float) -> tuple[list[str], str]:
    """(extra ffmpeg inputs, filter_complex producing [aout]); input 0 is the frame pipe."""
    T = spec.total_s
    inputs: list[str] = []
    chains: list[str] = []
    mix: list[str] = []
    idx = 1
    if spec.narration_audio:
        inputs += ["-i", str(spec.narration_audio)]
        avail = T - TITLE_S - END_S - 0.3
        tempo = min(1.25, narr_dur / avail) if narr_dur > avail else 1.0
        tf = f",atempo={tempo:.4f}" if tempo > 1.0 else ""
        chains.append(f"[{idx}:a]aformat=sample_rates=48000:channel_layouts=stereo{tf},adelay={int(TITLE_S * 1000)}|{int(TITLE_S * 1000)},apad[narr]")
        mix.append("[narr]")
        idx += 1
    if spec.music:
        inputs += ["-stream_loop", "-1", "-i", str(spec.music)]
        if spec.narration_audio:
            ns, ne = TITLE_S, TITLE_S + narr_dur
            vol = f"volume='{MUSIC_GAIN}*if(between(t,{ns - 0.3:.2f},{ne + 0.3:.2f}),{DUCK:.4f},1)':eval=frame"
        else:
            vol = f"volume={MUSIC_GAIN}"
        chains.append(f"[{idx}:a]aformat=sample_rates=48000:channel_layouts=stereo,atrim=0:{T},{vol},afade=t=in:d=1,afade=t=out:st={T - 2}:d=2[mus]")
        mix.append("[mus]")
        idx += 1
    if not mix:
        chains.append(f"anullsrc=r=48000:cl=stereo,atrim=0:{T}[aout]")
        return inputs, ";".join(chains)
    if len(mix) == 1:
        chains.append(f"{mix[0]}atrim=0:{T},apad=whole_dur={T}[aout]")
    else:
        chains.append(f"{''.join(mix)}amix=inputs={len(mix)}:duration=longest:normalize=0,atrim=0:{T},apad=whole_dur={T}[aout]")
    return inputs, ";".join(chains)


# ---------------------------------------------------------------------------------
# render
# ---------------------------------------------------------------------------------


class _VideoSource:
    """Sequential frames of a take, retimed to n frames (nearest frame; the last repeats if short)."""

    def __init__(self, path: Path, size: tuple[int, int], n: int) -> None:
        info = FF.probe(path)
        dur = info["duration"] or n / FF.FPS
        self.it: Iterator[Image.Image] = FF.read_frames(path, size, FF.FPS)
        self.src_n = max(1, round(dur * FF.FPS))
        self.n = n
        self.cur_idx = -1
        self.cur: Image.Image | None = None
        self.size = size

    def get(self, j: int) -> Image.Image:
        want = min(self.src_n - 1, int(j * self.src_n / self.n))
        while self.cur_idx < want:
            try:
                self.cur = next(self.it)
                self.cur_idx += 1
            except StopIteration:
                break
        return self.cur if self.cur is not None else Image.new("RGB", self.size, BOX)


def assemble(spec: FilmSpec, out: Path, poster: Path | None = None, progress: Callable[[float], None] | None = None,
             narr_dur: float = 0.0) -> dict[str, Any]:
    fps = FF.FPS
    segs = plan(spec, fps)
    total = round(spec.total_s * fps)
    title = title_card(spec)
    endc = end_card(spec)
    renderers: dict[int, Any] = {}
    for i, (kind, _s, n, payload) in enumerate(segs):
        if kind != "shot":
            continue
        if payload.kind == "video" and payload.video:
            renderers[i] = _VideoSource(Path(payload.video), spec.size, n)
        else:
            r = KB.ShotRenderer(KB.Shot(Path(payload.image), payload.move, n / fps, tuple(payload.focal), payload.direction), spec.size)
            r.frame(0.0)
            renderers[i] = r
    cl = cues(spec)
    for c in cl:
        c.img = cue_image(spec, c)
    W, H = spec.size
    cap_bottom = H * (0.06 if W > H else 0.15)

    def card(img: Image.Image, j: int, n: int, grow: bool) -> Image.Image:
        z = 1.0 + 0.025 * (j / max(1, n - 1) if grow else 1 - j / max(1, n - 1))
        if abs(z - 1) < 1e-3:
            return img
        w2, h2 = W / z, H / z
        return img.transform(spec.size, Image.EXTENT, ((W - w2) / 2, (H - h2) / 2, (W + w2) / 2, (H + h2) / 2), Image.BICUBIC)

    def layer(si: int, j: int, vid_frame: Image.Image | None) -> Image.Image:
        kind, _s, n, payload = segs[si]
        if kind == "title":
            return card(title, j, n, True)
        if kind == "end":
            return card(endc, j, n, False)
        if vid_frame is not None:
            return vid_frame
        return renderers[si].frame(j / max(1, n - 1))

    def compose(i: int, parts: list[tuple[int, int, Image.Image | None]], with_caption: bool = True) -> Image.Image:
        imgs = [layer(si, j, vf) for si, j, vf in parts]
        if len(imgs) == 1:
            frame = imgs[0].convert("RGB")
        else:
            si2, j2, _ = parts[1]
            a = KB.ease((j2 + 1) / (XFADE + 1))
            frame = Image.blend(imgs[0].convert("RGB"), imgs[1].convert("RGB"), a)
        if with_caption and cl:
            t = i / fps
            for c in cl:
                if c.start <= t < c.end:
                    fade = min(1.0, (t - c.start) / 0.25, (c.end - t) / 0.25)
                    ci = c.img
                    if fade < 1:
                        ci = ci.copy()
                        ci.putalpha(ci.getchannel("A").point(lambda v, f=fade: int(v * f)))
                    frame = frame.convert("RGBA")
                    frame.alpha_composite(ci, (round((W - ci.width) / 2), round(H - cap_bottom - ci.height)))
                    frame = frame.convert("RGB")
                    break
        return frame

    def parts_at(i: int) -> list[tuple[int, int, Image.Image | None]]:
        out = []
        for si, (kind, s, n, payload) in enumerate(segs):
            if s <= i < s + n:
                vf = renderers[si].get(i - s) if isinstance(renderers.get(si), _VideoSource) else None
                out.append((si, i - s, vf))
        return out

    inputs, graph = audio_graph(spec, narr_dur)
    poster_frame = None
    first_shot = next((k for k, sg in enumerate(segs) if sg[0] == "shot"), None)
    if first_shot is not None:
        poster_frame = segs[first_shot][1] + segs[first_shot][2] // 2
    out.parent.mkdir(parents=True, exist_ok=True)
    with FF.FrameWriter(out, spec.size, fps, spec.quality, extra_inputs=inputs, audio_filter=graph, duration=spec.total_s) as w, \
            ThreadPoolExecutor(FF.workers()) as ex:
        q: collections.deque = collections.deque()
        for i in range(total):
            parts = parts_at(i)
            q.append(ex.submit(compose, i, parts))
            if poster is not None and i == poster_frame:
                img = compose(i, parts, with_caption=False)
                poster.parent.mkdir(parents=True, exist_ok=True)
                img.save(poster, "JPEG", quality=88, optimize=True, progressive=True)
            while len(q) > FF.workers() * 3:
                w.write(q.popleft().result())
            if progress and i % 24 == 0:
                progress(i / total)
        while q:
            w.write(q.popleft().result())
    info = FF.probe(out)
    if info["bytes"] > MAX_BYTES:  # safety net: transcode down to fit the 20 MB budget
        tmp = out.with_suffix(".big.mp4")
        out.rename(tmp)
        kbps = int((MAX_BYTES * 8 / spec.total_s) / 1000 * 0.85) - 128
        FF.run(["-i", str(tmp), "-c:v", "libx264", "-b:v", f"{kbps}k", "-maxrate", f"{kbps}k", "-bufsize", f"{kbps * 2}k", "-pix_fmt", "yuv420p", "-c:a", "copy", "-movflags", "+faststart", str(out)])
        tmp.unlink()
        info = FF.probe(out)
    if progress:
        progress(1.0)
    info["frames"] = total
    info["cues"] = [{"start": round(c.start, 2), "end": round(c.end, 2), "lines": c.lines} for c in cl]
    return info
