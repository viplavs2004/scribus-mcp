"""Document verification and press export.

``verify_document`` is the check an agent must run before it says "done". It reports, as
structured findings: text overflow (including linked-frame chains), text below the press
minimum (5 pt), objects off the page, fonts that are not installed or differ from what was
requested, Unicode Hindi in a font that cannot draw it, Kruti Dev keystrokes in a non-Kruti
font (and Unicode in Kruti), empty frames, missing/low-resolution images, overlapping text
frames, and grouped objects it cannot inspect.
"""

from __future__ import annotations

import base64
import contextlib
from pathlib import Path
from typing import Annotated, Literal

from mcp.types import ImageContent, TextContent
from pydantic import Field

from scribus_mcp.tools._adlib import looks_like_kruti
from scribus_mcp.tools._common import Mode, ServerCtx, get_backend
from scribus_mcp.tools.hindi import DEVANAGARI_FAMILIES

# Script body. Parameters are injected as _P (dict). The result is left in _value.
VERIFY_SCRIPT = r'''
import scribus as _s
import re as _re
_findings = []
_fonts_used = {}
_installed = set(_s.getFontNames())
_unit = 25.4 / 72.0 / _s.pointsToDocUnit(1.0)  # doc units -> mm
_text_boxes = []
_groups = 0
_objects = 0

def _add(_sev, _kind, _obj, _page, _msg):
    _findings.append({'severity': _sev, 'kind': _kind, 'object': _obj, 'page': _page, 'message': _msg})

def _is_kruti_font(_f):
    return 'ruti' in (_f or '') or 'DevLys' in (_f or '') or 'Chanakya' in (_f or '')

def _deva_font(_f):
    for _k in _P['deva_families']:
        if _k.lower() in (_f or '').lower():
            return True
    return False

_seen_chain = set()
_pages = _s.pageCount()
for _pg in range(1, _pages + 1):
    _s.gotoPage(_pg)
    _pw, _ph = _s.getPageSize()
    _pw = _pw * _unit
    _ph = _ph * _unit
    _tol = _P['bleed_tolerance_mm']
    for _it in (_s.getPageItems() or []):
        _n, _t = _it[0], _it[1]
        _objects += 1
        try:
            _bb = _s.getBoundingBox(_n)
            _x, _y, _w, _h = [_v * _unit for _v in _bb]
        except Exception:
            continue
        if _t == 12:
            _groups += 1
            _add('info', 'group_not_inspected', _n, _pg, 'Group: objects inside a group cannot be addressed by name, so their text was NOT checked. Ungroup to verify.')
        if _x + _w < 0 or _y + _h < 0 or _x > _pw or _y > _ph:
            _add('error', 'off_page', _n, _pg, 'Object is completely outside the page.')
        elif _x < -_tol or _y < -_tol or _x + _w > _pw + _tol or _y + _h > _ph + _tol:
            _add('warning', 'sticks_out_of_page', _n, _pg, 'Object extends %.1f mm beyond the page edge (bleed tolerance %.1f mm).' % (max(-_x, -_y, _x + _w - _pw, _y + _h - _ph), _tol))
        if _t == 2:
            try:
                _fn = _s.getImageFile(_n)
            except Exception:
                _fn = ''
            if not _fn:
                _add('warning', 'image_frame_empty', _n, _pg, 'Image frame has no picture.')
            else:
                import os as _os
                if not _os.path.exists(_fn):
                    _add('error', 'image_missing', _n, _pg, 'Image file not found: %s' % _fn)
                else:
                    try:
                        _ppi = _s.getImagePpi(_n)
                        _eff = min(_ppi) if isinstance(_ppi, (list, tuple)) else _ppi
                        if _eff and _eff < _P['min_image_ppi']:
                            _add('warning', 'image_low_resolution', _n, _pg, 'Effective resolution %.0f ppi (< %d).' % (_eff, _P['min_image_ppi']))
                    except Exception:
                        pass
        if _t != 4:
            continue
        _len = _s.getTextLength(_n)
        try:
            _prev = _s.getPrevLinkedFrame(_n)
        except Exception:
            _prev = ''
        if _len == 0:
            if not _prev:
                _add('warning', 'empty_frame', _n, _pg, 'Text frame is empty.')
            continue
        _text = _s.getAllText(_n)
        # per-run fonts/sizes
        _runs = []
        _step_limit = _P['max_chars']
        _cnt = min(_len, _step_limit)
        for _i in range(_cnt):
            _s.selectText(_i, 1, _n)
            _fnt = _s.getFont(_n)
            _sz = round(_s.getFontSize(_n), 2)
            if _runs and _runs[-1][0] == _fnt and _runs[-1][1] == _sz:
                _runs[-1][2] += _text[_i:_i + 1]
            else:
                _runs.append([_fnt, _sz, _text[_i:_i + 1]])
        _s.selectText(0, 0, _n)
        if _len > _cnt:
            _add('info', 'text_truncated_check', _n, _pg, 'Only the first %d characters were style-checked.' % _cnt)
        _sizes = set()
        _bad_size = False
        for _fnt, _sz, _rt in _runs:
            _fonts_used[_fnt] = _fonts_used.get(_fnt, 0) + len(_rt)
            if _rt.strip():
                _sizes.add(_sz)
                if _sz < _P['min_pt'] and not _bad_size:
                    _bad_size = True
                    _add('error', 'text_below_min_size', _n, _pg, 'Text of %.2f pt is below the %.1f pt press minimum.' % (_sz, _P['min_pt']))
            if _fnt not in _installed:
                _add('error', 'font_missing', _n, _pg, 'Font "%s" is not installed (Scribus will substitute it).' % _fnt)
            _has_deva = bool(_re.search('[ऀ-ॿ]', _rt))
            if _has_deva and _is_kruti_font(_fnt):
                _add('error', 'unicode_in_kruti_font', _n, _pg, 'Unicode Devanagari in Kruti Dev renders as empty boxes: use set_text_hindi / create_text_box (converts to keystrokes).')
            elif _has_deva and not _deva_font(_fnt):
                _add('error', 'hindi_in_wrong_font', _n, _pg, 'Unicode Hindi in "%s", which has no Devanagari glyphs. Use Kruti Dev (via set_text_hindi) or a Devanagari Unicode font.' % _fnt)
            if (not _is_kruti_font(_fnt)) and _rt.strip() and _P['kruti_hints'] and _kruti_like(_rt):
                _add('error', 'kruti_keystrokes_in_non_kruti_font', _n, _pg, 'Text "%s" looks like Kruti Dev keystrokes but is set in "%s": it will show as Latin garbage.' % (_rt.strip()[:30], _fnt))
        _exp = _P['expected_fonts'].get(_n)
        if _exp:
            _got = sorted(set(_r[0] for _r in _runs if _r[2].strip()))
            if not any(_exp.lower() in _g.lower() for _g in _got):
                _add('error', 'font_differs_from_requested', _n, _pg, 'Requested "%s" but the frame uses %s.' % (_exp, _got))
        # overflow incl. linked chains
        _last = _n
        try:
            _last = _s.getLastLinkedFrame(_n) or _n
        except Exception:
            pass
        _key = _last
        if _key not in _seen_chain:
            _seen_chain.add(_key)
            try:
                _s.layoutTextChain(_n)
            except Exception:
                try:
                    _s.layoutText(_n)
                except Exception:
                    pass
            try:
                _ov = _s.textOverflows(_last, 1)
            except Exception:
                _ov = 0
            if _ov:
                _add('error', 'text_overflow', _last, _pg, 'Text overflows the frame%s: the end of the text is cut off.' % (' chain ending here' if _last != _n else ''))
        if _text.strip():
            _text_boxes.append((_n, _pg, _x, _y, _w, _h))

# overlaps between text frames with text
for _a in range(len(_text_boxes)):
    for _b in range(_a + 1, len(_text_boxes)):
        _na, _pa, _xa, _ya, _wa, _ha = _text_boxes[_a]
        _nb, _pb, _xb, _yb, _wb, _hb = _text_boxes[_b]
        if _pa != _pb:
            continue
        _ox = min(_xa + _wa, _xb + _wb) - max(_xa, _xb)
        _oy = min(_ya + _ha, _yb + _hb) - max(_ya, _yb)
        if _ox > 0.5 and _oy > 0.5:
            _small = min(_wa * _ha, _wb * _hb)
            if _small > 0 and (_ox * _oy) / _small > 0.35:
                _add('warning', 'text_frames_overlap', _na, _pa, 'Overlaps text frame %s by %.0f%% of the smaller frame.' % (_nb, 100.0 * _ox * _oy / _small))
_value = {'pages': _pages, 'objects': _objects, 'groups': _groups, 'findings': _findings, 'fonts_used': _fonts_used}
'''

