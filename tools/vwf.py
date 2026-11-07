"""Variable-width English text: our proportional font (pixfont.py) for single bytes 0x20-0x7f in
both font modes, a per-character advance in the printer, and pixel measuring where the game
sizes or centres text (notes/survey.md, session 4).

Printer: putchar 0x8001ab40(font, byte, mode) draws a character with 0x8001b9b8 (jal at
0x8001ae90, a3 = code) and then advances font+4 (x): single bytes (code < 0x200) by 8 * (1|2,
flag 0x40 = double width) at 0x8001af00. The hook `wrap` remembers the code of the draw call and
`adv` advances 0x20-0x7f by their width from a table in the blob instead.

Glyphs: the 1-byte glyph routine 0x8001b354 draws 8x12 cells in the 12-px mode (patched in
build.py to cell = c - 0x20 in FONT12) and 8x16 cells from the game's ASCII table 0x80100544 in
the 16-px mode (0x8001b48c/0x8001b49c: the table address -> FONT16 = our glyphs, 12 rows from
row FONT16_TOP of the 16-row cell).

  font() -> 96 x 12 B; font16() -> 96 x 16 B; width(text) -> pixels; listing(at) -> (labels, bytes)
"""
import os, struct, sys

sys.path.insert(0, os.path.dirname(__file__))
import asm, pixfont

_G = pixfont.glyphs()
WIDTHS = bytes(_G[chr(c)][1] if chr(c) in _G else 8 for c in range(0x20, 0x80))
FONT16_TOP = 2                    # 16-px cell row of our row 0 (baseline row 8 -> 10)

DRAW = 0x8001b9b8                 # putchar's glyph draw (a3 = code)
DRAW_AT = 0x8001ae90              # jal DRAW
ADV_AT = 0x8001af00               # single-byte advance: lw v0, 4(s1) / sll v1, v1, 3 / j / addu
ADV_RET = 0x8001af24              # sw v0, 4(s1)
G16_AT = (0x8001b48c, 0x8001b49c) # lui v0, 0x8010 / addiu v0, v0, 0x544 (ASCII 8x16 table)
SETX, SETY = 0x8001a8d0, 0x8001a938   # (font, x px) / (font, y px)
FONT_OBJ = 0x800c091c             # the text font object (flags byte 0x80 = 12-px mode)
LINE_MAX = 0x50                   # line builder: stack buffer sp+0x10..sp+0x68 (88 B)


def font():
    """96 cells x 12 rows (bit 7 = left), characters 0x20-0x7f."""
    out = bytearray()
    for c in range(0x20, 0x80):
        out += _G[chr(c)][0] if chr(c) in _G else bytes(12)
    return bytes(out)


def font16():
    f, out = font(), bytearray()
    for i in range(96):
        out += bytes(FONT16_TOP) + f[12 * i:12 * i + 12] + bytes(4 - FONT16_TOP)
    return bytes(out)


def width(s):
    """Pixel width of an ASCII string (macron letters count as their ASCII codes; other
    non-ASCII = a full-width KFONT glyph, 12 px)."""
    return sum(WIDTHS[ord(pixfont.MACRONS.get(c, c)) - 0x20] if ord(pixfont.MACRONS.get(c, c)) < 0x80
               else 12 for c in s)


