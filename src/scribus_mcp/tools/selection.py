"""Selection awareness: what is the user pointing at in the Scribus window?

When the user says "make THIS red" / "change this text" / "make that box bigger" the only place the
answer exists is the visible Scribus window (the interactive bridge). ``get_selection`` reads it
without changing it; ``format_selected_text`` and ``set_selection_colors`` act on it.

Scripter facts this module relies on (Scribus 1.7.4svn, verified empirically; see doc/BEST_PRACTICES.md):

* ``selectionCount()`` / ``getSelectedObject(i)``  - the selected objects (read-only).
* ``getSelectedTextRange(name)`` -> ``(start, length)`` of the highlighted text of a frame, story-wide.
  It is a per-frame property that SURVIVES deselecting the frame, so a stale range can exist on a frame
  that is no longer selected; only trust it for the selected frame.
* ``getAllText(name)`` returns only the highlighted characters when a highlight exists, else the whole
  story. ``getFont/getFontSize/getTextColor(name)`` report the first highlighted character, else the
  frame's current character style. ``setTextColor/setFont/setFontSize`` act on the highlight only when
  one exists, else on the whole story.
* ``selectText(start, length, name)`` replaces the highlight (and moves the cursor to its end);
  ``selectText(0, 0, name)`` clears it. ``selectObject`` ADDS to the selection (call ``deselectAll`` first).
* Newer builds (after applying scripter-selection.patch) add ``getCursorPosition()`` and ``getEditMode()``.
  The tool feature-detects them with ``hasattr`` and degrades gracefully without them.
"""

from __future__ import annotations

import json

from scribus_mcp.backends.headless import HeadlessBackend
from scribus_mcp.tools._common import Mode, ServerCtx, get_backend
from scribus_mcp.tools.palette import resolve_color

