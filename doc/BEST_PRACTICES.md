# scribus-mcp — best practices for driving the tool surface

This is the "house style" for an LLM composing Scribus documents through
the MCP. Follow these rules and the result will read like a designed
deliverable, not a wall of frames.

The same content is exposed as the `best_practices` MCP prompt — when an
agent driving the MCP fetches that prompt, it gets this file verbatim.

## Ads, flyers, posters (and Indian newspaper ads): the 8 rules

1. **Start from a template.** Flow: user describes the need -> `find_templates` (ranked
   shortlist with a numbered contact sheet and previews; show them to the USER and ask which
   one, never pick silently; if it says "nothing close", say so) -> `new_from_template(template,
   save_as)` (returns `editable_fields`: object name, role, current text, char budget, logo and
   photo slots) -> ask the user for the missing details (business name, offer, dates, phone,
   address, logo file) -> `fill_template_fields({name or role: text})` (Hindi as Unicode;
   shrink-to-fit with a 5 pt floor; `logo_path` fills the logo slot) -> `verify_document` ->
   `render_preview` (look at it) -> `export_press_pdf`. `list_templates` (filter by `query` /
   `category`) browses the library by text. Only when nothing fits use `create_document`
   (set all margins to 0 for a full-bleed flyer). `suggest_fonts` lists the installed fonts
   by role (condensed display, bold headline, slogan italic, Devanagari, Kruti Dev).
2. **One visual element = one tool call.** A banner, button, price tag, phone bar or title is
   `create_text_box` (fill, border, rounded corners, padding and text in ONE object; the text
   is vertically centred and auto-fitted). Do NOT stack `create_rectangle` + `create_text_frame`:
   that gives double outlines (rectangles get a default black stroke), text that does not follow
   the box, and boxes that do not wrap their text.
   - Headline in a panel: `create_text_box(..., font="Impact Regular", fit="fill")` and mixed
     sizes via `runs=[{"text": "ADMISSION OPEN\n", "size_pt": 40}, {"text": "2027-28", ...}]`.
   - Circle seal / "Ranked 7th": `create_badge` (ring styles solid, dashed, dotted, double).
   - Feature list: `create_bullet_list(items, ..., columns=2 or column_split=[9, 6])`.
   - NOTE / Call bar: `create_label_bar` or a `pill` `create_text_box`.
   - Swooshes, leaf fans, ragged banner backgrounds, stars: `create_decor_shape`.
3. **Order is z-order.** Create backgrounds and decor first, text boxes last. Colours may be
   `#RRGGBB` or basic names; they are defined on the fly (older versions silently used black).
4. **Fit, never guess sizes.** `fit="shrink"` (default) lowers the font until the text fits,
   `fit="fill"` finds the largest size that fits (`max_font_pt` caps it), `no_wrap=True` keeps
   a title on one line. `fit_text_to_frame` does the same for an existing frame. Leading is
   automatic in every new tool: a plain `create_text_frame` has FIXED 15 pt leading, so 40 pt
   type overprints itself. If you use primitives, call `set_line_spacing_mode` first.
5. **Hindi.** Pass Unicode Hindi; the composed tools convert it to Kruti Dev 010 keystrokes and
   set the font on the Hindi runs only (`set_text_hindi` for an existing frame,
   `convert_unicode_to_kruti` to just see the conversion). Never put Unicode into a Kruti
   font and never put Kruti keystrokes into a normal font. Kruti Dev has no bold.
6. **Press rules.** Nothing below 5 pt (the tools clamp to 5, `verify_document` flags it).
   Final output: `export_press_pdf(path, standard="X-1a")` (X-3 / X-4 also supported); it
   refuses to export while verification errors exist.
7. **Do not group what you may edit.** Objects inside a group cannot be addressed by name, so
   their text cannot be changed, fitted or verified. The composed tools do not group by default.
8. **Verify, then look.** Run `verify_document` (overflow incl. linked frames, text < 5 pt,
   objects off page, missing/changed fonts, Hindi in the wrong font, Kruti in the wrong font,
   empty frames, missing images, overlaps) until `errors == 0`, then `render_preview` and
   compare the picture with the brief (alignment, colours, hierarchy) before saying done.
   `align_objects` / `distribute_objects` fix alignment without guessing millimetres.

Small models: start the server with `SCRIBUS_MCP_TOOLSET=ads` to see ~70 tools instead of ~190.

## Composition: prefer patterns and layouts over primitives

The MCP exposes both raw primitives (`create_text_frame`, `create_rectangle`)
and composed patterns / layouts (`create_kpi_row`, `create_card_grid`,
`create_callout_box`, `create_radar_chart`, etc.). **Always reach for the
highest-level tool that fits the shape of your content.** Examples:

