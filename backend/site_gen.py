"""SITE — cycleofdharma.world.

The site's CODE is the Next.js app in web/ (Vercel deploys it from git). Its CONTENT is not in git: the studio publishes
`manifest.json` (links + published moments; schema web/lib/manifest.schema.json) and the media (MP4s, posters) to
Vercel Blob with stable pathnames (moments/{code}/en-16x9.mp4 …, unchanged files skipped by sha1), then calls the
site's POST /api/revalidate (REVALIDATE_SECRET) so pages refresh within seconds.

The studio also renders the same manifest into a static preview at /site-preview/ (data/site/) — watch pages, landing,
coming-soon pages, 404, robots, sitemap — and can zip it as an offline backup.
"""

from __future__ import annotations

import hashlib
import html
import json
import os
import secrets
import shutil
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from engine.comic import manuscript as MS

from . import db, links
from .models import Page, Project, Volume
from .motion_models import Link, Moment, SitePublish

ROOT = Path(__file__).resolve().parent.parent
FONT_LIB = ROOT / "engine" / "comic" / "fonts" / "library"
TEXTURE = ROOT / "engine" / "textures" / "page_warm.jpg"
SITE_FONTS = {"imfell": "IMFeENrm28P.ttf", "imfell-italic": "IMFeENit28P.ttf", "tiro": "TiroDevanagariHindi-Regular.ttf", "spectral": "Spectral-Regular.ttf"}
BOOK_HI = "द साइकिल ऑफ़ धर्म"
VOLUME_TITLES_HI = {1: "पहली पुस्तक", 2: "दूसरी पुस्तक", 3: "तीसरी पुस्तक"}
BLOB_API = "https://blob.vercel-storage.com"
MEDIA_KEYS = ("en_16x9", "en_9x16", "hi_16x9", "hi_9x16", "poster", "poster_9x16")


def site_dir() -> Path:
    d = db.DATA_DIR / "site"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _setting(name: str) -> str | None:
    from engine.settings import settings

    return getattr(settings, name.lower(), None) or os.environ.get(name.upper()) or None


def publishing(session: Session) -> dict[str, Any]:
    proj = session.scalar(select(Project))
    pub = dict(((proj.settings or {}).get("publishing") or {}) if proj else {})
    return {"site_url": (pub.get("site_url") or _setting("SITE_URL") or links.DEFAULT_SITE).rstrip("/"),
            "media_base": (pub.get("media_base") or "").rstrip("/") or None,
            "blob_token": bool(_setting("BLOB_READ_WRITE_TOKEN")), "revalidate_secret": bool(_setting("REVALIDATE_SECRET")),
            "manifest_url": pub.get("manifest_url"), "last": last_result(session)}


def last_result(session: Session) -> dict[str, Any] | None:
    r = session.scalar(select(SitePublish).where(SitePublish.kind == "publish").order_by(SitePublish.id.desc()))
    return {"id": r.id, "ok": r.ok, "at": r.created_at.isoformat() if r.created_at else None, **(r.result or {})} if r else None


def set_publishing(session: Session, site_url: str | None = None, media_base: str | None = None, manifest_url: str | None = None) -> None:
    proj = session.scalar(select(Project))
    st = dict(proj.settings or {})
    pub = dict(st.get("publishing") or {})
    if site_url is not None:
        pub["site_url"] = site_url.rstrip("/")
    if media_base is not None:
        pub["media_base"] = media_base.rstrip("/")
    if manifest_url is not None:
        pub["manifest_url"] = manifest_url
    st["publishing"] = pub
    proj.settings = st
    session.flush()


def new_secret() -> str:
    return secrets.token_urlsafe(32)


# ---------------------------------------------------------------------------------
# manifest
# ---------------------------------------------------------------------------------


def page_verse(session: Session, page: Page) -> dict[str, Any] | None:
    """The page's Sanskrit verse from its manuscript layer (exact Devanagari from engine/shlokas.yaml)."""
    vid = None
    stored = page.manuscript or {}
    for v in stored.get("verses") or []:
        vid = v.get("id")
        break
    if vid is None:
        try:
            from . import render

            st = render.manuscript_state(session, page)
            vid = next((v.get("id") for v in st.get("verses") or []), None)
        except Exception:  # noqa: BLE001
            vid = None
    v = MS.verse(vid) if vid else None
    if not v:
        return None
    return {"id": v["id"], "source": v.get("source", ""), "lines": list(v.get("lines") or []), "iast": v.get("iast", ""), "meaning": v.get("meaning", "")}


