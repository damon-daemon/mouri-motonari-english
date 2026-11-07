"""Officer names: the records keep their Japanese, the name printer returns English.

DATA/DATA.E3 starts with 800 officer records of 54 bytes (name [13] SJIS, reading [15]
half-width kana, stats); the game copies them to the officer table in RAM (OFFICERS, 0x50 bytes
each: +0 u16 index | 0x1000, +0x0c name, +0x19 reading, +0x3d digit-stripped name buffer).
The event scripts name their speaker by the Japanese record name (`&Id`, matched with strcmp
over the 800 records at 0x80023b10), so the records cannot change. Every name that is printed
goes through GETNAME 0x800190d4 (record -> name minus its digits: 家臣3 -> 家臣; 101 callers),
as in Oda Nobunaga Den: build.py redirects it to English by record number (blob_names/hook
below, in the blob that build.py appends to KFONT.BIN). The scripts here have no
`&Id&Display` headers (all 514 speaker ids are record names), so head() keeps them as they are.

tl/names/officers.json: one row per line, {"id": record, "en": "Family Given", "short": ...};
"short" (optional) is printed where the field is narrow (SHORT_SITES, SHORT_PX) when the full
name does not fit there; records without a row keep their Japanese (the empty 職人空き slots).
English names follow the records' kana readings (macrons where the kana lengthen a vowel).

usage:
    names.py show [TEXT]     records: number, Japanese, reading, English
    names.py check
"""
import json, os, struct, sys, unicodedata

sys.path.insert(0, os.path.dirname(__file__))
import asm, text

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TL_NAMES = os.path.join(ROOT, 'tl', 'names')
DATA_E3 = os.path.join(ROOT, 'extract', 'DATA', 'DATA.E3')
RECORD, COUNT = 54, 800
OFFICERS, OFFICER_SIZE = 0x800e43c8, 0x50
GETNAME = 0x800190d4
GETNAME_FIRST = 0x00003021              # move a2, zero (delay slot of our jump: lbu v0, 0xc(a0))
MAX_NAME = 24                           # longest English name (to be measured: speaker line, labels)
NAME_PX = 156                           # speaker name line above the dialogue (box text 160 px)
SHORT_PX = 68                           # SHORT_SITES fields (battle unit list: Lv digit at x 90)
MID_PX = 84                             # MID_SITES fields (battle unit panels: Lv label at x + 88 / 94;
                                        # People lists: 3 columns 88 / 92 px apart)


def japanese():
    d = open(DATA_E3, 'rb').read()
    return [text.decode(d[i * RECORD:i * RECORD + 13].split(b'\0')[0]) for i in range(COUNT)]


def readings():
    d = open(DATA_E3, 'rb').read()
    return [unicodedata.normalize('NFKC', d[i * RECORD + 13:i * RECORD + 28].split(b'\0')[0].decode('cp932'))
            for i in range(COUNT)]


def _rows(full=False):
    path = os.path.join(TL_NAMES, 'officers.json')
    if not os.path.exists(path):
        return {}
    rows = json.load(open(path, encoding='utf-8'))
    return {r['id']: r if full else r['en'] for r in rows}


def officers():
    return _rows()


def head(h):
    """Speaker header of the Japanese script -> header for the English one (unchanged: the
    `&Id` is looked up by its Japanese record name, the name shown comes from GETNAME)."""
    return h


def _short(row, px=SHORT_PX):
    return row['en'] if text.pixels(row['en']) <= px else row.get('short', row['en'])


def check():
    errs = []
    for i, r in _rows(full=True).items():
        en = r['en']
        if not 0 <= i < COUNT:
            errs.append('officers %d: no such record' % i)
        for s in {en, r.get('short', en)}:
            errs += ['officers %d: %s' % (i, e) for e in text.check(s)]
        if len(text.fold(en)) > MAX_NAME:
            errs.append('officers %d: %d characters > %d' % (i, len(en), MAX_NAME))
        if text.pixels(en) > NAME_PX:
            errs.append('officers %d: %d px > %d' % (i, text.pixels(en), NAME_PX))
        if SHORT_SITES and text.pixels(_short(r)) > SHORT_PX:
            errs.append('officers %d: %r wider than %d px (needs a "short")' % (i, _short(r), SHORT_PX))
        if MID_SITES and text.pixels(_short(r, MID_PX)) > MID_PX:
            errs.append('officers %d: %r wider than %d px (needs a "short")' % (i, _short(r, MID_PX), MID_PX))
    return errs


