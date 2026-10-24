"""Unicode <-> Kruti Dev 010 text conversion, for the Scribus AI agent.

Kruti Dev is a legacy (non-Unicode) Hindi font: it draws Latin keystrokes as Devanagari
shapes. Unicode Hindi shown in it appears as empty boxes, so text must be converted to the
keystrokes that make the font draw the right letters.

Rules this module follows, each checked against the glyph chart of Kruti Dev 010:
  * the matra i is typed before its whole consonant cluster,
  * a reph (r + halant before a consonant) is typed after the cluster and its matra,
  * letters that have a half form use it in conjuncts; letters without one use the visible
    halant (always correct Hindi, just less polished),
  * punctuation keys draw Devanagari shapes in this font, so ASCII punctuation is remapped,
  * Latin letters cannot be drawn by the font, so they stay outside the converted runs.

Public functions:
  kruti_runs(text)      -> list of (text, is_kruti)   Hindi runs converted, others unchanged
  kruti_dev(text)       -> str                        the runs joined
  unicode_runs(...)     see from_kruti
  from_kruti(text)      -> str                        best-effort reverse conversion
"""

# --- tables ------------------------------------------------------------------------------

VOWELS = {
    'अ': 'v', 'आ': 'vk', 'इ': 'b', 'ई': 'bZ', 'उ': 'm', 'ऊ': 'Å',
    'ऋ': '_', 'ए': ',', 'ऐ': ',s', 'ओ': 'vks', 'औ': 'vkS',
}

# letter -> (full form, half form or None)
CONS = {
    'क': ('d', 'D'),            # ka
    'ख': ('[k', '['),           # kha
    'ग': ('x', 'X'),            # ga
    'घ': ('?k', '?'),           # gha
    'ङ': ('³', None),      # nga
    'च': ('p', 'P'),            # ca
    'छ': ('N', None),           # cha
    'ज': ('t', 'T'),            # ja
    'झ': ('>', None),           # jha
    'ञ': ('¥', None),      # nya
    'ट': ('V', None),           # tta
    'ठ': ('B', None),           # ttha
    'ड': ('M', None),           # dda
    'ढ': ('<', None),           # ddha
    'ण': ('.k', '.'),           # nna
    'त': ('r', 'R'),            # ta
    'थ': ('Fk', 'F'),           # tha
    'द': ('n', None),           # da
    'ध': ('èk', 'è'),           # dha (the key the operators use; "/k" draws the same letter)
    'न': ('u', 'U'),            # na
    'प': ('i', 'I'),            # pa
    'फ': ('Q', '¶'),       # pha
    'ब': ('c', 'C'),            # ba
    'भ': ('Hk', 'H'),           # bha
    'म': ('e', 'E'),            # ma
    'य': (';', '¸'),       # ya
    'र': ('j', None),           # ra
    'ल': ('y', 'Y'),            # la
    'व': ('o', 'O'),            # va
    'श': ("'k", "'"),           # sha
    'ष': ('"k', '"'),           # ssa
    'स': ('l', 'L'),            # sa
    'ह': ('g', None),           # ha
    'ळ': ('G', None),           # lla
}

# two-letter conjuncts that have their own glyph: (full form, half form or None).
# Checked against the keystrokes in real ad PDFs: kssa is "{k" (a lone "{" is its half form,
# for example in lakshmi), tta is "Ùk" (a lone "Ù" is its half form).
LIGATURES = {
    ('क', 'ष'): ('{k', '{'),       # kssa
    ('ज', 'ञ'): ('K', None),       # jnya
    ('त', 'र'): ('=', None),       # tra
    ('त', 'त'): ('Ùk', 'Ù'),       # tta
    ('श', 'र'): ('J', None),       # shra
    ('द', 'य'): ('|', None),       # dya
    ('द', 'व'): ('}', None),       # dva
    ('द', 'ध'): (')', None),       # ddha
    ('प', 'र'): ('ç', None),       # pra
    ('क', 'त'): ('ä', None),       # kta
}
KRI_KEY = '—'                  # the ligature "kri" (ka + vowel sign ri)