# Runs INSIDE Scribus. Everything is prefixed _sel_ so it cannot clash with other scripts.
SEL_LIB = r'''
import re as __re
import scribus as __s

_SEL_SEPS = ("\r", "\n", " ", " ")


def _sel_try(_f, *_a):
    try:
        return _f(*_a)
    except Exception:
        return None


def _sel_mm():
    return {0: 25.4 / 72.0, 1: 1.0, 2: 25.4, 3: 25.4 / 6.0, 4: 10.0, 5: 4.5128}.get(__s.getUnit(), 1.0)


def _sel_hex(_n):
    if not _n or _n == "None":
        return None
    _c = _sel_try(__s.getColorAsRGB, _n)
    return "#%02X%02X%02X" % tuple(int(v) for v in _c[:3]) if _c else None


def _sel_color(_n, _shade=None):
    if _n is None:
        return None
    _d = {"name": _n}
    _h = _sel_hex(_n)
    if _h:
        _d["hex"] = _h
    if _shade is not None and _shade != 100:
        _d["shade"] = _shade
    return _d


def _sel_story(_n, _ctx):
    """Length, highlight and text of a frame. Reading the full text while a highlight exists needs the
    highlight to be lifted for a moment; it is restored in the same call (no event loop runs between)."""
    _len = _sel_try(__s.getTextLength, _n) or 0
    _r = _sel_try(__s.getSelectedTextRange, _n) or (0, 0)
    _st, _ln = int(_r[0]), int(_r[1])
    _o = {"length": _len, "sel_start": _st, "sel_len": _ln, "full": None, "selected": None}
    if _ln > 0:
        _o["selected"] = _sel_try(__s.getAllText, _n)
        if _ctx:
            try:
                __s.selectText(0, 0, _n)
                _o["full"] = _sel_try(__s.getAllText, _n)
            finally:
                _sel_try(__s.selectText, _st, _ln, _n)
    else:
        _o["full"] = _sel_try(__s.getAllText, _n)
    return _o


def _sel_chain(_n):
    _first = _sel_try(__s.getFirstLinkedFrame, _n) or _n
    _out = [_first]
    while len(_out) < 50:
        _nx = _sel_try(__s.getNextLinkedFrame, _out[-1])
        if not _nx or _nx in _out:
            break
        _out.append(_nx)
    return _out if len(_out) > 1 else []


def _sel_formatting(_n):
    _f = {
        "font": _sel_try(__s.getFont, _n),
        "size_pt": _sel_try(__s.getFontSize, _n),
        "color": _sel_color(_sel_try(__s.getTextColor, _n)),
    }
    return _f


def _sel_obj(_n, _ctx, _maxc, _mm):
    _t = _sel_try(__s.getObjectType, _n) or "?"
    _o = {"name": _n, "type": _t}
    _pg = _sel_try(__s.getItemPageNumber, _n)
    if _pg is not None:
        _o["page"] = int(_pg) + 1
    _x, _y = __s.getPosition(_n)
    _w, _h = __s.getSize(_n)
    _o["bbox_mm"] = {"x": round(_x * _mm, 2), "y": round(_y * _mm, 2),
                     "w": round(_w * _mm, 2), "h": round(_h * _mm, 2)}
    _rot = _sel_try(__s.getRotation, _n)
    if _rot:
        _o["rotation_deg"] = round(_rot, 2)
    _o["locked"] = bool(_sel_try(__s.isLocked, _n))
    _o["fill"] = _sel_color(_sel_try(__s.getFillColor, _n), _sel_try(__s.getFillShade, _n))
    _o["line"] = _sel_color(_sel_try(__s.getLineColor, _n), _sel_try(__s.getLineShade, _n))
    _lw = _sel_try(__s.getLineWidth, _n)
    if _lw is not None:
        _o["line_width_pt"] = round(_lw, 2)
    if _t == "Group":
        _items = _sel_try(__s.getGroupItems, _n) or []
        _o["members"] = [_i[0] for _i in _items]
        _o["note"] = "group: edit members by name, or ungroup first"
    elif _t == "ImageFrame":
        _o["image_file"] = _sel_try(__s.getImageFile, _n) or None
    elif _t == "TextFrame":
        _st = _sel_story(_n, _ctx)
        _full = _st["full"]
        _txt = {"chars": _st["length"]}
        _src = _full if _full is not None else _st["selected"]
        if _src is not None:
            _txt["preview"] = _src[:_maxc]
            if len(_src) > _maxc:
                _txt["preview_truncated"] = True
            if _full is None:
                _txt["preview_is_highlight_only"] = True
        _o["text"] = _txt
        _o["formatting"] = _sel_formatting(_n)
        _o["overflows"] = bool(_sel_try(__s.textOverflows, _n))
        _cols = _sel_try(__s.getColumns, _n)
        if _cols and _cols > 1:
            _o["columns"] = _cols
        _ch = _sel_chain(_n)
        if _ch:
            _o["linked_frames"] = _ch
        if _st["sel_len"] > 0:
            _o["highlighted"] = {"start": _st["sel_start"], "length": _st["sel_len"],
                                 "text": (_st["selected"] or "")[:_maxc]}
        _o["_story"] = _st
    elif _t == "Table":
        _o["rows"] = _sel_try(__s.getTableRows, _n)
        _o["columns"] = _sel_try(__s.getTableColumns, _n)
    return _o


def _sel_paragraph(_full, _pos):
    if _full is None or _pos is None:
        return None, None
    _pos = max(0, min(_pos, len(_full)))
    _ps, _idx = 0, 0
    for _i, _ch in enumerate(_full):
        if _ch in _SEL_SEPS:
            if _pos <= _i:
                break
            _ps = _i + 1
            _idx += 1
    _pe = len(_full)
    for _j in range(_ps, len(_full)):
        if _full[_j] in _SEL_SEPS:
            _pe = _j
            break
    return _full[_ps:_pe], _idx


def _sel_word(_full, _pos):
    if _full is None or _pos is None:
        return None
    for _m in __re.finditer(r"\w+", _full):
        if _m.start() <= _pos <= _m.end():
            return _m.group(0)
    return None


def _sel_get(_ctx, _maxc):
    _v = {"has_doc": bool(__s.haveDoc())}
    _has_edit = hasattr(__s, "getEditMode")
    _has_cur = hasattr(__s, "getCursorPosition")
    _v["scribus_api"] = {"getEditMode": _has_edit, "getCursorPosition": _has_cur,
                         "getSelectedTextRange": hasattr(__s, "getSelectedTextRange")}
    if not _v["has_doc"]:
        return _v
    _v["doc"] = _sel_try(__s.getDocName)
    _v["page"] = _sel_try(__s.currentPage)
    _v["page_count"] = _sel_try(__s.pageCount)
    _v["edit_mode"] = bool(__s.getEditMode()) if _has_edit else None
    _mm = _sel_mm()
    _cnt = __s.selectionCount()
    _v["selection_count"] = _cnt
    _names = [__s.getSelectedObject(_i) for _i in range(_cnt)]
    _objs = [_sel_obj(_n, _ctx, _maxc, _mm) for _n in _names]
    _v["text"] = None
    if _cnt == 1 and _objs[0]["type"] == "TextFrame":
        _o = _objs[0]
        _n = _o["name"]
        _st = _o["_story"]
        _sl = _st["sel_len"]
        _cur = int(__s.getCursorPosition(_n)) if _has_cur else None
        _anchor = _cur if _cur is not None else (_st["sel_start"] if _sl > 0 else None)
        _para, _pidx = _sel_paragraph(_st["full"], _anchor)
        _t = {
            "frame": _n,
            "editing": _v["edit_mode"],
            "cursor": _cur,
            "total_chars": _st["length"],
            "selection_start": _st["sel_start"] if _sl > 0 else None,
            "selection_length": _sl,
            "selected_text": _st["selected"] if _sl > 0 else None,
            "paragraph_index": _pidx,
            "paragraph_text": _para,
            "word_at_cursor": _sel_word(_st["full"], _anchor),
            "formatting": dict(_o["formatting"]),
        }
        _t["formatting"]["applies_to"] = ("first highlighted character" if _sl > 0
                                          else "the frame's current character style")
        _v["text"] = _t
    for _o in _objs:
        _o.pop("_story", None)
    _v["objects"] = _objs
    return _v
'''


