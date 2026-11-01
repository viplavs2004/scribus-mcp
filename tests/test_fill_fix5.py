"""Template asset copy, height-only resize, remove/expand, body block + sign-off logic, compare family.
Pure tests (no Scribus binary)."""

from __future__ import annotations

import asyncio
import gzip
import types
from pathlib import Path

import pytest

from scribus_mcp.tools.template_assets import copy_template_assets, preview_names, referenced_images
from scribus_mcp.tools.template_fields import (
    build_field_spec,
    find_signoff_pair,
    plan_expand,
    resolve_removals,
)
from scribus_mcp.tools.template_resize import (
    PT_PER_MM,
    plan_height_change,
    resize_sla_height,
    scale_path_y,
)

# --------------------------------------------------------------------------- a synthetic GN-like .sla


def _obj(name, typ, x, y, w, h, extra="", path=True):
    p = f'Path="M0 0 L{w} 0 L{w} {h} L0 {h} L0 0 Z" ContourLinePath="M0 0 L{w} 0 L{w} {h} L0 {h} L0 0 Z" ' if path else ""
    return (f'<PageObject XPosition="{x}" YPosition="{y}" OwnPage="0" ItemID="{abs(hash(name)) % 10**8}" '
            f'ItemType="{typ}" Width="{w}" Height="{h}" AutoName="{name}" {p}gXpos="{x}" gYpos="{y}" {extra}/>')


def make_sla(image="logo.png"):
    objs = [
        _obj("outer_border", 6, 105, 25, 182.7559, 174.2520),
        _obj("decor_logo", 2, 108.5, 28, 30.4, 32.64, f'ImageFileName="{image}"'),
        _obj("header", 4, 141, 31, 144, 22.5),
        _obj("body", 4, 108, 76.5, 176, 82.452, 'NextItem="9" BackItem="-1"'),
        _obj("body_last_line", 4, 108, 158.952, 86, 12, 'NextItem="-1" BackItem="1"'),
        _obj("signoff", 4, 196, 158.952, 88, 36.5),
    ]
    return ('<?xml version="1.0" encoding="UTF-8"?>\n<SCRIBUSUTF8NEW Version="1.7.4.svn">\n'
            '<Document PageCount="1" PageWidth="192.7559" PageHeight="184.2520" UnitIndex="0">\n'
            '<Page PageXPosition="100" PageYPosition="20" PageWidth="192.7559" PageHeight="184.2520" Size="Custom"/>\n'
            + "\n".join(objs) + "\n</Document>\n</SCRIBUSUTF8NEW>\n")


def _items(text):
    from scribus_mcp.tools.template_resize import read_items

    return {i["name"]: i for i in read_items(text)[0]}


# --------------------------------------------------------------------------- resize maths


def test_plan_height_change_roles_for_grow_and_shrink():
    items = [
        {"name": "border", "kind": "other", "y": 0.0, "h": 100.0, "w": 60},
        {"name": "logo", "kind": "other", "y": 3.0, "h": 30.0, "w": 30},
        {"name": "header", "kind": "text", "y": 5.0, "h": 20.0, "w": 40},
        {"name": "body", "kind": "text", "y": 40.0, "h": 40.0, "w": 60},
        {"name": "last", "kind": "text", "y": 80.0, "h": 10.0, "w": 30, "continuation": True},
        {"name": "sign", "kind": "text", "y": 80.0, "h": 15.0, "w": 30},
    ]
    p = plan_height_change(items, 20.0)
    ch = p["changes"]
    assert p["body"] == "body" and ch["body"] == {"role": "body", "y": 40.0, "h": 60.0}
    assert ch["last"]["y"] == 100.0 and ch["sign"]["y"] == 100.0 and ch["sign"]["h"] == 15.0
    assert ch["border"] == {"role": "stretch", "y": 0.0, "h": 120.0}
    assert "header" not in ch and "logo" not in ch  # top anchored, beside the body
    q = plan_height_change(items, -15.0, min_body=10.0)
    assert q["changes"]["body"]["h"] == 25.0 and q["changes"]["sign"]["y"] == 65.0
    assert q["changes"]["border"]["h"] == 85.0
    with pytest.raises(ValueError):
        plan_height_change(items, -35.0, min_body=10.0)


