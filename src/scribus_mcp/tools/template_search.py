"""``find_templates``: shortlist templates for a plain-words requirement, with preview images.

Flow: user describes an ad (English / Hindi / Hinglish) -> ``find_templates`` returns a ranked
shortlist (JSON + a numbered contact sheet + one preview per candidate) -> the client shows the
pictures to the USER and asks which one -> ``new_from_template(id, save_as)``.

Ranking is deterministic (no LLM): a synonym index (``data/template_tags.json``) maps words in
three scripts to concepts (school, jewellery, diwali ...); templates carry hand-reviewed tags, and
templates without an entry get draft tags derived from ``template.xml`` and the ``.sla`` itself,
so any template in the library is searchable. The real page size comes from the .sla.

Maintenance::

    python -m scribus_mcp.tools.template_search --retag [--dirs DIR;DIR] [--out draft.json]
    python -m scribus_mcp.tools.template_search --query "school admission 4 col x 12 cm" [--dirs ..]

``--retag`` prints draft tags for templates that have no entry in the tag file (review them, copy
into ``template_tags.json`` or into a file named by ``SCRIBUS_MCP_TEMPLATE_TAGS``, which overrides
the packaged data). Template folders are only ever read.
"""

from __future__ import annotations

import base64
import difflib
import html
import io
import json
import os
import re
import sys
import unicodedata
from functools import lru_cache
from pathlib import Path
from typing import Any

from scribus_mcp.tools._common import ServerCtx
from scribus_mcp.tools.template_sla import sla_info

DATA_FILE = Path(__file__).resolve().parent.parent / "data" / "template_tags.json"

# Newspaper geometry (mm). Broadsheet page 325 x 470; columns about 40 mm incl. gutter.
COL_NOMINAL = 40.4
COL_LO, COL_HI = 34.5, 42.0
PAPER = {"a0": (841, 1189), "a1": (594, 841), "a2": (420, 594), "a3": (297, 420),
         "a4": (210, 297), "a5": (148, 210), "a6": (105, 148)}
NAMED_TARGETS: dict[str, list[tuple[float, float]]] = {
    "full_page": [(325, 470)], "jacket": [(325, 470)],
    "half_page": [(325, 235), (161, 470)], "quarter_page": [(161, 235)],
    "eighth_page": [(161, 117), (325, 117)], "sixth_page": [(105, 50)],
    "strip": [(325, 80)],
}
NAMED_LABEL = {"full_page": "full page", "jacket": "jacket (full page)", "half_page": "half page",
               "quarter_page": "quarter page", "eighth_page": "1/8 page",
               "sixth_page": "1/6 page", "strip": "strip"}
CATEGORY_KIND = {"newspaper ads": "display", "flyers & posters": "flyer", "brochures": "brochure",
                 "newsletters": "newsletter", "business cards": "card", "cards": "card",
                 "grids": "grid", "books": "book", "pdf presentations": "presentation",
                 "packaging": "packaging", "stationery": "calendar"}
UNRELATED_KINDS = {"grid", "packaging", "presentation", "card", "book"}


# ----------------------------------------------------------------------------- text helpers
_DEVA_DIGITS = str.maketrans("०१२३४५६७८९", "0123456789")


def norm(s: str) -> str:
    """Lower-case, NFC, ASCII digits, no nukta/ZWJ, chandrabindu->anusvara, unified x."""
    s = html.unescape(s or "")
    s = unicodedata.normalize("NFC", s).translate(_DEVA_DIGITS).lower()
    for a, b in (("×", "x"), ("‍", ""), ("‌", ""), ("़", ""), ("ँ", "ं"),
                 ("’", "'"), ("“", '"'), ("”", '"'), ("।", " "), ("₹", " rs ")):
        s = s.replace(a, b)
    return s


_STRIP = " \t\r\n.,;:!?()[]{}\"'<>|*#@~`_=+"


def tokens(s: str) -> list[str]:
    out = []
    for t in norm(s).split():
        t = t.strip(_STRIP)
        if t:
            out.append(t)
    return out


def _is_roman(t: str) -> bool:
    return bool(re.fullmatch(r"[a-z0-9&/\-%]+", t))


