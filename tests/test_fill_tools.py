"""Pure tests for the fill tools: markup parser, Kruti regression, solver maths (fake Scribus),
field-spec building. No Scribus binary needed."""

from __future__ import annotations

import math
import sys
import types

import pytest

from scribus_mcp.kruti import kruti_dev
from scribus_mcp.tools._markup import has_markup, parse_markup, strip_markup
from scribus_mcp.tools._solve import SOLVER_LIB, solve_params

# --------------------------------------------------------------------------- markup


def test_markup_plain_text_is_one_run():
    runs, warns = parse_markup("hello world")
    assert runs == [{"text": "hello world"}] and not warns
    assert not has_markup("hello world")


def test_markup_mixed_font_line():
    src = "{font=Arial Bold,size=9}-:{/} {font=Kruti Dev 010 Regular}mid{/} {font=Arial Bold}:-{/}"
    runs, warns = parse_markup(src)
    assert not warns
    assert [r["text"] for r in runs] == ["-:", " ", "mid", " ", ":-"]
    assert runs[0] == {"text": "-:", "font": "Arial Bold", "size_pt": 9.0}
    assert runs[2]["font"] == "Kruti Dev 010 Regular"
    assert "font" not in runs[1]
    assert strip_markup(src) == "-: mid :-"


def test_markup_flags_nesting_and_literals():
    runs, _ = parse_markup("{bold,color=Red}a{italic}b{/}c{/}d")
    assert runs[0] == {"text": "a", "bold": True, "color": "Red"}
    assert runs[1] == {"text": "b", "bold": True, "color": "Red", "italic": True}
    assert runs[2]["text"] == "c" and "italic" not in runs[2]
    assert runs[3] == {"text": "d"}
    # braces: escaped and not-a-tag stay literal
    assert strip_markup("a {{b}} {foo} {size=x}") == "a {b} {foo} {size=x}"
    assert not has_markup("{foo} {{size=9}}")


def test_markup_unclosed_and_stray_close_warn():
    runs, warns = parse_markup("{size=8}abc")
    assert runs[0]["size_pt"] == 8.0 and any("not closed" in w for w in warns)
    _, warns = parse_markup("abc{/}")
    assert any("unmatched" in w for w in warns)


def test_markup_merges_equal_adjacent_runs_and_scale():
    runs, _ = parse_markup("{scale=90}a{/}{scale=90}b{/}")
    assert runs == [{"text": "ab", "h_scale": 90.0}]


# --------------------------------------------------------------------------- Kruti ऑ


def test_kruti_candra_a_does_not_crash_and_matches_decomposed_form():
    # U+0911 (ऑ) used to raise "Cannot convert"; it is now written as आ + ॉ
    assert kruti_dev("ऑफर") == kruti_dev("आॉफर")
    assert kruti_dev("ऑ") != ""


def test_fill_spec_converts_hindi_only_in_runs_that_need_it():
    from scribus_mcp.tools.template_fields import build_field_spec

    text = "{font=Arial Bold}-:{/} सूचना ऑफर {font=Arial Bold}:-{/}"
    runs = [["x", "Kruti Dev 010 Regular", 10.0, "Black"]]
    spec, warns = build_field_spec("T1", 1, text, {"ls": 11.0, "lsm": 0}, runs, min_pt=5.0)
    fonts = [(spec["text"][s["start"]:s["start"] + s["len"]], s["font"]) for s in spec["solve"]["spans"]]
    assert fonts[0] == ("-:", "Arial Bold")
    assert fonts[-1] == (":-", "Arial Bold")
    assert any(f == "__KRUTI__" for _, f in fonts)
    assert all("ऀ" > c or c > "ॿ" for c in spec["text"])  # no Devanagari left
    assert spec["solve"]["ratio"] == pytest.approx(1.1)  # template ratio preserved
    assert not warns


def test_fill_spec_options_and_errors():
    from scribus_mcp.tools.template_fields import build_field_spec

    runs = [["abc", "Arial Regular", 9.0, "Black"]]
    spec, _ = build_field_spec("T", 1, {"text": "hello", "target_lines": 5, "align": "justify",
                                        "leading": 4.0}, {}, runs, min_pt=5.0)
    assert spec["align"] == 3 and spec["solve"]["target_lines"] == 5
    assert spec["solve"]["fit"] == "fill"
    assert spec["solve"]["lead"] == pytest.approx(5.25)  # >= 1.05 x 5 pt
    with pytest.raises(ValueError):
        build_field_spec("T", 1, {"text": "x", "bogus": 1}, {}, runs, min_pt=5.0)
    with pytest.raises(ValueError):
        build_field_spec("T", 1, {"text": "x", "align": "diagonal"}, {}, runs, min_pt=5.0)


