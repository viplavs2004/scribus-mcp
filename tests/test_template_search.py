"""Offline tests for find_templates (ranking, size parsing, honesty, images) and the editable-field
classifier. The library is rebuilt from tests/fixtures: the repo's real template.xml plus stub
.sla files carrying the real page sizes / fonts / colours (tests/fixtures/sla_facts.json), so no
Scribus and no copy of the 17 MB library are needed. Live tests are gated by SCRIBUS_MCP_LIVE=1."""

from __future__ import annotations

import asyncio
import base64
import gzip
import io
import json
import os
import re
import shutil
from pathlib import Path

import pytest
from PIL import Image

from scribus_mcp.tools import template_fields as tf
from scribus_mcp.tools import template_search as ts

FIX = Path(__file__).parent / "fixtures"
HINDI_DISP = "news_disp_"


def _stub_sla(f: dict) -> str:
    pt = 72 / 25.4
    runs = "".join(f'<Content Font="{font}" FontSize="10" Chars="x"/>' for font in f["fonts"])
    cols = "".join(f'<X FillColor="{c}"/>' for c in f.get("chromatic_colors", []))
    return (f'<?xml version="1.0"?><SCRIBUSUTF8NEW><DOCUMENT ANZPAGES="{f["pages"]}" '
            f'PAGEWIDTH="{f["w_mm"] * pt}" PAGEHEIGHT="{f["h_mm"] * pt}">'
            f'<StoryText>{runs}<Content Font="Arial Regular" Chars="{f.get("text", "").replace(chr(34), "")}"/>'
            f'</StoryText>{cols}</DOCUMENT></SCRIBUSUTF8NEW>')


def build_library(root: Path, xml_bytes: bytes | None = None, drop_prefix: str | None = None) -> Path:
    facts = json.loads((FIX / "sla_facts.json").read_text(encoding="utf-8"))
    root.mkdir(parents=True, exist_ok=True)
    xml = xml_bytes if xml_bytes is not None else (FIX / "template.xml").read_bytes()
    (root / "template.xml").write_bytes(xml)
    for tid, f in facts.items():
        d = root / tid
        d.mkdir(exist_ok=True)
        with gzip.open(d / f"{tid}.sla.gz", "wb") as fh:
            fh.write(_stub_sla(f).encode("utf-8"))
        Image.new("RGB", (300, 400), (abs(hash(tid)) % 200 + 30, 120, 160)).save(d / f"{tid}.png")
    if drop_prefix:  # simulate templates that are in the folder but not in template.xml
        text = xml.decode("utf-8", errors="replace")
        text = re.sub(r"\s*<template [^>]*>(?:(?!</template>).)*?<file>" + re.escape(drop_prefix)
                      + r".*?</template>", "", text, flags=re.S)
        (root / "template.xml").write_bytes(text.encode("utf-8"))
    return root


@pytest.fixture(scope="module")
def lib(tmp_path_factory) -> Path:
    return build_library(tmp_path_factory.mktemp("lib"))


def top(lib: Path, q: str, n: int = 5, **kw) -> list[str]:
    return [c["id"] for c in ts.search(q, [lib], max_results=n, **kw)["candidates"]]


# ---- ranking: 20 queries (English, Hinglish, Devanagari) ---------------------------------
RANK_CASES = [
    ("school admission ad, 4 columns by 12 cm, Hindi", {"news_disp_school_5x20", "news_school_admission_flyer"}),
    ("jewellery sale ad half page colour", {"news_disp_jewellery_half_horizontal"}),
    ("court notice single column black and white", {"news_court_notice_3x10"}),
    ("Diwali greetings ad", {"news_disp_diwali_5x15"}),
    ("property plot launch display ad", {"news_disp_plots_half_vertical"}),
    ("classified job vacancy", {"news_disp_vacancy_bw_3x10"}),
    ("dukan ka grand opening ka ad", {"news_disp_grand_opening_4x15"}),
    ("A4 flyer for coaching institute", {"news_school_admission_flyer"}),
    ("quarter page car showroom offer", {"news_disp_car_quarter_page"}),
    ("दिवाली की शुभकामनाएं", {"news_disp_diwali_5x15"}),
    ("सोने चांदी के गहनों की दुकान का विज्ञापन", {"news_disp_jewellery_half_horizontal"}),
    ("नया स्कूल एडमिशन विज्ञापन 4 कॉलम x 12 सेमी", {"news_disp_school_5x20", "news_school_admission_flyer"}),
    ("holi ki badhai", {"news_disp_holi_4x10"}),
    ("tender notice black and white 4x10", {"news_disp_tender_bw_4x10"}),
    ("shaadi rishta matrimonial", {"news_disp_matrimonial_bw_3x10"}),
    ("name change notice", {"news_disp_namechange_bw_2x8"}),
    ("loan mela strip ad", {"news_disp_strip_8x8_loan_mela"}),
    ("hospital free health camp", {"news_disp_hospital_4x15"}),
    ("restaurant buffet offer 5 col x 12", {"news_disp_restaurant_5x12"}),
    ("bank auction neelami notice", {"news_disp_auction_notice_bw_5x15"}),
    ("EID mubarak greeting 3x10", {"news_disp_eid_3x10"}),
    ("furniture sale 4 col x 12 cm", {"news_disp_furniture_4x12"}),
]


