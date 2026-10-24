"""Composed ad / flyer building blocks.

These tools exist because stacking primitives (a rectangle, then a text frame on top, then an
ellipse) is what produced broken flyers: boxes that do not hold their text, double outlines,
fixed 15 pt leading under 40 pt type, text that is tiny or overflowing. Each tool here builds
ONE visual element as a unit and fits its text before returning:

* ``create_text_box``    filled rounded / pill / square box that owns its text
* ``create_badge``       circle or ellipse with a ring and centred text
* ``create_bullet_list`` custom-bullet list with hanging indent, 1-3 columns, auto-fit
* ``create_label_bar``   a coloured label chip plus a text pill (NOTE bar, phone bar)
* ``fit_text_to_frame``  fit existing text to its frame by font size

All sizes are millimetres except font sizes (pt). Colours accept a document colour name, a role
name, ``#RRGGBB`` or a basic colour word. Hindi (Devanagari) text is converted to Kruti Dev
keystrokes automatically (``hindi="auto"``).
"""

from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import Field

from scribus_mcp.tools._adlib import AD_LIB, MIN_PRESS_PT, build_rich_text
from scribus_mcp.tools._common import Mode, ServerCtx, clean_user_text, get_backend
from scribus_mcp.tools.palette import resolve_color

MM_TO_PT = 72.0 / 25.4

Align = Literal["left", "center", "right", "justify"]
VAlign = Literal["top", "middle", "bottom"]
Fit = Literal["none", "shrink", "fill"]


async def _color(backend, spec: str | None) -> str | None:
    """Resolve a colour spec; None / '' / 'None' mean 'no colour'."""
    if spec is None or str(spec).strip() in ("", "None", "none", "transparent"):
        return None
    name, _ = await resolve_color(backend, spec)
    return name


async def _resolve_runs(backend, runs: list[dict[str, Any]] | None) -> list[dict[str, Any]] | None:
    if not runs:
        return None
    out = []
    for r in runs:
        r = dict(r)
        r["text"] = clean_user_text(str(r.get("text", "")))
        for key in ("color", "stroke_color"):
            if r.get(key):
                r[key] = await _color(backend, r[key])
        out.append(r)
    return out


def _fail(res, what: str) -> dict:
    return {"ok": False, "error": res.error or f"{what} failed"}


