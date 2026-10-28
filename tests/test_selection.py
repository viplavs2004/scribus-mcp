"""Tests for get_selection / format_selected_text / set_selection_colors.

Offline tests use a stub backend. The live class needs a visible Scribus with the bridge
(SCRIBUS_MCP_LIVE=1 and the discovery file of that Scribus in the environment); it builds its own
objects and simulates user selections through scripter calls (selectObject / selectText)."""

from __future__ import annotations

import asyncio
import os
from types import SimpleNamespace

import pytest

from scribus_mcp.testing import unwrap
from scribus_mcp.tools import ADS_TOOLSET, selection as sel


class _Stub:
    def __init__(self, value):
        self.value = value
        self.bodies = []

    async def script(self, body, result_expr="None"):
        self.bodies.append(body)
        return SimpleNamespace(ok=True, value=self.value, error=None, unwrap_or=lambda *a: self.value)

    async def call(self, method, *a, **k):
        return SimpleNamespace(ok=True, value=["Black"], error=None)


def _server(monkeypatch, stub):
    from scribus_mcp.server import build_server

    async def fake(ctx, mode):
        return stub

    monkeypatch.setattr(sel, "get_backend", fake)
    return build_server()


SAMPLE = {
    "has_doc": True, "page": 1, "selection_count": 1, "edit_mode": None,
    "text": {"frame": "Title", "selection_start": 6, "selection_length": 5, "selected_text": "brave"},
    "objects": [{"name": "Title", "type": "TextFrame"}],
}


def test_scripts_are_valid_python():
    compile(sel.SEL_LIB + "\n_value = _sel_get(True, 200)\n", "<sel>", "exec")
    params = {"name": None, "color": "Red", "font": None, "size_pt": None, "shade": None,
              "scope": "auto", "start": None, "length": None}
    compile(sel._fill(sel._FORMAT_BODY, params), "<fmt>", "exec")
    compile(sel._fill(sel._COLORS_BODY, {"fill": "Red", "line": None, "line_width_pt": None,
                                         "fill_shade": None}), "<col>", "exec")


def test_get_selection_adds_hint_and_calls_script(monkeypatch):
    stub = _Stub(dict(SAMPLE))
    mcp = _server(monkeypatch, stub)
    out = unwrap(asyncio.run(mcp.call_tool("get_selection", {})))
    assert out["ok"] and out["interactive"]
    assert "format_selected_text" in out["hint"] and "brave" not in stub.bodies[0]
    assert "_sel_get(True, 200)" in stub.bodies[0]


def test_hint_nothing_selected_says_do_not_guess():
    h = sel._hint({"has_doc": True, "selection_count": 0})
    assert "Nothing is selected" in h and "guess" in h


def test_headless_says_no_selection(monkeypatch):
    from scribus_mcp.backends import HeadlessBackend
    from scribus_mcp.config import Config

    hb = HeadlessBackend(Config.from_env())
    mcp = _server(monkeypatch, hb)
    for tool, args in (("get_selection", {}), ("format_selected_text", {"color": "red"}),
                       ("set_selection_colors", {"fill": "red"})):
        out = unwrap(asyncio.run(mcp.call_tool(tool, args)))
        assert out["ok"] is False and out["interactive"] is False and "headless" in out["error"]


def test_format_validates_input(monkeypatch):
    stub = _Stub({"frame": "T"})
    mcp = _server(monkeypatch, stub)
    r = unwrap(asyncio.run(mcp.call_tool("format_selected_text", {})))
    assert not r["ok"] and "at least one" in r["error"]
    r = unwrap(asyncio.run(mcp.call_tool("format_selected_text", {"color": "red", "scope": "x"})))
    assert not r["ok"]
    r = unwrap(asyncio.run(mcp.call_tool("format_selected_text", {"size_pt": 2})))
    assert not r["ok"] and "5 pt" in r["error"]
    assert stub.bodies == []


def test_format_resolves_literal_colour(monkeypatch):
    from scribus_mcp.tools import palette as pal

    pal.invalidate_palette()
    stub = _Stub({"frame": "T", "start": 0, "length": 3})
    mcp = _server(monkeypatch, stub)
    r = unwrap(asyncio.run(mcp.call_tool("format_selected_text", {"color": "red"})))
    assert r["ok"]
    assert "'color': '#E8281E'" in stub.bodies[-1]
    compile(stub.bodies[-1], "<b>", "exec")


def test_new_tools_in_ads_toolset():
    for n in ("get_selection", "format_selected_text", "set_selection_colors"):
        assert n in ADS_TOOLSET


def test_instructions_mention_get_selection():
    from scribus_mcp.server import INSTRUCTIONS

    assert "get_selection FIRST" in INSTRUCTIONS


LIVE = os.environ.get("SCRIBUS_MCP_LIVE") == "1"