def test_plan_height_change_warns_about_several_bodies():
    items = [{"name": "a", "kind": "text", "y": 0.0, "h": 50.0, "w": 50},
             {"name": "b", "kind": "text", "y": 60.0, "h": 45.0, "w": 50}]
    p = plan_height_change(items, 5.0)
    assert p["warnings"] and p["body"] == "a"


def test_scale_path_y():
    assert scale_path_y("M0 0 L10 0 L10 20 L0 20 L0 0 Z", 2.0) == "M0 0 L10 0 L10 40 L0 40 L0 0 Z"
    assert scale_path_y("M0 0 C1 2 3 4 5 6", 0.5) == "M0 0 C1 1 3 2 5 3"


def test_resize_sla_height_rewrites_page_items_and_paths():
    text = make_sla()
    new, rep = resize_sla_height(text, extra_height_mm=10.0)
    d = 10.0 * PT_PER_MM
    assert rep["changed"] and rep["delta_mm"] == 10.0 and rep["page_h_mm"] == pytest.approx(65.0 + 10.0, abs=0.1)
    old, now = _items(text), _items(new)
    assert now["body"]["h"] == pytest.approx(old["body"]["h"] + d, abs=1e-3)
    assert now["signoff"]["y"] == pytest.approx(old["signoff"]["y"] + d, abs=1e-3)
    assert now["body_last_line"]["y"] == pytest.approx(old["body_last_line"]["y"] + d, abs=1e-3)
    assert now["outer_border"]["h"] == pytest.approx(old["outer_border"]["h"] + d, abs=1e-3)
    assert now["header"]["y"] == old["header"]["y"] and now["decor_logo"]["h"] == old["decor_logo"]["h"]
    # width untouched everywhere, border path rescaled to the new height
    assert all(now[n]["w"] == old[n]["w"] for n in old)
    assert f"L0 {now['outer_border']['h']:.4f}".rstrip("0").rstrip(".") in new  # border outline follows
    # page height in <Document> and <Page> agree and PageWidth is unchanged
    import re

    hs = set(re.findall(r'PageHeight="([^"]+)"', new))
    assert len(hs) == 1 and float(hs.pop()) == pytest.approx(184.252 + d, abs=1e-3)
    assert set(re.findall(r'PageWidth="([^"]+)"', new)) == {"192.7559"}


def test_resize_sla_height_absolute_noop_and_errors():
    text = make_sla()
    same, rep = resize_sla_height(text, height_mm=65.0)
    assert not rep["changed"] and same == text
    _, rep = resize_sla_height(text, height_mm=50.0)
    assert rep["delta_mm"] == pytest.approx(-15.0, abs=0.1)
    with pytest.raises(ValueError):
        resize_sla_height(text, height_mm=70.0, extra_height_mm=3.0)
    with pytest.raises(ValueError):
        resize_sla_height(text, height_mm=10.0)  # page below 20 mm
    with pytest.raises(ValueError):
        resize_sla_height(text, extra_height_mm=-40.0)  # body would vanish
    with pytest.raises(ValueError):
        resize_sla_height(text.replace('PageCount="1"', 'PageCount="2"'), extra_height_mm=5.0)


# --------------------------------------------------------------------------- assets


def _template_dir(tmp_path, ref="logo.png"):
    src = tmp_path / "tpl" / "news_x"
    src.mkdir(parents=True)
    (src / "news_x.sla").write_text(make_sla(ref), encoding="utf-8")
    (src / "news_x.png").write_bytes(b"preview")
    (src / "news_xtn.png").write_bytes(b"thumb")
    (src / "logo.png").write_bytes(b"LOGO")
    (src / "extra.jpg").write_bytes(b"EXTRA")
    (src / "notes.txt").write_text("not an image")
    return src


