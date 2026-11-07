"""Redraw the Japanese labels of the UI sprite sheet (GRAPHIC/MARK.E3) in English.

MARK.E3 (same layout as Oda Nobunaga Den's MARK.E4) holds 16-colour CLUTs at 0x20 * n (n = the CLUT field below) and, at SHEET, a 256x240
4bpp sheet that the game uploads to VRAM (320, 0). The sprite table TABLE in the program
(SPRITES entries of 12 bytes: page, u, v, w, h, clut; drawn by 0x80023b50(index, ?, x, y))
gives each label's rect; page 1 = this sheet.

A label is a textured plate (light top/left edge, dark bottom/right edge) with light kanji:
the lettering (pixels brighter than the plate) is inpainted from the plate around it, then
the English is drawn with the game's own pixel font (tools/pixfont.py, the VWF font) in a
light ink, centred; on the green buttons (CLUT 4) with a dark outline like the original.

WIDE: labels moved to a wider rect in the unused parts of the sheet (the plate is stretched
from the cleaned original); the program's table entry is patched to match. SITE_X: draw
sites whose x moves (a widened label that must grow to the left).

tl/gfx.txt: "index<TAB>English" (index into the sprite table).

  python tools/gfx.py preview out.png    sheet before/after (needs extract/)
"""
import os, random, struct, sys

sys.path.insert(0, os.path.dirname(__file__))
import pixfont, tinyfont

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TL = os.path.join(ROOT, 'tl', 'gfx.txt')
ISO_NAME = 'GRAPHIC/MARK.E3'
SHEET, SHEET_W, SHEET_H = 0x3920, 256, 240
TABLE, SPRITES = 0x800dd290, 228

# index -> new (u, v, w) in a free part of the sheet: rows 32-47 from x 96 and 208-223 from x 176
# are empty in the file and stay so in VRAM (checked in 7 states); rows 224-239 are empty in the
# file but the game uploads cursors/icons there at run time (x 0-24, 240-255): do not use them
WIDE = {
    28: (96, 32, 40),       # 武将 Officer: officer list header (names follow)
    37: (136, 32, 32),      # 装備 Equip
    38: (168, 32, 28),      # 金 Gold: grows to the left (SITE_X)
}
# (va, old word, new word): draw-site x changes
SITE_X = [(va, 0x24060000 | x, 0x24060000 | (x - 12)) for va, x in (    # addiu a2, zero, x
    (0x8006f188, 0xf0), (0x80070460, 0xf0), (0x80073e40, 0xf0), (0x8007460c, 0xf0),
    (0x8007526c, 0xf0), (0x80078778, 0xf4))]                 # 金 Gold


LIGHT = 100         # luma: lettering is brighter than this on the plates


def luma(c):
    return (c[0] * 299 + c[1] * 587 + c[2] * 114) // 1000


def rgb(v):
    return ((v & 31) << 3, ((v >> 5) & 31) << 3, ((v >> 10) & 31) << 3)


