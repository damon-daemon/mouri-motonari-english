"""Translation files of the event scripts DATA/R_*.EEX (story) and S_*.EEX (battles): show, apply, check, stats; used by build.py.

tl/eex/R_nn.txt (S_nn.txt) holds the English (no Japanese) of one script file:

    # comment (a line starting with #)
    @<n>        string n of the file (eex.strings order), whole string
    @<n>.<k>    speech k of dialogue string n (op 0x27; the speaker is kept from the original)
    English text, possibly over several physical lines (joined with spaces); \\n = line break.

See text.py for the segments, the character set and the wrapping. A segment without English
takes the English of a segment with the same Japanese (translation memory, explicit wins);
one with neither keeps its Japanese.

usage:
    tl.py show  R_00 [from] [to] [--todo]    # Japanese segments (from/to = string indexes)
    tl.py apply R_00 batch.txt               # validate a batch, merge it into tl/eex/R_00.txt
    tl.py check [R_00]                       # validate everything in tl/ (and the file sizes)
    tl.py stats
"""
import os, re, sys

sys.path.insert(0, os.path.dirname(__file__))
import eex, text
try:
    import names as officer_names     # English speaker headers (names session)
except ImportError:
    officer_names = None

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TL = os.path.join(ROOT, 'tl')
TL_EEX = os.path.join(TL, 'eex')
EEX_MAX = 0x18000                       # load buffer 0x800c4190-0x800dc190 (R_18 = 94,252 B)
_REC = re.compile(r'@(\d+)(?:\.(\d+))?\s*$')


# ---------------------------------------------------------------- Japanese side
class Script:
    """One EEX file: parsed sections, string operands, segments."""

    def __init__(self, name, data):
        self.name, self.data = name, data
        self.secs = eex.parse(data)
        self.strs = eex.strings(self.secs)
        self.segs = {}                  # (n, k) -> Japanese segment
        self.tmpl = []
        self.kind = {}
        for n, (op, args, i) in enumerate(self.strs):
            segs, tmpl = text.segments(op, text.decode(args[i][1]))
            self.tmpl.append(tmpl)
            for k, s in enumerate(segs):
                key = (n, k) if op == 0x27 else (n, None)
                self.segs[key] = s
                self.kind[key] = op

    def build(self, en):
        """{key: English} -> rebuilt file bytes."""
        secs = eex.parse(self.data)
        for n, (op, args, i) in enumerate(eex.strings(secs)):
            keys = sorted((k for k in self.segs if k[0] == n), key=lambda k: k[1] or 0)
            if not any(k in en for k in keys):
                continue
            segs = [text.wrap(en[k], text.WIDTH.get(op, 30), text.PAGE.get(op), op in text.SENT_PAGE) if k in en else self.segs[k] for k in keys]
            tmpl = self.tmpl[n]
            if tmpl[0] == 'talk' and officer_names:
                tmpl = ('talk', [officer_names.head(h) for h in tmpl[1]], tmpl[2])
            args[i] = (5, text.join(tmpl, segs).encode('cp932'))
        return eex.build(secs)


def names():
    return [os.path.basename(f)[:-4] for f in eex.files()]


def load(name, data=None):
    return Script(name, data if data is not None else eex.load(name))


def who(sc, k):
    """' [Speaker]' of a dialogue segment, else ''"""
    tmpl = sc.tmpl[k[0]]
    return ' [%s]' % tmpl[1][k[1]][1:] if tmpl[0] == 'talk' else ''


def key_str(k):
    return '@%d' % k[0] if k[1] is None else '@%d.%d' % k


# ---------------------------------------------------------------- tl files
def tl_path(name):
    return os.path.join(TL_EEX, name + '.txt')


def parse_tl(path):
    """-> {(n, k or None): English}"""
    out, key, buf = {}, None, []

    def flush():
        if key is not None:
            out[key] = ' '.join(x.strip() for x in buf if x.strip())
    if not os.path.exists(path):
        return out
    for ln in open(path, encoding='utf-8'):
        ln = ln.rstrip('\n')
        if ln.startswith('#'):
            continue
        m = _REC.match(ln)
        if m:
            flush()
            key, buf = (int(m.group(1)), None if m.group(2) is None else int(m.group(2))), []
            if key in out:
                raise ValueError('%s: %s twice' % (path, key_str(key)))
        elif key is not None:
            buf.append(ln)
        elif ln.strip():
            raise ValueError('%s: text before the first @ line: %r' % (path, ln))
    flush()
    return out


def write_tl(name, recs):
    os.makedirs(TL_EEX, exist_ok=True)
    with open(tl_path(name), 'w', encoding='utf-8') as f:
        for k in sorted(recs, key=lambda k: (k[0], k[1] or 0)):
            f.write('%s\n%s\n\n' % (key_str(k), recs[k]))


def load_tls():
    return {n: parse_tl(tl_path(n)) for n in names()}


def memory(scripts, tls):
    """{Japanese segment: English} from every explicit segment."""
    tm = {}
    for n, recs in tls.items():
        for k, en in recs.items():
            if k in scripts[n].segs:
                tm.setdefault(scripts[n].segs[k], en)
    return tm


