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

import re
from pathlib import Path
from typing import Any

from scribus_mcp.tools._adlib import AD_LIB, build_rich_text, has_devanagari
from scribus_mcp.tools._common import Mode, ServerCtx, clean_user_text, get_backend

MIN_PT = 5.0

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
    decor = [o["name"] for o in scan.get("other", [])]
    return {
        "fields": fields,
        "decorative": {"count": len(decor), "names": decor[:80],
                       "note": "shapes / images forming the design (panels, bursts, borders): "
                               "leave them alone, do not delete or move them"},
        "page_mm": [pw, ph],
    }


INSTRUCTIONS_FOR_CLIENT = (
    "To finish the ad: (1) from the user collect what is missing for each field: business name, "
    "headline / main offer, dates and timings, phone number(s), address, website, and the logo "
    "image file (and a photo if the template has a photo slot); ask in one message, do not invent "
    "phone numbers, dates or prices. (2) Call fill_template_fields({name or role: new text}) once; "
    "write Hindi as normal Unicode Devanagari (it is converted to Kruti Dev 010 automatically; never "
    "type Kruti keystrokes yourself), English as plain text. (3) Keep each text within its "
    "char_budget (approx_total characters at the current size; the tool shrinks text to fit but "
    "never below 5 pt, so shorter is better than tiny). (4) Fields with role logo_slot / photo_slot "
    "are image slots; decorative objects must not be edited. Roles marked confidence 'low' or "
    "'unknown' are guesses: check the preview before writing into them. (5) fill_template_fields "
    "returns the verify_document result; fix every error, then render_preview and LOOK at it, "
    "then export_press_pdf."
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


def _fill_script(specs: list[dict], logo: dict | None, min_pt: float) -> str:
    return AD_LIB + f"""
import scribus as _s
_specs = {specs!r}
_logo = {logo!r}
_res = []
for _sp in _specs:
    _f = _sp['name']
    try:
        # delete + insert (not setText): keeps the frame's paragraph alignment and default style
        _n0 = _s.getTextLength(_f)
        if _n0 > 0:
            _s.selectText(0, _n0, _f)
            _s.deleteText(_f)
        _s.insertText(_sp['text'], 0, _f)
        _s.setLineSpacingMode(1, _f)
        _before = _sp['size']
        _scale = _ad_fit(_f, _sp['spans'], 'shrink', {min_pt}, 1.0, False, _sp['text'].count(chr(10)) + 1)
        _ov = _ad_overflow(_f)
        _res.append({{'name': _f, 'scale': round(_scale, 3), 'overflow': bool(_ov), 'lines': _ad_lines(_f),
                     'size_from': _before, 'size_to': round(max(_x['size'] for _x in _sp['spans']) * _scale, 2)}})
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
_value = {{'fields': _res, 'logo': _logo_res, 'warnings': _AD_WARN}}
"""


def register(mcp, ctx: ServerCtx) -> None:
    @mcp.tool()
    async def fill_template_fields(
        fields: dict[str, str],
        logo_path: str = "",
        min_font_pt: float = 5.0,
        run_verify: bool = True,
        mode: Mode = "auto",
    ) -> dict:
        """Fill an opened template's text fields in ONE call (use after ``new_from_template``,
        which lists the editable fields and their char budgets).

        ``fields`` maps an object name from ``editable_fields`` (or a role such as
        'headline', 'contact', 'offer', 'business_name', 'fine_print', 'body_text'; 'contact_2'
        = second contact frame) to the new text. Hindi may be given as normal Unicode: it is
        converted to Kruti Dev 010 and the Latin parts keep the frame's font; the original
        colour is kept. Each text is shrunk to fit its frame (never below ``min_font_pt``, 5 pt
        floor); the result per field says 'fitted', 'shrunk to X pt' or 'OVERFLOW' (then shorten
        the text). ``logo_path`` (png/jpg/tif/svg file) replaces the first logo placeholder
        with the image, scaled to fit. Returns the per-field outcome, the fields you did not
        fill and the ``verify_document`` result (fix errors, then render_preview).
        """
        backend = await get_backend(ctx, mode)
        scan_res = await backend.script(COLLECT_SCRIPT, result_expr="_value")
        if not scan_res.ok:
            return {"ok": False, "error": scan_res.error}
        scan = scan_res.value or {}
        cls = classify_fields(scan)
        flds = cls["fields"]
        targets, errors = _resolve_keys({k: clean_user_text(v) for k, v in fields.items()}, flds)
        runs_by_name = {f["name"]: f.get("runs") or [] for f in scan.get("frames", [])}
        specs = []
        for name, text in targets.items():
            runs = runs_by_name.get(name) or []
            para_runs, latin_font, size, color = build_field_runs(text, runs)
            full, spans, _ = build_rich_text(text, para_runs, font=latin_font, size_pt=size,
                                             color=color, hindi="auto")
            spans = [{k: v for k, v in sp.items() if v is not None} for sp in spans]
            specs.append({"name": name, "text": full, "spans": spans, "size": size})
        logo = None
        notes: list[str] = []
        if logo_path:
            p = Path(logo_path)
            slot = next((f for f in flds if f["role"] == "logo_slot"), None)
            if not p.is_file():
                errors.append(f"logo_path not found: {logo_path}")
            elif slot is None:
                notes.append("no logo slot found in this template; logo not placed")
            else:
                logo = {"name": slot["name"], "path": str(p.resolve())}
        if not specs and not logo:
            return {"ok": False, "error": "; ".join(errors) or "nothing to fill", "errors": errors}
        res = await backend.script(_fill_script(specs, logo, max(MIN_PT, float(min_font_pt))),
                                   result_expr="_value")
        if not res.ok:
            return {"ok": False, "error": res.error}
        val = res.value or {}
        report = []
        for r in val.get("fields", []):
            if r.get("error"):
                report.append({"name": r["name"], "status": "error: " + r["error"]})
                continue
            if r["overflow"]:
                status = f"OVERFLOW at {r['size_to']} pt: shorten the text"
            elif r["scale"] < 0.999:
                status = f"shrunk to {r['size_to']} pt (from {r['size_from']})"
            else:
                status = "fitted"
            report.append({"name": r["name"], "status": status, "size_pt": r["size_to"],
                           "lines": r["lines"]})
        unfilled = [{"name": f["name"], "role": f["role"], "text": f["text"][:60]} for f in flds
                    if f["name"] not in targets and f["role"] not in
                    ("empty_frame", "logo_slot" if logo else "", "unknown")]
        out: dict[str, Any] = {"ok": True, "filled": report, "logo": val.get("logo"),
                               "unfilled_fields": unfilled, "warnings": val.get("warnings") or [],
                               "notes": notes, "errors": errors, "error": None}
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
        out["next_step"] = ("Fix any OVERFLOW / verify errors (shorten text), then render_preview and "
                            "look at the picture, then export_press_pdf.")
        return out
