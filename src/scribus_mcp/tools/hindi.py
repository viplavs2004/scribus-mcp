"""Hindi / Devanagari support and role-based font discovery.

Indian newspaper ads are usually set in the legacy font Kruti Dev 010, which is NOT Unicode:
it draws Latin keystrokes as Devanagari shapes. Unicode Hindi shown in it appears as empty
boxes, and Kruti keystrokes shown in a normal font appear as Latin garbage. The converter in
``scribus_mcp.kruti`` (tested separately, copied from the Scribus agent) turns Unicode Hindi
into the keystrokes.
"""

from __future__ import annotations

from typing import Literal

from scribus_mcp.kruti import from_kruti
from scribus_mcp.tools._adlib import AD_LIB, KRUTI_SENTINEL, build_rich_text, has_devanagari
from scribus_mcp.tools._common import Mode, ServerCtx, clean_user_text, get_backend

# (role, substrings that identify a family, preferred order)
FONT_ROLES: dict[str, tuple[str, ...]] = {
    "display_condensed": (
        "Impact", "Bebas", "Oswald", "Arial Narrow", "Franklin Gothic Demi Cond",
        "Franklin Gothic", "Bahnschrift", "Condensed",
    ),
    "headline_bold": (
        "Arial Black", "Segoe UI Black", "Segoe UI Bold", "Arial Bold", "Trebuchet MS Bold",
        "Verdana Bold", "Tahoma Bold", "Calibri Bold",
    ),
    "slogan_italic": (
        "Trebuchet MS Bold Italic", "Georgia Bold Italic", "Arial Bold Italic",
        "Segoe UI Bold Italic", "Palatino Linotype Bold Italic", "Segoe Script Bold",
        "Ink Free", "Segoe Print",
    ),
    "body": (
        "Arial Regular", "Segoe UI Regular", "Calibri Regular", "Verdana Regular",
        "Tahoma Regular", "Times New Roman Regular",
    ),
    "devanagari_unicode": (
        "Nirmala UI Regular", "Nirmala Text Regular", "Mangal", "Noto Sans Devanagari",
        "Kokila", "Aparajita", "Utsaah", "Lohit", "Nirmala",
    ),
    "kruti": ("Kruti Dev 010", "Kruti", "DevLys", "Chanakya", "Walkman"),
    "symbols": ("Segoe UI Symbol", "Wingdings", "Webdings", "Segoe UI Emoji"),
}

DEVANAGARI_FAMILIES = ("Nirmala", "Mangal", "Kokila", "Aparajita", "Utsaah", "Noto Sans Devan",
                       "Noto Serif Devan", "Lohit", "Sanskrit", "Gargi", "Shree", "Arial Unicode")


def classify_fonts(installed: list[str]) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for role, keys in FONT_ROLES.items():
        found: list[str] = []
        for key in keys:
            for f in installed:
                if key.lower() in f.lower() and f not in found:
                    found.append(f)
        out[role] = found
    return out