def _code(char, widths):
    return [
        'wrap:',                                  # jal DRAW in putchar comes here
        ('lui', 't0', asm.hi(char)),
        ('j', DRAW),
        ('sw', 'a3', asm.lo(char), 't0'),
        'adv:',                                   # v0 = x, v1 = 1 or 2 (double width)
        ('lui', 't0', asm.hi(char)),
        ('lw', 't0', asm.lo(char), 't0'),
        ('addiu', 'v1', 'v1', -1),
        ('addiu', 't1', 't0', -0x20),
        ('sltiu', 't2', 't1', 0x60),
        ('beqz', 't2', 'fixed'),
        ('lui', 't2', asm.hi(widths)),
        ('addu', 't2', 't2', 't1'),
        ('lbu', 't1', asm.lo(widths), 't2'),
        ('nop',),
        ('sllv', 't1', 't1', 'v1'),
        ('j', ADV_RET),
        ('addu', 'v0', 'v0', 't1'),
        'fixed:',
        ('addiu', 't1', 'zero', 8),
        ('sllv', 't1', 't1', 'v1'),
        ('j', ADV_RET),
        ('addu', 'v0', 'v0', 't1'),

        'pixw12:',          # pixw with 12-px pairs (in place of strlen * 6)
        ('b', 'pw'),
        ('addiu', 't3', 'zero', 12),
        'pixw16:',          # pixw with 16-px pairs (strlen * 8)
        ('b', 'pw'),
        ('addiu', 't3', 'zero', 16),
        'pixw:',            # a0 = text, a1 = width of an SJIS pair -> v0 = width of the first
        ('addu', 't3', 'a1', 'zero'),             # line, a0 after its end, v1 = the end
        'pw:',                                    # ('\n' or 0); uses t0-t3 only
        ('addu', 'v0', 'zero', 'zero'),
        'next:',
        ('lbu', 't0', 0, 'a0'),
        ('nop',),
        ('beqz', 't0', 'ret'),
        ('addiu', 'a0', 'a0', 1),
        ('sltiu', 't1', 't0', 0x80),
        ('beqz', 't1', 'high'),
        ('sltiu', 't1', 't0', 0x20),
        ('bnez', 't1', 'ctl'),
        ('lui', 't2', asm.hi(widths - 0x20)),
        ('addu', 't2', 't2', 't0'),
        ('lbu', 't1', asm.lo(widths - 0x20), 't2'),
        ('b', 'next'),
        ('addu', 'v0', 'v0', 't1'),
        'high:',                                  # SJIS pair, half-width kana 0xa0-0xdf 8 px
        ('sltiu', 't1', 't0', 0xa0),
        ('bnez', 't1', 'pair'),
        ('sltiu', 't1', 't0', 0xe0),
        ('beqz', 't1', 'pair'),
        ('nop',),
        ('b', 'next'),
        ('addiu', 'v0', 'v0', 8),
        'pair:',
        ('addiu', 'a0', 'a0', 1),
        ('b', 'next'),
        ('addu', 'v0', 'v0', 't3'),
        'ctl:',
        ('addiu', 't1', 'zero', 0x0a),
        ('beq', 't0', 't1', 'ret'),
        ('addiu', 't1', 'zero', 0x1b),
        ('bne', 't0', 't1', 'next'),              # ESC + 2 bytes: no width
        ('nop',),
        ('b', 'next'),
        ('addiu', 'a0', 'a0', 2),
        'ret:',
        ('jr', 'ra'),
        ('addu', 'v1', 't0', 'zero'),

        'pixwf:',           # pixw with the pair width of FONT_OBJ's mode (12 or 16)
        ('lui', 't0', asm.hi(FONT_OBJ)),
        ('lbu', 't0', asm.lo(FONT_OBJ), 't0'),
        ('nop',),
        ('andi', 't0', 't0', 0x80),
        ('beqz', 't0', 'pw'),
        ('addiu', 't3', 'zero', 16),
        ('b', 'pw'),
        ('addiu', 't3', 'zero', 12),

        'capw:',            # caption rows: a0 = first row (0x27 bytes each), a1 = count ->
        ('addu', 't4', 'ra', 'zero'),             # v0 = widest row in pixels (16-px font)
        ('addu', 't5', 'zero', 'zero'),
        ('addu', 't6', 'a0', 'zero'),
        ('addu', 't7', 'a1', 'zero'),
        'crow:',
        ('beqz', 't7', 'cdone'),
        ('addu', 'a0', 't6', 'zero'),
        ('jal', 'pixw16'),
        ('addiu', 't6', 't6', 0x27),
        ('sltu', 't1', 't5', 'v0'),
        ('beqz', 't1', 'crow'),
        ('addiu', 't7', 't7', -1),
        ('b', 'crow'),
        ('addu', 't5', 'v0', 'zero'),
        'cdone:',
        ('jr', 't4'),
        ('addu', 'v0', 't5', 'zero'),

        'msgw:',            # message window: a0 = text ('\n' lines), a1 = lines - 1 ->
        ('addu', 't4', 'ra', 'zero'),             # v0 = widest line in pixels (16-px font),
        ('addu', 't5', 'zero', 'zero'),           # v1 = lines * 16
        ('addiu', 't6', 'a1', 1),
        'mrow:',
        ('jal', 'pixw16'),
        ('nop',),
        ('sltu', 't1', 't5', 'v0'),
        ('beqz', 't1', 'mnext'),
        ('nop',),
        ('addu', 't5', 'v0', 'zero'),
        'mnext:',
        ('bnez', 'v1', 'mrow'),                   # v1 = the line's end ('\n' or 0)
        ('nop',),
        ('sll', 'v1', 't6', 4),
        ('jr', 't4'),
        ('addu', 'v0', 't5', 'zero'),

        'capxy:',           # (font, x px, y px): in place of 0x8001a99c (font, column, y)
        ('addiu', 'sp', 'sp', -0x20),
        ('sw', 'ra', 0x10, 'sp'),
        ('sw', 'a0', 0x14, 'sp'),
        ('jal', SETX),
        ('sw', 'a2', 0x18, 'sp'),
        ('lw', 'a0', 0x14, 'sp'),
        ('lw', 'a1', 0x18, 'sp'),
        ('jal', SETY),
        ('nop',),
        ('lw', 'ra', 0x10, 'sp'),
        ('nop',),
        ('jr', 'ra'),
        ('addiu', 'sp', 'sp', 0x20),
    ]