_KRUTI_HELPER = r'''
_KMARKS = set(_P['kruti_marks'])
_KWORDS = set(_P['kruti_words'])
def _kruti_like(_t):
    if not _t:
        return False
    _m = sum(1 for _c in _t if _c in _KMARKS)
    _w = sum(1 for _x in _re.findall('[A-Za-z -ÿ;\\[\\]~+]+', _t) if _x in _KWORDS)
    return _m >= 2 or _w >= 2
'''


def build_verify_script(params: dict) -> str:
    from scribus_mcp.tools._adlib import _KRUTI_MARKS, _KRUTI_WORDS

    p = dict(params)
    p["kruti_marks"] = "".join(sorted(_KRUTI_MARKS))
    p["kruti_words"] = sorted(_KRUTI_WORDS)
    p["deva_families"] = list(DEVANAGARI_FAMILIES)
    head = "import re as _re\n_P = " + repr(p) + "\n"
    # helper must exist before the main loop
    body = VERIFY_SCRIPT.replace("_seen_chain = set()", _KRUTI_HELPER + "\n_seen_chain = set()", 1)
    return head + body


def summarize(findings: list[dict]) -> dict:
    out = {"errors": 0, "warnings": 0, "info": 0}
    for f in findings:
        sev = f.get("severity")
        key = {"error": "errors", "warning": "warnings"}.get(sev, "info")
        out[key] += 1
    return out


