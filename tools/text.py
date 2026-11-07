"""EEX strings <-> translation segments, and the English encoder.

A string operand of the event scripts (eex.py) is split into segments:
  op 0x27 dialogue  '&Speaker\\ntext\\n&Speaker\\ntext' -> one segment per speech; the speaker
                    header (a DATA.E3 record name) stays as it is for now and is not part of
                    the translation
  op 0x27 credits   '$&Role\\n\\n\\nNames' (R_29; already English) -> one segment, '$&' kept
  every other op    the whole string (a trailing newline is kept)

English (tl/): plain ASCII; '\\n' forces a line break, a blank line = '\\n\\n'. build wraps every
line at the width of its op (WIDTH, in pixels of the proportional font, vwf.py). Typographic quotes,
dashes and ellipses are folded to ASCII; '&', '\\' (other than \\n), '%' and '{' are refused.
"""
import os, re, sys

sys.path.insert(0, os.path.dirname(__file__))
from vwf import width as pixels

# pixels per line, by op; (pixels, bytes) where a line also has a byte limit; None = no wrapping.
# dialogue (0x27): 12-px font, the line builder's 26 columns of 6 px (box 0x8003e0bc 176 wide).
# captions (0x29 places/chapter cards): caption 0x8003f4e4, 16-px font, box sized to the widest
# line, rows of at most 38 bytes. Episode titles (0x2a/0x2b): one line only (box 0x8004336c,
# 16-px, sized to the text): not wrapped, tl.py warns over TITLE_PX. narration (0x28): fixed
# 16-px box, text x 40..280 -> 240 px, 6 lines a page (session 5). goals (0x2c: R one-line
# objectives, S victory/defeat conditions): message window 0x8003f828 (box sized to the widest
# line, vwf msgw), not wrapped; limits() = errors: GOAL_BYTES (strlen < 250 or the view says
# 'cannot display'; buffer 0x180 in the save data), GOAL_LINES (window height), GOAL_PX (box
# W + 32 <= 320). choices (0x12): box sized bytes * 8 (not patched) -> CHOICE_BYTES per line
# (Japanese max 26), not wrapped.
CAPTION = (280, 38)
TITLE_PX = 280
GOAL_BYTES, GOAL_LINES, GOAL_PX = 249, 10, 280
CHOICE_BYTES = 26
WIDTH = {0x27: 160, 0x28: 240, 0x29: CAPTION, 0x2a: None, 0x2b: None, 0x2c: None, 0x12: None}
# lines per page of the auto-paging boxes: the Japanese pads with blank lines to start a new
# page (dialogue: blank runs end at line 3k; narration at 6, 12, 24), so build turns every
# blank-line paragraph break into padding up to the next page.
PAGE = {0x27: 3, 0x28: 6}
# boxes whose auto-paging ends a page at the last sentence end on it rather than mid-sentence
# (when that still leaves SENT_MIN lines on the page)
SENT_PAGE = {0x28}
SENT_MIN = 2
# numbered list item ('  2. ', 'Victory: 1. '): wrapped lines hang under the item text
_ITEM = re.compile(r' *(?:[A-Z][A-Za-z ()]*: )?\d+\. ')
MIDSENT = []                # pages that had to end mid-sentence (one sentence > a page): tl.py midsent
_SENT_END = re.compile(r'^(?!\d\.$).+[.!?][)"\']*$')       # not a list number '2.'
KIND = {0x12: 'choice', 0x27: 'talk', 0x28: 'narr', 0x29: 'place', 0x2a: 'title',
        0x2b: 'title2', 0x2c: 'goal'}
FOLD = {'‘': "'", '’': "'", '“': '"', '”': '"', '—': '--', '–': '-',
        '…': '...', ' ': ' ',
        'ō': '^', 'ū': '~', 'Ō': '|', 'Ū': '`'}   # macron vowels: pixfont.MACRONS
_SPEECH = re.compile(r'\n(?=&)')


def decode(b):
    return b.decode('cp932')


def segments(op, s):
    """Japanese string (str) -> (list of segment texts, template). The template rebuilds the
    string from English segments: build(template, [en...])."""
    if op == 0x27 and s.startswith('$&'):
        return [s[2:]], ('prefix', '$&', '')
    if op == 0x27:
        heads, segs, tails = [], [], []
        for sp in _SPEECH.split(s):
            head, _, body = sp.partition('\n')
            assert head.startswith('&'), repr(sp)
            core = body.rstrip('\n')
            heads.append(head)
            segs.append(core)
            tails.append(body[len(core):])
        return segs, ('talk', heads, tails)
    tail = s[len(s.rstrip('\n')):]
    return [s[:len(s) - len(tail)]], ('prefix', '', tail)


def join(tmpl, segs):
    if tmpl[0] == 'talk':
        return '\n'.join(h + '\n' + t + z for h, t, z in zip(tmpl[1], segs, tmpl[2]))
    return tmpl[1] + segs[0] + tmpl[2]


def check(en):
    """-> list of problems with an English segment."""
    errs = []
    s = fold(en)
    bad = sorted(set(c for c in s if not (' ' <= c <= '~')))
    if bad:
        errs.append('non-ASCII characters %r' % ''.join(bad))
    if re.search(r'[&%{}]|\\(?!n)', s):
        errs.append("reserved character (& %% { } or \\ other than \\n)")
    if re.search(r'[\^~|`]', en):
        errs.append('reserved character (^ ~ | ` are the macron letters in the font)')
    return errs