def warn(sc, k, en):
    op = sc.kind[k]
    w = text.WIDTH.get(op)
    out = []
    if w is None:
        # titles (session 4); goals/choices have hard limits (text.limits), warn over 200 px
        lim = text.TITLE_PX if op in (0x2a, 0x2b) else 200
        for line in text.fold(en).split('\\n'):
            if text.pixels(line) > lim:
                out.append('%d px (unwrapped label, limit %d)' % (text.pixels(line), lim))
    return ['%s %s: %s' % (sc.name, key_str(k), x) for x in out]


# ---------------------------------------------------------------- build
def english(scripts=None, tls=None):
    """-> ({name: rebuilt EEX bytes (changed files only)}, translated count, errors)"""
    scripts = scripts or {n: load(n) for n in names()}
    tls = tls if tls is not None else load_tls()
    tm = memory(scripts, tls)
    out, errs, done = {}, [], 0
    for n, sc in scripts.items():
        recs = tls.get(n, {})
        errs += ['%s %s: no such segment' % (n, key_str(k)) for k in recs if k not in sc.segs]
        en = {}
        for k, jp in sc.segs.items():
            e = recs.get(k, tm.get(jp))
            if e is None:
                continue
            es = text.check(e) or text.limits(sc.kind[k], e)
            if es:
                errs += ['%s %s: %s' % (n, key_str(k), x) for x in es]
                continue
            en[k] = e
        done += len(en)
        if en:
            d = sc.build(en)
            if len(d) > EEX_MAX:
                errs.append('%s: %d bytes > %d (load buffer)' % (n, len(d), EEX_MAX))
            out[n] = d
    return out, done, errs


# ---------------------------------------------------------------- commands
def show(name, a=0, z=None, todo=False):
    scripts = {n: load(n) for n in names()}
    tls = load_tls()
    sc, recs, tm = scripts[name], tls[name], memory(scripts, tls)
    heads = {}
    for k, jp in sorted(sc.segs.items(), key=lambda i: (i[0][0], i[0][1] or 0)):
        n = k[0]
        if n < a or (z is not None and n > z):
            continue
        if todo and (k in recs or jp in tm):
            continue
        print('%s %s%s\n%s\n' % (key_str(k), text.KIND.get(sc.kind[k], hex(sc.kind[k])), who(sc, k), text.jp_show(jp)))


def apply(name, batch):
    sc = load(name)
    new = parse_tl(batch)
    errs = []
    for k, en in new.items():
        if k not in sc.segs:
            errs.append('%s: no such segment in %s' % (key_str(k), name))
        else:
            errs += ['%s: %s' % (key_str(k), x) for x in text.check(en) or text.limits(sc.kind[k], en)]
    if errs:
        sys.exit('\n'.join(errs) + '\n%d errors, nothing written' % len(errs))
    for k, en in new.items():
        for w in warn(sc, k, en):
            print('warning ' + w)
    recs = parse_tl(tl_path(name))
    recs.update(new)
    write_tl(name, recs)
    print('%s: %d segments merged (%d in file)' % (name, len(new), len(recs)))


def check(only=None):
    scripts = {n: load(n) for n in names()}
    tls = load_tls()
    if only:
        tls = {n: (v if n == only else {}) for n, v in tls.items()}
    out, done, errs = english(scripts, tls)
    for n, recs in tls.items():
        for k, en in sorted(recs.items(), key=lambda i: (i[0][0], i[0][1] or 0)):
            if k in scripts[n].segs:
                for w in warn(scripts[n], k, en):
                    print('warning ' + w)
    for m in text.MIDSENT:
        print('warning narration page ends mid-sentence (sentence > a page): ...' + m)
    big = sorted(((len(d), n) for n, d in out.items()), reverse=True)[:3]
    if big:
        print('largest: ' + ', '.join('%s %d' % (n, s) for s, n in big))
    print('\n'.join(errs))
    print('%d segments translated, %d errors' % (done, len(errs)))
    return not errs


def stats():
    scripts = {n: load(n) for n in names()}
    tls = load_tls()
    tm = memory(scripts, tls)
    tot = done = 0
    for n, sc in scripts.items():
        t = len(sc.segs)
        d = sum(1 for k, jp in sc.segs.items() if k in tls[n] or jp in tm)
        tot, done = tot + t, done + d
        if d:
            print('%s: %4d / %4d' % (n, d, t))
    print('total: %d / %d segments (%.1f%%)' % (done, tot, 100.0 * done / max(tot, 1)))


def main():
    a = sys.argv[1:]
    if not a:
        sys.exit(__doc__)
    if a[0] == 'show':
        nums = [int(x) for x in a[2:] if not x.startswith('--')]
        show(a[1], *(nums + [0, None])[:2], todo='--todo' in a)
    elif a[0] == 'apply':
        apply(a[1], a[2])
    elif a[0] == 'check':
        sys.exit(0 if check(a[1] if len(a) > 1 else None) else 1)
    elif a[0] == 'stats':
        stats()
    else:
        sys.exit(__doc__)


if __name__ == '__main__':
    main()