MATRAS = {                           # all typed after the consonant, except i
    'ा': 'k', 'ी': 'h', 'ु': 'q', 'ू': 'w', 'ृ': '`',
    'े': 's', 'ै': 'S', 'ो': 'ks', 'ौ': 'kS', 'ॉ': '‚',
}
I_MATRA = 'ि'                   # typed before the cluster
SIGNS = {'ं': 'a', 'ँ': '¡', 'ः': '%'}     # anusvara, chandrabindu, visarga
HALANT = '्'
NUKTA = '़'
HALANT_KEY = '~'
NUKTA_KEY = '+'
REPH_KEY = 'Z'
RAKAR_KEY = 'z'
RAKAR_FLAT = 'ª'                # rakar under letters with a flat top: tta ttha dda ddha
FLAT_TOP = 'टठडढ'
DANDA = {'।': 'A', '॥': 'AA'}
DEVA_DIGITS = {chr(0x0966 + i): str(i) for i in range(10)}
ZW = '‍‌'

# i-matra and bindu combine into one glyph
I_WITH = {'ं': 'Ç', 'ँ': 'É'}         # i + anusvara, i + chandrabindu
II_WITH = {'ं': 'È', 'ँ': 'Ê'}        # ii + anusvara, ii + chandrabindu

PUNCT = {                            # ASCII punctuation -> the key that draws it in Kruti Dev
    ',': ']', '.': '-', '?': '\\', '!': '!', ':': '%', ';': '(', '(': '¼', ')': '½',
    '-': '&', '/': '@', '+': '$', '=': '¾', '"': 'ß', "'": '*',
    '‘': '*', '’': '*', '“': 'ß', '”': 'ß', '–': '&', '—': '&',
}

# --- run splitting ----------------------------------------------------------------------

def _is_deva(ch):
    return 'ऀ' <= ch <= 'ॿ' or ch in ZW


def _is_neutral(ch):
    return ch.isspace() or ch.isdigit() or ch in PUNCT


def _split_runs(text):
    """Split into (text, is_hindi). Neutral characters (space, digits, punctuation) join the
    run before them, so "Hello, world" stays Latin and "नमस्ते, दुनिया" stays Hindi."""
    runs = []
    current_is = None
    buf = []
    pending = []                     # neutrals at the very start, before any strong character
    for ch in text:
        if _is_deva(ch):
            kind = True
        elif _is_neutral(ch):
            kind = None
        else:
            kind = False
        if kind is None:
            (buf if current_is is not None else pending).append(ch)
            continue
        if current_is is None:
            current_is = kind
            buf = pending + [ch]
            pending = []
        elif kind == current_is:
            buf.append(ch)
        else:
            runs.append((''.join(buf), current_is))
            current_is = kind
            buf = [ch]
    if current_is is None:
        if pending:
            runs.append((''.join(pending), False))
    else:
        runs.append((''.join(buf), current_is))
    return runs


# --- Unicode -> Kruti Dev -----------------------------------------------------------------

def _full(ch, nukta):
    full, half = CONS[ch]
    if not nukta:
        return full
    if half is not None and full == half + 'k':          # nukta goes before the vowel sign k
        return half + NUKTA_KEY + 'k'
    return full + NUKTA_KEY


def _half(ch, nukta):
    full, half = CONS[ch]
    if half is None:
        return _full(ch, nukta) + HALANT_KEY
    return half + (NUKTA_KEY if nukta else '')


