"""Read-only facts about a template's .sla / .sla.gz: real page size, page count, fonts, text.

The .sla page size is the truth (``template.xml`` ``psize`` can be wrong or in points). Works for
old (upper-case ``PAGEWIDTH``) and 1.7 (``PageWidth``, ``<Content Chars=...>``) file formats.
"""

from __future__ import annotations

import gzip
import re
from pathlib import Path

_PT_TO_MM = 25.4 / 72.0
_DEVANAGARI = re.compile("[ऀ-ॿ]")


def _attr(tag: str, name: str) -> str | None:
    m = re.search(r'\b' + name + r'="([^"]*)"', tag, re.I)
    return m.group(1) if m else None


_NAMED_CHROMA = re.compile(r"(red|green|blue|yellow|orange|purple|pink|brown|cyan|magenta)", re.I)


def _chromatic(c: str) -> bool:
    """True for a colour that is not black/white/grey (hex or a Scribus colour name)."""
    m = re.fullmatch(r"#([0-9a-fA-F]{2})([0-9a-fA-F]{2})([0-9a-fA-F]{2})", c)
    if m:
        r, g, b = (int(x, 16) for x in m.groups())
        return max(r, g, b) - min(r, g, b) > 40
    return bool(_NAMED_CHROMA.search(c))


def sla_info(path: str | Path) -> dict:
    """Return ``{ok, pages, w_mm, h_mm, fonts, kruti, devanagari, text, n_text_frames,
    n_images}``; ``ok`` False if the file cannot be read or has no page size."""
    p = Path(path)
    try:
        raw = gzip.open(p, "rb").read() if p.suffix == ".gz" else p.read_bytes()
    except (OSError, EOFError, gzip.BadGzipFile):
        return {"ok": False}
    t = raw.decode("utf-8", errors="replace")
    m = re.search(r"<DOCUMENT\b[^>]*>", t, re.I)
    if not m:
        return {"ok": False}
    d = m.group(0)
    w, h = _attr(d, "PageWidth"), _attr(d, "PageHeight")
    pages = _attr(d, "PageCount") or _attr(d, "ANZPAGES")
    if w is None or h is None:
        mp = re.search(r"<PAGE\b[^>]*>", t, re.I)
        if mp:
            w, h = _attr(mp.group(0), "PAGEWIDTH"), _attr(mp.group(0), "PAGEHEIGHT")
    try:
        wmm, hmm = float(w) * _PT_TO_MM, float(h) * _PT_TO_MM  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return {"ok": False}
    try:
        npages = int(pages) if pages else max(1, len(re.findall(r"<PAGE\b", t, re.I)))
    except ValueError:
        npages = 1
    fonts = sorted(set(re.findall(r'\bFont="([^"]*)"', t)) | set(re.findall(r'\bFONT="([^"]*)"', t)))
    chars = re.findall(r'\bChars="([^"]*)"', t) + re.findall(r'\bCH="([^"]*)"', t)
    text = " ".join(chars)
    used = re.findall(r'(?:FontColor|FillColor|LineColor|StrokeColor|PCOLOR2?|TXTFILL|TXTSTROKE)="([^"]*)"', t)
    chroma = sorted({c.upper() for c in used if _chromatic(c)})
    return {
        "ok": True, "pages": npages, "w_mm": round(wmm, 1), "h_mm": round(hmm, 1),
        "fonts": fonts, "chromatic_colors": chroma[:12], "bw": not chroma, "kruti": any("kruti" in f.lower() for f in fonts),
        "devanagari": bool(_DEVANAGARI.search(text)), "text": text[:400],
        "n_text_frames": len(re.findall(r'ItemType="4"|PTYPE="4"', t)),
        "n_images": len(re.findall(r'ItemType="2"|PTYPE="2"', t)),
    }