def test_copy_assets_copies_logo_and_companions_but_not_previews(tmp_path):
    src = _template_dir(tmp_path)
    dst = tmp_path / "out" / "doc.sla"
    dst.parent.mkdir()
    text = (src / "news_x.sla").read_text(encoding="utf-8")
    new, rep = copy_template_assets(text, src / "news_x.sla", dst, str(src / "news_x.png"))
    assert new == text and rep["missing"] == [] and not rep["rewritten"]
    assert sorted(p.name for p in dst.parent.iterdir()) == ["extra.jpg", "logo.png"]
    assert set(rep["copied"]) == {"logo.png", "extra.jpg"}
    assert (dst.parent / "logo.png").read_bytes() == b"LOGO"
    assert preview_names(src / "news_x.sla", None) == {"news_x.png", "news_xtn.png"}
    assert referenced_images(text) == ["logo.png"]


def test_copy_assets_absolute_path_is_rewritten_and_missing_reported(tmp_path):
    src = _template_dir(tmp_path)
    dst = tmp_path / "out" / "doc.sla"
    dst.parent.mkdir()
    absolute = str(src / "logo.png").replace("\\", "/")
    text = make_sla(absolute)
    new, rep = copy_template_assets(text, src / "news_x.sla", dst)
    assert rep["rewritten"] == {absolute: "logo.png"} and 'ImageFileName="logo.png"' in new
    assert (dst.parent / "logo.png").is_file()
    # a reference that exists nowhere is reported (verify will then say image_missing)
    dst2 = tmp_path / "out2" / "doc.sla"
    dst2.parent.mkdir()
    new2, rep2 = copy_template_assets(make_sla("nothere.png"), src / "news_x.sla", dst2)
    assert rep2["missing"] == ["nothere.png"] and rep2["warnings"]
    assert 'ImageFileName="nothere.png"' in new2


def test_copy_assets_never_overwrites_a_different_file(tmp_path):
    src = _template_dir(tmp_path)
    out = tmp_path / "out"
    out.mkdir()
    (out / "logo.png").write_bytes(b"SOMEONE ELSES LOGO")
    dst = out / "doc.sla"
    new, rep = copy_template_assets(make_sla("logo.png"), src / "news_x.sla", dst)
    assert (out / "logo.png").read_bytes() == b"SOMEONE ELSES LOGO"
    assert rep["rewritten"] == {"logo.png": "doc_logo.png"} and 'ImageFileName="doc_logo.png"' in new
    assert (out / "doc_logo.png").read_bytes() == b"LOGO"


def test_all_share_templates_with_images_resolve(tmp_path):
    """Every template of the Scribus build that references image files: they all copy next to the
    new document (skipped when the build folder is not on this machine)."""
    share = Path(r"C:\Users\hp\Desktop\project\Scribus-builds\Scribus-Release-x64-v143\share\templates")
    if not share.is_dir():
        pytest.skip("no Scribus build share folder")
    n = 0
    for sla in sorted(share.glob("*/*.sla.gz")):
        text = gzip.decompress(sla.read_bytes()).decode("utf-8", "replace")
        refs = referenced_images(text)
        if not refs:
            continue
        n += 1
        dst = tmp_path / sla.parent.name / "doc.sla"
        dst.parent.mkdir()
        _, rep = copy_template_assets(text, sla, dst)
        assert not rep["missing"], (sla.name, rep)
        for r in refs:
            assert (dst.parent / r).is_file(), (sla.name, r)
    assert n >= 5


# --------------------------------------------------------------------------- new_from_template guards


def _tool(tmp_path):
    from scribus_mcp.tools import templates

    tools = {}

    class FakeMcp:
        def tool(self):
            def deco(fn):
                tools[fn.__name__] = fn
                return fn
            return deco

    src = tmp_path / "tpl" / "news_x"
    src.mkdir(parents=True)
    (src / "news_x.sla.gz").write_bytes(gzip.compress(make_sla().encode("utf-8")))
    (src / "logo.png").write_bytes(b"LOGO")
    ctx = types.SimpleNamespace(config=types.SimpleNamespace(scribus_bin=None))
    templates.register(FakeMcp(), ctx)
    return tools["new_from_template"], tmp_path / "tpl"