def test_solve_params_clamps():
    p = solve_params(["f"], [], fit="fill", min_pt=2.0, max_pt=9999, leading_pt=1.0)
    assert p["min_pt"] == 5.0 and p["max_pt"] == 512.0 and p["lead"] >= 5.25
    with pytest.raises(ValueError):
        solve_params(["f"], [], fit="zoom")


# --------------------------------------------------------------------------- solver maths


class FakeScribus(types.ModuleType):
    """A tiny text engine: characters are 0.5 x size wide, lines wrap greedily by width,
    paragraphs split on newline, leading is fixed or 1.2 x size (auto)."""

    def __init__(self, text: str, w_pt: float, h_pt: float, valign: int = 0, unit: float = 1.0):
        super().__init__("scribus")
        self.unit = unit  # document units per point (1.0 = pt document, 25.4/72 = mm document)
        self.text, self.w, self.h = text, w_pt, h_pt
        self.size = 10.0
        self.lead = 12.0
        self.lead_mode = 1
        self.valign = valign
        self.calls = 0

    # layout model
    def _lines(self) -> int:
        cpl = max(1, int(self.w / (0.5 * self.size)))
        return sum(max(1, math.ceil(len(p) / cpl)) for p in self.text.split("\n"))

    def _leading(self) -> float:
        return self.lead if self.lead_mode == 0 else 1.2 * self.size

    def selectText(self, start, length, name=None): pass
    def getFontNames(self): return ["Arial Regular", "Kruti Dev 010 Regular"]
    def setFont(self, f, name=None): pass
    def getFont(self, name=None): return "Arial Regular"
    def setTextColor(self, c, name=None): pass
    def setFontSize(self, sz, name=None):
        assert 1 <= sz <= 512, "Font size out of bounds"
        self.size = sz
    def getFontSize(self, name=None): return self.size
    def layoutText(self, name): self.calls += 1
    def layoutTextChain(self, name): self.calls += 1
    def getTextLines(self, name): return self._lines()
    def getTextLength(self, name): return len(self.text)
    def getAllText(self, name): return self.text
    def textOverflows(self, name, nolinks=0):
        if self.valign == 2:
            return 1  # models the bottom-alignment bug: wrong unless forced to top
        return 1 if self._lines() * self._leading() > self.h else 0
    def setLineSpacingMode(self, m, name=None): self.lead_mode = m
    def setLineSpacing(self, v, name=None): self.lead = v; self.lead_mode = 0
    def getLineSpacing(self, name=None): return self._leading()
    def getLineSpacingMode(self, name=None): return self.lead_mode
    def pointsToDocUnit(self, v): return v * self.unit
    def getSize(self, name): return (self.w * self.unit, self.h * self.unit)
    def getTextDistances(self, name): return (0, 0, 2 * self.unit, 2 * self.unit)
    def getTextVerticalAlignment(self, name): return self.valign
    def setTextVerticalAlignment(self, v, name=None): self.valign = v


def _run(text, w, h, **kw):
    from scribus_mcp.tools._adlib import AD_LIB

    fake = FakeScribus(text, w, h, valign=kw.pop("valign", 0), unit=kw.pop("unit", 1.0))
    old = sys.modules.get("scribus")
    sys.modules["scribus"] = fake
    try:
        ns: dict = {}
        exec(AD_LIB + SOLVER_LIB, ns)
        spans = [{"start": 0, "len": len(text), "size": kw.pop("base", 10.0)}]
        p = solve_params(["F"], spans, **kw)
        res = ns["_sv_solve"](p)
    finally:
        if old is None:
            del sys.modules["scribus"]
        else:
            sys.modules["scribus"] = old
    return res, fake


TEXT = "word " * 120  # 600 chars


