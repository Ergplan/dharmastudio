"""PDF post-processing: re-encode Chromium's lossless images as JPEG while keeping soft masks."""

from __future__ import annotations

import io
from pathlib import Path


def compress_pdf(src: Path, dst: Path | None = None, quality: int = 92) -> Path:
    """Re-encode Chromium's lossless 300-ppi image objects as JPEG (DCT) at the same resolution, keeping soft masks.
    Visually lossless for print; a 10-page chapter goes from ~63 MB to ~10 MB."""
    import pikepdf
    from PIL import Image  # noqa: F401  (pikepdf.PdfImage.as_pil_image needs Pillow)

    dst = dst or src
    tmp = dst.with_suffix(".tmp.pdf")
    with pikepdf.open(src) as pdf:
        for page in pdf.pages:
            imgs = page.get_images() if hasattr(page, "get_images") else page.images
            for _name, raw in list(imgs.items()):
                try:
                    pim = pikepdf.PdfImage(raw)
                    if pim.width * pim.height < 200_000 or pim.colorspace not in ("/DeviceRGB", "/DeviceGray"):
                        continue
                    if str(raw.get("/Filter", "")) == "/DCTDecode":
                        continue
                    im = pim.as_pil_image()
                    buf = io.BytesIO()
                    im.convert("RGB" if pim.colorspace == "/DeviceRGB" else "L").save(buf, "JPEG", quality=quality, subsampling=0, optimize=True)
                    smask = raw.get("/SMask")
                    raw.write(buf.getvalue(), filter=pikepdf.Name("/DCTDecode"))
                    raw.ColorSpace = pikepdf.Name("/DeviceRGB" if pim.colorspace == "/DeviceRGB" else "/DeviceGray")
                    raw.BitsPerComponent = 8
                    if smask is not None:
                        raw.SMask = smask
                except Exception:  # noqa: BLE001
                    continue
        pdf.save(tmp, compress_streams=True, object_stream_mode=pikepdf.ObjectStreamMode.generate)
    tmp.replace(dst)
    return dst


def pdf_page_count(path: Path) -> int:
    import pikepdf

    with pikepdf.open(path) as pdf:
        return len(pdf.pages)
