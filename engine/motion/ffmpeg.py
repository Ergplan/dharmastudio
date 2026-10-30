"""The bundled ffmpeg (imageio-ffmpeg's static binary — works inside the packaged Mac app), probing, and raw-frame pipes."""

from __future__ import annotations

import re
import shutil
import subprocess
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterator

from PIL import Image

FPS = 24


def workers() -> int:
    """Frame threads (Pillow releases the GIL in resampling)."""
    import os

    return max(2, min(8, (os.cpu_count() or 2)))


@lru_cache(maxsize=1)
def exe() -> str:
    try:
        import imageio_ffmpeg

        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:  # noqa: BLE001
        found = shutil.which("ffmpeg")
        if found:
            return found
        raise RuntimeError("ffmpeg is not available (pip install imageio-ffmpeg)")


def health() -> dict[str, Any]:
    try:
        e = exe()
        out = subprocess.run([e, "-hide_banner", "-version"], capture_output=True, text=True, timeout=20).stdout
        enc = subprocess.run([e, "-hide_banner", "-encoders"], capture_output=True, text=True, timeout=20).stdout
        return {"ok": "libx264" in enc and " aac " in enc, "path": e, "version": (out.splitlines() or [""])[0], "libx264": "libx264" in enc}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": str(exc)}


def run(args: list[str], timeout: int = 1800) -> subprocess.CompletedProcess:
    p = subprocess.run([exe(), "-hide_banner", "-y", *args], capture_output=True, timeout=timeout)
    if p.returncode != 0:
        raise RuntimeError("ffmpeg failed: " + p.stderr.decode("utf-8", "replace")[-1500:])
    return p


def probe(path: Path | str) -> dict[str, Any]:
    """Duration, size, fps and streams, parsed from `ffmpeg -i` (no ffprobe in the bundle)."""
    p = subprocess.run([exe(), "-hide_banner", "-i", str(path)], capture_output=True, text=True, timeout=60)
    err = p.stderr
    out: dict[str, Any] = {"duration": 0.0, "width": 0, "height": 0, "fps": 0.0, "has_audio": False, "has_video": False, "video_codec": None, "audio_codec": None,
                           "bytes": Path(path).stat().st_size if Path(path).exists() else 0}
    m = re.search(r"Duration: (\d+):(\d+):([\d.]+)", err)
    if m:
        out["duration"] = int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3))
    m = re.search(r"Stream #\S+.*?Video: (\w+).*?, (\d{2,5})x(\d{2,5})", err)
    if m:
        out.update(has_video=True, video_codec=m.group(1), width=int(m.group(2)), height=int(m.group(3)))
    m = re.search(r"([\d.]+) fps", err)
    if m:
        out["fps"] = float(m.group(1))
    m = re.search(r"Stream #\S+.*?Audio: (\w+)", err)
    if m:
        out.update(has_audio=True, audio_codec=m.group(1))
    m = re.search(r"bitrate: (\d+) kb/s", err)
    if m:
        out["kbps"] = int(m.group(1))
    return out


def count_frames(path: Path | str) -> int:
    p = subprocess.run([exe(), "-hide_banner", "-i", str(path), "-map", "0:v:0", "-f", "null", "-"], capture_output=True, text=True, timeout=600)
    m = re.findall(r"frame=\s*(\d+)", p.stderr)
    return int(m[-1]) if m else 0


def video_args(w: int, h: int, quality: str = "full") -> list[str]:
    """H.264 settings: ~3.5 Mbps at 1080p (each 30 s film well under 20 MB), CRF for small test renders."""
    px = w * h
    if quality == "draft" or px < 640 * 360:
        return ["-c:v", "libx264", "-preset", "veryfast", "-crf", "30", "-pix_fmt", "yuv420p"]
    kbps = int(3500 * px / (1920 * 1080)) if px < 1920 * 1080 else 3500
    kbps = max(900, kbps)
    return ["-c:v", "libx264", "-preset", "medium", "-profile:v", "high", "-pix_fmt", "yuv420p", "-b:v", f"{kbps}k",
            "-maxrate", f"{int(kbps * 1.2)}k", "-bufsize", f"{kbps * 2}k", "-g", "48"]


class FrameWriter:
    """Pipe RGB frames to ffmpeg. extra_inputs/filters let the caller mux audio in the same pass."""

    def __init__(self, out: Path, size: tuple[int, int], fps: int = FPS, quality: str = "full", extra_inputs: list[str] | None = None,
                 audio_filter: str | None = None, audio_map: str | None = None, duration: float | None = None, video_args_override: list[str] | None = None) -> None:
        w, h = size
        self.size = size
        args = [exe(), "-hide_banner", "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{w}x{h}", "-r", str(fps), "-i", "pipe:0"]
        args += extra_inputs or []
        if audio_filter:
            args += ["-filter_complex", audio_filter, "-map", "0:v", "-map", audio_map or "[aout]", "-c:a", "aac", "-b:a", "128k", "-ar", "48000"]
        else:
            args += ["-map", "0:v", "-an"]
        args += video_args_override or video_args(w, h, quality)
        if duration:
            args += ["-t", f"{duration:.3f}"]
        args += ["-r", str(fps), "-movflags", "+faststart", str(out)]
        self.proc = subprocess.Popen(args, stdin=subprocess.PIPE, stderr=subprocess.PIPE)
        self.n = 0

    def write(self, img: Image.Image) -> None:
        if img.size != self.size:
            img = img.resize(self.size, Image.BICUBIC)
        assert self.proc.stdin is not None
        self.proc.stdin.write(img.convert("RGB").tobytes())
        self.n += 1

    def close(self) -> None:
        assert self.proc.stdin is not None
        self.proc.stdin.close()
        err = self.proc.stderr.read().decode("utf-8", "replace") if self.proc.stderr else ""
        rc = self.proc.wait()
        if rc != 0:
            raise RuntimeError("ffmpeg encode failed: " + err[-1500:])

    def __enter__(self) -> "FrameWriter":
        return self

    def __exit__(self, et, ev, tb) -> None:  # noqa: ANN001
        if et is None:
            self.close()
        else:
            try:
                self.proc.kill()
            except Exception:  # noqa: BLE001
                pass


def read_frames(path: Path | str, size: tuple[int, int], fps: int = FPS) -> Iterator[Image.Image]:
    """Decode a video to RGB frames at `size` (cover-cropped) and `fps`."""
    w, h = size
    vf = f"fps={fps},scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h}"
    p = subprocess.Popen([exe(), "-hide_banner", "-loglevel", "error", "-i", str(path), "-vf", vf, "-f", "rawvideo", "-pix_fmt", "rgb24", "pipe:1"],
                         stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    n = w * h * 3
    assert p.stdout is not None
    try:
        while True:
            buf = p.stdout.read(n)
            if len(buf) < n:
                break
            yield Image.frombytes("RGB", (w, h), buf)
    finally:
        p.stdout.close()
        p.wait()
