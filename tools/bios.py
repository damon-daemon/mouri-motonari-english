"""DATA/PROFILE.E3: officer bios (People list -> a name -> bio screen).

File: plain SJIS text, CRLF. Entries are separated by '$'; the bio of entry k is the text after
the k-th '$' (entry 0: after the first line). The loader 0x80080e9c(officer, dst) maps the
officer (and story progress) to an entry with 0x8007c4e4 (< 651), loads the whole file
(at most 0x31000 bytes) to 0x801a8000, skips k '$' and the rest of that line, then copies
the bio to dst until '$': '//' up to the end of the line is a comment (anywhere in a line),
tabs are dropped and every CRLF pads the line with spaces to 24 bytes (12 full-width chars).
The screen 0x8008158c slices that buffer (dst = sp+0x20, 0x4e8 bytes, no bound check) into
rows of 24 bytes (stride 0x19, at most 50 rows), shown 9 at a time at x 92, y 56 + 18 * i in
the 16-px font, scrolled with Up/Down.
The English file has one 2048-byte sector per entry and the loader reads only sector k (no
whole-file load: the English would exceed 0x31000 and the RAM above 0x801d9000 is in use).

English: rows of ROW bytes (patched constants below), wrapped at PX pixels, at most ROWS
rows per entry (ROWS * ROW <= the 0x4e8-byte buffer). Officers 48 and 49 (entries 88/89 and
649/650, the drill-ground six-win opponents) are sprintf'd with the six-win officer's name
(%s) and then re-wrapped at Japanese '。' (0x800810c0 / 0x80081358): the re-wrap is replaced by
a strcpy, the English carries one '%s' as its own last row.

Units: paragraphs (a Japanese line starting with a full-width space starts one); later entries
of the same officer repeat earlier paragraphs, so each distinct paragraph is translated once.
A trailing （第N話） (episode of the event, right-aligned) is cut off and re-added by the build
as "(Episode N)" right-aligned.

script/profile.txt: "@n [entries] Name" + Japanese paragraph (first occurrence order).
tl/profile/*.txt:   "@n" + English paragraph (one line; '\\n' forces a break).

  bios.py           errors, sizes and the longest entries
  bios.py export    write script/profile.txt
"""
import glob, json, os, re, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import text

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROFILE = os.path.join(ROOT, 'extract', 'DATA', 'PROFILE.E3')
SCRIPT = os.path.join(ROOT, 'script', 'profile.txt')
TL = os.path.join(ROOT, 'tl', 'profile')
ISO_NAME = 'DATA/PROFILE.E3'
SLOT = 0x800                    # English file: one sector per entry ("\r\n" + bio + "$", zeros)
ROW = 40                        # bytes per row (Japanese 24)
ROWS = 30                       # rows per entry (Japanese 50; 30 * 40 <= 0x4e8 raw buffer)
PX = 192                        # text x 92 .. 284 (16-px font; scroll arrows at x 290)
INDENT = '   '                   # paragraph start
PCT_ENTRIES = (88, 89, 649, 650)
PCT_BYTES = 900                 # sprintf output in the loader's frame (sp+0x10 .. 0x3d0)
NAME_PX, NAME_BYTES = 160, 24   # room kept for the six-win officer's name on the last row
EP_NAMES = {'最終': 'Final Episode'}
_TAG = re.compile(r'[　 ]*（(第(.+)話|最終話)）$')
_NUM = {c: i for i, c in enumerate('〇一二三四五六七八九')}

LOADER, SCREEN = 0x80080e9c, 0x8008158c
# (address, clean word, new word): ROW / ROW + 1 / ROWS constants
#   loader: comment line -> column = 24; CRLF pads while column < 24
#   screen: slice while n < 24; row stride 0x19; at most 50 rows; print row (i) * 25 -> * 41
SITES = [
    (0x80080fc8, 0x24060018, 0x24060000 | ROW),            # addiu a2, zero, 0x18
    (0x80080fdc, 0x2cc20018, 0x2cc20000 | ROW),            # sltiu v0, a2, 0x18
    (0x80080ff0, 0x2cc20018, 0x2cc20000 | ROW),
    (0x80081634, 0x2e420018, 0x2e420000 | ROW),            # sltiu v0, s2, 0x18
    (0x80081654, 0x24a50019, 0x24a50000 | (ROW + 1)),      # addiu a1, a1, 0x19
    (0x80081664, 0x2d020032, 0x2d020000 | ROWS),           # sltiu v0, t0, 0x32
    (0x800818fc, 0x00022840, 0x00022880),                  # sll a1, v0, 1 -> 2 (25 -> 41)
    # loader: whole file (0x80010780(name, 0x801a8000, 0x31000)) + skip k '$' -> read sector k
    # only: 0x8001080c(name, 0x801a8000, k, 0x800), a3 = 0x801a8000, j to the line skip
    (0x80080eec, 0x3c060003, 0x02003021),                  # lui a2, 3 -> move a2, s0
    (0x80080ef0, 0x0c0041e0, 0x0c004203),                  # jal 0x80010780 -> jal 0x8001080c
    (0x80080ef4, 0x34c61000, 0x24070800),                  # ori a2, a2, 0x1000 -> addiu a3, zero, 0x800
    (0x80080f00, 0x1200000c, 0x080203cd),                  # beqz s0, 0x80080f34 -> j 0x80080f34
]
assert ROW == 40
# officers 48/49: after sprintf(sp+0x10, bio, name, name): strcpy(dst s1, sp+0x10); return
PCT_SITES = (0x800810c0, 0x80081358)
STRCPY, RETURN = 0x800a920c, 0x80081570


