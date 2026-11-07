"""DATA/IMSG.E3: 994 fixed 100-byte records (NUL-terminated SJIS).

Read one record at a time from the disc by 0x800192f4(dst, n) (seek n * 100, read 100 bytes raw
into a 101-byte dst, NUL at dst + 100). English stays in the 100-byte records: <= 99 bytes.
The Japanese descriptions break lines by padding the first line to 20 full-width characters;
the drill-ground lines use a literal "\\r" (two bytes) as the line break.

Sections (record = index + base, by the getters 0x80019344..0x80019434):
  item    0-228    item descriptions (item info box)
  skill   256-320  skill descriptions (+0x100)
  sortie  331-386  sortie lines (+0x14b; Motonari, Takamoto ... 56 people)
  retreat 391-446  retreat lines (+0x187)
  battle  451-479  battle names (+0x1c3; "full-width 10 characters at most")
  (491-502 town-map and 511-523 room descriptions: getters 0x800193e4 / 0x8001940c are never
   called -> unused, not translated)
  drill   655-837  drill-ground sparring lines (+0x28f; "\\r" breaks, 3 lines)
Records 255/330/390/450/490/510/530/654 are developer comments, 531-652 a debug sound list,
'終端' filler: not translated.

script/imsg.txt: "@n section" + Japanese, first occurrence of each text only (repeats listed
                 as "@n = @k").
tl/imsg/*.txt:   "@n" + English ('\\n' forces a break; build wraps at WIDTH pixels); a record
                 without English takes the English of an identical Japanese record.

  imsg.py           errors, size and line-count report
  imsg.py export    write script/imsg.txt
"""
import glob, os, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import text

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
IMSG = os.path.join(ROOT, 'extract', 'DATA', 'IMSG.E3')
SCRIPT = os.path.join(ROOT, 'script', 'imsg.txt')
TL = os.path.join(ROOT, 'tl', 'imsg')          # *.txt, read in name order
ISO_NAME = 'DATA/IMSG.E3'
REC = 100
SECTIONS = [('item', 0, 229), ('skill', 256, 321), ('sortie', 331, 387), ('retreat', 391, 447),
            ('battle', 451, 480), ('drill', 655, 838)]
# pixels per line, lines per record and line-break bytes, by section (to be measured)
# item/skill info box: its printer breaks every 40 bytes by itself (and at 0x0a), 2 lines shown
# (verified with a test record). Sortie/retreat: battle dialogue box (line builder 0x8003de8c,
# cut 0x50 since vwf, 160 px). Drill: speech box 0x90 wide (builder limit 0x14 originally).
WIDTH = {'item': 228, 'skill': 228, 'sortie': 160, 'retreat': 160, 'battle': None, 'drill': 112}
LINES = {'item': 2, 'skill': 2, 'sortie': 3, 'retreat': 3, 'battle': 1, 'drill': 3}
LINE_BYTES = {'item': 39, 'skill': 39}
BREAK = {'drill': b'\\r'}
# drill records 690-701 / 835-837: one '%' = the skill / item name, inserted by 0x800334e4 (the
# text is split at '%'): wrapped as a word of the widest name, bytes counted with the longest
PCT = {range(690, 702): ('skill', 56, 10), range(835, 838): ('item', 76, 16)}       # others: raw 0x0a
FILLER = '終端'
BATTLE_PX = 200
BATTLE_BYTES = 29               # 0x80069aa4 copies the name into a 30-byte field


def records(data=None):
    d = data or open(IMSG, 'rb').read()
    return [d[i:i + REC].split(b'\0')[0].decode('cp932') for i in range(0, len(d), REC)]


def section(n):
    for s, lo, hi in SECTIONS:
        if lo <= n < hi:
            return s
    return None


def japanese(recs=None):
    """-> {n: (section, Japanese)} of the records to translate."""
    recs = recs or records()
    return {n: (section(n), r) for n, r in enumerate(recs) if section(n) and r and r != FILLER}


def show(jp):
    """Japanese record as the worker sees it: padding runs and \\r as \\n."""
    import re
    return re.sub('\u3000{2,}', r'\\n', jp.replace('\\r', '\\n')).rstrip('\u3000')


