"""Tests for the ad / flyer tools. Offline tests need no Scribus; the live class is gated by
SCRIBUS_MCP_LIVE=1 (headless backend, one Scribus spawn per call, so each test chains what it
needs in a single script via the tools that build several things at once)."""

from __future__ import annotations

import asyncio
import gzip
import os
from types import SimpleNamespace

import pytest

from scribus_mcp.kruti import from_kruti, kruti_dev
from scribus_mcp.testing import unwrap
from scribus_mcp.tools import ADS_TOOLSET, apply_toolset
from scribus_mcp.tools import palette as pal
from scribus_mcp.tools import templates as tpl
from scribus_mcp.tools import verify as ver
from scribus_mcp.tools._adlib import (
    AD_LIB,
    KRUTI_SENTINEL,
    build_rich_text,
    has_devanagari,
    looks_like_kruti,
)
from scribus_mcp.tools.ad_boxes import _BULLET_LIB
from scribus_mcp.tools.decor import _PLACE_LIB, SHAPE_PATHS
from scribus_mcp.tools.hindi import classify_fonts

HINDI = "प्रवेश प्रारंभ"


# --- Kruti / rich text ---------------------------------------------------------------------
def test_kruti_roundtrip():
    assert from_kruti(kruti_dev(HINDI)) == HINDI


def test_rich_text_spans_cover_text_and_flag_kruti():
    text, spans, npar = build_rich_text(
        f"{HINDI} Admission\nSecond", None, font="Arial Regular", size_pt=12, color="Black"
    )
    assert npar == 2
    assert sum(s["len"] for s in spans) == len(text)
    pos = 0
    for s in spans:
        assert s["start"] == pos
        pos += s["len"]
    assert spans[0]["font"] == KRUTI_SENTINEL
    assert spans[-1]["font"] == "Arial Regular"
    assert not has_devanagari(text)  # converted


def test_rich_text_unicode_mode_keeps_devanagari():
    text, spans, _ = build_rich_text(HINDI, None, font="Nirmala UI Regular", size_pt=12,
                                     color=None, hindi="unicode")
    assert text == HINDI and spans[0]["font"] == "Nirmala UI Regular"


def test_rich_text_runs_keep_per_run_size_and_color():
    text, spans, npar = build_rich_text(
        None,
        [{"text": "AB\n", "size_pt": 40}, {"text": "cd", "size_pt": 20, "color": "Red"}],
        font="Impact Regular", size_pt=10, color="White",
    )
    assert text == "AB\ncd" and npar == 2
    assert [s["size"] for s in spans] == [40.0, 20.0]
    assert spans[1]["color"] == "Red" and spans[0]["color"] == "White"


def test_looks_like_kruti():
    assert looks_like_kruti("izos'k izkjaHk gS vkSj ds")
    assert not looks_like_kruti("Admission open for Nursery to IX")
    assert not looks_like_kruti(HINDI)


# --- colours --------------------------------------------------------------------------------
def test_parse_color_literal():
    assert pal.parse_color_literal("#ffde00") == ("#FFDE00", (255, 222, 0))
    assert pal.parse_color_literal("#f00") == ("#FF0000", (255, 0, 0))
    assert pal.parse_color_literal("yellow")[0] == "#FFDE00"
    assert pal.parse_color_literal("primary") is None
    assert pal.parse_color_literal("#12345") is None


# --- fonts / templates / toolset ------------------------------------------------------------
def test_classify_fonts():
    installed = ["Impact Regular", "Kruti Dev 010 Regular", "Nirmala UI Regular", "Arial Regular",
                 "Segoe UI Symbol Regular"]
    roles = classify_fonts(installed)
    assert roles["display_condensed"][0] == "Impact Regular"
    assert roles["kruti"] == ["Kruti Dev 010 Regular"]
    assert roles["devanagari_unicode"][0] == "Nirmala UI Regular"
    assert roles["body"] == ["Arial Regular"]


def test_scan_templates_reads_index_with_utf8_declaration(tmp_path):
    d = tmp_path / "templates"
    (d / "t1").mkdir(parents=True)
    with gzip.open(d / "t1" / "t1.sla.gz", "wb") as f:
        f.write(b"<SCRIBUSUTF8NEW/>")
    (d / "t1" / "t1.png").write_bytes(b"x")
    (d / "orphan").mkdir()
    (d / "orphan" / "o.sla").write_text("<x/>")
    (d / "template.xml").write_text(
        '<?xml version="1.0" encoding="utf8"?><templates><template category="Newspaper Ads">'
        "<name>Test ad</name><file>t1/t1.sla.gz</file><img>t1/t1.png</img><psize>A4</psize>"
        "<descr>d</descr><usage>u</usage></template></templates>",
        encoding="utf-8",
    )
    found = tpl.scan_templates([d])
    by_id = {t["id"]: t for t in found}
    assert by_id["t1"]["category"] == "Newspaper Ads" and by_id["t1"]["preview"]
    assert by_id["orphan"]["category"] == "(not in index)"


def test_ads_toolset_names_all_exist_and_filter_works():
    from scribus_mcp.server import build_server

    mcp = build_server()
    names = {t.name for t in asyncio.run(mcp.list_tools())}
    missing = [n for n in ADS_TOOLSET if n not in names]
    assert not missing, missing
    for new in ("create_text_box", "create_badge", "create_bullet_list", "create_label_bar",
                "create_decor_shape", "fit_text_to_frame", "set_text_hindi",
                "convert_unicode_to_kruti", "suggest_fonts", "verify_document",
                "export_press_pdf", "render_preview", "list_templates", "new_from_template",
                "align_objects", "distribute_objects"):
        assert new in names
    removed = apply_toolset(mcp, "ads")
    left = {t.name for t in asyncio.run(mcp.list_tools())}
    assert removed > 50 and left == set(ADS_TOOLSET)
    with pytest.raises(ValueError):
        apply_toolset(mcp, "nope")


