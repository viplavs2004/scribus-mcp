"""Editable-field map of an opened template, and ``fill_template_fields``.

After ``new_from_template`` opens a template the client must know WHAT to change: which text
frames exist, what each is for, what it says now, which are logo / photo slots and how much
text fits. ``describe_open_document`` reads that from the open document (object names, fonts per
run, size, geometry, text) and ``classify_fields`` derives a conservative role for each frame
(headline, offer, contact ...; 'unknown' when unsure). ``fill_template_fields`` then writes new
texts in one call (Hindi through the Kruti converter, English plain), shrinks each text to its
frame (5 pt floor), optionally puts a logo image into the logo slot and returns the
``verify_document`` result.

The classification is pure Python (``classify_fields``) so it is unit-tested offline.
"""

from __future__ import annotations

import base64
import json
import re
from pathlib import Path
from typing import Any

from mcp.types import ImageContent, TextContent

from scribus_mcp.tools._adlib import AD_LIB, build_rich_text, has_devanagari
from scribus_mcp.tools._common import Mode, ServerCtx, clean_user_text, get_backend
from scribus_mcp.tools._markup import has_markup, parse_markup
from scribus_mcp.tools._solve import SOLVER_LIB, solve_params

MIN_PT = 5.0
MAX_INHERITED_RATIO = 1.3

# Script run inside Scribus: every object of every page; text frames with their style runs.
COLLECT_SCRIPT = r'''
import scribus as _s
_u = 25.4 / 72.0 / _s.pointsToDocUnit(1.0)
_pw, _ph = _s.getPageSize()

def _runs_of(_n, _txt):
    _len = _s.getTextLength(_n)
    if _len <= 0 or not _txt:
        return []
    _idx = sorted(set([0, _len // 5, _len // 3, _len // 2, (2 * _len) // 3, (4 * _len) // 5, _len - 1]))
    def _probe(_i):
        _i = max(0, min(_len - 1, _i))
        _j = _i
        while _j < _len - 1 and _j < len(_txt) and _txt[_j].isspace():
            _j += 1
        _s.selectText(_j, 1, _n)
        return (_s.getFont(_n), round(_s.getFontSize(_n), 2), _s.getTextColor(_n))
    _probes = [_probe(_i) for _i in _idx]
    if len(set(_probes)) == 1 or _len > 400 or len(_txt) != _len:
        _s.selectText(0, 0, _n)
        if len(set(_probes)) == 1:
            return [[_txt, _probes[0][0], _probes[0][1], _probes[0][2]]]
        return [[_txt, _probes[0][0], max(p[1] for p in _probes), _probes[0][2]]]
    _runs = []
    for _i in range(_len):
        _s.selectText(_i, 1, _n)
        _k = (_s.getFont(_n), round(_s.getFontSize(_n), 2), _s.getTextColor(_n))
        if _runs and (_runs[-1][1], _runs[-1][2], _runs[-1][3]) == _k:
            _runs[-1][0] += _txt[_i]
        else:
            _runs.append([_txt[_i], _k[0], _k[1], _k[2]])
    _s.selectText(0, 0, _n)
    return _runs

_frames = []
_other = []
for _p in range(1, _s.pageCount() + 1):
    _s.gotoPage(_p)
    for _it in (_s.getPageItems() or []):
        _n, _t = _it[0], _it[1]
        _x, _y = _s.getPosition(_n)
        _w, _h = _s.getSize(_n)
        _g = [round(_x * _u, 1), round(_y * _u, 1), round(_w * _u, 1), round(_h * _u, 1)]
        if _t == 4:
            _txt = _s.getAllText(_n)
            _frames.append({'name': _n, 'page': _p, 'geom': _g, 'text': _txt, 'runs': _runs_of(_n, _txt),
                            'ls': round(_s.getLineSpacing(_n), 2),
                            'lsm': int(_s.getLineSpacingMode(_n)),
                            'first': _s.getFirstLinkedFrame(_n), 'next': _s.getNextLinkedFrame(_n),
                            'align': _s.getTextAlignment(_n) if hasattr(_s, 'getTextAlignment') else None})
        else:
            _other.append({'name': _n, 'type': _t, 'page': _p, 'geom': _g})
_value = {'page_w_mm': round(_pw * _u, 1), 'page_h_mm': round(_ph * _u, 1), 'pages': _s.pageCount(),
          'frames': _frames, 'other': _other}
'''

_PHONE_RUN = re.compile(r"[\dxX][\dxX ()+\-/,.]{6,}")


def _has_phone(s: str) -> bool:
    """A run of at least 8 digits / X placeholders (98XXX XXXXX, 0120-XXXXXXX)."""
    return any(len(re.findall(r"[\dxX]", m)) >= 8 for m in _PHONE_RUN.findall(s))

_CONTACT_EN = re.compile(r"\b(call|phone|contact|helpline|whatsapp|appointment|book now|toll free|enquir|e-?mail|www\.|\.com)", re.I)
_CONTACT_HI = re.compile(r"फोन|संपर्क|सम्पर्क|कॉल|अपॉइंटमेंट|अपाइंटमेंट|हेल्पलाइन|बुकिंग|मोबाइल|ई-मेल")
_OFFER_EN = re.compile(r"(%|\brs\.?\b|₹|\boff\b|\bfree\b|\bemi\b|\bsale\b|\boffer|\bdiscount|\bscholarship|\bflat\b|\bup to\b|\bstarting from\b|\bbonus\b)", re.I)
_OFFER_HI = re.compile(r"%|रु|₹|छूट|निःशुल्क|नि:शुल्क|ऑफर|ऑफ़र|सेल|ईएमआई|लाख|मुफ्त|मुफ़्त|उपहार")
_FINE_EN = re.compile(r"(address|terms|conditions|t&c|\*|plot no|applicable|subject to|valid|images are|for illustration|registration)", re.I)
_FINE_HI = re.compile(r"पता|शर्तें|शर्तें|नियम|\*|लागू|वैध")
_LOGO = re.compile(r"\b(your\s+)?logo\b|\bemblem\b|लोगो|प्रतीक चिह्न", re.I)
_PHOTO = re.compile(r"photo|picture|image here|फोटो|चित्र", re.I)
_NAME_PH = re.compile(r"(your\s+)?(organi[sz]ation|company|business|institution|firm|shop)\s*(name)?|आपकी संस्था|संस्था का नाम|कंपनी का नाम|आपका नाम|फर्म का नाम", re.I)
_BULLET = re.compile(r"^\s*[•●■♦▪◆▶►✓✔\-–\*]\s*\S", re.M)


