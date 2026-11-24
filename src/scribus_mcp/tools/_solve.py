"""Script-side solver that fits text into a frame (or a chain of linked frames) by calculation.

``SOLVER_LIB`` is Scribus-side source that tools append after ``AD_LIB`` (it uses ``_ad_style``,
``_ad_overflow`` ...). It searches (bisection, about 8-10 layouts) against Scribus' own layout
(``layoutText`` + ``textOverflows`` + ``getTextLines``) instead of guessing, within the press
limits: font size >= ``min_pt`` (5 pt), leading >= ``min_ratio`` x font size (1.05).

``_sv_solve(P)`` parameters (a dict, build it with :func:`solve_params`):

========== ===================================================================================
chain      frame names the text flows through (one name for a normal frame)
spans      style spans from ``build_rich_text`` / ``_sv_spans_of`` (sizes are the BASE sizes)
fit        'none' (keep sizes) | 'shrink' (<= base) | 'fill' (largest that fits, capped by max_pt)
           | 'leading' (keep sizes, solve the largest leading that fits)
lead       fixed leading in pt, or None
ratio      leading / size when ``lead`` is None; None = automatic leading (Scribus decides)
target_lines  N: largest size whose text needs <= N lines (plus no overflow)
spread     with target_lines: afterwards raise the leading so the lines span the frame height
block      body-block mode: after the fit, spread the leading (up to ``block_ratio`` x size) so the
           text fills the chain; result gets ``tail_lines`` / ``tail_empty`` for a linked chain
========== ===================================================================================

Result dict: ``size_pt`` (largest run), ``leading_pt``, ``lines``, ``overflow``, ``tries``,
``scale``, ``notes``. The search keeps leading in fixed mode (``setLineSpacingMode(0)``) so
Scribus does not reset it while the font size changes, and temporarily forces top vertical
alignment (bottom/middle alignment confuses ``textOverflows``).
"""

from __future__ import annotations

from typing import Any