def entries(data=None):
    """-> list of entries, each a list of (Japanese paragraph, episode tag or None)"""
    d = (data or open(PROFILE, 'rb').read()).decode('cp932')
    parts = d.split('$')[:-1]
    out = []
    for k, e in enumerate(parts):
        lines = e.split('\r\n')[1:]               # the rest of the '$' line (entry 0: first line)
        paras = []
        for ln in lines:
            ln = ln.split('//')[0].replace('\t', '')
            if not ln:
                continue
            if ln.startswith('　') or not paras:
                paras.append(ln)
            else:
                paras[-1] += ln
        ps = []
        for p in paras:
            m = _TAG.search(p)
            tag = None
            if m:
                tag = 'Final Episode' if m.group(1) == '最終話' else 'Episode %d' % kanji_num(m.group(2))
                p = p[:m.start()]
            p = p.strip('　 ')
            if p:
                ps.append([p, tag])
            elif tag and ps:
                ps[-1][1] = tag
            elif tag:
                ps.append(['', tag])
        out.append([tuple(x) for x in ps])
    return out


def kanji_num(s):
    if s.isdigit():
        return int(s)
    n, cur = 0, 0
    for c in s:
        if c == '十':
            n += (cur or 1) * 10
            cur = 0
        else:
            cur = _NUM[c]
    return n + cur


def officers_of_entries():
    """-> {entry: officer header 'nnn' of the group it belongs to}"""
    d = open(PROFILE, 'rb').read().decode('cp932')
    out, cur = {}, None
    for k, e in enumerate(d.split('$')[:-1]):
        m = re.search(r'^//\s*(\d+) ', e, re.M)
        if m:
            cur = int(m.group(1))
        out[k] = cur
    return out


def paragraphs(ents=None):
    """-> {Japanese paragraph: n} in first-occurrence order"""
    out = {}
    for ps in ents or entries():
        for p, _ in ps:
            if p and p not in out:
                out[p] = len(out)
    return out


def export():
    ents = entries()
    paras = paragraphs(ents)
    who = officers_of_entries()
    names = {r['id']: r['en'] for r in json.load(open(os.path.join(ROOT, 'tl', 'names', 'officers.json'), encoding='utf-8'))}
    used = {}
    for k, ps in enumerate(ents):
        for p, _ in ps:
            if p:
                used.setdefault(paras[p], []).append(k)
    os.makedirs(os.path.dirname(SCRIPT), exist_ok=True)
    with open(SCRIPT, 'w', encoding='utf-8') as f:
        for p, n in paras.items():
            ks = used[n]
            o = who[ks[0]]
            f.write('@%d [%s] %s%s\n%s\n\n' % (n, ' '.join(map(str, ks)), names.get(o, '?'),
                                             ' (officer %s)' % o, p))
    return len(paras)


def load_tl(path=TL):
    out, key = {}, None
    files = sorted(glob.glob(os.path.join(path, '*.txt')))
    for ln in (ln for f in files for ln in open(f, encoding='utf-8').read().splitlines()):
        if ln.startswith('@'):
            key = int(ln[1:].split()[0])
        elif ln.strip() and key is not None:
            out[key] = ln.strip()
            key = None
    return out


def _pad_right(line, tag):
    """line + tag pushed to the right edge with spaces (None if it does not fit)"""
    s = (line + ' ' + tag) if line else tag
    if text.pixels(s) > PX or len(s) > ROW:
        return None
    gap = ' ' if line else ''
    while text.pixels(line + gap + ' ' + tag) <= PX and len(line + gap + tag) < ROW:
        gap += ' '
    return line + gap + tag


