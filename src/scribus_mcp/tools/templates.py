"""Scribus template library (File > New from Template) as MCP tools.

Agents should start from a template whenever one fits (newspaper notice, flyer, brochure ...)
instead of from an empty page. Templates are listed from ``template.xml`` indexes found in the
Scribus install (``<bin dir>/share/templates``), the user's templates folder and any folders in
``SCRIBUS_MCP_TEMPLATE_DIRS`` (os.pathsep separated). Folders with an .sla but without an index
entry are listed too. Template folders are only ever READ; ``new_from_template`` copies the
.sla to ``save_as`` and opens the copy.
"""

from __future__ import annotations

import gzip
import os
import shutil
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

from scribus_mcp.tools._common import Mode, ServerCtx, get_backend


def template_dirs(scribus_bin: str | None) -> list[Path]:
    dirs: list[Path] = []
    for p in os.environ.get("SCRIBUS_MCP_TEMPLATE_DIRS", "").split(os.pathsep):
        if p:
            dirs.append(Path(p))
    if scribus_bin:
        b = Path(scribus_bin).resolve().parent
        dirs += [b / "share" / "templates", b.parent / "share" / "scribus" / "templates",
                 b.parent / "share" / "templates"]
    home = Path.home()
    dirs += [home / ".scribus" / "templates", home / "scribus" / "templates"]
    if sys.platform == "win32":
        appdata = os.environ.get("APPDATA")
        if appdata:
            dirs.append(Path(appdata) / "scribus" / "templates")
    dirs += [Path("/usr/share/scribus/templates"), Path("/usr/local/share/scribus/templates")]
    seen: set[str] = set()
    out = []
    for d in dirs:
        key = str(d).lower()
        if key not in seen and d.is_dir():
            seen.add(key)
            out.append(d)
    return out


def _text(el: ET.Element, tag: str) -> str:
    c = el.find(tag)
    return (c.text or "").strip() if c is not None else ""


def scan_templates(dirs: list[Path]) -> list[dict]:
    found: list[dict] = []
    seen_files: set[str] = set()
    for d in dirs:
        idx = d / "template.xml"
        if idx.is_file():
            try:
                raw = idx.read_bytes().decode("utf-8", errors="replace")
                # index files declare encoding="utf8", which expat rejects
                raw = raw.replace('encoding="utf8"', 'encoding="utf-8"', 1)
                raw = raw.split("?>", 1)[1] if raw.lstrip().startswith("<?xml") else raw
                root = ET.fromstring(raw)
            except (ET.ParseError, OSError):
                root = None
            for el in root.findall("template") if root is not None else []:
                rel = _text(el, "file")
                f = (d / rel) if rel else None
                if not f or not f.is_file():
                    continue
                seen_files.add(str(f.resolve()).lower())
                prev = d / _text(el, "img")
                found.append({
                    "id": f.parent.name if f.parent != d else f.stem,
                    "name": _text(el, "name"),
                    "category": el.get("category", ""),
                    "page_size": _text(el, "psize"),
                    "colors": _text(el, "color"),
                    "description": _text(el, "descr"),
                    "usage": _text(el, "usage"),
                    "file": str(f),
                    "preview": str(prev) if prev.is_file() else None,
                })
        for f in sorted(d.glob("*/*.sla*")):
            if f.suffix not in (".sla", ".gz") or str(f.resolve()).lower() in seen_files:
                continue
            seen_files.add(str(f.resolve()).lower())
            found.append({
                "id": f.parent.name, "name": f.parent.name, "category": "(not in index)",
                "page_size": "", "colors": "", "description": "", "usage": "",
                "file": str(f), "preview": None,
            })
    return found


def register(mcp, ctx: ServerCtx) -> None:
    @mcp.tool()
    async def list_templates(query: str = "", category: str = "") -> dict:
        """List Scribus templates you can start from. START HERE for a new document.

        ``query`` filters by words in name/description/id, ``category`` by category (e.g.
        "Newspaper Ads"). Each entry has ``id``, ``name``, ``category``, ``page_size``,
        ``description``, ``usage`` and a ``preview`` PNG path you can look at. Open one with
        ``new_from_template``.
        """
        items = scan_templates(template_dirs(ctx.config.scribus_bin))
        words = [w for w in query.lower().split() if w]
        out = []
        for t in items:
            hay = " ".join([t["id"], t["name"], t["description"], t["category"]]).lower()
            if words and not all(w in hay for w in words):
                continue
            if category and category.lower() not in t["category"].lower():
                continue
            out.append({k: v for k, v in t.items() if k != "file"})
        cats = sorted({t["category"] for t in items})
        return {"ok": True, "count": len(out), "categories": cats, "templates": out, "error": None}

    @mcp.tool()
    async def new_from_template(template: str, save_as: str, mode: Mode = "auto") -> dict:
        """Create a new document from a template: copies the template to ``save_as`` (a .sla
        path) and opens the copy, so the original template is never modified.

        ``template`` is the ``id`` or (part of) the ``name`` from ``list_templates``. Returns the
        page size and every text frame with its current text and geometry, so you can replace
        the placeholder text with ``set_text`` / ``set_text_hindi`` and then ``verify_document``.
        ``editable_fields`` lists every text frame with its role (headline, offer, contact, logo
        slot ...), current text, font and char budget; fill them with ``fill_template_fields``.
        """
        items = scan_templates(template_dirs(ctx.config.scribus_bin))
        t = next((x for x in items if x["id"].lower() == template.lower()), None)
        if t is None:
            t = next((x for x in items if template.lower() in x["name"].lower()), None)
        if t is None:
            return {"ok": False, "error": f"no template matching {template!r}; call list_templates"}
        dst = Path(save_as)
        if dst.suffix.lower() != ".sla":
            return {"ok": False, "error": "save_as must end in .sla"}
        dst.parent.mkdir(parents=True, exist_ok=True)
        src = Path(t["file"])
        if src.suffix == ".gz":
            with gzip.open(src, "rb") as fin, open(dst, "wb") as fout:
                shutil.copyfileobj(fin, fout)
        else:
            shutil.copyfile(src, dst)
        backend = await get_backend(ctx, mode)
        body = f"""
import scribus as _s
_s.openDoc({str(dst)!r})
_u = 25.4 / 72.0 / _s.pointsToDocUnit(1.0)
_pw, _ph = _s.getPageSize()
_frames = []
for _p in range(1, _s.pageCount() + 1):
    _s.gotoPage(_p)
    for _it in (_s.getPageItems() or []):
        if _it[1] == 4:
            _n = _it[0]
            _x, _y = _s.getPosition(_n)
            _w, _h = _s.getSize(_n)
            _t = _s.getAllText(_n)
            _frames.append({{'name': _n, 'page': _p, 'x_mm': round(_x * _u, 1), 'y_mm': round(_y * _u, 1),
                            'w_mm': round(_w * _u, 1), 'h_mm': round(_h * _u, 1), 'chars': len(_t),
                            'text': _t[:80]}})
_value = {{'pages': _s.pageCount(), 'page_w_mm': round(_pw * _u, 1), 'page_h_mm': round(_ph * _u, 1),
          'text_frames': _frames}}
"""
        res = await backend.script(body, result_expr="_value")
        if not res.ok:
            return {"ok": False, "error": res.error}
        from scribus_mcp.tools.template_fields import describe_open_document
        fields = await describe_open_document(backend)  # editable_fields, decorative, instructions
        return {"ok": True, "template": t["name"], "document": str(dst), **(res.value or {}),
                **fields, "usage": t["usage"], "error": None}
