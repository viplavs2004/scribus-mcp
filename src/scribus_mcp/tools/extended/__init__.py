"""Scripter operations that were not wrapped by the original tool modules.

Modal dialogs, the progress bar, zoom, and scroll stay out: they do not fit a
request/response tool. Deprecated aliases (``newDoc``, ``setStyle``,
``scaleImage``, ``copyObject``, ``pasteObject``, ``getText``) stay out too;
the current functions are wrapped instead.
"""

from __future__ import annotations

from scribus_mcp.tools.extended import (
    color_style,
    document,
    images,
    layers,
    objects,
    output,
    tables,
    text,
)


def register(mcp, ctx) -> None:
    tables.register(mcp, ctx)
    text.register(mcp, ctx)
    objects.register(mcp, ctx)
    color_style.register(mcp, ctx)
    document.register(mcp, ctx)
    images.register(mcp, ctx)
    layers.register(mcp, ctx)
    output.register(mcp, ctx)