def published_moments(session: Session) -> list[tuple[Moment, Link, Page]]:
    out = []
    for m in session.scalars(select(Moment).where(Moment.status == "published").order_by(Moment.id)).all():
        link = session.get(Link, m.link_id) if m.link_id else None
        page = session.get(Page, m.page_id)
        if link and page and all((m.outputs or {}).get(k) for k in MEDIA_KEYS[:5]):
            out.append((m, link, page))
    return out


def media_pathname(code: str, key: str) -> str:
    return f"moments/{code}/{key.replace('_', '-')}{'.jpg' if key.startswith('poster') else '.mp4'}"


def build_manifest(session: Session, media_url: Any, site_url: str | None = None) -> dict[str, Any]:
    """media_url(code, key, rel_path) -> the public URL of that file."""
    pub = publishing(session)
    site = (site_url or pub["site_url"]).rstrip("/")
    proj = session.scalar(select(Project))
    vols = session.scalars(select(Volume).order_by(Volume.number)).all()
    moms = published_moments(session)
    count: dict[int, int] = {}
    moments = []
    for m, link, page in moms:
        vol = page.chapter.volume.number
        count[vol] = count.get(vol, 0) + 1
        media = {k: media_url(link.code, k, m.outputs[k]) for k in MEDIA_KEYS if (m.outputs or {}).get(k)}
        dur = ((m.render_meta or {}).get("variants") or {}).get("en_16x9", {}).get("duration") or 30.0
        moments.append({
            "code": link.code, "title_en": m.title_en or f"Page {page.number}", "title_hi": m.title_hi or "", "volume": vol, "chapter": page.chapter.number,
            "chapter_title": page.chapter.title or "", "page": page.number, "caption_en": m.narration_en or "", "caption_hi": m.narration_hi or "",
            "verse": page_verse(session, page), "media": media, "duration_s": round(float(dur), 2),
            "published_at": m.published_at.isoformat() if m.published_at else None,
        })
    live = {x["code"] for x in moments}
    link_rows = []
    for link in session.scalars(select(Link).order_by(Link.code)).all():
        r = links.resolved(session, link)
        item: dict[str, Any] = {"code": link.code, "kind": r["kind"], "destination": None, "moment": None, "chapter": None}
        if r["kind"] == "redirect":
            item["destination"] = r["destination"]
        elif r["kind"] == "moment":
            item["moment"] = link.code if link.code in live else None
            if item["moment"] is None:
                item["kind"] = "coming_soon"
        elif r["kind"] == "chapter":
            ch = links.target_row(session, link)
            codes = [x["code"] for x in moments if ch is not None and x["volume"] == ch.volume.number and x["chapter"] == ch.number]
            item["chapter"] = {"volume": ch.volume.number, "number": ch.number, "title": ch.title or ""} if ch is not None else None
            item["moments"] = codes
        link_rows.append(item)
    return {
        "version": 1, "generated_at": datetime.now(timezone.utc).isoformat(), "site_url": site, "media_base": pub["media_base"],
        "book": {"title": (proj.title if proj else None) or "The Cycle of Dharma", "title_hi": BOOK_HI, "author": (proj.author if proj else "") or "Rachit Agarwal",
                 "books": [{"number": v.number, "title": v.title or f"Book {v.number}", "title_hi": VOLUME_TITLES_HI.get(v.number, ""), "moments": count.get(v.number, 0)} for v in vols]},
        "links": link_rows, "moments": moments,
    }


def schema() -> dict[str, Any]:
    return json.loads((ROOT / "web" / "lib" / "manifest.schema.json").read_text())


def validate_manifest(man: dict[str, Any]) -> None:
    try:
        import jsonschema
    except ImportError:  # dev dependency; the shape is still produced by build_manifest
        return
    jsonschema.validate(man, schema())


# ---------------------------------------------------------------------------------
# static preview (same manifest -> HTML)
# ---------------------------------------------------------------------------------