@pytest.mark.parametrize("query,expected", RANK_CASES)
def test_top_hit(lib, query, expected):
    got = top(lib, query)
    assert got and got[0] in expected, (query, got)


def test_diwali_second_is_the_jacket(lib):
    assert top(lib, "Diwali greetings ad")[:2] == ["news_disp_diwali_5x15",
                                                    "news_disp_jacket_deepotsav_full_page"]


def test_size_beats_topic_only_when_topic_ties(lib):
    got = top(lib, "school admission 5 col x 20 cm")
    assert got[0] == "news_disp_school_5x20"


def test_bw_request_penalises_colour_templates(lib):
    r = ts.search("notice black and white", [lib])
    assert all(c["colour"] == "black & white" for c in r["candidates"][:3])


def test_hindi_request_prefers_hindi_template_when_topic_equal(lib):
    assert top(lib, "festival greeting Hindi")[0] != "news_disp_eid_3x10"


# ---- honesty -----------------------------------------------------------------------------
def test_nonsense_says_nothing_close(lib):
    r = ts.search("xyzzy qwerty", [lib])
    assert r["match_quality"] == "none"
    assert "Nothing close" in r["message"]
    assert 1 <= len(r["candidates"]) <= 3
    assert all(c["match"] == "weak" for c in r["candidates"])


def test_unknown_service_is_not_called_good(lib):
    r = ts.search("plumbing services", [lib])
    assert r["match_quality"] != "good"
    assert "plumbing" in r["message"]


def test_unknown_words_do_not_crash(lib):
    for q in ["", "   ", "%%%", "!!! 4x", "x" * 500, "कॉलम", "1/0 page", "a99 sale"]:
        r = ts.search(q, [lib])
        assert r["ok"] and "candidates" in r


def test_empty_library_does_not_crash(tmp_path):
    r = ts.search("school", [tmp_path])
    assert r["candidates"] == [] and r["match_quality"] == "none"


# ---- size parsing ---------------------------------------------------------------------------
@pytest.mark.parametrize("text,kind,vals", [
    ("4 col x 12 cm", "cols", (4, 12)),
    ("4 cols 12cm", "cols", (4, 12)),
    ("4 columns by 12 cm", "cols", (4, 12)),
    ("ad 4x12", "cols", (4, 12)),
    ("3x10", "cols", (3, 10)),
    ("12 cm x 4 col", "cols", (4, 12)),
    ("4 कॉलम x 12 सेमी", "cols", (4, 12)),
    ("४ कॉलम x १२ सेमी", "cols", (4, 12)),
])
def test_parse_cols(text, kind, vals):
    s, _ = ts.parse_size(text)
    assert s and s["kind"] == kind and (s["cols"], s["h_cm"]) == vals


def test_parse_cm_paper_named():
    s, _ = ts.parse_size("10x15 cm")
    assert s["kind"] == "cm" and (round(s["w_mm"]), round(s["h_mm"])) == (100, 150)
    s, _ = ts.parse_size("10 x 15")
    assert s["kind"] == "cm"
    assert ts.parse_size("A4 flyer")[0]["paper"] == "a4"
    assert ts.parse_size("A3")[0]["paper"] == "a3"
    for text, key in [("half page", "half_page"), ("quarter page", "quarter_page"),
                      ("full page", "full_page"), ("jacket ad", "jacket"),
                      ("1/8 page", "eighth_page"), ("aadha page", "half_page"),
                      ("आधा पेज", "half_page"), ("1/4 page", "quarter_page")]:
        assert ts.parse_size(text)[0]["named"] == key, text
    s, _ = ts.parse_size("single column")
    assert s["cols"] == 1 and s["h_cm"] is None
    assert ts.parse_size("hello world")[0] is None
    assert ts.parse_size("phone 98765 43210")[0] is None