# ----------------------------------------------------------------------------- tag data
@lru_cache(maxsize=1)
def _load_data_cached(extra: str, extra_mtime: float) -> dict:
    data = json.loads(DATA_FILE.read_text(encoding="utf-8"))
    if extra:
        try:
            more = json.loads(Path(extra).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            more = {}
        for k in ("templates", "concepts"):
            data.setdefault(k, {}).update(more.get(k, {}))
        data["patterns"] = list(more.get("patterns", [])) + list(data.get("patterns", []))
    return data


def load_data() -> dict:
    extra = os.environ.get("SCRIBUS_MCP_TEMPLATE_TAGS", "")
    mt = Path(extra).stat().st_mtime if extra and Path(extra).is_file() else 0.0
    return _load_data_cached(extra, mt)


class Index:
    """Phrase index over concepts / kinds / colours / languages (all scripts)."""

    def __init__(self, data: dict):
        self.data = data
        self.phrases: dict[tuple[str, ...], list[tuple[str, str]]] = {}
        self.roman_vocab: set[str] = set()
        self.parent = {c: v.get("parent") for c, v in data["concepts"].items()}
        self.weight = {c: float(v.get("w", 10)) for c, v in data["concepts"].items()}
        for c, v in data["concepts"].items():
            for w in v["words"]:
                self._add(w, ("concept", c))
        for k, words in data["kind_words"].items():
            for w in words:
                self._add(w, ("kind", k))
        for k, words in data["colour_words"].items():
            for w in words:
                self._add(w, ("colour", k))
        for k, words in data["language_words"].items():
            for w in words:
                self._add(w, ("lang", k))
        self.stop = {norm(w) for w in data.get("stopwords", [])}

    def _add(self, word: str, tag: tuple[str, str]) -> None:
        toks = tuple(tokens(word))
        if not toks:
            return
        lst = self.phrases.setdefault(toks, [])
        if tag not in lst:
            lst.append(tag)
        if len(toks) == 1 and _is_roman(toks[0]) and len(toks[0]) >= 5:
            self.roman_vocab.add(toks[0])

    def scan(self, text: str) -> dict:
        """Find concepts/kinds/colour/language in free text. Returns hits + unmatched words."""
        toks = tokens(text)
        used = [False] * len(toks)
        hits: dict[str, list] = {"concept": [], "kind": [], "colour": [], "lang": []}
        fuzzy: list[tuple[str, str]] = []
        i = 0
        while i < len(toks):
            matched = 0
            for n in range(min(4, len(toks) - i), 0, -1):
                key = tuple(toks[i:i + n])
                tags = self.phrases.get(key)
                if tags is None and n == 1 and len(key[0]) > 3 and key[0].endswith("s"):
                    tags = self.phrases.get((key[0][:-1],))
                if tags:
                    for cat, val in tags:
                        if val not in [h[0] for h in hits[cat]]:
                            hits[cat].append((val, " ".join(key)))
                    matched = n
                    break
            if not matched:
                t = toks[i]
                if _is_roman(t) and len(t) >= 5 and not t.isdigit():
                    near = [c for c in difflib.get_close_matches(t, self.roman_vocab, n=1, cutoff=0.86)
                            if c[0] == t[0]]
                    if near:
                        for cat, val in self.phrases[(near[0],)]:
                            if val not in [h[0] for h in hits[cat]]:
                                hits[cat].append((val, t))
                        fuzzy.append((t, near[0]))
                        matched = 1
            if matched:
                for j in range(i, i + matched):
                    used[j] = True
                i += matched
            else:
                i += 1
        unmatched = [t for t, u in zip(toks, used) if not u]
        return {"hits": hits, "unmatched": unmatched, "fuzzy": fuzzy, "tokens": toks}

    def related(self, q: str, t: str) -> float:
        """How strongly query concept q is satisfied by template concept t."""
        if q == t:
            return 1.0
        pq, pt = self.parent.get(q), self.parent.get(t)
        if pt == q:
            return 0.6          # query is general (health), template specific (clinic)
        if pq == t:
            return 0.5          # query specific (diwali), template tagged at the general level
        if pq and pq == pt:
            return 0.4          # siblings (diwali / holi)
        return 0.0


def get_index() -> Index:
    data = load_data()
    return _index_cached(id(data))


@lru_cache(maxsize=4)
def _index_cached(data_id: int) -> Index:
    return Index(load_data())


# ----------------------------------------------------------------------------- size parsing
_NUM = r"(\d+(?:\.\d+)?)"
_COL = r"(?:columns?|cols?|कॉलम(?:ों)?|कालम(?:ों)?|कलम|स्तंभ)(?![a-z])"
_CM = r"(?:cm|c\.m\.?|centimet(?:er|re)s?|सेमी|से\.मी\.?|सेंटीमीटर)(?![a-z])"
_SEP = r"(?:x|\*|by|बाई|गुणा)"
_RX_COL_BY_CM = re.compile(_NUM + r"\s*" + _COL + r"\s*(?:" + _SEP + r")?\s*" + _NUM + r"\s*(?:" + _CM + r")?")
_RX_CM_BY_COL = re.compile(_NUM + r"\s*" + _CM + r"\s*" + _SEP + r"?\s*" + _NUM + r"\s*" + _COL)
_RX_COL_ONLY = re.compile(r"(?:(single|double|one|two|three|ek|do|teen|एक|दो|तीन)|" + _NUM + r")\s*" + _COL)
_RX_DIMS = re.compile(_NUM + r"\s*(cm|mm|in|inch|inches|\")?\s*" + _SEP + r"\s*" + _NUM + r"\s*(cm|mm|in|inch|inches|\")?(?![a-z0-9])")
_RX_PAPER = re.compile(r"(?<![a-z0-9])(a[0-6])(?![a-z0-9])")
_WORD_N = {"single": 1, "one": 1, "ek": 1, "एक": 1, "double": 2, "two": 2, "do": 2, "दो": 2,
           "three": 3, "teen": 3, "तीन": 3}
_NAMED_RX = [
    ("eighth_page", re.compile(r"(?:1/8|one[- ]eighth|eighth)\s*(?:page|pg)?|आठवां\s*पेज")),
    ("sixth_page", re.compile(r"(?:1/6|one[- ]sixth|sixth)\s*(?:page|pg)?")),
    ("quarter_page", re.compile(r"(?:quarter|1/4|chauthai|चौथाई|चौथा)\s*(?:page|pg|पेज)?")),
    ("half_page", re.compile(r"(?:half|1/2|adha|aadha|aadhe|adhe|आधा|आधे)\s*[- ]?(?:page|pg|पेज|पृष्ठ)")),
    ("full_page", re.compile(r"(?:full|poora|pura|पूरा|पूरे)\s*[- ]?(?:page|pg|पेज|पृष्ठ)")),
    ("jacket", re.compile(r"jacket|जैकेट|front page wrap|cover wrap")),
    ("strip", re.compile(r"(?<![a-z])strip(?![a-z])|पट्टी")),
]


def parse_size(text: str) -> tuple[dict | None, str]:
    """Extract a size request from text. Returns (size dict | None, text with size removed).

    size = {kind: 'cols'|'cm'|'paper'|'named', cols, w_mm, h_mm, paper, named, label, note}
    """
    s = norm(text)
    size: dict | None = None

    def blank(m: re.Match) -> None:
        nonlocal s
        s = s[:m.start()] + " " * (m.end() - m.start()) + s[m.end():]

    m = _RX_COL_BY_CM.search(s)
    if m:
        cols, h = float(m.group(1)), float(m.group(2))
        size = {"kind": "cols", "cols": cols, "h_cm": h, "label": f"{cols:g} col x {h:g} cm"}
        blank(m)
    if size is None:
        m = _RX_CM_BY_COL.search(s)
        if m:
            h, cols = float(m.group(1)), float(m.group(2))
            size = {"kind": "cols", "cols": cols, "h_cm": h, "label": f"{cols:g} col x {h:g} cm"}
            blank(m)
    if size is None:
        m = _RX_DIMS.search(s)
        if m:
            a, ua, b, ub = float(m.group(1)), m.group(2), float(m.group(3)), m.group(4)
            unit = ua or ub
            if unit in ("in", "inch", "inches", '"'):
                size = {"kind": "cm", "w_mm": a * 25.4, "h_mm": b * 25.4,
                        "label": f"{a:g} x {b:g} inch"}
            elif unit == "mm":
                size = {"kind": "cm", "w_mm": a, "h_mm": b, "label": f"{a:g} x {b:g} mm"}
            elif a <= 8 and float(a).is_integer() and b >= 2:
                size = {"kind": "cols", "cols": a, "h_cm": b, "label": f"{a:g} col x {b:g} cm",
                        "note": f"read '{a:g}x{b:g}' as {a:g} columns x {b:g} cm (newspaper style)"}
            else:
                size = {"kind": "cm", "w_mm": a * 10, "h_mm": b * 10, "label": f"{a:g} x {b:g} cm"}
            blank(m)
    if size is None:
        m = _RX_COL_ONLY.search(s)
        if m:
            cols = float(_WORD_N.get(m.group(1), 0) or m.group(2))
            size = {"kind": "cols", "cols": cols, "h_cm": None, "label": f"{cols:g} col"}
            blank(m)
    if size is None:
        m = _RX_PAPER.search(s)
        if m:
            p = m.group(1)
            size = {"kind": "paper", "paper": p, "label": p.upper()}
            blank(m)
    if size is None:
        for key, rx in _NAMED_RX:
            m = rx.search(s)
            if m:
                size = {"kind": "named", "named": key, "label": NAMED_LABEL[key]}
                blank(m)
                break
    return size, s


# ----------------------------------------------------------------------------- size fit
def _dim_score(target: float, actual: float, tol: float) -> float:
    rel = abs(actual - target) / target
    if rel <= tol:
        return 1.0
    return max(0.0, 1.0 - (rel - tol) / (0.35 - tol))


def _width_cols_score(cols: float, w: float) -> float:
    lo, hi = cols * COL_LO, cols * COL_HI
    if lo <= w <= hi:
        return 1.0
    ref = lo if w < lo else hi
    return _dim_score(ref, w, 0.04)


def size_fit(req: dict, w: float, h: float, size_tags: list[str]) -> tuple[float, str]:
    """Return (score 0..1, explanation) of a template page (w x h mm) against a size request."""
    k = req["kind"]
    if k == "cols":
        ws = _width_cols_score(req["cols"], w)
        hs = 1.0 if not req.get("h_cm") else _dim_score(req["h_cm"] * 10, h, 0.06)
        s = ws * hs
        if req["cols"] == 1 and "single_column" in size_tags:
            s = max(s, 0.95)
        return s, f"{size_label(w, h)} vs asked {req['label']}"
    if k == "named":
        key = req["named"]
        if key in size_tags:
            return 1.0, f"{size_label(w, h)}: tagged {NAMED_LABEL[key]}"
        best = 0.0
        for tw, th in NAMED_TARGETS[key]:
            if key == "strip":
                best = max(best, _dim_score(tw, w, 0.05) * (1.0 if h <= 105 else _dim_score(105, h, 0.0)))
            else:
                best = max(best, _dim_score(tw, w, 0.05) * _dim_score(th, h, 0.05))
        return best, f"{size_label(w, h)} vs {NAMED_LABEL[key]}"
    if k == "paper":
        pw, ph = PAPER[req["paper"]]
        s1 = _dim_score(pw, w, 0.03) * _dim_score(ph, h, 0.03)
        s2 = 0.85 * _dim_score(ph, w, 0.03) * _dim_score(pw, h, 0.03)
        return max(s1, s2), f"{size_label(w, h)} vs {req['label']}"
    s1 = _dim_score(req["w_mm"], w, 0.06) * _dim_score(req["h_mm"], h, 0.06)
    s2 = 0.85 * _dim_score(req["h_mm"], w, 0.06) * _dim_score(req["w_mm"], h, 0.06)
    return max(s1, s2), f"{size_label(w, h)} vs asked {req['label']}"


def size_label(w: float, h: float) -> str:
    """Human label: 'N col x H cm (half page)' for newspaper sizes, 'A4 portrait', or plain cm."""
    frac = ""
    for key in ("full_page", "half_page", "quarter_page", "eighth_page"):
        for tw, th in NAMED_TARGETS[key]:
            if abs(w - tw) <= 6 and abs(h - th) <= 10:
                orient = ""
                if key == "half_page":
                    orient = " horizontal" if tw > th else " vertical"
                frac = NAMED_LABEL[key] + orient
    for name, (pw, ph) in PAPER.items():
        if abs(w - pw) <= 2 and abs(h - ph) <= 2:
            return f"{name.upper()} portrait"
        if abs(w - ph) <= 2 and abs(h - pw) <= 2:
            return f"{name.upper()} landscape"
    n = round(w / COL_NOMINAL)
    if n >= 1 and n * COL_LO * 0.98 <= w <= n * COL_HI * 1.02 and h >= 20:
        lab = f"{n} col x {h / 10:.1f} cm".replace(".0 cm", " cm")
        return f"{lab} ({frac})" if frac else lab
    return f"{w / 10:.1f} x {h / 10:.1f} cm".replace(".0 ", " ")


# ----------------------------------------------------------------------------- library
def library_dirs(scribus_bin: str | None = None) -> list[Path]:
    from scribus_mcp.tools.templates import template_dirs
    return template_dirs(scribus_bin)


_SLA_CACHE: dict[tuple, dict] = {}


def _sla_cached(path: str) -> dict:
    try:
        st = Path(path).stat()
    except OSError:
        return {"ok": False}
    key = (path, st.st_mtime_ns, st.st_size)
    if key not in _SLA_CACHE:
        _SLA_CACHE[key] = sla_info(path)
    return _SLA_CACHE[key]


def _kruti_to_unicode(text: str) -> str:
    try:
        from scribus_mcp.kruti import from_kruti
        return from_kruti(text)
    except Exception:  # pragma: no cover
        return text


def _find_preview(folder: Path, tid: str) -> str | None:
    for cand in (folder / f"{tid}.png", folder / f"{tid}.jpg"):
        if cand.is_file():
            return str(cand)
    others = sorted(p for p in folder.glob("*.png") if not p.stem.endswith("tn"))
    if others:
        return str(others[0])
    tns = sorted(folder.glob("*tn.png"))
    return str(tns[0]) if tns else None


def load_library(dirs: list[Path]) -> list[dict]:
    """All templates in ``dirs`` (first dir wins on duplicate ids), index fields + .sla facts."""
    from scribus_mcp.tools.templates import scan_templates
    out: dict[str, dict] = {}
    for d in dirs:
        for t in scan_templates([d]):
            tid = t["id"]
            if tid in out:
                continue
            f = Path(t["file"])
            t = dict(t)
            if not t.get("preview"):
                t["preview"] = _find_preview(f.parent, tid)
            if t["category"] == "(not in index)":
                t["category"] = "Newspaper Ads" if tid.startswith(("news_", "ad_")) else "(not in index)"
                t["indexed"] = False
                t["name"] = tid.replace("_", " ").strip().capitalize()
            else:
                t["indexed"] = True
            t["sla"] = _sla_cached(t["file"])
            out[tid] = t
    return list(out.values())


# ----------------------------------------------------------------------------- tags
def _pattern_tags(tid: str, data: dict) -> dict:
    for p in data.get("patterns", []):
        if re.search(p["match"], tid):
            return {k: v for k, v in p.items() if k != "match"}
    return {}


def _is_bw_text(color_text: str) -> bool | None:
    c = color_text.lower()
    if not c:
        return None
    if re.search(r"b/?w|black|grey|gray|mono", c) and not re.search(r"colou?r.*(green|blue|red)", c):
        return True
    return False


def derive_tags(t: dict, idx: Index) -> dict:
    """Draft tags for a template from template.xml fields, folder name and .sla facts."""
    sla = t.get("sla", {})
    bag_parts = [t["id"].replace("_", " "), t.get("name", ""), t.get("description", "")]
    if sla.get("ok") and not sla.get("kruti"):
        bag_parts.append(sla.get("text", ""))
    elif sla.get("ok"):
        bag_parts.append(_kruti_to_unicode(sla.get("text", "")))
    scan = idx.scan(" ".join(bag_parts))
    concepts = [c for c, _ in scan["hits"]["concept"]]
    themes, also = concepts[:2], concepts[2:6]
    kinds = [k for k, _ in scan["hits"]["kind"]]
    kind: list[str] = []
    cat_kind = CATEGORY_KIND.get(t["category"].lower())
    if cat_kind:
        kind.append(cat_kind)
    for k in kinds:
        if k not in kind and k in ("notice", "classified", "flyer", "poster", "calendar", "menu"):
            kind.append(k)
    tid = t["id"].lower()
    if tid.startswith("news_disp_") and "display" not in kind:
        kind.append("display")
    if re.search(r"classified|vacanc|matrimon", tid) and "classified" not in kind:
        kind.insert(0, "classified")
    if not kind:
        kind = ["other"]
    # language: Kruti font or Devanagari text -> hindi; Latin only -> english
    lang_words = [v for v, _ in scan["hits"]["lang"]]
    if sla.get("kruti") or sla.get("devanagari") or "hindi" in lang_words:
        language = "hindi"
    else:
        language = "english"
    # colour: template.xml text, then _bw / _color in the id, then the .sla colours
    bw = _is_bw_text(t.get("colors", ""))
    if re.search(r"(^|_)bw(_|$)", tid):
        bw = True
    elif re.search(r"(^|_)colou?r(_|$)", tid):
        bw = False
    if bw is None:
        bw = bool(sla.get("bw", False)) if sla.get("ok") else False
    words = []
    for w in tokens(" ".join([t.get("name", ""), t["id"].replace("_", " "), t.get("description", "")])):
        if len(w) > 2 and w not in idx.stop and w not in words and not w.isdigit():
            words.append(w)
    tags: dict[str, Any] = {"themes": themes, "also": also, "kind": kind, "language": language,
                            "colour": "bw" if bw else "colour", "keywords": words[:20]}
    return tags


def effective_tags(t: dict, data: dict, idx: Index) -> tuple[dict, str]:
    """(tags, source) where source is 'reviewed' (tag file entry) or 'auto'."""
    manual = data["templates"].get(t["id"])
    auto = derive_tags(t, idx)
    pat = _pattern_tags(t["id"], data)
    if manual is not None:
        tags = {**auto, **manual}
        return tags, "reviewed"
    if pat:
        tags = {**auto, **pat}
        return tags, "auto"
    return auto, "auto"


# ----------------------------------------------------------------------------- query
def parse_query(requirement: str, hints: dict, idx: Index) -> dict:
    """Turn the requirement text + optional hints into a structured query."""
    text = requirement or ""
    size, rest = parse_size(text)
    if hints.get("size"):
        hs, _ = parse_size(hints["size"])
        if hs:
            size = hs
    scan = idx.scan(rest)
    hits = scan["hits"]
    concepts = [c for c, _ in hits["concept"]]
    kinds = [k for k, _ in hits["kind"]]
    explicit_kind = norm(hints.get("kind", "")).strip()
    if explicit_kind:
        sk = idx.scan(explicit_kind)["hits"]["kind"]
        explicit_kind = sk[0][0] if sk else explicit_kind
        if explicit_kind not in kinds:
            kinds.insert(0, explicit_kind)
    colour = None
    cands = [c for c, _ in hits["colour"]]
    if hints.get("colour"):
        hc = idx.scan(hints["colour"])["hits"]["colour"]
        if hc:
            cands = [hc[0][0]]
        elif norm(hints["colour"]).strip() in ("colour", "color"):
            cands = ["colour"]
        elif norm(hints["colour"]).strip() in ("bw", "b/w"):
            cands = ["bw"]
    if cands:
        colour = "bw" if "bw" in cands else cands[0]
    lang = None
    lcands = [v for v, _ in hits["lang"]]
    if hints.get("language"):
        hl = idx.scan(hints["language"])["hits"]["lang"]
        if hl:
            lcands = [hl[0][0]]
    if lcands:
        lang = lcands[0]
    elif re.search("[ऀ-ॿ]", text):
        lang = "hindi"
    stop = idx.stop
    free = [t for t in scan["unmatched"] if t not in stop and len(t) >= 3 and not t.isdigit()
            and not re.fullmatch(r"[\d.x/\-%]+", t)]
    return {"raw": requirement, "size": size, "concepts": concepts, "kinds": kinds,
            "explicit_kind": explicit_kind or None, "colour": colour, "language": lang,
            "free_words": free, "fuzzy": scan["fuzzy"], "category": (hints.get("category") or "").strip()}


def _bag(t: dict, tags: dict) -> set[str]:
    parts = [t["id"].replace("_", " "), t.get("name", ""), t.get("description", ""),
             " ".join(tags.get("keywords", [])), " ".join(tags.get("themes", [])),
             " ".join(tags.get("also", []))]
    return set(tokens(" ".join(parts)))


LANG_SCORE = {  # (query, template) -> points
    ("hindi", "hindi"): 2, ("hindi", "bilingual"): 1, ("hindi", "english"): 0,
    ("english", "english"): 2, ("english", "bilingual"): 1, ("english", "hindi"): 0,
    ("hinglish", "bilingual"): 2, ("hinglish", "hindi"): 1, ("hinglish", "english"): 1,
}


def score_template(t: dict, tags: dict, q: dict, idx: Index) -> dict:
    w = idx.weight
    pts = 0.0
    why: list[str] = []
    evidence = "weak"
    topic_pts = 0.0
    matched_topics: list[str] = []
    prim = list(tags.get("themes", []))
    sec = [c for c in tags.get("also", []) if c not in prim]
    exact_topic = False
    dom = max([w.get(c, 10.0) for c in q["concepts"]] or [0.0])
    for qc in q["concepts"]:
        best, via, level = 0.0, None, ""
        for tc, lv in [(c, 1.0) for c in prim] + [(c, 0.5) for c in sec]:
            r = idx.related(qc, tc) * lv
            if r > best:
                best, via, level = r, tc, ("primary" if lv == 1.0 else "secondary")
        if best > 0:
            topic_pts += w.get(qc, 10.0) * best
            matched_topics.append(qc if via == qc else f"{qc}~{via}")
            if best >= 1.0 and w.get(qc, 10.0) >= max(6.0, dom * 0.99):
                exact_topic = True
    if matched_topics:
        pts += topic_pts
        why.append("topic: " + ", ".join(matched_topics))
    # kind
    tk = tags.get("kind", [])
    if q["kinds"]:
        hit = [k for k in q["kinds"] if k in tk]
        if hit:
            pts += 4 if "notice" in hit else 6
            why.append("kind: " + ", ".join(hit))
        elif q["explicit_kind"]:
            pts -= 6
            why.append(f"kind is {'/'.join(tk)}, not {q['explicit_kind']}")
        else:
            pts -= 2
    elif UNRELATED_KINDS & set(tk):
        pts -= 5
        hit = []
    else:
        hit = []
    # colour
    tc_ = tags.get("colour")
    if q["colour"] and tc_:
        if q["colour"] == tc_:
            pts += 5 if tc_ == "bw" else 3
            why.append("colour: " + ("black & white" if tc_ == "bw" else "colour"))
        else:
            pts -= 8 if q["colour"] == "bw" else 6
            why.append("colour: template is " + ("black & white" if tc_ == "bw" else "colour")
                       + f", you asked {'black & white' if q['colour'] == 'bw' else 'colour'}")
    # language
    tl = tags.get("language")
    if q["language"] and tl:
        d = LANG_SCORE.get((q["language"], tl), 0)
        pts += d
        if d > 0:
            why.append(f"language: {tl} placeholder text")
        elif q["language"] in ("hindi", "english") and tl in ("hindi", "english"):
            why.append(f"placeholder text is {tl} (you asked {q['language']}; the text is replaced anyway)")
    # size
    sla = t.get("sla", {})
    fit_cls, fit_s = "none", 0.0
    wmm = hmm = None
    if sla.get("ok"):
        wmm, hmm = sla["w_mm"], sla["h_mm"]
    if q["size"] and wmm is not None:
        fit_s, expl = size_fit(q["size"], wmm, hmm, tags.get("size_tags", []))
        if fit_s >= 0.9:
            fit_cls, pts = "exact", pts + 7 * fit_s
            why.append("size fits: " + expl)
        elif fit_s >= 0.45:
            fit_cls, pts = "near", pts + 7 * fit_s
            why.append("size near: " + expl)
        else:
            fit_cls = "no"
            pts -= 2
            why.append("size differs: " + expl)
    # free words
    bag = _bag(t, tags)
    fw = [x for x in q["free_words"] if x in bag]
    if fw:
        pts += min(6.0, 2.0 * len(fw))
        why.append("words: " + ", ".join(fw[:4]))
    # generic fallback bonus and category filter
    if tags.get("generic"):
        pts += 1
    if q["category"] and q["category"].lower() not in t["category"].lower():
        pts -= 50
    # evidence
    if exact_topic:
        evidence = "strong"
        pts += 3
    elif matched_topics or (q["kinds"] and hit) or fw or (
            fit_cls == "exact" and not (UNRELATED_KINDS & set(tk))):
        evidence = "partial"
    return {"score": round(pts, 2), "why": why, "evidence": evidence, "size_fit": fit_cls,
            "fit": round(fit_s, 2)}


# ----------------------------------------------------------------------------- search
def _lang_label(tl: str | None) -> str:
    return {"hindi": "Hindi (Kruti Dev placeholder text)", "english": "English",
            "bilingual": "Hindi + English"}.get(tl or "", tl or "unknown")


def search(requirement: str, dirs: list[Path], *, max_results: int = 5, **hints: str) -> dict:
    """Pure ranking function (no images). Returns the JSON-able result dict."""
    data = load_data()
    idx = get_index()
    lib = load_library(dirs)
    q = parse_query(requirement, hints, idx)
    scored = []
    n_auto = 0
    auto_ids = []
    for t in lib:
        tags, src = effective_tags(t, data, idx)
        if src == "auto":
            n_auto += 1
            auto_ids.append(t["id"])
        sc = score_template(t, tags, q, idx)
        scored.append((sc["score"], t["id"], t, tags, src, sc))
    scored.sort(key=lambda x: (-x[0], x[1]))
    non_weak = [s for s in scored if s[5]["evidence"] != "weak"]
    if non_weak and non_weak[0][5]["evidence"] == "strong":
        # keep partial hits only when they are reasonably close to the best one
        non_weak = [s for s in non_weak if s[5]["evidence"] == "strong" or s[0] >= 0.4 * non_weak[0][0]]
    max_results = max(1, min(int(max_results or 5), 12))
    if non_weak:
        quality = "good" if non_weak[0][5]["evidence"] == "strong" else "partial"
        chosen = non_weak[:max_results]
    else:
        quality = "none"
        chosen = scored[:min(3, max_results)]
    cands = []
    for rank, (score, tid, t, tags, src, sc) in enumerate(chosen, 1):
        sla = t.get("sla", {})
        w = sla.get("w_mm")
        h = sla.get("h_mm")
        cands.append({
            "number": rank, "id": tid, "name": t["name"], "category": t["category"],
            "size_label": size_label(w, h) if w else (t.get("page_size") or "unknown"),
            "page_mm": [w, h] if w else None,
            "pages": sla.get("pages"),
            "colour": "black & white" if tags.get("colour") == "bw" else "colour",
            "language": _lang_label(tags.get("language")),
            "kind": tags.get("kind"),
            "match": sc["evidence"], "size_fit": sc["size_fit"] if q["size"] else None,
            "why": sc["why"] or ["no specific match"], "score": sc["score"],
            "tags_source": src, "preview": t.get("preview"),
            "description": (t.get("description") or "")[:160],
        })
    ignored = [x for x in q["free_words"] if not any(x in _bag(c[2], c[3]) for c in scored[:1])]
    parsed = {"size": q["size"]["label"] if q["size"] else None,
              "size_note": (q["size"] or {}).get("note"),
              "topics": q["concepts"], "kinds": q["kinds"], "colour": q["colour"],
              "language": q["language"], "ignored_words": q["free_words"][:10]}
    if quality == "good":
        msg = "Found close matches. Show the previews to the user and ask which to start from."
    elif quality == "partial":
        msg = ("Only partial matches (same size, kind or a related topic, not the exact subject). "
               "Say so to the user, show the previews and ask whether one is acceptable or "
               "whether to start from a blank page.")
    else:
        msg = ("Nothing close: no template matches this request. These are the nearest; tell the "
               "user honestly, or build from a blank page with create_document.")
    if q["free_words"] and quality != "good":
        msg += " Words not understood: " + ", ".join(q["free_words"][:6]) + "."
    return {"ok": True, "match_quality": quality, "message": msg, "query": parsed,
            "library": {"templates": len(lib), "auto_tagged": n_auto,
                        "dirs": [str(d) for d in dirs]},
            "candidates": cands, "_auto_ids": auto_ids}


# ----------------------------------------------------------------------------- images
def _font(size: int):
    from PIL import ImageFont
    for name in ("arialbd.ttf", "arial.ttf", "DejaVuSans-Bold.ttf", "DejaVuSans.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    try:
        return ImageFont.load_default(size)
    except TypeError:  # old Pillow
        return ImageFont.load_default()


def _open_preview(path: str | None):
    from PIL import Image
    if not path:
        return None
    try:
        im = Image.open(path)
        im.load()
    except Exception:
        return None
    if im.mode in ("RGBA", "LA", "P"):
        im = im.convert("RGBA")
        bg = Image.new("RGB", im.size, "white")
        bg.paste(im, mask=im.split()[-1])
        return bg
    return im.convert("RGB")


def candidate_png(path: str | None, label: str = "no preview", max_px: int = 480) -> bytes:
    """Preview downscaled to ``max_px`` on the longest side, as PNG bytes."""
    from PIL import Image, ImageDraw
    im = _open_preview(path)
    if im is None:
        im = Image.new("RGB", (320, 240), "#eeeeee")
        ImageDraw.Draw(im).text((20, 100), label, fill="#555555", font=_font(20))
    im.thumbnail((max_px, max_px))
    buf = io.BytesIO()
    im.save(buf, "PNG", optimize=True)
    return buf.getvalue()


def contact_sheet(cands: list[dict], cell_w: int = 380, cell_h: int = 330) -> bytes:
    """ONE JPEG with every candidate in a grid, numbered 1..N (red badge) and captioned."""
    from PIL import Image, ImageDraw
    n = max(1, len(cands))
    cols = min(n, 3)
    rows = (n + cols - 1) // cols
    cap_h = 44
    pad = 10
    W = cols * (cell_w + pad) + pad
    H = rows * (cell_h + cap_h + pad) + pad
    sheet = Image.new("RGB", (W, H), "#f4f4f4")
    d = ImageDraw.Draw(sheet)
    f_cap, f_num = _font(15), _font(24)
    for i, c in enumerate(cands):
        x = pad + (i % cols) * (cell_w + pad)
        y = pad + (i // cols) * (cell_h + cap_h + pad)
        d.rectangle([x, y, x + cell_w, y + cell_h + cap_h], fill="white", outline="#cccccc")
        im = _open_preview(c.get("preview"))
        if im is not None:
            im.thumbnail((cell_w - 12, cell_h - 12))
            sheet.paste(im, (x + (cell_w - im.width) // 2, y + (cell_h - im.height) // 2))
        else:
            d.text((x + 20, y + cell_h // 2), "no preview", fill="#777777", font=f_cap)
        d.ellipse([x + 4, y + 4, x + 40, y + 40], fill="#d32f2f")
        num = str(c["number"])
        bb = d.textbbox((0, 0), num, font=f_num)
        d.text((x + 22 - (bb[2] - bb[0]) / 2, y + 22 - (bb[3] - bb[1]) / 2 - 3), num, fill="white", font=f_num)
        d.text((x + 6, y + cell_h + 4), c["id"][:44], fill="#111111", font=f_cap)
        sub = f"{c['size_label']} | {'B/W' if c['colour'].startswith('black') else 'colour'}"
        d.text((x + 6, y + cell_h + 24), sub[:52], fill="#555555", font=f_cap)
    buf = io.BytesIO()
    sheet.save(buf, "JPEG", quality=85)
    return buf.getvalue()


# ----------------------------------------------------------------------------- tool
def build_response(res: dict) -> list:
    """Text block + contact sheet + one image per candidate (rank order)."""
    from mcp.types import ImageContent, TextContent
    cands = res["candidates"]
    out = {k: v for k, v in res.items() if not k.startswith("_")}
    out["candidates"] = [{**{k: v for k, v in c.items() if k != "preview"},
                          "preview_png": c.get("preview")} for c in cands]
    if cands:
        top = cands[0]["id"]
        out["images"] = ("Image 1 is the numbered contact sheet (candidates 1.."
                         f"{len(cands)}); images 2.. are the same candidates in rank order.")
        out["next_step"] = (f"Show the images to the USER and ask which number to start from "
                            f"(do not pick silently when several are reasonable). Then call "
                            f"new_from_template(template='<id>', save_as='<path>.sla'), e.g. "
                            f"new_from_template(template='{top}', save_as=...)."
                            " It returns the editable fields to fill.")
    blocks: list = [TextContent(type="text", text=json.dumps(out, ensure_ascii=False, indent=1))]
    if cands:
        blocks.append(ImageContent(type="image", mimeType="image/jpeg",
                                   data=base64.b64encode(contact_sheet(cands)).decode()))
        for c in cands:
            blocks.append(ImageContent(type="image", mimeType="image/png",
                                       data=base64.b64encode(candidate_png(c.get("preview"))).decode()))
    return blocks


def register(mcp, ctx: ServerCtx) -> None:
    @mcp.tool()
    async def find_templates(
        requirement: str,
        category: str = "",
        size: str = "",
        language: str = "",
        colour: str = "",
        kind: str = "",
        max_results: int = 5,
    ) -> list:
        """CALL THIS when the user wants to start a new ad / flyer / notice and describes what
        they need (English, Hindi, Hinglish; newspaper sizes like '4x12', '4 col x 12 cm',
        'half page', 'A4', '10x15 cm'). Returns a ranked shortlist of templates from the library
        with PREVIEW IMAGES: image 1 is a numbered contact sheet, then one preview per
        candidate. SHOW THE IMAGES TO THE USER AND LET THEM PICK; do not silently choose when
        several are reasonable. If ``match_quality`` is 'partial' or 'none' say so honestly
        (nothing close) instead of presenting a weak match as a fit.

        ``requirement`` is the user's words as given. Optional hints (override the parse):
        ``size`` ('3x10', 'A4', 'half page'), ``language`` ('hindi'|'english'|'hinglish'),
        ``colour`` ('colour'|'bw'), ``kind`` ('display'|'classified'|'notice'|'flyer'|'poster'|
        'brochure'|...), ``category`` (e.g. 'Newspaper Ads'), ``max_results`` (default 5).
        The chosen ``id`` goes to ``new_from_template(template=id, save_as=...)``, which returns
        the editable fields.
        """
        res = search(requirement, library_dirs(ctx.config.scribus_bin), max_results=max_results,
                     category=category, size=size, language=language, colour=colour, kind=kind)
        return build_response(res)


# ----------------------------------------------------------------------------- CLI
def _cli(argv: list[str]) -> int:
    import argparse
    ap = argparse.ArgumentParser(prog="template_search", description=__doc__.split("\n\n")[0])
    ap.add_argument("--retag", action="store_true", help="print draft tags for untagged templates")
    ap.add_argument("--all", action="store_true", help="with --retag: draft tags for every template")
    ap.add_argument("--query", help="rank the library for this requirement and print the table")
    ap.add_argument("--dirs", default=os.environ.get("SCRIBUS_MCP_TEMPLATE_DIRS", ""),
                    help="template folders separated by the OS path separator")
    ap.add_argument("--out", help="write --retag JSON here instead of stdout")
    ap.add_argument("-n", type=int, default=5)
    a = ap.parse_args(argv)
    dirs = [Path(p) for p in a.dirs.split(os.pathsep) if p and Path(p).is_dir()]
    if not dirs:
        dirs = library_dirs(os.environ.get("SCRIBUS_BIN"))
    if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
        sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    if a.query:
        r = search(a.query, dirs, max_results=a.n)
        print(json.dumps({k: v for k, v in r.items() if k in ("match_quality", "query", "library")},
                         ensure_ascii=False))
        for c in r["candidates"]:
            print(f"{c['number']}. {c['id']:42} {c['score']:6.1f} {c['match']:7} {c['size_label']:18} "
                  f"{c['colour'][:6]:6} | {'; '.join(c['why'])}")
        return 0
    if a.retag:
        data, idx = load_data(), get_index()
        out = {}
        for t in load_library(dirs):
            if a.all or t["id"] not in data["templates"]:
                tags = derive_tags(t, idx)
                tags["_draft"] = True
                out[t["id"]] = tags
        text = json.dumps({"templates": out}, ensure_ascii=False, indent=1)
        if a.out:
            Path(a.out).write_text(text, encoding="utf-8")
            print(f"wrote draft tags for {len(out)} templates to {a.out}")
        else:
            print(text)
        return 0
    ap.print_help()
    return 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(_cli(sys.argv[1:]))