def test_new_from_template_rejects_other_width_and_bad_heights(tmp_path, monkeypatch):
    fn, tpl = _tool(tmp_path)
    monkeypatch.setenv("SCRIBUS_MCP_TEMPLATE_DIRS", str(tpl))
    out = str(tmp_path / "o" / "x.sla")
    r = asyncio.run(fn("news_x", out, width_mm=80.0))
    assert not r["ok"] and "fixed" in r["error"] and "68" in r["error"]
    r = asyncio.run(fn("news_x", out, height_mm=10.0))
    assert not r["ok"] and "height change not possible" in r["error"]
    r = asyncio.run(fn("news_x", out, height_mm=70.0, extra_height_mm=2.0))
    assert not r["ok"]
    assert not (tmp_path / "o" / "x.sla").exists()


# --------------------------------------------------------------------------- remove / expand / pair


GN_FRAMES = [
    {"name": "header", "page": 1, "geom": [14.5, 3.9, 50.8, 7.9]},
    {"name": "address", "page": 1, "geom": [14.5, 11.8, 50.8, 3.7]},
    {"name": "title", "page": 1, "geom": [14.5, 15.5, 50.8, 4.2]},
    {"name": "body", "page": 1, "geom": [2.8, 19.9, 62.1, 29.1], "next": "body_last_line"},
    {"name": "body_last_line", "page": 1, "geom": [2.8, 49.0, 30.3, 4.2], "first": "body"},
    {"name": "signoff", "page": 1, "geom": [33.9, 49.0, 31.0, 12.9]},
]
GN_SCAN = {"frames": GN_FRAMES, "other": [
    {"name": "outer_border", "type": 6, "page": 1, "geom": [0.0, 0.0, 64.5, 61.5]},
    {"name": "decor_logo", "type": 2, "page": 1, "geom": [1.2, 2.8, 10.7, 11.5]}]}


def test_find_signoff_pair_gn_and_nagar_geometry():
    assert find_signoff_pair(GN_FRAMES, "body") == {"last": "body_last_line", "signoff": "signoff"}
    nagar = [
        {"name": "body", "page": 1, "geom": [37.1, 20.9, 59.8, 43.2]},
        {"name": "body_last_line", "page": 1, "geom": [37.1, 63.8, 38.0, 4.0]},
        {"name": "signoff", "page": 1, "geom": [74.3, 63.8, 22.6, 7.5]},
        {"name": "title", "page": 1, "geom": [37.1, 16.5, 59.8, 4.2]},
    ]
    assert find_signoff_pair(nagar, "body") == {"last": "body_last_line", "signoff": "signoff"}
    assert find_signoff_pair(nagar[:1], "body") == {"last": None, "signoff": None}


def test_resolve_removals_names_and_decorative():
    r, e = resolve_removals(["decor_logo"], GN_SCAN)
    assert [x["name"] for x in r] == ["decor_logo"] and not e
    r, e = resolve_removals("decorative", GN_SCAN)
    assert [x["name"] for x in r] == ["decor_logo"]  # images only, never borders
    r, e = resolve_removals(["nope"], GN_SCAN)
    assert not r and "nope" in e[0]
    assert resolve_removals(None, GN_SCAN) == ([], [])


def test_plan_expand_stretches_frames_beside_the_removed_image():
    logo = GN_SCAN["other"][1]
    ex = plan_expand(logo, GN_FRAMES)
    names = {e["name"] for e in ex}
    assert names == {"header", "address"}  # title starts below the logo; body is below
    h = next(e for e in ex if e["name"] == "header")
    assert h["x_mm"] == 1.2 and h["w_mm"] == pytest.approx(14.5 + 50.8 - 1.2)
    assert plan_expand({"geom": [60, 0, 5, 5], "page": 1}, GN_FRAMES) == []  # nothing to its right


# --------------------------------------------------------------------------- body block spec


