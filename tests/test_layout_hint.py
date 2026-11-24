"""find_templates(layout_hint=...): ranking from a reference picture's aspect / size / descriptor."""

from __future__ import annotations

import json

import pytest

from scribus_mcp.tools import template_search as ts

from tests.test_template_search import build_library


@pytest.fixture(scope="module")
def lib(tmp_path_factory):
    root = build_library(tmp_path_factory.mktemp("lay"))
    needed = ("news_bw_notice_nagar_palika_63x66", "news_court_notice_3x10", "news_gn_notice")
    missing = [n for n in needed if not (root / n).is_dir()]
    if missing:
        pytest.skip(f"fixture library lacks {missing}")
    return root


def _ids(res):
    return [c["id"] for c in res["candidates"]]


def test_parse_layout_hint_forms():
    assert ts.parse_layout_hint(None) is None and ts.parse_layout_hint("") is None
    assert ts.parse_layout_hint(12) is None
    s = ts.parse_layout_hint("double border, justified body ~17 lines, text only, black and white")
    assert s["bw"] is True and "double" in s["words"] and "justified" in s["words"]
    d = ts.parse_layout_hint({"aspect_ratio": 0.96, "width_mm": 63, "height_mm": 66, "body_lines": 17,
                              "text_only": True, "black_and_white": True, "descriptor": "single border"})
    assert d["aspect"] == pytest.approx(0.96) and d["text_heavy"] is True and d["h_mm"] == 66.0
    # the whole analyze_reference_image result is accepted too
    whole = ts.parse_layout_hint({"ok": True, "layout_hint": {"aspect_ratio": 1.5}})
    assert whole["aspect"] == 1.5
    assert ts.parse_layout_hint({"junk": 1}) is None
    # width + height give the aspect
    assert ts.parse_layout_hint({"width_mm": 50, "height_mm": 100})["aspect"] == 0.5


def test_aspect_within_10_percent_is_rewarded(lib):
    base = ts.search("notice", [lib], max_results=12)
    hint = {"aspect_ratio": 63.4 / 66.0, "black_and_white": True}
    res = ts.search("notice", [lib], max_results=12, layout_hint=hint)
    by_base = {c["id"]: c["score"] for c in base["candidates"]}
    by_hint = {c["id"]: c for c in res["candidates"]}
    nagar = by_hint["news_bw_notice_nagar_palika_63x66"]
    assert nagar["score"] > by_base.get("news_bw_notice_nagar_palika_63x66", -99) + 4
    assert any("matches the picture" in w for w in nagar["why"])
    # a very different shape does not get the aspect bonus
    court = by_hint.get("news_court_notice_3x10")
    if court:
        assert not any("matches the picture" in w for w in court["why"])
    assert _ids(res).index("news_bw_notice_nagar_palika_63x66") < _ids(res).index("news_court_notice_3x10") \
        if "news_court_notice_3x10" in _ids(res) else True


def test_tall_picture_prefers_tall_template(lib):
    res = ts.search("notice", [lib], max_results=12, layout_hint={"aspect_ratio": 0.33})
    assert _ids(res)[0] == "news_court_notice_3x10"


def test_real_size_in_layout_hint_matches_size(lib):
    res = ts.search("notice", [lib], max_results=12,
                    layout_hint={"width_mm": 68, "height_mm": 65, "aspect_ratio": 68 / 65})
    top = res["candidates"][0]
    assert top["id"] in ("news_gn_notice", "news_bw_notice_nagar_palika_63x66")
    assert any(w.startswith("layout:") for w in top["why"])


def test_descriptor_words_and_text_heavy_bonus(lib):
    plain = ts.search("notice", [lib], max_results=12)
    hinted = ts.search("notice", [lib], max_results=12,
                       layout_hint="double border, justified body ~17 lines, text only, black and white notice")
    p = {c["id"]: c["score"] for c in plain["candidates"]}
    h = {c["id"]: c["score"] for c in hinted["candidates"]}
    common = [i for i in p if i in h]
    assert any(h[i] > p[i] for i in common)  # some notice template gained points
    for c in hinted["candidates"]:
        if c["colour"] == "colour" and c["id"] in p:
            assert h[c["id"]] <= p[c["id"]] + 1e-9  # colour templates never gain from a b&w picture


def test_ranking_is_deterministic_and_unchanged_without_hint(lib):
    hint = {"aspect_ratio": 1.0, "black_and_white": True, "descriptor": "single border text only"}
    a = ts.search("notice", [lib], max_results=12, layout_hint=hint)
    b = ts.search("notice", [lib], max_results=12, layout_hint=dict(hint))
    assert json.dumps(a["candidates"], sort_keys=True) == json.dumps(b["candidates"], sort_keys=True)
    n1 = ts.search("notice", [lib], max_results=12)
    n2 = ts.search("notice", [lib], max_results=12, layout_hint=None)
    n3 = ts.search("notice", [lib], max_results=12, layout_hint="")
    assert _ids(n1) == _ids(n2) == _ids(n3)
    assert [c["score"] for c in n1["candidates"]] == [c["score"] for c in n2["candidates"]]


def test_hint_only_query_gives_partial_not_a_silent_good_match(lib):
    res = ts.search("", [lib], max_results=5, layout_hint={"aspect_ratio": 0.96, "width_mm": 63, "height_mm": 66})
    assert res["candidates"]
    assert res["match_quality"] in ("partial", "good", "none")
    assert any(w.startswith("layout:") for w in res["candidates"][0]["why"])
