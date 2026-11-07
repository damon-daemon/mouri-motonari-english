"""Redraw the two kanji stat icons of the battle/duel status panel (GRAPHIC/BA_BACK.BIN).

BA_BACK.BIN is a 4bpp texture of 512-byte rows (1024 px; uploaded to VRAM (640, 416)).
Rows 0-15 at x 896-959 hold four 16x16 icons: Lv, 耐 (Endurance), 技 (Skill), Ex. The panel
shows them beside the level, Endurance and Skill bars and the experience in attack scenes
and Training Ground duels. 耐 and 技 are redrawn as "En" and "Sk" in the style of the
existing "Ex" icon (capital in columns 3-7, small letter in 9-12, blue corner patch):
the "Ex" icon is copied and its letters replaced. Own pixel art (two letters on a frame).

  python tools/baback.py preview out.png
"""
import os, sys

ISO_NAME = 'GRAPHIC/BA_BACK.BIN'
ROW = 512
EX_X = 944                     # the "Ex" icon (template)
TARGETS = {912: 'En', 928: 'Sk'}

# inner 10x10 (columns 3-12, rows 3-12); '.' = keep the template pixel
# palette: f = icon fill, 5 = ink, c = soft shade (left of / above strokes), 6 = blue patch
CAP = {
    'E': None,                 # the template's own E
    'S': ['fffff',             # no shade pixels: they read as a smear behind the S
          'f5555',
          '5ffff',
          '5ffff',
          'f555f',
          'ffff5',
          'ffff5',
          'ffff5',
          'ffff5',
          '5555f'],
}
SMALL = {                      # columns 8-12, rows 7-12
    'n': ['f.fff',
          'f555f',
          'f5ff5',
          'f5ff5',
          'f5ff5',
          'f5ff5'],
    'k': ['ff5ff',
          'ff5f5',
          'ff55f',
          'ff5f5',
          'ff5f5',
          'ff5f5'],
}


def _get(d, x, y):
    b = d[y * ROW + x // 2]
    return (b >> 4) if x & 1 else (b & 15)


def _put(d, x, y, v):
    o = y * ROW + x // 2
    d[o] = (d[o] & 0x0f) | (v << 4) if x & 1 else (d[o] & 0xf0) | v


def build(data):
    d = bytearray(data)
    for x0, (cap, small) in TARGETS.items():
        for y in range(16):                      # start from a copy of the Ex icon
            for x in range(16):
                _put(d, x0 + x, y, _get(d, EX_X + x, y))
        if CAP[cap]:
            for r, line in enumerate(CAP[cap]):
                for c, ch in enumerate(line):
                    _put(d, x0 + 3 + c, 3 + r, int(ch, 16))
        for r, line in enumerate(SMALL[small]):
            for c, ch in enumerate(line):
                if ch != '.':
                    _put(d, x0 + 8 + c, 7 + r, int(ch, 16))
    return bytes(d), len(TARGETS)


def main():
    a = sys.argv[1:]
    if a[:1] != ['preview'] or len(a) != 2:
        sys.exit(__doc__)
    from PIL import Image
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    src = open(os.path.join(root, 'extract', ISO_NAME), 'rb').read()
    new, _ = build(src)
    im = Image.new('L', (64, 34), 0)
    for i, d in enumerate((src, new)):
        for y in range(16):
            for x in range(64):
                im.putpixel((x, y + 18 * i), 255 - _get(d, 896 + x, y) * 17)
    im.resize((64 * 8, 34 * 8), Image.NEAREST).save(a[1])


if __name__ == '__main__':
    main()
