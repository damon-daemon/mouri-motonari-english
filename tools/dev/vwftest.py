"""Run the blob's measuring functions (vwf.py pixw12/pixw16/capw/msgw) in a MIPS emulator (unicorn)
and compare with the Python widths.

usage: .venv/bin/python tools/dev/vwftest.py
"""
import os, struct, sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
import vwf
from unicorn import Uc, UC_ARCH_MIPS, UC_MODE_MIPS32, UC_MODE_LITTLE_ENDIAN
from unicorn.mips_const import UC_MIPS_REG_A0, UC_MIPS_REG_A1, UC_MIPS_REG_V0, UC_MIPS_REG_RA, UC_MIPS_REG_SP

BASE = 0x80196000
STR = 0x80100000
RET = 0x80000100


def run(entry, data, s, a1=0):
    uc = Uc(UC_ARCH_MIPS, UC_MODE_MIPS32 + UC_MODE_LITTLE_ENDIAN)
    uc.mem_map(0, 0x200000)                             # KSEG0 0x80000000 -> physical 0
    uc.mem_write(BASE & 0x1fffffff, data)
    uc.mem_write(STR & 0x1fffffff, s + b'\0')
    uc.mem_write(RET & 0x1fffffff, struct.pack('<2I', 0, 0))        # nop; nop
    uc.reg_write(UC_MIPS_REG_A0, STR)
    uc.reg_write(UC_MIPS_REG_A1, a1)
    uc.reg_write(UC_MIPS_REG_RA, RET)
    uc.reg_write(UC_MIPS_REG_SP, 0x801ff000)
    uc.emu_start(entry, RET, count=100000)
    return uc.reg_read(UC_MIPS_REG_V0)


def main():
    lab, data = vwf.listing(BASE)
    bad = 0

    def check(name, got, want):
        nonlocal bad
        bad += got != want
        print('%-44s %4d %4d%s' % (name, got, want, '' if got == want else '  <-- FAIL'))
    for t in ['', 'Aki Province', 'The quick brown fox, jumps!', 'iiii', 'WWW mmm 0123']:
        check('pixw12 %r' % t, run(lab['pixw12'], data, t.encode()), vwf.width(t))
    jp = '安芸の国'.encode('cp932')
    s = b'A' + jp + b'\x1b=1B'
    check('pixw12 A+4 kanji+ESC', run(lab['pixw12'], data, s), vwf.width('AB') + 48)
    check('pixw16 A+4 kanji+ESC', run(lab['pixw16'], data, s), vwf.width('AB') + 64)
    check('pixw a1=12 first line', run(lab['pixw'], data, b'Abc\nWWWWW', 12), vwf.width('Abc'))
    rows = ['Short row', 'A much longer row of text', 'mid row']
    buf = b''.join(r.encode().ljust(0x27, b'\0') for r in rows)
    check('capw', run(lab['capw'], data, buf, len(rows)), max(map(vwf.width, rows)))
    check('capw 1 row', run(lab['capw'], data, buf, 1), vwf.width(rows[0]))
    msg = 'Battle of Arita\nVictory\n  1. Takeda Motoshige retreats\nDefeat'
    check('msgw 4 lines', run(lab['msgw'], data, msg.encode(), 3), max(map(vwf.width, msg.split('\n'))))
    check('msgw 1 line + kanji', run(lab['msgw'], data, b'Ab' + jp, 0), vwf.width('Ab') + 64)
    bad += names_test()
    bad += title_test()
    bad += town_test()
    sys.exit('%d failures' % bad if bad else 0)