SOLVER_LIB = r'''
_AD_REMOVED = []

def _sv_chain(_f):
    import scribus as __s
    _c = [_f]
    try:
        _n = __s.getNextLinkedFrame(_f)
        while _n and _n not in _c:
            _c.append(_n)
            _n = __s.getNextLinkedFrame(_n)
    except Exception:
        pass
    return _c

def _sv_pt(_v):
    import scribus as __s
    return _v / __s.pointsToDocUnit(1.0)

def _sv_overflow(_chain):
    import scribus as __s
    try:
        __s.layoutTextChain(_chain[0])
    except Exception:
        try:
            __s.layoutText(_chain[0])
        except Exception:
            pass
    try:
        if bool(__s.textOverflows(_chain[-1], 1)):
            return True
    except Exception:
        return False
    try:
        if __s.getTextLength(_chain[0]) > 0 and _sv_lines(_chain) == 0:
            return True
    except Exception:
        pass
    return False

def _sv_lines(_chain):
    import scribus as __s
    _n = 0
    for _c in _chain:
        try:
            _n += int(__s.getTextLines(_c))
        except Exception:
            pass
    return _n

def _sv_bisect(_ok, _lo, _hi):
    # largest integer k in [lo, hi] with _ok(k), assuming _ok is monotone; returns (k or None, tries)
    _tries = 1
    if _ok(_hi):
        return _hi, _tries
    _tries += 1
    if not _ok(_lo):
        return None, _tries
    while _hi - _lo > 1:
        _mid = (_lo + _hi) // 2
        _tries += 1
        if _ok(_mid):
            _lo = _mid
        else:
            _hi = _mid
    return _lo, _tries

def _sv_sizes(_spans, _sc, _min):
    return [max(_min, round(_sp['size'] * _sc * 4) / 4.0) for _sp in _spans if _sp.get('len', 1) > 0]

def _sv_set_leading(_chain, _lead):
    import scribus as __s
    for _c in _chain:
        __s.setLineSpacingMode(0, _c)
        __s.setLineSpacing(_lead, _c)

def _sv_apply(_P, _sc, _lead_override=None):
    import scribus as __s
    _chain = _P['chain']
    _ad_style(_chain[0], _P['spans'], _sc, _P['min_pt'])
    _sz = max(_sv_sizes(_P['spans'], _sc, _P['min_pt']) or [_P['min_pt']])
    if _P.get('ratio') is None and _P.get('lead') is None and _lead_override is None:
        for _c in _chain:
            __s.setLineSpacingMode(1, _c)
        return _sz, None
    if _lead_override is not None:
        _l = _lead_override
    elif _P.get('lead') is not None:
        _l = float(_P['lead'])
    else:
        _l = float(_P['ratio']) * _sz
    _l = max(_l, _P['min_ratio'] * _sz)
    _sv_set_leading(_chain, _l)
    return _sz, _l

def _sv_inner_h(_f):
    import scribus as __s
    _w, _h = __s.getSize(_f)
    try:
        _d = __s.getTextDistances(_f)
        return _sv_pt(_h) - _sv_pt(_d[2]) - _sv_pt(_d[3])
    except Exception:
        return _sv_pt(_h)

def _sv_solve(_P):
    import scribus as __s
    _chain = _P['chain']
    _spans = _P['spans']
    _notes = []
    _va = {}
    for _c in _chain:
        try:
            _va[_c] = __s.getTextVerticalAlignment(_c)
            __s.setTextVerticalAlignment(0, _c)
        except Exception:
            pass
    _maxsz = max([_sp['size'] for _sp in _spans] or [10.0])
    if _P.get('ratio') is None and _P.get('lead') is None and (_P.get('fit') == 'leading' or _P.get('spread') or _P.get('block')):
        _P['ratio'] = 1.2
    _min = _P['min_pt']
    _fit = _P.get('fit', 'shrink')
    _tl = _P.get('target_lines')
    _tl0 = _tl
    _target_missed = False
    _mr = _P['min_ratio']
    _tries = [0]
    _hi = {'none': 1.0, 'shrink': 1.0, 'leading': 1.0, 'fill': (_P.get('max_pt') or 200.0) / _maxsz}[_fit]
    _hi = min(_hi, 512.0 / _maxsz)
    if _P.get('lead') is not None:
        _cap = (float(_P['lead']) / _mr - 0.13) / _maxsz
        if _cap < _hi:
            _hi = _cap
            _notes.append('font limited so that leading >= %.2f x size' % _mr)
    _lo = _min / _maxsz
    if _hi < _lo:
        _lo = _hi
    def _ok(_sc):
        _tries[0] += 1
        _sv_apply(_P, _sc)
        if _sv_overflow(_chain):
            return False
        if _tl and _sv_lines(_chain) > _tl:
            return False
        return True
    _scale = _hi
    if _fit == 'none':
        _sv_apply(_P, min(1.0, _hi))
        _scale = min(1.0, _hi)
        _sv_overflow(_chain)
    elif _fit == 'leading':
        _sv_apply(_P, 1.0)
        _scale = 1.0
    else:
        _khi = int(_hi * _maxsz * 4 + 1e-6)
        _klo = max(1, int(_lo * _maxsz * 4 + 0.999999))
        if _khi < _klo:
            _klo = _khi
        _k, _t = _sv_bisect(lambda _k: _ok(_k / (4.0 * _maxsz)), _klo, _khi)
        if _k is None and _tl:
            # the line target cannot be met: fall back to the largest size that merely fits
            _tl = None
            _k, _t = _sv_bisect(lambda _k: _ok(_k / (4.0 * _maxsz)), _klo, _khi)
            _target_missed = True
        if _k is None:
            _scale = _klo / (4.0 * _maxsz)
            _sv_apply(_P, _scale)
            _notes.append('does not fit even at the minimum size: shorten the text or enlarge the frame')
        else:
            _scale = _k / (4.0 * _maxsz)
            _sv_apply(_P, _scale)
    _sz, _l = _sv_apply(_P, _scale)
    _ov = _sv_overflow(_chain)
    # leading: solve the largest leading that still fits (fit == 'leading'), or spread the
    # lines over the frame height (target_lines + spread)
    if (_fit == 'leading' or (_tl and _P.get('spread'))) and _P.get('lead') is None and not _ov:
        _lines_now = _sv_lines(_chain)
        _top = _P.get('max_ratio', 1.6) * _sz
        if _fit == 'leading':
            _lead0 = _mr * _sz
        else:
            _lead0 = max(_l if _l is not None else 0.0, _mr * _sz)
            if _lines_now > 0 and len(_chain) == 1:
                _top = min(_top, _sv_inner_h(_chain[0]) / float(_lines_now))
        def _okl(_x):
            _tries[0] += 1
            _sv_apply(_P, _scale, _x)
            if _sv_overflow(_chain):
                return False
            if _tl and _sv_lines(_chain) > _tl:
                return False
            return True
        _best = _lead0
        if _top > _lead0 + 0.01:
            _k2, _t2 = _sv_bisect(lambda _k: _okl(_k / 20.0), int(_lead0 * 20) + 1, int(_top * 20))
            if _k2 is not None:
                _best = _k2 / 20.0
        _sv_apply(_P, _scale, max(_best, _lead0))
    if _P.get('block') and not _ov and _fit in ('fill', 'shrink'):
        # fill the chain: the largest leading (<= block_ratio x size) that still lays out without
        # overflow, so the last lines land in the continuation frame and no rows stay empty
        _lead0 = max(_l if _l is not None else 0.0, _mr * _sz)
        _top = _P.get('block_ratio', 1.5) * _sz
        def _okb(_x):
            _tries[0] += 1
            _sv_apply(_P, _scale, _x)
            return not _sv_overflow(_chain)
        _best = _lead0
        if _top > _lead0 + 0.01:
            _k3, _t3 = _sv_bisect(lambda _k: _okb(_k / 20.0), int(_lead0 * 20) + 1, int(_top * 20))
            if _k3 is not None:
                _best = _k3 / 20.0
        _sv_apply(_P, _scale, _best)
    try:
        _l = __s.getLineSpacing(_chain[0])
    except Exception:
        pass
    _ov = _sv_overflow(_chain)
    _ln = _sv_lines(_chain)
    for _c in _chain:
        if _c in _va:
            try:
                __s.setTextVerticalAlignment(_va[_c], _c)
            except Exception:
                pass
    _tail = None
    if len(_chain) > 1:
        _tail = _sv_lines([_chain[-1]])
    _blank = None
    try:
        if _l:
            _blank = sum(_sv_inner_h(_c) for _c in _chain) - _ln * _l
    except Exception:
        pass
    if _ov:
        _notes.append('text overflows the frame')
    if _tl0 and _ln != _tl0 and not _ov:
        _notes.append('target_lines %d not reachable: %d lines at the best size that fits' % (_tl0, _ln))
    return {'size_pt': round(_sz, 2), 'leading_pt': round(_l, 2) if _l is not None else None,
            'lines': _ln, 'overflow': bool(_ov), 'tries': _tries[0], 'scale': round(_scale, 4),
            'target_lines': _tl0, 'target_met': (not _tl0) or (_ln == _tl0 and not _ov), 'notes': _notes,
            'tail_lines': _tail, 'tail_empty': bool(_tail is not None and _tail == 0 and not _ov),
            'blank_pt': round(_blank, 1) if _blank is not None else None}

def _sv_make_beside(_a, _sig, _gap_mm):
    # body frame _a stops above the signature frame _sig; a second frame, linked to _a, takes
    # the left part of the signature rows: the last lines of the body sit beside the signature
    # and no two frames overlap
    import scribus as __s
    _u = __s.pointsToDocUnit(1.0)
    _mm = 72.0 / 25.4 * _u
    _ax, _ay = __s.getPosition(_a)
    _aw, _ah = __s.getSize(_a)
    _sx, _sy = __s.getPosition(_sig)
    _sw, _sh = __s.getSize(_sig)
    _bn = _a + '_last'
    _bw = _sx - _gap_mm * _mm - _ax
    if _bw < 10 * _mm:
        raise ValueError('the signature frame leaves less than 10 mm on the left for the last lines')
    if _sy < _ay + 5 * _mm:
        raise ValueError('the signature frame must lie below the top of the body frame')
    _bh = max(_sh, _ay + _ah - _sy)
    __s.sizeObject(_aw, _sy - _ay, _a)
    _removed = []
    # a template's own 'last line' frame inside the new area is replaced by the linked frame
    for _it in (__s.getPageItems() or []):
        _n, _ty = _it[0], _it[1]
        if _ty != 4 or _n in (_a, _sig, _bn):
            continue
        _x, _y = __s.getPosition(_n)
        _w, _h = __s.getSize(_n)
        _ox = min(_x + _w, _ax + _bw) - max(_x, _ax)
        _oy = min(_y + _h, _sy + _bh) - max(_y, _sy)
        if _ox > 0 and _oy > 0 and _ox * _oy >= 0.6 * min(_w * _h, _bw * _bh):
            try:
                __s.deleteObject(_n)
                _removed.append(_n)
            except Exception:
                pass
    _AD_REMOVED.extend(_removed)
    if __s.objectExists(_bn):
        __s.moveObjectAbs(_ax, _sy, _bn)
        __s.sizeObject(_bw, _bh, _bn)
    else:
        _b = __s.createText(_ax, _sy, _bw, _bh, _bn)
        __s.setFillColor('None', _b)
        __s.setLineColor('None', _b)
        try:
            _d = __s.getTextDistances(_a)
            __s.setTextDistances(_d[0], _d[1], _d[2], _d[3], _b)
        except Exception:
            pass
        try:
            __s.linkTextFrames(_a, _b)
        except Exception:
            pass
    return [_a, _bn]

def _sv_spans_of(_f):
    # size spans of the text now in the frame; paragraph separators carry the frame default size
    # (12 pt), not the text's, so they take the size of the character before them
    import scribus as __s
    _n = __s.getTextLength(_f)
    try:
        _t = __s.getAllText(_f)
    except Exception:
        _t = ''
    if len(_t) != _n:
        _t = ''
    _sizes = []
    for _i in range(_n):
        if _t and ord(_t[_i]) in (13, 10, 8233, 11, 12):
            _sizes.append(None)
            continue
        __s.selectText(_i, 1, _f)
        _sizes.append(round(__s.getFontSize(_f), 2))
    __s.selectText(0, 0, _f)
    _known = [_x for _x in _sizes if _x is not None]
    if not _known:
        return []
    _prev = _known[0]
    for _i in range(_n):
        if _sizes[_i] is None:
            _sizes[_i] = _prev
        else:
            _prev = _sizes[_i]
    _spans = []
    _i = 0
    while _i < _n:
        _j = _i + 1
        while _j < _n and _sizes[_j] == _sizes[_i]:
            _j += 1
        _spans.append({'start': _i, 'len': _j - _i, 'size': _sizes[_i]})
        _i = _j
    return _spans
'''