def _convert_hindi(s):
    out = []
    i = 0
    n = len(s)
    while i < n:
        ch = s[i]
        if ch in ZW:
            i += 1
            continue
        if ch in DEVA_DIGITS:
            out.append(DEVA_DIGITS[ch]); i += 1; continue
        if ch in DANDA:
            out.append(DANDA[ch]); i += 1; continue
        if ch == '॰':                                              # abbreviation sign, typed as a 0
            out.append('0'); i += 1; continue
        if ch in VOWELS:
            out.append(VOWELS[ch]); i += 1; continue
        if ch in SIGNS:
            out.append(SIGNS[ch]); i += 1; continue
        if ch in MATRAS:
            out.append(MATRAS[ch]); i += 1; continue
        if ch == I_MATRA:
            out.append('f'); i += 1; continue
        if ch == HALANT:
            out.append(HALANT_KEY); i += 1; continue
        if ch == NUKTA:
            out.append(NUKTA_KEY); i += 1; continue
        if ch not in CONS:
            raise ValueError("Cannot convert %r (U+%04X) to Kruti Dev" % (ch, ord(ch)))

        # a syllable: [reph] consonant (halant consonant)* [matra] [signs]
        reph = False
        if ch == 'र' and i + 2 < n and s[i + 1] == HALANT and s[i + 2] in CONS:
            reph = True
            i += 2
        units = []                   # [char, nukta]
        while True:
            c = s[i]
            i += 1
            nukta = i < n and s[i] == NUKTA
            if nukta:
                i += 1
            units.append([c, nukta])
            j = i
            if j < n and s[j] == HALANT:
                j += 1
                while j < n and s[j] in ZW:
                    j += 1
                if j < n and s[j] in CONS:
                    i = j
                    continue
            break
        trailing_halant = False
        if i < n and s[i] == HALANT:
            trailing_halant = True
            i += 1
            while i < n and s[i] in ZW:
                i += 1

        # merge two-letter ligatures, then detect a rakar (halant + ra) at the end
        merged = []
        k = 0
        while k < len(units):
            if k + 1 < len(units) and (units[k][0], units[k + 1][0]) in LIGATURES \
                    and not units[k][1] and not units[k + 1][1]:
                full_key, half_key = LIGATURES[(units[k][0], units[k + 1][0])]
                merged.append(['LIG', full_key, half_key])
                k += 2
            else:
                merged.append(units[k])
                k += 1
        units = merged
        rakar = ''
        if len(units) >= 2 and units[-1][0] == 'र' and not units[-1][1]:
            units.pop()
            rakar = RAKAR_FLAT if units[-1][0] in FLAT_TOP else RAKAR_KEY

        matra = ''
        if i < n and (s[i] in MATRAS or s[i] == I_MATRA):
            matra = s[i]
            i += 1
        signs = []
        while i < n and s[i] in SIGNS:
            signs.append(s[i])
            i += 1

        prefix = ''
        suffix = ''
        if matra == I_MATRA:
            if signs and signs[0] in I_WITH:
                prefix = I_WITH[signs.pop(0)]
            else:
                prefix = 'f'
        elif matra in MATRAS:
            suffix = MATRAS[matra]
            if matra == 'ी' and signs and signs[0] in II_WITH:
                suffix = II_WITH[signs.pop(0)]

        body = []
        for u in units[:-1]:
            if u[0] == 'LIG':
                body.append(u[2] if u[2] else u[1] + HALANT_KEY)   # no half form: full letter + visible halant
            else:
                body.append(_half(u[0], u[1]))
        last = units[-1]
        single_ra = len(units) == 1 and last[0] == 'र' and not last[1] and not rakar
        if single_ra and matra == 'ु':
            body.append('#')
            suffix = ''
        elif single_ra and matra == 'ू':
            body.append(':')
            suffix = ''
        elif last[0] == 'क' and not last[1] and not rakar and matra == 'ृ':
            body.append(KRI_KEY)                                   # kri has its own glyph
            suffix = ''
        else:
            body.append(last[1] if last[0] == 'LIG' else _full(last[0], last[1]))
        body.append(rakar)
        body.append(suffix)
        if reph:
            body.append(REPH_KEY)
        if trailing_halant:
            body.append(HALANT_KEY)
        out.append(prefix + ''.join(body) + ''.join(SIGNS[x] for x in signs))
    return ''.join(out)


def _convert_neutral(s):
    return ''.join(PUNCT.get(ch, ch) for ch in s)


def _convert_run(run):
    """Convert one Hindi run: letters become Kruti Dev keys, and so do the punctuation and
    digits inside it."""
    converted = []
    buf = []
    for ch in run:
        if _is_deva(ch):
            buf.append(ch)
        else:
            if buf:
                converted.append(_convert_hindi(''.join(buf)))
                buf = []
            converted.append(_convert_neutral(ch))
    if buf:
        converted.append(_convert_hindi(''.join(buf)))
    return ''.join(converted)


