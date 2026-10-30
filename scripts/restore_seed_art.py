"""Unpack the Chapter 1 seed art (engine/seed_art/*.jpg, committed) into data/ch1_candidates/*.png for the seed."""
from pathlib import Path

from PIL import Image

root = Path(__file__).resolve().parent.parent
src, dst = root / "engine" / "seed_art", root / "data" / "ch1_candidates"
dst.mkdir(parents=True, exist_ok=True)
n = 0
for f in sorted(src.glob("*.jpg")):
    out = dst / f"{f.stem}.png"
    if not out.exists():
        Image.open(f).save(out)
        n += 1
print(f"seed art: {n} restored, {len(list(dst.glob('*.png')))} present")
