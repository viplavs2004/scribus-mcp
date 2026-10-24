"""Decorative vector shapes for flyers and ads: swooshes, leaves, brush bands, stars, bursts...

Scribus's Scripter only draws straight-sided polygons. These tools build a smooth SVG path,
hand it to Scribus's own SVG importer (``placeSVG``), then resize / recolour / rotate the
resulting polygon so it is a normal, editable Scribus object.
"""

from __future__ import annotations

import math
import uuid
from typing import Literal

from scribus_mcp.tools._adlib import AD_LIB
from scribus_mcp.tools._common import Mode, ServerCtx, get_backend
from scribus_mcp.tools.ad_boxes import _color

Kind = Literal[
    "swoosh", "leaf", "brush", "star", "burst", "diamond", "triangle", "chevron", "ribbon",
    "wave", "arc_band", "leaf_fan", "custom",
]


def _star_path(points: int, inner: float) -> str:
    pts = []
    for i in range(points * 2):
        r = 50.0 if i % 2 == 0 else 50.0 * inner
        a = -math.pi / 2 + i * math.pi / points
        pts.append((50 + r * math.cos(a), 50 + r * math.sin(a)))
    return "M" + " L".join(f"{x:.2f} {y:.2f}" for x, y in pts) + " Z"


# Paths are drawn in a 100 x 100 box and stretched to the requested width/height.
SHAPE_PATHS: dict[str, str] = {
    "swoosh": "M0 100 C 15 30, 60 0, 100 8 C 62 22, 30 55, 0 100 Z",
    "petal": "M50 100 C 2 72, 8 22, 50 0 C 92 22, 98 72, 50 100 Z",
    "leaf": "M0 100 C 0 45, 40 0, 100 0 C 100 60, 60 100, 0 100 Z",
    "brush": (
        "M2 18 L9 4 L22 10 L38 0 L55 7 L72 1 L88 8 L100 2 L96 24 L100 42 L95 60 L100 80 "
        "L90 100 L74 92 L58 100 L40 93 L24 100 L10 92 L0 100 L5 78 L0 58 L6 40 Z"
    ),
    "star": _star_path(5, 0.42),
    "burst": _star_path(18, 0.86),
    "diamond": "M50 0 L100 50 L50 100 L0 50 Z",
    "triangle": "M50 0 L100 100 L0 100 Z",
    "chevron": "M0 0 L70 0 L100 50 L70 100 L0 100 L30 50 Z",
    "ribbon": "M0 12 L100 12 L100 88 L0 88 L10 50 Z",
    "wave": "M0 20 C 25 -10, 50 50, 100 15 L100 85 C 50 120, 25 60, 0 90 Z",
    "arc_band": "M0 70 Q 50 -25 100 45 L100 100 L0 100 Z",
}

_PLACE_LIB = r'''
def _ad_import_svg(_path, _x, _y, _w, _h, _fill, _line, _line_w, _name):
    import scribus as __s
    _before = set(__s.getAllObjects())
    __s.placeSVG(_path, _x, _y)
    _new = [n for n in __s.getAllObjects() if n not in _before]
    if not _new:
        raise RuntimeError('SVG import created no object')
    _o = _new[0]
    if len(_new) > 1 or __s.getObjectType(_o) == 'Group':
        raise RuntimeError('SVG import produced a group; use a single path')
    __s.sizeObject(_w, _h, _o)
    __s.moveObjectAbs(_x, _y, _o)
    if _fill:
        __s.setFillColor(_fill, _o)
    if _line:
        __s.setLineColor(_line, _o)
        __s.setLineWidth(_line_w, _o)
    else:
        __s.setLineColor('None', _o)
    if _name:
        __s.setItemName(_name, _o)
        _o = _name
    return _o

def _ad_rotate_about(_o, _cx, _cy, _deg):
    import scribus as __s
    if abs(_deg) >= 0.01:
        __s.rotateObject(-_deg, _o)
    _bb = __s.getBoundingBox(_o)
    __s.moveObject(_cx - (_bb[0] + _bb[2] / 2.0), _cy - (_bb[1] + _bb[3] / 2.0), _o)
'''