def _is_kruti(font: str) -> bool:
    return "ruti" in (font or "").lower() or "devlys" in (font or "").lower()


def _unicode_text(runs: list[list]) -> tuple[str, str]:
    """(unicode text, raw text): Kruti runs converted back to Devanagari, Latin runs untouched."""
    try:
        from scribus_mcp.kruti import from_kruti
    except Exception:  # pragma: no cover
        from_kruti = lambda s: s  # noqa: E731
    uni, raw = [], []
    for text, font, *_ in runs:
        raw.append(text)
        uni.append(from_kruti(text) if _is_kruti(font) else text)
    return "".join(uni), "".join(raw)


def para_styles(runs: list[list]) -> list[dict]:
    """Style (font, size, colour) of each paragraph, taken from its longest run."""
    paras: list[list[list]] = [[]]
    for text, font, size, color in runs:
        parts = re.split(r"[\r\n]", text)
        for i, part in enumerate(parts):
            if i > 0:
                paras.append([])
            if part.strip():
                paras[-1].append([part, font, size, color])
    out = []
    for runs_p in paras:
        if not runs_p:
            out.append(None)
            continue
        best = max(runs_p, key=lambda r: len(r[0].strip()))
        out.append({"font": best[1], "size": best[2], "color": best[3]})
    return [p for p in out if p]


def build_field_runs(text: str, runs: list[list]) -> tuple[list[dict] | None, str, float, str | None]:
    """Runs for build_rich_text. If the new text has as many paragraphs as the template text,
    each paragraph keeps its own font / size / colour (burst badges, two-line headlines);
    otherwise one style (the largest size, the longest run's colour). Returns
    (runs or None, latin_font, size, colour)."""
    lat = [r for r in runs if not _is_kruti(r[1])]
    latin_font = max(lat, key=lambda r: len(r[0]))[1] if lat else "Arial Regular"
    size = max([r[2] for r in runs] or [10.0])
    longest = max(runs, key=lambda r: len(r[0])) if runs else None
    color = longest[3] if longest else None
    ps = para_styles(runs)
    new_paras = text.split(chr(10))
    if len(ps) > 1 and len(ps) == len(new_paras) and len({(p["font"], p["size"]) for p in ps}) > 1:
        rr = []
        for i, (ptxt, st) in enumerate(zip(new_paras, ps)):
            font = latin_font if _is_kruti(st["font"]) else st["font"]
            rr.append({"text": ptxt + (chr(10) if i < len(new_paras) - 1 else ""), "font": font,
                       "size_pt": st["size"], "color": st["color"]})
        return rr, latin_font, size, color
    return None, latin_font, size, color


def _char_budget(w_mm: float, h_mm: float, size_pt: float) -> dict:
    wpt, hpt = w_mm * 72 / 25.4, h_mm * 72 / 25.4
    size = max(size_pt, 1.0)
    cpl = max(1, int(wpt / (0.5 * size)))
    lines = max(1, int(hpt / (1.2 * size)))
    return {"chars_per_line": cpl, "lines": lines, "approx_total": int(cpl * lines * 0.9)}