def _e(s: Any) -> str:
    return html.escape(str(s or ""), quote=True)


def ensure_fonts(dst: Path) -> dict[str, str]:
    """woff2 copies of the site's faces (fontTools + brotli), else the TTFs."""
    dst.mkdir(parents=True, exist_ok=True)
    out = {}
    for key, fn in SITE_FONTS.items():
        src = FONT_LIB / fn
        woff2 = dst / (Path(fn).stem + ".woff2")
        if not woff2.exists():
            try:
                from fontTools.ttLib import TTFont

                f = TTFont(str(src))
                f.flavor = "woff2"
                f.save(str(woff2))
            except Exception:  # noqa: BLE001
                woff2 = dst / fn
                shutil.copyfile(src, woff2)
        out[key] = woff2.name
    return out


def ensure_texture(dst: Path) -> str:
    from PIL import Image

    dst.mkdir(parents=True, exist_ok=True)
    p = dst / "parchment.jpg"
    if not p.exists():
        im = Image.open(TEXTURE).convert("RGB")
        im.thumbnail((1024, 1536))
        im.save(p, "JPEG", quality=72, optimize=True, progressive=True)
    return p.name


CSS = """
:root{--ink:#2a1d10;--rubric:#8c2f1c;--paper:#efe4c9;--edge:#5a3a1a}
*{box-sizing:border-box}html{-webkit-text-size-adjust:100%}
body{margin:0;color:var(--ink);background:var(--paper) url(%(base)s/textures/parchment.jpg) center/cover fixed;font:18px/1.6 Spectral,Georgia,serif;min-height:100vh}
body:before{content:"";position:fixed;inset:0;pointer-events:none;box-shadow:inset 0 0 140px rgba(70,46,22,.55)}
a{color:var(--rubric)}
.wrap{max-width:1040px;margin:0 auto;padding:28px 16px 64px}
header.top{display:flex;justify-content:space-between;align-items:center;gap:12px;font-family:'IM Fell',serif}
header.top a.home{color:var(--ink);text-decoration:none;letter-spacing:.14em;text-transform:uppercase;font-size:14px}
.langs{display:flex;border:1px solid rgba(42,29,16,.35);border-radius:999px;overflow:hidden}
.langs button{font:inherit;font-size:15px;background:transparent;border:0;padding:6px 14px;color:var(--ink);cursor:pointer}
.langs button[aria-pressed=true]{background:var(--ink);color:var(--paper)}
h1{font-family:'IM Fell',serif;font-weight:400;font-size:clamp(30px,5vw,52px);line-height:1.15;margin:18px 0 6px}
.hi,[lang=hi]{font-family:'Tiro Devanagari Hindi',serif}
body[data-lang=en] .only-hi,body[data-lang=hi] .only-en{display:none}
.kicker{font-family:'IM Fell',serif;color:var(--rubric);letter-spacing:.16em;text-transform:uppercase;font-size:13px}
.player{position:relative;margin:18px 0 8px;border-radius:6px;overflow:hidden;background:#140d06;box-shadow:0 12px 40px rgba(42,29,16,.35)}
.player video{display:block;width:100%;aspect-ratio:16/9;background:#140d06}
@media (max-width:640px){.player video{aspect-ratio:9/16;max-height:82vh}}
.from{font-style:italic;opacity:.85;margin:4px 0 22px}
.caption{font-size:20px;max-width:46em}
.caption.hi{font-size:21px;line-height:1.75}
.verse{margin:30px 0;padding:18px 20px;border-left:3px solid var(--rubric);background:rgba(239,228,201,.55)}
.verse .lines{font-family:'Tiro Devanagari Hindi',serif;font-size:22px;line-height:1.9;white-space:pre-line}
.verse .meaning{font-style:italic;margin-top:8px}.verse .src{font-size:14px;opacity:.75;margin-top:4px}
.rule{height:1px;background:linear-gradient(90deg,transparent,rgba(42,29,16,.45),transparent);margin:30px 0}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(220px,1fr));gap:18px}
.card{display:block;color:inherit;text-decoration:none;background:rgba(239,228,201,.6);border:1px solid rgba(42,29,16,.18);border-radius:6px;overflow:hidden}
.card img{display:block;width:100%;aspect-ratio:16/9;object-fit:cover}
.card div{padding:10px 12px}.card b{font-family:'IM Fell',serif;font-weight:400;font-size:19px;display:block}
.books{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:14px;margin:18px 0}
.book{padding:16px;border:1px solid rgba(42,29,16,.25);border-radius:6px;background:rgba(239,228,201,.5)}
.book b{font-family:'IM Fell',serif;font-weight:400;font-size:22px}
footer{margin-top:48px;font-size:14px;opacity:.8;text-align:center}
.soon{text-align:center;padding:12vh 0}
"""


