"""analyze_reference_image on synthetic pictures with known geometry (Pillow only)."""

from __future__ import annotations

import random

import pytest

PIL = pytest.importorskip("PIL")
from PIL import Image, ImageDraw  # noqa: E402

from scribus_mcp.tools.reference_image import analyze_image  # noqa: E402

W, H = 600, 800


def _words(dr, rng, x0, x1, y, line_h, last=False, ink=(0, 0, 0)):
    """One text line made of word blocks between x0 and x1 (justified unless ``last``)."""
    x = x0
    end = x0 + (x1 - x0) * (0.45 if last else 1.0)
    while x < end - 25:
        w = min(rng.randint(24, 60), end - x)
        if end - (x + w + 7) < 25:
            w = end - x  # last word flush with the right edge (justified)
        # shirorekha bar on top + body of the letters
        dr.rectangle([x, y, x + w, y + 2], fill=ink)
        dr.rectangle([x + 3, y + 3, x + w - 3, y + line_h * 0.75], fill=ink)
        x += w + 7
    return


def make_notice(path, *, double=True, columns=1, body_lines=17, colour_block=False, seed=1):
    rng = random.Random(seed)
    img = Image.new("RGB", (W, H), "white")
    dr = ImageDraw.Draw(img)
    m = 12
    dr.rectangle([m, m, W - m - 1, H - m - 1], outline="black", width=6)
    if double:
        o = m + 6 + 8
        dr.rectangle([o, o, W - o - 1, H - o - 1], outline="black", width=3)
        inner = o + 3 + 10
    else:
        inner = m + 6 + 10
    x0, x1 = inner, W - inner
    y = inner + 4
    _words(dr, rng, x0 + 60, x1 - 60, y, 28)          # header, one big line
    y += 56
    _words(dr, rng, x0 + 150, x1 - 150, y, 20)        # title, centred, shorter
    y += 54
    top_body = y
    pitch, lh = 24, 14
    if columns == 1:
        for i in range(body_lines):
            _words(dr, rng, x0, x1, y, lh, last=(i == body_lines - 1))
            y += pitch
    else:
        gut = 44
        cw = (x1 - x0 - gut) // 2
        for i in range(body_lines):
            yy = top_body + i * pitch
            _words(dr, rng, x0, x0 + cw, yy, lh)
            _words(dr, rng, x0 + cw + gut, x1, yy, lh)
        y = top_body + body_lines * pitch
    y += 30
    for i in range(3):  # right-aligned sign-off, 3 lines, pitch 22
        _words(dr, rng, x1 - 200 + 20 * i, x1, y + i * 22, 12)
    if colour_block:
        dr.rectangle([x0, H - 200, x0 + 130, H - 120], fill=(20, 150, 60))
    img.save(path)
    return img


def test_double_border_justified_body_geometry(tmp_path):
    p = tmp_path / "n.png"
    make_notice(p)
    r = analyze_image(p, width_mm=100.0)
    assert r["image"]["aspect_ratio"] == pytest.approx(W / H, abs=1e-3)
    assert r["page_mm"] == [100.0, round(H * 100 / W, 1)]
    b = r["border"]
    assert b["found"] and b["style"] == "double"
    assert b["thickness_px"] == pytest.approx(6, abs=1.5)
    assert b["inner_thickness_px"] == pytest.approx(3, abs=1.5)
    assert b["gap_px"] == pytest.approx(8, abs=2)
    assert b["outer_rect_px"][:2] == [12, 12]
    body = r["body"]
    assert body["lines"] == 17 and body["justified"] and body["columns"] == 1
    assert body["pitch_px"] == pytest.approx(24, abs=0.6)
    # leading in pt = pitch * mm_per_px * 72 / 25.4
    assert body["leading_pt"] == pytest.approx(24 * (100 / 600) * 72 / 25.4, rel=0.03)
    roles = [bd["role"] for bd in r["bands"]]
    assert roles.count("body") == 1 and roles[0] == "header" and roles[-1] == "signoff"
    assert len(r["bands"]) == 4
    assert r["black_and_white"] and not r["image_blocks"]
    d = r["layout_descriptor"]
    assert "double border" in d and "justified body ~17 lines" in d and "text only" in d
    assert "100 x 133.3 mm" in r["suggested_query"]
    assert r["layout_hint"]["aspect_ratio"] == pytest.approx(0.75, abs=1e-3)


def test_single_border_and_no_scale(tmp_path):
    p = tmp_path / "n.png"
    make_notice(p, double=False, body_lines=10)
    r = analyze_image(p)
    assert r["border"]["style"] == "single"
    assert r["page_mm"] is None and r["body"]["leading_pt"] is None
    assert r["body"]["lines"] == 10 and r["scale_note"]


def test_two_columns_detected(tmp_path):
    p = tmp_path / "n.png"
    make_notice(p, columns=2, body_lines=12)
    assert analyze_image(p)["body"]["columns"] == 2


def test_colour_block_and_not_black_and_white(tmp_path):
    p = tmp_path / "n.png"
    make_notice(p, colour_block=True)
    r = analyze_image(p)
    assert not r["black_and_white"]
    assert r["image_blocks"], "the solid green block should be reported"
    assert "with image/logo area" in r["layout_descriptor"]


def test_no_border_blank_and_bad_input(tmp_path):
    p = tmp_path / "blank.png"
    Image.new("RGB", (300, 200), "white").save(p)
    r = analyze_image(p)
    assert r["border"]["style"] == "none" and r["body"] is None and r["bands"] == []
    with pytest.raises(FileNotFoundError):
        analyze_image(tmp_path / "missing.png")


def test_overlay_is_written(tmp_path):
    p = tmp_path / "n.png"
    make_notice(p)
    r = analyze_image(p, overlay_path=tmp_path / "ov.png")
    assert (tmp_path / "ov.png").is_file() and r["overlay_path"]


def test_tool_registered_and_in_ads_toolset():
    from scribus_mcp.tools import ADS_TOOLSET

    assert "analyze_reference_image" in ADS_TOOLSET


def test_compare_identical_and_different(tmp_path):
    from scribus_mcp.tools.reference_image import compare_images

    a, b, c = tmp_path / "a.png", tmp_path / "b.png", tmp_path / "c.png"
    make_notice(a, body_lines=17)
    make_notice(b, body_lines=17, seed=7)       # same layout, different "words"
    make_notice(c, double=False, body_lines=10)  # different layout
    same = compare_images(a, a, 100.0)
    assert same["similarity"] > 0.99 and not same["hints"]
    near = compare_images(a, b, 100.0, tmp_path / "side.png")
    assert near["differences"]["body_lines"]["diff"] == 0
    assert near["similarity"] > 0.7 and (tmp_path / "side.png").is_file()
    far = compare_images(a, c, 100.0)
    assert far["differences"]["body_lines"]["diff"] == -7
    assert far["differences"]["border_style"] == {"reference": "double", "render": "single"}
    assert any("fewer" in h for h in far["hints"]) and far["similarity"] < near["similarity"]


def test_compare_tool_registered_and_in_ads_toolset():
    from scribus_mcp.tools import ADS_TOOLSET

    assert "compare_to_reference" in ADS_TOOLSET