def layout(ps, tl):
    """entry paragraphs + English -> (rows, error); rows without padding"""
    rows = []
    for p, tag in ps:
        if p:
            en = tl.get(paragraphs_index[p])
            if en is None:
                return None, None
            w = text.wrap(INDENT + en, (PX, ROW)).split('\n')
            rows += [r.rstrip() for r in w]
        if tag:
            tag = '(%s)' % tag
            last = rows[-1] if rows and p else ''
            r = _pad_right(last, tag) if last else None
            if r:
                rows[-1] = r
            else:
                rows.append(_pad_right('', tag))
    return rows, None


paragraphs_index = {}


def english():
    """-> (list of entry byte strings or None, errors)"""
    global paragraphs_index
    ents = entries()
    paragraphs_index = paragraphs(ents)
    tl = load_tl()
    errs = []
    nums = set(paragraphs_index.values())
    for n, en in tl.items():
        if n not in nums:
            errs.append('@%d: no such paragraph' % n)
            continue
        es = text.check(en.replace('%s', 'X'))
        if '//' in en or '$' in en:
            es.append("'//' and '$' are not allowed")
        pct = [k for k in PCT_ENTRIES if any(paragraphs_index.get(p) == n for p, _ in ents[k])]
        if '%' in en.replace('%s', '') or (en.count('%s') and not pct):
            es.append("'%' is not allowed")
        errs += ['@%d: %s' % (n, e) for e in es]
    out = []
    for k, ps in enumerate(ents):
        if k in PCT_ENTRIES:                       # the name row ends the entry: no episode tag
            ps = [(p, None) for p, _ in ps]
        rows, _ = layout(ps, tl)
        if rows is None:
            out.append(None)
            continue
        if k in PCT_ENTRIES:
            body = ' '.join(rows)
            if body.count('%s') != 1 or rows[-1].strip() not in ('%s', '%s.'):
                errs.append('entry %d: needs exactly one %%s, alone on the last row (the name)' % k)
        if len(rows) > ROWS:
            errs.append('entry %d: %d rows > %d' % (k, len(rows), ROWS))
        b = encode_rows(rows)
        if k in PCT_ENTRIES and len(rows) * ROW + NAME_BYTES > PCT_BYTES:
            errs.append('entry %d: %d bytes padded > %d' % (k, len(rows) * ROW + NAME_BYTES, PCT_BYTES))
        out.append(b)
    return out, errs


def encode_rows(rows):
    return b''.join(text.fold(r).encode('ascii') + b'\r\n' for r in rows)


def build(data):
    """PROFILE.E3 bytes -> (English file, translated entries); exits on errors.
    Untranslated entries keep the Japanese (rows of 24 bytes fit the 40-byte rows)."""
    ents, errs = english()
    if errs:
        sys.exit('\n'.join(errs) + '\n%d errors in tl/profile/ (tools/bios.py)' % len(errs))
    raw = data.decode('cp932').split('$')[:-1]
    out = b''
    for k, e in enumerate(ents):
        if e is None:
            e = '\r\n'.join(raw[k].split('\r\n')[1:]).encode('cp932')
        slot = b'\r\n' + e + b'$'
        assert len(slot) < SLOT, 'entry %d: %d bytes' % (k, len(slot))
        out += slot.ljust(SLOT, b'\0')
    return out, sum(1 for e in ents if e is not None)


def patch(exe, exe_base):
    import asm, struct
    for va, old, new in SITES:
        o = va - exe_base
        assert struct.unpack_from('<I', exe, o)[0] == old, 'unexpected word at %#x' % va
        struct.pack_into('<I', exe, o, new)
    for va in PCT_SITES:
        o = va - exe_base
        assert struct.unpack_from('<I', exe, o)[0] == 0x27a70010, 'unexpected word at %#x' % va
        code = asm.assemble(va, [
            ('addu', 'a0', 's1', 'zero'),
            ('jal', STRCPY),
            ('addiu', 'a1', 'sp', 0x10),
            ('j', RETURN),
            ('nop',)])
        exe[o:o + len(code)] = code


def main():
    if sys.argv[1:] == ['export']:
        print('script/profile.txt: %d paragraphs' % export())
        return
    ents, errs = english()
    for e in errs:
        print(e)
    tl = load_tl()
    done = [b for b in ents if b is not None]
    print('%d / %d paragraphs translated; %d / %d entries complete, %d errors'
          % (len(tl), len(paragraphs_index), len(done), len(ents), len(errs)))
    if done:
        sizes = sorted(((b.count(b'\n'), k) for k, b in enumerate(ents) if b), reverse=True)[:5]
        print('most rows: ' + ', '.join('entry %d %d' % (k, n) for n, k in sizes))
        print('largest entry %d bytes (sector %d)' % (max(len(b) for b in done) + 3, SLOT))


if __name__ == '__main__':
    main()