def _fonts_css(base: str, files: dict[str, str]) -> str:
    def ff(name: str, key: str, style: str = "normal") -> str:
        fn = files[key]
        fmt = "woff2" if fn.endswith(".woff2") else "truetype"
        return f"@font-face{{font-family:'{name}';src:url({base}/fonts/{fn}) format('{fmt}');font-style:{style};font-display:swap}}"

    return ff("IM Fell", "imfell") + ff("IM Fell", "imfell-italic", "italic") + ff("Tiro Devanagari Hindi", "tiro") + ff("Spectral", "spectral")


def _doc(title: str, body: str, base: str, fonts: dict[str, str], head: str = "", lang: str = "en") -> str:
    return (f"<!doctype html><html lang='{lang}'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'>"
            f"<title>{_e(title)}</title><link rel='icon' href='data:,'><style>{_fonts_css(base, fonts)}{CSS.replace('%(base)s', base)}</style>{head}</head>"
            f"<body data-lang='{lang}'>{body}</body></html>")


LANG_JS = """<script>
(function(){var b=document.body,v=document.querySelector('video'),M=v?JSON.parse(v.dataset.media):null;
function portrait(){return window.matchMedia('(max-width: 640px)').matches}
function pick(){if(!v)return;var k=b.dataset.lang+(portrait()?'_9x16':'_16x9');if(v.dataset.k===k)return;
var t=v.currentTime,p=!v.paused;v.dataset.k=k;v.poster=(portrait()&&M.poster_9x16)?M.poster_9x16:M.poster;v.src=M[k];
if(t){v.addEventListener('loadedmetadata',function f(){v.currentTime=t;v.removeEventListener('loadedmetadata',f)})}if(p)v.play()}
function set(l){b.dataset.lang=l;document.documentElement.lang=l;document.querySelectorAll('.langs button').forEach(function(x){x.setAttribute('aria-pressed',x.dataset.l===l)});
try{localStorage.setItem('cod-lang',l)}catch(e){}pick()}
document.querySelectorAll('.langs button').forEach(function(x){x.onclick=function(){set(x.dataset.l)}});
var s=null;try{s=localStorage.getItem('cod-lang')}catch(e){}var q=new URLSearchParams(location.search).get('lang');
set(q==='hi'||q==='en'?q:(s||((navigator.language||'').startsWith('hi')?'hi':'en')));window.addEventListener('resize',pick)})();
</script>"""


def _langs() -> str:
    return "<div class='langs' role='group' aria-label='Language'><button data-l='en' aria-pressed='true'>EN</button><button data-l='hi' class='hi' aria-pressed='false'>हिंदी</button></div>"


def _top(base: str) -> str:
    return f"<header class='top'><a class='home' href='{base}/'>The Cycle of Dharma</a>{_langs()}</header>"