def register(mcp, ctx: ServerCtx) -> None:
    @mcp.tool()
    async def verify_document(
        expected_fonts: dict[str, str] | None = None,
        min_font_pt: float = 5.0,
        bleed_tolerance_mm: float = 3.0,
        min_image_ppi: int = 100,
        check_kruti_keystrokes: bool = True,
        mode: Mode = "auto",
    ) -> dict:
        """RUN THIS BEFORE SAYING A LAYOUT IS DONE. Structured quality check of the open document.

        Findings (each has severity error/warning/info, kind, object, page, message):
        ``text_overflow`` (also follows linked-frame chains), ``text_below_min_size``
        (< ``min_font_pt``, press rule 5 pt), ``off_page`` / ``sticks_out_of_page``,
        ``font_missing``, ``font_differs_from_requested`` (pass ``expected_fonts``
        ``{"object name": "Impact"}``), ``hindi_in_wrong_font`` (Unicode Devanagari in a font
        without those glyphs), ``unicode_in_kruti_font``, ``kruti_keystrokes_in_non_kruti_font``
        (heuristic), ``empty_frame``, ``image_missing`` / ``image_frame_empty`` /
        ``image_low_resolution``, ``text_frames_overlap``, ``group_not_inspected``.
        Fix every ``error`` and re-run until ``errors == 0``; then render and look at the image.
        """
        backend = await get_backend(ctx, mode)
        script = build_verify_script(
            {
                "min_pt": float(min_font_pt),
                "bleed_tolerance_mm": float(bleed_tolerance_mm),
                "min_image_ppi": int(min_image_ppi),
                "expected_fonts": expected_fonts or {},
                "kruti_hints": bool(check_kruti_keystrokes),
                "max_chars": 4000,
            }
        )
        res = await backend.script(script, result_expr="_value")
        if not res.ok:
            return {"ok": False, "error": res.error or "verification script failed"}
        v = res.value or {}
        summary = summarize(v.get("findings", []))
        return {
            "ok": True,
            "passed": summary["errors"] == 0,
            "summary": {**summary, "pages": v.get("pages"), "objects": v.get("objects")},
            "findings": v.get("findings", []),
            "fonts_used": v.get("fonts_used", {}),
            "error": None,
        }

    @mcp.tool()
    async def export_press_pdf(
        path: str,
        standard: Literal["X-1a", "X-3", "X-4"] = "X-1a",
        resolution: Annotated[int, Field(ge=150, le=1200)] = 300,
        bleed_mm: float = 0.0,
        pages: str = "all",
        allow_errors: bool = False,
        mode: Mode = "auto",
    ) -> dict:
        """Export a press-ready PDF/X (X-1a default for newspapers, X-3, X-4).

        Runs ``verify_document`` first and refuses to export while there are errors
        (text below 5 pt, overflow, wrong Hindi font ...) unless ``allow_errors=True``.
        Sets the mandatory PDF/X info string, printer output and the bleed. Returns the path,
        the verification summary and the version actually written.
        """
        backend = await get_backend(ctx, mode)
        vres = await backend.script(
            build_verify_script(
                {
                    "min_pt": 5.0, "bleed_tolerance_mm": max(3.0, bleed_mm),
                    "min_image_ppi": 100, "expected_fonts": {}, "kruti_hints": True,
                    "max_chars": 4000,
                }
            ),
            result_expr="_value",
        )
        summary = {}
        findings: list[dict] = []
        if vres.ok:
            findings = (vres.value or {}).get("findings", [])
            summary = summarize(findings)
            if summary["errors"] and not allow_errors:
                return {
                    "ok": False,
                    "error": f"{summary['errors']} verification error(s): fix them or pass allow_errors=True",
                    "findings": [f for f in findings if f["severity"] == "error"],
                }
        version = {"X-4": 10, "X-1a": 11, "X-3": 12}[standard]
        body = f"""\
import scribus as _s
_pdf = _s.PDFfile()
_pdf.file = {path!r}
_pdf.version = {version}
_pdf.resolution = {resolution}
_pdf.compress = 1
_pdf.outdst = 1
_pdf.bleedt = _pdf.bleedb = _pdf.bleedl = _pdf.bleedr = {bleed_mm}
try:
    _pdf.info = _s.getDocName().replace(chr(92), '/').split('/')[-1] or 'Document'
except Exception:
    _pdf.info = 'Document'
_total = _s.pageCount()
if {pages!r} == 'all':
    _pdf.pages = list(range(1, _total + 1))
else:
    _r = []
    for _part in {pages!r}.split(','):
        _part = _part.strip()
        if '-' in _part:
            _a, _b = _part.split('-', 1)
            _r.extend(range(int(_a), int(_b) + 1))
        elif _part:
            _r.append(int(_part))
    _pdf.pages = _r
_pdf.save()
import os
_value = {{'path': {path!r}, 'exists': os.path.exists({path!r}), 'size': os.path.getsize({path!r}) if os.path.exists({path!r}) else 0, 'version': {version}}}
"""
        res = await backend.script(body, result_expr="_value")
        if not res.ok:
            return {"ok": False, "error": res.error}
        val = res.value or {}
        return {
            "ok": bool(val.get("exists")),
            "standard": standard,
            "file": val,
            "verification": summary,
            "warnings": [f for f in findings if f["severity"] == "warning"],
            "error": None if val.get("exists") else "PDF was not written",
        }

    @mcp.tool()
    async def render_preview(
        path: str = "",
        dpi: Annotated[int, Field(ge=36, le=300)] = 100,
        page_number: int = 1,
        mode: Mode = "auto",
    ) -> list[TextContent | ImageContent]:
        """Render a page to a PNG, cropped exactly to the page, and return it inline.

        Prefer this over ``render_page_to_image``: it crops the oversized canvas Scribus's
        ImageExport produces, so the picture is the page only. ``path`` optionally also saves
        the PNG there. Look at the picture and compare it with the brief before finishing.
        """
        backend = await get_backend(ctx, mode)
        out = Path(path) if path else ctx.config.workdir / "preview.png"
        body = f"""\
import scribus as _s
_s.gotoPage({int(page_number)})
_e = _s.ImageExport()
_e.type = 'PNG'
_e.dpi = {int(dpi)}
_e.scale = 100
_e.saveAs({str(out)!r})
_pw, _ph = _s.getPageSize()
_k = _s.pointsToDocUnit(1.0)  # page size comes in document units (mm for most templates)
_value = [_pw / _k, _ph / _k]
"""
        res = await backend.script(body, result_expr="_value")
        if not res.ok or not out.exists():
            return [TextContent(type="text", text=f"Render failed: {res.error or 'no file'}")]
        try:
            from io import BytesIO

            from PIL import Image

            pw_pt, ph_pt = res.value
            img = Image.open(out)
            box = (0, 0, round(pw_pt / 72 * dpi), round(ph_pt / 72 * dpi))
            # ImageExport may render at a different scale than asked (then the image already is
            # the page); only crop when the canvas is oversized (aspect ratio differs).
            if abs(img.width / img.height - box[2] / box[3]) > 0.01:
                img = img.crop(box)
            box = (0, 0, img.width, img.height)
            if path:
                img.save(out)
            buf = BytesIO()
            img.save(buf, format="PNG", optimize=True)
            data = buf.getvalue()
        except Exception as exc:  # pragma: no cover
            return [TextContent(type="text", text=f"Render post-processing failed: {exc}")]
        finally:
            if not path:
                with contextlib.suppress(OSError):
                    out.unlink()
        return [
            TextContent(type="text", text=f"Page {page_number} at {dpi} dpi ({box[2]}x{box[3]} px)"),
            ImageContent(
                type="image", data=base64.b64encode(data).decode("ascii"), mimeType="image/png"
            ),
        ]


__all__ = ["looks_like_kruti", "summarize"]