def test_server_instructions_mention_composed_tools():
    from scribus_mcp.server import INSTRUCTIONS

    for word in ("create_text_box", "verify_document", "Kruti", "list_templates", "5 pt"):
        assert word in INSTRUCTIONS


# --- script bodies are valid python ----------------------------------------------------------
def test_script_libraries_compile():
    compile(AD_LIB + _BULLET_LIB + _PLACE_LIB, "<lib>", "exec")
    src = ver.build_verify_script({
        "min_pt": 5.0, "bleed_tolerance_mm": 3.0, "min_image_ppi": 100, "expected_fonts": {},
        "kruti_hints": True, "max_chars": 4000,
    })
    compile(src, "<verify>", "exec")
    assert all(p.startswith("M") for p in SHAPE_PATHS.values())


def test_export_version_map_x4_is_10():
    import inspect

    from scribus_mcp.tools import export

    src = inspect.getsource(export)
    assert '"X-4": 10' in src and '"X-1a": 11' in src and '"X-3": 12' in src


def test_pyproject_pins_mcp_below_2():
    from pathlib import Path

    text = (Path(__file__).parent.parent / "pyproject.toml").read_text(encoding="utf-8")
    assert '"mcp>=1.2,<2"' in text


# --- composed tools against a stub backend (no Scribus) --------------------------------------
class _StubBackend:
    def __init__(self):
        self.bodies = []

    async def script(self, body, result_expr="None"):
        self.bodies.append(body)
        return SimpleNamespace(ok=True, value={"name": "T1", "font_scale": 1.0, "sizes": [12.0],
                                               "overflows": False, "lines": 1, "warnings": []},
                               error=None, unwrap_or=lambda *a: None)

    async def call(self, method, *args, **kw):
        return SimpleNamespace(ok=True, value=["Black"], error=None)


def test_create_text_box_builds_valid_script_and_clamps_min_font(monkeypatch):
    from scribus_mcp.server import build_server
    from scribus_mcp.tools import ad_boxes

    stub = _StubBackend()

    async def fake_backend(ctx, mode):
        return stub

    monkeypatch.setattr(ad_boxes, "get_backend", fake_backend)
    pal.invalidate_palette()
    mcp = build_server()
    out = unwrap(asyncio.run(mcp.call_tool("create_text_box", {
        "x_mm": 1, "y_mm": 2, "width_mm": 50, "height_mm": 20, "text": HINDI + " Open",
        "fill_color": "#14398F", "min_font_pt": 2, "shape": "pill",
    })))
    assert out["ok"] is True
    body = stub.bodies[-1]
    compile(body, "<body>", "exec")
    assert "'min_pt': 5.0" in body  # clamped to the press minimum
    assert "'pill': True" in body
    assert KRUTI_SENTINEL in body  # Hindi converted + flagged for the Kruti font
    assert HINDI not in body


# --- live ------------------------------------------------------------------------------------
LIVE = os.environ.get("SCRIBUS_MCP_LIVE") == "1"


@pytest.mark.skipif(not LIVE, reason="set SCRIBUS_MCP_LIVE=1 for live Scribus tests")
class TestLiveHeadless:
    @pytest.fixture(scope="class")
    def mcp(self):
        from scribus_mcp.server import build_server

        return build_server()

    def _call(self, mcp, tool, **kw):
        kw.setdefault("mode", "headless")
        return unwrap(asyncio.run(mcp.call_tool(tool, kw)))

    def test_suggest_fonts_and_templates(self, mcp):
        r = self._call(mcp, "suggest_fonts")
        assert r["ok"] and r["installed_count"] > 0
        t = self._call(mcp, "list_templates")
        assert t["ok"]

    def test_escape_free_script_roundtrip_via_text_box(self, mcp, tmp_path):
        # create_document in headless mode is stateless, so run a single composed script
        # through verify's building blocks: create doc + text box + verify in one body.
        from scribus_mcp.backends import HeadlessBackend
        from scribus_mcp.config import Config

        backend = HeadlessBackend(Config.from_env())
        spec = {
            "x": 10, "y": 10, "w": 80, "h": 20, "name": None, "text": "Hello big title",
            "spans": [{"start": 0, "len": 15, "font": None, "size": 40.0, "color": "Black"}],
            "npar": 1, "fill": None, "line": None, "pad_mm": [1, 1, 1, 1], "align": "center",
            "valign": "middle", "fit": "shrink", "min_pt": 5.0, "max_scale": 6.0, "no_wrap": True,
        }
        body = (
            "import scribus as _s\n"
            "_s.newDocument(_s.PAPER_A4, (10, 10, 10, 10), _s.PORTRAIT, 1, _s.UNIT_MILLIMETERS,"
            " _s.NOFACINGPAGES, _s.FIRSTPAGERIGHT, 1)\n"
            + AD_LIB
            + f"\n_f, _sc = _ad_box({spec!r})\n"
            "_over = _ad_overflow(_f)\n"
            "_value = {'scale': _sc, 'over': _over, 'lines': _ad_lines(_f)}\n"
        )
        res = asyncio.run(backend.script(body, result_expr="_value"))
        assert res.ok, res.error
        assert res.value["over"] is False
        assert res.value["lines"] == 1
        assert res.value["scale"] < 1.0  # 40 pt does not fit 80 mm on one line: it shrank