def register(mcp, ctx: ServerCtx) -> None:
    @mcp.tool()
    async def create_decor_shape(
        kind: Kind,
        x_mm: float,
        y_mm: float,
        width_mm: float,
        height_mm: float,
        fill_color: str = "#E8281E",
        border_color: str | None = None,
        border_width_pt: float = 0.0,
        rotation_deg: float = 0.0,
        flip_horizontal: bool = False,
        colors: list[str] | None = None,
        path_d: str = "",
        name: str = "",
        mode: Mode = "auto",
    ) -> dict:
        """Decorative vector shape: swoosh, leaf, brush (ragged banner background), star,
        burst (seal), diamond, triangle, chevron, ribbon, wave, arc_band, leaf_fan, custom.

        The shape is stretched to the (x, y, width, height) box, filled with ``fill_color``
        (``#RRGGBB`` fine) and optionally rotated about its centre (positive = clockwise).
        ``kind="leaf_fan"`` draws a fan of leaves in the given ``colors`` (default red,
        orange, green, blue) rising from the bottom centre of the box, like the colourful
        swooshes on school/ad flyers. ``kind="custom"`` takes an SVG path in ``path_d``
        drawn in a 0-100 box (M, L, C, Q, Z commands).
        Returns the object name (``names`` for leaf_fan). Put brush/arc shapes BEHIND text:
        create them first, or lower them with the layer tools.
        """
        backend = await get_backend(ctx, mode)
        fill = await _color(backend, fill_color) or "Black"
        line = await _color(backend, border_color)
        if kind == "custom" and not path_d.strip():
            return {"ok": False, "error": "kind='custom' needs path_d"}
        if kind == "leaf_fan":
            cols = colors or ["#E8281E", "#F58220", "#1A9A3A", "#1F4E9E"]
            rcols = [await _color(backend, c) or "Black" for c in cols]
            paths = [SHAPE_PATHS["petal"]] * len(rcols)
        else:
            rcols = [fill]
            paths = [path_d.strip() if kind == "custom" else SHAPE_PATHS[kind]]

        flip = ""
        files = []
        for p in paths:
            f = ctx.config.workdir / f"decor-{uuid.uuid4().hex}.svg"
            f.write_text(
                "<svg xmlns='http://www.w3.org/2000/svg' width='100' height='100' "
                f"viewBox='0 0 100 100'><path d='{p}' fill='#000000'{flip}/></svg>",
                encoding="utf-8",
            )
            files.append(str(f))
        script = AD_LIB + _PLACE_LIB + f"""
import scribus as _s, os
_files = {files!r}
_cols = {rcols!r}
_names = []
_fan = {kind == 'leaf_fan'!r}
_x, _y, _w, _h = {x_mm}, {y_mm}, {width_mm}, {height_mm}
try:
    if not _fan:
        _o = _ad_import_svg(_files[0], _x, _y, _w, _h, _cols[0], {line!r}, {border_width_pt}, {name!r} or None)
        if {flip_horizontal!r}:
            _s.flipObject(1, 0, _o)
        _ad_rotate_about(_o, _x + _w / 2.0, _y + _h / 2.0, {rotation_deg})
        _names.append(_o)
    else:
        _n = len(_files)
        _lw = min(_h * 0.42, _w * 0.5)
        _lh = _h
        _px, _py = _x + _w / 2.0, _y + _h
        for _i in range(_n):
            _ang = (-1 + 2.0 * _i / max(1, _n - 1)) * 52.0 * (-1 if {flip_horizontal!r} else 1) if _n > 1 else 0.0
            _o = _ad_import_svg(_files[_i], _px, _py - _lh, _lw, _lh, _cols[_i], None, 0, None)
            import math as _m
            _r = _lh / 2.0
            _cx = _px + _r * _m.sin(_m.radians(_ang))
            _cy = _py - _r * _m.cos(_m.radians(_ang))
            _ad_rotate_about(_o, _cx, _cy, _ang)
            _names.append(_o)
finally:
    for _f in _files:
        try:
            os.remove(_f)
        except Exception:
            pass
_value = {{"names": _names}}
"""
        res = await backend.script(script, result_expr="_value")
        if not res.ok:
            return {"ok": False, "error": res.error or "create_decor_shape failed"}
        names = (res.value or {}).get("names", [])
        return {"ok": True, "name": names[0] if names else None, "names": names, "error": None}