def test_solver_shrink_finds_largest_fitting_size():
    res, fake = _run(TEXT, 200, 120, fit="shrink", base=14.0, leading_ratio=1.2)
    assert not res["overflow"]
    assert res["size_pt"] <= 14.0 and res["size_pt"] >= 5.0
    # one quarter point more must overflow (it is the LARGEST fitting size)
    fake.size = res["size_pt"] + 0.25
    fake.lead = 1.2 * fake.size
    assert fake._lines() * fake.lead > fake.h
    assert res["tries"] <= 10


def test_solver_fill_respects_cap_and_512():
    res, _ = _run("hi", 400, 400, fit="fill", base=10.0, leading_ratio=1.2)
    assert res["size_pt"] <= 200.0 and not res["overflow"]
    res, _ = _run("hi", 5000, 5000, fit="fill", base=10.0, max_pt=9999, leading_ratio=1.2)
    assert res["size_pt"] <= 512.0  # the 512 pt limit used to raise in Scribus


def test_solver_fixed_leading_caps_font_and_keeps_mode():
    res, fake = _run(TEXT, 300, 200, fit="fill", base=9.0, leading_pt=10.0)
    assert res["size_pt"] <= 10.0 / 1.05 + 0.01
    assert fake.lead_mode == 0 and fake.lead >= 1.05 * fake.size - 1e-9
    assert not res["overflow"]


def test_solver_target_lines_exact_and_spread():
    res, fake = _run(TEXT, 300, 200, fit="fill", base=9.0, leading_ratio=1.2, target_lines=6)
    assert res["lines"] <= 6 and not res["overflow"]
    # spread: the leading grew so that lines x leading approaches the frame height
    assert res["leading_pt"] >= 1.2 * res["size_pt"] - 0.01
    assert res["lines"] * res["leading_pt"] <= 200 + 1e-6
    assert res["tries"] <= 30


def test_solver_leading_mode_keeps_size():
    res, fake = _run(TEXT, 300, 200, fit="leading", base=9.0)
    assert res["size_pt"] == 9.0
    assert res["leading_pt"] >= 1.05 * 9.0 - 0.01 and res["leading_pt"] <= 1.6 * 9.0 + 0.01
    assert not res["overflow"]


def test_solver_bottom_valign_does_not_shrink_to_5pt():
    res, fake = _run(TEXT, 200, 200, fit="shrink", base=8.0, leading_ratio=1.2, valign=2)
    assert res["size_pt"] > 5.0
    assert fake.valign == 2  # restored


def test_solver_reports_impossible_fit():
    res, _ = _run(TEXT * 20, 100, 40, fit="shrink", base=10.0, leading_ratio=1.2)
    assert res["overflow"] and res["size_pt"] == 5.0
    assert any("does not fit" in n for n in res["notes"])


def test_solver_is_unit_independent_in_mm_documents():
    # frame sizes / text distances arrive in document units (mm here); leading and font stay in pt
    res_pt, _ = _run(TEXT, 300, 200, fit="fill", base=9.0, leading_ratio=1.2, target_lines=6)
    res_mm, _ = _run(TEXT, 300, 200, fit="fill", base=9.0, leading_ratio=1.2, target_lines=6, unit=25.4 / 72)
    assert res_mm["size_pt"] == res_pt["size_pt"]
    assert res_mm["leading_pt"] == pytest.approx(res_pt["leading_pt"], abs=0.1)
    assert res_mm["lines"] * res_mm["leading_pt"] <= 200 + 1e-6


def test_solver_unreachable_target_falls_back_to_best_fit_not_5pt():
    res, _ = _run(TEXT, 300, 200, fit="fill", base=9.0, leading_ratio=1.2, target_lines=1)
    assert not res["overflow"] and res["size_pt"] > 5.0
    assert res["target_met"] is False and any("not reachable" in n for n in res["notes"])


def test_template_ratio_is_capped_so_default_15pt_leading_is_not_inherited():
    from scribus_mcp.tools.template_fields import _template_ratio

    assert _template_ratio({"ls": 15.0, "lsm": 0}, 9.4, 1.05) == pytest.approx(1.3)
    assert _template_ratio({"ls": 9.5, "lsm": 0}, 9.0, 1.05) == pytest.approx(9.5 / 9.0)
    assert _template_ratio({"ls": 9.0, "lsm": 0}, 9.0, 1.05) == pytest.approx(1.05)  # floor
    assert _template_ratio({"ls": 15.0, "lsm": 1}, 9.0, 1.05) is None  # automatic leading stays automatic