@pytest.mark.skipif(not LIVE, reason="set SCRIBUS_MCP_LIVE=1 with a visible Scribus + bridge")
class TestLiveSelection:
    @pytest.fixture(scope="class")
    def env(self):
        from scribus_mcp.backends import InteractiveBackend
        from scribus_mcp.config import Config
        from scribus_mcp.server import build_server

        b = InteractiveBackend(Config.from_env())
        if not asyncio.run(b.is_available()):
            pytest.skip("no interactive bridge")
        return b, build_server()

    def _s(self, b, body):
        r = asyncio.run(b.script(body, result_expr="_value"))
        assert r.ok, (r.error, r.traceback)
        return r.value

    def _call(self, mcp, tool, **kw):
        return unwrap(asyncio.run(mcp.call_tool(tool, kw)))

    @pytest.fixture(autouse=True)
    def objects(self, env):
        b, _ = env
        self._s(b, (
            "import scribus as s\n"
            "if not s.haveDoc():\n"
            "    s.newDocument(s.PAPER_A4,(10,10,10,10),s.PORTRAIT,1,s.UNIT_MILLIMETERS,"
            "s.NOFACINGPAGES,s.FIRSTPAGERIGHT,1)\n"
            "s.deselectAll()\n"
            "for n in list(s.getAllObjects()):\n"
            "    s.deleteObject(n)\n"
            "a = s.createText(20,20,120,30,'SelA'); s.setText('Hello brave new world' + chr(13) + 'Two', a)\n"
            "b = s.createText(20,60,120,20,'SelB'); s.setText('Second frame', b)\n"
            "c = s.createText(20,90,120,20,'SelC'); s.setText('Third', c)\n"
            "r = s.createRect(20,120,50,30,'SelR'); s.setFillColor('Black', r)\n"
            "_value = 1\n"))

    def test_nothing_selected(self, env):
        b, mcp = env
        self._s(b, "import scribus as s\ns.deselectAll()\n_value=1")
        r = self._call(mcp, "get_selection")
        assert r["ok"] and r["selection_count"] == 0 and r["objects"] == []

    def test_selected_frame_and_rect(self, env):
        b, mcp = env
        self._s(b, "import scribus as s\ns.deselectAll(); s.selectObject('SelB'); s.selectObject('SelR')\n_value=1")
        r = self._call(mcp, "get_selection")
        assert [o["name"] for o in r["objects"]] == ["SelB", "SelR"]
        assert r["objects"][1]["fill"]["name"] == "Black"
        assert r["objects"][0]["bbox_mm"]["w"] == 120.0

    def test_highlight_range_and_passive(self, env):
        b, mcp = env
        self._s(b, "import scribus as s\ns.deselectAll(); s.selectObject('SelA'); s.selectText(6,5,'SelA')\n_value=1")
        r = self._call(mcp, "get_selection")
        t = r["text"]
        assert (t["selection_start"], t["selection_length"], t["selected_text"]) == (6, 5, "brave")
        assert t["paragraph_text"] == "Hello brave new world" and t["word_at_cursor"] == "brave"
        again = self._s(b, "import scribus as s\n_value=[s.selectionCount(), s.getSelectedObject(0),"
                           " list(s.getSelectedTextRange('SelA'))]")
        assert again == [1, "SelA", [6, 5]]  # untouched by the read

    def test_format_highlight_only(self, env):
        b, mcp = env
        self._s(b, "import scribus as s\ns.deselectAll(); s.selectObject('SelA'); s.selectText(6,5,'SelA')\n_value=1")
        r = self._call(mcp, "format_selected_text", color="#FF0000")
        assert r["ok"] and not r["whole_frame"] and (r["start"], r["length"]) == (6, 5)
        st = self._s(b, "import scribus as s\ns.deselectAll()\n"
                        "s.selectText(0,1,'SelA'); c0 = s.getTextColor('SelA')\n"
                        "s.selectText(7,1,'SelA'); c7 = s.getTextColor('SelA')\n"
                        "s.selectText(0,0,'SelA'); _value=[c0,c7]")
        assert st[0] != "#FF0000" and st[1] == "#FF0000"

    def test_format_whole_frame_and_colors(self, env):
        b, mcp = env
        self._s(b, "import scribus as s\ns.deselectAll(); s.selectObject('SelC')\n_value=1")
        r = self._call(mcp, "format_selected_text", color="#00AA00", size_pt=20)
        assert r["ok"] and r["whole_frame"] and r["after_first_char"]["size_pt"] == 20.0
        self._s(b, "import scribus as s\ns.deselectAll(); s.selectObject('SelR')\n_value=1")
        r = self._call(mcp, "set_selection_colors", fill="#1F4E9E")
        assert r["ok"] and r["applied"][0]["fill"] == "#1F4E9E"
        assert r["selection_count_after"] == 1