def item_users():
    """-> {description record: [item numbers]} (DATA.E3 item record byte 20 = description)."""
    import datae3
    d = open(datae3.DATA_E3, 'rb').read()
    off, size, count, cap = datae3.TABLES['item']
    out = {}
    for k, _ in datae3.japanese(d):
        t, _, n = k.partition(':')
        if t == 'item' and n != '255':
            out.setdefault(d[off + int(n) * size + 20], []).append(int(n))
    return out


def export():
    jp, first, done = japanese(), {}, 0
    users = item_users()
    os.makedirs(os.path.dirname(SCRIPT), exist_ok=True)
    with open(SCRIPT, 'w', encoding='utf-8') as f:
        for n, (s, r) in sorted(jp.items()):
            if r in first:
                f.write('@%d = @%d\n\n' % (n, first[r]))
                continue
            first[r] = n
            who = ' [%s]' % ' '.join('item:%d' % i for i in users.get(n, [])) if s == 'item' else ''
            f.write('@%d %s%s\n%s\n\n' % (n, s, who, show(r)))
            done += 1
    return done


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


def encode(s, w):
    return text.fold(w).encode('ascii').replace(b'\n', BREAK.get(s, b'\n'))


def english():
    """-> ({n: record bytes}, errors)"""
    jp, tl = japanese(), load_tl()
    memory = {}
    for n, en in tl.items():
        if n in jp:
            memory.setdefault(jp[n][1], en)
    out, errs = {}, []
    for n in tl:
        if n not in jp:
            errs.append('@%d: not a translatable record' % n)
    for n, (s, r) in jp.items():
        en = tl.get(n, memory.get(r))
        if en is None:
            continue
        pct = next((v for k, v in PCT.items() if n in k), None)
        es = text.check(en.replace('%', 'X', 1) if pct else en)
        if pct and en.count('%') != 1:
            es.append("needs exactly one '%' (the %s name)" % pct[0])
        if es:
            errs += ['@%d: %s' % (n, e) for e in es]
            continue
        ph = ''
        if pct:
            import vwf
            ph = 'M'
            while vwf.width(ph) < pct[1]:
                ph += 'M'
            en = en.replace('%', ph)
        w = text.wrap(en, WIDTH[s]) if WIDTH[s] else text.fold(en)
        if pct:
            w = w.replace(ph, '%')
        b = encode(s, w)
        if pct and len(b) - 1 + pct[2] > REC - 1:
            errs.append('@%d: %d bytes with the longest %s name > %d' % (n, len(b) - 1 + pct[2], pct[0], REC - 1))
        if len(b) > REC - 1:
            errs.append('@%d: %d bytes > %d' % (n, len(b), REC - 1))
        if w.count('\n') + 1 > LINES[s]:
            errs.append('@%d: %d lines > %d' % (n, w.count('\n') + 1, LINES[s]))
        errs += ['@%d: line of %d bytes > %d (the box breaks it by itself)' % (n, len(l), LINE_BYTES[s])
                 for l in w.split('\n') if len(l) > LINE_BYTES.get(s, 99)]
        if s == 'battle' and len(b) > BATTLE_BYTES:
            errs.append('@%d: %d bytes > %d (battle name field)' % (n, len(b), BATTLE_BYTES))
        if s == 'battle' and text.pixels(w) > BATTLE_PX:
            errs.append('@%d: %d px > %d (battle name)' % (n, text.pixels(w), BATTLE_PX))
        out[n] = b
    return out, errs


def build(data):
    """IMSG.E3 bytes -> (English bytes, count); exits on errors."""
    en, errs = english()
    if errs:
        sys.exit('\n'.join(errs) + '\n%d errors in tl/imsg/ (tools/imsg.py)' % len(errs))
    d = bytearray(data)
    for n, b in en.items():
        d[n * REC:(n + 1) * REC] = b.ljust(REC, b'\0')
    return bytes(d), len(en)


def main():
    if sys.argv[1:] == ['export']:
        print('script/imsg.txt: %d records' % export())
        return
    en, errs = english()
    for e in errs:
        print(e)
    print('%d / %d records translated, %d errors' % (len(en), len(japanese()), len(errs)))


if __name__ == '__main__':
    main()