def kruti_segments(text):
    """Return [(source start, source length, converted text, is_kruti)]. Segments with is_kruti
    True must be set in Kruti Dev; the others are unchanged text."""
    segments = []
    pos = 0
    for run, hindi in _split_runs(text):
        segments.append((pos, len(run), _convert_run(run) if hindi else run, hindi))
        pos += len(run)
    return segments


def kruti_runs(text):
    """Return [(converted text, is_kruti)]. Runs with is_kruti True must be set in Kruti Dev."""
    return [(converted, is_kruti) for _, _, converted, is_kruti in kruti_segments(text)]


def kruti_dev(text):
    return ''.join(t for t, _ in kruti_runs(text))


# --- Kruti Dev -> Unicode ------------------------------------------------------------------

_HALF = {h: ch for ch, (f, h) in CONS.items() if h is not None}
_HALF.update({'/': 'ध', '”': 'श'})              # other keys that draw the same half letters
_FULL = {f: ch for ch, (f, h) in CONS.items()}
_FULL.update({'/k': 'ध', '”k': 'श'})
_LIG = {full: a + HALANT + b for (a, b), (full, half) in LIGATURES.items()}
_LIG[KRI_KEY] = 'क' + 'ृ'
_HALF_LIG = {half: a + HALANT + b for (a, b), (full, half) in LIGATURES.items() if half}
_REV_VOWELS = {v: k for k, v in VOWELS.items()}
_REV_MATRAS = {v: k for k, v in MATRAS.items()}
_REV_SIGNS = {v: k for k, v in SIGNS.items()}
_REV_DANDA = {'AA': '॥', 'A': '।'}
_REV_PUNCT = {'\\': '?', ']': ',', '-': '.', '(': ';', '¼': '(', '½': ')', '&': '-',
              '@': '/', '$': '+', '¾': '=', 'ß': '"', '*': "'"}
_REV_I = {'f': '', 'Ç': 'ं', 'É': 'ँ'}      # prefix i -> bindu it carries
_REV_II = {'È': 'ं', 'Ê': 'ँ'}              # ii with bindu
_REV_RAKAR = (RAKAR_KEY, RAKAR_FLAT)
_BY_LENGTH = lambda table: sorted(table, key=len, reverse=True)
_FULL_KEYS = _BY_LENGTH(list(_FULL) + list(_LIG))
_VOWEL_KEYS = _BY_LENGTH(_REV_VOWELS)
_MATRA_KEYS = _BY_LENGTH(_REV_MATRAS)


# Words that end in a visarga. In Kruti Dev a visarga and a colon are the same key, so when
# converting back, a % after a letter is a visarga only inside a word or at the end of one of these.
_VISARGA_WORDS = ('अतः', 'प्रातः', 'पुनः',
                  'स्वतः', 'प्रायः',
                  'मुख्यतः', 'विशेषतः',
                  'सामान्यतः', 'अंततः',
                  'वस्तुतः', 'सर्वतः',
                  'मूलतः', 'पूर्णतः',
                  'नमः', 'मनः', 'यशः', 'तपः',
                  'आयुः', 'तेजः', 'ओजः')
_VISARGA_KRUTI = None
_LETTER_KEYS = None


def _is_visarga(text, j):
    """text[j] is a % that follows a letter: visarga (True) or colon (False)?"""
    global _VISARGA_KRUTI, _LETTER_KEYS
    if _VISARGA_KRUTI is None:
        _VISARGA_KRUTI = set(kruti_dev(word) for word in _VISARGA_WORDS)
        keys = list(_FULL) + list(_HALF) + list(_LIG) + list(_HALF_LIG) + list(_REV_VOWELS) + list(_REV_MATRAS)
        _LETTER_KEYS = set(key[0] for key in keys)
    if j + 1 < len(text) and (text[j + 1].isalpha() or text[j + 1] in _LETTER_KEYS) and not text[j + 1].isspace():
        return True                                # inside a word: duhkh
    start = j
    while start > 0 and not text[start - 1].isspace():
        start -= 1
    return text[start:j + 1] in _VISARGA_KRUTI


