"""Text operations the original text tools did not wrap."""

from __future__ import annotations

from scribus_mcp.tools._common import Mode, ServerCtx
from scribus_mcp.tools.extended._util import fail, mm, ok, run
from scribus_mcp.tools.text import FIRST_LINE_OFFSET, LINE_SPACING_MODE

_FLOW = {
    "none": 0,
    "frame": 1,
    "bounding_box": 2,
    "contour": 3,
    "clip": 4,
}
_FLOW_NAMES = {value: name for name, value in _FLOW.items()}
_V_ALIGN = {0: "top", 1: "center", 2: "bottom"}
_DIRECTION = {"ltr": 0, "rtl": 1}
_SPACING_NAMES = {value: name for name, value in LINE_SPACING_MODE.items()}
_OFFSET_NAMES = {value: name for name, value in FIRST_LINE_OFFSET.items()}


def register(mcp, ctx: ServerCtx) -> None:
    @mcp.tool()
    async def delete_text(name: str, mode: Mode = "auto") -> dict:
        """Delete the text in a frame. If a range is selected, only that range is deleted.

        Select a range first with ``select_text``. With no selection, the whole story goes.
        """
        result = await run(ctx, mode, f"import scribus as _s\n_value = _s.deleteText({name!r})\n")
        return ok(result)

    @mcp.tool()
    async def select_text(name: str, start: int, count: int, mode: Mode = "auto") -> dict:
        """Select ``count`` characters of the whole story, starting at ``start`` (0-based).

        ``count`` 0 clears the selection. This spans linked frames. Use
        ``select_frame_text`` to stay inside one frame.
        """
        result = await run(
            ctx,
            mode,
            f"import scribus as _s\n_value = _s.selectText({int(start)}, {int(count)}, {name!r})\n",
        )
        return ok(result)

    @mcp.tool()
    async def select_frame_text(name: str, start: int, count: int, mode: Mode = "auto") -> dict:
        """Select ``count`` characters visible in this frame only.

        ``count`` 0 clears the selection. ``count`` -1 runs to the end of the frame.
        Layout the frame first (``layout_text``) or the range can be wrong.
        """
        result = await run(
            ctx,
            mode,
            f"import scribus as _s\n_value = _s.selectFrameText({int(start)}, {int(count)}, {name!r})\n",
        )
        return ok(result)

    @mcp.tool()
    async def get_text_selection(name: str, mode: Mode = "auto") -> dict:
        """Return the story selection and the selection inside this frame.

        Each is ``{start, length}``. Both are 0 when nothing is selected.
        """
        body = (
            "import scribus as _s\n"
            f"_story = _s.getSelectedTextRange({name!r}) or (0, 0)\n"
            f"_frame = _s.getFrameSelectedTextRange({name!r}) or (0, 0)\n"
            "_value = {'story_start': int(_story[0]), 'story_length': int(_story[1]), "
            "'frame_start': int(_frame[0]), 'frame_length': int(_frame[1])}\n"
        )
        result = await run(ctx, mode, body)
        if not result.ok or not isinstance(result.value, dict):
            return ok(result)
        return ok(result, **result.value)

    @mcp.tool()
    async def unlink_text_frames(name: str, mode: Mode = "auto") -> dict:
        """Pull this frame out of its text chain. Neighbours stay linked to each other."""
        result = await run(
            ctx, mode, f"import scribus as _s\n_value = _s.unlinkTextFrames({name!r})\n"
        )
        return ok(result)

    @mcp.tool()
    async def get_text_chain(name: str, mode: Mode = "auto") -> dict:
        """Return the first, previous, next, and last frame names in this story."""
        body = (
            "import scribus as _s\n"
            f"_value = {{'first': _s.getFirstLinkedFrame({name!r}), "
            f"'previous': _s.getPrevLinkedFrame({name!r}), "
            f"'next': _s.getNextLinkedFrame({name!r}), "
            f"'last': _s.getLastLinkedFrame({name!r})}}\n"
        )
        result = await run(ctx, mode, body)
        if not result.ok or not isinstance(result.value, dict):
            return ok(result)
        return ok(result, **result.value)

    @mcp.tool()
    async def hyphenate_text(name: str, mode: Mode = "auto") -> dict:
        """Hyphenate the text in a frame. Returns whether Scribus changed anything."""
        result = await run(
            ctx, mode, f"import scribus as _s\n_value = bool(_s.hyphenateText({name!r}))\n"
        )
        return ok(result, hyphenated=result.value if result.ok else None)

    @mcp.tool()
    async def dehyphenate_text(name: str, mode: Mode = "auto") -> dict:
        """Remove discretionary hyphens from a frame."""
        result = await run(
            ctx, mode, f"import scribus as _s\n_value = bool(_s.dehyphenateText({name!r}))\n"
        )
        return ok(result, changed=result.value if result.ok else None)

    @mcp.tool()
    async def insert_html_text(name: str, path: str, mode: Mode = "auto") -> dict:
        """Insert a UTF-8 HTML file into a text frame.

        ``path`` is a file on disk, not an HTML string. Scribus keeps a limited
        subset of inline markup.
        """
        result = await run(
            ctx,
            mode,
            f"import scribus as _s\n_value = _s.insertHtmlText({path!r}, {name!r})\n",
        )
        return ok(result)

    @mcp.tool()
    async def set_text_distances(
        name: str,
        left_mm: float,
        right_mm: float,
        top_mm: float,
        bottom_mm: float,
        mode: Mode = "auto",
    ) -> dict:
        """Set the text inset on each side of a frame, in millimetres. Values must be >= 0."""
        for label, value in (
            ("left_mm", left_mm),
            ("right_mm", right_mm),
            ("top_mm", top_mm),
            ("bottom_mm", bottom_mm),
        ):
            if value < 0:
                return fail(f"{label} must be >= 0")
        result = await run(
            ctx,
            mode,
            mm(
                f"_value = _s.setTextDistances({left_mm}, {right_mm}, {top_mm}, {bottom_mm}, {name!r})\n"
            ),
        )
        return ok(result)

    @mcp.tool()
    async def get_text_distances(name: str, mode: Mode = "auto") -> dict:
        """Return the text inset as ``{left_mm, right_mm, top_mm, bottom_mm}``."""
        result = await run(
            ctx, mode, mm(f"_value = list(_s.getTextDistances({name!r}))\n")
        )
        if not result.ok or not isinstance(result.value, list) or len(result.value) < 4:
            return ok(result)
        left, right, top, bottom = result.value[:4]
        return ok(result, left_mm=left, right_mm=right, top_mm=top, bottom_mm=bottom)

    @mcp.tool()
    async def set_text_flow(name: str, flow: str = "frame", mode: Mode = "auto") -> dict:
        """Choose how other text wraps this object.

        ``flow`` is none, frame, bounding_box, contour, or clip.
        """
        if flow not in _FLOW:
            return fail(f"flow must be one of {sorted(_FLOW)}")
        result = await run(
            ctx,
            mode,
            f"import scribus as _s\n_value = _s.setTextFlowMode({name!r}, {_FLOW[flow]})\n",
        )
        return ok(result)

    @mcp.tool()
    async def get_text_flow(name: str, mode: Mode = "auto") -> dict:
        """Return how text wraps this object: none, frame, bounding_box, contour, or clip."""
        result = await run(
            ctx, mode, f"import scribus as _s\n_value = _s.getTextFlowMode({name!r})\n"
        )
        if not result.ok:
            return ok(result)
        try:
            code = int(result.value)
        except (TypeError, ValueError):
            return ok(result, flow=result.value)
        return ok(result, flow=_FLOW_NAMES.get(code, str(code)))

    @mcp.tool()
    async def set_tracking(name: str, tracking: int, mode: Mode = "auto") -> dict:
        """Set character tracking. Scribus expects an integer; 0 is the font default.

        A selection inside the frame limits the change to that selection.
        """
        result = await run(
            ctx,
            mode,
            f"import scribus as _s\n_value = _s.setTracking({int(tracking)}, {name!r})\n",
        )
        return ok(result)

    @mcp.tool()
    async def get_tracking(name: str, mode: Mode = "auto") -> dict:
        """Read character tracking. A selection returns the first selected character's value."""
        result = await run(
            ctx, mode, f"import scribus as _s\n_value = _s.getTracking({name!r})\n"
        )
        return ok(result, tracking=result.value if result.ok else None)

    @mcp.tool()
    async def set_word_tracking(name: str, tracking: float, mode: Mode = "auto") -> dict:
        """Set word spacing as a tracking factor. A selection limits the change."""
        result = await run(
            ctx,
            mode,
            f"import scribus as _s\n_value = _s.setWordTracking({float(tracking)}, {name!r})\n",
        )
        return ok(result)

    @mcp.tool()
    async def get_word_tracking(name: str, mode: Mode = "auto") -> dict:
        """Read word tracking."""
        result = await run(
            ctx, mode, f"import scribus as _s\n_value = _s.getWordTracking({name!r})\n"
        )
        return ok(result, tracking=result.value if result.ok else None)

    @mcp.tool()
    async def set_min_word_tracking(name: str, tracking: float, mode: Mode = "auto") -> dict:
        """Set the minimum word tracking used when justifying a line."""
        result = await run(
            ctx,
            mode,
            f"import scribus as _s\n_value = _s.setMinWordTracking({float(tracking)}, {name!r})\n",
        )
        return ok(result)

    @mcp.tool()
    async def get_min_word_tracking(name: str, mode: Mode = "auto") -> dict:
        """Read the minimum word tracking."""
        result = await run(
            ctx, mode, f"import scribus as _s\n_value = _s.getMinWordTracking({name!r})\n"
        )
        return ok(result, tracking=result.value if result.ok else None)

    @mcp.tool()
    async def set_font_features(name: str, features: list[str], mode: Mode = "auto") -> dict:
        """Set OpenType / font features on a frame, or on the current text selection.

        ``features`` is a list such as ``["underline", "smallcaps"]``. Scribus
        joins them with commas and no spaces. Known tokens include inherit,
        bold, italic, underline, underlinewords, strike, superscript, subscript,
        outline, shadowed, allcaps, smallcaps. An empty list clears them.
        """
        joined = ",".join(part.strip() for part in features if part and part.strip())
        if any(" " in part or "," in part for part in features):
            return fail("each feature is a single token with no spaces or commas")
        result = await run(
            ctx,
            mode,
            f"import scribus as _s\n_value = _s.setFontFeatures({joined!r}, {name!r})\n",
        )
        return ok(result)

    @mcp.tool()
    async def get_font_features(name: str, mode: Mode = "auto") -> dict:
        """Return the font-feature string and the same tokens as a list."""
        result = await run(
            ctx, mode, f"import scribus as _s\n_value = _s.getFontFeatures({name!r}) or ''\n"
        )
        if not result.ok:
            return ok(result)
        raw = result.value or ""
        tokens = [part for part in str(raw).split(",") if part]
        return ok(result, features=raw, tokens=tokens)

    @mcp.tool()
    async def set_text_direction(name: str, direction: str = "ltr", mode: Mode = "auto") -> dict:
        """Set the frame's text direction to ``ltr`` or ``rtl``."""
        if direction not in _DIRECTION:
            return fail("direction must be 'ltr' or 'rtl'")
        result = await run(
            ctx,
            mode,
            "import scribus as _s\n"
            f"_value = _s.setTextDirection({_DIRECTION[direction]}, {name!r})\n",
        )
        return ok(result)

    @mcp.tool()
    async def set_text_stroke(name: str, color: str, mode: Mode = "auto") -> dict:
        """Set the stroke color of the glyphs. ``color`` is a document color name."""
        result = await run(
            ctx,
            mode,
            f"import scribus as _s\n_value = _s.setTextStroke({color!r}, {name!r})\n",
        )
        return ok(result)

    @mcp.tool()
    async def get_text_color(name: str, mode: Mode = "auto") -> dict:
        """Return the text fill color. A selection returns the first selected character."""
        result = await run(
            ctx, mode, f"import scribus as _s\n_value = _s.getTextColor({name!r})\n"
        )
        return ok(result, color=result.value if result.ok else None)

    @mcp.tool()
    async def get_text_shade(name: str, mode: Mode = "auto") -> dict:
        """Return the text shade, 0–100."""
        result = await run(
            ctx, mode, f"import scribus as _s\n_value = _s.getTextShade({name!r})\n"
        )
        return ok(result, shade=result.value if result.ok else None)

    @mcp.tool()
    async def get_text_vertical_alignment(name: str, mode: Mode = "auto") -> dict:
        """Return vertical alignment: top, center, or bottom."""
        result = await run(
            ctx,
            mode,
            f"import scribus as _s\n_value = _s.getTextVerticalAlignment({name!r})\n",
        )
        if not result.ok:
            return ok(result)
        try:
            label = _V_ALIGN.get(int(result.value), str(result.value))
        except (TypeError, ValueError):
            label = result.value
        return ok(result, alignment=label)

    @mcp.tool()
    async def get_line_spacing(name: str, mode: Mode = "auto") -> dict:
        """Return the frame's leading in points."""
        result = await run(
            ctx, mode, f"import scribus as _s\n_value = _s.getLineSpacing({name!r})\n"
        )
        return ok(result, leading_pt=result.value if result.ok else None)

    @mcp.tool()
    async def get_line_spacing_mode(name: str, mode: Mode = "auto") -> dict:
        """Return fixed, automatic, or baseline."""
        result = await run(
            ctx, mode, f"import scribus as _s\n_value = _s.getLineSpacingMode({name!r})\n"
        )
        if not result.ok:
            return ok(result)
        try:
            label = _SPACING_NAMES.get(int(result.value), str(result.value))
        except (TypeError, ValueError):
            label = result.value
        return ok(result, spacing_mode=label)

    @mcp.tool()
    async def get_column_count(name: str, mode: Mode = "auto") -> dict:
        """Return how many text columns the frame has."""
        result = await run(
            ctx, mode, f"import scribus as _s\n_value = _s.getColumns({name!r})\n"
        )
        return ok(result, count=result.value if result.ok else None)

    @mcp.tool()
    async def get_column_gap(name: str, mode: Mode = "auto") -> dict:
        """Return the gap between text columns, in millimetres."""
        result = await run(ctx, mode, mm(f"_value = _s.getColumnGap({name!r})\n"))
        return ok(result, gap_mm=result.value if result.ok else None)

    @mcp.tool()
    async def get_first_line_offset(name: str, mode: Mode = "auto") -> dict:
        """Return the first-line offset policy: real_glyph_height, font_ascent, line_spacing, or baseline_grid."""
        result = await run(
            ctx, mode, f"import scribus as _s\n_value = _s.getFirstLineOffset({name!r})\n"
        )
        if not result.ok:
            return ok(result)
        try:
            label = _OFFSET_NAMES.get(int(result.value), str(result.value))
        except (TypeError, ValueError):
            label = result.value
        return ok(result, policy=label)

    @mcp.tool()
    async def get_text_length(name: str, mode: Mode = "auto") -> dict:
        """Return the number of characters in the story."""
        result = await run(
            ctx, mode, f"import scribus as _s\n_value = _s.getTextLength({name!r})\n"
        )
        return ok(result, length=result.value if result.ok else None)

    @mcp.tool()
    async def get_text_lines(name: str, mode: Mode = "auto") -> dict:
        """Return how many lines are laid out in the frame.

        Call ``layout_text`` first if the frame was just edited, or the count can be stale.
        """
        result = await run(
            ctx, mode, f"import scribus as _s\n_value = _s.getTextLines({name!r})\n"
        )
        return ok(result, lines=result.value if result.ok else None)