def register(mcp, ctx: ServerCtx) -> None:
    @mcp.tool()
    async def create_text_box(
        x_mm: float,
        y_mm: float,
        width_mm: float,
        height_mm: float,
        text: str = "",
        runs: list[dict[str, Any]] | None = None,
        shape: Literal["rect", "rounded", "pill"] = "rounded",
        corner_radius_mm: float = 3.0,
        fill_color: str | None = None,
        fill_shade: Annotated[int | None, Field(ge=0, le=100)] = None,
        border_color: str | None = None,
        border_width_pt: float = 0.0,
        text_color: str = "Black",
        font: str | None = None,
        font_size_pt: float = 14.0,
        align: Align = "center",
        valign: VAlign = "middle",
        padding_mm: float = 1.5,
        fit: Fit = "shrink",
        min_font_pt: float = 5.0,
        max_font_pt: float | None = None,
        no_wrap: bool = False,
        stroke_color: str | None = None,
        h_scale_percent: float | None = None,
        hindi: Literal["auto", "unicode"] = "auto",
        name: str = "",
        mode: Mode = "auto",
    ) -> dict:
        """PREFERRED way to make a banner, headline panel, button, price tag, phone bar, title.

        ONE object that owns its fill, border, rounded corners, padding and text, so it can
        never drift apart from a separate rectangle. Text is vertically centred by default and
        fitted to the box: ``fit="shrink"`` (default) reduces the font until it fits,
        ``fit="fill"`` grows it to the largest size that fits (use for headlines; ``max_font_pt``
        caps it), ``fit="none"`` keeps ``font_size_pt``. Leading is automatic, so big type
        never overprints. ``no_wrap=True`` forces one line per paragraph (the font shrinks
        to fit the width, good for titles).

        ``text`` may contain ``\\n`` for several lines. For mixed sizes/fonts/colours pass
        ``runs`` instead of ``text``: ``[{"text": "ADMISSION OPEN\\n", "size_pt": 40},
        {"text": "2027-28", "size_pt": 32, "color": "#FFDE00"}]`` (keys: text, size_pt,
        font, color, stroke_color, h_scale). All run sizes scale together when fitting.

        ``shape``: "rect", "rounded" (``corner_radius_mm`` is the visual radius) or "pill".
        For a condensed bold headline use ``font="Impact Regular"`` (see ``suggest_fonts``).
        Hindi in the text is converted to Kruti Dev automatically.

        Returns the frame name, the applied ``font_scale``, the final font sizes, whether
        text still overflows (only possible at the 5 pt floor) and warnings.
        """
        backend = await get_backend(ctx, mode)
        rruns = await _resolve_runs(backend, runs)
        full, spans, npar = build_rich_text(
            clean_user_text(text), rruns, font=font, size_pt=font_size_pt,
            color=await _color(backend, text_color) or "Black", hindi=hindi,
        )
        if not full:
            return {"ok": False, "error": "text or runs is required"}
        if stroke_color or h_scale_percent:
            sc = await _color(backend, stroke_color)
            for sp in spans:
                if sc:
                    sp.setdefault("stroke", sc)
                if h_scale_percent:
                    sp.setdefault("hscale", float(h_scale_percent))
        spec = {
            "x": x_mm, "y": y_mm, "w": width_mm, "h": height_mm, "name": name or None,
            "text": full, "spans": spans, "npar": npar,
            "fill": await _color(backend, fill_color), "fill_shade": fill_shade,
            "line": await _color(backend, border_color), "line_w": border_width_pt,
            "radius_mm": corner_radius_mm if shape == "rounded" else 0,
            "pill": shape == "pill",
            "pad_mm": [padding_mm] * 4,
            "align": align, "valign": valign, "fit": fit,
            "min_pt": max(MIN_PRESS_PT, min_font_pt),
            "max_scale": (max_font_pt / font_size_pt) if (max_font_pt and fit == "fill") else 6.0,
            "no_wrap": no_wrap,
        }
        body = AD_LIB + f"""
import scribus as _s
_spec = {spec!r}
_f, _scale = _ad_box(_spec)
_ov = _ad_overflow(_f)
_value = {{"name": _f, "font_scale": round(_scale, 3),
          "sizes": sorted(set(max({spec['min_pt']}, round(_sp['size'] * _scale * 4) / 4.0) for _sp in _spec['spans'])),
          "overflows": _ov, "lines": _ad_lines(_f), "warnings": _AD_WARN}}
"""
        res = await backend.script(body, result_expr="_value")
        if not res.ok:
            return _fail(res, "create_text_box")
        return {"ok": True, **(res.value or {}), "error": None}

    @mcp.tool()
    async def create_badge(
        x_mm: float,
        y_mm: float,
        diameter_mm: float,
        text: str = "",
        runs: list[dict[str, Any]] | None = None,
        height_mm: float | None = None,
        fill_color: str = "#1F4E9E",
        ring_color: str = "#FFC20E",
        ring_width_pt: float = 3.0,
        ring_style: Literal["solid", "dashed", "dotted", "double", "none"] = "solid",
        text_color: str = "#FFFFFF",
        font: str | None = None,
        font_size_pt: float = 12.0,
        fit: Fit = "shrink",
        min_font_pt: float = 5.0,
        max_font_pt: float | None = None,
        text_area_ratio: float = 0.72,
        hindi: Literal["auto", "unicode"] = "auto",
        group: bool = False,
        name: str = "",
        mode: Mode = "auto",
    ) -> dict:
        """Circular (or elliptical, give ``height_mm``) badge with a ring and centred text.

        Use for "Ranked 7th in Noida", "Free admission ...", seals, stamps, price circles.
        Builds the disc, the ring (solid / dashed / dotted / double) and a text frame inscribed
        in the circle and fits the text. Parts are NOT grouped by default (``group=True`` to
        group): objects inside a group cannot be addressed by name afterwards, so you could
        not edit the text or verify it. (x, y) is the top-left of the
        bounding box. ``runs`` as in ``create_text_box`` (mixed sizes/colours per line).
        Returns the ``disc`` and ``text`` names (and ``group`` if requested).
        """
        backend = await get_backend(ctx, mode)
        h = height_mm or diameter_mm
        rruns = await _resolve_runs(backend, runs)
        full, spans, npar = build_rich_text(
            clean_user_text(text), rruns, font=font, size_pt=font_size_pt,
            color=await _color(backend, text_color) or "White", hindi=hindi,
        )
        if not full:
            return {"ok": False, "error": "text or runs is required"}
        ring_mm = ring_width_pt / MM_TO_PT
        # Inscribed rectangle of the inner ellipse (ratio of the inner box).
        iw = (diameter_mm - ring_mm) * text_area_ratio
        ih = (h - ring_mm) * text_area_ratio
        tspec = {
            "x": x_mm + (diameter_mm - iw) / 2, "y": y_mm + (h - ih) / 2, "w": iw, "h": ih,
            "text": full, "spans": spans, "npar": npar, "fill": None, "line": None,
            "pad_mm": [0, 0, 0, 0], "align": "center", "valign": "middle", "fit": fit,
            "min_pt": max(MIN_PRESS_PT, min_font_pt),
            "max_scale": (max_font_pt / font_size_pt) if (max_font_pt and fit == "fill") else 6.0,
        }
        fill = await _color(backend, fill_color) or "White"
        ring = await _color(backend, ring_color) or "Black"
        script = AD_LIB + f"""
import scribus as _s
_d, _h, _x, _y = {diameter_mm}, {h}, {x_mm}, {y_mm}
_ring_pt = {0.0 if ring_style == 'none' else ring_width_pt}
_disc = _s.createEllipse(_x, _y, _d, _h)
_s.setFillColor({fill!r}, _disc)
if _ring_pt > 0:
    _s.setLineColor({ring!r}, _disc)
    _s.setLineWidth(_ring_pt, _disc)
    _style = {ring_style!r}
    if _style == 'dashed':
        _s.setLineStyle(_s.LINE_DASH, _disc)
    elif _style == 'dotted':
        _s.setLineStyle(_s.LINE_DOT, _disc)
        _s.setLineCap(_s.CAP_ROUND, _disc)
else:
    _s.setLineColor('None', _disc)
_parts = [_disc]
if {ring_style!r} == 'double' and _ring_pt > 0:
    _g = _ring_pt / {MM_TO_PT} * 1.9
    _in = _s.createEllipse(_x + _g, _y + _g, _d - 2 * _g, _h - 2 * _g)
    _s.setFillColor('None', _in)
    _s.setLineColor({ring!r}, _in)
    _s.setLineWidth(max(0.75, _ring_pt / 3.0), _in)
    _parts.append(_in)
_t, _scale = _ad_box({tspec!r})
_parts.append(_t)
_grp = None
if {name!r}:
    try:
        _s.setItemName({name!r}, _disc)
        _disc = {name!r}
        _parts[0] = _disc
    except Exception:
        pass
if {group!r}:
    try:
        _grp = _s.groupObjects(_parts)
    except Exception:
        _grp = None
_value = {{"group": _grp, "parts": _parts, "disc": _disc, "text": _t, "font_scale": round(_scale, 3),
          "overflows": _ad_overflow(_t), "warnings": _AD_WARN}}
"""
        res = await backend.script(script, result_expr="_value")
        if not res.ok:
            return _fail(res, "create_badge")
        return {"ok": True, **(res.value or {}), "error": None}

    @mcp.tool()
    async def create_bullet_list(
        items: list[str],
        x_mm: float,
        y_mm: float,
        width_mm: float,
        height_mm: float,
        columns: Annotated[int, Field(ge=1, le=3)] = 1,
        column_split: list[int] | None = None,
        column_gap_mm: float = 4.0,
        bullet: Literal["diamond", "square", "circle", "triangle", "dash"] = "diamond",
        bullet_color: str = "#E8281E",
        text_color: str = "Black",
        font: str | None = None,
        font_size_pt: float = 10.0,
        fit: Fit = "shrink",
        min_font_pt: float = 5.0,
        max_font_pt: float | None = None,
        item_gap_ratio: float = 0.35,
        leading_ratio: float = 1.18,
        indent_mm: float | None = None,
        hindi: Literal["auto", "unicode"] = "auto",
        group: bool = False,
        mode: Mode = "auto",
    ) -> dict:
        """Bulleted list with vector bullets (diamond / square / circle / triangle / dash),
        hanging indent, optional 1-3 columns and automatic font fitting.

        One text frame per item (so every item wraps independently under its bullet), stacked
        top-down inside the box (x, y, width, height). ``fit="shrink"`` (default) lowers the
        font until all items fit the height; ``fit="fill"`` raises it to the largest size that
        fits (``max_font_pt`` caps). ``column_split`` gives items per column, e.g. ``[9, 6]``;
        without it items flow into the next column when the height is used up. Bullets are
        real shapes in ``bullet_color``, so no missing-glyph boxes and no tab-stop problems. Not grouped by default (grouped
        objects cannot be addressed by name, so their text could not be edited or verified).
        Items may be Hindi (auto-converted to Kruti Dev). Returns ``group``, ``frames``,
        ``bullets``, the applied ``font_pt`` and whether everything ``fits``.
        """
        if not items:
            return {"ok": False, "error": "items must not be empty"}
        backend = await get_backend(ctx, mode)
        tcolor = await _color(backend, text_color) or "Black"
        bcolor = await _color(backend, bullet_color) or "Black"
        parts = []
        for it in items:
            full, spans, _ = build_rich_text(
                clean_user_text(it), None, font=font, size_pt=font_size_pt, color=tcolor,
                hindi=hindi,
            )
            parts.append({"text": full, "spans": spans})
        spec = {
            "items": parts, "x": x_mm, "y": y_mm, "w": width_mm, "h": height_mm,
            "columns": columns, "split": column_split, "gap": column_gap_mm,
            "bullet": bullet, "bullet_color": bcolor, "fit": fit,
            "min_pt": max(MIN_PRESS_PT, min_font_pt), "base_pt": font_size_pt,
            "max_scale": (max_font_pt / font_size_pt) if (max_font_pt and fit == "fill") else 6.0,
            "item_gap": item_gap_ratio, "lead": leading_ratio, "indent": indent_mm,
            "group": group,
        }
        script = AD_LIB + _BULLET_LIB + f"""
import scribus as _s
_value = _ad_bullet_list({spec!r})
_value['warnings'] = _AD_WARN
"""
        res = await backend.script(script, result_expr="_value")
        if not res.ok:
            return _fail(res, "create_bullet_list")
        return {"ok": True, **(res.value or {}), "error": None}

    @mcp.tool()
    async def create_label_bar(
        label: str,
        text: str,
        x_mm: float,
        y_mm: float,
        width_mm: float,
        height_mm: float,
        label_width_mm: float | None = None,
        label_fill: str = "#E8281E",
        label_text_color: str = "#FFFFFF",
        bar_fill: str = "#FFFFFF",
        text_color: str = "#1F2A44",
        border_color: str | None = None,
        border_width_pt: float = 0.0,
        font: str | None = None,
        font_size_pt: float = 10.0,
        align: Align = "left",
        shape: Literal["rect", "rounded", "pill"] = "pill",
        hindi: Literal["auto", "unicode"] = "auto",
        group: bool = False,
        mode: Mode = "auto",
    ) -> dict:
        """A bar with a coloured label chip on the left and text on the right.

        Use for the "NOTE: Fees of any kind once paid ..." line, "Call:" bars, "Venue:" bars.
        Builds a pill/rounded background, a chip (``label``) and a fitted text frame, aligned.
        Returns the three object names.
        """
        backend = await get_backend(ctx, mode)
        lw = label_width_mm or max(height_mm * 2.2, 16.0)
        pad = height_mm * 0.12
        bg = await create_text_box(
            x_mm, y_mm, width_mm, height_mm, text=" ", shape=shape,
            corner_radius_mm=height_mm / 3, fill_color=bar_fill, border_color=border_color,
            border_width_pt=border_width_pt, font_size_pt=font_size_pt, fit="none",
            name="", mode=mode,
        )
        if not bg.get("ok"):
            return bg
        chip = await create_text_box(
            x_mm + pad, y_mm + pad, lw, height_mm - 2 * pad, text=label,
            shape="pill" if shape == "pill" else shape, corner_radius_mm=height_mm / 3,
            fill_color=label_fill, text_color=label_text_color, font=font,
            font_size_pt=font_size_pt * 1.2, fit="shrink", hindi=hindi, padding_mm=0.8,
            mode=mode,
        )
        if not chip.get("ok"):
            return chip
        body = await create_text_box(
            x_mm + pad * 2 + lw, y_mm + pad, width_mm - lw - pad * 3, height_mm - 2 * pad,
            text=text, shape="rect", text_color=text_color, font=font,
            font_size_pt=font_size_pt, align=align, fit="shrink", no_wrap=False,
            hindi=hindi, padding_mm=1.0, mode=mode,
        )
        if not body.get("ok"):
            return body
        names = [bg["name"], chip["name"], body["name"]]
        grp = None
        if group:
            grp = await backend.script(
                f"import scribus as _s\ntry:\n    _value = _s.groupObjects({names!r})\n"
                "except Exception:\n    _value = None\n",
                result_expr="_value",
            )
        return {
            "ok": True, "group": grp.value if (grp and grp.ok) else None, "background": names[0],
            "label": names[1], "text": names[2],
            "overflows": bool(chip.get("overflows") or body.get("overflows")),
            "warnings": (chip.get("warnings") or []) + (body.get("warnings") or []),
            "error": None,
        }

    @mcp.tool()
    async def fit_text_to_frame(
        name: str,
        mode_fit: Literal["shrink", "fill"] = "shrink",
        min_font_pt: float = 5.0,
        max_font_pt: float | None = None,
        no_wrap: bool = False,
        mode: Mode = "auto",
    ) -> dict:
        """Fit the text of an existing frame into the frame by changing font sizes only.

        ``shrink`` lowers sizes until nothing overflows; ``fill`` also raises them to the
        largest size that fits (``max_font_pt`` caps). Relative sizes of mixed-size text are
        kept. Also switches the frame to automatic leading. ``no_wrap`` keeps every paragraph
        on one line. Never goes below ``min_font_pt`` (>= 5).
        """
        backend = await get_backend(ctx, mode)
        script = AD_LIB + f"""
import scribus as _s
_f = {name!r}
_n = _s.getTextLength(_f)
_spans = []
_i = 0
while _i < _n:
    _s.selectText(_i, 1, _f)
    _sz = _s.getFontSize(_f)
    _j = _i + 1
    while _j < _n:
        _s.selectText(_j, 1, _f)
        if abs(_s.getFontSize(_f) - _sz) > 0.01:
            break
        _j += 1
    _spans.append({{'start': _i, 'len': _j - _i, 'size': _sz}})
    _i = _j
_s.selectText(0, 0, _f)
_s.setLineSpacingMode(1, _f)
_text = _s.getAllText(_f)
_maxsz = max([_sp['size'] for _sp in _spans] or [10.0])
_cap = {max_font_pt if max_font_pt else 'None'}
_ms = (_cap / _maxsz) if (_cap and {mode_fit!r} == 'fill') else 6.0
_scale = _ad_fit(_f, _spans, {mode_fit!r}, {max(MIN_PRESS_PT, min_font_pt)}, _ms, {no_wrap!r}, _text.count(chr(10)) + 1)
_value = {{"name": _f, "font_scale": round(_scale, 3), "overflows": _ad_overflow(_f),
          "lines": _ad_lines(_f), "max_font_pt": round(_maxsz * _scale, 2)}}
"""
        res = await backend.script(script, result_expr="_value")
        if not res.ok:
            return _fail(res, "fit_text_to_frame")
        return {"ok": True, **(res.value or {}), "error": None}


