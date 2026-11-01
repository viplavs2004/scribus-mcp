"""``analyze_reference_image``: measure a photo / screenshot of a notice or ad from its pixels.

A client that gets a picture ("make it like this") needs numbers, not a guess: aspect ratio,
border rectangles and thickness, the text lines (count, pitch -> leading in pt), the bands
(header / title / body / sign-off), columns, black-and-white or colour, and a plain-words layout
descriptor it can hand to ``find_templates(layout_hint=...)``.

Pure Pillow (no numpy): profiles come from ``Image.resize`` box filters, so a 2000 px image takes
well under a second. Pillow is a core dependency of this package; ``Pillow`` is still imported
lazily so that a broken install gives a clear message.

Assumptions (also returned as ``notes``): ink is darker than the paper; the picture is a
reasonably straight crop of the ad (a rotated photo or a photo of a whole newspaper page is not
deskewed); pitch / leading in points is only computed when the caller passes the real
``width_mm`` of the picture (or of the ad when the picture is cropped to it).
"""

from __future__ import annotations

import statistics
from pathlib import Path
from typing import Any

from mcp.types import ImageContent, TextContent

from scribus_mcp.tools._common import Mode, get_backend

MAX_WORK_PX = 1500


def _pil():
    try:
        from PIL import Image, ImageDraw
    except Exception as exc:  # pragma: no cover
        raise RuntimeError(
            "Pillow is required for analyze_reference_image: pip install Pillow") from exc
    return Image, ImageDraw


def _box_filter(Image):
    return getattr(getattr(Image, "Resampling", Image), "BOX")


def _otsu(hist: list[int]) -> int:
    total = sum(hist)
    sum_all = sum(i * h for i, h in enumerate(hist))
    w_b = 0
    sum_b = 0.0
    best, thr = -1.0, 128
    for t in range(256):
        w_b += hist[t]
        if w_b == 0:
            continue
        w_f = total - w_b
        if w_f == 0:
            break
        sum_b += t * hist[t]
        m_b, m_f = sum_b / w_b, (sum_all - sum_b) / w_f
        var = w_b * w_f * (m_b - m_f) ** 2
        if var > best:
            best, thr = var, t
    return thr


class _Mask:
    """Binary ink mask ('L' image, 255 = ink) with cheap row / column profiles."""

    def __init__(self, Image, img):
        self.Image = Image
        self.img = img
        self.w, self.h = img.size

    def rows(self, box: tuple[int, int, int, int]) -> list[float]:
        x0, y0, x1, y1 = box
        if x1 <= x0 or y1 <= y0:
            return []
        c = self.img.crop(box).resize((1, y1 - y0), _box_filter(self.Image))
        return [v / 255.0 for v in c.tobytes()]

    def cols(self, box: tuple[int, int, int, int]) -> list[float]:
        x0, y0, x1, y1 = box
        if x1 <= x0 or y1 <= y0:
            return []
        c = self.img.crop(box).resize((x1 - x0, 1), _box_filter(self.Image))
        return [v / 255.0 for v in c.tobytes()]

    def bbox(self, box):
        return self.img.crop(box).getbbox()


def _runs(flags: list[bool], max_gap: int = 1) -> list[tuple[int, int]]:
    """Inclusive index runs of True, bridging gaps of up to ``max_gap``."""
    out: list[list[int]] = []
    for i, f in enumerate(flags):
        if not f:
            continue
        if out and i - out[-1][1] <= max_gap + 1:
            out[-1][1] = i
        else:
            out.append([i, i])
    return [(a, b) for a, b in out]


def _longest_run(seg: bytes, max_gap: int = 0) -> int:
    """Length of the longest stretch of ink (>127) in a 1-px strip, bridging gaps <= max_gap."""
    best = cur = gap = 0
    for v in seg:
        if v > 127:
            cur += gap + 1 if cur else 1
            gap = 0
        elif cur:
            gap += 1
            if gap > max_gap:
                best = max(best, cur)
                cur = gap = 0
    return max(best, cur)


