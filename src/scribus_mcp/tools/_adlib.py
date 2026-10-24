"""Shared building blocks for the composed ad / flyer tools.

Two halves:

* MCP side (plain Python, no Scribus needed, unit-testable): ``build_rich_text`` turns
  ``text`` / ``runs`` into the final string plus per-character-range style spans, converting
  Unicode Hindi to Kruti Dev keystrokes on the way when asked to.
* Scribus side: ``AD_LIB`` is a block of script source that the tools prepend to their
  ``backend.script`` body. It defines the helpers that style a frame from spans, fit text into a
  frame by font size and create a "box that owns its text".

Script bodies must not contain multi-line string literals (the headless backend indents every
line), so everything is passed as ``repr`` of dicts/lists.
"""

from __future__ import annotations

import re
from typing import Any

from scribus_mcp.kruti import kruti_segments

KRUTI_SENTINEL = "__KRUTI__"
MIN_PRESS_PT = 5.0

_DEVA = re.compile("[ऀ-ॿ]")


def has_devanagari(text: str) -> bool:
    return bool(_DEVA.search(text or ""))


def build_rich_text(
    text: str | None,
    runs: list[dict[str, Any]] | None,
    *,
    font: str | None,
    size_pt: float,
    color: str | None,
    hindi: str = "auto",
    hindi_scale: float = 1.0,
) -> tuple[str, list[dict[str, Any]], int]:
    """Return ``(final_text, spans, paragraph_count)``.

    ``spans`` cover the whole text, in order, with the keys ``start``, ``len``, ``font``,
    ``size``, ``color`` and optional ``stroke``/``hscale``. A span whose font is
    ``KRUTI_SENTINEL`` is resolved to the installed Kruti Dev font inside Scribus.

    ``hindi``: ``"auto"`` converts any Devanagari run to Kruti Dev keystrokes, ``"kruti"``
    does the same, ``"unicode"`` leaves the text untouched (use a Unicode Devanagari font).
    """
    if runs:
        run_list = [dict(r) for r in runs if r.get("text") not in (None, "")]
    else:
        run_list = [{"text": text or ""}]
    out_text: list[str] = []
    spans: list[dict[str, Any]] = []
    pos = 0
    for r in run_list:
        rtext = str(r.get("text", ""))
        rfont = r.get("font") or font
        rsize = float(r.get("size_pt") or size_pt)
        rcolor = r.get("color") or color
        pieces: list[tuple[str, bool]]
        if hindi != "unicode" and has_devanagari(rtext):
            pieces = [(c, k) for _, _, c, k in kruti_segments(rtext)]
        else:
            pieces = [(rtext, False)]
        for ptext, is_k in pieces:
            if not ptext:
                continue
            span = {
                "start": pos,
                "len": len(ptext),
                "font": KRUTI_SENTINEL if is_k else rfont,
                "size": rsize * (hindi_scale if is_k else 1.0),
                "color": rcolor,
            }
            if r.get("stroke_color"):
                span["stroke"] = r["stroke_color"]
            if r.get("h_scale"):
                span["hscale"] = float(r["h_scale"])
            spans.append(span)
            out_text.append(ptext)
            pos += len(ptext)
    full = "".join(out_text)
    return full, spans, full.count("\n") + 1


# Kruti Dev keystroke detection (heuristic) -------------------------------------------------
# Kruti keystrokes are Latin-1 letters/punctuation that are meaningless as English. These marks
# and whole-word hits only occur in Kruti text in practice.
_KRUTI_MARKS = set("¡ªÇÈÉÊ¼½¿ñÑØÙàá«¬")
_KRUTI_WORDS = {
    "gS", "gSa", "ds", "dh", "dk", "esa", "ls", "dks", "vkSj", "gksxk", "fd", "ij", "Hkh", "rFkk",
    "lsok", "ukSdjh", "fnukad", "vkosnu", "iznsk", "dk;kZy;", "foKkiu", "lwpuk", "lkoZtfud",
}


def looks_like_kruti(text: str) -> bool:
    """True if ``text`` looks like Kruti Dev keystrokes rather than English or Unicode Hindi."""
    if not text or has_devanagari(text):
        return False
    marks = sum(1 for ch in text if ch in _KRUTI_MARKS)
    words = re.findall(r"[A-Za-z -ÿ;\[\]~+]+", text)
    hits = sum(1 for w in words if w in _KRUTI_WORDS)
    return marks >= 2 or hits >= 2


# --- Scribus-side library ---------------------------------------------------------------