- 4 stat tiles in a row → `create_kpi_row` (handles widths, gaps, font
  auto-shrink). Don't loop over `create_kpi_tile`.
- 6 feature cards in a 2×3 grid → `create_card_grid`.
- A dashboard chart → `create_bar_chart` / `create_pie_chart` /
  `create_radar_chart` (all return a `bbox` dict you can chain).
- Highlighted code → `create_code_sample` (Pygments-tokenized, monospace
  auto-pick). Don't roll your own with `create_text_frame`.
- A bordered "tip / note / sidebar" block → `create_callout_box`.
- Markdown content → `import_markdown`, never hand-roll headings + bullet
  lists with primitives.
- Anchored stage list → `create_numbered_steps`.

Primitives are for composition glue (decorative shapes, page chrome,
filling gaps the patterns don't cover yet).

## Pointing words (this / that / selected / here): call `get_selection` first

If the user refers to something by pointing, never guess which object or text they mean. Call
`get_selection` (interactive mode, read-only). It returns the page, the selected objects (name, type,
bbox in mm, fill/line colour, font, text preview) and, for one selected text frame, the highlighted range
(`selection_start`, `selection_length`, `selected_text`), the paragraph/word around it and the formatting.
Then act: `format_selected_text(color|font|size_pt)` restyles only the highlighted words (or the whole
frame when nothing is highlighted), `set_selection_colors(fill|line)` recolours the selected objects,
and the usual name-based tools (`move_object`, `resize_object`, `set_text`, ...) take the returned names.
In headless mode there is no selection and the tool says so. Text-edit mode and cursor position are only
reported by a Scribus built with `scripter-selection.patch`; without it `editing`/`cursor` are null and
only a highlighted range is detectable. Note: the Scripter's own `setTextColor/setFont/setFontSize` act on
a frame's highlight if one exists, else on all text.

## Coordinates are millimetres, top-left origin

Every `_mm` parameter is millimetres. `x_mm` / `y_mm` is the **top-left**
of a bbox unless the parameter is explicitly named `center_*` (pie chart,
radar chart, dot label) or `axis_y_mm` / `top_y_mm` (timeline). For
charts that take a center, every slot returned by `PageCursor.split` /
`PageCursor.band` carries `center_x` / `center_y` precomputed — splat
them.

## Vertical flow: use PageCursor for multi-band scripts

```python
from scribus_mcp.layout import PageCursor

pc = PageCursor(x_mm=12, y_mm=22, width_mm=186, default_gap_mm=4)

await t("create_kpi_row", **pc.band(height_mm=38), items=[...])
left, right = pc.split([85, 101], height_mm=45)
await t("create_bar_chart", **left, ...)
await t("create_pie_chart", center_x_mm=right["center_x"], ...)
```

Hand-coding y values per band is the #1 source of overlap bugs. Let the
cursor do the math.

## Patterns return accurate bboxes

`create_bar_chart`, `create_radar_chart`, `create_timeline` all return
`bbox` in their result — that's the **true** total footprint (including
labels, legend, axis halo). Use it to advance `PageCursor` when in
doubt:

```python
r = await t("create_bar_chart", **pc.band(height_mm=50), values=[...])
# pc has already advanced past 50 mm — but if the chart actually drew
# something taller (e.g. a multi-dataset legend pushed the bbox down),
# correct with:
pc.jump_to(r["bbox"]["y_mm"] + r["bbox"]["height_mm"] + pc.default_gap_mm)
```

## Charts: `height_mm` is inclusive

`create_bar_chart.height_mm` is the **total** vertical footprint —
bars + gridlines + bottom category-label strip + legend strip (if
multi-dataset) + value-label strip (if `show_values`). Pass the slot's
full height; don't subtract a manual buffer.

For radar / pie, the chart sits at `(center_*, radius_*)` — labels poke
beyond the rings by `label_offset_mm + label_width_mm/2`. The defaults
(4 + 11 = 15 mm halo on radar) keep the chart tight enough to fit a
half-width column. Returned `bbox` is the truth.

## Compare variants → multi-dataset radar / bar

Pass `datasets=[{label, values, fill_color, …}, ...]` instead of a flat
`values=[...]`. The chart auto-renders a legend below (set
`legend_position="below"`) and overlapping radar polygons get partial
transparency (`fill_alpha=0.5`) so both stay legible.

## Colors must be defined before use

Every Scribus color reference (in any tool's `color`, `fill_color`,
`bar_color` etc.) must be a name **already defined in the document**. The
default palette is just `Black` / `White` plus a CMYK rotation. Define a
brand palette early:

```python
for n, c, m, y, k in (("Brand Deep", 85, 55, 0, 10), ...):
    await t("define_color_cmyk", name=n, cyan=c, magenta=m, yellow=y, key=k)
```

`create_code_sample` is the exception — it auto-defines token colors
from the Pygments style.

## Palette roles — define once, every tool uses them

Every color slot defaults to a **palette role name** instead of `Black`.
Define those role names with `define_color_rgb` / `define_color_cmyk`
once at the top of a script and every later tool inherits the palette
without restating the color on every call. Roles you don't define fall
back to the historical `"Black"` default with the tool's conventional
shade — there's no behaviour change for scripts that ignore the
convention.

The canonical roles (also exposed via `list_palette_roles`):

| Role      | Used for                                                            |
|-----------|---------------------------------------------------------------------|
| `primary` | brand main color (cover band, big titles, dominant accents)         |
| `accent`  | secondary highlight (eyebrows, KPI values, marker fills, badges)    |
| `surface` | light fill for cards, callouts, table backgrounds, sidebars         |
| `ink`     | body text and dark elements (titles, body, table cells)             |
| `muted`   | de-emphasised text, subtle borders, axis lines, table-of-contents leaders |
| `warning` | warning / danger emphasis                                           |
| `success` | success / positive emphasis                                         |
| `subtle`  | even quieter borders / hairlines                                    |

Typical opener:

```python
await t("define_color_rgb", name="primary", red=88, green=23, blue=128)
await t("define_color_rgb", name="accent",  red=0,  green=170, blue=200)
await t("define_color_rgb", name="surface", red=241, green=240, blue=248)
await t("define_color_rgb", name="ink",     red=28, green=30,  blue=42)
await t("define_color_rgb", name="muted",   red=120, green=120, blue=130)
```

After this, `create_card_grid`, `create_callout_box`, `create_kpi_tile`,
`create_section_header`, `create_hero_band`, `create_timeline`, etc. all
adopt the palette automatically. Per-call overrides still work — pass
`accent_color="Brand Coral"` (or another role name) to override one slot.

When a slot resolves to a role color the tool draws it at full shade
(100). When a slot falls back to `"Black"` (role undefined), the tool
keeps the conventional shade — e.g. card fills stay at `Black @ 8%` for
a faint grey background. So define roles at the **final hue you want
drawn**, not a base color the tool will tint.

> **Common pitfall — name your colors with the canonical role names.**
> If you call `define_color_rgb(name="ZephyrPurple", …)` and skip
> `primary` / `accent` / `surface` / `ink` / `muted`, every tool whose
> color slot you *don't* explicitly override will fall back to `"Black"`.
> Visible symptom: hero bands render near-black, numbered-step badges
> render black, card accent stripes render black — even though the
> document palette is full of beautiful brand colors. Either (a) name
> the role colors directly (`name="primary"`) or (b) pass them
> explicitly on every call (`fill_color="ZephyrPurple"`). The first is
> dramatically less typing.

## Markdown handles inline emphasis automatically

`import_markdown` walks inline tokens, strips `**` / `*` / `` ` ``
markers, and re-applies bold / italic / monospace via `selectText` +
`setFont` (auto-discovers the bold/italic/mono variant of the frame's
font family). Don't pre-process markdown yourself — feed the raw source.

## Verify before declaring done

After building, **always**:

1. `preflight_check` — surface text overflow, missing images / fonts.
2. `render_page_to_image` for each page — eyeball the layout. Adjust if
   anything overlaps or sits in the page margin.
3. Only then `export_pdf`.

## Page chrome → master page or a `page_chrome()` helper

Header band, footer, accent rule — these repeat per page. Either build
them on a master page (`create_master_page` + `apply_master_page`) or
write a small `async def page_chrome(t, page_num, ...)` and call it once
per page (the demos use the latter).

## Custom fonts

Scribus only scans fonts at startup. Use `install_custom_font(font_path)`
to copy the file into a managed dir AND patch Scribus's *Additional Font
Paths* prefs — the font becomes available **after the next Scribus
launch**, not in the current session.

## Forms

`create_pdf_text_field` / `create_pdf_checkbox` / `create_pdf_combo_box`
etc. are the form-field tools. `create_link_annotation` /
`create_uri_annotation` / `create_text_annotation` cover navigation +
sticky-note annotations. Pass `target_x_mm` / `target_y_mm` (page coords
the link jumps to) and `frame_x_mm` / `frame_y_mm` / `frame_width_mm` /
`frame_height_mm` (where the clickable rectangle sits on the *current*
page).

## Two frames for left+right page chrome — never pad with spaces

Tempting anti-pattern: stuff a page footer into one text frame as `"Project · License · URL"` + many spaces + `"page 3 / 5"`, hoping the spaces push the right side to the right edge. Don't. In a proportional font, the space width varies per page, the right side never lines up cleanly, and any change in the left text re-flows the gap. The `.sla` ends up with strings like `"…rtos                                            page 5 / 5"` and the rendered page looks ragged.

Use two separate frames instead:

```python
# Footer band: left side and right side as independent frames,
# both aligned to their own edge.
await t("create_text_frame", x_mm=15, y_mm=285, width_mm=120, height_mm=5)
await t("set_text", name=left_name, text="Project · License · URL")
await t("set_text_alignment", name=left_name, alignment="left")