def _sites(lab):
    """[(address, original words, new instructions; None = keep the word, int = data word)]"""
    f16 = lab['font16']
    return [
        (DRAW_AT, [0x0c006e6e], [('jal', lab['wrap'])]),
        (ADV_AT, [0x8e220004, 0x000318c0, 0x08006bc9, 0x00431021],
         [('j', lab['adv']), ('lw', 'v0', 4, 's1'), ('nop',), ('nop',)]),
        (G16_AT[0], [0x3c028010], [('lui', 'v0', asm.hi(f16))]),
        (G16_AT[1], [0x24420544], [('addiu', 'v0', 'v0', asm.lo(f16))]),
        # line builder 0x8003de8c(x, y, text, limit, [sp+0x10] centre): column cut -> LINE_MAX
        # bytes (English is wrapped by pixels at build time); centring x += (limit - strlen) * 4
        # -> limit * 4 - pixw / 2
        (0x8003def0, [0x32f500ff], [('addiu', 's5', 'zero', LINE_MAX)]),
        (0x8003e03c, [0x0c02a497, 0x27a40010, 0x32e300ff, 0x304200ff, 0x00621823, 0x00031880,
                      0x02c3b021], [
            ('jal', lab['pixwf']),
            ('addiu', 'a0', 'sp', 0x10),
            ('andi', 'v1', 's7', 0xff),
            ('sll', 'v1', 'v1', 2),
            ('srl', 'v0', 'v0', 1),
            ('subu', 'v1', 'v1', 'v0'),
            ('addu', 's6', 's6', 'v1')]),
        # centred print 0x8001bb94(font, columns, text): (columns * c - strlen * c) / 2, c = 6|8
        (0x8001bbd8, [0x0c02a497, 0x02602021, 0x00500018, 0x00001812], [
            ('sll', 'a1', 's0', 1),
            ('jal', lab['pixw']),
            ('addu', 'a0', 's3', 'zero'),
            ('addu', 'v1', 'v0', 'zero')]),
        # caption 0x8003f4e4 (op 0x29 places, chapter cards): rows of 0x27 bytes at sp+0x20,
        # s1 = longest row (bytes), s3 = rows - 1; text column s5 = 20 - s1 / 2, y s6 = 0x78 -
        # 8 * rows; box x = 8 * s5 - 16, w = 8 * s1 + 32 -> s5 = text x in pixels, centred
        (0x8003f59c, [0x2e220027, 0x10400005, 0x26730001, 0x00111842, 0x24020014, 0x0800fd6f,
                      0x0043a823, 0x0000a821, 0x001318c0, 0x24020078, 0x0043b023, 0x001188c0,
                      0x26310020], [
            # 0x8003f538 (last row not the longest) branches to 0x8003f5a0: the row count
            # increment must sit there, not at 0x8003f59c (else only the first row is drawn)
            ('nop',),
            ('addiu', 's3', 's3', 1),
            ('addiu', 'a0', 'sp', 0x20),
            ('jal', lab['capw']),
            ('addu', 'a1', 's3', 'zero'),
            ('srl', 'v1', 'v0', 1),
            ('addiu', 's5', 'zero', 160),
            ('subu', 's5', 's5', 'v1'),
            ('sll', 'v1', 's3', 3),
            ('addiu', 's6', 'zero', 0x78),
            ('subu', 's6', 's6', 'v1'),
            ('addiu', 's1', 'v0', 0x20),
            ('nop',)]),
        (0x8003f5e4, [0x001528c0], [('addu', 'a1', 's5', 'zero')]),
        # People (by episode): footer box with the cursor episode's full title: window
        # 0x80075bec(x 0x48, y 0xa4, w 0xb0, h 0x18) at 0x8008342c, title centred over 26 columns
        # from x 0x52, text area cleared by 0x8001b20c(0x50, 0xa8, 0xa0, 0x10) -> window x 8 w 248
        # (L1/R1 arrows at x 256 / 288), title over 40 columns (240 px) from x 12 (titles <= 227 px)
        (0x8008342c, [0x24050048], [('addiu', 'a1', 'zero', 0x08)]),
        (0x80083434, [0x240700b0], [('addiu', 'a3', 'zero', 0xf8)]),
        (0x80083678, [0x24050052], [('addiu', 'a1', 'zero', 0x0c)]),
        (0x800836a4, [0x2405001a], [('addiu', 'a1', 'zero', 40)]),   # 12-px font: 6-px columns
        (0x80083718, [0x24040050], [('addiu', 'a0', 'zero', 0x0c)]),
        (0x80083720, [0x240600a0], [('addiu', 'a2', 'zero', 0xf0)]),
        (0x8003f650, [0x0c006a67], [('jal', lab['capxy'])]),
        # message window 0x8003f828(type, fmt, ...) (all EXE prompts, goals / victory
        # conditions op 0x2c): text at 0x800fdc68, a0 = lines - 1, s2 = longest line (bytes,
        # rounded up to 4) -> box w fp = 8 * s2 + 32, x [sp+0x168] = 144 - 4 * s2, text column
        # 20 - s2 / 2 (+ [sp+0x160]) -> pixels: w = W + 32, x = 144 - W / 2, text x = x + 16
        (0x8003f99c, [0x24150078, 0x001210c0, 0x245e0020, 0x24820001, 0x00021900, 0x00121080,
                      0x240900a0, 0x01221023, 0x2442fff0, 0xafa20168], [
            ('addiu', 's5', 'zero', 0x78),
            ('addu', 'a1', 'a0', 'zero'),
            ('lui', 'a0', 0x8010),
            ('jal', lab['msgw']),
            ('addiu', 'a0', 'a0', -0x2398),
            ('addiu', 'fp', 'v0', 0x20),
            ('srl', 'v0', 'v0', 1),
            ('addiu', 't1', 'zero', 0x90),
            ('subu', 'v0', 't1', 'v0'),
            ('sw', 'v0', 0x168, 'sp')]),
        (0x8003fac8, [0x000928c2, 0xa0400000, 0x00121042, 0x00a22823, 0x25100001, 0x00103100,
                      0x8fa90160, 0x02a63021, 0x0c006a67, 0x00a92821], [
            ('lw', 'a1', 0x168, 'sp'), None, ('nop',), ('addiu', 'a1', 'a1', 16), None, None,
            ('nop',), None, ('jal', lab['capxy']), ('nop',)]),
        # name label 0x8002e270 (GETNAME of the unit's record, 12-px): x offset s0 =
        # ((12 - strlen) / 2) * 6 -> (72 - pixw12) / 2
        (0x8002e27c, [0x0c02a497, 0x00402021, 0x00021400, 0x00021403, 0x2403000c, 0x00621823,
                      0x000317c2, 0x00621821, 0x00031843, 0x00038040, 0x02038021, 0x0c006cb1,
                      0x00108040], [
            ('jal', lab['pixw12']),
            ('addu', 'a0', 'v0', 'zero'),
            ('addiu', 'v1', 'zero', 72),
            ('subu', 'v1', 'v1', 'v0'),
            ('sra', 's0', 'v1', 1),
            ('nop',), ('nop',), ('nop',), ('nop',), ('nop',), ('nop',),
            None,
            ('nop',)]),
        # menu 0x800599xx: widest item (strlen, twice) * 8 -> pixw16
        (0x80059a24, [0x0c02a497], [('jal', lab['pixw16'])]),
        (0x80059a3c, [0x0c02a497], [('jal', lab['pixw16'])]),
        (0x80059a74, [0x001290c0], [('nop',)]),
        # workshop list header: 名前 at x 0x24 + （%s） at x 0x44, Make at 0x74: "(Support)" ran
        # into "Make" -> x 0x41 = right after "Name " (the "(%s)" string is shared with the
        # merchant's sort tag, so it stays)
        (0x800714d4, [0x24050044], [('addiu', 'a1', 'zero', 0x41)]),
        # town-map place list (Square, 0x80025a14): 64-px box at x 0x18 / 0xe8 (table
        # 0x801243c0) -> 88 px: frame width, centred print columns 8 -> 12, cursor bar width,
        # right-hand box x, side-switch arrow x (left box)
        (0x80025ab8, [0x24070040], [('addiu', 'a3', 'zero', 0x58)]),
        (0x80025b6c, [0x24050008], [('addiu', 'a1', 'zero', 12)]),
        (0x80025940, [0x24060038], [('addiu', 'a2', 'zero', 0x50)]),
        (0x80025bb8, [0x24c6003c], [('addiu', 'a2', 'a2', 0x54)]),
        (0x801243c4, [0xe8], [0xd0]),
        # merchant: storehouse panel header 倉庫 at column 0x15 + （%s） at 0x1b (8-px columns):
        # "Storehouse" is 56 px -> "(%s)" at column 0x1d
        (0x80072f68, [0x2405001b], [('addiu', 'a1', 'zero', 0x1d)]),
        (0x80075390, [0x2405001b], [('addiu', 'a1', 'zero', 0x1d)]),     # same, sort-toggle redraw
        # merchant footer: Triangle icon x 0xa8 + sort label column 0x17: "Materials" ran into the
        # Gold box -> icon x 0xa0, label column 0x16
        (0x800752d0, [0x240600a8], [('addiu', 'a2', 'zero', 0xa0)]),
        (0x800752e0, [0x24050017], [('addiu', 'a1', 'zero', 0x16)]),
    ] + [s for jal, mul, reg in STRLEN6 for s in (
        (jal, [0x0c02a497], [('jal', lab['pixw12'])]),
        (mul, asm_words(mul, [('sll', reg, 'v0', 1), ('addu', reg, reg, 'v0'), ('sll', reg, reg, 1)]),
         [('addu', reg, 'v0', 'zero'), ('nop',), ('nop',)]))
    ] + [s for jal, mul, reg in STRLEN8 for s in (
        (jal, [0x0c02a497], [('jal', lab['pixw16'])]),
        (mul, asm_words(mul, [('sll', reg, 'v0', 3)]), [('addu', reg, 'v0', 'zero')]))]