def watch_html(man: dict[str, Any], mo: dict[str, Any], base: str, fonts: dict[str, str]) -> str:
    site = man["site_url"]
    url = f"{site}/v/{mo['code']}"
    from_en = f"From The Cycle of Dharma — Book {mo['volume']}, page {mo['page']}"
    from_hi = f"{BOOK_HI} से — पुस्तक {mo['volume']}, पृष्ठ {mo['page']}"
    m = mo["media"]
    head = "".join([
        f"<meta name='description' content='{_e(mo['caption_en'][:200])}'>", f"<link rel='canonical' href='{_e(url)}'>",
        "<meta property='og:type' content='video.other'>", f"<meta property='og:title' content='{_e(mo['title_en'])} — The Cycle of Dharma'>",
        f"<meta property='og:description' content='{_e(from_en)}'>", f"<meta property='og:url' content='{_e(url)}'>",
        f"<meta property='og:image' content='{_e(m['poster'])}'>", f"<meta property='og:video' content='{_e(m['en_16x9'])}'>",
        "<meta property='og:video:type' content='video/mp4'><meta property='og:video:width' content='1920'><meta property='og:video:height' content='1080'>",
        "<meta name='twitter:card' content='summary_large_image'>", f"<meta name='twitter:title' content='{_e(mo['title_en'])}'>",
        f"<meta name='twitter:description' content='{_e(from_en)}'>", f"<meta name='twitter:image' content='{_e(m['poster'])}'>",
    ])
    v = mo.get("verse")
    verse = ""
    if v:
        verse = (f"<section class='verse' aria-label='Verse'><div class='lines' lang='sa'>{_e(chr(10).join(v['lines']))}</div>"
                 f"<div class='meaning'>{_e(v['meaning'])}</div><div class='src'>{_e(v.get('source', ''))}</div></section>")
    title_hi = mo.get("title_hi") or mo["title_en"]
    body = (f"<div class='wrap'>{_top(base)}"
            f"<div class='kicker'>Book {mo['volume']} · {_e(mo.get('chapter_title'))}</div>"
            f"<h1 class='only-en'>{_e(mo['title_en'])}</h1><h1 class='only-hi hi' lang='hi'>{_e(title_hi)}</h1>"
            f"<div class='player'><video controls playsinline preload='metadata' poster='{_e(m['poster'])}' src='{_e(m['en_16x9'])}' data-media='{_e(json.dumps(m))}'></video></div>"
            f"<p class='from only-en'>{_e(from_en)}</p><p class='from only-hi hi' lang='hi'>{_e(from_hi)}</p>"
            f"<p class='caption only-en'>{_e(mo['caption_en'])}</p><p class='caption only-hi hi' lang='hi'>{_e(mo['caption_hi'] or mo['caption_en'])}</p>"
            f"{verse}<div class='rule'></div><footer><a href='{base}/'>cycleofdharma.world</a> · {_e(man['book']['author'])}</footer></div>{LANG_JS}")
    return _doc(f"{mo['title_en']} — The Cycle of Dharma", body, base, fonts, head)


def soon_html(code: str, base: str, fonts: dict[str, str]) -> str:
    body = (f"<div class='wrap'>{_top(base)}<div class='soon'><div class='kicker'>cycleofdharma.world/v/{_e(code)}</div>"
            "<h1 class='only-en'>This moment is still being painted</h1><h1 class='only-hi hi' lang='hi'>यह क्षण अभी रचा जा रहा है</h1>"
            "<p class='only-en'>The film for this page is coming soon. Keep the book close — the code you scanned will light up here.</p>"
            "<p class='only-hi hi' lang='hi'>इस पृष्ठ की फ़िल्म जल्द आ रही है। आपने जो कोड स्कैन किया है, वह यहीं जीवंत होगा।</p>"
            f"<p><a href='{base}/'>The Cycle of Dharma</a></p></div></div>{LANG_JS}")
    return _doc("Coming soon — The Cycle of Dharma", body, base, fonts, "<meta name='robots' content='noindex'>")


def chapter_html(man: dict[str, Any], item: dict[str, Any], base: str, fonts: dict[str, str]) -> str:
    ch = item.get("chapter") or {}
    cards = _cards([x for x in man["moments"] if x["code"] in (item.get("moments") or [])], base)
    body = (f"<div class='wrap'>{_top(base)}<div class='kicker'>Book {ch.get('volume', '')} · Chapter {ch.get('number', '')}</div>"
            f"<h1>{_e(ch.get('title'))}</h1><div class='grid'>{cards}</div></div>{LANG_JS}")
    return _doc(f"{ch.get('title', 'Chapter')} — The Cycle of Dharma", body, base, fonts)


def _cards(moments: list[dict[str, Any]], base: str) -> str:
    return "".join(
        f"<a class='card' href='{base}/v/{_e(x['code'])}/'><img loading='lazy' src='{_e(x['media']['poster'])}' alt=''>"
        f"<div><b class='only-en'>{_e(x['title_en'])}</b><b class='only-hi hi' lang='hi'>{_e(x['title_hi'] or x['title_en'])}</b>"
        f"<span>Book {x['volume']} · page {x['page']}</span></div></a>" for x in moments)


