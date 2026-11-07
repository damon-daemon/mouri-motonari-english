"""Name tables of DATA/DATA.E3 other than the officers (names.py): items, skills, towns.

DATA.E3 sections (offsets table 0x800dc1e4 in MAIN.EXE: 0, 0xa8c0, 0xdec3, 0xe50b, 0xe8a7,
0xed6f, end 0xfad5); the loader 0x80022944 reads the file to 0x801a8000 and parses each record
into a RAM struct array with fixed name fields:
  officers  800 x 54  -> 0x800e43c8 (names.py)
  items     419 x 33  -> 0x800f47b0 x 0x22, parser 0x8001913c: name 16 + NUL (file byte 16 skipped)
  towns      12 x 134 -> 0x800f7f58 x 0xec, parser 0x80019d6c: name 8 + NUL (+ shop item lists)
  (32 + 16 records without text: 0x80019074, 0x8001902c)
  skills     65 x 49  -> 0x800f8a68 x 0x31, parser 0x80019e60: name 10 + NUL (the file has 70:
             the last five 空白 placeholders are never loaded)
Items and skills get their English in place (ASCII, NUL-padded): the file keeps its size.
Town names (8 bytes are too few) stay Japanese in the records; their only reader is the getter
0x80019c14(id) (2 callers: save description "%s Castle", march prompt "Enter %s?"), and those
two calls go to TOWN in the blob, which returns the English from a table there.

script/data.txt: "table:n<TAB>Japanese" (made by setup.py / datae3.py export).
tl/data.txt:     "table:n<TAB>English"; '#' lines are comments.

  datae3.py           field fit report (errors, counts, widest names)
  datae3.py export    write script/data.txt
"""
import os, struct, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import asm, text, vwf

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_E3 = os.path.join(ROOT, 'extract', 'DATA', 'DATA.E3')
SCRIPT = os.path.join(ROOT, 'script', 'data.txt')
TL = os.path.join(ROOT, 'tl', 'data.txt')
ISO_NAME = 'DATA/DATA.E3'
# table: (file offset, record size, count, name cap in bytes)
TABLES = {'item': (0xa8c0, 33, 419, 16),
          'skill': (0xed6f, 49, 65, 10),
          'town': (0xdec3, 134, 12, 8)}
IN_PLACE = ('item', 'skill')
TOWN_MAX = 31                     # blob strings (sprintf "%s Castle" -> 72-B save description)
# pixel limits of the narrowest display (measured in the emulator: see notes/survey.md)
ITEM_PX = 76      # battle item window: text x 35, next icon x 116; storehouse: label at +80 px
SKILL_PX = 56     # battle skill window: the cost is drawn at +58 px from the name
TOWN_GET = 0x80019c14
TOWN_CALLS = (0x80016374, 0x800245b4)


def _cstr(b):
    return b.split(b'\0')[0].decode('cp932')


def japanese(data=None):
    """-> [(key, name)] of the non-blank records."""
    d = data or open(DATA_E3, 'rb').read()
    out = []
    for t, (off, size, count, cap) in TABLES.items():
        for n in range(count):
            name = _cstr(d[off + n * size: off + n * size + cap])
            if name.strip():
                out.append(('%s:%d' % (t, n), name))
    return out


def export():
    rows = japanese()
    os.makedirs(os.path.dirname(SCRIPT), exist_ok=True)
    with open(SCRIPT, 'w', encoding='utf-8') as f:
        for k, name in rows:
            f.write('%s\t%s\n' % (k, name))
    return len(rows)


def load_tl(path=TL):
    out = {}
    if not os.path.exists(path):
        return out
    for n, ln in enumerate(open(path, encoding='utf-8').read().splitlines(), 1):
        if ln.strip() and not ln.startswith('#'):
            k, tab, en = ln.partition('\t')
            if not tab:
                raise ValueError('tl/data.txt line %d: expected key<TAB>English: %r' % (n, ln))
            out[k] = en.strip()
    return out


def errors(tl):
    errs = []
    px = {'item': ITEM_PX, 'skill': SKILL_PX}
    for k, en in tl.items():
        t, _, n = k.partition(':')
        if t not in TABLES or not n.isdigit() or int(n) >= TABLES[t][2]:
            errs.append('%s: no such record' % k)
            continue
        e = text.fold(en)
        if not e or text.check(en) or '\\n' in e:
            errs.append('%s: bad characters %r' % (k, en))
            continue
        cap = TABLES[t][3] if t in IN_PLACE else TOWN_MAX
        if len(e) > cap:
            errs.append('%s: %d characters > %d (%s)' % (k, len(e), cap, en))
        if t in px and vwf.width(e) > px[t]:
            errs.append('%s: %d px > %d (%s)' % (k, vwf.width(e), px[t], en))
    return errs


def apply(data, tl):
    d = bytearray(data)
    for k, en in tl.items():
        t, _, n = k.partition(':')
        if t not in IN_PLACE:
            continue
        off, size, count, cap = TABLES[t]
        o = off + int(n) * size
        d[o:o + cap] = text.fold(en).encode('ascii').ljust(cap, b'\0')
    return bytes(d)


def build(data):
    """DATA.E3 bytes -> (English bytes, count); exits on errors."""
    tl = load_tl()
    errs = errors(tl)
    if errs:
        sys.exit('\n'.join(errs) + '\n%d errors in tl/data.txt' % len(errs))
    return apply(data, tl), len(tl)


def blob(at):
    """-> (bytes, TOWN entry) of the blob part at `at` (4-aligned): strings, pointer table, code.
    TOWN(id) = English town name, NULL for id >= 12 (as the original getter); Japanese record
    name when tl has no English."""
    tl = load_tl()
    count = TABLES['town'][2]
    strs, offs = b'', []
    for n in range(count):
        en = tl.get('town:%d' % n)
        offs.append(len(strs) if en else None)
        if en:
            strs += text.fold(en).encode('ascii') + b'\0'
    strs += bytes(-len(strs) % 4)
    tab_at = at + len(strs)
    tab = b''.join(struct.pack('<I', at + o if o is not None else 0x800f7f58 + n * 0xec)
                   for n, o in enumerate(offs))
    code_at = tab_at + len(tab)
    code = asm.assemble(code_at, [
        ('sltiu', 'v0', 'a0', count),
        ('beqz', 'v0', 'out'),
        ('sll', 't0', 'a0', 2),
        ('lui', 't1', asm.hi(tab_at)),
        ('addu', 't1', 't1', 't0'),
        ('lw', 'v0', asm.lo(tab_at), 't1'),
        'out:',
        ('jr', 'ra'),
        ('nop',)])
    return strs + tab + code, code_at


def patch(exe, exe_base, town):
    jal = asm.assemble(0, [('jal', TOWN_GET)])
    for va in TOWN_CALLS:
        o = va - exe_base
        assert exe[o:o + 4] == jal, 'no jal town getter at %#x' % va
        exe[o:o + 4] = asm.assemble(va, [('jal', town)])


def main():
    if sys.argv[1:] == ['export']:
        print('script/data.txt: %d names' % export())
        return
    tl = load_tl()
    for e in errors(tl):
        print(e)
    rows = japanese()
    for t in TABLES:
        keys = [k for k, _ in rows if k.startswith(t + ':')]
        print('%s: %d / %d translated' % (t, sum(k in tl for k in keys), len(keys)))
    wide = sorted(((vwf.width(text.fold(en)), k, en) for k, en in tl.items()), reverse=True)[:10]
    print('widest: ' + ', '.join('%s %s %dpx' % (k, en, w) for w, k, en in wide))


if __name__ == '__main__':
    main()