def register(mcp, ctx: ServerCtx) -> None:
    @mcp.tool()
    async def convert_unicode_to_kruti(text: str) -> dict:
        """Convert Unicode Hindi (Devanagari) to Kruti Dev 010 keystrokes. Pure text, no
        Scribus needed.

        Returns ``kruti_text`` (the whole string, Hindi runs converted, Latin text
        unchanged), ``segments`` ([{text, kruti}]: ``kruti`` true means that piece must be set
        in the font Kruti Dev 010, the others in a Latin font) and ``roundtrip`` (the
        keystrokes converted back, to eyeball the result). Kruti Dev has no bold or italic.
        Usually you do not need this: ``create_text_box``, ``create_bullet_list``,
        ``create_badge`` and ``set_text_hindi`` convert automatically.
        """
        text = clean_user_text(text)
        full, spans, _ = build_rich_text(text, None, font=None, size_pt=10, color=None)
        segments = [
            {"text": full[sp["start"] : sp["start"] + sp["len"]], "kruti": sp["font"] == KRUTI_SENTINEL}
            for sp in spans
        ]
        rt = "".join(
            from_kruti(s["text"]) if s["kruti"] else s["text"] for s in segments
        )
        return {
            "ok": True, "kruti_text": full, "segments": segments, "has_hindi": has_devanagari(text),
            "roundtrip": rt, "error": None,
        }

    @mcp.tool()
    async def set_text_hindi(
        name: str,
        text: str,
        font_size_pt: float | None = None,
        latin_font: str | None = None,
        color: str | None = None,
        encoding: Literal["kruti", "unicode"] = "kruti",
        unicode_font: str | None = None,
        mode: Mode = "auto",
    ) -> dict:
        """Set the text of an existing frame from Unicode Hindi / English / Hinglish.

        ``encoding="kruti"`` (default, newspaper standard): Devanagari runs are converted to
        Kruti Dev 010 keystrokes and set in that font; Latin runs keep ``latin_font`` (default:
        the frame's current font). ``encoding="unicode"`` keeps real Unicode and sets
        ``unicode_font`` (default: an installed Nirmala/Mangal/Noto Devanagari font).
        Font size defaults to the frame's current size (never below 5 pt). Leading is set to
        automatic. Returns the final text and the fonts used.
        """
        backend = await get_backend(ctx, mode)
        text = clean_user_text(text)
        meta = await backend.script(
            f"import scribus as _s\n_value = {{'font': _s.getFont({name!r}), "
            f"'size': _s.getFontSize({name!r}), 'fonts': _s.getFontNames()}}\n",
            result_expr="_value",
        )
        if not meta.ok:
            return {"ok": False, "error": meta.error}
        cur = meta.value
        base_font = latin_font or cur["font"]
        size = max(5.0, font_size_pt or cur["size"])
        hmode = "auto" if encoding == "kruti" else "unicode"
        ufont = unicode_font
        if encoding == "unicode" and not ufont:
            cls = classify_fonts(cur["fonts"])
            ufont = (cls["devanagari_unicode"] or [None])[0]
            if not ufont:
                return {"ok": False, "error": "no Unicode Devanagari font installed"}
        full, spans, _ = build_rich_text(
            text, None, font=base_font, size_pt=size, color=color, hindi=hmode
        )
        if encoding == "unicode":
            for sp in spans:
                if has_devanagari(full[sp["start"] : sp["start"] + sp["len"]]):
                    sp["font"] = ufont
        spans = [{k: v for k, v in sp.items() if v is not None} for sp in spans]
        script = AD_LIB + f"""
import scribus as _s
_f = {name!r}
_s.setText({full!r}, _f)
_s.setLineSpacingMode(1, _f)
_ad_style(_f, {spans!r}, 1.0, 5.0)
_value = {{"text": _s.getAllText(_f), "warnings": _AD_WARN, "overflows": _ad_overflow(_f)}}
"""
        res = await backend.script(script, result_expr="_value")
        if not res.ok:
            return {"ok": False, "error": res.error}
        return {"ok": True, **(res.value or {}), "error": None}

    @mcp.tool()
    async def suggest_fonts(mode: Mode = "auto") -> dict:
        """Installed fonts grouped by design role, with one recommendation per role.

        Roles: display_condensed (tall bold titles: Impact, Bahnschrift), headline_bold,
        slogan_italic (bold italic / script for taglines), body, devanagari_unicode, kruti
        (legacy Hindi newspaper font; no bold), symbols. Use the exact names returned (e.g.
        "Impact Regular") in ``font=`` arguments; a name that is not installed is reported in
        the ``warnings`` of the tool and NOT applied.
        """
        backend = await get_backend(ctx, mode)
        res = await backend.call("getFontNames")
        if not res.ok:
            return {"ok": False, "error": res.error}
        installed = list(res.value or [])
        roles = classify_fonts(installed)
        return {
            "ok": True,
            "recommended": {r: (v[0] if v else None) for r, v in roles.items()},
            "roles": roles,
            "installed_count": len(installed),
            "notes": [
                "Kruti Dev 010 is a legacy font: set Hindi text only via the Hindi-aware tools "
                "(create_text_box, set_text_hindi ...), never paste Unicode into it.",
                "Press rule: no text below 5 pt.",
            ],
            "error": None,
        }