def landing_html(man: dict[str, Any], base: str, fonts: dict[str, str]) -> str:
    b = man["book"]
    books = "".join(f"<div class='book'><div class='kicker'>Book {x['number']}</div><b>{_e(x['title'])}</b><div class='hi' lang='hi'>{_e(x.get('title_hi'))}</div>"
                    f"<small>{x.get('moments', 0)} moment{'s' if x.get('moments', 0) != 1 else ''}</small></div>" for x in b["books"])
    grid = _cards(man["moments"], base) or "<p>The first moments are being painted.</p>"
    head = (f"<meta name='description' content='The Cycle of Dharma — a bilingual graphic novel by {_e(b['author'])}. Scan a page, watch the moment.'>"
            f"<meta property='og:title' content='{_e(b['title'])}'><meta property='og:type' content='website'><meta property='og:url' content='{_e(man['site_url'])}'>"
            + (f"<meta property='og:image' content='{_e(man['moments'][0]['media']['poster'])}'>" if man["moments"] else ""))
    body = (f"<div class='wrap'><header class='top'><span class='kicker'>cycleofdharma.world</span>{_langs()}</header>"
            f"<h1>{_e(b['title'])}</h1><div class='hi' lang='hi' style='font-size:24px'>{_e(b.get('title_hi'))}</div>"
            f"<p class='from'>A graphic novel in three books by {_e(b['author'])}. Scan a page — watch its moment.</p>"
            f"<div class='books'>{books}</div><div class='rule'></div><h2 class='kicker'>Moments</h2><div class='grid'>{grid}</div>"
            f"<footer>© {_e(b['author'])}</footer></div>{LANG_JS}")
    return _doc(b["title"], body, base, fonts, head)


def not_found_html(base: str, fonts: dict[str, str]) -> str:
    body = (f"<div class='wrap'>{_top(base)}<div class='soon'><h1>This page is not in the book</h1>"
            f"<p>Check the code under the QR, or <a href='{base}/'>start at the beginning</a>.</p></div></div>{LANG_JS}")
    return _doc("Not found — The Cycle of Dharma", body, base, fonts, "<meta name='robots' content='noindex'>")


def build_static(session: Session, out: Path | None = None, base: str = "/site-preview", origin: str = "", site_url: str | None = None) -> dict[str, Any]:
    """Render the manifest to static HTML (the local preview / offline backup) with media copied under /media/."""
    out = out or site_dir() / "preview"
    tmp = out.with_name(out.name + ".tmp")
    if tmp.exists():
        shutil.rmtree(tmp)
    tmp.mkdir(parents=True)
    fonts = ensure_fonts(tmp / "fonts")
    ensure_texture(tmp / "textures")
    copied: dict[str, str] = {}

    def media_url(code: str, key: str, rel_path: str) -> str:
        src = db.abs_path(rel_path)
        name = media_pathname(code, key).split("/", 1)[1]
        dst = tmp / "media" / code / name
        dst.parent.mkdir(parents=True, exist_ok=True)
        if src and src.exists():
            try:
                os.link(src, dst)
            except OSError:
                shutil.copyfile(src, dst)
        copied[f"{code}/{name}"] = str(dst)
        return f"{origin}{base}/media/{code}/{name}"

    man = build_manifest(session, media_url, site_url)
    validate_manifest(man)
    (tmp / "manifest.json").write_text(json.dumps(man, ensure_ascii=False, indent=1))
    (tmp / "index.html").write_text(landing_html(man, base, fonts))
    by_code = {x["code"]: x for x in man["moments"]}
    for item in man["links"]:
        d = tmp / "v" / item["code"]
        d.mkdir(parents=True, exist_ok=True)
        if item["kind"] == "moment" and item["code"] in by_code:
            page = watch_html(man, by_code[item["code"]], base, fonts)
        elif item["kind"] == "chapter":
            page = chapter_html(man, item, base, fonts)
        elif item["kind"] == "redirect":
            dest = _e(item["destination"])
            page = f"<!doctype html><meta charset='utf-8'><meta http-equiv='refresh' content='0;url={dest}'><link rel='canonical' href='{dest}'><a href='{dest}'>{dest}</a>"
        else:
            page = soon_html(item["code"], base, fonts)
        (d / "index.html").write_text(page)
    (tmp / "404.html").write_text(not_found_html(base, fonts))
    (tmp / "robots.txt").write_text(f"User-agent: *\nAllow: /\nSitemap: {man['site_url']}/sitemap.xml\n")
    urls = [man["site_url"] + "/"] + [f"{man['site_url']}/v/{x['code']}" for x in man["moments"]]
    (tmp / "sitemap.xml").write_text("<?xml version='1.0' encoding='UTF-8'?><urlset xmlns='http://www.sitemaps.org/schemas/sitemap/0.9'>"
                                     + "".join(f"<url><loc>{_e(u)}</loc></url>" for u in urls) + "</urlset>")
    if out.exists():
        shutil.rmtree(out)
    tmp.rename(out)
    return {"dir": str(out), "manifest": man, "pages": len(man["links"]) + 1, "moments": len(man["moments"]), "media": len(copied)}


