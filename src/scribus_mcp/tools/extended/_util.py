"""Shared helpers for the extended Scripter wrappers."""

from __future__ import annotations

from scribus_mcp.backends.base import ScribusResult
from scribus_mcp.tools._common import Mode, ServerCtx, get_backend
from scribus_mcp.tools.styling import LINE_STYLES

MM = (
    "import scribus as _s\n"
    "try:\n"
    "    _s.setUnit(_s.UNIT_MILLIMETERS)\n"
    "except Exception:\n"
    "    pass\n"
)

# Scribus 1.7.4 blend-mode constants (scribus.NORMAL … scribus.LUMINOSITY).
BLEND_MODES = {
    "normal": 0,
    "darken": 1,
    "lighten": 2,
    "multiply": 3,
    "screen": 4,
    "overlay": 5,
    "hard_light": 6,
    "soft_light": 7,
    "difference": 8,
    "exclusion": 9,
    "color_dodge": 10,
    "color_burn": 11,
    "hue": 12,
    "saturation": 13,
    "color": 14,
    "luminosity": 15,
}
BLEND_NAMES = {value: name for name, value in BLEND_MODES.items()}

LINE_STYLE_NAMES = {value: name for name, value in LINE_STYLES.items()}
LINE_CAP_NAMES = {0: "flat", 32: "round", 16: "square"}
LINE_JOIN_NAMES = {0: "miter", 128: "round", 64: "bevel"}


def fail(error: str) -> dict:
    return {"ok": False, "error": error}


def ok(result: ScribusResult, **fields) -> dict:
    if not result.ok:
        return {"ok": False, "error": result.error}
    if not fields:
        return {"ok": True, "value": result.value, "error": None}
    return {"ok": True, "error": None, **fields}


async def run(ctx: ServerCtx, mode: Mode, body: str) -> ScribusResult:
    backend = await get_backend(ctx, mode)
    if not body.endswith("\n"):
        body += "\n"
    return await backend.script(body, result_expr="_value")


def mm(body: str) -> str:
    return MM + body


def blend_code(name: str) -> int | None:
    return BLEND_MODES.get(name)


def blend_label(code) -> str:
    try:
        return BLEND_NAMES.get(int(code), str(code))
    except (TypeError, ValueError):
        return str(code)


def border_lines(lines: list[dict]) -> list[tuple]:
    """Turn ``[{width, style, color}]`` into Scribus ``(width, LINE_*, color)`` tuples."""
    if not lines:
        raise ValueError("lines must contain at least one border")
    out = []
    for line in lines:
        style = str(line.get("style", "solid"))
        if style not in LINE_STYLES:
            raise ValueError(f"style must be one of {sorted(LINE_STYLES)}")
        if "width" not in line:
            raise ValueError("each line needs a width (points)")
        out.append((float(line["width"]), LINE_STYLES[style], str(line.get("color", "Black"))))
    return out
