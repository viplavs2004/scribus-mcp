from __future__ import annotations

import logging
import os

from mcp.server.fastmcp import FastMCP

from scribus_mcp.backends import HeadlessBackend, InteractiveBackend
from scribus_mcp.config import Config
from scribus_mcp.prompts import register_all as register_prompts
from scribus_mcp.resources import register_all as register_resources
from scribus_mcp.tools import apply_toolset
from scribus_mcp.tools import register_all as register_tools
from scribus_mcp.tools._common import ServerCtx

log = logging.getLogger("scribus_mcp")


INSTRUCTIONS = (
    "Scribus desktop publishing MCP. Tools manipulate Scribus documents via the Scripter "
    "Python API. mode='auto' (default) picks an open Scribus session (interactive) or a fresh "
    "headless run. Coordinates are millimetres (origin top-left); font sizes are points.\n\n"
    "POINTING: if the user refers to something by pointing (this / that / these / selected / here / "
    "'the words I highlighted'), call get_selection FIRST and never guess which object or text is meant. "
    "Then act with the names it returns, or with format_selected_text (colour/font/size of the highlighted "
    "words, or the whole selected frame) and set_selection_colors (fill/line of the selected objects). "
    "Needs a visible Scribus with the bridge; in headless mode there is no selection.\n\n"
    "FOR ADS, FLYERS AND POSTERS (incl. Indian newspaper ads):\n"
    "1. Flow: user describes the need -> find_templates (returns previews: SHOW THEM to the user "
    "and ask which one; never pick silently when several fit) -> new_from_template (returns "
    "editable_fields: roles, current text, char budgets) -> ask the user for the missing details "
    "(name, offer, dates, phone, address, logo file) -> fill_template_fields -> verify_document -> "
    "render_preview (look at it) -> export_press_pdf. If find_templates says nothing is close, say "
    "so and use create_document (margins 0 for full-bleed flyers). list_templates browses the "
    "library by text. suggest_fonts tells you which installed fonts to use.\n"
    "2. Build with the COMPOSED tools, not loose rectangles + text frames: create_text_box "
    "(banner / headline / button / bar: fill, border, rounded corners and text in ONE object, "
    "text auto-fitted and vertically centred), create_badge (circle seal with ring), "
    "create_bullet_list (real bullets, columns, auto-fit), create_label_bar (NOTE: bar), "
    "create_decor_shape (swoosh, leaf fan, brush band, star, burst, ribbon). Background shapes "
    "first, text last (later objects are on top). Colours can be #RRGGBB.\n"
    "3. Hindi: pass normal Unicode Hindi to the text tools; it is converted to Kruti Dev 010 "
    "automatically (set_text_hindi for existing frames). Never paste Unicode into a Kruti font.\n"
    "4. Never use text below 5 pt. Do not group objects you still want to edit (grouped objects "
    "cannot be addressed by name).\n"
    "5. Before you say done: verify_document (fix every error, rerun until errors == 0), then "
    "render_preview and LOOK at the picture. For press output use export_press_pdf "
    "(PDF/X-1a default).\n"
    "Set SCRIBUS_MCP_TOOLSET=ads to expose a compact ~70-tool subset."
)


def build_server(config: Config | None = None) -> FastMCP:
    cfg = config or Config.from_env()
    logging.basicConfig(
        level=cfg.log_level,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    mcp = FastMCP(
        name="scribus-mcp",
        instructions=INSTRUCTIONS,
    )

    headless = HeadlessBackend(cfg)
    interactive = InteractiveBackend(cfg)
    ctx = ServerCtx(config=cfg, headless=headless, interactive=interactive)

    register_tools(mcp, ctx)
    removed = apply_toolset(mcp, os.environ.get("SCRIBUS_MCP_TOOLSET"))
    if removed:
        log.info("SCRIBUS_MCP_TOOLSET active: %d tools hidden", removed)
    register_resources(mcp, ctx)
    register_prompts(mcp, ctx)

    log.info(
        "scribus-mcp ready (scribus_bin=%s, run_script_enabled=%s, runtime_dir=%s)",
        cfg.scribus_bin,
        cfg.run_script_enabled,
        cfg.runtime_dir,
    )
    return mcp
