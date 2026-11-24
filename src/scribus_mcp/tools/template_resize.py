"""Height-only resize of a template (.sla text), done BEFORE the document is opened.

Newspaper templates have a FIXED width (the column width the paper sells); only the height may
change. Scribus' scripter cannot change the page size of an open document, so the page height and
the object geometry are rewritten in the .sla text:

* the body (main text) frame gets the whole height difference;
* everything that starts at or below the bottom of the body (sign-off, last-line frame, bottom
  blocks) moves by the difference;
* everything that encloses the body (outer / inner border rectangles, background panels) grows or
  shrinks by the difference; their outline path is rescaled;
* everything beside the body (header, logo ...) stays where it is (top anchored).

Limits: single-page templates in the Scribus 1.7 file format; one body frame (when several
text frames are body-sized the main one is used and a warning says so); rotated items are left
alone. :func:`plan_height_change` is pure (no Scribus, no file access) and unit-tested.
"""

from __future__ import annotations

import re
from typing import Any

PT_PER_MM = 72.0 / 25.4
MIN_BODY_MM = 10.0
TOL_PT = 3.0  # items whose top is within this of the body bottom count as "below the body"

_NUM = r"-?\d+(?:\.\d+)?"


def pick_body(items: list[dict[str, Any]]) -> tuple[dict[str, Any] | None, list[str]]:
    """The main text frame: named body / body_text, else the largest chain-head text frame."""
    warns: list[str] = []
    texts = [i for i in items if i["kind"] == "text" and not i.get("continuation")]
    if not texts:
        return None, ["no text frame found"]
    named = [i for i in texts if i["name"].lower() in ("body", "body_text")]
    body = named[0] if named else max(texts, key=lambda i: i["w"] * i["h"])
    area = body["w"] * body["h"]
    rivals = [i["name"] for i in texts if i is not body and i["w"] * i["h"] >= 0.6 * area]
    if rivals:
        warns.append(f"several body-sized text frames ({', '.join(rivals)}): only {body['name']} "
                     "takes the height change")
    return body, warns


def plan_height_change(items: list[dict[str, Any]], delta: float, body: str | None = None,
                       min_body: float = MIN_BODY_MM * PT_PER_MM, tol: float = TOL_PT) -> dict[str, Any]:
    """Geometry changes for growing (delta > 0) or shrinking (delta < 0) the page height.

    ``items``: dicts ``{name, kind('text'|'other'), y, h, w, continuation?}`` (any one length unit, the
    same as ``delta`` / ``min_body`` / ``tol``; y measured down from the page top). Returns
    ``{body, changes: {name: {role, y, h}}, warnings}``; ``role`` is body | move | stretch.
    Raises ValueError when the body would become shorter than ``min_body``.
    """
    warns: list[str] = []
    if body:
        b = next((i for i in items if i["name"] == body), None)
        if b is None:
            raise ValueError(f"body frame {body!r} not found")
    else:
        b, warns = pick_body(items)
        if b is None:
            raise ValueError("no text frame to take the height change")
    b_top, b_bot = b["y"], b["y"] + b["h"]
    if b["h"] + delta < min_body:
        raise ValueError(f"cannot shrink by {-delta:g}: the body frame {b['name']} would be "
                         f"{b['h'] + delta:g} high (minimum {min_body:g})")
    changes: dict[str, dict[str, Any]] = {b["name"]: {"role": "body", "y": b["y"], "h": b["h"] + delta}}
    for it in items:
        if it is b:
            continue
        top, bot = it["y"], it["y"] + it["h"]
        if top >= b_bot - tol or (top > b_top and top < b_bot - tol and bot > b_bot + tol):
            changes[it["name"]] = {"role": "move", "y": it["y"] + delta, "h": it["h"]}
        elif top <= b_top + tol and bot >= b_bot - tol:
            changes[it["name"]] = {"role": "stretch", "y": it["y"], "h": it["h"] + delta}
    return {"body": b["name"], "changes": changes, "warnings": warns}


# --------------------------------------------------------------------------- .sla text editing


def _get(tag: str, name: str) -> str | None:
    m = re.search(r'(?<![\w])' + name + r'="([^"]*)"', tag)
    return m.group(1) if m else None


def _set(tag: str, name: str, value: str) -> str:
    return re.sub(r'(?<![\w])(' + name + r')="[^"]*"', lambda m: f'{m.group(1)}="{value}"', tag, count=1)


def _fmt(v: float) -> str:
    return f"{v:.4f}"


def scale_path_y(path: str, factor: float) -> str:
    """Multiply every y coordinate of an SVG-like path (M/L/C numbers alternate x y) by ``factor``."""
    out: list[str] = []
    n = 0
    for tok in re.finditer(r"([A-Za-z])|(" + _NUM + ")", path):
        if tok.group(1):
            out.append(("" if not out else " ") + tok.group(1))
            n = 0
            continue
        v = float(tok.group(2))
        if n % 2 == 1:
            v *= factor
        out.append(("" if out and out[-1][-1:].isalpha() else " ") + f"{v:.4f}".rstrip("0").rstrip("."))
        n += 1
    return "".join(out).strip()


