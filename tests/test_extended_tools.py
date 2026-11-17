"""Registration and argument-order checks for the extended Scripter tools."""

from __future__ import annotations

import asyncio

from scribus_mcp.backends.base import ScribusResult
from scribus_mcp.tools.extended._util import border_lines
from scribus_mcp.tools.text import font_feature_script


class _FakeBackend:
    def __init__(self) -> None:
        self.scripts: list[str] = []

    async def call(self, method, *args, **kwargs):
        return ScribusResult(ok=True, value=None)

    async def script(self, body, result_expr="None"):
        self.scripts.append(body)
        return ScribusResult(ok=True, value="Frame1")

    async def is_available(self):
        return True


def _patch(monkeypatch, backend: _FakeBackend) -> None:
    async def _get(ctx, mode):
        return backend

    monkeypatch.setattr("scribus_mcp.tools.extended._util.get_backend", _get)


def test_extended_tools_are_registered():
    from scribus_mcp.server import build_server

    names = {tool.name for tool in asyncio.run(build_server().list_tools())}
    expected = [
        "create_table",
        "set_cell_text",
        "merge_table_cells",
        "set_cell_border",
        "set_text_flow",
        "set_font_features",
        "get_text_chain",
        "duplicate_objects",
        "combine_polygons",
        "bring_to_front",
        "define_color_lab",
        "create_paragraph_style",
        "create_character_style",
        "set_fill_blend_mode",
        "set_gradient_vector",
        "set_bleeds",
        "set_baseline_grid",
        "import_pages",
        "edit_master_page",
        "place_vector_file",
        "set_layer_locked",
        "set_pdf_bookmark",
        "save_page_as_eps",
        "set_text_distances",
        "ungroup_objects",
        "scale_frame_to_image",
    ]
    missing = [name for name in expected if name not in names]
    assert not missing, missing


def test_font_feature_script_falls_back_when_legacy_is_missing():
    body = font_feature_script("Title", "underline", True, "setUnderline", "-1, -1, 'Title'")
    assert "hasattr(_s, 'setUnderline')" in body
    assert "setFontFeatures" in body
    assert "'underline'" in body


def test_border_lines_map_style_names():
    assert border_lines([{"width": 0.5, "style": "dot", "color": "Black"}]) == [
        (0.5, 3, "Black")
    ]


def test_create_table_forces_millimetres(monkeypatch):
    backend = _FakeBackend()
    _patch(monkeypatch, backend)
    from scribus_mcp.server import build_server
    from scribus_mcp.testing import unwrap

    mcp = build_server()
    result = unwrap(
        asyncio.run(
            mcp.call_tool(
                "create_table",
                {
                    "x_mm": 10,
                    "y_mm": 20,
                    "width_mm": 100,
                    "height_mm": 40,
                    "rows": 2,
                    "columns": 3,
                    "name": "Prices",
                    "mode": "headless",
                },
            )
        )
    )
    assert result["ok"] is True
    script = backend.scripts[-1]
    assert "setUnit" in script
    assert "createTable(10.0, 20.0, 100.0, 40.0, 2, 3, 'Prices')" in script


def test_layer_lock_passes_the_inverted_flag(monkeypatch):
    backend = _FakeBackend()
    _patch(monkeypatch, backend)
    from scribus_mcp.server import build_server
    from scribus_mcp.testing import unwrap

    unwrap(
        asyncio.run(
            build_server().call_tool(
                "set_layer_locked",
                {"name": "Notes", "locked": True, "mode": "headless"},
            )
        )
    )
    assert "setLayerLocked('Notes', 0)" in backend.scripts[-1]


def test_text_flow_uses_name_then_mode(monkeypatch):
    backend = _FakeBackend()
    _patch(monkeypatch, backend)
    from scribus_mcp.server import build_server
    from scribus_mcp.testing import unwrap

    unwrap(
        asyncio.run(
            build_server().call_tool(
                "set_text_flow",
                {"name": "Body", "flow": "bounding_box", "mode": "headless"},
            )
        )
    )
    assert "setTextFlowMode('Body', 2)" in backend.scripts[-1]
