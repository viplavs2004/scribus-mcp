"""Native Scribus table objects (``createTable`` and the cell API)."""

from __future__ import annotations

from scribus_mcp.tools._common import Mode, ServerCtx, clean_user_text
from scribus_mcp.tools.extended._util import border_lines, fail, mm, ok, run

_EDGES = {
    "top": "setCellTopBorder",
    "bottom": "setCellBottomBorder",
    "left": "setCellLeftBorder",
    "right": "setCellRightBorder",
}
_TABLE_EDGES = {
    "top": "setTableTopBorder",
    "bottom": "setTableBottomBorder",
    "left": "setTableLeftBorder",
    "right": "setTableRightBorder",
}


def register(mcp, ctx: ServerCtx) -> None:
    @mcp.tool()
    async def create_table(
        x_mm: float,
        y_mm: float,
        width_mm: float,
        height_mm: float,
        rows: int,
        columns: int,
        name: str = "",
        mode: Mode = "auto",
    ) -> dict:
        """Create a native Scribus table. Rows and columns are counts, not sizes.

        Cell indices on every other table tool are 0-based. Returns ``{name}``.
        """
        if rows < 1 or columns < 1:
            return fail("rows and columns must be >= 1")
        if width_mm <= 0 or height_mm <= 0:
            return fail("width_mm and height_mm must be > 0")
        args = f"{x_mm}, {y_mm}, {width_mm}, {height_mm}, {int(rows)}, {int(columns)}"
        if name:
            args += f", {name!r}"
        result = await run(ctx, mode, mm(f"_value = _s.createTable({args})\n"))
        return ok(result, name=result.value)

    @mcp.tool()
    async def get_table_size(name: str, mode: Mode = "auto") -> dict:
        """Return ``{rows, columns}`` of a native table."""
        body = (
            f"_rows = _s.getTableRows({name!r})\n"
            f"_cols = _s.getTableColumns({name!r})\n"
            "_value = {'rows': _rows, 'columns': _cols}\n"
        )
        result = await run(ctx, mode, "import scribus as _s\n" + body)
        if not result.ok or not isinstance(result.value, dict):
            return ok(result)
        return ok(result, rows=result.value.get("rows"), columns=result.value.get("columns"))

    @mcp.tool()
    async def set_cell_text(
        name: str, row: int, column: int, text: str, mode: Mode = "auto"
    ) -> dict:
        """Set the text of one cell. ``row`` and ``column`` are 0-based."""
        cleaned = clean_user_text(text)
        result = await run(
            ctx,
            mode,
            f"import scribus as _s\n_value = _s.setCellText({int(row)}, {int(column)}, {cleaned!r}, {name!r})\n",
        )
        return ok(result)

    @mcp.tool()
    async def get_cell_text(name: str, row: int, column: int, mode: Mode = "auto") -> dict:
        """Read the text of one cell."""
        result = await run(
            ctx,
            mode,
            f"import scribus as _s\n_value = _s.getCellText({int(row)}, {int(column)}, {name!r})\n",
        )
        return ok(result, text=result.value if result.ok else None)

    @mcp.tool()
    async def set_cell_fill(
        name: str, row: int, column: int, color: str, mode: Mode = "auto"
    ) -> dict:
        """Set a cell's fill color. ``color`` is a document color name, or ``None``."""
        result = await run(
            ctx,
            mode,
            "import scribus as _s\n"
            f"_value = _s.setCellFillColor({int(row)}, {int(column)}, {color!r}, {name!r})\n",
        )
        return ok(result)

    @mcp.tool()
    async def get_cell_fill(name: str, row: int, column: int, mode: Mode = "auto") -> dict:
        """Return the fill color name of one cell."""
        result = await run(
            ctx,
            mode,
            "import scribus as _s\n"
            f"_value = _s.getCellFillColor({int(row)}, {int(column)}, {name!r})\n",
        )
        return ok(result, color=result.value if result.ok else None)

    @mcp.tool()
    async def set_cell_style(
        name: str, row: int, column: int, style: str, mode: Mode = "auto"
    ) -> dict:
        """Apply a named cell style. See ``list_cell_styles``."""
        result = await run(
            ctx,
            mode,
            "import scribus as _s\n"
            f"_value = _s.setCellStyle({int(row)}, {int(column)}, {style!r}, {name!r})\n",
        )
        return ok(result)

    @mcp.tool()
    async def get_cell_style(name: str, row: int, column: int, mode: Mode = "auto") -> dict:
        """Return the named style of one cell."""
        result = await run(
            ctx,
            mode,
            "import scribus as _s\n"
            f"_value = _s.getCellStyle({int(row)}, {int(column)}, {name!r})\n",
        )
        return ok(result, style=result.value if result.ok else None)

    @mcp.tool()
    async def get_cell_span(name: str, row: int, column: int, mode: Mode = "auto") -> dict:
        """Return ``{row_span, column_span}`` for a cell. ``-1`` means the cell does not exist."""
        body = (
            "import scribus as _s\n"
            f"_value = {{'row_span': _s.getCellRowSpan({int(row)}, {int(column)}, {name!r}), "
            f"'column_span': _s.getCellColumnSpan({int(row)}, {int(column)}, {name!r})}}\n"
        )
        result = await run(ctx, mode, body)
        if not result.ok or not isinstance(result.value, dict):
            return ok(result)
        return ok(
            result,
            row_span=result.value.get("row_span"),
            column_span=result.value.get("column_span"),
        )

    @mcp.tool()
    async def merge_table_cells(
        name: str,
        row: int,
        column: int,
        num_rows: int,
        num_columns: int,
        mode: Mode = "auto",
    ) -> dict:
        """Merge the cell at ``row``, ``column`` with the cells to its right and below.

        ``num_rows`` and ``num_columns`` include the starting cell, so both are >= 1.
        """
        if num_rows < 1 or num_columns < 1:
            return fail("num_rows and num_columns must be >= 1")
        result = await run(
            ctx,
            mode,
            "import scribus as _s\n"
            f"_value = _s.mergeTableCells({int(row)}, {int(column)}, {int(num_rows)}, {int(num_columns)}, {name!r})\n",
        )
        return ok(result)

    @mcp.tool()
    async def insert_table_rows(
        name: str, index: int, count: int = 1, mode: Mode = "auto"
    ) -> dict:
        """Insert ``count`` rows before the 0-based ``index``."""
        if count < 1:
            return fail("count must be >= 1")
        result = await run(
            ctx,
            mode,
            f"import scribus as _s\n_value = _s.insertTableRows({int(index)}, {int(count)}, {name!r})\n",
        )
        return ok(result)

    @mcp.tool()
    async def insert_table_columns(
        name: str, index: int, count: int = 1, mode: Mode = "auto"
    ) -> dict:
        """Insert ``count`` columns before the 0-based ``index``."""
        if count < 1:
            return fail("count must be >= 1")
        result = await run(
            ctx,
            mode,
            f"import scribus as _s\n_value = _s.insertTableColumns({int(index)}, {int(count)}, {name!r})\n",
        )
        return ok(result)

    @mcp.tool()
    async def remove_table_rows(
        name: str, index: int, count: int = 1, mode: Mode = "auto"
    ) -> dict:
        """Remove ``count`` rows starting at the 0-based ``index``."""
        if count < 1:
            return fail("count must be >= 1")
        result = await run(
            ctx,
            mode,
            f"import scribus as _s\n_value = _s.removeTableRows({int(index)}, {int(count)}, {name!r})\n",
        )
        return ok(result)

    @mcp.tool()
    async def remove_table_columns(
        name: str, index: int, count: int = 1, mode: Mode = "auto"
    ) -> dict:
        """Remove ``count`` columns starting at the 0-based ``index``."""
        if count < 1:
            return fail("count must be >= 1")
        result = await run(
            ctx,
            mode,
            f"import scribus as _s\n_value = _s.removeTableColumns({int(index)}, {int(count)}, {name!r})\n",
        )
        return ok(result)

    @mcp.tool()
    async def set_table_column_width(
        name: str, column: int, width_mm: float, mode: Mode = "auto"
    ) -> dict:
        """Set one column's width in millimetres."""
        if width_mm < 0:
            return fail("width_mm must be >= 0")
        result = await run(
            ctx,
            mode,
            mm(f"_value = _s.resizeTableColumn({int(column)}, {width_mm}, {name!r})\n"),
        )
        return ok(result)

    @mcp.tool()
    async def set_table_row_height(
        name: str, row: int, height_mm: float, mode: Mode = "auto"
    ) -> dict:
        """Set one row's height in millimetres."""
        if height_mm < 0:
            return fail("height_mm must be >= 0")
        result = await run(
            ctx,
            mode,
            mm(f"_value = _s.resizeTableRow({int(row)}, {height_mm}, {name!r})\n"),
        )
        return ok(result)

    @mcp.tool()
    async def get_table_column_width(name: str, column: int, mode: Mode = "auto") -> dict:
        """Return one column's width in millimetres."""
        result = await run(
            ctx,
            mode,
            mm(f"_value = _s.getTableColumnWidth({int(column)}, {name!r})\n"),
        )
        return ok(result, width_mm=result.value if result.ok else None)

    @mcp.tool()
    async def get_table_row_height(name: str, row: int, mode: Mode = "auto") -> dict:
        """Return one row's height in millimetres."""
        result = await run(
            ctx,
            mode,
            mm(f"_value = _s.getTableRowHeight({int(row)}, {name!r})\n"),
        )
        return ok(result, height_mm=result.value if result.ok else None)

    @mcp.tool()
    async def set_cell_border(
        name: str,
        row: int,
        column: int,
        edge: str,
        lines: list[dict],
        mode: Mode = "auto",
    ) -> dict:
        """Set one cell edge. ``edge`` is top, bottom, left, or right.

        ``lines`` is a list of ``{width, style, color}``. ``width`` is points.
        ``style`` is solid, dash, dot, dashdot, or dashdotdot. Several entries
        make a multi-stroke border.
        """
        if edge not in _EDGES:
            return fail(f"edge must be one of {sorted(_EDGES)}")
        try:
            spec = border_lines(lines)
        except ValueError as exc:
            return fail(str(exc))
        result = await run(
            ctx,
            mode,
            "import scribus as _s\n"
            f"_value = _s.{_EDGES[edge]}({int(row)}, {int(column)}, {spec!r}, {name!r})\n",
        )
        return ok(result)

    @mcp.tool()
    async def set_table_border(
        name: str, edge: str, lines: list[dict], mode: Mode = "auto"
    ) -> dict:
        """Set an outer table edge. Same ``lines`` shape as ``set_cell_border``."""
        if edge not in _TABLE_EDGES:
            return fail(f"edge must be one of {sorted(_TABLE_EDGES)}")
        try:
            spec = border_lines(lines)
        except ValueError as exc:
            return fail(str(exc))
        result = await run(
            ctx,
            mode,
            f"import scribus as _s\n_value = _s.{_TABLE_EDGES[edge]}({spec!r}, {name!r})\n",
        )
        return ok(result)

    @mcp.tool()
    async def set_table_style(name: str, style: str, mode: Mode = "auto") -> dict:
        """Apply a named table style. See ``list_table_styles``."""
        result = await run(
            ctx,
            mode,
            f"import scribus as _s\n_value = _s.setTableStyle({style!r}, {name!r})\n",
        )
        return ok(result)

    @mcp.tool()
    async def get_table_style(name: str, mode: Mode = "auto") -> dict:
        """Return the named style of a table."""
        result = await run(
            ctx, mode, f"import scribus as _s\n_value = _s.getTableStyle({name!r})\n"
        )
        return ok(result, style=result.value if result.ok else None)

    @mcp.tool()
    async def list_table_styles(mode: Mode = "auto") -> dict:
        """List table style names defined in the document."""
        result = await run(ctx, mode, "import scribus as _s\n_value = list(_s.getTableStyles() or [])\n")
        return ok(result, styles=result.value if result.ok else None)

    @mcp.tool()
    async def list_cell_styles(mode: Mode = "auto") -> dict:
        """List cell style names defined in the document."""
        result = await run(ctx, mode, "import scribus as _s\n_value = list(_s.getCellStyles() or [])\n")
        return ok(result, styles=result.value if result.ok else None)
