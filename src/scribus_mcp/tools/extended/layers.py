"""Layer flags, blend, opacity, and stacking."""

from __future__ import annotations

from scribus_mcp.tools._common import Mode, ServerCtx
from scribus_mcp.tools.extended._util import BLEND_MODES, blend_code, blend_label, fail, ok, run


def register(mcp, ctx: ServerCtx) -> None:
    @mcp.tool()
    async def get_active_layer(mode: Mode = "auto") -> dict:
        """Return the name of the active layer. New objects are created on it."""
        result = await run(ctx, mode, "import scribus as _s\n_value = _s.getActiveLayer()\n")
        return ok(result, layer=result.value if result.ok else None)

    @mcp.tool()
    async def set_layer_locked(name: str, locked: bool = True, mode: Mode = "auto") -> dict:
        """Lock or unlock a layer.

        On Scribus 1.7.4, ``setLayerLocked(layer, True)`` leaves the layer
        unlocked and ``False`` locks it. This tool passes the opposite flag
        so ``locked=True`` matches ``isLayerLocked``.
        """
        flag = 0 if locked else 1
        result = await run(
            ctx,
            mode,
            "import scribus as _s\n"
            f"_s.setLayerLocked({name!r}, {flag})\n"
            f"_value = bool(_s.isLayerLocked({name!r}))\n",
        )
        return ok(result, locked=result.value if result.ok else None)

    @mcp.tool()
    async def is_layer_locked(name: str, mode: Mode = "auto") -> dict:
        """Return whether a layer is locked."""
        result = await run(
            ctx, mode, f"import scribus as _s\n_value = bool(_s.isLayerLocked({name!r}))\n"
        )
        return ok(result, locked=result.value if result.ok else None)

    @mcp.tool()
    async def set_layer_outlined(name: str, outlined: bool = True, mode: Mode = "auto") -> dict:
        """Draw a layer as outlines only."""
        result = await run(
            ctx,
            mode,
            "import scribus as _s\n"
            f"_s.setLayerOutlined({name!r}, {1 if outlined else 0})\n"
            f"_value = bool(_s.isLayerOutlined({name!r}))\n",
        )
        return ok(result, outlined=result.value if result.ok else None)

    @mcp.tool()
    async def is_layer_outlined(name: str, mode: Mode = "auto") -> dict:
        """Return whether a layer is drawn as outlines."""
        result = await run(
            ctx, mode, f"import scribus as _s\n_value = bool(_s.isLayerOutlined({name!r}))\n"
        )
        return ok(result, outlined=result.value if result.ok else None)

    @mcp.tool()
    async def set_layer_text_flow(name: str, flow: bool = True, mode: Mode = "auto") -> dict:
        """When true, text on layers above wraps around objects on this layer."""
        result = await run(
            ctx,
            mode,
            "import scribus as _s\n"
            f"_s.setLayerFlow({name!r}, {1 if flow else 0})\n"
            f"_value = bool(_s.isLayerFlow({name!r}))\n",
        )
        return ok(result, flow=result.value if result.ok else None)

    @mcp.tool()
    async def is_layer_text_flow(name: str, mode: Mode = "auto") -> dict:
        """Return whether text on higher layers wraps around this layer."""
        result = await run(
            ctx, mode, f"import scribus as _s\n_value = bool(_s.isLayerFlow({name!r}))\n"
        )
        return ok(result, flow=result.value if result.ok else None)

    @mcp.tool()
    async def is_layer_visible(name: str, mode: Mode = "auto") -> dict:
        """Return whether a layer is visible."""
        result = await run(
            ctx, mode, f"import scribus as _s\n_value = bool(_s.isLayerVisible({name!r}))\n"
        )
        return ok(result, visible=result.value if result.ok else None)

    @mcp.tool()
    async def is_layer_printable(name: str, mode: Mode = "auto") -> dict:
        """Return whether a layer is included when printing or exporting."""
        result = await run(
            ctx, mode, f"import scribus as _s\n_value = bool(_s.isLayerPrintable({name!r}))\n"
        )
        return ok(result, printable=result.value if result.ok else None)

    @mcp.tool()
    async def set_layer_blend_mode(name: str, blend: str, mode: Mode = "auto") -> dict:
        """Set a layer's blend mode. Same names as ``set_fill_blend_mode``."""
        code = blend_code(blend)
        if code is None:
            return fail(f"blend must be one of {sorted(BLEND_MODES)}")
        result = await run(
            ctx,
            mode,
            "import scribus as _s\n"
            f"_s.setLayerBlendmode({name!r}, {code})\n"
            f"_value = _s.getLayerBlendmode({name!r})\n",
        )
        if not result.ok:
            return ok(result)
        return ok(result, blend=blend_label(result.value))

    @mcp.tool()
    async def get_layer_blend_mode(name: str, mode: Mode = "auto") -> dict:
        """Return a layer's blend mode name."""
        result = await run(
            ctx, mode, f"import scribus as _s\n_value = _s.getLayerBlendmode({name!r})\n"
        )
        if not result.ok:
            return ok(result)
        return ok(result, blend=blend_label(result.value))

    @mcp.tool()
    async def set_layer_transparency(name: str, opacity: float, mode: Mode = "auto") -> dict:
        """Set a layer's opacity, 0–1. 1 is opaque, matching ``set_fill_transparency``."""
        if not 0.0 <= opacity <= 1.0:
            return fail("opacity must be in [0, 1]")
        result = await run(
            ctx,
            mode,
            "import scribus as _s\n"
            f"_s.setLayerTransparency({name!r}, {float(opacity)})\n"
            f"_value = _s.getLayerTransparency({name!r})\n",
        )
        return ok(result, opacity=result.value if result.ok else None)

    @mcp.tool()
    async def get_layer_transparency(name: str, mode: Mode = "auto") -> dict:
        """Return a layer's opacity, 0–1."""
        result = await run(
            ctx, mode, f"import scribus as _s\n_value = _s.getLayerTransparency({name!r})\n"
        )
        return ok(result, opacity=result.value if result.ok else None)

    @mcp.tool()
    async def raise_active_layer(mode: Mode = "auto") -> dict:
        """Move the active layer up one step in the stack."""
        result = await run(
            ctx,
            mode,
            "import scribus as _s\n_s.raiseActiveLayer()\n_value = _s.getActiveLayer()\n",
        )
        return ok(result, layer=result.value if result.ok else None)

    @mcp.tool()
    async def lower_active_layer(mode: Mode = "auto") -> dict:
        """Move the active layer down one step in the stack."""
        result = await run(
            ctx,
            mode,
            "import scribus as _s\n_s.lowerActiveLayer()\n_value = _s.getActiveLayer()\n",
        )
        return ok(result, layer=result.value if result.ok else None)
