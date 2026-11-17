"""Colors, paragraph and character styles, blend modes, and gradients."""

from __future__ import annotations

from scribus_mcp.tools._common import Mode, ServerCtx
from scribus_mcp.tools.extended._util import (
    BLEND_MODES,
    LINE_CAP_NAMES,
    LINE_JOIN_NAMES,
    LINE_STYLE_NAMES,
    blend_code,
    blend_label,
    fail,
    mm,
    ok,
    run,
)
from scribus_mcp.tools.palette import add_known_color, invalidate_palette
from scribus_mcp.tools.styling import LINE_CAPS, LINE_JOINS
from scribus_mcp.tools.text import ALIGN, LINE_SPACING_MODE

_DASH = {"solid": 1, "dash": 2, "dot": 3, "dashdot": 4, "dashdotdot": 5}


def register(mcp, ctx: ServerCtx) -> None:
    @mcp.tool()
    async def get_color(name: str, mode: Mode = "auto") -> dict:
        """Read a document color as CMYK percentages and as 0–255 RGB."""
        body = (
            "import scribus as _s\n"
            f"_cmyk = list(_s.getColorFloat({name!r}))\n"
            f"_rgb = list(_s.getColorAsRGB({name!r}))\n"
            "_value = {'cmyk': _cmyk, 'rgb': _rgb}\n"
        )
        result = await run(ctx, mode, body)
        if not result.ok or not isinstance(result.value, dict):
            return ok(result)
        cmyk = result.value.get("cmyk") or [None, None, None, None]
        rgb = result.value.get("rgb") or [None, None, None]
        return ok(
            result,
            cyan=cmyk[0],
            magenta=cmyk[1],
            yellow=cmyk[2],
            key=cmyk[3],
            red=rgb[0],
            green=rgb[1],
            blue=rgb[2],
        )

    @mcp.tool()
    async def define_color_lab(
        name: str, lightness: float, a: float, b: float, mode: Mode = "auto"
    ) -> dict:
        """Define a CIE Lab color. L is 0–100, a and b are -128–128."""
        if not name:
            return fail("name must not be empty")
        if not 0.0 <= lightness <= 100.0:
            return fail("lightness must be in [0, 100]")
        if not -128.0 <= a <= 128.0 or not -128.0 <= b <= 128.0:
            return fail("a and b must be in [-128, 128]")
        backend_result = await run(
            ctx,
            mode,
            "import scribus as _s\n"
            f"_value = _s.defineColorLab({name!r}, {lightness}, {a}, {b})\n",
        )
        if backend_result.ok:
            from scribus_mcp.tools._common import get_backend

            add_known_color(await get_backend(ctx, mode), name)
        return ok(backend_result)

    @mcp.tool()
    async def change_color_rgb(
        name: str, red: int, green: int, blue: int, mode: Mode = "auto"
    ) -> dict:
        """Replace the RGB components of an existing color. Each channel is 0–255."""
        for label, value in (("red", red), ("green", green), ("blue", blue)):
            if not 0 <= value <= 255:
                return fail(f"{label} must be in [0, 255]")
        result = await run(
            ctx,
            mode,
            "import scribus as _s\n"
            f"_value = _s.changeColorRGB({name!r}, {int(red)}, {int(green)}, {int(blue)})\n",
        )
        return ok(result)

    @mcp.tool()
    async def change_color_cmyk(
        name: str,
        cyan: float,
        magenta: float,
        yellow: float,
        key: float,
        mode: Mode = "auto",
    ) -> dict:
        """Replace the CMYK components of an existing color. Each channel is 0–100."""
        for label, value in (
            ("cyan", cyan),
            ("magenta", magenta),
            ("yellow", yellow),
            ("key", key),
        ):
            if not 0.0 <= value <= 100.0:
                return fail(f"{label} must be in [0, 100]")
        result = await run(
            ctx,
            mode,
            "import scribus as _s\n"
            f"_value = _s.changeColorCMYKFloat({name!r}, {cyan}, {magenta}, {yellow}, {key})\n",
        )
        return ok(result)

    @mcp.tool()
    async def replace_color(name: str, replace_with: str, mode: Mode = "auto") -> dict:
        """Substitute ``replace_with`` everywhere ``name`` is used. Both must already exist."""
        result = await run(
            ctx,
            mode,
            f"import scribus as _s\n_value = _s.replaceColor({name!r}, {replace_with!r})\n",
        )
        if result.ok:
            from scribus_mcp.tools._common import get_backend

            invalidate_palette(await get_backend(ctx, mode))
        return ok(result)

    @mcp.tool()
    async def set_spot_color(name: str, spot: bool = True, mode: Mode = "auto") -> dict:
        """Mark a color as a spot color, or turn that flag off."""
        result = await run(
            ctx,
            mode,
            f"import scribus as _s\n_value = _s.setSpotColor({name!r}, {bool(spot)})\n",
        )
        return ok(result)

    @mcp.tool()
    async def is_spot_color(name: str, mode: Mode = "auto") -> dict:
        """Return whether a color is a spot color."""
        result = await run(
            ctx, mode, f"import scribus as _s\n_value = bool(_s.isSpotColor({name!r}))\n"
        )
        return ok(result, spot=result.value if result.ok else None)

    @mcp.tool()
    async def create_paragraph_style(
        name: str,
        alignment: str | None = None,
        line_spacing_mode: str | None = None,
        line_spacing_pt: float | None = None,
        left_margin: float | None = None,
        right_margin: float | None = None,
        gap_before: float | None = None,
        gap_after: float | None = None,
        first_indent: float | None = None,
        drop_cap: bool | None = None,
        drop_cap_lines: int | None = None,
        drop_cap_offset: float | None = None,
        character_style: str | None = None,
        bullet: str | None = None,
        mode: Mode = "auto",
    ) -> dict:
        """Create a paragraph style. Omitted options are left to Scribus.

        Distances (margins, gaps, indent, leading) are in points, which is
        how the style manager stores them. ``alignment`` is left, center,
        right, justify, or forced. ``line_spacing_mode`` is fixed, automatic,
        or baseline.
        """
        if not name:
            return fail("name must not be empty")
        kwargs: dict = {"name": name}
        if alignment is not None:
            if alignment not in ALIGN:
                return fail(f"alignment must be one of {sorted(ALIGN)}")
            kwargs["alignment"] = ALIGN[alignment]
        if line_spacing_mode is not None:
            if line_spacing_mode not in LINE_SPACING_MODE:
                return fail(f"line_spacing_mode must be one of {sorted(LINE_SPACING_MODE)}")
            kwargs["linespacingmode"] = LINE_SPACING_MODE[line_spacing_mode]
        if line_spacing_pt is not None:
            kwargs["linespacing"] = float(line_spacing_pt)
        if left_margin is not None:
            kwargs["leftmargin"] = float(left_margin)
        if right_margin is not None:
            kwargs["rightmargin"] = float(right_margin)
        if gap_before is not None:
            kwargs["gapbefore"] = float(gap_before)
        if gap_after is not None:
            kwargs["gapafter"] = float(gap_after)
        if first_indent is not None:
            kwargs["firstindent"] = float(first_indent)
        if drop_cap is not None:
            kwargs["hasdropcap"] = 1 if drop_cap else 0
        if drop_cap_lines is not None:
            kwargs["dropcaplines"] = int(drop_cap_lines)
        if drop_cap_offset is not None:
            kwargs["dropcapoffset"] = float(drop_cap_offset)
        if character_style is not None:
            kwargs["charstyle"] = character_style
        if bullet is not None:
            kwargs["bullet"] = bullet
        parts = ", ".join(f"{key}={value!r}" for key, value in kwargs.items())
        result = await run(
            ctx, mode, f"import scribus as _s\n_value = _s.createParagraphStyle({parts})\n"
        )
        return ok(result)

    @mcp.tool()
    async def create_character_style(
        name: str,
        font: str | None = None,
        font_size_pt: float | None = None,
        features: list[str] | None = None,
        fill_color: str | None = None,
        fill_shade: float | None = None,
        stroke_color: str | None = None,
        stroke_shade: float | None = None,
        background_color: str | None = None,
        baseline_offset: float | None = None,
        tracking: float | None = None,
        scale_h: float | None = None,
        scale_v: float | None = None,
        mode: Mode = "auto",
    ) -> dict:
        """Create a character style. Omitted options are left to Scribus.

        ``features`` uses the same tokens as ``set_font_features`` (underline,
        smallcaps, italic, …) and is stored comma-separated with no spaces.
        """
        if not name:
            return fail("name must not be empty")
        kwargs: dict = {"name": name}
        if font is not None:
            kwargs["font"] = font
        if font_size_pt is not None:
            kwargs["fontsize"] = float(font_size_pt)
        if features is not None:
            if any(" " in part or "," in part for part in features):
                return fail("each feature is a single token with no spaces or commas")
            kwargs["features"] = ",".join(part.strip() for part in features if part.strip())
        if fill_color is not None:
            kwargs["fillcolor"] = fill_color
        if fill_shade is not None:
            kwargs["fillshade"] = float(fill_shade)
        if stroke_color is not None:
            kwargs["strokecolor"] = stroke_color
        if stroke_shade is not None:
            kwargs["strokeshade"] = float(stroke_shade)
        if background_color is not None:
            kwargs["bgcolor"] = background_color
        if baseline_offset is not None:
            kwargs["baselineoffset"] = float(baseline_offset)
        if tracking is not None:
            kwargs["tracking"] = float(tracking)
        if scale_h is not None:
            kwargs["scaleh"] = float(scale_h)
        if scale_v is not None:
            kwargs["scalev"] = float(scale_v)
        parts = ", ".join(f"{key}={value!r}" for key, value in kwargs.items())
        result = await run(
            ctx, mode, f"import scribus as _s\n_value = _s.createCharStyle({parts})\n"
        )
        return ok(result)

    @mcp.tool()
    async def get_applied_paragraph_style(name: str, mode: Mode = "auto") -> dict:
        """Return the paragraph style on a frame, or on the start of a text selection."""
        result = await run(
            ctx, mode, f"import scribus as _s\n_value = _s.getParagraphStyle({name!r})\n"
        )
        return ok(result, style=result.value if result.ok else None)

    @mcp.tool()
    async def get_applied_character_style(name: str, mode: Mode = "auto") -> dict:
        """Return the character style on a frame, or on the start of a text selection."""
        result = await run(
            ctx, mode, f"import scribus as _s\n_value = _s.getCharacterStyle({name!r})\n"
        )
        return ok(result, style=result.value if result.ok else None)

    @mcp.tool()
    async def remove_unused_styles(mode: Mode = "auto") -> dict:
        """Delete paragraph, character, table, cell, and line styles that nothing uses.

        Default styles are kept. Returns how many styles were removed.
        """
        result = await run(
            ctx, mode, "import scribus as _s\n_value = _s.removeUnusedStyles()\n"
        )
        return ok(result, removed=result.value if result.ok else None)

    @mcp.tool()
    async def list_line_styles(mode: Mode = "auto") -> dict:
        """List custom line-style names."""
        result = await run(
            ctx, mode, "import scribus as _s\n_value = list(_s.getLineStyles() or [])\n"
        )
        return ok(result, styles=result.value if result.ok else None)

    @mcp.tool()
    async def create_line_style(name: str, lines: list[dict], mode: Mode = "auto") -> dict:
        """Define a multi-stroke line style.

        Each entry may set color, width (points), dash (solid, dash, dot,
        dashdot, dashdotdot), cap (flat, round, square), and join (miter,
        round, bevel).
        """
        if not name:
            return fail("name must not be empty")
        if not lines:
            return fail("lines must contain at least one stroke")
        strokes = []
        for line in lines:
            stroke: dict = {}
            if "color" in line:
                stroke["Color"] = str(line["color"])
            if "width" in line:
                stroke["Width"] = float(line["width"])
            if "dash" in line:
                dash = str(line["dash"])
                if dash not in _DASH:
                    return fail(f"dash must be one of {sorted(_DASH)}")
                stroke["Dash"] = _DASH[dash]
            if "cap" in line:
                cap = str(line["cap"])
                if cap not in LINE_CAPS:
                    return fail(f"cap must be one of {sorted(LINE_CAPS)}")
                stroke["LineEnd"] = LINE_CAPS[cap]
            if "join" in line:
                join = str(line["join"])
                if join not in LINE_JOINS:
                    return fail(f"join must be one of {sorted(LINE_JOINS)}")
                stroke["LineJoin"] = LINE_JOINS[join]
            strokes.append(stroke)
        result = await run(
            ctx,
            mode,
            f"import scribus as _s\n_value = _s.createCustomLineStyle({name!r}, {strokes!r})\n",
        )
        return ok(result)

    @mcp.tool()
    async def set_custom_line_style(name: str, style: str, mode: Mode = "auto") -> dict:
        """Apply a named custom line style to an object."""
        result = await run(
            ctx,
            mode,
            f"import scribus as _s\n_value = _s.setCustomLineStyle({style!r}, {name!r})\n",
        )
        return ok(result)

    @mcp.tool()
    async def get_custom_line_style(name: str, mode: Mode = "auto") -> dict:
        """Return the custom line style name on an object, or an empty string."""
        result = await run(
            ctx, mode, f"import scribus as _s\n_value = _s.getCustomLineStyle({name!r}) or ''\n"
        )
        return ok(result, style=result.value if result.ok else None)

    @mcp.tool()
    async def set_fill_blend_mode(name: str, blend: str, mode: Mode = "auto") -> dict:
        """Set the fill blend mode.

        ``blend`` is normal, darken, lighten, multiply, screen, overlay,
        hard_light, soft_light, difference, exclusion, color_dodge,
        color_burn, hue, saturation, color, or luminosity.
        """
        code = blend_code(blend)
        if code is None:
            return fail(f"blend must be one of {sorted(BLEND_MODES)}")
        result = await run(
            ctx,
            mode,
            f"import scribus as _s\n_value = _s.setFillBlendmode({code}, {name!r})\n",
        )
        return ok(result)

    @mcp.tool()
    async def set_line_blend_mode(name: str, blend: str, mode: Mode = "auto") -> dict:
        """Set the stroke blend mode. Same names as ``set_fill_blend_mode``."""
        code = blend_code(blend)
        if code is None:
            return fail(f"blend must be one of {sorted(BLEND_MODES)}")
        result = await run(
            ctx,
            mode,
            f"import scribus as _s\n_value = _s.setLineBlendmode({code}, {name!r})\n",
        )
        return ok(result)

    @mcp.tool()
    async def get_fill_blend_mode(name: str, mode: Mode = "auto") -> dict:
        """Return the fill blend mode name."""
        result = await run(
            ctx, mode, f"import scribus as _s\n_value = _s.getFillBlendmode({name!r})\n"
        )
        if not result.ok:
            return ok(result)
        return ok(result, blend=blend_label(result.value))

    @mcp.tool()
    async def get_line_blend_mode(name: str, mode: Mode = "auto") -> dict:
        """Return the stroke blend mode name."""
        result = await run(
            ctx, mode, f"import scribus as _s\n_value = _s.getLineBlendmode({name!r})\n"
        )
        if not result.ok:
            return ok(result)
        return ok(result, blend=blend_label(result.value))

    @mcp.tool()
    async def set_gradient_stop(
        name: str,
        color: str,
        position: float,
        shade: int = 100,
        opacity: float = 1.0,
        mode: Mode = "auto",
    ) -> dict:
        """Add or replace a gradient stop. Call ``apply_gradient`` first so a gradient exists.

        ``position`` is 0–1 along the ramp. ``shade`` is 0–100. ``opacity`` is 0–1.
        """
        if not 0.0 <= position <= 1.0:
            return fail("position must be in [0, 1]")
        if not 0 <= shade <= 100:
            return fail("shade must be in [0, 100]")
        if not 0.0 <= opacity <= 1.0:
            return fail("opacity must be in [0, 1]")
        result = await run(
            ctx,
            mode,
            "import scribus as _s\n"
            f"_value = _s.setGradientStop({color!r}, {int(shade)}, {opacity}, {position}, {name!r})\n",
        )
        return ok(result)

    @mcp.tool()
    async def get_gradient_stops(name: str, mode: Mode = "auto") -> dict:
        """Return every gradient stop as ``{color, opacity, shade}``."""
        body = (
            "import scribus as _s\n"
            f"_n = int(_s.getGradientStopsCount({name!r}) or 0)\n"
            "_stops = []\n"
            "for _i in range(_n):\n"
            f"    _color, _opacity, _shade = _s.getGradientStop(_i, {name!r})\n"
            "    _stops.append({'color': _color, 'opacity': _opacity, 'shade': _shade})\n"
            "_value = _stops\n"
        )
        result = await run(ctx, mode, body)
        return ok(result, stops=result.value if result.ok else None)

    @mcp.tool()
    async def set_gradient_vector(
        name: str,
        start_x_mm: float,
        start_y_mm: float,
        end_x_mm: float,
        end_y_mm: float,
        mode: Mode = "auto",
    ) -> dict:
        """Place the gradient ramp from start to end, in millimetres, relative to the object."""
        result = await run(
            ctx,
            mode,
            mm(
                "_value = _s.setGradientVector("
                f"{start_x_mm}, {start_y_mm}, {end_x_mm}, {end_y_mm}, {name!r})\n"
            ),
        )
        return ok(result)

    @mcp.tool()
    async def get_gradient_vector(name: str, mode: Mode = "auto") -> dict:
        """Return the gradient ramp as start and end points in millimetres."""
        result = await run(
            ctx, mode, mm(f"_value = list(_s.getGradientVector({name!r}))\n")
        )
        if not result.ok or not isinstance(result.value, list) or len(result.value) < 4:
            return ok(result)
        sx, sy, ex, ey = result.value[:4]
        return ok(result, start_x_mm=sx, start_y_mm=sy, end_x_mm=ex, end_y_mm=ey)

    @mcp.tool()
    async def get_fill_shade(name: str, mode: Mode = "auto") -> dict:
        """Return the fill shade, 0–100."""
        result = await run(
            ctx, mode, f"import scribus as _s\n_value = _s.getFillShade({name!r})\n"
        )
        return ok(result, shade=result.value if result.ok else None)

    @mcp.tool()
    async def get_line_shade(name: str, mode: Mode = "auto") -> dict:
        """Return the stroke shade, 0–100."""
        result = await run(
            ctx, mode, f"import scribus as _s\n_value = _s.getLineShade({name!r})\n"
        )
        return ok(result, shade=result.value if result.ok else None)

    @mcp.tool()
    async def get_fill_transparency(name: str, mode: Mode = "auto") -> dict:
        """Return fill opacity, 0–1. 1 is opaque."""
        result = await run(
            ctx, mode, f"import scribus as _s\n_value = _s.getFillTransparency({name!r})\n"
        )
        return ok(result, opacity=result.value if result.ok else None)

    @mcp.tool()
    async def get_line_transparency(name: str, mode: Mode = "auto") -> dict:
        """Return stroke opacity, 0–1. 1 is opaque."""
        result = await run(
            ctx, mode, f"import scribus as _s\n_value = _s.getLineTransparency({name!r})\n"
        )
        return ok(result, opacity=result.value if result.ok else None)

    @mcp.tool()
    async def get_line_cap(name: str, mode: Mode = "auto") -> dict:
        """Return the stroke cap: flat, round, or square."""
        result = await run(
            ctx, mode, f"import scribus as _s\n_value = _s.getLineCap({name!r})\n"
        )
        if not result.ok:
            return ok(result)
        try:
            label = LINE_CAP_NAMES.get(int(result.value), str(result.value))
        except (TypeError, ValueError):
            label = result.value
        return ok(result, cap=label)

    @mcp.tool()
    async def get_line_join(name: str, mode: Mode = "auto") -> dict:
        """Return the stroke join: miter, round, or bevel."""
        result = await run(
            ctx, mode, f"import scribus as _s\n_value = _s.getLineJoin({name!r})\n"
        )
        if not result.ok:
            return ok(result)
        try:
            label = LINE_JOIN_NAMES.get(int(result.value), str(result.value))
        except (TypeError, ValueError):
            label = result.value
        return ok(result, join=label)

    @mcp.tool()
    async def get_line_style(name: str, mode: Mode = "auto") -> dict:
        """Return the stroke dash style: solid, dash, dot, dashdot, or dashdotdot."""
        result = await run(
            ctx, mode, f"import scribus as _s\n_value = _s.getLineStyle({name!r})\n"
        )
        if not result.ok:
            return ok(result)
        try:
            label = LINE_STYLE_NAMES.get(int(result.value), str(result.value))
        except (TypeError, ValueError):
            label = result.value
        return ok(result, style=label)