def find_borders(mask: _Mask) -> dict[str, list[tuple[int, int]]]:
    """Long straight dark lines near each image edge: {'top': [(start, end)], ...} (px)."""
    w, h = mask.w, mask.h
    res: dict[str, list[tuple[int, int]]] = {"top": [], "bottom": [], "left": [], "right": []}
    rows = mask.rows((0, 0, w, h))
    cols = mask.cols((0, 0, w, h))

    def cand(profile, n, lo, hi, vertical):
        flags = []
        for i in range(n):
            ok = lo <= i < hi and profile[i] >= 0.8
            if ok:
                # a border is ONE long unbroken stroke; a dense row of Devanagari shirorekha
                # (headline bar of a justified line) is broken by word gaps
                if vertical:
                    seg = mask.img.crop((i, 0, i + 1, h)).tobytes()
                    ok = _longest_run(seg, 2) >= 0.8 * h
                else:
                    seg = mask.img.crop((0, i, w, i + 1)).tobytes()
                    ok = _longest_run(seg, 2) >= 0.8 * w
            flags.append(ok)
        return _runs(flags, 1)

    res["top"] = cand(rows, h, 0, int(0.2 * h), False)
    res["bottom"] = cand(rows, h, int(0.8 * h), h, False)
    res["left"] = cand(cols, w, 0, int(0.2 * w), True)
    res["right"] = cand(cols, w, int(0.8 * w), w, True)
    return res


def _median(xs: list[float], default: float = 0.0) -> float:
    return statistics.median(xs) if xs else default


def find_lines(mask: _Mask, box: tuple[int, int, int, int]) -> list[tuple[int, int]]:
    """Text line row ranges (absolute y) inside ``box``."""
    x0, y0, x1, y1 = box
    prof = mask.rows(box)
    nz = sorted(f for f in prof if f > 0.004)
    if len(nz) < 3:
        return []
    ref = nz[int(0.7 * (len(nz) - 1))]
    on = [f > max(0.006, 0.22 * ref) for f in prof]
    runs = _runs(on, 1)
    # drop specks, merge thin fragments (matras above / descenders below a line) into a neighbour
    heights = [b - a + 1 for a, b in runs]
    med = _median(heights, 1.0)
    changed = True
    runs = [r for r in runs if r[1] - r[0] + 1 >= 2]
    while changed and len(runs) > 1:
        changed = False
        med = _median([b - a + 1 for a, b in runs], 1.0)
        for i, (a, b) in enumerate(runs):
            if b - a + 1 >= 0.45 * med:
                continue
            nb = None
            if i > 0 and a - runs[i - 1][1] <= 0.5 * med:
                nb = i - 1
            if i + 1 < len(runs) and runs[i + 1][0] - b <= 0.5 * med and (
                    nb is None or runs[i + 1][0] - b < a - runs[nb][1]):
                nb = i + 1
            if nb is not None:
                lo, hi = sorted((i, nb))
                runs[lo:hi + 1] = [(runs[lo][0], runs[hi][1])]
                changed = True
                break
            runs.pop(i)
            changed = True
            break
    return [(y0 + a, y0 + b) for a, b in runs]