def _hint(v: dict) -> str:
    if not v.get("has_doc"):
        return "No document is open in Scribus."
    n = v.get("selection_count", 0)
    if n == 0:
        return (
            "Nothing is selected in the Scribus window. If the user said 'this/that/here', ask them to "
            "click the object (or tell you its name; list_page_objects shows what is on the page). "
            "Do not guess."
        )
    objs = v.get("objects", [])
    names = ", ".join(o["name"] for o in objs[:6])
    t = v.get("text")
    parts: list[str] = []
    if t and t.get("selection_length", 0) > 0:
        parts.append(
            "The user has highlighted text inside the frame: 'this text' means selected_text "
            f"(chars {t['selection_start']}..{t['selection_start'] + t['selection_length']}). "
            "To restyle ONLY that text call format_selected_text (color / font / size_pt). "
            "To replace it, use set_text on the whole frame after splicing the new words into the full text."
        )
    elif t:
        parts.append(
            "No words are highlighted: 'this' means the whole frame. format_selected_text restyles all of "
            "its text; set_text / set_font / set_font_size / set_text_color address it by name."
        )
    if any(o["type"] != "TextFrame" for o in objs) or n > 1:
        parts.append(
            "To recolour the selected object(s) call set_selection_colors (fill / line / line_width_pt); "
            "to move or resize use move_object / resize_object with the names above."
        )
    if any(o["type"] == "Group" for o in objs):
        parts.append("A group is selected; its members are listed, ungroup before editing a member.")
    if v.get("edit_mode") is None:
        parts.append(
            "This Scribus build cannot report text-edit mode or the cursor position (needs the "
            "scripter-selection patch); only a highlighted range is detectable."
        )
    return f"Selected: {names}. " + " ".join(parts)


# Runs inside Scribus: restyle a text frame's highlight (or whole story) and restore the user's state.
_FORMAT_BODY = r'''
import scribus as __s
_p = __P__
_cnt = __s.selectionCount()
if _p["name"]:
    _n = _p["name"]
elif _cnt == 1:
    _n = __s.getSelectedObject(0)
else:
    raise RuntimeError("select exactly one text frame (selection_count=%d), or pass name" % _cnt)
if __s.getObjectType(_n) != "TextFrame":
    raise RuntimeError("%s is a %s, not a text frame; use set_selection_colors for shapes" % (_n, __s.getObjectType(_n)))
_len = __s.getTextLength(_n)
_r = __s.getSelectedTextRange(_n)
_hs, _hl = int(_r[0]), int(_r[1])
_scope = _p["scope"]
if _p["start"] is not None:
    _a = int(_p["start"])
    _b = _len if _p["length"] is None else _a + int(_p["length"])
    if _a < 0 or _b > _len or _b <= _a:
        raise RuntimeError("range %d..%d outside text of %d chars" % (_a, _b, _len))
    _whole = False
elif _scope == "frame" or (_scope == "auto" and _hl == 0):
    _a, _b, _whole = 0, _len, True
elif _hl > 0:
    _a, _b, _whole = _hs, _hs + _hl, False
else:
    raise RuntimeError("scope='highlight' but no text is highlighted in %s" % _n)
if _len == 0:
    raise RuntimeError("%s has no text to format" % _n)
_before = {"font": __s.getFont(_n), "size_pt": __s.getFontSize(_n), "color": __s.getTextColor(_n)}
try:
    if _whole:
        __s.selectText(0, 0, _n)
    else:
        __s.selectText(_a, _b - _a, _n)
    if _p["color"] is not None:
        __s.setTextColor(_p["color"], _n)
        if _p["shade"] is not None:
            __s.setTextShade(int(_p["shade"]), _n)
    if _p["font"] is not None:
        __s.setFont(_p["font"], _n)
    if _p["size_pt"] is not None:
        __s.setFontSize(float(_p["size_pt"]), _n)
    _after = {"font": __s.getFont(_n), "size_pt": __s.getFontSize(_n), "color": __s.getTextColor(_n)}
finally:
    # put the user's highlight back (or clear the temporary one)
    if _hl > 0:
        __s.selectText(_hs, _hl, _n)
    else:
        __s.selectText(0, 0, _n)
_value = {"frame": _n, "whole_frame": _whole, "start": _a, "length": _b - _a,
          "before_first_char": _before, "after_first_char": _after,
          "highlight_restored": _hl > 0}
'''