def export_zip(session: Session, dest: Path | None = None) -> Path:
    """Offline backup: the static site at the domain root (base ''), media included."""
    res = build_static(session, site_dir() / "export", base="", origin="")
    dest = dest or site_dir() / "cycleofdharma-site.zip"
    with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED) as z:
        for p in sorted(Path(res["dir"]).rglob("*")):
            if p.is_file():
                z.write(p, p.relative_to(res["dir"]).as_posix(), compress_type=zipfile.ZIP_STORED if p.suffix in (".mp4", ".jpg", ".woff2") else zipfile.ZIP_DEFLATED)
    session.add(SitePublish(kind="zip", ok=True, result={"path": db.rel(dest), "bytes": dest.stat().st_size}))
    session.flush()
    return dest


# ---------------------------------------------------------------------------------
# publish: Vercel Blob + revalidate
# ---------------------------------------------------------------------------------


def _sha1(p: Path) -> str:
    h = hashlib.sha1()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def blob_put(token: str, pathname: str, data: bytes | Path, content_type: str, max_age: int = 31536000, client: Any = None) -> dict[str, Any]:
    """Vercel Blob REST upload (what @vercel/blob's put() sends): PUT {BLOB_API}/?pathname=…, public, no random suffix,
    overwrite allowed. Returns {url, pathname, …}."""
    import httpx

    body = data.read_bytes() if isinstance(data, Path) else data
    headers = {"authorization": f"Bearer {token}", "x-api-version": "11", "x-vercel-blob-access": "public", "x-add-random-suffix": "0",
               "x-allow-overwrite": "1", "x-content-type": content_type, "x-cache-control-max-age": str(max_age)}
    c = client or httpx.Client(timeout=600)
    try:
        r = c.put(f"{BLOB_API}/", params={"pathname": pathname}, content=body, headers=headers)
        if r.status_code in (400, 404, 405):  # older API shape: the pathname in the path
            r = c.put(f"{BLOB_API}/{pathname}", content=body, headers=headers)
        r.raise_for_status()
        return r.json()
    finally:
        if client is None:
            c.close()


def publish_state_path() -> Path:
    return site_dir() / "publish_state.json"