def test_size_fit_uses_real_page_size():
    req, _ = ts.parse_size("4 col x 12 cm")
    assert ts.size_fit(req, 161, 120, [])[0] >= 0.9
    assert 0.45 <= ts.size_fit(req, 161, 132, [])[0] < 0.9      # near fit
    assert ts.size_fit(req, 325, 470, [])[0] < 0.2
    assert ts.size_label(161, 120).startswith("4 col x 12 cm")
    assert ts.size_label(210, 297) == "A4 portrait"
    assert "half page vertical" in ts.size_label(161, 470)


# ---- tolerance of a bad byte, unindexed templates, retagging ------------------------------
def test_bad_byte_in_template_xml(tmp_path):
    raw = (FIX / "template.xml").read_bytes()
    i = raw.index(b"<descr>") + 7
    raw = raw[:i] + b"caf\xe9 " + raw[i:]
    with pytest.raises(UnicodeDecodeError):
        raw.decode("utf-8")
    lib2 = build_library(tmp_path / "bad", xml_bytes=raw)
    assert len(ts.load_library([lib2])) == 89
    assert top(lib2, "jewellery sale")[0] == "news_disp_jewellery_half_horizontal"


def test_templates_missing_from_index_are_auto_tagged(tmp_path):
    lib2 = build_library(tmp_path / "noidx", drop_prefix="news_disp_")
    items = {t["id"]: t for t in ts.load_library([lib2])}
    assert items["news_disp_clinic_3x10"]["indexed"] is False
    assert items["news_disp_clinic_3x10"]["preview"]          # found by file name
    r = ts.search("dental clinic", [lib2])
    assert r["candidates"][0]["id"] == "news_disp_clinic_3x10"
    assert r["candidates"][0]["tags_source"] in ("reviewed", "auto")
    r = ts.search("jewellery", [lib2])
    assert r["candidates"][0]["id"] == "news_disp_jewellery_half_horizontal"


def test_derive_tags_for_unknown_template(tmp_path):
    lib2 = build_library(tmp_path / "x")
    d = lib2 / "news_disp_pharmacy_bw_2x6"
    d.mkdir()
    facts = {"pages": 1, "w_mm": 79.0, "h_mm": 60.0, "fonts": ["Arial Bold", "Kruti Dev 010 Regular"],
             "text": "x", "chromatic_colors": []}
    with gzip.open(d / "news_disp_pharmacy_bw_2x6.sla.gz", "wb") as fh:
        fh.write(_stub_sla(facts).encode())
    r = ts.search("pharmacy medicine ad 2 col x 6 cm black and white", [lib2])
    top1 = r["candidates"][0]
    assert top1["id"] == "news_disp_pharmacy_bw_2x6"
    assert top1["tags_source"] == "auto" and top1["colour"] == "black & white"
    assert top1["language"].startswith("Hindi")
    assert top1["size_label"] == "2 col x 6 cm"


def test_retag_cli_lists_only_untagged(tmp_path, capsys):
    lib2 = build_library(tmp_path / "r")
    d = lib2 / "mystery_ad"
    d.mkdir()
    with gzip.open(d / "mystery_ad.sla.gz", "wb") as fh:
        fh.write(_stub_sla({"pages": 1, "w_mm": 100, "h_mm": 100, "fonts": ["Arial Regular"],
                            "text": "x"}).encode())
    out = tmp_path / "draft.json"
    assert ts._cli(["--retag", "--dirs", str(lib2), "--out", str(out)]) == 0
    draft = json.loads(out.read_text(encoding="utf-8"))["templates"]
    assert "mystery_ad" in draft and "news_disp_school_5x20" not in draft
    assert draft["mystery_ad"]["_draft"] is True


def test_every_library_template_is_tagged_or_derivable(lib):
    data = ts.load_data()
    idx = ts.get_index()
    reviewed = 0
    for t in ts.load_library([lib]):
        tags, src = ts.effective_tags(t, data, idx)
        assert tags["kind"] and tags["language"] in ("hindi", "english", "bilingual")
        assert tags["colour"] in ("bw", "colour")
        reviewed += src == "reviewed"
    assert reviewed >= 45
    for tid in data["templates"]:
        assert (lib / tid).is_dir() or tid not in json.loads(
            (FIX / "sla_facts.json").read_text(encoding="utf-8")), tid