def classify_fields(scan: dict) -> dict:
    """Derive roles from the collected scan (see COLLECT_SCRIPT). Conservative: 'unknown' when
    unsure. Returns ``{fields, decorative, page_mm}``; fields are in reading order."""
    pw, ph = scan["page_w_mm"], scan["page_h_mm"]
    items: list[dict] = []
    for fr in scan["frames"]:
        runs = fr.get("runs") or []
        uni, raw = _unicode_text(runs) if runs else (fr.get("text", ""), fr.get("text", ""))
        text = uni.strip()
        sizes = [r[2] for r in runs] or [10.0]
        longest = max(runs, key=lambda r: len(r[0])) if runs else None
        main = longest[2] if longest else 10.0
        kr = any(_is_kruti(r[1]) for r in runs)
        lat = any(not _is_kruti(r[1]) and re.search(r"[A-Za-z]{2}", r[0]) for r in runs)
        lang = "hindi" if kr and not lat else ("mixed" if kr and lat else "english")
        if not kr and has_devanagari(text):
            lang = "hindi"
        x, y, w, h = fr["geom"]
        items.append({"fr": fr, "text": text, "raw": raw, "runs": runs, "main": main,
                      "max": max(sizes), "lang": lang, "x": x, "y": y, "w": w, "h": h,
                      "cy": (y + h / 2) / ph if ph else 0.5, "role": None, "conf": "high"})
    # pass 1: explicit placeholders and content-based roles
    for it in items:
        t, flat = it["text"].replace(chr(13), chr(10)), re.sub(r"\s+", " ", it["text"])
        short = len(flat) <= 24
        if not flat:
            it["role"], it["conf"] = "empty_frame", "high"
        elif _LOGO.search(flat) and short:
            it["role"] = "logo_slot"
        elif _PHOTO.search(flat) and len(flat) <= 70:
            it["role"] = "photo_slot"
        elif it["max"] <= 8.5 and (it["cy"] > 0.72 or len(flat) > 70) and (
                _FINE_EN.search(flat) or _FINE_HI.search(flat) or it["max"] <= 7.5):
            it["role"] = "fine_print"
        elif _NAME_PH.search(flat) and len(flat) <= 50:
            it["role"] = "business_name"
        elif _has_phone(it["raw"]) or _has_phone(flat) or _CONTACT_HI.search(flat) or (
                _CONTACT_EN.search(flat) and len(flat) <= 90):
            it["role"] = "contact"
        elif len(_BULLET.findall(t)) >= 2 or (t.count("\n") >= 2 and all(len(l) < 70 for l in t.splitlines())
                                              and it["h"] > 14 and it["max"] <= 14):
            it["role"] = "bullet_list"
        elif (_OFFER_EN.search(flat) or _OFFER_HI.search(flat)) and len(flat) <= 60:
            it["role"] = "offer"
        elif (max(it["w"], it["h"]) <= 50 and 0.6 <= it["h"] / max(it["w"], 0.1) <= 1.7
              and len(it["text"].splitlines()) >= 2):
            it["role"], it["conf"] = "badge", "medium"
    # pass 1b: stacked short frames with the same x / width / size = one bullet list
    for it in items:
        if it["role"] in (None, "offer", "subheadline"):
            pass
    cand = [it for it in items if it["role"] in (None, "offer") and it["h"] <= 16
            and 3 <= len(it["text"]) <= 70]
    groups: dict[tuple, list] = {}
    for it in cand:
        groups.setdefault((it["fr"]["page"], round(it["x"]), round(it["w"]), round(it["max"], 1)), []).append(it)
    gno = 0
    for g in groups.values():
        g.sort(key=lambda i: i["y"])
        if len(g) >= 3 and all(g[i + 1]["y"] - g[i]["y"] <= 2.2 * g[i]["h"] for i in range(len(g) - 1)):
            gno += 1
            for it in g:
                it["role"], it["conf"], it["group"] = "list_item", "high", f"list_{gno}"
    # pass 2: size ranking among the rest -> headline / subheadline / body
    rest = [it for it in items if it["role"] is None]
    if rest:
        by_size = sorted(rest, key=lambda i: (-i["max"], i["y"]))
        head = by_size[0]
        others = sorted(it["max"] for it in by_size[1:]) or [0.0]
        median = others[len(others) // 2]
        if head["max"] >= max(14.0, 1.25 * median) or len(rest) == 1 and head["max"] >= 14:
            head["role"] = "headline"
            head["conf"] = "high" if head["max"] >= 1.6 * median else "medium"
        for it in by_size:
            if it["role"]:
                continue
            flat = re.sub(r"\s+", " ", it["text"])
            if it["cy"] < 0.2 and 3 <= len(flat) <= 45 and it["max"] >= 9:
                it["role"] = "business_name"
                it["conf"] = "medium" if any(o["role"] == "logo_slot" and o["cy"] < 0.25
                                             for o in items) else "low"
            elif len(flat) > 110 or it["h"] > 25 and len(flat) > 60:
                it["role"], it["conf"] = "body_text", "medium"
            elif it["max"] >= max(median, 9.0) and 3 <= len(flat) <= 90:
                it["role"], it["conf"] = "subheadline", "medium"
            else:
                it["role"], it["conf"] = "unknown", "low"
    fields = []
    for it in sorted(items, key=lambda i: (i["fr"]["page"], round(i["y"] / 4), i["x"])):
        fr = it["fr"]
        main = it["main"] if it["role"] not in ("headline",) else it["max"]
        d = {
            "name": fr["name"], "role": it["role"] or "unknown", "confidence": it["conf"],
            "language": it["lang"], "text": re.sub(r"[ \t]+", " ", it["text"])[:140],
            "font": (it["runs"][0][1] if it["runs"] else None),
            "size_pt": round(main, 1), "frame_mm": [it["w"], it["h"]], "pos_mm": [it["x"], it["y"]],
            "page": fr["page"], "char_budget": _char_budget(it["w"], it["h"], main),
        }
        npar = len(para_styles(it["runs"])) if it["runs"] else 1
        if npar > 1:
            d["paragraphs"] = npar
        if it.get("group"):
            d["group"] = it["group"]
        if it["role"] == "logo_slot":
            d["how"] = "pass logo_path to fill_template_fields (an image file); else leave or type the brand name"
        elif it["role"] == "photo_slot":
            d["how"] = "replace with a photo (image frame) if the user supplies one, else delete the placeholder text"
        elif it["role"] == "empty_frame":
            d["how"] = "empty text frame; leave alone"
        if it["max"] - min(r[2] for r in (it["runs"] or [[0, 0, it["max"], 0]])) > 0.5:
            d["mixed_sizes"] = True
        fields.append(d)
    # linked frames (a body that continues in a second frame): the head is filled, the rest
    # only receives the overflow
    nxt = {fr["name"]: fr.get("next") for fr in scan["frames"]}
    first = {fr["name"]: fr.get("first") or fr["name"] for fr in scan["frames"]}
    for d in fields:
        if first.get(d["name"], d["name"]) != d["name"]:
            d["role"], d["confidence"] = "continuation", "high"
            d["linked_from"] = first[d["name"]]
            d["how"] = f"linked to {first[d['name']]}: the text flows in from there; fill {first[d['name']]}"
        elif nxt.get(d["name"]):
            chain, cur = [d["name"]], nxt.get(d["name"])
            while cur and cur not in chain:
                chain.append(cur)
                cur = nxt.get(cur)
            d["linked_frames"] = chain
    decor = [o["name"] for o in scan.get("other", [])]
    return {
        "fields": fields,
        "decorative": {"count": len(decor), "names": decor[:80],
                       "note": "shapes / images forming the design (panels, bursts, borders): "
                               "leave them alone, do not delete or move them"},
        "page_mm": [pw, ph],
    }


INSTRUCTIONS_FOR_CLIENT = (
    "TRUST this template: do not pixel-analyse or rebuild it. Differences in logo, divider lines or page "
    "height are fine; the width is fixed. Fill it now: (1) ask the user only for missing facts (names, "
    "dates, phone numbers, address, logo file); never invent them. (2) ONE call "
    "fill_template_fields(fields={name or role: text}, remove=['decor_logo'] if there is no logo, "
    "expand_header=true) using the field names above; write Hindi as normal Unicode Devanagari (converted "
    "to Kruti Dev 010 automatically), English as plain text. Body, sign-off size and last lines are fitted "
    "automatically (never below 5 pt; shorter text is better than tiny). For a different page height call "
    "new_from_template again with height_mm=<mm> (width cannot change). logo_slot / photo_slot are image "
    "slots; other decorative objects stay. Roles with confidence 'low' / 'unknown' are guesses. (3) The "
    "fill returns verify and a preview: fix every error, LOOK at it, then export_press_pdf."
)


async def describe_open_document(backend) -> dict:
    """Collect and classify the editable fields of the document open in ``backend``."""
    res = await backend.script(COLLECT_SCRIPT, result_expr="_value")
    if not res.ok:
        return {"editable_fields": [], "fields_error": res.error}
    c = classify_fields(res.value or {"page_w_mm": 0, "page_h_mm": 0, "frames": []})
    return {"editable_fields": c["fields"], "decorative": c["decorative"],
            "instructions": INSTRUCTIONS_FOR_CLIENT}


def _resolve_keys(requested: dict[str, str], fields: list[dict]) -> tuple[dict[str, str], list[str]]:
    """Map keys (object name, role, or 'role_2') to object names. Returns (name->text, errors)."""
    by_name = {f["name"]: f for f in fields}
    out: dict[str, str] = {}
    errors: list[str] = []
    used: set[str] = set()
    for key, text in requested.items():
        if key in by_name:
            out[key] = text
            used.add(key)
            continue
        m = re.fullmatch(r"([a-z_]+?)(?:_(\d+))?", key.strip().lower())
        role, nth = (m.group(1), int(m.group(2) or 1)) if m else (key, 1)
        cands = [f["name"] for f in fields if f["role"] == role]
        if len(cands) >= nth and role not in ("logo_slot", "photo_slot"):
            out[cands[nth - 1]] = text
            used.add(cands[nth - 1])
        else:
            errors.append(f"no field {key!r}; use an object name or a role "
                          f"({', '.join(sorted({f['role'] for f in fields}))}), optionally role_2")
    return out, errors


def find_signoff_pair(frames: list[dict], body: str, tol_mm: float = 3.0) -> dict[str, str | None]:
    """The newspaper sign-off layout around a body frame, from geometry only: ``last`` is the
    short text frame under the body's left edge (the 'last line' frame, linked or not), ``signoff``
    the frame to its right (or, without a last-line frame, the frame under the body's right part).
    ``frames`` are scan frames (``name``, ``page``, ``geom`` = [x, y, w, h] mm)."""
    by = {f["name"]: f for f in frames}
    b = by.get(body)
    if not b:
        return {"last": None, "signoff": None}
    bx, by0, bw, bh = b["geom"]
    bottom = by0 + bh
    last = sig = None
    near = [f for f in frames if f["name"] != body and f["page"] == b["page"]
            and abs(f["geom"][1] - bottom) <= tol_mm]
    for f in sorted(near, key=lambda f: f["geom"][0]):
        x, _, w, _ = f["geom"]
        if last is None and abs(x - bx) <= 2.0 and w <= bw - 10.0:
            last = f
        elif sig is None and x > bx + 10.0 and (last is None or x >= last["geom"][0] + last["geom"][2] - 2.0):
            sig = f
    named = [f for f in frames if re.search(r"sign|sig$", f["name"], re.I) and f["name"] != body]
    if sig is None and named:
        sig = named[0]
    return {"last": last["name"] if last else None, "signoff": sig["name"] if sig else None}


def plan_expand(removed: dict, frames: list[dict], max_gap_mm: float = 10.0) -> list[dict]:
    """Text frames that sat to the right of a removed image frame and overlap it vertically are
    stretched leftwards to the image's left edge. ``removed`` / ``frames`` have ``geom``
    [x, y, w, h] mm and ``page``. Returns ``[{name, page, x_mm, w_mm}]``."""
    rx, ry, rw, rh = removed["geom"]
    out = []
    for f in frames:
        if f["page"] != removed["page"]:
            continue
        x, y, w, h = f["geom"]
        overlap = min(y + h, ry + rh) - max(y, ry)
        if (overlap >= 0.3 * min(h, rh) and x >= rx + rw - 1.0 and x - (rx + rw) <= max_gap_mm
                and x > rx):
            out.append({"name": f["name"], "page": f["page"], "x_mm": round(rx, 2),
                        "w_mm": round(x + w - rx, 2)})
    return out


def resolve_removals(remove: Any, scan: dict) -> tuple[list[dict], list[str]]:
    """Names to delete: object names, or the word 'decorative' = every image frame that is not a
    text frame. Returns ``([{name, page, geom, type}], errors)``."""
    if not remove:
        return [], []
    toks = [remove] if isinstance(remove, str) else list(remove)
    objs = {f["name"]: {"name": f["name"], "page": f["page"], "geom": f["geom"], "type": 4}
            for f in scan.get("frames", [])}
    objs.update({o["name"]: {"name": o["name"], "page": o["page"], "geom": o["geom"], "type": o["type"]}
                 for o in scan.get("other", [])})
    out: list[dict] = []
    errs: list[str] = []
    for t in toks:
        t = str(t)
        if t.strip().lower() == "decorative":
            out += [o for o in objs.values() if o["type"] == 2 and o not in out]
        elif t in objs:
            if objs[t] not in out:
                out.append(objs[t])
        else:
            errs.append(f"remove: no object {t!r} (decorative objects: "
                        f"{', '.join(o['name'] for o in objs.values() if o['type'] != 4) or 'none'})")
    return out, errs


_ALIGN = {"left": 0, "center": 1, "centre": 1, "right": 2, "justify": 3, "justified": 3}
_FIELD_KEYS = {"text", "size", "leading", "leading_ratio", "target_lines", "align", "fit",
               "max_size", "last_line_beside", "beside_gap_mm", "auto_block"}
BODY_GROW2 = 1.5  # second stage for short texts (big blank / empty continuation frame)
BODY_GROW = 1.25  # a body may grow to this many times the template size when it is short


def _fill_script(specs: list[dict], logo: dict | None, removals: list[dict] | None = None,
                 expands: list[dict] | None = None) -> str:
    return AD_LIB + SOLVER_LIB + f"""
import scribus as _s
_specs = {specs!r}
_logo = {logo!r}
_removals = {removals or []!r}
_expands = {expands or []!r}
_mm = 72.0 / 25.4 * _s.pointsToDocUnit(1.0)
_res = []
_body_size = {{}}
for _rm in _removals:
    try:
        _s.gotoPage(_rm['page'])
        _s.deleteObject(_rm['name'])
        _AD_REMOVED.append(_rm['name'])
    except Exception as _e:
        _AD_WARN.append('could not remove %s: %s' % (_rm['name'], _e))
for _ex in _expands:
    try:
        _s.gotoPage(_ex['page'])
        _x, _y = _s.getPosition(_ex['name'])
        _w, _h = _s.getSize(_ex['name'])
        _s.moveObjectAbs(_ex['x_mm'] * _mm, _y, _ex['name'])
        _s.sizeObject(_ex['w_mm'] * _mm, _h, _ex['name'])
    except Exception as _e:
        _AD_WARN.append('could not widen %s: %s' % (_ex['name'], _e))
for _sp in _specs:
    _f = _sp['name']
    try:
        _s.gotoPage(_sp['page'])
        _chain = _sv_chain(_f)
        if _sp.get('beside'):
            _chain = _sv_make_beside(_f, _sp['beside'], _sp.get('gap_mm', 2.0))
        # delete + insert (not setText): keeps the frame's paragraph alignment and default style
        _n0 = _s.getTextLength(_f)
        if _n0 > 0:
            _s.selectText(0, _n0, _f)
            _s.deleteText(_f)
        _s.insertText(_sp['text'], 0, _f)
        if _sp.get('align') is not None:
            for _c in _chain:
                _s.setTextAlignment(_sp['align'], _c)
        _P = _sp['solve']
        _P['chain'] = _chain
        _auto = _sp.get('auto_size')
        _note = None
        if _auto and _body_size.get(_auto['from']):
            # sign-off follows the body size: ratio x body, never below 5 pt, never above 1.3 x body
            _bs = _body_size[_auto['from']]
            _tg = max(5.0, min(1.3 * _bs, _auto['ratio'] * _bs))
            _mx = max([_q['size'] for _q in _P['spans']] or [_tg])
            if _mx > 0:
                _fct = _tg / _mx
                for _q in _P['spans']:
                    _q['size'] = max(5.0, round(_q['size'] * _fct * 4) / 4.0)
                _sp['size'] = max(5.0, round(_mx * _fct * 4) / 4.0)
                # one line per paragraph if that is possible at >= 5 pt (no wrapped sign-off line)
                _P['target_lines'] = 1 + len([_ch for _ch in _sp['text'].rstrip(chr(13) + chr(10)) if _ch in (chr(13), chr(10))])
                _P['spread'] = False
                _note = 'sign-off sized to the body: %s pt (body %s pt)' % (_sp['size'], _bs)
        _r = _sv_solve(_P)
        if _P.get('block') and _P.get('grow2') and not _r['overflow']:
            # stage 2: a short text may grow further (up to grow2) when the first fit leaves a big
            # blank or an empty continuation frame; kept only if it helps and still fits
            _bl0 = (_r.get('blank_pt') or 0.0) - (_sv_inner_h(_chain[-1]) if _r.get('tail_empty') else 0.0)
            if _r.get('tail_empty') or _bl0 > 2.5 * (_r.get('leading_pt') or 12.0):
                _old_cap = _P['max_pt']
                _P['max_pt'] = _P['grow2']
                _r2 = _sv_solve(_P)
                _bl2 = (_r2.get('blank_pt') or 0.0) - (_sv_inner_h(_chain[-1]) if _r2.get('tail_empty') else 0.0)
                if (not _r2['overflow']) and ((_r.get('tail_empty') and not _r2.get('tail_empty')) or _bl2 < _bl0 - 1.0):
                    _r = _r2
                else:
                    _P['max_pt'] = _old_cap
                    _r = _sv_solve(_P)
        _r['name'] = _f
        _r['size_from'] = _sp['size']
        _r['chain'] = _chain
        if _note:
            _r.setdefault('notes', []).append(_note)
        if _sp.get('is_body') and not _r['overflow']:
            _body_size[_f] = _r['size_pt']
        if _r.get('tail_empty') and len(_chain) > 1:
            _t = _chain[-1]
            try:
                if _r.get('blank_pt') is not None:
                    _r['blank_pt'] -= _sv_inner_h(_t)
                _s.deleteObject(_t)
                _AD_REMOVED.append(_t)
                _AD_WARN.append('%s: the text fits in %s alone, the empty continuation frame %s was deleted'
                                % (_f, _chain[0], _t))
                _chain = _chain[:-1]
                _r['chain'] = _chain
            except Exception as _e:
                _AD_WARN.append('%s: continuation frame %s is empty and could not be deleted: %s' % (_f, _t, _e))
        if _sp.get('is_body') and _r.get('blank_pt') is not None and _r.get('leading_pt'):
            _bl = _r['blank_pt']
            if _bl > 3 * _r['leading_pt']:
                _AD_WARN.append('%s: the text is short for its frame, about %.0f mm stays blank at the bottom '
                                '(use new_from_template height_mm / extra_height_mm to shorten the page)'
                                % (_f, _bl / (72.0 / 25.4)))
        _res.append(_r)
    except Exception as _e:
        _res.append({{'name': _f, 'error': str(_e)}})
_logo_res = None
if _logo:
    try:
        _x, _y = _s.getPosition(_logo['name'])
        _w, _h = _s.getSize(_logo['name'])
        _s.deleteObject(_logo['name'])
        _im = _s.createImage(_x, _y, _w, _h)
        _s.loadImage(_logo['path'], _im)
        _s.setScaleImageToFrame(1, 1, _im)
        _s.setFillColor('None', _im)
        _s.setLineColor('None', _im)
        _logo_res = {{'image_frame': _im, 'replaced': _logo['name']}}
    except Exception as _e:
        _logo_res = {{'error': str(_e)}}
_value = {{'fields': _res, 'logo': _logo_res, 'warnings': _AD_WARN, 'removed': _AD_REMOVED}}
"""


def _template_ratio(frame: dict, size: float, min_ratio: float) -> float | None:
    """Leading / size of the template frame when its leading is fixed; None = automatic. A ratio
    above 1.3 is almost always Scribus' default 15 pt leading left on a small font, not a design
    choice, so it is capped there."""
    ls, lsm = frame.get("ls"), frame.get("lsm")
    if lsm == 0 and ls and size:
        return max(min_ratio, min(MAX_INHERITED_RATIO, float(ls) / float(size)))
    return None


def build_field_spec(name: str, page: int, raw: Any, frame: dict, runs: list[list], *,
                     min_pt: float, min_ratio: float = 1.05,
                     beside: str | None = None, body_like: bool = False) -> tuple[dict, list[str]]:
    """The script spec for one field: final text, style spans and the solver parameters.

    ``raw`` is the user's value: a string (with optional inline run markup) or a dict with the
    options listed in ``_FIELD_KEYS``. Returns ``(spec, warnings)``; raises ValueError for bad
    options.
    """
    opts: dict[str, Any] = {"text": raw} if isinstance(raw, str) else dict(raw)
    unknown = set(opts) - _FIELD_KEYS
    if unknown:
        raise ValueError(f"unknown field option(s) {sorted(unknown)}; allowed: {sorted(_FIELD_KEYS)}")
    text = clean_user_text(str(opts.get("text", "")))
    warns: list[str] = []
    mruns, w = parse_markup(text)
    warns += w
    plain = "".join(r["text"] for r in mruns)
    para_runs, latin_font, size, color = build_field_runs(plain, runs)
    if opts.get("size"):
        size = float(opts["size"])
        para_runs = None
    if has_markup(text):
        rr = [dict(r) for r in mruns]
        for r in rr:
            r.setdefault("size_pt", size)
        full, spans, _ = build_rich_text(None, rr, font=latin_font, size_pt=size, color=color,
                                         hindi="auto")
    else:
        full, spans, _ = build_rich_text(plain, para_runs, font=latin_font, size_pt=size,
                                         color=color, hindi="auto")
    spans = [{k: v for k, v in sp.items() if v is not None} for sp in spans]
    align = opts.get("align")
    if align is not None:
        if str(align).lower() not in _ALIGN:
            raise ValueError(f"align must be one of left|center|right|justify, not {align!r}")
        align = _ALIGN[str(align).lower()]
    target = opts.get("target_lines")
    fit = opts.get("fit") or ("fill" if target else "shrink")
    # body block: a body-like field with no explicit sizing is fitted as a block (largest size up
    # to BODY_GROW x the template size that fits, leading spread so the chain is filled, last
    # lines in the continuation frame). Any of size/leading/target_lines/fit other than fill opts out.
    explicit = any(opts.get(k) is not None for k in ("size", "leading", "leading_ratio", "target_lines"))
    block = bool(body_like and opts.get("auto_block", True) and not explicit
                 and opts.get("fit") in (None, "fill"))
    max_size = opts.get("max_size")
    grow2 = None
    if block:
        fit = "fill"
        if not max_size:
            max_size = round(size * BODY_GROW * 4) / 4.0
            grow2 = round(size * BODY_GROW2 * 4) / 4.0
    ratio = opts.get("leading_ratio")
    if opts.get("leading") is None and ratio is None and fit != "none":
        ratio = _template_ratio(frame, size, min_ratio)
    if opts.get("leading") is not None and float(opts["leading"]) < min_ratio * min_pt:
        warns.append(f"leading raised to {min_ratio * min_pt:.2f} pt (minimum {min_ratio} x font size)")
    solve = solve_params(
        [name], spans, fit=fit, min_pt=min_pt, max_pt=max_size,
        leading_pt=opts.get("leading"), leading_ratio=ratio,
        target_lines=target, min_ratio=min_ratio, block=block)
    if grow2:
        solve["grow2"] = grow2
    spec: dict[str, Any] = {"name": name, "page": page, "text": full, "size": size, "solve": solve,
                            "align": align}
    if beside:
        spec["beside"] = beside
        spec["gap_mm"] = float(opts.get("beside_gap_mm", 2.0))
    return spec, warns


def register(mcp, ctx: ServerCtx) -> None:
    @mcp.tool()
    async def fill_template_fields(
        fields: dict[str, str | dict[str, Any]],
        logo_path: str = "",
        min_font_pt: float = 5.0,
        remove: list[str] | str | None = None,
        expand_header: bool = False,
        signoff_ratio: float = 1.0,
        run_verify: bool = True,
        preview: bool = True,
        preview_dpi: int = 0,
        mode: Mode = "auto",
    ) -> list:
        """Fill an opened template in ONE call: text, fit, verify and a preview picture
        (use after ``new_from_template``, which lists the editable fields and char budgets).

        ``fields`` maps an object name from ``editable_fields`` (or a role: 'headline',
        'contact', 'offer', 'business_name', 'fine_print', 'body_text'; 'contact_2' = second
        contact frame) to either the new TEXT or an options dict
        ``{"text": ..., "size": pt, "leading": pt, "leading_ratio": 1.2, "target_lines": N,
        "align": "justify", "fit": "shrink|fill|none|leading", "max_size": pt,
        "last_line_beside": "<signature frame>", "beside_gap_mm": 2}``.

        TEXT is normal Unicode Hindi (converted to Kruti Dev 010 where the font needs it; write
        the letter ऑ as आ+ॉ) or English, and may contain inline run markup so one line can mix
        fonts: ``{font=Arial Bold,size=9}-:{/} {font=Kruti Dev 010 Regular}सार्वजनिक सूचना{/}
        {bold}:-{/}``. Tag options: ``font=``, ``size=``, ``color=``, ``bold``, ``italic``,
        ``scale=`` (h-scale %); ``{/}`` closes the innermost run; ``{{`` and ``}}`` are literal
        braces. Fitting is a calculation against Scribus' own layout (never below
        ``min_font_pt`` = 5 pt, leading never below 1.05 x size): ``fit='shrink'`` (default)
        lowers all sizes until it fits; ``'fill'`` finds the largest size that fits;
        ``target_lines=N`` finds the largest size that lays out in N lines and spreads the
        leading over the frame height; ``leading`` fixes the leading in pt (font follows);
        ``fit='leading'`` keeps the size and solves the leading. The template's paragraph
        alignment is kept (``align`` overrides it). ``last_line_beside="<frame>"`` is the
        newspaper sign-off layout: the body frame is cut above that (signature) frame and a
        linked frame takes the rows to its left, so the last body lines sit beside the
        signature with no overlapping frames.

        BODY BLOCK (default for the main body, no options needed): the body is fitted as a block:
        the largest size that fits (at most 1.25 x the template size), the leading spread to fill
        the frame, the last lines in the continuation frame beside the sign-off (a template's
        manual last-line frame is linked automatically); an empty continuation frame is deleted
        (listed in ``removed_frames``). Any of ``size``, ``leading``, ``target_lines``,
        ``fit='shrink'|'leading'|'none'`` or ``"auto_block": false`` switches this off.
        SIGN-OFF follows the body: its size becomes ``signoff_ratio`` x the body size (default 1.0;
        never below 5 pt, never above 1.3 x body) unless that field has an explicit ``size``;
        ``signoff_ratio=0`` leaves the template size.

        ``remove`` deletes frames: a list of object names (``["decor_logo"]``) or ``"decorative"``
        (every image frame). ``expand_header=true`` then stretches the text frames that sat beside a
        removed image leftwards over the freed space. Removed frames are listed in
        ``removed_frames``; a missing logo file is only tolerated when its frame is removed.

        ``logo_path`` (png/jpg/tif/svg) replaces the first logo placeholder. Returns a JSON text
        block (fields applied with size / leading / lines, warnings, unfilled fields, the
        ``verify_document`` result) and, when ``preview`` is true, a PNG of the page at
        ``preview_dpi`` (0 = automatic, about 1100 px on the long side): look at it, fix problems, then export_press_pdf.
        """
        backend = await get_backend(ctx, mode)
        scan_res = await backend.script(COLLECT_SCRIPT, result_expr="_value")
        if not scan_res.ok:
            return [TextContent(type="text", text=json.dumps({"ok": False, "error": scan_res.error}))]
        scan = scan_res.value or {}
        cls = classify_fields(scan)
        flds = cls["fields"]
        min_pt = max(MIN_PT, float(min_font_pt))
        targets, errors = _resolve_keys(dict(fields), flds)
        removals, rerr = resolve_removals(remove, scan)
        errors += rerr
        gone = {r["name"] for r in removals}
        for nm in [n for n in targets if n in gone]:
            errors.append(f"{nm}: field targets a removed frame; not filled")
            del targets[nm]
        expands: list[dict] = []
        if expand_header:
            others = [f for f in scan.get("frames", []) if f["name"] not in gone]
            for r in removals:
                if r["type"] == 2:
                    expands += plan_expand(r, others)
        frames_by_name = {f["name"]: f for f in scan.get("frames", [])}
        role_by_name = {f["name"]: f["role"] for f in flds}
        pages = {f["name"]: f["page"] for f in flds}
        specs = []
        notes: list[str] = []
        body_name: str | None = None
        sig_name: str | None = None
        pair: dict = {}
        for name, raw in targets.items():
            try:
                fr = frames_by_name.get(name) or {}
                head = fr.get("first") or name
                if head != name:
                    notes.append(f"{name} is linked to {head}: text goes to {head} and flows on")
                    if head in targets:
                        continue
                    name, fr = head, frames_by_name.get(head) or fr
                beside = None
                body_like = (role_by_name.get(name) == "body_text" or name == "body"
                             or bool(fr.get("next"))) and not re.search(r"sign|sig$", name, re.I)
                if body_like and body_name is None:
                    body_name = name
                    pair = find_signoff_pair(scan.get("frames", []), name)
                    sig_name = pair["signoff"]
                if (body_like and not (isinstance(raw, dict) and raw.get("last_line_beside"))
                        and not fr.get("next") and pair.get("last") and pair.get("signoff")
                        and (not isinstance(raw, dict) or raw.get("auto_block", True))):
                    beside = pair["signoff"]
                    notes.append(f"{name}: last lines placed beside {beside} "
                                 f"(template last-line frame {pair['last']} replaced by a linked frame)")
                if isinstance(raw, dict) and raw.get("last_line_beside") and fr.get("next"):
                    notes.append(f"{name} already continues in {fr['next']}: last_line_beside ignored")
                elif isinstance(raw, dict) and raw.get("last_line_beside"):
                    bt, be = _resolve_keys({str(raw["last_line_beside"]): ""}, flds)
                    errors += be
                    if not bt:
                        continue
                    beside = next(iter(bt))
                spec, warns = build_field_spec(name, pages.get(name, 1), raw, fr,
                                               fr.get("runs") or [], min_pt=min_pt, beside=beside,
                                               body_like=body_like)
                spec["is_body"] = body_like
                specs.append(spec)
                notes += [f"{name}: {w}" for w in warns]
            except ValueError as exc:
                errors.append(f"{name}: {exc}")
        if signoff_ratio and body_name:
            for sp in specs:
                nm = sp["name"]
                is_sig = nm == sig_name or (not sig_name and re.search(r"sign|sig$", nm, re.I))
                raw_sp = targets.get(nm)
                if is_sig and not (isinstance(raw_sp, dict) and raw_sp.get("size")):
                    sp["auto_size"] = {"ratio": float(signoff_ratio), "from": body_name}
        specs.sort(key=lambda sp: 1 if sp.get("auto_size") else 0)
        logo = None
        if logo_path:
            p = Path(logo_path)
            slot = next((f for f in flds if f["role"] == "logo_slot"), None)
            if not p.is_file():
                errors.append(f"logo_path not found: {logo_path}")
            elif slot is None:
                notes.append("no logo slot found in this template; logo not placed")
            else:
                logo = {"name": slot["name"], "path": str(p.resolve())}
        if not specs and not logo and not removals:
            return [TextContent(type="text", text=json.dumps(
                {"ok": False, "error": "; ".join(errors) or "nothing to fill", "errors": errors},
                ensure_ascii=False))]
        res = await backend.script(_fill_script(specs, logo, removals, expands), result_expr="_value")
        if not res.ok:
            return [TextContent(type="text", text=json.dumps({"ok": False, "error": res.error}))]
        val = res.value or {}
        report = []
        for r in val.get("fields", []):
            if r.get("error"):
                report.append({"name": r["name"], "status": "error: " + r["error"]})
                continue
            if r["overflow"]:
                status = f"OVERFLOW at {r['size_pt']} pt: shorten the text or enlarge the frame"
            elif r.get("target_lines") and not r.get("target_met"):
                status = (f"fitted at {r['size_pt']} pt but NOT {r['target_lines']} lines: "
                          f"{r['lines']} lines (text too long or short for that target)")
            elif r["size_pt"] < r["size_from"] - 0.01:
                status = f"shrunk to {r['size_pt']} pt (from {r['size_from']})"
            else:
                status = "fitted"
            entry = {"name": r["name"], "status": status, "size_pt": r["size_pt"],
                     "leading_pt": r.get("leading_pt"), "lines": r["lines"], "tries": r["tries"]}
            if len(r.get("chain", [])) > 1:
                entry["frames"] = r["chain"]
            if r.get("notes"):
                entry["notes"] = r["notes"]
            report.append(entry)
        gone_now = set(val.get("removed") or [])
        unfilled = [{"name": f["name"], "role": f["role"], "text": f["text"][:60]} for f in flds
                    if f["name"] not in targets and f["name"] not in gone_now and f["role"] not in
                    ("empty_frame", "continuation", "logo_slot" if logo else "", "unknown")]
        out: dict[str, Any] = {"ok": not any(r.get("status", "").startswith("error") for r in report),
                               "filled": report, "logo": val.get("logo"),
                               "unfilled_fields": unfilled,
                               "removed_frames": val.get("removed") or [],
                               "widened_frames": [e["name"] for e in expands],
                               "warnings": (val.get("warnings") or []) + notes,
                               "errors": errors, "error": None}
        if run_verify:
            from scribus_mcp.tools.verify import build_verify_script, summarize
            vres = await backend.script(build_verify_script({
                "min_pt": MIN_PT, "bleed_tolerance_mm": 3.0, "min_image_ppi": 100,
                "expected_fonts": {}, "kruti_hints": True, "max_chars": 4000}), result_expr="_value")
            if vres.ok:
                findings = (vres.value or {}).get("findings", [])
                out["verify"] = {"passed": summarize(findings)["errors"] == 0,
                                 "summary": summarize(findings), "findings": findings[:25]}
            else:
                out["verify"] = {"error": vres.error}
        blocks: list[TextContent | ImageContent] = []
        if preview:
            from scribus_mcp.tools.verify import render_page_png
            page = specs[0]["page"] if specs else 1
            dpi = int(preview_dpi) or max(50, min(250, round(1100 / max(scan.get("page_w_mm", 100),
                                                                       scan.get("page_h_mm", 100)) * 25.4)))
            data, size, err = await render_page_png(ctx, backend, dpi, page)
            if data is not None:
                out["preview"] = f"page {page} at {dpi} dpi, {size[0]}x{size[1]} px (image below)"
                blocks.append(ImageContent(type="image", data=base64.b64encode(data).decode("ascii"),
                                           mimeType="image/png"))
            else:
                out["preview"] = err
        out["next_step"] = ("Look at the preview. Fix any OVERFLOW / verify errors (shorten text, "
                            "change size / leading / target_lines), refill, then export_press_pdf.")
        return [TextContent(type="text", text=json.dumps(out, ensure_ascii=False, indent=1)), *blocks]
