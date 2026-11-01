"""Inline font-run markup for ``fill_template_fields`` (pure Python, unit-tested).

Syntax (one tag opens a run, ``{/}`` closes the innermost one)::

    {font=Arial Bold,size=9}-:{/} {font=Kruti Dev 010 Regular}Unicode Hindi here{/} {bold,color=Red}:-{/}

Tag options, comma separated, all optional:

* ``font=NAME``   exact Scribus font name ("Arial Bold", "Kruti Dev 010 Regular"); a close name
  is resolved inside Scribus (case-insensitive, "Arial" finds "Arial Regular").
* ``size=PT``     font size of the run in points.
* ``color=NAME``  a colour name known to the document (or ``#RRGGBB``).
* ``bold`` / ``italic``  use the bold / italic face of the current font family when installed.
* ``scale=PCT``   horizontal glyph scale in percent.

Runs nest: an inner tag inherits what the outer ones set. Text outside any tag keeps the field's
default style. ``{{`` and ``}}`` write a literal brace; a brace group that is not a valid tag
(``{foo}``) stays literal text, so ordinary text with braces is safe. A tag may span paragraphs
(newlines); it is closed at the end of the text if the closing ``{/}`` is missing (reported as a
warning). Unicode Hindi inside any run is converted to Kruti Dev keystrokes by the caller
(``build_rich_text``), so write Hindi as plain Unicode. Write ऑ as आ + ॉ if you can (the
converter now also accepts ऑ itself).
"""

from __future__ import annotations

import re
from typing import Any

_KEYS = {"font", "size", "color", "colour", "bold", "italic", "scale"}
_OPT = r"[A-Za-z_]+(?:=[^,{}]*)?"
_TAG = re.compile(r"\{(" + _OPT + r"(?:\s*,\s*" + _OPT + r")*)\}")
_TOKEN = re.compile(r"\{\{|\}\}|\{/\}|" + _TAG.pattern)


def has_markup(text: str) -> bool:
    """True if ``text`` contains at least one valid run tag."""
    for m in _TOKEN.finditer(text or ""):
        if m.group(0) in ("{{", "}}"):
            continue
        if m.group(0) == "{/}" or _valid(m.group(1)):
            return True
    return False


def _parse_opts(body: str) -> dict[str, Any] | None:
    out: dict[str, Any] = {}
    for part in body.split(","):
        part = part.strip()
        if not part:
            continue
        key, eq, val = part.partition("=")
        key = key.strip().lower()
        val = val.strip()
        if key not in _KEYS:
            return None
        if key in ("bold", "italic"):
            out[key] = (val.lower() not in ("0", "false", "no")) if eq else True
        elif key in ("size", "scale"):
            try:
                out["size_pt" if key == "size" else "h_scale"] = float(val)
            except ValueError:
                return None
        elif key in ("color", "colour"):
            if not val:
                return None
            out["color"] = val
        else:  # font
            if not val:
                return None
            out["font"] = val
    return out or None


def _valid(body: str) -> bool:
    return _parse_opts(body) is not None


def parse_markup(text: str) -> tuple[list[dict[str, Any]], list[str]]:
    """Split ``text`` into runs ``[{text, font?, size_pt?, color?, bold?, italic?, h_scale?}]``.

    Returns ``(runs, warnings)``. Text without markup gives a single run ``[{text}]``.
    Adjacent runs with identical style are merged.
    """
    warnings: list[str] = []
    stack: list[dict[str, Any]] = []
    runs: list[dict[str, Any]] = []
    pos = 0

    def style() -> dict[str, Any]:
        cur: dict[str, Any] = {}
        for layer in stack:
            cur.update(layer)
        return cur

    def emit(chunk: str) -> None:
        if not chunk:
            return
        st = style()
        if runs and {k: v for k, v in runs[-1].items() if k != "text"} == st:
            runs[-1]["text"] += chunk
        else:
            runs.append({"text": chunk, **st})

    text = text or ""
    for m in _TOKEN.finditer(text):
        tok = m.group(0)
        if tok in ("{{", "}}"):
            emit(text[pos:m.start()] + tok[0])
            pos = m.end()
            continue
        if tok == "{/}":
            emit(text[pos:m.start()])
            pos = m.end()
            if stack:
                stack.pop()
            else:
                warnings.append("unmatched {/} ignored")
            continue
        opts = _parse_opts(m.group(1))
        if opts is None:
            continue  # looks like a tag but is not valid: stays literal text
        emit(text[pos:m.start()])
        pos = m.end()
        stack.append(opts)
    emit(text[pos:])
    if stack:
        warnings.append(f"{len(stack)} run tag(s) not closed with {{/}}; closed at the end of the text")
    if not runs:
        runs = [{"text": ""}]
    return runs, warnings


def strip_markup(text: str) -> str:
    """The plain text of ``text`` without tags."""
    runs, _ = parse_markup(text)
    return "".join(r["text"] for r in runs)
