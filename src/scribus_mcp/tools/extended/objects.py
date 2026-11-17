"""Object operations: clipboard, stacking, attributes, and geometry reads."""

from __future__ import annotations

from scribus_mcp.tools._common import Mode, ServerCtx
from scribus_mcp.tools.extended._util import fail, mm, ok, run

_ATTR_KEYS = (
    "Name",
    "Type",
    "Value",
    "Parameter",
    "Relationship",
    "RelationshipTo",
    "AutoAddTo",
)


def _attributes(items: list[dict]) -> list[dict]:
    out = []
    for item in items:
        row = {}
        lowered = {str(key).lower(): value for key, value in item.items()}
        for key in _ATTR_KEYS:
            row[key] = str(lowered.get(key.lower(), ""))
        out.append(row)
    return out


def register(mcp, ctx: ServerCtx) -> None:
    @mcp.tool()
    async def duplicate_objects(names: list[str], mode: Mode = "auto") -> dict:
        """Duplicate objects in place. Returns ``{names}`` of the copies."""
        if not names:
            return fail("names must contain at least one object")
        result = await run(
            ctx,
            mode,
            "import scribus as _s\n"
            f"_value = list(_s.duplicateObjects({list(names)!r}) or [])\n",
        )
        return ok(result, names=result.value if result.ok else None)

    @mcp.tool()
    async def copy_objects(names: list[str], mode: Mode = "auto") -> dict:
        """Copy objects to the Scribus clipboard of this session.

        ``paste_objects`` only sees them in the same running Scribus. A later
        headless call is a new process and has an empty clipboard.
        """
        if not names:
            return fail("names must contain at least one object")
        result = await run(
            ctx,
            mode,
            f"import scribus as _s\n_value = _s.copyObjects({list(names)!r})\n",
        )
        return ok(result)

    @mcp.tool()
    async def paste_objects(mode: Mode = "auto") -> dict:
        """Paste the Scribus clipboard. Returns ``{names}`` of the new objects.

        Only works in the same Scribus session as ``copy_objects``.
        """
        result = await run(
            ctx,
            mode,
            "import scribus as _s\n_value = list(_s.pasteObjects() or [])\n",
        )
        return ok(result, names=result.value if result.ok else None)

    @mcp.tool()
    async def ungroup_objects(name: str, mode: Mode = "auto") -> dict:
        """Ungroup the group that ``name`` belongs to. ``name`` may be the group or a member."""
        result = await run(
            ctx, mode, f"import scribus as _s\n_value = _s.unGroupObjects({name!r})\n"
        )
        return ok(result)

    @mcp.tool()
    async def combine_polygons(names: list[str], mode: Mode = "auto") -> dict:
        """Boolean-combine two or more polygons. Returns the names left selected."""
        if len(names) < 2:
            return fail("names must contain at least two polygons")
        body = (
            "import scribus as _s\n"
            "_s.deselectAll()\n"
            f"for _n in {list(names)!r}:\n"
            "    _s.selectObject(_n)\n"
            "_s.combinePolygons()\n"
            "_value = [_s.getSelectedObject(_i) for _i in range(_s.selectionCount())]\n"
        )
        result = await run(ctx, mode, body)
        return ok(result, names=result.value if result.ok else None)

    @mcp.tool()
    async def flip_object(
        name: str,
        horizontal: bool = False,
        vertical: bool = False,
        mode: Mode = "auto",
    ) -> dict:
        """Toggle a flip. Each true axis flips once; this does not set an absolute mirror state.

        Call it again on the same axis to flip back.
        """
        if not horizontal and not vertical:
            return fail("set horizontal and/or vertical to true")
        result = await run(
            ctx,
            mode,
            "import scribus as _s\n"
            f"_value = _s.flipObject({1 if horizontal else 0}, {1 if vertical else 0}, {name!r})\n",
        )
        return ok(result)

    @mcp.tool()
    async def bring_to_front(name: str, mode: Mode = "auto") -> dict:
        """Stack this object above everything else on the page."""
        body = (
            "import scribus as _s\n"
            "_s.deselectAll()\n"
            f"_s.selectObject({name!r})\n"
            "_s.moveSelectionToFront()\n"
            f"_value = {name!r}\n"
        )
        result = await run(ctx, mode, body)
        return ok(result)

    @mcp.tool()
    async def send_to_back(name: str, mode: Mode = "auto") -> dict:
        """Stack this object behind everything else on the page."""
        body = (
            "import scribus as _s\n"
            "_s.deselectAll()\n"
            f"_s.selectObject({name!r})\n"
            "_s.moveSelectionToBack()\n"
            f"_value = {name!r}\n"
        )
        result = await run(ctx, mode, body)
        return ok(result)

    @mcp.tool()
    async def select_objects(names: list[str], mode: Mode = "auto") -> dict:
        """Replace the current selection with these objects.

        ``selectObject`` adds, so this clears the selection first. Headless
        Scribus has no lasting selection between tool calls.
        """
        if not names:
            return fail("names must contain at least one object")
        body = (
            "import scribus as _s\n"
            "_s.deselectAll()\n"
            f"for _n in {list(names)!r}:\n"
            "    _s.selectObject(_n)\n"
            "_value = _s.selectionCount()\n"
        )
        result = await run(ctx, mode, body)
        return ok(result, count=result.value if result.ok else None)

    @mcp.tool()
    async def deselect_all(mode: Mode = "auto") -> dict:
        """Clear the object selection in the current Scribus session."""
        result = await run(ctx, mode, "import scribus as _s\n_s.deselectAll()\n_value = True\n")
        return ok(result)

    @mcp.tool()
    async def get_object_rotation(name: str, mode: Mode = "auto") -> dict:
        """Return the object's rotation in degrees. Scribus reports clockwise as positive."""
        result = await run(
            ctx, mode, f"import scribus as _s\n_value = _s.getRotation({name!r})\n"
        )
        return ok(result, degrees=result.value if result.ok else None)

    @mcp.tool()
    async def get_bounding_box(name: str, mode: Mode = "auto") -> dict:
        """Return the object's position and size in millimetres: x, y, width, height."""
        result = await run(ctx, mode, mm(f"_value = list(_s.getBoundingBox({name!r}))\n"))
        return _box(result)

    @mcp.tool()
    async def get_visual_bounding_box(name: str, mode: Mode = "auto") -> dict:
        """Return the visual bounds in millimetres, including strokes and effects."""
        result = await run(
            ctx, mode, mm(f"_value = list(_s.getVisualBoundingBox({name!r}))\n")
        )
        return _box(result)

    @mcp.tool()
    async def get_object_type(name: str, mode: Mode = "auto") -> dict:
        """Return the object type, such as TextFrame, ImageFrame, Table, or Group."""
        result = await run(
            ctx, mode, f"import scribus as _s\n_value = _s.getObjectType({name!r})\n"
        )
        return ok(result, type=result.value if result.ok else None)

    @mcp.tool()
    async def get_object_page(name: str, mode: Mode = "auto") -> dict:
        """Return the 1-based page number that holds this object."""
        result = await run(
            ctx, mode, f"import scribus as _s\n_value = _s.getItemPageNumber({name!r})\n"
        )
        return ok(result, page=result.value if result.ok else None)

    @mcp.tool()
    async def set_object_exportable(
        name: str, exportable: bool = True, mode: Mode = "auto"
    ) -> dict:
        """Include or exclude an object from export."""
        result = await run(
            ctx,
            mode,
            "import scribus as _s\n"
            f"_value = bool(_s.setExportableObject({name!r}, {bool(exportable)}))\n",
        )
        return ok(result, exportable=result.value if result.ok else None)

    @mcp.tool()
    async def is_object_exportable(name: str, mode: Mode = "auto") -> dict:
        """Return whether the object is included in export."""
        result = await run(
            ctx,
            mode,
            f"import scribus as _s\n_value = bool(_s.isExportable({name!r}))\n",
        )
        return ok(result, exportable=result.value if result.ok else None)

    @mcp.tool()
    async def get_object_attributes(name: str, mode: Mode = "auto") -> dict:
        """Return the object's attribute rows (Name, Type, Value, and the relationship fields)."""
        result = await run(
            ctx,
            mode,
            f"import scribus as _s\n_value = list(_s.getObjectAttributes({name!r}) or [])\n",
        )
        return ok(result, attributes=result.value if result.ok else None)

    @mcp.tool()
    async def set_object_attributes(
        name: str, attributes: list[dict], mode: Mode = "auto"
    ) -> dict:
        """Replace the object's attributes.

        Each item may set Name, Type, Value, Parameter, Relationship,
        RelationshipTo, and AutoAddTo. Missing keys are stored as empty strings.
        This replaces the whole attribute list.
        """
        try:
            rows = _attributes(attributes)
        except (AttributeError, TypeError) as exc:
            return fail(f"attributes must be a list of objects: {exc}")
        result = await run(
            ctx,
            mode,
            f"import scribus as _s\n_value = _s.setObjectAttributes({rows!r}, {name!r})\n",
        )
        return ok(result)

    @mcp.tool()
    async def list_object_properties(
        name: str, include_inherited: bool = True, mode: Mode = "auto"
    ) -> dict:
        """List Qt property names on the object. Use with ``get_object_property``."""
        flag = "True" if include_inherited else "False"
        result = await run(
            ctx,
            mode,
            "import scribus as _s\n"
            f"_value = list(_s.getPropertyNames({name!r}, {flag}) or [])\n",
        )
        return ok(result, properties=result.value if result.ok else None)

    @mcp.tool()
    async def get_object_property(name: str, property: str, mode: Mode = "auto") -> dict:
        """Read one Qt property by name."""
        result = await run(
            ctx,
            mode,
            f"import scribus as _s\n_value = _s.getProperty({name!r}, {property!r})\n",
        )
        return ok(result)

    @mcp.tool()
    async def set_object_property(
        name: str,
        property: str,
        value: str | int | float | bool,
        mode: Mode = "auto",
    ) -> dict:
        """Set one Qt property. ``value`` is a string, number, or boolean."""
        result = await run(
            ctx,
            mode,
            f"import scribus as _s\n_value = _s.setProperty({name!r}, {property!r}, {value!r})\n",
        )
        return ok(result)


def _box(result) -> dict:
    if not result.ok or not isinstance(result.value, list) or len(result.value) < 4:
        return ok(result)
    x, y, width, height = result.value[:4]
    return ok(result, x_mm=x, y_mm=y, width_mm=width, height_mm=height)