def _match(text, i, keys):
    for key in keys:
        if text.startswith(key, i):
            return key
    return None


def _read_syllable(text, i):
    """Read one consonant syllable starting at i. Returns (unicode text, next index) or None."""
    n = len(text)
    j = i
    prefix_bindu = None
    if text[j] in _REV_I:
        prefix_bindu = _REV_I[text[j]]
        j += 1
    units = []
    complete = False
    while j < n:
        if text[j] in '#:' and not units:
            # ru / ruu
            matra = 'ु' if text[j] == '#' else 'ू'
            return 'र' + ('ि' if prefix_bindu is not None else '') + matra, j + 1
        # full forms first: "[k" (kha) must not be read as half kha + the vowel sign k
        key = _match(text, j, _FULL_KEYS)
        if key is None:
            if text[j] in _HALF_LIG:                # half form of a conjunct, for example kssa before ma
                units.append(_HALF_LIG[text[j]] + HALANT)
                j += 1
                continue
            if text[j] in _HALF:
                c = _HALF[text[j]]
                j += 1
                if j < n and text[j] == NUKTA_KEY:
                    c += NUKTA
                    j += 1
                units.append(c + HALANT)
                continue
            break
        base = _LIG[key] if key in _LIG else _FULL[key]
        j += len(key)
        if j < n and text[j] == NUKTA_KEY:
            base += NUKTA
            j += 1
        units.append(base)
        complete = True
        break
    if not units:
        return None
    cluster = ''.join(units)
    while j < n and text[j] in _REV_RAKAR:
        cluster += HALANT + 'र'
        j += 1

    matra = ''
    signs = ''
    if prefix_bindu is not None:
        matra = I_MATRA
        signs = prefix_bindu
    elif j < n and text[j] in _REV_II:
        matra = 'ी'
        signs = _REV_II[text[j]]
        j += 1
    else:
        key = _match(text, j, _MATRA_KEYS)
        if key is not None:
            matra = _REV_MATRAS[key]
            j += len(key)
    reph = ''
    if j < n and text[j] == REPH_KEY:
        reph = 'र' + HALANT
        j += 1
    while j < n and text[j] in _REV_SIGNS:
        if text[j] == '%' and not _is_visarga(text, j):
            break                                  # a colon, left for from_kruti()
        signs += _REV_SIGNS[text[j]]
        j += 1
    if complete and j < n and text[j] == HALANT_KEY:
        cluster += HALANT
        j += 1
    return reph + cluster + matra + signs, j


def from_kruti(text):
    """Convert Kruti Dev keystrokes back to Unicode. Exact for text made by kruti_dev(), best
    effort for text typed by someone else. In Kruti Dev a colon and a visarga are the same key,
    so a colon that directly follows a letter comes back as a visarga."""
    out = []
    i = 0
    n = len(text)
    while i < n:
        syllable = _read_syllable(text, i)
        if syllable is not None:
            out.append(syllable[0])
            i = syllable[1]
            continue
        key = _match(text, i, _VOWEL_KEYS)
        if key is not None:
            out.append(_REV_VOWELS[key])
            i += len(key)
            continue
        key = _match(text, i, _MATRA_KEYS)
        if key is not None:
            out.append(_REV_MATRAS[key])
            i += len(key)
            continue
        if text.startswith('AA', i):
            out.append('॥')
            i += 2
            continue
        ch = text[i]
        if ch == 'A':
            out.append('।')
        elif ch == '%':
            out.append(':')                      # a lone % (after a space or digit) is a colon
        elif ch in _REV_SIGNS:
            out.append(_REV_SIGNS[ch])
        elif ch == HALANT_KEY:
            out.append(HALANT)
        elif ch == NUKTA_KEY:
            out.append(NUKTA)
        elif ch in _REV_PUNCT:
            out.append(_REV_PUNCT[ch])
        elif ch.isdigit():
            out.append(ch)
        else:
            out.append(ch)
        i += 1
    return ''.join(out)