def group_bands(lines: list[tuple[int, int]]) -> list[dict[str, Any]]:
    """Group lines into bands (header, title, body, sign-off ...)."""
    if not lines:
        return []
    pitches = [lines[i][0] - lines[i - 1][0] for i in range(1, len(lines))]
    base = _median(pitches, 0.0)
    # the body dominates; use the lower-median pitch as the in-band pitch
    small = sorted(pitches)[: max(1, (len(pitches) * 3) // 4)] if pitches else []
    base = _median(small, base)
    bands: list[list[tuple[int, int]]] = [[lines[0]]]
    for i in range(1, len(lines)):
        prev, cur = lines[i - 1], lines[i]
        pitch = cur[0] - prev[0]
        hp, hc = prev[1] - prev[0] + 1, cur[1] - cur[0] + 1
        ratio = max(hp, hc) / max(1, min(hp, hc))
        if base and (pitch > 1.5 * base or ratio > 1.45 and len(bands[-1]) >= 1 and pitch > 1.15 * base):
            bands.append([cur])
        else:
            bands[-1].append(cur)
    return [_make_band(b) for b in bands]


def _make_band(b: list[tuple[int, int]]) -> dict[str, Any]:
    ps = [b[i][0] - b[i - 1][0] for i in range(1, len(b))]
    return {"lines": b, "top": b[0][0], "bottom": b[-1][1], "n": len(b),
            "pitch": _median(ps) if ps else None,
            "line_h": _median([e - s + 1 for s, e in b])}


def refine_bands(mask: _Mask, bands: list[dict[str, Any]], box: tuple[int, int, int, int]) -> list[dict[str, Any]]:
    """Peel a short centred title off the top of a body band and a right-hand sign-off off its end."""
    x0, _, x1, _ = box
    width = max(1, x1 - x0)
    out: list[dict[str, Any]] = []
    for bd in bands:
        lines = bd["lines"]
        n = len(lines)
        if n < 5:
            out.append(bd)
            continue
        ext = []
        for (a, c) in lines:
            bb = mask.bbox((x0, a, x1, c + 1))
            ext.append((x0 + bb[0], x0 + bb[2]) if bb else (x0, x0))
        widths = [r - l for l, r in ext]
        medw = _median(widths[1:], 1.0)
        medl = _median([l for l, _ in ext], x0)
        medr = _median([r for _, r in ext], x1)
        lead = 0
        while lead < 2 and lead < n - 4:
            l, r = ext[lead]
            if (r - l) < 0.72 * medw and l > medl + 0.05 * width and r < medr - 0.05 * width:
                lead += 1
            else:
                break
        trail = 0
        while trail < 4 and trail < n - 4 - lead:
            l, r = ext[n - 1 - trail]
            if l > medl + 0.25 * medw:
                trail += 1
            else:
                break
        parts = []
        if lead:
            parts.append(lines[:lead])
        parts.append(lines[lead:n - trail])
        if trail:
            parts.append(lines[n - trail:])
        out.extend(_make_band(p) for p in parts)
    return out


def band_geometry(mask: _Mask, band: dict[str, Any], box: tuple[int, int, int, int]) -> None:
    """Left / right extent per line, alignment and justification flags (in place)."""
    x0, _, x1, _ = box
    width = max(1, x1 - x0)
    lefts, rights = [], []
    for (a, b) in band["lines"]:
        bb = mask.bbox((x0, a, x1, b + 1))
        if bb:
            lefts.append(x0 + bb[0])
            rights.append(x0 + bb[2])
    band["left"] = min(lefts) if lefts else x0
    band["right"] = max(rights) if rights else x1
    band["align"] = "unknown"
    band["justified"] = False
    if not lefts:
        return
    cx = (band["left"] + band["right"]) / 2.0
    ccx = (x0 + x1) / 2.0
    n = len(lefts)
    if n >= 4:
        body_l, body_r = lefts[:-1], rights[:-1]
        tol = 0.02 * width
        if (max(body_r) - min(body_r) <= tol and max(body_l) - min(body_l) <= tol
                and (band["right"] - band["left"]) >= 0.6 * width):
            band["justified"] = True
            band["align"] = "justify"
            return
    if n >= 2 and max(lefts) - min(lefts) <= 0.03 * width and max(rights) - min(rights) > 0.04 * width:
        band["align"] = "left"
    elif n >= 2 and max(rights) - min(rights) <= 0.03 * width and max(lefts) - min(lefts) > 0.04 * width:
        band["align"] = "right"
    elif abs(cx - ccx) <= 0.04 * width and (band["right"] - band["left"]) < 0.98 * width:
        band["align"] = "center"
    elif band["left"] - x0 > 0.45 * width:
        band["align"] = "right"
    else:
        band["align"] = "left"


def count_columns(mask: _Mask, box: tuple[int, int, int, int]) -> int:
    x0, y0, x1, y1 = box
    prof = mask.cols(box)
    n = len(prof)
    if n < 40:
        return 1
    gap = max(3, int(0.012 * n))
    lo, hi = int(0.18 * n), int(0.82 * n)
    flags = [lo <= i < hi and prof[i] < 0.004 for i in range(n)]
    gutters = [r for r in _runs(flags, 0) if r[1] - r[0] + 1 >= gap]
    return len(gutters) + 1


def colour_profile(Image, img) -> dict[str, Any]:
    """Share of coloured (chromatic, non-paper) pixels -> black-and-white or colour."""
    small = img.copy()
    small.thumbnail((160, 160))
    raw = small.tobytes()
    ink = chroma = 0
    for i in range(0, len(raw) - 2, 3):
        r, g, b = raw[i], raw[i + 1], raw[i + 2]
        if r + g + b < 3 * 235:  # not paper white
            ink += 1
            if max(r, g, b) - min(r, g, b) > 45:
                chroma += 1
    frac = chroma / ink if ink else 0.0
    return {"black_and_white": frac < 0.03, "colour_fraction": round(frac, 3)}


def find_solid_blocks(mask: _Mask, box: tuple[int, int, int, int]) -> list[list[int]]:
    """Dense rectangular areas (photos, logos, solid panels) as [x0, y0, x1, y1]; text is lighter."""
    x0, y0, x1, y1 = box
    cell = max(6, (x1 - x0) // 40)
    gw, gh = (x1 - x0) // cell, (y1 - y0) // cell
    if gw < 4 or gh < 4:
        return []
    small = mask.img.crop((x0, y0, x0 + gw * cell, y0 + gh * cell)).resize((gw, gh), _box_filter(mask.Image))
    dens = list(small.tobytes())
    seen = [False] * (gw * gh)
    blocks = []
    for s in range(gw * gh):
        if seen[s] or dens[s] < 0.48 * 255:
            continue
        stack, cells = [s], []
        seen[s] = True
        while stack:
            c = stack.pop()
            cells.append(c)
            cx, cy = c % gw, c // gw
            for nx, ny in ((cx + 1, cy), (cx - 1, cy), (cx, cy + 1), (cx, cy - 1)):
                if 0 <= nx < gw and 0 <= ny < gh and not seen[ny * gw + nx] and dens[ny * gw + nx] >= 0.48 * 255:
                    seen[ny * gw + nx] = True
                    stack.append(ny * gw + nx)
        xs = [c % gw for c in cells]
        ys = [c // gw for c in cells]
        bw, bh = max(xs) - min(xs) + 1, max(ys) - min(ys) + 1
        if len(cells) >= 0.025 * gw * gh and bw >= 0.08 * gw and bh >= 0.08 * gh:
            blocks.append([x0 + min(xs) * cell, y0 + min(ys) * cell,
                           x0 + (max(xs) + 1) * cell, y0 + (max(ys) + 1) * cell])
    return blocks


def analyze_image(path: str | Path, width_mm: float | None = None, height_mm: float | None = None,
                  overlay_path: str | Path | None = None) -> dict[str, Any]:
    """Measure the picture. See the module docstring; all pixel values are in the ORIGINAL image."""
    Image, ImageDraw = _pil()
    p = Path(path)
    if not p.is_file():
        raise FileNotFoundError(f"image not found: {path}")
    orig = Image.open(p)
    orig.load()
    if orig.mode in ("RGBA", "LA", "P"):
        bg = Image.new("RGB", orig.size, (255, 255, 255))
        rgba = orig.convert("RGBA")
        bg.paste(rgba, mask=rgba.split()[-1])
        rgb = bg
    else:
        rgb = orig.convert("RGB")
    W0, H0 = rgb.size
    k = min(1.0, MAX_WORK_PX / max(W0, H0))
    work = rgb.resize((max(1, round(W0 * k)), max(1, round(H0 * k)))) if k < 1.0 else rgb
    W, H = work.size
    inv = 1.0 / k  # work px -> original px
    gray = work.convert("L")
    thr = _otsu(gray.histogram())
    ink_mask = gray.point(lambda v, t=thr: 255 if v <= t else 0)
    ink_frac = sum(1 for v in ink_mask.resize((64, 64), _box_filter(Image)).tobytes() if v > 127) / 4096.0
    inverted = False
    if ink_frac > 0.5:  # light ink on a dark ground
        ink_mask = ink_mask.point(lambda v: 255 - v)
        inverted = True
    mask = _Mask(Image, ink_mask)
    notes: list[str] = []
    if inverted:
        notes.append("light text on a dark background: inverted for the analysis")

    # --- borders
    b = find_borders(mask)
    sides = {s: v for s, v in b.items() if v}
    border: dict[str, Any] = {"found": len(sides) >= 3}
    inner_box = [int(0.02 * W), int(0.02 * H), int(0.98 * W), int(0.98 * H)]
    if border["found"]:
        # outer = outermost edge of the outermost line on each side
        outer = [b["left"][0][0] if b["left"] else 0, b["top"][0][0] if b["top"] else 0,
                 b["right"][-1][1] if b["right"] else W - 1, b["bottom"][-1][1] if b["bottom"] else H - 1]
        n_lines = max(len(v) for v in sides.values())
        outer_thick = _median([(v[0][1] - v[0][0] + 1) for v in sides.values()])
        inner_thick = _median([(v[-1][1] - v[-1][0] + 1) for v in sides.values() if len(v) > 1]) if n_lines > 1 else None
        gap = _median([(v[1][0] - v[0][1] - 1) for v in sides.values() if len(v) > 1]) if n_lines > 1 else None
        border.update({
            "style": "double" if n_lines >= 2 else "single",
            "sides_found": sorted(sides),
            "outer_rect_px": [round(c * inv) for c in outer],
            "thickness_px": round(outer_thick * inv, 1),
            "inner_thickness_px": round(inner_thick * inv, 1) if inner_thick else None,
            "gap_px": round(gap * inv, 1) if gap else None,
        })
        pad = max(2, int(0.008 * W))
        inner_box = [
            (b["left"][-1][1] + 1 + pad) if b["left"] else int(0.02 * W),
            (b["top"][-1][1] + 1 + pad) if b["top"] else int(0.02 * H),
            (b["right"][0][0] - pad) if b["right"] else int(0.98 * W),
            (b["bottom"][0][0] - pad) if b["bottom"] else int(0.98 * H),
        ]
    else:
        border["style"] = "none"
        if sides:
            border["sides_found"] = sorted(sides)
            notes.append("lines found on some sides only: " + ", ".join(sorted(sides)) + " (not a full border)")
    box = (max(0, inner_box[0]), max(0, inner_box[1]), min(W, inner_box[2]), min(H, inner_box[3]))

    # --- lines, bands
    lines = find_lines(mask, box)
    bands = refine_bands(mask, group_bands(lines), box)
    for bd in bands:
        band_geometry(mask, bd, box)
    body = None
    if bands:
        cand = [bd for bd in bands if bd["n"] >= 3]
        body = max(cand or bands, key=lambda bd: (bd["n"], bd["bottom"] - bd["top"]))
    cols = count_columns(mask, (box[0], body["top"], box[2], body["bottom"] + 1)) if body and body["n"] >= 3 else 1
    blocks = find_solid_blocks(mask, box)
    colour = colour_profile(Image, work)

    # --- scale
    mm_px = None
    page_mm = None
    if width_mm:
        mm_px = float(width_mm) / W0
        page_mm = [round(float(width_mm), 1), round(H0 * mm_px, 1)]
    elif height_mm:
        mm_px = float(height_mm) / H0
        page_mm = [round(W0 * mm_px, 1), round(float(height_mm), 1)]
    aspect = W0 / H0

    def lead_pt(pitch_work):
        return round(pitch_work * inv * mm_px * 72 / 25.4, 2) if (pitch_work and mm_px) else None

    out_bands = []
    for i, bd in enumerate(bands):
        role = "body" if bd is body else None
        if role is None:
            role = "header" if (body and bd["top"] < body["top"]) else "signoff"
        ob: dict[str, Any] = {
            "index": i + 1, "role": role, "lines": bd["n"],
            "top_px": round(bd["top"] * inv), "bottom_px": round(bd["bottom"] * inv),
            "left_px": round(bd["left"] * inv), "right_px": round(bd["right"] * inv),
            "line_height_px": round(bd["line_h"] * inv, 1),
            "pitch_px": round(bd["pitch"] * inv, 2) if bd["pitch"] else None,
            "align": bd["align"],
        }
        if mm_px and bd["pitch"]:
            ob["leading_pt"] = lead_pt(bd["pitch"])
        out_bands.append(ob)

    # --- descriptor words
    words: list[str] = []
    if border["style"] == "double":
        words.append("double border")
    elif border["style"] == "single":
        words.append("single border")
    else:
        words.append("no border")
    if bands:
        words.append(f"{len(bands)} bands")
    if body:
        if body["justified"]:
            words.append(f"justified body ~{body['n']} lines")
        else:
            words.append(f"{body['align']} body ~{body['n']} lines")
    if cols > 1:
        words.append(f"{cols} columns")
    words.append("with image/logo area" if blocks else "text only")
    words.append("black and white" if colour["black_and_white"] else "colour")
    words.append("portrait" if aspect < 0.95 else "landscape" if aspect > 1.05 else "square")
    descriptor = ", ".join(words)

    text_heavy = bool(body and body["n"] >= 8)
    kind_word = ("public notice" if text_heavy and not blocks else "ad")
    q = [kind_word, "text only" if not blocks else "with logo or photo",
         "black and white" if colour["black_and_white"] else "colour"]
    if page_mm:
        q.append(f"{page_mm[0]:g} x {page_mm[1]:g} mm")
    if border["style"] != "none":
        q.append(f"{border['style']} border")
    suggested = " ".join(q)

    result: dict[str, Any] = {
        "ok": True,
        "image": {"path": str(p), "width_px": W0, "height_px": H0, "aspect_ratio": round(aspect, 4),
                  "orientation": "portrait" if aspect < 0.95 else "landscape" if aspect > 1.05 else "square"},
        "page_mm": page_mm,
        "mm_per_px": round(mm_px, 5) if mm_px else None,
        "scale_note": (None if mm_px else
                       "pass width_mm (real width of this picture / ad) to get mm and leading in pt"),
        "border": border,
        "bands": out_bands,
        "body": ({"lines": body["n"], "pitch_px": round(body["pitch"] * inv, 2) if body["pitch"] else None,
                  "leading_pt": lead_pt(body["pitch"]), "justified": body["justified"],
                  "align": body["align"], "columns": cols} if body else None),
        "text_lines_total": len(lines),
        "black_and_white": colour["black_and_white"],
        "colour_fraction": colour["colour_fraction"],
        "image_blocks": [[round(c * inv) for c in blk] for blk in blocks],
        "layout_descriptor": descriptor,
        "suggested_query": suggested,
        "layout_hint": {
            "descriptor": descriptor, "aspect_ratio": round(aspect, 4),
            "width_mm": page_mm[0] if page_mm else None, "height_mm": page_mm[1] if page_mm else None,
            "black_and_white": colour["black_and_white"], "border": border["style"],
            "body_lines": body["n"] if body else None, "columns": cols,
            "text_only": not blocks,
        },
        "notes": notes + ["pixel values refer to the original image; the analysis is approximate "
                          "(straight crops of clean scans work best)"],
    }
    if overlay_path:
        ov = work.copy()
        dr = ImageDraw.Draw(ov)
        for side, runs in b.items():
            for (s, e) in runs:
                if side in ("top", "bottom"):
                    dr.rectangle([0, s, W, e], outline=(255, 0, 0))
                else:
                    dr.rectangle([s, 0, e, H], outline=(255, 0, 0))
        dr.rectangle(box, outline=(0, 160, 0))
        for bd in bands:
            for (a, c) in bd["lines"]:
                dr.rectangle([bd["left"], a, bd["right"], c], outline=(0, 0, 255))
        for blk in blocks:
            dr.rectangle([blk[0] * k, blk[1] * k, blk[2] * k, blk[3] * k], outline=(255, 128, 0), width=2)
        ov.save(str(overlay_path))
        result["overlay_path"] = str(overlay_path)
    return result


def register(mcp, ctx) -> None:
    register_compare(mcp, ctx)

    @mcp.tool()
    async def analyze_reference_image(
        image_path: str,
        width_mm: float | None = None,
        height_mm: float | None = None,
        overlay_path: str = "",
    ) -> dict:
        """START HERE when the user gives a PHOTO / SCREENSHOT / SCAN of a notice or ad to copy.
        Measures the picture from its pixels (no AI guessing): size and aspect ratio, border
        rectangles and thickness (single / double), text bands (header, title, body, sign-off)
        with line counts and line pitch, justified or not, number of columns, image/logo blocks,
        black-and-white or colour.

        Pass ``width_mm`` (the real printed width of the picture, e.g. the ad is 63 mm wide) to
        also get ``page_mm`` and the leading of every band in points (``leading_pt``: use it as
        ``leading`` in fill_template_fields). Returns ``layout_descriptor`` (plain words),
        ``suggested_query`` and ``layout_hint``: pass ``layout_hint`` unchanged to
        ``find_templates(requirement=..., layout_hint=...)`` to rank templates by aspect ratio and
        layout. ``overlay_path`` saves a debug PNG with the detected borders / lines drawn on it.
        Works best on a straight crop of the ad; the numbers are estimates (+-1-2 lines on dense
        text), check them against the picture.
        """
        try:
            return analyze_image(image_path, width_mm, height_mm, overlay_path or None)
        except (FileNotFoundError, RuntimeError) as exc:
            return {"ok": False, "error": str(exc)}
        except Exception as exc:  # corrupt / unsupported image
            return {"ok": False, "error": f"could not analyze the image: {exc}"}


# --------------------------------------------------------------------------- compare

def _pearson(a: list[float], b: list[float]) -> float:
    n = min(len(a), len(b))
    if n < 3:
        return 0.0
    a, b = a[:n], b[:n]
    ma, mb = sum(a) / n, sum(b) / n
    va = sum((x - ma) ** 2 for x in a)
    vb = sum((x - mb) ** 2 for x in b)
    if va <= 0 or vb <= 0:
        return 0.0
    return sum((x - ma) * (y - mb) for x, y in zip(a, b)) / (va * vb) ** 0.5


def layout_family(ref: dict[str, Any], ren: dict[str, Any]) -> dict[str, Any]:
    """How alike two analyses are as a LAYOUT FAMILY: border style, band structure (header /
    body / sign-off), columns, justified body. Ignores the logo, the aspect ratio / page height and
    the exact line counts, so a template that only differs in logo or height still matches.
    Returns ``{score 0-1, match, reasons}``."""
    reasons: list[str] = []
    score = 0.0
    rs, ns = ref["border"]["style"], ren["border"]["style"]
    if rs == ns:
        score += 0.30
    elif "none" not in (rs, ns):
        score += 0.20  # single vs double border: same family, different frame
        reasons.append(f"border {rs} vs {ns}")
    else:
        reasons.append(f"border {rs} vs {ns}")
    rb, nb = ref.get("body") or {}, ren.get("body") or {}
    if (rb.get("columns") or 1) == (nb.get("columns") or 1):
        score += 0.15
    else:
        reasons.append("number of columns differs")
    if bool(rb.get("justified")) == bool(nb.get("justified")):
        score += 0.15
    else:
        reasons.append("justified vs ragged body")

    def roles(a):
        r = [b["role"] for b in a["bands"]]
        return (r.count("header"), r.count("body"), r.count("signoff"))

    dh = abs(roles(ref)[0] - roles(ren)[0])
    ds = abs(roles(ref)[2] - roles(ren)[2])
    nb_ref, nb_ren = len(ref["bands"]), len(ren["bands"])
    # a logo beside the header merges or splits header bands: allow one band of difference
    if abs(nb_ref - nb_ren) <= 1:
        score += 0.20
    elif abs(nb_ref - nb_ren) == 2:
        score += 0.10
        reasons.append("band count differs by 2")
    else:
        reasons.append(f"band count {nb_ref} vs {nb_ren}")
    if dh <= 1 and ds <= 1 and roles(ref)[1] == roles(ren)[1]:
        score += 0.20
    elif roles(ref)[1] == roles(ren)[1]:
        score += 0.10
    else:
        reasons.append("body band missing on one side")
    score = round(score, 2)
    return {"score": score, "match": score >= 0.65, "reasons": reasons}


def compare_images(ref_path, render_path, width_mm: float | None = None,
                   side_by_side_path: str | Path | None = None) -> dict[str, Any]:
    """Differences between a reference picture and a render: structure numbers + similarity."""
    Image, ImageDraw = _pil()
    ref = analyze_image(ref_path, width_mm)
    ren = analyze_image(render_path, width_mm)

    def num(a, b):
        return None if a is None or b is None else round(b - a, 3)

    rb, nb = ref.get("body") or {}, ren.get("body") or {}
    diffs: dict[str, Any] = {
        "aspect_ratio": {"reference": ref["image"]["aspect_ratio"], "render": ren["image"]["aspect_ratio"],
                         "diff_percent": round(100 * (ren["image"]["aspect_ratio"] / ref["image"]["aspect_ratio"] - 1), 1)},
        "body_lines": {"reference": rb.get("lines"), "render": nb.get("lines"),
                       "diff": num(rb.get("lines"), nb.get("lines"))},
        "text_lines_total": {"reference": ref["text_lines_total"], "render": ren["text_lines_total"],
                             "diff": ren["text_lines_total"] - ref["text_lines_total"]},
        "bands": {"reference": len(ref["bands"]), "render": len(ren["bands"])},
        "border_style": {"reference": ref["border"]["style"], "render": ren["border"]["style"]},
    }

    def rel(img, px):
        return None if px is None else round(100.0 * px / img["image"]["width_px"], 2)

    # pitch and border thickness relative to the picture width, so different pixel sizes compare
    diffs["body_pitch_percent_of_width"] = {
        "reference": rel(ref, rb.get("pitch_px")), "render": rel(ren, nb.get("pitch_px"))}
    diffs["border_thickness_percent_of_width"] = {
        "reference": rel(ref, ref["border"].get("thickness_px")),
        "render": rel(ren, ren["border"].get("thickness_px"))}
    if width_mm:
        diffs["body_leading_pt"] = {"reference": rb.get("leading_pt"), "render": nb.get("leading_pt")}
    fam = layout_family(ref, ren)
    aspect_diff = abs(diffs["aspect_ratio"]["diff_percent"])
    shape_differs = aspect_diff > 5
    hints: list[str] = []
    bl = diffs["body_lines"]
    if bl["diff"] and not shape_differs:
        hints.append(f"body has {abs(bl['diff'])} {'more' if bl['diff'] > 0 else 'fewer'} line(s) than the reference "
                     "(text length differs; fine unless the layout looks wrong)")
    pr = diffs["body_pitch_percent_of_width"]["reference"]
    pn = diffs["body_pitch_percent_of_width"]["render"]
    if pr and pn and abs(pn / pr - 1) > 0.06 and not fam["match"]:
        hints.append(f"line pitch is {100 * (pn / pr - 1):+.0f}% vs the reference (adjust leading)")
    if diffs["border_style"]["reference"] != diffs["border_style"]["render"]:
        hints.append("border style differs (single/double/none)")
    if shape_differs:
        sug = ""
        if width_mm:
            sug = f" To match it: new_from_template(..., height_mm={round(width_mm / ref['image']['aspect_ratio'])})."
        hints.append("page shape differs: expected when only the page height / logo differ; the width of a "
                     "template is fixed, change only the height." + sug)
    # similarity: blurred grayscale at the same size + per-row ink correlation
    from PIL import ImageFilter

    a = Image.open(ref_path).convert("L")
    b = Image.open(render_path).convert("L").resize(a.size)
    s = 160 / max(a.size)
    sz = (max(8, round(a.size[0] * s)), max(8, round(a.size[1] * s)))
    a2 = a.resize(sz).filter(ImageFilter.GaussianBlur(1.5))
    b2 = b.resize(sz).filter(ImageFilter.GaussianBlur(1.5))
    pa, pb = a2.tobytes(), b2.tobytes()
    mad = sum(abs(x - y) for x, y in zip(pa, pb)) / (255.0 * len(pa))
    ra = _Mask(Image, a2.point(lambda v: 255 if v < 140 else 0)).rows((0, 0, sz[0], sz[1]))
    rbp = _Mask(Image, b2.point(lambda v: 255 if v < 140 else 0)).rows((0, 0, sz[0], sz[1]))
    corr = _pearson(ra, rbp)
    similarity = round(max(0.0, 1 - 2.0 * mad) * 0.5 + max(0.0, corr) * 0.5, 3)
    if fam["match"] and (shape_differs or similarity < 0.75 or hints):
        hints.insert(0, "layout family matches: page shape / logo / height differences are expected, do NOT "
                        "rebuild or re-layout; keep the template (remove=[...] for the logo, height_mm for "
                        "the height).")
    elif not fam["match"]:
        hints.insert(0, "the layout family differs (" + "; ".join(fam["reasons"] or ["see numbers"]) +
                     "): consider another template via find_templates.")
    out: dict[str, Any] = {
        "ok": True, "similarity": similarity, "pixel_difference": round(mad, 4),
        "row_ink_correlation": round(corr, 3),
        "layout_family_match": fam["match"], "layout_family_score": fam["score"],
        "differences": diffs, "hints": hints,
        "note": ("Layout family matches: a low similarity only reflects page shape / logo / text length, "
                 "not a wrong template. Keep the template." if fam["match"] else
                 "similarity 1.0 = identical pixels-level layout; the layout family differs, so another "
                 "template may fit better (find_templates).")}
    if side_by_side_path:
        h = 600
        ia = Image.open(ref_path).convert("RGB")
        ib = Image.open(render_path).convert("RGB")
        ia = ia.resize((max(1, round(ia.size[0] * h / ia.size[1])), h))
        ib = ib.resize((max(1, round(ib.size[0] * h / ib.size[1])), h))
        sheet = Image.new("RGB", (ia.size[0] + ib.size[0] + 30, h + 30), "white")
        sheet.paste(ia, (10, 25))
        sheet.paste(ib, (ia.size[0] + 20, 25))
        d = ImageDraw.Draw(sheet)
        d.text((10, 5), "reference", fill=(200, 0, 0))
        d.text((ia.size[0] + 20, 5), "render", fill=(200, 0, 0))
        sheet.save(str(side_by_side_path))
        out["side_by_side_path"] = str(side_by_side_path)
    return out


def register_compare(mcp, ctx) -> None:
    import base64
    import contextlib
    import json
    import os
    import tempfile

    def _err(msg: str) -> list:
        return [TextContent(type="text", text=json.dumps({"ok": False, "error": msg}))]

    @mcp.tool()
    async def compare_to_reference(
        reference_path: str,
        render_path: str = "",
        width_mm: float | None = None,
        dpi: int = 0,
        mode: Mode = "auto",
    ) -> list:
        """Compare the reference photo of a notice / ad with your result. Returns
        ``layout_family_match`` (true = same layout family: border, header / body / sign-off bands,
        justified body; ignores logo, page height and exact line counts), body line count, line
        pitch, border style, page shape, a pixel ``similarity`` and a side-by-side picture.
        A low ``similarity`` with ``layout_family_match`` true only means different logo / page
        height / text length: KEEP the template (use ``remove=`` for the logo and ``height_mm`` on
        new_from_template for the height); never rebuild it. ``render_path`` empty = render the open
        document (page 1). ``width_mm`` = real width of the ad (gives leading in pt and a suggested
        ``height_mm``). Call it at most once.
        """
        side = str(ctx.config.workdir / "compare_side_by_side.png")
        tmp = None
        try:
            rp = render_path
            if not rp:
                from scribus_mcp.tools.verify import render_page_png

                backend = await get_backend(ctx, mode)
                tmp = os.path.join(tempfile.gettempdir(), "scribus_mcp_compare_render.png")
                data, _, err = await render_page_png(ctx, backend, dpi or 150, 1, tmp)
                if data is None:
                    return _err(err or "render failed")
                rp = tmp
            res = compare_images(reference_path, rp, width_mm, side)
        except (FileNotFoundError, RuntimeError) as exc:
            return _err(str(exc))
        except Exception as exc:
            return _err(f"could not compare: {exc}")
        finally:
            if tmp:
                with contextlib.suppress(OSError):
                    os.unlink(tmp)
        blocks: list[TextContent | ImageContent] = [
            TextContent(type="text", text=json.dumps(res, ensure_ascii=False, indent=1))]
        with contextlib.suppress(Exception):
            with open(side, "rb") as fh:
                blocks.append(ImageContent(type="image", data=base64.b64encode(fh.read()).decode("ascii"),
                                           mimeType="image/png"))
        return blocks