def test_tag_file_covers_all_news_templates(lib):
    data = ts.load_data()
    missing = [t["id"] for t in ts.load_library([lib])
               if t["id"].startswith(("news_", "ad_")) and t["id"] not in data["templates"]]
    assert missing == []


# ---- images ----------------------------------------------------------------------------
def test_response_has_contact_sheet_and_previews(lib):
    from mcp.types import ImageContent, TextContent
    res = ts.search("Diwali greetings ad", [lib])
    blocks = ts.build_response(res)
    n = len(res["candidates"])
    assert isinstance(blocks[0], TextContent)
    imgs = [b for b in blocks if isinstance(b, ImageContent)]
    assert len(imgs) == n + 1
    sheet = Image.open(io.BytesIO(base64.b64decode(imgs[0].data)))
    assert imgs[0].mimeType == "image/jpeg" and sheet.width > 300 and sheet.height > 200
    for b in imgs[1:]:
        im = Image.open(io.BytesIO(base64.b64decode(b.data)))
        assert max(im.size) <= 480
    j = json.loads(blocks[0].text)
    assert j["candidates"][0]["number"] == 1 and "new_from_template" in j["next_step"]
    assert "preview" not in j["candidates"][0]


def test_contact_sheet_numbers_and_missing_preview():
    cands = [{"number": i, "id": f"t{i}", "size_label": "A4 portrait", "colour": "colour",
              "preview": None} for i in (1, 2, 3, 4)]
    data = ts.contact_sheet(cands)
    im = Image.open(io.BytesIO(data))
    assert im.size[0] > 3 * 380 and im.size[1] > 2 * 330        # 3 columns x 2 rows
    assert len(ts.candidate_png(None)) > 100                      # placeholder image


# ---- field classifier -------------------------------------------------------------------
def _frame(name, x, y, w, h, text, size=12.0, font="Arial Bold", color="Black"):
    return {"name": name, "page": 1, "geom": [x, y, w, h], "text": text,
            "runs": [[text, font, size, color]]}


def test_classify_fields_roles():
    scan = {"page_w_mm": 202.0, "page_h_mm": 200.0, "pages": 1, "other": [{"name": "Poly1", "type": 6}],
            "frames": [
                _frame("A", 5, 5, 20, 20, "YOUR\rLOGO", 14),
                _frame("B", 30, 5, 150, 15, "SUNRISE SCHOOL", 38, "Impact Regular"),
                _frame("C", 10, 40, 140, 34, "ADMISSIONS OPEN", 53, "Impact Regular"),
                _frame("D", 10, 150, 190, 15, "ADMISSION HELPLINE: 98XXX XXXXX | 0120-XXXXXXX", 17),
                _frame("E", 10, 180, 190, 18, "Address: Plot No. 00, Sector 00, Your City", 8, "Arial Regular"),
                _frame("F", 100, 80, 44, 30, "SCHOLARSHIP\rUP TO\r100%", 24, "Arial Black"),
                _frame("G", 10, 90, 100, 6, "Experienced faculty", 12),
                _frame("H", 10, 98, 100, 6, "Smart classes", 12),
                _frame("I", 10, 106, 100, 6, "Sports and music", 12),
                _frame("J", 10, 120, 35, 35, "SESSION\r2027-28", 10),
                _frame("K", 10, 130, 60, 30, "YOUR CAR PHOTO", 9),
            ]}
    out = tf.classify_fields(scan)
    roles = {f["name"]: f["role"] for f in out["fields"]}
    assert roles["A"] == "logo_slot" and roles["C"] == "headline" and roles["D"] == "contact"
    assert roles["E"] == "fine_print" and roles["F"] == "offer" and roles["K"] == "photo_slot"
    assert roles["G"] == roles["H"] == roles["I"] == "list_item"
    assert roles["J"] == "badge" and roles["B"] == "business_name"
    assert out["decorative"]["count"] == 1
    d = next(f for f in out["fields"] if f["name"] == "C")
    assert d["char_budget"]["approx_total"] > 5 and d["frame_mm"] == [140, 34]