RUNS = [["abc", "Kruti Dev 010 Regular", 8.4, "Black"]]


def test_body_like_field_gets_block_fitting_with_growth_cap():
    spec, _ = build_field_spec("body", 1, {"text": "hello", "align": "justify"}, {"ls": 12.0, "lsm": 0}, RUNS,
                               min_pt=5.0, body_like=True)
    s = spec["solve"]
    assert s["block"] and s["fit"] == "fill"
    assert s["max_pt"] == pytest.approx(10.5) and s["grow2"] == pytest.approx(12.5)


def test_explicit_sizing_or_opt_out_disables_block():
    for opts in ({"size": 7}, {"leading": 9}, {"target_lines": 6}, {"fit": "shrink"}, {"auto_block": False}):
        spec, _ = build_field_spec("body", 1, {"text": "x", **opts}, {}, RUNS, min_pt=5.0, body_like=True)
        assert not spec["solve"]["block"], opts
    spec, _ = build_field_spec("body", 1, {"text": "x", "fit": "fill", "max_size": 9}, {}, RUNS,
                               min_pt=5.0, body_like=True)
    assert spec["solve"]["block"] and spec["solve"]["max_pt"] == 9.0 and "grow2" not in spec["solve"]
    spec, _ = build_field_spec("header", 1, "hi", {}, RUNS, min_pt=5.0)  # not body-like: unchanged default
    assert not spec["solve"]["block"] and spec["solve"]["fit"] == "shrink"


def test_solver_block_mode_spreads_leading_to_fill_the_frame():
    from tests.test_fill_tools import TEXT, _run

    plain, _ = _run(TEXT, 300, 200, fit="fill", base=9.0, max_pt=9.0, leading_ratio=1.2)
    blk, _ = _run(TEXT, 300, 200, fit="fill", base=9.0, max_pt=9.0, leading_ratio=1.2, block=True)
    assert not blk["overflow"] and blk["size_pt"] == plain["size_pt"]
    assert blk["leading_pt"] > plain["leading_pt"] + 0.5 and blk["leading_pt"] <= 1.5 * blk["size_pt"] + 0.01
    assert blk["lines"] * blk["leading_pt"] <= 200 + 1e-6
    assert blk["tail_lines"] is None and blk["tail_empty"] is False
    assert blk["blank_pt"] is not None and blk["blank_pt"] < plain["blank_pt"]


# --------------------------------------------------------------------------- compare: layout family


def _an(border="single", bands=("header", "header", "body", "signoff"), cols=1, just=True):
    return {"border": {"style": border}, "bands": [{"role": r} for r in bands],
            "body": {"columns": cols, "justified": just, "lines": 12}}


def test_layout_family_ignores_logo_and_height_but_sees_real_differences():
    from scribus_mcp.tools.reference_image import layout_family

    ref = _an()
    assert layout_family(ref, _an(bands=("header", "body", "signoff")))["match"]       # logo merged a band
    assert layout_family(ref, _an())["score"] == 1.0
    far = layout_family(ref, _an(border="none", bands=("body",), cols=2, just=False))
    assert not far["match"] and far["reasons"]


def test_compare_low_similarity_by_shape_says_family_matches(tmp_path):
    from tests.test_reference_image import H, W, make_notice

    from scribus_mcp.tools.reference_image import compare_images

    pytest.importorskip("PIL")
    from PIL import Image

    a, b = tmp_path / "a.png", tmp_path / "b.png"
    make_notice(a, body_lines=17)
    Image.open(a).crop((0, 0, W, int(H * 0.62))).save(b)  # same notice, much shorter page
    c = compare_images(a, b, 100.0)
    assert c["differences"]["aspect_ratio"]["diff_percent"] != 0
    text = " ".join(c["hints"]).lower()
    assert "page shape" in text and "height_mm" in text
    if c["layout_family_match"]:
        assert "do not rebuild" in text
    assert not any("adjust leading" in h or "re-layout the" in h for h in c["hints"])
    assert "layout_family_match" in c and "layout_family_score" in c
