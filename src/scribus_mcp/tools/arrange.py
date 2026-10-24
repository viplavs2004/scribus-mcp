"""Alignment and distribution helpers (the Align palette of Scribus, for agents)."""

from __future__ import annotations

from typing import Literal

from scribus_mcp.tools._common import Mode, ServerCtx, get_backend

Align = Literal["left", "center", "right", "top", "middle", "bottom"]


def register(mcp, ctx: ServerCtx) -> None:
    @mcp.tool()
    async def align_objects(
        names: list[str],
        align: Align,
        to: Literal["page", "margins", "first", "bounds"] = "page",
        mode: Mode = "auto",
    ) -> dict:
        """Align objects on one edge or centre line. ``to``: "page" (page edges), "margins"
        (page margins), "first" (the first name in ``names`` stays put) or "bounds" (the
        bounding box of all the named objects). left/center/right move horizontally,
        top/middle/bottom vertically. Uses the visual bounding box (rotation included).
        """
        backend = await get_backend(ctx, mode)
        body = f"""
import scribus as _s
_names = {names!r}
_u = 1.0  # everything in document units (mm)
_pw, _ph = _s.getPageSize()
_boxes = {{n: _s.getBoundingBox(n) for n in _names}}
_to = {to!r}
if _to == 'page':
    _L, _T, _R, _B = 0.0, 0.0, _pw, _ph
elif _to == 'margins':
    _mt, _ml, _mr, _mb = _s.getPageMargins() if hasattr(_s, 'getPageMargins') else (0, 0, 0, 0)
    _L, _T, _R, _B = _ml * _u, _mt * _u, _pw - _mr * _u, _ph - _mb * _u
elif _to == 'first':
    _b = _boxes[_names[0]]
    _L, _T, _R, _B = _b[0], _b[1], _b[0] + _b[2], _b[1] + _b[3]
else:
    _L = min(b[0] for b in _boxes.values()); _T = min(b[1] for b in _boxes.values())
    _R = max(b[0] + b[2] for b in _boxes.values()); _B = max(b[1] + b[3] for b in _boxes.values())
_a = {align!r}
for _n in _names:
    _x, _y, _w, _h = _boxes[_n]
    _dx = _dy = 0.0
    if _a == 'left': _dx = _L - _x
    elif _a == 'right': _dx = _R - (_x + _w)
    elif _a == 'center': _dx = (_L + _R) / 2.0 - (_x + _w / 2.0)
    elif _a == 'top': _dy = _T - _y
    elif _a == 'bottom': _dy = _B - (_y + _h)
    elif _a == 'middle': _dy = (_T + _B) / 2.0 - (_y + _h / 2.0)
    if _dx or _dy:
        _s.moveObject(_dx, _dy, _n)
_value = {{n: [round(v, 2) for v in _s.getBoundingBox(n)] for n in _names}}
"""
        res = await backend.script(body, result_expr="_value")
        return {"ok": res.ok, "boxes_mm": res.value, "error": res.error}

    @mcp.tool()
    async def distribute_objects(
        names: list[str],
        axis: Literal["horizontal", "vertical"] = "horizontal",
        gap_mm: float | None = None,
        mode: Mode = "auto",
    ) -> dict:
        """Space objects evenly along an axis. With ``gap_mm`` every gap is exactly that and
        the first object stays put; without it the first and last stay put and the rest are
        spread so all gaps are equal. Objects are ordered by their current position.
        """
        backend = await get_backend(ctx, mode)
        body = f"""
import scribus as _s
_horiz = {axis == 'horizontal'!r}
_gap = {gap_mm!r}
_items = []
for _n in {names!r}:
    _b = _s.getBoundingBox(_n)
    _items.append((_b[0] if _horiz else _b[1], _n, _b))
_items.sort()
_k = 2 if _horiz else 3
_p = 0 if _horiz else 1
if _gap is None and len(_items) > 2:
    _first, _last = _items[0][2], _items[-1][2]
    _total = (_last[_p] + _last[_k]) - _first[_p]
    _sizes = sum(i[2][_k] for i in _items)
    _gap = (_total - _sizes) / (len(_items) - 1)
elif _gap is None:
    _gap = 0.0
_cur = _items[0][2][_p] + _items[0][2][_k] + _gap
for _pos, _n, _b in _items[1:]:
    _d = _cur - _b[_p]
    _s.moveObject(_d if _horiz else 0.0, 0.0 if _horiz else _d, _n)
    _cur += _b[_k] + _gap
_value = {{'gap_mm': round(_gap, 2)}}
"""
        res = await backend.script(body, result_expr="_value")
        return {"ok": res.ok, "value": res.value, "error": res.error}