class Sheet:
    def __init__(self, data):
        self.d = bytearray(data)

    def pal(self, clut):
        return [rgb(v) for v in struct.unpack_from('<16H', self.d, 0x20 * clut)]

    def idx(self, x, y):
        b = self.d[SHEET + y * (SHEET_W // 2) + x // 2]
        return b >> 4 if x & 1 else b & 15

    def put(self, x, y, i):
        o = SHEET + y * (SHEET_W // 2) + x // 2
        self.d[o] = (self.d[o] & 0x0f) | (i << 4) if x & 1 else (self.d[o] & 0xf0) | i


def table(exe, exe_base):
    """-> [(page, u, v, w, h, clut)] from the program image."""
    return [struct.unpack_from('<6h', exe, TABLE - exe_base + 12 * k) for k in range(SPRITES)]


def load_tl(path=TL):
    out = {}
    if not os.path.exists(path):
        return out
    for n, line in enumerate(open(path, encoding='utf-8'), 1):
        line = line.rstrip('\n')
        if not line or line.startswith('#'):
            continue
        k, _, en = line.partition('\t')
        out[int(k)] = en
    return out


def text_width(text, g):
    return sum(g[c][1] for c in text) - pixfont.SPACING


def erase(sh, box, pal, seed):
    """Inpaint the light pixels inside box (x0, y0, x1, y1) from the plate around them."""
    x0, y0, x1, y1 = box
    rnd = random.Random(seed)
    todo = {(x, y) for y in range(y0, y1 + 1) for x in range(x0, x1 + 1) if luma(pal[sh.idx(x, y)]) > LIGHT}
    # on a light plate (green buttons) every dark pixel inside is the lettering's outline
    ls = sorted(luma(pal[sh.idx(x, y)]) for y in range(y0, y1 + 1) for x in range(x0, x1 + 1))
    if ls[len(ls) // 2] > 70:
        todo |= {(x, y) for y in range(y0, y1 + 1) for x in range(x0, x1 + 1) if luma(pal[sh.idx(x, y)]) < 40}
    near = [(dx, dy) for dx in range(-2, 3) for dy in range(-2, 3) if dx or dy]
    while todo:
        cand = {p: [(p[0] + dx, p[1] + dy) for dx, dy in near
                    if x0 <= p[0] + dx <= x1 and y0 <= p[1] + dy <= y1 and (p[0] + dx, p[1] + dy) not in todo]
                for p in sorted(todo)}
        best = max(len(v) for v in cand.values())
        if best == 0:
            # nothing known nearby: take any plate pixel of the box
            src = [sh.idx(x, y) for y in range(y0, y1 + 1) for x in range(x0, x1 + 1) if (x, y) not in todo]
            for p in sorted(todo):
                sh.put(p[0], p[1], rnd.choice(src))
            break
        layer = [p for p, v in cand.items() if len(v) >= min(best, 6)]
        for p in layer:
            sh.put(p[0], p[1], sh.idx(*rnd.choice(cand[p])))
        todo -= set(layer)


def stretch(sh, src, dst):
    """Copy the plate src (u, v, w, h) to dst (u, v, w) with w >= the source width: edge
    columns kept, inner columns repeated."""
    u, v, w, h = src
    nu, nv, nw = dst
    cols = list(range(u + 1, u + w - 1))
    for y in range(h):
        sh.put(nu, nv + y, sh.idx(u, v + y))
        sh.put(nu + nw - 1, nv + y, sh.idx(u + w - 1, v + y))
        for x in range(1, nw - 1):
            sh.put(nu + x, nv + y, sh.idx(cols[(x - 1) % len(cols)], v + y))


def draw(sh, box, text, pal, g):
    """English centred in box (x0, y0, x1, y1): light ink; dark outline where the plate is
    not dark (green buttons)."""
    x0, y0, x1, y1 = box
    bw, bh = x1 - x0 + 1, y1 - y0 + 1
    order = sorted(range(1, 16), key=lambda i: luma(pal[i]))
    ink = order[-1] if luma(pal[order[-1]]) < 240 else order[-2]       # brightest below pure white
    plate = sorted(luma(pal[sh.idx(x, y)]) for y in range(y0, y1 + 1) for x in range(x0, x1 + 1))
    outline = order[0] if plate[len(plate) // 2] > 70 else None
    if outline is not None:
        ink = order[-1]
    tw = text_width(text, g)
    if tw <= bw:
        # VWF font: caps 9 rows (pixfont rows 0-8), descenders 3 more: centre the caps
        top = y0 + (bh - 9) // 2 - (1 if outline is None and bh >= 14 else 0)
        ink_px, x = set(), x0 + (bw - tw + 1) // 2
        for c in text:
            rows, adv = g[c]
            for r in range(pixfont.CELL_H):
                for i in range(pixfont.CELL_W):
                    if rows[r] & (0x80 >> i):
                        ink_px.add((x + i, top + r))
            x += adv
    else:
        # tiny icons: 5x7 / 3x5 pixel capitals
        for font, cap in ((tinyfont.MID, 7), (tinyfont.SMALL, 5)):
            if any(c not in font for c in text):
                continue
            tw, _, px = tinyfont.render(text, font)
            if tw <= bw:
                break
        else:
            raise ValueError('%r is %d px, room %d' % (text, text_width(text, g), bw))
        ox, oy = x0 + (bw - tw + 1) // 2, y0 + (bh - cap) // 2
        ink_px = {(ox + x, oy + y) for x, y in px}
    inside = lambda p: x0 - 1 <= p[0] <= x1 + 1 and y0 - 1 <= p[1] <= y1 + 1
    if outline is not None:
        for (px, py) in ink_px:
            for dx in (-1, 0, 1):
                for dy in (-1, 0, 1):
                    q = (px + dx, py + dy)
                    if q not in ink_px and inside(q):
                        sh.put(q[0], q[1], outline)
    for p in ink_px:
        if not inside(p):
            raise ValueError('%r does not fit the box height' % text)
        sh.put(p[0], p[1], ink)


def build(mark, exe, exe_base, tl=None, strict=True):
    """-> (new MARK.E3 bytes, number of labels); patches the sprite table in exe for WIDE."""
    tl = load_tl() if tl is None else tl
    sh = Sheet(mark)
    sprites = table(exe, exe_base)
    g = pixfont.glyphs()
    errs = []
    for k, en in sorted(tl.items()):
        page, u, v, w, h, clut = sprites[k]
        assert page == 1, 'sprite %d is not on the MARK sheet' % k
        pal = sh.pal(clut)
        erase(sh, (u + 1, v + 1, u + w - 2, v + h - 2), pal, k)
        if k in WIDE:
            nu, nv, nw = WIDE[k]
            stretch(sh, (u, v, w, h), (nu, nv, nw))
            struct.pack_into('<3h', exe, TABLE - exe_base + 12 * k + 2, nu, nv, nw)
            u, v, w = nu, nv, nw
        try:
            draw(sh, (u + 1, v + 1, u + w - 2, v + h - 2), en, pal, g)
        except ValueError as e:
            errs.append('gfx %d: %s' % (k, e))
    if errs and strict:
        raise ValueError('\n'.join(errs))
    for e in errs:
        print(e)
    for va, old, new in SITE_X:
        o = va - exe_base
        assert struct.unpack_from('<I', exe, o)[0] == old, 'unexpected code at %#x' % va
        struct.pack_into('<I', exe, o, new)
    return bytes(sh.d), len(tl)


def image(data, exe, exe_base, scale=3):
    """The sheet as RGB, every sprite in its own CLUT (preview)."""
    from PIL import Image
    sh = Sheet(data)
    im = Image.new('RGB', (SHEET_W, SHEET_H), (255, 0, 255))
    for page, u, v, w, h, clut in table(exe, exe_base):
        if page != 1:
            continue
        pal = sh.pal(clut)
        for y in range(v, min(v + h, SHEET_H)):
            for x in range(u, min(u + w, SHEET_W)):
                im.putpixel((x, y), pal[sh.idx(x, y)])
    return im.resize((SHEET_W * scale, SHEET_H * scale), Image.NEAREST)


def main():
    a = sys.argv[1:]
    if a[:1] == ['preview']:
        from PIL import Image
        mark = open(os.path.join(ROOT, 'extract', ISO_NAME), 'rb').read()
        exe = bytearray(open(os.path.join(ROOT, 'extract', 'MAIN.EXE'), 'rb').read())
        base = 0x80010000 - 0x800
        before = image(mark, exe, base)
        new, n = build(mark, exe, base, strict=False)
        after = image(new, exe, base)
        top = int(a[2]) if len(a) > 2 else 0
        out = Image.new('RGB', (before.width, before.height * 2 + 6), (0, 0, 0))
        out.paste(before, (0, 0))
        out.paste(after, (0, before.height + 6))
        out.save(a[1])
        print('%d labels' % n)
    else:
        print(__doc__)


if __name__ == '__main__':
    main()