def solve_params(
    chain: list[str],
    spans: list[dict[str, Any]],
    *,
    fit: str = "shrink",
    min_pt: float = 5.0,
    max_pt: float | None = None,
    leading_pt: float | None = None,
    leading_ratio: float | None = None,
    target_lines: int | None = None,
    spread: bool | None = None,
    min_ratio: float = 1.05,
    max_ratio: float = 1.6,
    block: bool = False,
    block_ratio: float = 1.5,
) -> dict[str, Any]:
    """Build the parameter dict for ``_sv_solve`` (clamps to the press limits)."""
    if fit not in ("none", "shrink", "fill", "leading"):
        raise ValueError(f"fit must be none|shrink|fill|leading, not {fit!r}")
    min_pt = max(5.0, float(min_pt))
    min_ratio = max(1.0, float(min_ratio))
    if leading_pt is not None:
        leading_pt = max(float(leading_pt), min_ratio * min_pt)
    if target_lines is not None:
        target_lines = max(1, int(target_lines))
        if spread is None:
            spread = leading_pt is None
    p: dict[str, Any] = {
        "chain": list(chain), "spans": spans, "fit": fit, "min_pt": min_pt,
        "max_pt": min(512.0, float(max_pt)) if max_pt else None,
        "lead": leading_pt, "ratio": None if leading_pt is not None else leading_ratio,
        "target_lines": target_lines, "spread": bool(spread), "min_ratio": min_ratio,
        "max_ratio": max_ratio, "block": bool(block), "block_ratio": float(block_ratio),
    }
    return p
