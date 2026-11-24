"""Companion files of a template (logos, photos) copied next to a new document.

A template folder holds the .sla (or .sla.gz), two preview pictures (``<name>.png`` and
``<name>tn.png``, or whatever ``template.xml`` names) and the images the .sla frames use. The .sla
stores image paths as ``ImageFileName`` (1.7) / ``PFILE`` (older), normally relative to the
document. ``new_from_template`` writes the document to another folder, so those images must
travel with it, otherwise ``verify_document`` reports ``image_missing``.
"""

from __future__ import annotations

import re
import shutil
from pathlib import Path
from typing import Any

IMAGE_EXT = {".png", ".jpg", ".jpeg", ".svg", ".tif", ".tiff", ".pdf", ".eps", ".psd", ".gif", ".bmp",
             ".webp", ".ai"}
_REF = re.compile(r'(?<![\w])(ImageFileName|PFILE\d?)="([^"]+)"')


def sla_stem(name: str) -> str:
    n = Path(name).name
    for suf in (".sla.gz", ".sla"):
        if n.lower().endswith(suf):
            return n[: -len(suf)]
    return Path(n).stem


def preview_names(sla: Path, preview: str | None = None) -> set[str]:
    """Lower-case file names that are template previews (never copied)."""
    stem = sla_stem(sla.name)
    names = {f"{stem}.png", f"{stem}tn.png"}
    if preview:
        pn = Path(preview).name
        names.add(pn.lower())
        names.add(Path(pn).stem.lower() + "tn.png")
    return {n.lower() for n in names}


def referenced_images(text: str) -> list[str]:
    seen: list[str] = []
    for m in _REF.finditer(text):
        v = m.group(2)
        if v and v not in seen:
            seen.append(v)
    return seen


def _same(a: Path, b: Path) -> bool:
    try:
        return a.stat().st_size == b.stat().st_size and a.read_bytes() == b.read_bytes()
    except OSError:
        return False


def copy_template_assets(text: str, src_sla: Path, dst_sla: Path, preview: str | None = None,
                         ) -> tuple[str, dict[str, Any]]:
    """Copy the images the .sla ``text`` references, and every other image file of the template
    folder, next to ``dst_sla``. Returns ``(new_text, report)``; the text only changes where a
    path had to be rewritten (absolute path, ``..`` path, or a name that is taken by a different
    file in the destination folder). ``report`` has ``copied`` (file names), ``rewritten``
    ({old: new}), ``missing`` (referenced but not found anywhere) and ``warnings``."""
    src_dir, dst_dir = src_sla.parent, dst_sla.parent
    dst_stem = sla_stem(dst_sla.name)
    skip = preview_names(src_sla, preview)
    copied: list[str] = []
    rewritten: dict[str, str] = {}
    missing: list[str] = []
    warns: list[str] = []

    def put(src: Path, rel: str) -> str:
        """Copy ``src`` to dst_dir/rel; returns the relative name actually used."""
        target = dst_dir / rel
        if target.exists() and not _same(src, target):
            rel = f"{dst_stem}_{Path(rel).name}"
            target = dst_dir / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        if not target.exists():
            shutil.copyfile(src, target)
            copied.append(rel.replace("\\", "/"))
        return rel.replace("\\", "/")

    for ref in referenced_images(text):
        p = Path(ref)
        found: Path | None = None
        if p.is_absolute():
            if p.is_file():
                found = p
            elif (src_dir / p.name).is_file():
                found = src_dir / p.name
        else:
            if (src_dir / p).is_file():
                found = src_dir / p
            elif (src_dir / p.name).is_file():
                found = src_dir / p.name
        if found is None:
            missing.append(ref)
            continue
        simple = (not p.is_absolute()) and ".." not in p.parts and (src_dir / p).is_file()
        rel = ref.replace("\\", "/") if simple else found.name
        used = put(found, rel)
        if used != ref:
            rewritten[ref] = used
    for f in sorted(src_dir.iterdir()):
        if (not f.is_file() or f.suffix.lower() not in IMAGE_EXT or f.name.lower() in skip
                or f.name == sla_stem(src_sla.name)):
            continue
        t = dst_dir / f.name
        if f.name in copied or any(Path(c).name == f.name for c in copied):
            continue
        if t.exists():
            continue  # never overwrite an unrelated file; unreferenced companions are optional
        shutil.copyfile(f, t)
        copied.append(f.name)
    new = text
    if rewritten:
        def sub(m: re.Match) -> str:
            return f'{m.group(1)}="{rewritten.get(m.group(2), m.group(2))}"'
        new = _REF.sub(sub, text)
    if missing:
        warns.append("referenced image file(s) not found next to the template: " + ", ".join(missing))
    return new, {"copied": copied, "rewritten": rewritten, "missing": missing, "warnings": warns}