# Script-side bullet-list builder -----------------------------------------------------------

_BULLET_LIB = r'''
def _ad_bullet_shape(_kind, _cx, _cy, _d, _color):
    import scribus as __s
    _r = _d / 2.0
    if _kind == 'circle':
        _o = __s.createEllipse(_cx - _r, _cy - _r, _d, _d)
    elif _kind == 'square':
        _o = __s.createRect(_cx - _r * 0.85, _cy - _r * 0.85, _d * 0.85, _d * 0.85)
    elif _kind == 'triangle':
        _o = __s.createPolygon([_cx - _r * 0.7, _cy - _r, _cx + _r * 0.9, _cy, _cx - _r * 0.7, _cy + _r])
    elif _kind == 'dash':
        _o = __s.createRect(_cx - _r, _cy - _r * 0.18, _d, _r * 0.36)
    else:
        _o = __s.createPolygon([_cx, _cy - _r * 1.1, _cx + _r * 0.85, _cy, _cx, _cy + _r * 1.1, _cx - _r * 0.85, _cy])
    __s.setFillColor(_color, _o)
    __s.setLineColor('None', _o)
    return _o

def _ad_bullet_list(_sp):
    import scribus as __s
    _MM = 72.0 / 25.4
    _items = _sp['items']
    _cols = _sp['columns']
    _cw = (_sp['w'] - (_cols - 1) * _sp['gap']) / _cols
    _frames = []
    for _it in _items:
        _f = __s.createText(_sp['x'], _sp['y'], _cw, 200.0)
        __s.setText(_it['text'], _f)
        __s.setFillColor('None', _f)
        __s.setLineColor('None', _f)
        __s.setLineWidth(0, _f)
        __s.setTextAlignment(0, _f)
        __s.setTextVerticalAlignment(0, _f)
        __s.setLineSpacingMode(0, _f)
        _frames.append(_f)
    _indent = _sp['indent'] if _sp['indent'] else None

    def _layout(_sc):
        _sz = max(_sp['min_pt'], round(_sp['base_pt'] * _sc * 4) / 4.0)
        _ind_mm = _indent if _indent else _sz * 0.95 / _MM
        _lead = _sz * _sp['lead']
        _heights = []
        for _f, _it in zip(_frames, _items):
            __s.sizeObject(_cw, 200.0, _f)
            __s.setTextDistances(_ind_mm, 0, 0, 0, _f)
            _ad_style(_f, _it['spans'], _sc, _sp['min_pt'])
            __s.setLineSpacing(_lead, _f)
            _n = max(1, _ad_lines(_f))
            _heights.append((_n * _lead + _lead * 0.12) / _MM)
        _gap = _sz * _sp['item_gap'] / _MM
        # assign to columns
        _cols_items = [[] for _ in range(_cols)]
        _used = [0.0] * _cols
        _fits = True
        if _sp['split']:
            _k = 0
            for _c in range(_cols):
                _cnt = _sp['split'][_c] if _c < len(_sp['split']) else 0
                for _i in range(_k, min(_k + _cnt, len(_items))):
                    _cols_items[_c].append(_i)
                _k += _cnt
            for _i in range(_k, len(_items)):
                _cols_items[_cols - 1].append(_i)
        else:
            _c = 0
            for _i, _hh in enumerate(_heights):
                _need = _hh + (_gap if _cols_items[_c] else 0)
                if _used[_c] + _need > _sp['h'] and _cols_items[_c] and _c < _cols - 1:
                    _c += 1
                    _need = _hh
                _cols_items[_c].append(_i)
                _used[_c] += _need
        for _c in range(_cols):
            _tot = sum(_heights[_i] for _i in _cols_items[_c]) + _gap * max(0, len(_cols_items[_c]) - 1)
            _used[_c] = _tot
            if _tot > _sp['h'] + 0.01:
                _fits = False
        return _fits, _heights, _cols_items, _gap, _sz, _ind_mm, _lead

    _hi = _sp['max_scale'] if _sp['fit'] == 'fill' else 1.0
    _scale = _hi
    _res = _layout(_scale)
    if _sp['fit'] != 'none' and not _res[0]:
        _lo = 0.05
        for _i in range(14):
            _mid = (_lo + _hi) / 2.0
            if _layout(_mid)[0]:
                _lo = _mid
            else:
                _hi = _mid
        _scale = _lo
        _res = _layout(_scale)
    elif _sp['fit'] == 'none':
        _scale = 1.0
        _res = _layout(1.0)
    _fits, _heights, _cols_items, _gap, _sz, _ind_mm, _lead = _res
    _bullets = []
    _bd = _sz * 0.62 / _MM
    for _c in range(_cols):
        _yy = _sp['y']
        _xx = _sp['x'] + _c * (_cw + _sp['gap'])
        for _i in _cols_items[_c]:
            _f = _frames[_i]
            __s.moveObjectAbs(_xx, _yy, _f)
            __s.sizeObject(_cw, _heights[_i], _f)
            _cy = _yy + _sz * 0.64 / _MM
            _bullets.append(_ad_bullet_shape(_sp['bullet'], _xx + _ind_mm * 0.38, _cy - _sz * 0.06 / _MM, _bd, _sp['bullet_color']))
            _yy += _heights[_i] + _gap
    _grp = None
    if _sp['group']:
        try:
            _grp = __s.groupObjects(_frames + _bullets)
        except Exception:
            _grp = None
    _over = any(_ad_overflow(_f) for _f in _frames)
    return {'group': _grp, 'frames': _frames, 'bullets': _bullets, 'font_pt': _sz,
            'fits': bool(_fits and not _over), 'columns_used': sum(1 for _c in _cols_items if _c),
            'used_height_mm': round(max(sum(_heights[_i] for _i in _c) + _gap * max(0, len(_c) - 1) for _c in _cols_items), 2)}
'''
