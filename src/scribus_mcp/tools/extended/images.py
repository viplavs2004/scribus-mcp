"""Image adjustments and placing vector files."""

from __future__ import annotations

from scribus_mcp.tools._common import Mode, ServerCtx
from scribus_mcp.tools.extended._util import fail, mm, ok, run

_COLOR_SPACE = {
    -1: "undefined",
    0: "rgb",
    1: "cmyk",
    2: "gray",
    3: "duotone",
    4: "monochrome",
}
_PREVIEW = {"full": 0, "normal": 1, "low": 2}
_PREVIEW_NAMES = {value: name for name, value in _PREVIEW.items()}
_PLACE = {
    "svg": "placeSVG",
    "eps": "placeEPS",
    "odg": "placeODG",
    "sxd": "placeSXD",
    "vector": "placeVectorFile",
}


def register(mcp, ctx: ServerCtx) -> None:
    @mcp.tool()
    async def get_image_scale(name: str, mode: Mode = "auto") -> dict:
        """Return the image scale factors. 1 means 100 percent."""
        result = await run(
            ctx, mode, f"import scribus as _s\n_value = list(_s.getImageScale({name!r}))\n"
        )
        if not result.ok or not isinstance(result.value, list) or len(result.value) < 2:
            return ok(result)
        return ok(result, x_scale=result.value[0], y_scale=result.value[1])

    @mcp.tool()
    async def get_image_offset(name: str, mode: Mode = "auto") -> dict:
        """Return the image offset inside the frame, in millimetres."""
        result = await run(
            ctx, mode, mm(f"_value = list(_s.getImageOffset({name!r}))\n")
        )
        if not result.ok or not isinstance(result.value, list) or len(result.value) < 2:
            return ok(result)
        return ok(result, offset_x_mm=result.value[0], offset_y_mm=result.value[1])

    @mcp.tool()
    async def get_image_color_space(name: str, mode: Mode = "auto") -> dict:
        """Return rgb, cmyk, gray, duotone, monochrome, or undefined."""
        result = await run(
            ctx, mode, f"import scribus as _s\n_value = _s.getImageColorSpace({name!r})\n"
        )
        if not result.ok:
            return ok(result)
        try:
            label = _COLOR_SPACE.get(int(result.value), str(result.value))
        except (TypeError, ValueError):
            label = result.value
        return ok(result, color_space=label)

    @mcp.tool()
    async def get_image_ppi(name: str, mode: Mode = "auto") -> dict:
        """Return the placed image's effective resolution in each axis."""
        result = await run(
            ctx, mode, f"import scribus as _s\n_value = list(_s.getImagePpi({name!r}))\n"
        )
        if not result.ok or not isinstance(result.value, list) or len(result.value) < 2:
            return ok(result)
        return ok(result, ppi_x=result.value[0], ppi_y=result.value[1])

    @mcp.tool()
    async def get_image_rotation(name: str, mode: Mode = "auto") -> dict:
        """Return the image rotation in degrees."""
        result = await run(
            ctx, mode, f"import scribus as _s\n_value = _s.getImageRotation({name!r})\n"
        )
        return ok(result, degrees=result.value if result.ok else None)

    @mcp.tool()
    async def set_image_rotation(name: str, degrees: float, mode: Mode = "auto") -> dict:
        """Rotate the image inside its frame, in degrees."""
        result = await run(
            ctx,
            mode,
            f"import scribus as _s\n_value = _s.setImageRotation({float(degrees)}, {name!r})\n",
        )
        return ok(result)

    @mcp.tool()
    async def set_image_brightness(name: str, factor: float, mode: Mode = "auto") -> dict:
        """Set image brightness. 1 is unchanged, matching the properties palette."""
        result = await run(
            ctx,
            mode,
            f"import scribus as _s\n_value = _s.setImageBrightness({float(factor)}, {name!r})\n",
        )
        return ok(result)

    @mcp.tool()
    async def set_image_grayscale(name: str, mode: Mode = "auto") -> dict:
        """Toggle the grayscale effect on the image in this frame."""
        result = await run(
            ctx, mode, f"import scribus as _s\n_value = _s.setImageGrayscale({name!r})\n"
        )
        return ok(result)

    @mcp.tool()
    async def get_image_page(name: str, mode: Mode = "auto") -> dict:
        """Return which page of a multi-page image is shown. 0 means automatic."""
        result = await run(
            ctx, mode, f"import scribus as _s\n_value = _s.getImagePage({name!r})\n"
        )
        return ok(result, page=result.value if result.ok else None)

    @mcp.tool()
    async def get_image_page_count(name: str, mode: Mode = "auto") -> dict:
        """Return how many pages the loaded image has."""
        result = await run(
            ctx, mode, f"import scribus as _s\n_value = _s.getImagePageCount({name!r})\n"
        )
        return ok(result, pages=result.value if result.ok else None)

    @mcp.tool()
    async def set_image_page(name: str, page: int, mode: Mode = "auto") -> dict:
        """Choose a page of a multi-page image. 0 means automatic."""
        if page < 0:
            return fail("page must be >= 0")
        result = await run(
            ctx,
            mode,
            f"import scribus as _s\n_value = _s.setImagePage({int(page)}, {name!r})\n",
        )
        return ok(result)

    @mcp.tool()
    async def set_image_preview(name: str, resolution: str = "normal", mode: Mode = "auto") -> dict:
        """Set the on-canvas preview to full, normal, or low. Export resolution is unchanged."""
        if resolution not in _PREVIEW:
            return fail(f"resolution must be one of {sorted(_PREVIEW)}")
        result = await run(
            ctx,
            mode,
            "import scribus as _s\n"
            f"_value = _s.setImagePreviewResolution({_PREVIEW[resolution]}, {name!r})\n",
        )
        return ok(result)

    @mcp.tool()
    async def get_image_preview(name: str, mode: Mode = "auto") -> dict:
        """Return the on-canvas preview resolution: full, normal, or low."""
        result = await run(
            ctx,
            mode,
            f"import scribus as _s\n_value = _s.getImagePreviewResolution({name!r})\n",
        )
        if not result.ok:
            return ok(result)
        try:
            label = _PREVIEW_NAMES.get(int(result.value), str(result.value))
        except (TypeError, ValueError):
            label = result.value
        return ok(result, resolution=label)

    @mcp.tool()
    async def scale_frame_to_image(name: str, mode: Mode = "auto") -> dict:
        """Resize the frame to the loaded image's pixel size."""
        result = await run(
            ctx, mode, f"import scribus as _s\n_value = _s.setScaleFrameToImage({name!r})\n"
        )
        return ok(result)

    @mcp.tool()
    async def place_vector_file(
        path: str,
        x_mm: float,
        y_mm: float,
        kind: str = "vector",
        mode: Mode = "auto",
    ) -> dict:
        """Place an external vector file on the current page.

        ``kind`` is vector (any format Scribus can place), svg, eps, odg, or sxd.
        Returns the names of the objects Scribus selected after the import.
        """
        if kind not in _PLACE:
            return fail(f"kind must be one of {sorted(_PLACE)}")
        body = mm(
            f"_s.{_PLACE[kind]}({path!r}, {x_mm}, {y_mm})\n"
            "_value = [_s.getSelectedObject(_i) for _i in range(_s.selectionCount())]\n"
        )
        result = await run(ctx, mode, body)
        return ok(result, names=result.value if result.ok else None)
