"""Document and page setup that the original page tools did not wrap."""

from __future__ import annotations

from scribus_mcp.tools._common import Mode, ServerCtx
from scribus_mcp.tools.extended._util import fail, mm, ok, run

_GUIDE_REF = {"page": 0, "margin": 1, "selection": 2}
_PAGE_SIDE = {0: "left", 1: "middle", 2: "right"}
_IMPORT_WHERE = {"end": (1, 2), "before": (1, 0), "after": (1, 1), "replace": (0, 2)}


def register(mcp, ctx: ServerCtx) -> None:
    @mcp.tool()
    async def get_document_metadata(mode: Mode = "auto") -> dict:
        """Read the author, title, and comments stored by ``set_document_metadata``.

        Scribus 1.7.4's ``getInfo`` returns an empty string even after a
        successful ``setInfo``. The values are still written onto the
        document. This tool returns whatever the running Scribus gives back.
        """
        result = await run(ctx, mode, "import scribus as _s\n_value = _s.getInfo()\n")
        if not result.ok:
            return ok(result)
        raw = result.value
        if isinstance(raw, (list, tuple)) and len(raw) >= 3:
            return ok(result, author=raw[0], title=raw[1], comments=raw[2])
        return ok(result, raw=raw)

    @mcp.tool()
    async def set_document_right_to_left(right_to_left: bool = True, mode: Mode = "auto") -> dict:
        """Set whether the document's page order is right-to-left."""
        result = await run(
            ctx,
            mode,
            f"import scribus as _s\n_value = _s.setRTL({bool(right_to_left)})\n",
        )
        return ok(result)

    @mcp.tool()
    async def get_document_right_to_left(mode: Mode = "auto") -> dict:
        """Return whether the document is right-to-left."""
        result = await run(ctx, mode, "import scribus as _s\n_value = bool(_s.getRTL())\n")
        return ok(result, right_to_left=result.value if result.ok else None)

    @mcp.tool()
    async def mark_document_changed(changed: bool = True, mode: Mode = "auto") -> dict:
        """Set the document's unsaved-changes flag.

        Scribus does not always notice scripted edits. Pass true so Save
        lights up, or false after you have saved through a script.
        """
        result = await run(
            ctx, mode, f"import scribus as _s\n_value = _s.docChanged({bool(changed)})\n"
        )
        return ok(result)

    @mcp.tool()
    async def get_bleeds(mode: Mode = "auto") -> dict:
        """Return document bleeds in millimetres."""
        result = await run(ctx, mode, mm("_value = list(_s.getBleeds())\n"))
        if not result.ok or not isinstance(result.value, list) or len(result.value) < 4:
            return ok(result)
        left, right, top, bottom = result.value[:4]
        return ok(result, left_mm=left, right_mm=right, top_mm=top, bottom_mm=bottom)

    @mcp.tool()
    async def set_bleeds(
        left_mm: float,
        right_mm: float,
        top_mm: float,
        bottom_mm: float,
        mode: Mode = "auto",
    ) -> dict:
        """Set the document bleeds in millimetres."""
        result = await run(
            ctx,
            mode,
            mm(f"_value = _s.setBleeds({left_mm}, {right_mm}, {top_mm}, {bottom_mm})\n"),
        )
        return ok(result)

    @mcp.tool()
    async def get_baseline_grid(mode: Mode = "auto") -> dict:
        """Return the baseline grid spacing and offset in millimetres."""
        result = await run(ctx, mode, mm("_value = list(_s.getBaseLine())\n"))
        if not result.ok or not isinstance(result.value, list) or len(result.value) < 2:
            return ok(result)
        return ok(result, spacing_mm=result.value[0], offset_mm=result.value[1])

    @mcp.tool()
    async def set_baseline_grid(
        spacing_mm: float, offset_mm: float = 0.0, mode: Mode = "auto"
    ) -> dict:
        """Set the baseline grid. ``spacing_mm`` is the distance between lines."""
        if spacing_mm <= 0:
            return fail("spacing_mm must be > 0")
        result = await run(
            ctx,
            mode,
            mm(f"_value = _s.setBaseLine({spacing_mm}, {offset_mm})\n"),
        )
        return ok(result)

    @mcp.tool()
    async def set_facing_pages(
        facing: bool = True, first_page: str = "right", mode: Mode = "auto"
    ) -> dict:
        """Turn facing pages on or off. ``first_page`` is left or right."""
        if first_page not in ("left", "right"):
            return fail("first_page must be 'left' or 'right'")
        side = "_s.FIRSTPAGELEFT" if first_page == "left" else "_s.FIRSTPAGERIGHT"
        facing_flag = "_s.FACINGPAGES" if facing else "_s.NOFACINGPAGES"
        result = await run(
            ctx,
            mode,
            "import scribus as _s\n"
            f"_value = _s.setDocType({facing_flag}, {side})\n",
        )
        return ok(result)

    @mcp.tool()
    async def set_page_size(width_mm: float, height_mm: float, mode: Mode = "auto") -> dict:
        """Set the current page's size in millimetres."""
        if width_mm <= 0 or height_mm <= 0:
            return fail("width_mm and height_mm must be > 0")
        result = await run(
            ctx,
            mode,
            mm(f"_value = _s.setCurrentPageSize({width_mm}, {height_mm})\n"),
        )
        return ok(result)

    @mcp.tool()
    async def get_page_type(mode: Mode = "auto") -> dict:
        """Return whether the current page is a left, middle, or right page."""
        result = await run(ctx, mode, "import scribus as _s\n_value = _s.getPageType()\n")
        if not result.ok:
            return ok(result)
        try:
            label = _PAGE_SIDE.get(int(result.value), str(result.value))
        except (TypeError, ValueError):
            label = result.value
        return ok(result, side=label)

    @mcp.tool()
    async def get_page_size_at(page_number: int, mode: Mode = "auto") -> dict:
        """Return width and height of a 1-based page, in millimetres."""
        result = await run(
            ctx, mode, mm(f"_value = list(_s.getPageNSize({int(page_number)}))\n")
        )
        if not result.ok or not isinstance(result.value, list) or len(result.value) < 2:
            return ok(result)
        return ok(result, width_mm=result.value[0], height_mm=result.value[1])

    @mcp.tool()
    async def get_page_margins_at(page_number: int, mode: Mode = "auto") -> dict:
        """Return one page's margins in millimetres, in the same order as ``get_page_margins``."""
        result = await run(
            ctx, mode, mm(f"_value = list(_s.getPageNMargins({int(page_number)}))\n")
        )
        if not result.ok or not isinstance(result.value, list) or len(result.value) < 4:
            return ok(result)
        top, left, right, bottom = result.value[:4]
        return ok(result, top_mm=top, left_mm=left, right_mm=right, bottom_mm=bottom)

    @mcp.tool()
    async def get_applied_master_page(page_number: int, mode: Mode = "auto") -> dict:
        """Return the master page applied to a 1-based page."""
        result = await run(
            ctx,
            mode,
            f"import scribus as _s\n_value = _s.getMasterPage({int(page_number)})\n",
        )
        return ok(result, master_page=result.value if result.ok else None)

    @mcp.tool()
    async def get_section_page_number(mode: Mode = "auto") -> dict:
        """Return the current page number as shown in its section, which may not start at 1."""
        result = await run(
            ctx, mode, "import scribus as _s\n_value = _s.currentPageNumberForSection()\n"
        )
        return ok(result, page=result.value if result.ok else None)

    @mcp.tool()
    async def get_column_guides(mode: Mode = "auto") -> dict:
        """Return the current page's column-guide grid.

        The result includes the count, the gap in millimetres, what the grid
        is measured from (page, margin, or selection), and the guide positions.
        """
        result = await run(ctx, mode, mm("_value = _s.getColumnGuides()\n"))
        return ok(result, guides=result.value if result.ok else None)

    @mcp.tool()
    async def set_column_guides(
        count: int,
        gap_mm: float = 0.0,
        refer_to: str = "page",
        mode: Mode = "auto",
    ) -> dict:
        """Lay out ``count`` equal columns of guides. ``count`` 0 clears them.

        ``refer_to`` is page, margin, or selection. ``gap_mm`` is the gutter.
        """
        if count < 0:
            return fail("count must be >= 0")
        if refer_to not in _GUIDE_REF:
            return fail(f"refer_to must be one of {sorted(_GUIDE_REF)}")
        result = await run(
            ctx,
            mode,
            mm(
                f"_value = _s.setColumnGuides({int(count)}, {float(gap_mm)}, {_GUIDE_REF[refer_to]})\n"
            ),
        )
        return ok(result)

    @mcp.tool()
    async def get_row_guides(mode: Mode = "auto") -> dict:
        """Return the current page's row-guide grid. Same shape as ``get_column_guides``."""
        result = await run(ctx, mode, mm("_value = _s.getRowGuides()\n"))
        return ok(result, guides=result.value if result.ok else None)

    @mcp.tool()
    async def set_row_guides(
        count: int,
        gap_mm: float = 0.0,
        refer_to: str = "page",
        mode: Mode = "auto",
    ) -> dict:
        """Lay out ``count`` equal rows of guides. ``count`` 0 clears them."""
        if count < 0:
            return fail("count must be >= 0")
        if refer_to not in _GUIDE_REF:
            return fail(f"refer_to must be one of {sorted(_GUIDE_REF)}")
        result = await run(
            ctx,
            mode,
            mm(
                f"_value = _s.setRowGuides({int(count)}, {float(gap_mm)}, {_GUIDE_REF[refer_to]})\n"
            ),
        )
        return ok(result)

    @mcp.tool()
    async def edit_master_page(name: str, mode: Mode = "auto") -> dict:
        """Open a master page for editing. Call ``close_master_page`` when finished.

        Objects created while it is open land on the master. ``create_master_page``
        already opens a new one; use this to reopen an existing master.
        """
        result = await run(
            ctx, mode, f"import scribus as _s\n_value = _s.editMasterPage({name!r})\n"
        )
        return ok(result)

    @mcp.tool()
    async def close_master_page(mode: Mode = "auto") -> dict:
        """Leave master-page editing and return to the document pages."""
        result = await run(ctx, mode, "import scribus as _s\n_value = _s.closeMasterPage()\n")
        return ok(result)

    @mcp.tool()
    async def import_pages(
        path: str,
        page_numbers: list[int],
        where: str = "end",
        where_page: int = 0,
        mode: Mode = "auto",
    ) -> dict:
        """Import pages from another ``.sla``.

        ``page_numbers`` are the source document's page numbers as
        ``importPage`` expects them. ``where`` is end, before, after, or
        replace. ``where_page`` is the 0-based index in the current document
        used by before and after.
        """
        if where not in _IMPORT_WHERE:
            return fail(f"where must be one of {sorted(_IMPORT_WHERE)}")
        if not page_numbers:
            return fail("page_numbers must contain at least one page")
        create, place = _IMPORT_WHERE[where]
        result = await run(
            ctx,
            mode,
            "import scribus as _s\n"
            f"_value = _s.importPage({path!r}, {tuple(int(n) for n in page_numbers)!r}, "
            f"{create}, {place}, {int(where_page)})\n",
        )
        return ok(result)