def publish(session: Session, log: Any = print, client: Any = None) -> dict[str, Any]:
    """Upload changed media (sha1) + manifest.json to Vercel Blob, then POST {site}/api/revalidate."""
    import httpx

    token = _setting("BLOB_READ_WRITE_TOKEN")
    if not token:
        raise RuntimeError("set BLOB_READ_WRITE_TOKEN (Settings → Publishing) to publish; meanwhile use Preview site locally")
    pub = publishing(session)
    state_p = publish_state_path()
    state = json.loads(state_p.read_text()) if state_p.exists() else {}
    uploaded, skipped = [], 0

    def media_url(code: str, key: str, rel_path: str) -> str:
        nonlocal skipped
        src = db.abs_path(rel_path)
        pathname = media_pathname(code, key)
        if pub["media_base"]:  # media hosted elsewhere (same pathnames); nothing to upload
            return f"{pub['media_base']}/{pathname}"
        sha = _sha1(src)
        prev = state.get(pathname)
        if prev and prev.get("sha1") == sha and prev.get("url"):
            skipped += 1
            return prev["url"]
        ctype = "image/jpeg" if pathname.endswith(".jpg") else "video/mp4"
        res = blob_put(token, pathname, src, ctype, client=client)
        state[pathname] = {"sha1": sha, "url": res["url"], "bytes": src.stat().st_size}
        uploaded.append(pathname)
        log(f"uploaded {pathname} ({src.stat().st_size / 1e6:.1f} MB)")
        return res["url"]

    man = build_manifest(session, media_url)
    validate_manifest(man)
    raw = json.dumps(man, ensure_ascii=False).encode()
    res = blob_put(token, "manifest.json", raw, "application/json", max_age=60, client=client)
    state["manifest.json"] = {"sha1": hashlib.sha1(raw).hexdigest(), "url": res["url"]}
    state_p.write_text(json.dumps(state, indent=1))
    set_publishing(session, manifest_url=res["url"])
    reval: dict[str, Any] = {"ok": False}
    secret = _setting("REVALIDATE_SECRET")
    if secret:
        try:
            c = client or httpx.Client(timeout=30)
            r = c.post(f"{pub['site_url']}/api/revalidate", json={"secret": secret}, headers={"x-revalidate-secret": secret})
            reval = {"ok": r.status_code < 400, "status": r.status_code}
        except Exception as exc:  # noqa: BLE001
            reval = {"ok": False, "error": str(exc)[:200]}
    else:
        reval = {"ok": False, "error": "no REVALIDATE_SECRET: pages refresh within 5 minutes"}
    result = {"manifest_url": res["url"], "uploaded": uploaded, "skipped": skipped, "moments": len(man["moments"]), "links": len(man["links"]),
              "revalidate": reval, "site_url": pub["site_url"]}
    session.add(SitePublish(kind="publish", ok=True, result=result))
    session.flush()
    log(f"manifest → {res['url']}; revalidate {reval}")
    return result


def h_site_publish(ctx: Any, p: dict[str, Any]) -> dict[str, Any]:
    ctx.progress(done=1, total=4)
    prev = build_static(ctx.session, origin=p.get("origin", ""))
    ctx.log(f"preview: {prev['moments']} moments, {prev['pages']} pages")
    ctx.progress(done=2, total=4)
    out: dict[str, Any] = {"preview": {k: v for k, v in prev.items() if k != "manifest"}}
    if p.get("publish") and _setting("BLOB_READ_WRITE_TOKEN"):
        try:
            out["publish"] = publish(ctx.session, ctx.log)
        except Exception as exc:  # noqa: BLE001
            ctx.session.add(SitePublish(kind="publish", ok=False, result={"error": str(exc)[:500]}))
            ctx.session.commit()
            raise
    elif p.get("publish"):
        out["publish"] = {"skipped": "no BLOB_READ_WRITE_TOKEN — preview only"}
    ctx.progress(done=4, total=4)
    ctx.session.commit()
    return out


CHECKLIST = [
    {"id": "domain", "label": "Register cycleofdharma.world", "detail": "Any registrar. Keep the registrar's DNS panel open for step 5."},
    {"id": "project", "label": "Vercel → Add New Project → import the dharmastudio repo", "detail": "Root Directory: web · Framework: Next.js. Vercel then deploys on every push to main."},
    {"id": "blob", "label": "Vercel → Storage → create a Blob store", "detail": "Copy its read-write token into Settings → Publishing (BLOB_READ_WRITE_TOKEN). The site itself does not need it."},
    {"id": "env", "label": "Set the project's environment variables", "detail": "MANIFEST_URL = the manifest URL shown here after the first Publish · REVALIDATE_SECRET = the secret generated here. Optional: NEXT_PUBLIC_VERCEL_ANALYTICS=1."},
    {"id": "dns", "label": "Vercel → Domains → add cycleofdharma.world", "detail": "Set the DNS records Vercel shows (A / CNAME) at the registrar; wait for the certificate."},
    {"id": "publish", "label": "Publish from the studio", "detail": "Uploads changed media + manifest.json and refreshes the pages within seconds."},
]
