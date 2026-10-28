"""Document palette — semantic role names that resolve to Scribus colors.

The Scribus document palette (visible in *Edit → Colors and Fills*) is the
canonical place to keep brand colors. This module layers a thin
"semantic role" convention on top:

    primary    — brand main color (cover band, big titles, dominant accents)
    accent     — secondary highlight (eyebrows, KPI values, marker fills)
    surface    — light fill for cards / callouts / table backgrounds
    ink        — body text and dark elements
    muted      — de-emphasised text, subtle borders, axis lines, dividers
    warning    — warning / danger emphasis
    success    — success / positive emphasis
    subtle     — even-quieter borders / hairlines

The LLM driving the MCP defines those colors once with
``define_color_rgb("primary", 88, 23, 128)`` etc. Every later tool whose
default color is a role name will pick the resolved palette color. If a
role isn't defined, the resolver falls back to ``"Black"`` so old
behavior is preserved when the LLM never sets a palette.

Tools combine a color with a shade (Scribus's "tint toward white").
Conventional fallbacks keep e.g. card backgrounds at *Black @ 8%* (a
faint grey). When the role is defined, the resolver flips the shade to
100 — the LLM picked the exact color it wants drawn, so applying the
conventional 8% tint would wash it out. Callers passing an explicit
shade always win.
"""

from __future__ import annotations

from scribus_mcp.backends.base import ScribusBackend

# Standard role names — the docs above and BEST_PRACTICES enumerate
# these. Tools default to one of them per color slot. Adding a new role
# is fine; pick a short lowercase identifier so it doesn't collide with
# Scribus's built-in CMYK swatch names (all of which are capitalised
# and longer).
ROLE_NAMES: frozenset[str] = frozenset(
    {
        "primary",
        "accent",
        "surface",
        "ink",
        "muted",
        "warning",
        "success",
        "subtle",
    }
)


_CSS_COLORS: dict[str, str] = {
    "white": "FFFFFF", "black": "000000", "red": "E8281E", "green": "1A9A3A",
    "blue": "1F4E9E", "yellow": "FFDE00", "orange": "F58220", "purple": "6A2C91",
    "pink": "E91E8C", "cyan": "00AEEF", "magenta": "EC008C", "gray": "808080",
    "grey": "808080", "navy": "0B2E6B", "maroon": "7B1E1E", "gold": "FFC20E",
    "brown": "7A4A21", "teal": "007C80", "lime": "8DC63F",
}


def parse_color_literal(spec: str) -> tuple[str, tuple[int, int, int]] | None:
    """Parse ``#RRGGBB`` / ``#RGB`` / a basic colour word.

    Returns ``(scribus_color_name, (r, g, b))`` or None when ``spec`` is not a literal.
    The colour is named ``#RRGGBB`` so repeated use reuses one swatch.
    """
    s = (spec or "").strip()
    if s.lower() in _CSS_COLORS:
        s = "#" + _CSS_COLORS[s.lower()]
    if not s.startswith("#"):
        return None
    h = s[1:]
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    if len(h) != 6:
        return None
    try:
        r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    except ValueError:
        return None
    return "#" + h.upper(), (r, g, b)


# Per-backend cache of "what color names exist in the open document".
# Keyed by ``id(backend)`` so headless and interactive backends keep
# separate caches. Populated lazily on first ``resolve_color`` call;
# mutated by ``add_known_color`` / ``invalidate_palette`` from the
# colors.py and document.py registration sites.
_palette_cache: dict[int, set[str] | None] = {}


async def known_colors(backend: ScribusBackend) -> set[str]:
    """Return the set of color names the open Scribus document knows about.

    Cached per backend instance — the cache is invalidated by
    ``invalidate_palette`` whenever a color is deleted or the document
    changes. ``define_color_*`` calls inject directly via
    ``add_known_color`` so the next ``resolve_color`` sees them without
    a re-probe.
    """
    cached = _palette_cache.get(id(backend))
    if cached is not None:
        return cached
    res = await backend.call("getColorNames")
    names = set(res.value or []) if res.ok else set()
    _palette_cache[id(backend)] = names
    return names


def add_known_color(backend: ScribusBackend, name: str) -> None:
    """Inject a freshly-defined color into the cache.

    Called from ``define_color_rgb`` / ``define_color_cmyk`` after
    success so subsequent resolves don't have to round-trip
    ``getColorNames`` again.
    """
    cached = _palette_cache.get(id(backend))
    if cached is not None and name:
        cached.add(name)


def invalidate_palette(backend: ScribusBackend | None = None) -> None:
    """Drop the cached color list for ``backend`` (or all backends).

    Document open / close / create and color deletion all change the
    set of valid color names; rather than maintain perfect deltas we
    just drop the cache and let the next ``known_colors`` reprobe.
    """
    if backend is None:
        _palette_cache.clear()
    else:
        _palette_cache.pop(id(backend), None)


async def resolve_color(
    backend: ScribusBackend,
    name: str | None,
    *,
    fallback_color: str = "Black",
    role_shade: int = 100,
    fallback_shade: int | None = None,
    current_shade: int | None = None,
) -> tuple[str, int | None]:
    """Resolve a possibly-role color name through the document palette.

    - If ``name`` is a string that names a real color in the open
      document (whether one of the standard roles like ``"primary"`` or
      a literal Scribus color like ``"Z Cyan"``), returns
      ``(name, current_shade if current_shade is not None else role_shade)``.
    - Otherwise returns
      ``(fallback_color, current_shade if current_shade is not None else fallback_shade)``.

    Tools pass ``current_shade`` straight from their caller-facing
    parameter. When that parameter defaults to ``None`` the resolver
    fills in either ``role_shade`` (palette mode — the role color is
    drawn as the LLM defined it) or ``fallback_shade`` (no palette —
    apply the conventional shade like *Black @ 8%* for card fills).
    """
    if not name:
        return fallback_color, current_shade if current_shade is not None else fallback_shade
    known = await known_colors(backend)
    if name not in known:
        literal = parse_color_literal(name)
        if literal is not None:
            # "#FFDE00", "#fd0" or a basic CSS name: define it on the fly instead of
            # silently falling back to Black (the old behaviour hid colour mistakes).
            r, g, b = literal[1]
            res = await backend.call("defineColorRGB", literal[0], r, g, b)
            if res.ok or "exist" in str(res.error or "").lower():
                add_known_color(backend, literal[0])
                return literal[0], current_shade if current_shade is not None else role_shade
    if name in known:
        return name, current_shade if current_shade is not None else role_shade
    return fallback_color, current_shade if current_shade is not None else fallback_shade


__all__ = [
    "ROLE_NAMES",
    "add_known_color",
    "invalidate_palette",
    "known_colors",
    "parse_color_literal",
    "resolve_color",
]
