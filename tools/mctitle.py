"""Memory-card file title (the 64-byte Shift-JIS title in the save's header, shown by the console's
memory-card screen, which has no ASCII glyphs).

The game builds a save description (0x8001622c: "毛利%s%s：" + episode title + battle/place, our
English "Motonari1: Ep.21 Battle of ...") for its own load/save list, and 0x80012498 copies it into
the card header cut right after the first 話 (strstr with the string at 0x801240b4) ->
"毛利元就１：第二十一話". English: the memcpy there (0x800124e0) -> TITLE in the blob, which writes
the description as full-width Shift-JIS (macron letters as plain o/u/O/U) up to the first double
space (the episode strings end with two spaces: "Motonari 2: Ep.21"), at most 31 characters,
NUL-terminated.
"""
import struct
import asm

COPY_AT = 0x800124e0            # jal memcpy(s2 = header title, s0 = description, s1 = length)
MEMCPY = 0x800a931c
MACRON = {'^': 'ｏ', '~': 'ｕ', '|': 'Ｏ', '`': 'Ｕ', '"': '”', "'": '’'}


def table():
    """96 big-endian Shift-JIS pairs for the bytes 0x20-0x7f."""
    out = b''
    for c in range(0x20, 0x80):
        ch = chr(c)
        fw = MACRON.get(ch, '　' if ch == ' ' else chr(c + 0xFEE0))
        try:
            b = fw.encode('cp932')
        except UnicodeEncodeError:
            b = '　'.encode('cp932')
        assert len(b) == 2, ch
        out += b
    return out


def blob(at):
    """-> (bytes, TITLE entry) of the blob part at `at` (4-aligned): table, then code."""
    tab = table()
    code_at = at + len(tab)
    lines = [
        ('addiu', 't3', 'a0', 62),             # last start for a 2-byte character (NUL after)
        ('lui', 't5', asm.hi(at)),
        ('addiu', 't5', 't5', asm.lo(at)),
        'loop:',
        ('lbu', 't0', 0, 'a1'),
        ('nop',),
        ('beqz', 't0', 'end'),
        ('sltu', 't1', 'a0', 't3'),
        ('beqz', 't1', 'end'),
        ('addiu', 'a1', 'a1', 1),
        ('sltiu', 't1', 't0', 0x80),
        ('bnez', 't1', 'ascii'),
        ('nop',),
        ('lbu', 't2', 0, 'a1'),                # Shift-JIS pair: copy
        ('addiu', 'a1', 'a1', 1),
        ('sb', 't0', 0, 'a0'),
        ('sb', 't2', 1, 'a0'),
        ('b', 'loop'),
        ('addiu', 'a0', 'a0', 2),
        'ascii:',
        ('addiu', 't1', 't0', -0x20),
        ('bnez', 't1', 'notspace'),
        ('sltiu', 't2', 't1', 0x60),
        ('lbu', 't4', 0, 'a1'),                # space: a second space follows -> stop
        ('nop',),                              # (load delay)
        ('addiu', 't4', 't4', -0x20),
        ('beqz', 't4', 'end'),
        ('nop',),
        'notspace:',
        ('beqz', 't2', 'loop'),                # control byte: skip
        ('sll', 't1', 't1', 1),
        ('addu', 't1', 't1', 't5'),
        ('lbu', 't0', 0, 't1'),
        ('lbu', 't2', 1, 't1'),
        ('nop',),
        ('sb', 't0', 0, 'a0'),
        ('sb', 't2', 1, 'a0'),
        ('b', 'loop'),
        ('addiu', 'a0', 'a0', 2),
        'end:',
        ('sb', 'zero', 0, 'a0'),
        ('jr', 'ra'),
        ('sb', 'zero', 1, 'a0')]
    return tab + asm.assemble(code_at, lines), code_at


def patch(exe, exe_base, entry):
    o = COPY_AT - exe_base
    assert struct.unpack_from('<I', exe, o)[0] == 0x0c000000 | (MEMCPY >> 2) & 0x3ffffff, 'unexpected code at %#x' % COPY_AT
    struct.pack_into('<I', exe, o, 0x0c000000 | (entry >> 2) & 0x3ffffff)


def convert(desc):
    """Python model of TITLE (tests): description bytes -> header title bytes."""
    tab, out, i = table(), b'', 0
    while i < len(desc) and desc[i] and len(out) < 62:
        c = desc[i]; i += 1
        if c >= 0x80:
            out += desc[i - 1:i + 1]; i += 1
            continue
        if c == 0x20 and i < len(desc) and desc[i] == 0x20:
            break
        if c >= 0x20:
            out += tab[2 * (c - 0x20):2 * (c - 0x20) + 2]
    return out