_COLORS_BODY = r'''
import scribus as __s
_p = __P__
_cnt = __s.selectionCount()
_sel = [__s.getSelectedObject(_i) for _i in range(_cnt)]
if not _sel:
    raise RuntimeError("nothing is selected in Scribus")
_targets, _skipped = [], []
for _n in _sel:
    if __s.getObjectType(_n) == "Group":
        for _it in (__s.getGroupItems(_n) or []):
            _targets.append(_it[0])
    else:
        _targets.append(_n)
_done = []
for _n in _targets:
    _t = __s.getObjectType(_n)
    _e = {"name": _n, "type": _t}
    try:
        if _p["fill"] is not None:
            __s.setFillColor(_p["fill"], _n)
            if _p["fill_shade"] is not None:
                __s.setFillShade(int(_p["fill_shade"]), _n)
            _e["fill"] = __s.getFillColor(_n)
        if _p["line"] is not None:
            __s.setLineColor(_p["line"], _n)
            _e["line"] = __s.getLineColor(_n)
        if _p["line_width_pt"] is not None:
            __s.setLineWidth(float(_p["line_width_pt"]), _n)
            _e["line_width_pt"] = __s.getLineWidth(_n)
    except Exception as _ex:
        _e["error"] = str(_ex)
    _done.append(_e)
_value = {"selected": _sel, "applied": _done, "selection_count_after": __s.selectionCount()}
'''


def _fill(body: str, params: dict) -> str:
    return body.replace("__P__", repr(params))


def _headless_msg() -> dict:
    return {
        "ok": False,
        "interactive": False,
        "error": (
            "No visible Scribus window is connected (headless mode): there is no user selection to "
            "read. Selection awareness only works with the interactive bridge. Ask the user to start "
            "Scribus with scribus_mcp_bridge.spy, or name the object explicitly (list_page_objects)."
        ),
    }