def names_test():
    """GETNAME 0x800190d4 in the patched MAIN.EXE: English by record, fallback = the original
    digit stripping (record outside the table, record without English)."""
    import build, iso, names, setup
    disc = iso.Disc(setup.CLEAN)
    recs = disc.records()
    exe = bytearray(disc.file(iso.EXE_NAME, recs))
    build.patch_exe(exe)
    blob, lab = build.make_blob()
    build.patch_blob(exe, len(blob), lab['font12'])
    vwf.patch(exe, build.EXE_BASE, lab)
    names.patch(exe, build.EXE_BASE, lab['names'], lab['names_short'], lab['names_raw'])
    jp = names.japanese()
    bad = 0
    for rec, want in [(0, names.officers()[0]), (5, names.officers()[5]), (252, 'Retainer'),
                      (248, None), (None, None)]:
        uc = Uc(UC_ARCH_MIPS, UC_MODE_MIPS32 + UC_MODE_LITTLE_ENDIAN)
        uc.mem_map(0, 0x200000)
        uc.mem_write(0x10000, bytes(exe[0x800:]))
        uc.mem_write(build.BLOB & 0x1fffffff, blob)
        uc.mem_write(RET & 0x1fffffff, struct.pack('<2I', 0, 0))
        if rec is None:                                 # not in the table: e.g. 刀兵12 at 0x80100000
            a0, src = STR, '刀兵12'
        else:
            a0, src = names.OFFICERS + names.OFFICER_SIZE * rec, jp[rec]
        uc.mem_write((a0 + 0x0c) & 0x1fffffff, src.encode('cp932') + b'\0')
        uc.reg_write(UC_MIPS_REG_A0, a0)
        uc.reg_write(UC_MIPS_REG_RA, RET)
        uc.reg_write(UC_MIPS_REG_SP, 0x801ff000)
        uc.emu_start(names.GETNAME, RET, count=100000)
        v0 = uc.reg_read(UC_MIPS_REG_V0)
        got = bytes(uc.mem_read(v0 & 0x1fffffff, 40)).split(b'\0')[0].decode('cp932')
        exp = __import__('text').fold(want) if want else ''.join(c for c in src if not c.isdigit())
        ok = got == exp
        bad += not ok
        print('%-44s %s%s' % ('GETNAME %s' % rec, got, '' if ok else '  <-- FAIL (want %s)' % exp))
        if rec in (0, 5):                               # short / mid entries
            rows = names._rows(full=True)
            for label, entry, px in (('short', lab['names_short'], names.SHORT_PX),
                                     ('mid', lab['names_short'] + 8, names.MID_PX)):
                uc.reg_write(UC_MIPS_REG_A0, a0)
                uc.reg_write(UC_MIPS_REG_RA, RET)
                uc.emu_start(entry, RET, count=100000)
                v0 = uc.reg_read(UC_MIPS_REG_V0)
                g = bytes(uc.mem_read(v0 & 0x1fffffff, 40)).split(b'\0')[0].decode('cp932')
                e = __import__('text').fold(names._short(rows[rec], px))
                bad += g != e
                print('%-44s %s%s' % ('GETNAME %s %s' % (label, rec), g, '' if g == e else '  <-- FAIL (want %s)' % e))
        if rec == 5:                                    # level-up wrapper: a2 = record + 0x0c
            from unicorn.mips_const import UC_MIPS_REG_A2
            uc.reg_write(UC_MIPS_REG_A2, a0 + 0x0c)
            uc.reg_write(UC_MIPS_REG_A0, 0x1234)
            uc.reg_write(UC_MIPS_REG_RA, RET)
            uc.emu_start(lab['names_raw'], names.MSGW, count=100000)
            a2 = uc.reg_read(UC_MIPS_REG_A2)
            got2 = bytes(uc.mem_read(a2 & 0x1fffffff, 40)).split(b'\0')[0].decode('cp932')
            ok = got2 == exp and uc.reg_read(UC_MIPS_REG_A0) == 0x1234 and uc.reg_read(UC_MIPS_REG_SP) == 0x801ff000
            bad += not ok
            print('%-44s %s%s' % ('level-up wrapper', got2, '' if ok else '  <-- FAIL'))
    return bad


def title_test():
    """mctitle TITLE (memory-card header title) against its Python model."""
    import build, mctitle
    from unicorn.mips_const import UC_MIPS_REG_A0, UC_MIPS_REG_A1
    blob, lab = build.make_blob()
    bad = 0
    for d in [b'Motonari 1: Ep.21  Arita Castle, Turn  3', b'Terumoto \x82\x50: Final Ep.  Kizu',
              b'Motonari 1: Ending  Yoshida-K^riyama Castle', b'Motonari 1: Yoshida-K^riyama Castle Grounds and more', b'']:
        uc = Uc(UC_ARCH_MIPS, UC_MODE_MIPS32 + UC_MODE_LITTLE_ENDIAN)
        uc.mem_map(0, 0x200000)
        uc.mem_write(build.BLOB & 0x1fffffff, bytes(blob))
        uc.mem_write(0x100000, d + b'\0')
        uc.mem_write(0x110000, b'\xee' * 70)
        uc.reg_write(UC_MIPS_REG_A0, 0x80110000)
        uc.reg_write(UC_MIPS_REG_A1, 0x80100000)
        uc.reg_write(UC_MIPS_REG_RA, RET)
        uc.emu_start(lab['title'], RET, count=10000)
        exp = mctitle.convert(d)
        got = bytes(uc.mem_read(0x110000, len(exp) + 2))
        ok = got == exp + bytes(2)
        bad += not ok
        print('%-44s %s%s' % ('TITLE %r' % d[:20], exp.decode('cp932'), '' if ok else '  <-- FAIL'))
    return bad


def town_test():
    """datae3 TOWN(id): English town name from the blob table, NULL for id >= 12."""
    import build, datae3, text
    from unicorn.mips_const import UC_MIPS_REG_A0
    blob, lab = build.make_blob()
    tl = datae3.load_tl()
    bad = 0
    for i in (0, 6, 11, 12, 200):
        uc = Uc(UC_ARCH_MIPS, UC_MODE_MIPS32 + UC_MODE_LITTLE_ENDIAN)
        uc.mem_map(0, 0x200000)
        uc.mem_write(build.BLOB & 0x1fffffff, bytes(blob))
        uc.mem_write(RET & 0x1fffffff, struct.pack('<2I', 0, 0))
        uc.reg_write(UC_MIPS_REG_A0, i)
        uc.reg_write(UC_MIPS_REG_RA, RET)
        uc.emu_start(lab['town'], RET, count=1000)
        v = uc.reg_read(UC_MIPS_REG_V0)
        got = bytes(uc.mem_read(v & 0x1fffffff, 32)).split(b'\0')[0] if v else None
        exp = text.fold(tl['town:%d' % i]).encode('ascii') if i < 12 else None
        bad += got != exp
        print('TOWN %-3d %r%s' % (i, got, '' if got == exp else '  <-- FAIL'))
    return bad


if __name__ == '__main__':
    main()