def read_items(text: str) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Items (page 1) of a Scribus 1.7 .sla and the page facts. Raises ValueError if unsupported."""
    doc = re.search(r"<Document\b[^>]*>", text)
    if not doc:
        raise ValueError("height change needs a Scribus 1.7 .sla file")
    pages = int(_get(doc.group(0), "PageCount") or 1)
    if pages != 1:
        raise ValueError("height change supports single-page templates only")
    ph = float(_get(doc.group(0), "PageHeight") or 0)
    pw = float(_get(doc.group(0), "PageWidth") or 0)
    page = re.search(r"<Page\b[^>]*>", text)
    page_y = float(_get(page.group(0), "PageYPosition") or 0) if page else 0.0
    items: list[dict[str, Any]] = []
    for m in re.finditer(r"<PageObject\b[^>]*>", text):
        t = m.group(0)
        name = _get(t, "AutoName") or _get(t, "ItemName") or _get(t, "ANNAME") or f"_item{len(items)}"
        try:
            y = float(_get(t, "YPosition")) - page_y
            h = float(_get(t, "Height"))
        except (TypeError, ValueError):
            continue
        items.append({
            "name": name, "kind": "text" if _get(t, "ItemType") == "4" else "other", "y": y, "h": h,
            "w": float(_get(t, "Width") or 0),
            "continuation": (_get(t, "BackItem") not in (None, "-1")),
            "rotated": abs(float(_get(t, "Rotation") or 0)) > 0.01,
            "span": (m.start(), m.end()), "tag": t,
        })
    return items, {"page_w": pw, "page_h": ph, "page_y": page_y}


def resize_sla_height(text: str, *, height_mm: float | None = None, extra_height_mm: float | None = None,
                      ) -> tuple[str, dict[str, Any]]:
    """Return ``(new_text, report)`` with the page height changed. ``height_mm`` = new page height,
    ``extra_height_mm`` = difference (negative = shorter). Width never changes."""
    items, facts = read_items(text)
    old_h = facts["page_h"]
    if height_mm is not None and extra_height_mm is not None:
        raise ValueError("pass height_mm OR extra_height_mm, not both")
    if height_mm is not None:
        delta_pt = float(height_mm) * PT_PER_MM - old_h
    else:
        delta_pt = float(extra_height_mm or 0.0) * PT_PER_MM
    if abs(delta_pt) < 0.01:
        return text, {"changed": False, "page_h_mm": round(old_h / PT_PER_MM, 1)}
    if old_h + delta_pt < 20 * PT_PER_MM:
        raise ValueError("resulting page height would be below 20 mm")
    plan = plan_height_change([i for i in items if not i["rotated"]], delta_pt)
    out: list[str] = []
    pos = 0
    moved: list[str] = []
    for it in items:
        ch = plan["changes"].get(it["name"])
        if not ch or it["rotated"]:
            continue
        t = it["tag"]
        old_y, old_hh = float(_get(t, "YPosition")), it["h"]
        new_y = old_y + (ch["y"] - it["y"])
        t = _set(t, "YPosition", _fmt(new_y))
        if _get(t, "gYpos") is not None and abs(float(_get(t, "gYpos")) - old_y) < 0.01:
            t = _set(t, "gYpos", _fmt(new_y))
        if abs(ch["h"] - old_hh) > 1e-6:
            t = _set(t, "Height", _fmt(ch["h"]))
            f = ch["h"] / old_hh if old_hh else 1.0
            for key in ("Path", "ContourLinePath"):
                v = _get(t, key)
                if v:
                    t = _set(t, key, scale_path_y(v, f))
        out.append(text[pos:it["span"][0]])
        out.append(t)
        pos = it["span"][1]
        moved.append(f"{it['name']}:{ch['role']}")
    out.append(text[pos:])
    new = "".join(out)
    new_h = old_h + delta_pt
    # page height in <Document> and every <Page>/<MasterPage> start tag
    def fix(m: re.Match) -> str:
        t = m.group(0)
        cur = _get(t, "PageHeight")
        if cur is not None and abs(float(cur) - old_h) < 0.05:
            t = _set(t, "PageHeight", repr(round(new_h, 9)))
        return t
    new = re.sub(r"<(?:Document|Page|MasterPage)\b[^>]*>", fix, new)
    rep = {
        "changed": True, "body_frame": plan["body"],
        "old_page_h_mm": round(old_h / PT_PER_MM, 1), "page_h_mm": round(new_h / PT_PER_MM, 1),
        "delta_mm": round(delta_pt / PT_PER_MM, 1), "adjusted": moved, "warnings": plan["warnings"],
    }
    return new, rep