# ---------------------------------------------------------------- program patch
def blob_names(base):
    """English names at `base`: three tables of u16 offsets (from base; 0 = keep the Japanese)
    per record: full names, short forms for SHORT_PX and for MID_PX ("short" if the full name is
    wider, else the full name); then the NUL-terminated strings (shared). -> bytes"""
    rows = _rows(full=True)
    strs, offs = bytearray(), {}
    head = 6 * COUNT

    def off(s):
        if s not in offs:
            offs[s] = head + len(strs)
            strs.extend(text.fold(s).encode('ascii') + b'\0')
        return offs[s]
    full = [off(rows[i]['en']) if i in rows else 0 for i in range(COUNT)]
    short = [off(_short(rows[i])) if i in rows else 0 for i in range(COUNT)]
    mid = [off(_short(rows[i], MID_PX)) if i in rows else 0 for i in range(COUNT)]
    data = struct.pack('<%dH' % (3 * COUNT), *(full + short + mid)) + bytes(strs)
    assert len(data) < 0x10000
    return data


def hook(at, base, raw_target):
    """New GETNAME at `at` (full names), `at` + 8 (short forms, SHORT_SITES call it) and
    `at` + 16 (MID_PX forms, MID_SITES):
    English of the record if the table has it, else the original (which continues at
    GETNAME + 4; its first instruction, replaced by the jump to here, runs in the delay slot).
    Then a wrapper for RAW_SITES: a2 = GETNAME(a2 - 0x0c), then jump to `raw_target`.
    -> (code, short entry, raw entry)"""
    lines = [
        ('b', 'common'),
        ('addiu', 't3', 'zero', 0),             # full table: offset 0
        ('b', 'common'),                        # short entry: second table
        ('addiu', 't3', 'zero', 2 * COUNT),
        ('addiu', 't3', 'zero', 4 * COUNT),     # mid entry (short entry + 8): third table
        'common:',
        ('lui', 't0', asm.hi(OFFICERS)),
        ('addiu', 't0', 't0', asm.lo(OFFICERS)),
        ('subu', 't1', 'a0', 't0'),
        ('addiu', 't2', 'zero', OFFICER_SIZE),
        ('divu', 't1', 't2'),
        ('mflo', 't1'),
        ('sltiu', 'v0', 't1', COUNT),
        ('beqz', 'v0', 'jp'),
        ('sll', 't1', 't1', 1),
        ('addu', 't1', 't1', 't3'),
        ('lui', 't2', asm.hi(base)),
        ('addu', 't2', 't2', 't1'),
        ('lhu', 't1', asm.lo(base), 't2'),
        ('nop',),
        ('beqz', 't1', 'jp'),
        ('lui', 'v0', asm.hi(base)),
        ('addiu', 'v0', 'v0', asm.lo(base)),
        ('jr', 'ra'),
        ('addu', 'v0', 'v0', 't1'),
        'jp:',
        ('lbu', 'v0', 0x0c, 'a0'),              # the original's first two instructions
        ('j', GETNAME + 8),
        ('addu', 'a2', 'zero', 'zero')]
    raw = at + 4 * len([x for x in lines if not isinstance(x, str)])
    lines += [                                  # RAW_SITES: a2 = record + 0x0c
        ('addiu', 'sp', 'sp', -32),
        ('sw', 'ra', 28, 'sp'),
        ('sw', 'a0', 16, 'sp'),
        ('sw', 'a1', 20, 'sp'),
        ('sw', 'a3', 24, 'sp'),
        ('jal', at),
        ('addiu', 'a0', 'a2', -0x0c),
        ('addu', 'a2', 'v0', 'zero'),
        ('lw', 'ra', 28, 'sp'),
        ('lw', 'a0', 16, 'sp'),
        ('lw', 'a1', 20, 'sp'),
        ('lw', 'a3', 24, 'sp'),
        ('j', raw_target),
        ('addiu', 'sp', 'sp', 32)]
    return asm.assemble(at, lines), at + 8, raw


# officer screens: printf(font, fmt, record + 0x19) prints the kana reading right of the name
# (0x8007886c at x 0x70, 0x800817d0 at x 0x74) -> record + 0x18, the name field's last byte
# (always NUL: names are <= 11 bytes)
READING_SITES = [0x8007886c, 0x800817d0]
READING_OLD, READING_NEW = 0x26660019, 0x26660018     # addiu a2, s3, ...
# calls of GETNAME that print into a narrow field: they get the short forms
SHORT_SITES = [
    0x8007a8dc,     # battle unit list (部隊表; helper 0x8007a76c, 3 callers in the list module)
    0x8002ad48,     # name by unit id 0x8002ad1c: floating labels on the walk-around maps (fixed
                    # 72-px cells: longer names wrap to the screen's left edge; centred by vwf at
                    # 0x8002e27c) and the people list (Square; centred in 10 columns = 80 px)
]
# calls that pass the Japanese record name (a2 = record + 0x0c in the delay slot)
MSGW = 0x8003f828                       # message window (type, fmt, ...)
# battle unit panels (Square on a unit; name at x, Lv label at x + 88 / x + 94): MID_PX forms
MID_SITES = [0x80059428, 0x8005afa8,
             0x80082cf0,    # People (by name): 3 columns x 8 rows, x = 48 + 88 col (16-px font)
             0x80081f30]    # People (by episode): x = 44 + 92 col