def register(mcp, ctx: ServerCtx) -> None:
    async def _read(mode: Mode, include_context: bool, max_text_chars: int) -> dict:
        backend = await get_backend(ctx, mode)
        if isinstance(backend, HeadlessBackend):
            return _headless_msg()
        body = SEL_LIB + f"\n_value = _sel_get({bool(include_context)!r}, {int(max_text_chars)!r})\n"
        res = await backend.script(body, result_expr="_value")
        if not res.ok:
            return {"ok": False, "error": res.error}
        v = dict(res.value or {})
        v["ok"] = True
        v["interactive"] = True
        v["hint"] = _hint(v)
        return v

    @mcp.tool()
    async def get_selection(
        include_context: bool = True,
        max_text_chars: int = 200,
        mode: Mode = "auto",
    ) -> dict:
        """What is the user pointing at in the Scribus window? CALL THIS FIRST whenever the user says
        this / that / these / selected / here / "the box I clicked" / "the words I highlighted" -
        never guess which object they mean.

        Read-only: does not change what is selected. Returns the current page, ``selection_count``
        and for each selected object its name, type, page, bbox in mm, fill and line colour (name +
        hex), locked flag, group members, and for text frames the font / size / text colour, a text
        preview, overflow flag, linked-frame chain and the highlighted range. For a single selected
        text frame the ``text`` section adds: editing (is the user typing in it), cursor position,
        selection_start / selection_length / selected_text (the highlighted words), the paragraph and
        word around the cursor, and the formatting there. ``hint`` says what to do next.

        Use the names it returns with the normal tools (set_text_color, move_object, ...), or the
        selection-aware tools format_selected_text (colour / font / size of the highlighted words only)
        and set_selection_colors (fill / line of the selected objects).

        Interactive mode only (a visible Scribus with the bridge); headless has no user selection.
        ``include_context=False`` is strictly passive (no paragraph text while words are highlighted);
        the default briefly lifts and restores the highlight to read the full text.
        """
        return await _read(mode, include_context, max_text_chars)

    @mcp.resource("scribus://document/selection")
    async def selection_resource() -> str:
        """The user's current selection in the Scribus window (same JSON as get_selection)."""
        return json.dumps(await _read("auto", True, 200), ensure_ascii=False)

    async def _resolve(backend, color: str | None, what: str):
        """-> (name_or_None, error_or_None). 'None' means transparent (only valid for fill/line)."""
        if color is None:
            return None, None
        if color == "None":
            return "None", None
        name, _ = await resolve_color(backend, color, fallback_color="\0")
        if name == "\0":
            return None, (
                f"unknown {what} colour {color!r}: use a defined colour name, a #RRGGBB value or a "
                "basic colour word (red, blue, ...)"
            )
        return name, None

    @mcp.tool()
    async def format_selected_text(
        color: str | None = None,
        font: str | None = None,
        size_pt: float | None = None,
        shade: int | None = None,
        scope: str = "auto",
        start: int | None = None,
        length: int | None = None,
        name: str | None = None,
        mode: Mode = "auto",
    ) -> dict:
        """Restyle the text the user is pointing at: colour, font and/or size. Call get_selection first.

        scope "auto" (default): the highlighted words if the user highlighted some in the selected text
        frame, otherwise ALL text of the selected frame. "highlight": only the highlighted words (error
        if none). "frame": the whole frame text even if words are highlighted. ``start``/``length``
        (character indices, as in get_selection) override the scope with an explicit range.
        ``name`` targets a frame explicitly instead of the single selected one.

        Only the chosen range changes; the user's selection / highlight is restored afterwards.
        ``color``: a defined colour name, #RRGGBB or a basic colour word. Interactive mode only.
        """
        backend = await get_backend(ctx, mode)
        if isinstance(backend, HeadlessBackend):
            return _headless_msg()
        if scope not in ("auto", "highlight", "frame"):
            return {"ok": False, "error": "scope must be auto, highlight or frame"}
        if color is None and font is None and size_pt is None:
            return {"ok": False, "error": "give at least one of color, font, size_pt"}
        if size_pt is not None and size_pt < 5:
            return {"ok": False, "error": "size_pt below 5 pt is not legible in print"}
        cname, err = await _resolve(backend, color, "text")
        if err:
            return {"ok": False, "error": err}
        params = {"name": name, "color": cname, "font": font, "size_pt": size_pt, "shade": shade,
                  "scope": scope, "start": start, "length": length}
        res = await backend.script(_fill(_FORMAT_BODY, params), result_expr="_value")
        if not res.ok:
            return {"ok": False, "error": res.error}
        return {"ok": True, **(res.value or {})}

    @mcp.tool()
    async def set_selection_colors(
        fill: str | None = None,
        line: str | None = None,
        line_width_pt: float | None = None,
        fill_shade: int | None = None,
        mode: Mode = "auto",
    ) -> dict:
        """Change the fill and/or line (border) colour of the object(s) the user has selected - no
        names needed. Call get_selection first so you know what is selected. A selected group is
        applied to its members. Colours: a defined name, #RRGGBB, a basic colour word, or "None"
        (transparent / no line). For a TEXT frame, ``fill`` is the frame's background, NOT the
        letters: use format_selected_text(color=...) to colour the text itself.
        Does not change what is selected. Interactive mode only.
        """
        backend = await get_backend(ctx, mode)
        if isinstance(backend, HeadlessBackend):
            return _headless_msg()
        if fill is None and line is None and line_width_pt is None:
            return {"ok": False, "error": "give at least one of fill, line, line_width_pt"}
        fname, err = await _resolve(backend, fill, "fill")
        if err:
            return {"ok": False, "error": err}
        lname, err = await _resolve(backend, line, "line")
        if err:
            return {"ok": False, "error": err}
        params = {"fill": fname, "line": lname, "line_width_pt": line_width_pt, "fill_shade": fill_shade}
        res = await backend.script(_fill(_COLORS_BODY, params), result_expr="_value")
        if not res.ok:
            return {"ok": False, "error": res.error}
        return {"ok": True, **(res.value or {})}