def asm_words(va, lines):
    b = asm.assemble(va, lines)
    return list(struct.unpack('<%dI' % (len(b) // 4), b))


# strlen * 6 (12-px text) and strlen * 8 (16-px) used as pixel widths: (jal strlen, the
# multiply, its register) -> jal pixw12 / pixw16 and a move
STRLEN6 = [(0x8001694c, 0x80016960, 'a3'), (0x80059150, 0x80059158, 'v1'),
           (0x80059188, 0x80059190, 'v1'), (0x800591d4, 0x800591dc, 'v1'),
           (0x80059200, 0x80059208, 'v1'), (0x8006661c, 0x80066624, 'v1')]
STRLEN8 = [(0x80018544, 0x80018550, 'v0'), (0x8004336c, 0x80043380, 'a3'),
           (0x800551c8, 0x800551d4, 's4'), (0x80065910, 0x8006591c, 'v0'),
           (0x80069660, 0x80069670, 'v0')]


def listing(at):
    """-> (labels, bytes) of the blob part at `at`: font12, font16, char, widths, code."""
    font12, f16 = at, at + 96 * 12
    char = f16 + 96 * 16
    widths = char + 4
    code_at = widths + len(WIDTHS)
    code_at += -code_at & 3
    lines = _code(char, widths)
    lab = asm.labels(code_at, lines)
    lab.update(font12=font12, font16=f16, char=char, widths=widths)
    data = font() + font16() + bytes(4) + WIDTHS
    data += bytes(code_at - at - len(data))
    return lab, data + asm.assemble(code_at, lines)


def patch(exe, exe_base, lab):
    for va, old, new in _sites(lab):
        o = va - exe_base
        assert list(struct.unpack_from('<%dI' % len(old), exe, o)) == old, 'unexpected code at %#x' % va
        code = b''.join(struct.pack('<I', w) if n is None else struct.pack('<I', n) if isinstance(n, int)
                        else asm.assemble(va + 4 * i, [n])
                        for i, (w, n) in enumerate(zip(old, new)))
        exe[o:o + len(code)] = code
