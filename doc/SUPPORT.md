# Scribus Scripter API support matrix

Status of every Scribus 1.6 / 1.7 Scripter function we have considered, broken down by category. The goal is to help you (or an agent) quickly answer:

> "Can scribus-mcp do X?" — and if not, "where is the gap?"

The original tool surface works on both Scribus 1.6 and 1.7. `create_qr_code_block` is flagged `(req. Scribus 1.7+)` and gated at runtime, so calling it on 1.6 returns a structured `required_version` payload (see the README's *Scribus version requirements per feature* section). Tools in `src/scribus_mcp/tools/extended/` call the Scribus 1.7.4 names and are not version-gated; on 1.6 a missing name comes back as `ok: false` with Scribus's error. Where 1.7.4 renamed a call, the matching tool tries the name that exists (`setMargins`, `setNewName`, `outlineText`, `setFontFeatures`).

## Legend

| Mark | Meaning |
|---|---|
| **Yes** | Exposed as a dedicated MCP tool (or as a documented arg of one). Full coverage, validation, structured response. |
| **Partial** | Reachable via the `script` body of another tool (e.g. used inside `create_numbered_badge`, `preflight_check`, `markdown_import`) but not a tool of its own. Available to power users who pass raw Python; not a first-class MCP verb. |
| **No** | Not exposed. Either out of scope for now, or low value compared to building blocks already shipped. |
| **N/A** | Function exists in the Scripter API but is non-deterministic in headless mode (modal dialogs, busy cursors, etc.) — covered only inside the bridge for diagnostics. |

The "MCP tool" column points to the verb name a caller should look up. Multiple Scripter functions can map to one tool when the higher-level shape is more useful (e.g. `apply_gradient` wraps `setGradientFill`).

## How to verify on your install

The tables below are curated from the Scribus 1.7.4 Scripter surface and our own usage on 1.6.x and 1.7.x. If you suspect a drift, run this from inside Scribus (Script → Execute Script):

```python
import scribus, json, os
api = sorted(a for a in dir(scribus) if not a.startswith('_') and callable(getattr(scribus, a)))
log = os.path.join(os.environ.get('LOCALAPPDATA', os.path.expanduser('~')), 'scribus-mcp', 'api.txt')
with open(log, 'w', encoding='utf-8') as f:
    for name in api:
        f.write(name + '\n')
scribus.messageBox('scribus-mcp', f'Wrote {len(api)} names to:\n{log}')
```

The resulting `api.txt` is the ground truth for your Scribus build.

---

## Document lifecycle

| Scripter function | Supported | Description | MCP tool / remarks |
|---|---|---|---|
| `newDocument` | **Yes** | Create a new document (size, margins, orientation, units, columns). | `create_document` |
| `newDocDialog` | **No** | Pops the New Document modal. | Modal — out of scope for MCP. |
| `closeDoc` | **Yes** | Close current document. | `close_document` |
| `haveDoc` | **Yes** | Returns True if any doc is open. | `has_document` (also surfaced via `scribus://document/info`). |
| `openDoc` | **Yes** | Open an existing `.sla`. | `open_document` |
| `saveDoc` | **Yes** | Save under existing path. | `save_document` |
| `saveDocAs` | **Yes** | Save to a new path. | `save_document_as` |
| `revertDoc` | **Yes** | Reload from disk discarding edits. | `revert_document`. |
| `getDocName` | **Yes** | Path of the current document. | `get_document_name`. |
| `setUnit` / `getUnit` | **Yes** | Document unit (mm, pt, in, p, cm, c). | `get_unit` / `set_unit` (string-based). MCP geometry tools still take mm regardless. |
| `setRedraw` / `redrawAll` | **No** | Toggle / force canvas redraw. | Bridge handles redraws at job boundaries; not exposed. |
| `setInfo` | **Yes** | Set Title / Author / Description metadata. | Via `set_document_metadata`. |
| `getInfo` | **Yes** | Read back metadata. | `get_document_metadata`. On Scribus 1.7.4 `getInfo()` returns an empty string after a successful `setInfo`; the values are still stored on the document. |
| `setRTL` / `getRTL` | **Yes** | Right-to-left page order. | `set_document_right_to_left` / `get_document_right_to_left`. |
| `docChanged` | **Yes** | Unsaved-changes flag. | `mark_document_changed`. |
| `getBleeds` / `setBleeds` | **Yes** | Bleed distances in mm. | `get_bleeds` / `set_bleeds`. |
| `getBaseLine` / `setBaseLine` | **Yes** | Baseline grid spacing and offset in mm. | `get_baseline_grid` / `set_baseline_grid`. |
| `setDocType` | **Yes** | Facing pages and which side page 1 sits on. | `set_facing_pages`. |
| `progressReset` / `progressSet` / `progressTotal` | **No** | UI progress bar. | Out of scope for headless flow. |

## Pages

| Scripter function | Supported | Description | MCP tool / remarks |
|---|---|---|---|
| `pageCount` | **Yes** | Number of pages. | `get_page_count` |
| `currentPage` | **Yes** | Index of current page. | `get_current_page` |
| `gotoPage` | **Yes** | Jump to a page. | `goto_page` |
| `newPage` | **Yes** | Insert a page (before/after). | `add_page` |
| `deletePage` | **Yes** | Delete a page. | `delete_page` |
| `movePage` | **Yes** | Reorder pages. | `move_page(from_page, to_page, position=before/after/at_end)`. Scribus 1.7.4 has no `movePage`; that build returns an error and `import_pages` is how pages come in from another file. |
| `getPageSize` / `pageDimension` | **Yes** | Width/height of current page in mm. | `get_page_size` (forces mm; also surfaced via `scribus://document/info`). |
| `setCurrentPageSize` | **Yes** | Resize the current page. | `set_page_size`. |
| `getPageNSize` | **Yes** | Width/height of a page by number. | `get_page_size_at`. |
| `getPageType` | **Yes** | Left, middle, or right page. | `get_page_type`. |
| `getPageMargins` | **Yes** | Read page margins (top/left/right/bottom in mm). | `get_page_margins`. |
| `getPageNMargins` | **Yes** | Margins of a page by number, same order. | `get_page_margins_at`. |
| `setPageMargins` / `setMargins` | **Yes** | Write page margins (mm). | `set_page_margins`. Scribus takes `(left, right, top, bottom)`. 1.6 names the call `setPageMargins`; 1.7.4 names it `setMargins`. |
| `getHGuides` / `setHGuides` | **Yes** | Horizontal guide y-positions (mm). | `get_horizontal_guides` / `set_horizontal_guides`. |
| `getVGuides` / `setVGuides` | **Yes** | Vertical guide x-positions (mm). | `get_vertical_guides` / `set_vertical_guides`. |
| `getColumnGuides` / `setColumnGuides` | **Yes** | Even column guides (count, gap, reference). | `get_column_guides` / `set_column_guides`. Count 0 clears them. Reference is page, margin, or selection. |
| `getRowGuides` / `setRowGuides` | **Yes** | Even row guides. | `get_row_guides` / `set_row_guides`. |
| `masterPageNames` | **Yes** | List all master pages. | `list_master_pages` |
| `createMasterPage` | **Yes** | Create a master page. | `create_master_page` |
| `applyMasterPage` | **Yes** | Apply master to a page. | `apply_master_page` |
| `getMasterPage` | **Yes** | Master applied to a page. | `get_applied_master_page`. |
| `deleteMasterPage` | **Yes** | Remove a master page. | `delete_master_page`. |
| `editMasterPage` / `closeMasterPage` | **Yes** | Enter and leave master-page editing. | `edit_master_page` / `close_master_page`. Objects created while a master is open land on that master. |
| `importPage` | **Yes** | Import pages from another `.sla`. | `import_pages`. |
| `currentPageNumberForSection` | **Yes** | Page number within the current section. | `get_section_page_number`. |

## Frames & object creation

| Scripter function | Supported | Description | MCP tool / remarks |
|---|---|---|---|
| `createText` | **Yes** | Text frame at (x, y, w, h). | `create_text_frame`, also used internally by every text-bearing pattern. |
| `createImage` | **Yes** | Image frame. | `create_image_frame`, `create_image_caption`. |
| `createRect` | **Yes** | Rectangle. | `create_rectangle`, used by all card/callout patterns. |
| `createEllipse` | **Yes** | Ellipse / circle. | `create_ellipse`. |
| `createLine` | **Yes** | Single straight line. | `create_line`. |
| `createPolyLine` | **Yes** | Open polyline. | `create_polyline`. |
| `createPolygon` | **Yes** | Closed polygon. | `create_polygon`. Takes `list[tuple[float, float]]` of points in mm. |
| `createBezierLine` | **Yes** | Bezier curve. | `create_bezier_line`. |
| `createPathText` | **Yes** | Text along a path. | `create_path_text`. |
| `createBarcode` | **Yes** | Barcode/QR code. **(req. Scribus 1.7+)** | `create_qr_code_block` pattern; gated at runtime — calling on 1.6 returns `ok=false` with `required_version="1.7.0"`. Also needs Ghostscript on the host. |
| `createTable` | **Yes** | Native Scribus table object. | `create_table`. Cell tools are listed under [Tables](#tables-scribus-native-tables). `create_comparison_table` is still the composed rect-and-text pattern. |
| `createCustomLineStyle` | **Yes** | Define a multi-segment line style. | `create_line_style`. Apply it with `set_custom_line_style`. |
| `groupObjects` | **Yes** | Group a list of objects by name. | `group_objects` (returns the new group's name). |
| `unGroupObjects` | **Yes** | Ungroup. | `ungroup_objects`. The name may be the group or a member. |
| `combinePolygons` | **Yes** | Boolean union of polygons. | `combine_polygons`. |
| `duplicateObjects` | **Yes** | Duplicate by name. | `duplicate_objects`. Returns the new names. |
| `copyObjects` / `pasteObjects` | **Yes** | Session clipboard. | `copy_objects` / `paste_objects`. Paste only sees the clipboard of the same running Scribus. A later headless call is a new process. The singular `copyObject` / `pasteObject` aliases are not wrapped. |
| `deleteObject` | **Yes** | Remove an object. | `delete_object`. |
| `objectExists` | **Yes** | Test name presence. | `object_exists`. |
| `selectObject` / `deselectAll` / `selectionCount` / `getSelectedObject` | **Yes** | Selection model. | `select_objects`, `deselect_all`, and (interactive, with the bridge) `get_selection`. Headless has no canvas selection to read. `format_selected_text` and `set_selection_colors` act on the current selection. |

## Object geometry & manipulation

| Scripter function | Supported | Description | MCP tool / remarks |
|---|---|---|---|
| `moveObject` | **Yes** | Move by delta. | `move_object(absolute=False)`. |
| `moveObjectAbs` | **Yes** | Move to absolute coordinates. | `move_object(absolute=True)`. Also used internally by `create_numbered_badge` to recenter outlined glyphs. |
| `sizeObject` | **Yes** | Resize an object. | `resize_object`. |
| `rotateObject` / `rotateObjectAbs` | **Yes** | Rotate by delta / to absolute angle. | `rotate_object(absolute=False/True)`. |
| `scaleGroup` | **Yes** | Scale a group proportionally. | `scale_group(name, factor)`. |
| `getPosition` | **Yes** | (x, y) of object in mm. | `get_object_position` (forces mm before reading). |
| `getSize` | **Yes** | (w, h) of object in mm. | `get_object_size` (forces mm before reading). |
| `traceText` / `outlineText` | **Yes** | Convert text frame to vector outlines. | `outline_text` (returns the names of generated polygons). 1.7 calls `outlineText`; `traceText` is the older name. |
| `getRotation` | **Yes** | Rotation in degrees, clockwise positive. | `get_object_rotation`. |
| `getBoundingBox` / `getVisualBoundingBox` | **Yes** | Object bounds in mm. | `get_bounding_box` / `get_visual_bounding_box`. |
| `getObjectType` | **Yes** | Scribus item type. | `get_object_type`. |
| `getItemPageNumber` | **Yes** | Page the object sits on. | `get_object_page`. |
| `flipObject` | **Yes** | Toggle horizontal and/or vertical flip. | `flip_object`. Each call flips; it does not set an absolute mirrored state. |
| `moveSelectionToFront` / `moveSelectionToBack` | **Yes** | Stacking order. | `bring_to_front` / `send_to_back`. |
| `setExportableObject` / `isExportable` | **Yes** | Include the object in export. | `set_object_exportable` / `is_object_exportable`. |
| `getObjectAttributes` / `setObjectAttributes` | **Yes** | Object attribute rows. | `get_object_attributes` / `set_object_attributes`. |
| `lockObject` / `isLocked` | **Yes** | Lock/unlock for editing. | `set_object_locked(name, locked)` (idempotent — reads first, toggles only if needed) and `is_object_locked`. |
| `getName` / `renameObject` / `setNewName` | **Yes** | Read/write object name. | `get_object_name` / `rename_object`. 1.6 uses `getName` and `renameObject`. 1.7.4 has no `getName` (the tool confirms with `objectExists`) and renames with `setNewName(new, old)`. |
| `getPropertyNames` / `getProperty` / `setProperty` | **Yes** | Qt property reflection. | `list_object_properties` / `get_object_property` / `set_object_property`. `find_objects` still uses the property path internally. |
| `itemNumberFromName` | **No** | Resolve name to internal index. | Not relevant — we never expose internal indices. |

## Text content & flow

| Scripter function | Supported | Description | MCP tool / remarks |
|---|---|---|---|
| `setText` | **Yes** | Replace a frame's text. | `set_text` (and used inside ~25 other tools). |
| `insertText` | **Partial** | Insert at offset. | Used inside `append_text`. |
| `deleteText` | **Yes** | Delete the current text selection. | `delete_text`. Select a range first with `select_text` or `select_frame_text`. |
| `getAllText` | **Yes** | Full story text. | `get_text`. |
| `getFrameText` | **Yes** | Only laid-out (visible) text. | `get_visible_text`. May return empty if not yet laid out. |
| `selectText` | **Yes** | Select a character range in the story. | `select_text`. Also used internally by `create_image_caption`, `create_code_sample`, `import_markdown`. |
| `selectFrameText` | **Yes** | Select a range in the current frame. | `select_frame_text`. Count 0 clears the selection. Count -1 runs to the end of the frame. |
| `getSelectedTextRange` / `getFrameSelectedTextRange` | **Yes** | Read the current selection. | `get_text_selection`. |
| `getTextLines` | **Yes** | Number of laid-out lines. | `get_text_lines`. |
| `getTextLength` | **Yes** | Character count of story. | `get_text_length`. |
| `linkTextFrames` | **Yes** | Link frames into a chain. | `link_text_frames`. |
| `unlinkTextFrames` | **Yes** | Break a link. | `unlink_text_frames`. |
| `getFirstLinkedFrame` / `getPrevLinkedFrame` / `getNextLinkedFrame` / `getLastLinkedFrame` | **Yes** | Walk a text chain. | `get_text_chain`. |
| `hyphenateText` / `dehyphenateText` | **Yes** | Hyphenation for one frame. | `hyphenate_text` / `dehyphenate_text`. |
| `insertHtmlText` | **Yes** | Import HTML from a file into a frame. | `insert_html_text`. The argument is a file path. |
| `setTextDistances` / `getTextDistances` | **Yes** | Text inset, in mm. | `set_text_distances` / `get_text_distances`. |
| `setTextFlowMode` / `getTextFlowMode` | **Yes** | How text flows around the object. | `set_text_flow` / `get_text_flow`. Modes: none, frame, bounding_box, contour, clip. |
| `textOverflows` | **Yes** | True if frame has overset text. | `is_text_overflowing`. |
| `layoutText` / `layoutTextChain` | **Yes** | Force re-layout. | `layout_text(chain=False/True)`. |

## Text formatting

| Scripter function | Supported | Description | MCP tool / remarks |
|---|---|---|---|
| `setFont` | **Yes** | Set font of a frame. | `set_font`. |
| `getFont` | **Yes** | Read font of a frame. | `get_text_frame_font`. |
| `setFontSize` | **Yes** | Set point size. | `set_font_size`. |
| `getFontSize` | **Yes** | Read point size. | `get_font_size`. |
| `setTextColor` | **Yes** | Set text fill color (per-range with `selectText`). | `set_text_color` + used inside `create_image_caption`, `create_code_sample`, `import_markdown`. |
| `setTextShade` | **Yes** | Tint text color 0–100. | `set_text_shade`. |
| `setTextAlignment` | **Yes** | left / center / right / justify / forced. | `set_text_alignment`. |
| `setTextVerticalAlignment` | **Yes** | top / center / bottom. | `set_text_vertical_alignment`. |
| `setLineSpacing` | **Yes** | Set leading in pt. | `set_line_spacing`. |
| `setLineSpacingMode` | **Yes** | Fixed / automatic / baseline. | `set_line_spacing_mode`. |
| `setColumns` / `setColumnGap` | **Yes** | Multi-column text in a single frame. | `set_columns(name, count)` and `set_column_gap(name, gap_mm)` (forces mm). |
| `setUnderline` / `setStrikethrough` | **Yes** | Underline / strikethrough with offset+width. | `set_underline` / `set_strikethrough` (1/100 pt; `-1` = font default). Also `_pt` variants accepting points (`-1.0` = font default). Scribus 1.7.4 has neither function; those tools set the `underline` and `strike` font features, and the width applies only when the 1.6 function exists. |
| `setOutline` | **Yes** | Glyph outline width. | `set_outline(name, width_hpt)` (1/100 pt) and `set_outline_pt(name, width_pt)`. On 1.7.4 this sets the `outline` font feature. |
| `setShadow` | **Yes** | Drop-shadow offsets. | `set_shadow(name, x_offset_hpt, y_offset_hpt)` (1/100 pt) and `set_shadow_pt(name, x_offset_pt, y_offset_pt)`. On 1.7.4 this sets the `shadowed` font feature. |
| `setFontFeatures` / `getFontFeatures` | **Yes** | Comma-separated font feature tokens. | `set_font_features` / `get_font_features`. Tokens have no spaces. |
| `setTracking` / `getTracking` | **Yes** | Character tracking. | `set_tracking` / `get_tracking`. |
| `setWordTracking` / `getWordTracking` / `setMinWordTracking` / `getMinWordTracking` | **Yes** | Word spacing. | `set_word_tracking`, `get_word_tracking`, `set_min_word_tracking`, `get_min_word_tracking`. |
| `setTextDirection` | **Yes** | Left-to-right or right-to-left text. | `set_text_direction`. |
| `setTextStroke` | **Yes** | Text stroke color. | `set_text_stroke`. |
| `getTextColor` / `getTextShade` / `getTextVerticalAlignment` | **Yes** | Read text formatting. | `get_text_color`, `get_text_shade`, `get_text_vertical_alignment`. |
| `getLineSpacing` / `getLineSpacingMode` | **Yes** | Read leading. | `get_line_spacing` (points) / `get_line_spacing_mode`. |
| `getColumns` / `getColumnGap` | **Yes** | Read column count and gap. | `get_column_count` / `get_column_gap` (gap in mm). |
| `getFirstLineOffset` | **Yes** | Read first-line offset policy. | `get_first_line_offset`. |
| `setTextScalingH` / `setTextScalingV` | **Yes** | Horizontal/vertical glyph scale. | `set_text_horizontal_scale` / `set_text_vertical_scale` (input in percent — converted to Scribus's 1/1000ths). |
| `setFirstLineOffset` | **Yes** | First-line offset mode. | `set_first_line_offset(name, policy=real_glyph_height/font_ascent/line_spacing/baseline_grid)`. |

## Paragraph & character styles

| Scripter function | Supported | Description | MCP tool / remarks |
|---|---|---|---|
| `getParagraphStyles` | **Yes** | List paragraph style names. | `list_paragraph_styles`. |
| `getCharStyles` | **Yes** | List character style names. | `list_character_styles`. |
| `setParagraphStyle` | **Yes** | Apply paragraph style by name. | `apply_paragraph_style`. |
| `setCharacterStyle` | **Yes** | Apply character style by name. | `apply_character_style`. |
| `loadStylesFromFile` | **Yes** | Import styles from another `.sla`. | `import_styles_from_file`. |
| `createParagraphStyle` / `createCharStyle` | **Yes** | Programmatically define a style. | `create_paragraph_style` / `create_character_style`. Keyword names are Scribus's (`alignment`, `linespacingmode`, `features`, `tracking`, …). Paragraph distances are in points. `defineParagraphStyle` / `defineCharStyle` are not on 1.7.4. |
| `getParagraphStyle` / `getCharacterStyle` | **Yes** | Style applied to a frame. | `get_applied_paragraph_style` / `get_applied_character_style`. |
| `removeUnusedStyles` | **Yes** | Drop styles nothing uses. | `remove_unused_styles`. |
| `getLineStyles` / `createCustomLineStyle` | **Yes** | Named multi-segment line styles. | `list_line_styles` / `create_line_style`. |
| `setCustomLineStyle` / `getCustomLineStyle` | **Yes** | Apply a named line style to an object. | `set_custom_line_style` / `get_custom_line_style`. |

## Color management

| Scripter function | Supported | Description | MCP tool / remarks |
|---|---|---|---|
| `getColorNames` | **Yes** | All defined color names. | `list_colors`. |
| `getColorFloat` / `getColorAsRGB` | **Yes** | Read components of a defined color. | `get_color` (CMYK float and RGB int). |
| `defineColorCMYK` | **No** | CMYK 0–255 ints. | Use `define_color_cmyk` (float). |
| `defineColorCMYKFloat` | **Yes** | CMYK 0.0–100.0. | `define_color_cmyk`. |
| `defineColorRGB` | **Yes** | RGB 0–255. | `define_color_rgb` + auto-called by `create_code_sample` for syntax token colors. |
| `defineColorLab` | **Yes** | Lab color. | `define_color_lab` (L 0–100, a/b −128–128). |
| `changeColorRGB` / `changeColorCMYKFloat` | **Yes** | Redefine an existing color. | `change_color_rgb` / `change_color_cmyk`. |
| `deleteColor` | **Yes** | Delete; replaces uses with given color. | `delete_color`. |
| `replaceColor` | **Yes** | Substitute one color for another in the document. | `replace_color`. |
| `isSpotColor` / `setSpotColor` | **Yes** | Spot-color flag. | `is_spot_color` / `set_spot_color`. |

## Object styling (fill, stroke, gradient)

| Scripter function | Supported | Description | MCP tool / remarks |
|---|---|---|---|
| `setFillColor` / `getFillColor` | **Yes** | Fill color. | `set_fill_color` / `get_fill_color`. |
| `setLineColor` / `getLineColor` | **Yes** | Stroke color. | `set_line_color` / `get_line_color`. |
| `setFillShade` | **Yes** | Fill tint 0–100 (cast to int). | `set_fill_shade`. |
| `setLineShade` | **Yes** | Stroke tint 0–100. | `set_line_shade`. |
| `getFillShade` / `getLineShade` | **Yes** | Read tints. | `get_fill_shade` / `get_line_shade`. |
| `setFillTransparency` / `setLineTransparency` | **Yes** | Opacity 0.0–1.0. | `set_fill_transparency`, `set_line_transparency`. |
| `getFillTransparency` / `getLineTransparency` | **Yes** | Read opacity. | `get_fill_transparency` / `get_line_transparency`. 1 is opaque, matching the setters. |
| `setFillBlendmode` / `setLineBlendmode` / `getFillBlendmode` / `getLineBlendmode` | **Yes** | Blend mode (normal, multiply, screen, …). | `set_fill_blend_mode`, `set_line_blend_mode`, `get_fill_blend_mode`, `get_line_blend_mode`. |
| `setLineWidth` / `getLineWidth` | **Yes** | Stroke width pt. | `set_line_width` / `get_line_width`. |
| `setLineStyle` | **Yes** | Solid / dash / dot / etc. | `set_line_style`. |
| `setLineCap` / `getLineCap` | **Yes** | Flat / round / square. | `set_line_cap` / `get_line_cap`. |
| `setLineJoin` / `getLineJoin` | **Yes** | Miter / round / bevel. | `set_line_join` / `get_line_join`. |
| `getLineStyle` | **Yes** | Read solid / dash / dot. | `get_line_style`. |
| `setCornerRadius` / `getCornerRadius` | **Yes** | Rounded rect radius (int-cast). | `set_corner_radius` / `get_corner_radius`. |
| `setGradientFill` | **Yes** | 2-stop gradient (none / horizontal / vertical / diagonal / cross / radial). | `apply_gradient`, `clear_gradient`. Radial anchors at the bbox corner by default — see the docstring for the centering caveat. |
| `setGradientStop` / `getGradientStop` | **Yes** | One gradient stop (color, shade, opacity, ramp position). | `set_gradient_stop` / `get_gradient_stops`. `getGradientStop` returns `(color, opacity, shade)`. |
| `setGradientVector` / `getGradientVector` | **Yes** | Gradient start, end, and focal point in mm. | `set_gradient_vector` / `get_gradient_vector`. |
| `setCustomLineStyle` | **Yes** | Apply a multi-segment line style. | `set_custom_line_style`. |

## Images

| Scripter function | Supported | Description | MCP tool / remarks |
|---|---|---|---|
| `loadImage` | **Yes** | Load file into image frame. | `load_image`, `create_image_caption`. |
| `setImageOffset` | **Yes** | Offset image inside frame. | `set_image_offset`. |
| `setImageScale` | **Yes** | Manual scale factors. | `set_image_scale`. |
| `setScaleImageToFrame` | **Yes** | Auto scale + proportional flag. | `scale_image_to_frame`. |
| `setScaleFrameToImage` | **Yes** | Resize frame to image's pixel size. | `scale_frame_to_image`. |
| `getImageScale` | **Yes** | Read current scale (1 = 100%). | `get_image_scale`. |
| `getImageOffset` | **Yes** | Read image offset in mm. | `get_image_offset`. |
| `getImageFile` | **Yes** | Path of loaded image. | `get_image_file`. |
| `getImageColorSpace` | **Yes** | RGB / CMYK / gray / duotone / monochrome. | `get_image_color_space`. |
| `getImagePpi` | **Yes** | Effective resolution. | `get_image_ppi`. |
| `getImageRotation` / `setImageRotation` | **Yes** | Image rotation inside the frame. | `get_image_rotation` / `set_image_rotation`. |
| `setImageBrightness` | **Yes** | Brightness factor (1 = unchanged). | `set_image_brightness`. |
| `setImageGrayscale` | **Yes** | Toggle grayscale. | `set_image_grayscale`. Each call toggles. |
| `getImagePage` / `setImagePage` / `getImagePageCount` | **Yes** | Page of a multi-page image. | `get_image_page` / `set_image_page` / `get_image_page_count`. Page 0 is automatic. |
| `setImagePreviewResolution` / `getImagePreviewResolution` | **Yes** | On-canvas preview quality. | `set_image_preview` / `get_image_preview` (`full`, `normal`, `low`). |
| `placeVectorFile` / `placeSVG` / `placeEPS` / `placeODG` / `placeSXD` | **Yes** | Place an external vector file. | `place_vector_file` (`kind` is `vector`, `svg`, `eps`, `odg`, or `sxd`). Returns the names Scribus selected after the import. |
| `imageGetColors` / `imageGetCMYK` | **No** | Pixel inspection. | Not yet — outside MCP scope. |

## Layers

| Scripter function | Supported | Description | MCP tool / remarks |
|---|---|---|---|
| `getLayers` | **Yes** | List layer names. | `list_layers`. |
| `getActiveLayer` | **Yes** | Read active. | `get_active_layer`. |
| `setActiveLayer` | **Yes** | Switch active. | `set_active_layer`. |
| `createLayer` | **Yes** | Create. | `create_layer`. |
| `deleteLayer` | **Yes** | Delete. | `delete_layer`. |
| `sendToLayer` | **Yes** | Move object to layer. | `send_to_layer`. |
| `setLayerVisible` | **Yes** | Show/hide. | `set_layer_visible`. |
| `setLayerPrintable` | **Yes** | Toggle printable flag. | `set_layer_printable`. |
| `setLayerLocked` / `isLayerLocked` | **Yes** | Lock/unlock layer. | `set_layer_locked` / `is_layer_locked`. On Scribus 1.7.4 `setLayerLocked(name, True)` leaves the layer unlocked, so the tool passes the opposite flag and then reads `isLayerLocked`. |
| `setLayerOutlined` / `isLayerOutlined` | **Yes** | Outline display. | `set_layer_outlined` / `is_layer_outlined`. |
| `setLayerFlow` / `isLayerFlow` | **Yes** | Text flow against the layer. | `set_layer_text_flow` / `is_layer_text_flow`. |
| `isLayerVisible` / `isLayerPrintable` | **Yes** | Read visibility and print flags. | `is_layer_visible` / `is_layer_printable`. |
| `setLayerBlendmode` / `getLayerBlendmode` | **Yes** | Layer blend mode. | `set_layer_blend_mode` / `get_layer_blend_mode`. |
| `setLayerTransparency` / `getLayerTransparency` | **Yes** | Layer opacity, 0–1, 1 = opaque. | `set_layer_transparency` / `get_layer_transparency`. |
| `raiseActiveLayer` / `lowerActiveLayer` | **Yes** | Reorder the active layer. | `raise_active_layer` / `lower_active_layer`. |

## Search & inspection

| Scripter function | Supported | Description | MCP tool / remarks |
|---|---|---|---|
| `getPageItems` | **Yes** | List `(name, type, info)` per page. | `list_page_objects` (also used internally by `find_objects`, `preflight_check`, all resources). |
| `getAllObjects` | **No** | Cross-page version. | Use `find_objects` (which iterates pages). |
| `isAnnotated` | **Yes** | True if object is a PDF annotation; returns metadata tuple. | `is_annotated`. |
| `isPDFBookmark` / `setPDFBookmark` | **Yes** | PDF bookmark flag on an object. | `is_pdf_bookmark` / `set_pdf_bookmark`. |

## Export

| Scripter function | Supported | Description | MCP tool / remarks |
|---|---|---|---|
| `PDFfile` (class) | **Yes** | PDF export configuration object. | Used by `export_pdf` (preset, range, compression, fonts embed/subset). |
| `ImageExport` (class) | **Yes** | Page-to-image export. | Used by `render_page_to_image` (PNG, base64-inlined as MCP image content). |
| `saveAsImage` (instance method) | **Partial** | Image export call. | Inside `render_page_to_image`. |
| Preflight | **Yes (custom)** | We re-implement preflight in Python by walking `getPageItems` + `getFontNames`. | `preflight_check` (returns issues + used fonts). |
| `savePageAsEPS` | **Yes** | Export the current page as EPS. | `save_page_as_eps`. |
| `readPDFOptions` / `savePDFOptions` | **Yes** | Read and write a PDF options file. | `read_pdf_options` / `save_pdf_options`. |
| `placeODT` | **No** | Place an ODT document. | Not wrapped. Vector placement is `place_vector_file`. |

## PDF annotations & forms

| Scripter function | Supported | Description | MCP tool / remarks |
|---|---|---|---|
| `createPdfAnnotation` | **Yes** | Create a PDF form field (button, text, checkbox, radio, combo, list, sticky note, link, 3D). | All 6 form-field tools (`create_pdf_text_field`, `create_pdf_checkbox`, `create_pdf_radio_button`, `create_pdf_combo_box`, `create_pdf_list_box`, `create_pdf_push_button`). 3D annotations require OSG and aren't exposed. |
| `setLinkAnnotation` | **Yes** | Internal page link on a text frame. | `create_link_annotation` (auto-creates frame if needed). All numeric args are int-cast. |
| `setURIAnnotation` | **Yes** | External URL link. | `create_uri_annotation`. |
| `setFileAnnotation` | **Yes** | Link to an external file (relative / absolute). | `create_file_annotation`. |
| `setTextAnnotation` | **Yes** | Sticky-note PDF annotation with icon. | `create_text_annotation` (9 icons). |
| `setJSActionScript` | **Yes** | Attach JS to a field event. | `set_js_action`, also used inline by `create_pdf_push_button`. |
| `getJSActionScript` | **Yes** | Read JS on an event. | `get_js_action`. |
| `isPDFBookmark` / `setPDFBookmark` | **Yes** | PDF bookmarks. | `is_pdf_bookmark` / `set_pdf_bookmark`. |

## UI / dialogs / app state

| Scripter function | Supported | Description | MCP tool / remarks |
|---|---|---|---|
| `messageBox` | **N/A** | Modal message. | Used by the bridge for fatal-error reporting only. Tools never invoke modals. |
| `valueDialog` / `inputDialog` / `fileDialog` / `newStyleDialog` | **N/A** | Other modals. | Out of scope — modals don't fit MCP request/response. |
| `statusMessage` / `setBookmark` / `haveSpellCheck` | **No** | App utilities. | Not yet — low value for headless. |
| `zoomDocument` / `getZoomFactor` / `scrollDocument` | **No** | Canvas viewport. | Not yet — interactive-only utility. |
| `setBusyCursor` | **No** | Cursor toggle. | Not yet. |
| `runScribusCommand` | **No** | Invoke a Scribus action by name. | Not yet — surface is brittle. |

## Fonts

| Scripter function | Supported | Description | MCP tool / remarks |
|---|---|---|---|
| `getFontNames` | **Yes** | Flat list of font names. | `list_fonts`. |
| `getXFontNames` | **Yes** | Detailed (family, name, file, ps_name, embed). | `list_fonts_detailed`. |
| `getFont` | **Yes** | Frame's current font. | `get_text_frame_font`. |
| `setFont` | **Yes** | Set frame's font. | `set_font` + auto-resolved by `create_code_sample`. |
| (no Scripter equivalent) | **Partial** | Add a new font at runtime. | Not possible via Scripter — Scribus only scans fonts at startup. We expose a *staging* path: `install_custom_font` copies the .ttf/.otf/.ttc/.pfa/.pfb into a managed dir and patches Scribus's per-user prefs XML to add that dir to *Additional Font Paths*. Takes effect on the **next Scribus launch**. |
| `list_extra_font_dirs` (MCP-only) | **Yes** | Read additional font dirs registered in Scribus's prefs. | `list_extra_font_dirs`. |
| `list_monospace_fonts` (MCP-only) | **Yes** | Filter loaded fonts by name heuristic. | `list_monospace_fonts` — used as a fallback by `create_code_sample` when no `font` is passed. |
| `font_is_available` (MCP-only) | **Yes** | Check before applying — `setFont` raises if absent. | `font_is_available`. |

## Tables (Scribus native tables)

Cell indices are 0-based. Widths and heights are millimetres. `create_comparison_table` is a separate composed pattern (rectangles and text frames) and does not create a Scribus table object.

| Scripter function | Supported | Description | MCP tool / remarks |
|---|---|---|---|
| `createTable` | **Yes** | Table frame. | `create_table`. |
| `getTableRows` / `getTableColumns` | **Yes** | Row and column counts. | `get_table_size`. |
| `setCellText` / `getCellText` | **Yes** | Cell text. | `set_cell_text` / `get_cell_text`. |
| `setCellFillColor` / `getCellFillColor` | **Yes** | Cell fill. | `set_cell_fill` / `get_cell_fill`. |
| `setCellStyle` / `getCellStyle` | **Yes** | Style name on a cell. | `set_cell_style` / `get_cell_style`. |
| `getCellRowSpan` / `getCellColumnSpan` / `mergeTableCells` | **Yes** | How many rows and columns a cell covers, and merging. | `get_cell_span` / `merge_table_cells`. |
| `insertTableRows` / `insertTableColumns` | **Yes** | Insert rows or columns. | `insert_table_rows` / `insert_table_columns`. |
| `removeTableRows` / `removeTableColumns` | **Yes** | Remove rows or columns. | `remove_table_rows` / `remove_table_columns`. |
| `resizeTableColumn` / `getTableColumnWidth` / `resizeTableRow` / `getTableRowHeight` | **Yes** | Column width and row height in mm. | `set_table_column_width`, `get_table_column_width`, `set_table_row_height`, `get_table_row_height`. |
| `setCellTopBorder` / `setCellBottomBorder` / `setCellLeftBorder` / `setCellRightBorder` | **Yes** | One cell edge: width in points, line style, color. | `set_cell_border`. Edges are top, bottom, left, right. Several line entries make a multi-stroke border. |
| `setTableTopBorder` / `setTableBottomBorder` / `setTableLeftBorder` / `setTableRightBorder` | **Yes** | Outer table edge, same line shape. | `set_table_border`. |
| `setTableStyle` / `getTableStyle` / `getTableStyles` / `getCellStyles` | **Yes** | Named table and cell styles. | `set_table_style` / `get_table_style` / `list_table_styles` / `list_cell_styles`. |

---

## Summary

The server registers 362 tools. The `SCRIBUS_MCP_TOOLSET=ads` subset is the compact ad and flyer set and does not include the extended Scripter tools.

Items still in the **No** column are modal dialogs, canvas chrome (zoom, scroll, redraw, progress, cursor), and a few leftovers (`selectAll`, `placeODT`, integer `defineColorCMYK`, `imageGetColors`). Deprecated aliases (`newDoc`, `setStyle`, `getText`, `scaleImage`, `copyObject`, `pasteObject`) are not wrapped; the current function is.

If you hit a function that's in **No** and would unblock a real task, file it and we'll wire a tool. The `run_script` tool (raw Python passthrough, off by default) is the escape hatch for anything not promoted yet.