def limits(op, en):
    """-> list of hard size problems of an English segment of op (unwrapped boxes)."""
    lines = fold(en).split('\\n')
    errs = []
    if op == 0x2c:
        n = len('\n'.join(lines))
        if n > GOAL_BYTES:
            errs.append('goal %d bytes > %d' % (n, GOAL_BYTES))
        if len(lines) > GOAL_LINES:
            errs.append('goal %d lines > %d' % (len(lines), GOAL_LINES))
        errs += ['goal line %d px > %d' % (pixels(l), GOAL_PX) for l in lines if pixels(l) > GOAL_PX]
    elif op == 0x12:
        errs += ['choice line %d bytes > %d' % (len(l), CHOICE_BYTES) for l in lines
                 if len(l) > CHOICE_BYTES]
    return errs


def fold(en):
    return ''.join(FOLD.get(c, c) for c in en)


def _para(p):
    """forced-break paragraph -> word list; leading spaces (list indents) stay on the first word"""
    words = p.split()
    if words and p[0] == ' ':
        words[0] = ' ' * (len(p) - len(p.lstrip(' '))) + words[0]
    return words


def fits(s, width):
    """width: pixels, or (pixels, bytes), or None (no limit)"""
    if width is None:
        return True
    if isinstance(width, tuple):
        return pixels(s) <= width[0] and len(s) <= width[1]
    return pixels(s) <= width


def _lines(words, width):
    """one paragraph (word list) -> list of word lists, one per line"""
    if fits(' '.join(words), width):
        return [words]
    m = _ITEM.match(' '.join(words))
    hang = ' ' * round(pixels(m.group()) / pixels(' ')) if m else ''
    out, line = [], []
    for w in words:
        if line and not fits(' '.join(line + [w]), width):
            out.append(line)
            line = [hang + w]
        else:
            line.append(w)
    out.append(line)
    return out


def _sent_pages(paras, width, page):
    """paragraphs of one block (word lists) -> lines, padded so that no page ends mid-sentence
    when the page holds an earlier sentence end (after its first SENT_MIN lines)"""
    out = []
    paras = [list(p) for p in paras]
    while paras:
        lines, src = [], []                       # src: (paragraph index, words before the line end)
        for i, p in enumerate(paras):
            n = 0
            for ln in _lines(p, width):
                n += len(ln)
                lines.append(ln)
                src.append((i, n))
        if len(lines) <= page:
            out += [' '.join(ln) for ln in lines]
            break
        last = lines[page - 1]
        i, n = src[page - 1]
        if n == len(paras[i]) or _SENT_END.search(last[-1]):
            cut = (i, n)
        else:
            cut = None
            for j in range(page - 1, SENT_MIN - 2, -1):
                ln = lines[j]
                k = max((m for m in range(len(ln) - (j == page - 1)) if _SENT_END.search(ln[m])), default=None)
                if k is not None:
                    cut = (src[j][0], src[j][1] - len(ln) + k + 1)
                    break
            if cut is None:
                cut = (i, n)
                MIDSENT.append(' '.join(last))
        i, n = cut
        for ln, (pi, pn) in zip(lines, src):
            if (pi, pn) > cut and (pi, pn - len(ln)) < cut:
                ln = ln[:len(ln) - (pn - n)]
            elif (pi, pn) > cut:
                break
            out.append(' '.join(ln))
        out += [''] * (-len(out) % page)
        paras = ([paras[i][n:]] if n < len(paras[i]) else []) + paras[i + 1:]
    return out


def _caption(words):
    """caption paragraph -> rows: a two-row split after ' - ' when one fits (place captions
    'Castle - Room'), else the two-row split with the narrowest widest row (no orphan words);
    greedy rows beyond two."""
    if fits(' '.join(words), CAPTION):
        return [' '.join(words)]
    best = None
    for i in range(1, len(words)):
        a, b = ' '.join(words[:i]), ' '.join(words[i:])
        if not (fits(a, CAPTION) and fits(b, CAPTION)):
            continue
        key = (words[i - 1] != '-', max(pixels(a), pixels(b)))
        if best is None or key < best[0]:
            best = (key, [a, b])
    return best[1] if best else [' '.join(ln) for ln in _lines(words, CAPTION)]


def wrap(en, width, page=None, sent=False):
    """English (one tl paragraph, '\\n' = forced break) -> lines joined by real newlines.
    page: lines per box page; a run of blank lines then pads to the next page.
    sent: pages end at a sentence end where possible (SENT_PAGE)."""
    paras = [_para(p) for p in fold(en).split('\\n')]
    if width is CAPTION:
        return '\n'.join(ln for p in paras for ln in _caption(p))
    if not page:
        return '\n'.join(' '.join(ln) for p in paras for ln in _lines(p, width))
    blocks, cur = [], []
    for p in paras:
        if p:
            cur.append(p)
        elif cur:
            blocks.append(cur)
            cur = []
    if cur:
        blocks.append(cur)
    out = []
    for b in blocks:
        out += [''] * (-len(out) % page)
        if sent:
            out += _sent_pages(b, width, page)
        else:
            out += [' '.join(ln) for p in b for ln in _lines(p, width)]
    while out and not out[-1]:
        out.pop()
    return '\n'.join(out)


def lines(en, width):
    return wrap(en, width).count('\n') + 1


def jp_show(seg):
    """Japanese segment as one tl-style line (newlines as \\n)."""
    return seg.replace('\n', '\\n')
