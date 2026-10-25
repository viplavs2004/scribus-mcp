"""Tool modules. Each module exposes a `register(mcp, ctx)` function that
attaches its tools to the FastMCP server."""

from scribus_mcp.tools import (
    ad_boxes,
    arrange,
    templates,
    template_fields,
    template_search,
    decor,
    colors,
    document,
    escape,
    export,
    fonts,
    forms,
    hindi,
    frames,
    images,
    layers,
    layouts,
    markdown,
    pages,
    patterns,
    search,
    selection,
    shapes,
    styles,
    styling,
    text,
    verify,
)


def register_all(mcp, ctx) -> None:
    document.register(mcp, ctx)
    pages.register(mcp, ctx)
    frames.register(mcp, ctx)
    shapes.register(mcp, ctx)
    text.register(mcp, ctx)
    fonts.register(mcp, ctx)
    styles.register(mcp, ctx)
    styling.register(mcp, ctx)
    colors.register(mcp, ctx)
    images.register(mcp, ctx)
    layers.register(mcp, ctx)
    search.register(mcp, ctx)
    export.register(mcp, ctx)
    markdown.register(mcp, ctx)
    patterns.register(mcp, ctx)
    layouts.register(mcp, ctx)
    forms.register(mcp, ctx)
    escape.register(mcp, ctx)
    ad_boxes.register(mcp, ctx)
    decor.register(mcp, ctx)
    arrange.register(mcp, ctx)
    templates.register(mcp, ctx)
    template_search.register(mcp, ctx)
    template_fields.register(mcp, ctx)
    hindi.register(mcp, ctx)
    verify.register(mcp, ctx)
    selection.register(mcp, ctx)


# Compact tool set for small models / ad and flyer work: ``SCRIBUS_MCP_TOOLSET=ads`` keeps only
# these tools (about 60 of ~190). The composed tools come first; primitives stay available
# for the odd thing the composed ones cannot do.
ADS_TOOLSET: tuple[str, ...] = (
    # start / documents
    "list_templates", "find_templates", "new_from_template", "fill_template_fields", "create_document", "open_document",
    "save_document", "save_document_as", "close_document", "get_document_info", "add_page",
    "goto_page", "get_page_size", "set_page_margins",
    # what the user points at (interactive only): get_selection FIRST for this/that/selected
    "get_selection", "format_selected_text", "set_selection_colors",
    # composed building blocks
    "create_text_box", "create_badge", "create_bullet_list", "create_label_bar",
    "create_decor_shape", "fit_text_to_frame",
    # primitives
    "create_rectangle", "create_ellipse", "create_line", "create_polygon",
    "create_text_frame", "create_image_frame", "load_image", "scale_image_to_frame",
    "set_image_scale", "set_image_offset",
    # text
    "set_text", "set_text_hindi", "convert_unicode_to_kruti", "append_text", "get_text",
    "set_font", "set_font_size", "set_text_color", "set_text_alignment",
    "set_text_vertical_alignment", "set_line_spacing", "set_line_spacing_mode",
    "set_text_horizontal_scale", "set_columns", "is_text_overflowing",
    # colour / style
    "set_fill_color", "set_line_color", "set_line_width", "set_corner_radius",
    "apply_gradient", "define_color_rgb", "define_color_cmyk",
    # arrange
    "move_object", "resize_object", "rotate_object", "delete_object", "rename_object",
    "group_objects", "list_page_objects", "find_objects", "align_objects",
    "distribute_objects", "get_object_position", "get_object_size", "send_to_layer",
    # fonts, check, output
    "suggest_fonts", "list_fonts", "font_is_available", "verify_document", "render_preview",
    "export_pdf", "export_press_pdf",
)


def apply_toolset(mcp, name: str | None) -> int:
    """Restrict the registered tools to a named set. Returns the number of tools removed."""
    if not name or name.lower() in ("all", "full"):
        return 0
    if name.lower() != "ads":
        raise ValueError(f"unknown SCRIBUS_MCP_TOOLSET {name!r} (use 'ads' or 'all')")
    keep = set(ADS_TOOLSET)
    removed = 0
    for tool in list(mcp._tool_manager.list_tools()):
        if tool.name not in keep:
            mcp.remove_tool(tool.name)
            removed += 1
    return removed