await t("create_text_frame", x_mm=145, y_mm=285, width_mm=50, height_mm=5)
await t("set_text", name=right_name, text=f"page {p} / {n_pages}")
await t("set_text_alignment", name=right_name, alignment="right")
```

`create_hero_band` already handles left+right via its `right_text` parameter — use it for headers. Reach for two-frame composition for footers.

## Cards with short body text — `auto_height=True`

`create_card_grid` and `create_callout_box` accept a fixed `height_mm`. If the body text doesn't fill the card, the trailing space is visible as an empty band — looks unbalanced. Pass `auto_height=True` and the tool measures the rendered body and shrinks the card chrome (background, accent stripe, body frame) so it sits snug against the content. For `create_card_grid`, every card in the same row is then resized to that row's tallest fitted height so the row stays visually uniform.

The result includes `height_mm` (callout) or `grid_height_mm` (card grid) — chain it via `PageCursor.jump_to(...)` so the next band picks up at the actual bottom rather than the originally-requested height.

## Pass plain text — never HTML-escape

Scribus's `setText` takes raw strings. If you pre-encode `&` as `&amp;` (or `<` as `&lt;`, etc.) the way you would for HTML, the encoded form ends up rendered literally in the PDF — Scribus stores user content as XML in the SLA file and re-escapes on save, so a pre-encoded `&amp;` becomes `&amp;amp;` on disk and renders as the five characters `&amp;`.

The MCP defends against this by running `html.unescape` on user-text inputs at the boundary (see `clean_user_text` in `src/scribus_mcp/tools/_common.py`), but you should still pass plain text:

| Don't | Do |
|---|---|
| `"R&amp;D"` | `"R&D"` |
| `"AT&amp;T merger"` | `"AT&T merger"` |
| `"foo &lt;bar&gt;"` | `"foo <bar>"` |

This applies to every tool that accepts user-visible text — `set_text`, `append_text`, `import_markdown`, every pattern's `title` / `caption` / `label` / `body`, every layout's `title` / `eyebrow` / `subtitle` / `right_text`, form `default_value` / `label`, annotation `link_text`, etc. The one exception is `create_code_sample`'s code body — code may legitimately contain literal `&amp;` and is passed through verbatim.

**Typographic entities are preserved.** `&nbsp;` decodes to U+00A0 (a real non-breaking space, *not* a regular space) — Scribus respects it at line-break time, so use it intentionally to keep words glued together: `"Apache&nbsp;2.0"` won't wrap between "Apache" and "2.0". Same goes for `&mdash;` (—), `&ndash;` (–), `&hellip;` (…), `&copy;` (©), etc. — they're decoded to the actual Unicode character, not stripped.

## Version-gated tools

A small number of tools wrap Scripter calls that only exist on Scribus 1.7+. If you call one on 1.6 you get a structured `ok=false` payload like:

```json
{
  "ok": false,
  "error": "create_qr_code_block (...) requires Scribus 1.7.0+ (this Scribus reports 1.6.3). ...",
  "required_version": "1.7.0",
  "actual_version": "1.6.3"
}
```

Surface this verbatim to the user — `required_version` and `actual_version` are stable fields you can pattern-match on. Don't retry the same tool, and don't paper over with primitives unless the user asks. Currently only `create_qr_code_block` is gated; see [doc/SUPPORT.md](SUPPORT.md) for the matrix.

## When in doubt

- Read [doc/SUPPORT.md](SUPPORT.md) — every Scripter function with
  Yes / Partial / No / N/A status.
- Read [doc/COOKBOOK.md](COOKBOOK.md) — end-to-end recipes for
  one-pagers, manuals, dashboards, and reports.
- Inspect the live document with the resources `scribus://document/info`,
  `…/colors`, `…/fonts`, `…/missing-resources`.