# people list (Square on the walk-around maps; 0x8002e5c0): box 76 px at x 16 or 228 (table
# 0x80124520), names centred in 10 columns -> everything 16 px wider, right-hand x 212
# (va, original word, new word)
PEOPLE_LIST = [
    (0x8002e690, 0x2407004c, 0x2407005c),   # box width (addiu a3, zero, 0x4c)
    (0x8002e6fc, 0x2406003c, 0x2406004c),   # list area width 0x8001b20c
    (0x8002e440, 0x24060044, 0x24060054),   # cursor bar width 0x80012238
    (0x8002e550, 0x2405000a, 0x2405000c),   # centred print columns (names)
    (0x8002e560, 0x2405000a, 0x2405000c),   # (empty-slot string)
    (0x8002e7a0, 0x24c60048, 0x24c60058),   # scroll arrow x + 0x48
    (0x8002e7c8, 0x24c60048, 0x24c60058),   # side-switch arrow x + 0x48
    (0x80124524, 0x000000e4, 0x000000d4),   # right-hand box x
]
RAW_SITES = [
    0x800189dc,     # level-up message "%sはレベル%uになった" (message window)
]


def _word(exe, exe_base, va, old=None):
    o = va - exe_base
    if old is not None:
        assert struct.unpack_from('<I', exe, o)[0] == old, 'unexpected code at %#x' % va
    return o


def patch(exe, exe_base, at, short_entry, raw_entry):
    # GETNAME's first word -> j at; its delay slot (lbu v0, 0xc(a0)) still runs, harmless:
    # the hook's own fallback redoes both instructions and continues at GETNAME + 8
    o = _word(exe, exe_base, GETNAME, GETNAME_FIRST)
    assert struct.unpack_from('<I', exe, o + 4)[0] == 0x9082000c
    exe[o:o + 4] = asm.assemble(GETNAME, [('j', at)])
    for va in READING_SITES:
        struct.pack_into('<I', exe, _word(exe, exe_base, va, READING_OLD), READING_NEW)
    jal = asm.assemble(0, [('jal', GETNAME)])
    for va in SHORT_SITES:
        o = _word(exe, exe_base, va)
        assert exe[o:o + 4] == jal, 'no jal GETNAME at %#x' % va
        exe[o:o + 4] = asm.assemble(va, [('jal', short_entry)])
    for va in MID_SITES:
        o = _word(exe, exe_base, va)
        assert exe[o:o + 4] == jal, 'no jal GETNAME at %#x' % va
        exe[o:o + 4] = asm.assemble(va, [('jal', short_entry + 8)])
    for va, old, new in PEOPLE_LIST:
        struct.pack_into('<I', exe, _word(exe, exe_base, va, old), new)
    for va in RAW_SITES:
        o = _word(exe, exe_base, va)
        assert exe[o:o + 4] == asm.assemble(0, [('jal', MSGW)]), 'no jal message window at %#x' % va
        w = struct.unpack_from('<I', exe, o + 4)[0]
        assert w >> 26 == 9 and (w >> 16) & 31 == 6 and w & 0xffff == 0x0c, 'no addiu a2, rX, 0xc at %#x' % va
        exe[o:o + 4] = asm.assemble(va, [('jal', raw_entry)])


# ---------------------------------------------------------------- commands
def main():
    a = sys.argv[1:]
    if not a:
        sys.exit(__doc__)
    if a[0] == 'show':
        en = officers()
        for i, (jp, kana) in enumerate(zip(japanese(), readings())):
            if len(a) < 2 or a[1] in jp or a[1] in en.get(i, ''):
                print('%3d  %-10s %-14s %s' % (i, jp, kana, en.get(i, '')))
    elif a[0] == 'check':
        errs = check()
        print('\n'.join(errs) or 'ok: %d officers' % len(officers()))
        sys.exit(1 if errs else 0)
    else:
        sys.exit(__doc__)


if __name__ == '__main__':
    main()
