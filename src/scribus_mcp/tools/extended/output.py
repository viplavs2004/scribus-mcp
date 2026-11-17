"""PDF bookmarks and the export calls that were not already wrapped."""

from __future__ import annotations

from scribus_mcp.tools._common import Mode, ServerCtx
from scribus_mcp.tools.extended._util import ok, run


def register(mcp, ctx: ServerCtx) -> None:
    @mcp.tool()
    async def set_pdf_bookmark(name: str, enabled: bool = True, mode: Mode = "auto") -> dict:
        """Mark a text frame as a PDF bookmark, or clear that flag."""
        result = await run(
            ctx,
            mode,
            "import scribus as _s\n"
            f"_s.setPDFBookmark({1 if enabled else 0}, {name!r})\n"
            f"_value = bool(_s.isPDFBookmark({name!r}))\n",
        )
        return ok(result, bookmark=result.value if result.ok else None)

    @mcp.tool()
    async def is_pdf_bookmark(name: str, mode: Mode = "auto") -> dict:
        """Return whether a text frame is a PDF bookmark."""
        result = await run(
            ctx, mode, f"import scribus as _s\n_value = bool(_s.isPDFBookmark({name!r}))\n"
        )
        return ok(result, bookmark=result.value if result.ok else None)

    @mcp.tool()
    async def save_page_as_eps(path: str, mode: Mode = "auto") -> dict:
        """Save the current page as an EPS file."""
        result = await run(
            ctx, mode, f"import scribus as _s\n_value = _s.savePageAsEPS({path!r})\n"
        )
        return ok(result, path=path if result.ok else None)

    @mcp.tool()
    async def read_pdf_options(path: str, mode: Mode = "auto") -> dict:
        """Load a saved PDF-export preset into the current document."""
        result = await run(
            ctx, mode, f"import scribus as _s\n_value = _s.readPDFOptions({path!r})\n"
        )
        return ok(result)

    @mcp.tool()
    async def save_pdf_options(path: str, mode: Mode = "auto") -> dict:
        """Write the current PDF-export settings to a preset file."""
        result = await run(
            ctx, mode, f"import scribus as _s\n_value = _s.savePDFOptions({path!r})\n"
        )
        return ok(result, path=path if result.ok else None)