AD_LIB = r'''
_AD_WARN = []

def _ad_kfont():
    import scribus as __s
    _names = __s.getFontNames()
    for _n in _names:
        if 'Kruti Dev 010' in _n:
            return _n
    for _n in _names:
        if 'ruti' in _n:
            return _n
    return None

def _ad_font_ok(_font):
    import scribus as __s
    return _font in __s.getFontNames()

def _ad_style(_f, _spans, _scale=1.0, _min=5.0, _body=True):
    import scribus as __s
    _k = _ad_kfont()
    for _sp in _spans:
        if _sp['len'] <= 0:
            continue
        __s.selectText(_sp['start'], _sp['len'], _f)
        _font = _sp.get('font')
        if _font == '__KRUTI__':
            _font = _k
            if _font is None and 'Kruti Dev 010 not installed' not in _AD_WARN:
                _AD_WARN.append('Kruti Dev 010 not installed: Hindi will not display')
        if _font:
            if _ad_font_ok(_font):
                __s.setFont(_font, _f)
            elif ('font not installed: ' + _font) not in _AD_WARN:
                _AD_WARN.append('font not installed: ' + _font)
        _sz = max(_min, round(_sp['size'] * _scale * 4) / 4.0)
        __s.setFontSize(_sz, _f)
        if _sp.get('color'):
            __s.setTextColor(_sp['color'], _f)
        if _sp.get('stroke'):
            __s.setTextStroke(_sp['stroke'], _f)
        if _sp.get('hscale'):
            __s.setTextScalingH(_sp['hscale'], _f)
    __s.selectText(0, 0, _f)

def _ad_overflow(_f):
    import scribus as __s
    try:
        __s.layoutText(_f)
    except Exception:
        pass
    try:
        return bool(__s.textOverflows(_f))
    except Exception:
        return False

def _ad_lines(_f):
    import scribus as __s
    try:
        __s.layoutText(_f)
    except Exception:
        pass
    try:
        return int(__s.getTextLines(_f))
    except Exception:
        return 0

def _ad_fit(_f, _spans, _mode, _min, _max_scale, _no_wrap, _npar):
    """Find the scale factor for all span sizes so the text just fits the frame.
    mode 'shrink': never above 1.0; 'fill': up to _max_scale; 'none': 1.0."""
    if _mode == 'none':
        _ad_style(_f, _spans, 1.0, _min)
        return 1.0
    def _ok(_sc):
        _ad_style(_f, _spans, _sc, _min)
        if _ad_overflow(_f):
            return False
        if _no_wrap and _ad_lines(_f) > _npar:
            return False
        return True
    _hi = _max_scale if _mode == 'fill' else 1.0
    if _ok(_hi):
        return _hi
    _lo = 0.05
    if not _ok(_lo):
        _ad_style(_f, _spans, _lo, _min)
        return _lo
    for _i in range(14):
        _mid = (_lo + _hi) / 2.0
        if _ok(_mid):
            _lo = _mid
        else:
            _hi = _mid
    _ad_style(_f, _spans, _lo, _min)
    return _lo

def _ad_corner(_f, _radius_mm, _w, _h, _pill):
    import scribus as __s
    # Scribus's corner-radius value is about twice the visual radius, and clamps at ~1.4 x the
    # short side (which is a full pill).
    _cap = 1.4 * min(_w, _h)
    _v = _cap if _pill else min(_cap, float(_radius_mm) * 2.0)
    if _v > 0:
        # setCornerRadius also rounds the CURRENT SELECTION (e.g. a shape imported just before),
        # turning it into a square: clear the selection first.
        __s.deselectAll()
        __s.setCornerRadius(int(round(_v)), _f)

def _ad_box(_sp):
    """Create one text frame that owns its fill, border, corner radius, padding and text."""
    import scribus as __s
    if _sp.get('name'):
        _f = __s.createText(_sp['x'], _sp['y'], _sp['w'], _sp['h'], _sp['name'])
    else:
        _f = __s.createText(_sp['x'], _sp['y'], _sp['w'], _sp['h'])
    __s.setText(_sp['text'], _f)
    __s.setLineSpacingMode(1, _f)
    if _sp.get('fill'):
        __s.setFillColor(_sp['fill'], _f)
        if _sp.get('fill_shade') is not None:
            __s.setFillShade(int(_sp['fill_shade']), _f)
    else:
        __s.setFillColor('None', _f)
    if _sp.get('line') and _sp.get('line_w', 0) > 0:
        __s.setLineColor(_sp['line'], _f)
        __s.setLineWidth(float(_sp['line_w']), _f)
    else:
        __s.setLineColor('None', _f)
        __s.setLineWidth(0, _f)
    if _sp.get('pill') or _sp.get('radius_mm', 0) > 0:
        _ad_corner(_f, _sp.get('radius_mm', 0), _sp['w'], _sp['h'], _sp.get('pill'))
    _p = _sp.get('pad_mm', [0, 0, 0, 0])
    __s.setTextDistances(_p[0], _p[1], _p[2], _p[3], _f)
    __s.setTextAlignment({'left': 0, 'center': 1, 'right': 2, 'justify': 3}[_sp.get('align', 'center')], _f)
    __s.setTextVerticalAlignment({'top': 0, 'middle': 1, 'bottom': 2}[_sp.get('valign', 'middle')], _f)
    _scale = _ad_fit(_f, _sp['spans'], _sp.get('fit', 'shrink'), _sp.get('min_pt', 5.0),
                     _sp.get('max_scale', 6.0), _sp.get('no_wrap', False), _sp.get('npar', 1))
    return _f, _scale
'''


def box_spec(**kw: Any) -> dict[str, Any]:
    """Helper that documents the keys ``_ad_box`` understands (and drops None values)."""
    return {k: v for k, v in kw.items() if v is not None}