def test_classify_unsure_is_unknown_not_invented():
    scan = {"page_w_mm": 100, "page_h_mm": 100, "pages": 1, "other": [],
            "frames": [_frame("A", 5, 50, 40, 8, "Lorem ipsum dolor", 10),
                       _frame("B", 5, 60, 40, 8, "Dolor sit amet", 10)]}
    roles = {f["name"]: f["role"] for f in tf.classify_fields(scan)["fields"]}
    assert set(roles.values()) <= {"unknown", "subheadline", "body_text"}


def test_classify_hindi_kruti_runs():
    scan = {"page_w_mm": 120, "page_h_mm": 100, "pages": 1, "other": [],
            "frames": [_frame("A", 5, 80, 110, 10, "lEidZ% 98XXX XXXXX", 20, "Kruti Dev 010 Regular")]}
    f = tf.classify_fields(scan)["fields"][0]
    assert f["language"] in ("hindi", "mixed") and f["role"] == "contact"


def test_resolve_keys_by_name_and_role():
    fields = [{"name": "T1", "role": "headline"}, {"name": "T2", "role": "contact"},
              {"name": "T3", "role": "contact"}]
    m, err = tf._resolve_keys({"headline": "x", "contact_2": "y", "T2": "z", "bogus": "q"}, fields)
    assert m == {"T1": "x", "T3": "y", "T2": "z"} and len(err) == 1


def test_paragraph_styles_kept_when_paragraph_count_matches():
    runs = [["SCHOLARSHIP\r", "Arial Bold", 9.0, "White"], ["UP TO\r", "Arial Bold", 12.0, "White"],
            ["100%", "Arial Black", 24.0, "White"]]
    rr, font, size, color = tf.build_field_runs("SCHOLARSHIP\nUP TO\n50%", runs)
    assert rr and [r["size_pt"] for r in rr] == [9.0, 12.0, 24.0]
    rr2, *_ = tf.build_field_runs("one line", runs)
    assert rr2 is None


# ---- shared-file wiring --------------------------------------------------------------------
def test_tools_registered_and_in_ads_toolset():
    from scribus_mcp.tools import ADS_TOOLSET
    assert "find_templates" in ADS_TOOLSET and "fill_template_fields" in ADS_TOOLSET
    from scribus_mcp.server import INSTRUCTIONS
    assert "find_templates" in INSTRUCTIONS and "fill_template_fields" in INSTRUCTIONS


def test_best_practices_documents_the_flow():
    doc = (Path(__file__).parent.parent / "doc" / "BEST_PRACTICES.md").read_text(encoding="utf-8")
    assert "find_templates" in doc and "fill_template_fields" in doc and "export_press_pdf" in doc


# ---- live (needs a Scribus bridge: SCRIBUS_MCP_LIVE=1) ----------------------------------------
LIVE = os.environ.get("SCRIBUS_MCP_LIVE") == "1"


def _data(out):
    if isinstance(out, tuple) and isinstance(out[1], dict) and out[1]:
        return out[1]
    content = out[0] if isinstance(out, tuple) else out
    return json.loads(content[0].text)


@pytest.mark.skipif(not LIVE, reason="set SCRIBUS_MCP_LIVE=1 for live Scribus tests")
class TestLive:
    def _server(self):
        from scribus_mcp.server import build_server
        return build_server()

    def test_find_then_open_then_fill(self, tmp_path, lib, monkeypatch):
        from mcp.types import ImageContent
        monkeypatch.setenv("SCRIBUS_MCP_TEMPLATE_DIRS", str(os.environ.get("SCRIBUS_MCP_TEMPLATE_DIRS", lib)))
        srv = self._server()

        async def run():
            out = await srv.call_tool("find_templates", {"requirement": "school ad for new admission"})
            content = out[0] if isinstance(out, tuple) else out
            imgs = [c for c in content if isinstance(c, ImageContent)]
            j = json.loads(content[0].text)
            assert len(imgs) == len(j["candidates"]) + 1
            tid = j["candidates"][0]["id"]
            r = await srv.call_tool("new_from_template", {"template": tid, "save_as": str(tmp_path / "a.sla")})
            r = _data(r)
            assert r["ok"] and r["editable_fields"]
            head = next(f for f in r["editable_fields"] if f["role"] == "headline")
            f = await srv.call_tool("fill_template_fields", {"fields": {head["name"]: "ADMISSIONS OPEN"}})
            f = _data(f)
            assert f["ok"] and f["verify"]["passed"]

        asyncio.run(run())
