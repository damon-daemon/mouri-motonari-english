"""March-map province labels (GRAPHIC/MMAP.E3).

MMAP.E3 = 135 frames of 38 sectors (0x13000 B): 512-B CLUT (256 x 15-bit) + 320 x 240 8-bpp
picture (uploaded to VRAM (320,256)). Frames 0-2 are the march maps (Aki area, west Chugoku +
Kyushu/Shikoku, Chugoku + Kinai) with the province names painted in as light-cyan kanji with a
dark outline; every other frame is a scene background without text.

Each label: the kanji box is found from the label's fill colour near a hand-picked centre, the box
(plus room for the English) is covered by a patch of nearby terrain (the offset whose surrounding
ring matches best and that holds no label pixels), then the English name is drawn centred on the
old label in the pixfont, light ink + dark outline in the nearest CLUT colours.

  python tools/mmap.py out.png      preview of frames 0-2 (3x) from the clean disc
"""
import os, random, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pixfont

ISO_NAME = 'GRAPHIC/MMAP.E3'
FRAME = 0x13000
W, H = 320, 240
PIC = 512

# (centre x, centre y, English) per frame; centres within a few px of the kanji label
LABELS = {
    0: [(247, 61, 'Izumo'), (85, 93, 'Iwami'), (190, 113, 'Aki'), (265, 120, 'Bingo'),
        (45, 182, 'Suō')],
    1: [(288, 55, 'Izumo'), (278, 93, 'Bingo'), (62, 121, 'Nagato'), (152, 115, 'Iwami'),
        (205, 110, 'Aki'), (138, 143, 'Suō'), (56, 173, 'Buzen'), (70, 203, 'Bungo'),
        (243, 209, 'Iyo')],
    2: [(220, 32, 'Echizen'), (273, 32, 'Mino'), (287, 54, 'Owari'), (307, 69, 'Mikawa'),
        (126, 79, 'Inaba'), (162, 69, 'Tajima'), (196, 91, 'Tanba'), (55, 114, 'Izumo'),
        (91, 108, 'Hōki'), (163, 114, 'Harima'), (198, 112, 'Settsu'), (225, 119, 'Yamashiro'),
        (258, 121, 'Ise'), (129, 125, 'Mimasaka'), (106, 148, 'Bizen'), (236, 153, 'Yamato'),
        (68, 170, 'Bitchū'), (30, 182, 'Aki'), (204, 192, 'Kii')],
}
SHIFT = {             # (frame, English) -> (dx, dy) to move the English off a neighbour
    (2, 'Settsu'): (-4, -4), (2, 'Yamashiro'): (8, 3), (2, 'Ise'): (10, 7), (2, 'Harima'): (-3, 0),
    (2, 'Mimasaka'): (0, 2), (2, 'Inaba'): (2, -1),
}
CAP = 9               # pixfont cap height (rows 0-8, baseline 8)


def rgb(c):
    return ((c & 31) << 3, ((c >> 5) & 31) << 3, ((c >> 10) & 31) << 3)


class Frame:
    def __init__(self, data, i):
        self.base = i * FRAME
        self.d = data
        self.pal = [rgb(int.from_bytes(data[self.base + 2 * j:self.base + 2 * j + 2], 'little'))
                    for j in range(256)]

    def idx(self, x, y):
        return self.d[self.base + PIC + y * W + x]

    def put(self, x, y, v):
        if 0 <= x < W and 0 <= y < H:
            self.d[self.base + PIC + y * W + x] = v

    def c(self, x, y):
        return self.pal[self.idx(x, y)]

    def fill(self, x, y):
        r, g, b = self.c(x, y)
        return b >= 150 and g >= 110 and b > r + 50

    def icon(self, x, y):
        r, g, b = self.c(x, y)
        return max(r, g, b) < 40 or (abs(r - g) < 16 and abs(g - b) < 16 and r > 60)

    def nearest(self, col, avoid=()):
        return min((j for j in range(256) if j not in avoid and self.pal[j] != (0, 0, 0) or j == 0),
                   key=lambda j: sum((a - b) ** 2 for a, b in zip(self.pal[j], col)))


def find_box(f, cx, cy):
    """Bounding box (x0, y0, x1, y1) of the label's fill pixels, outline + 1 px included."""
    pts = [(x, y) for y in range(cy - 8, cy + 9) for x in range(cx - 16, cx + 17)
           if 0 <= x < W and 0 <= y < H and f.fill(x, y)]
    if len(pts) < 15:
        raise ValueError('no label near (%d,%d)' % (cx, cy))
    xs, ys = [p[0] for p in pts], [p[1] for p in pts]
    return (max(min(xs) - 3, 0), max(min(ys) - 3, 0), min(max(xs) + 3, W - 1), min(max(ys) + 3, H - 1))


def ink_pixels(s, g):
    px, x = set(), 0
    for ch in s:
        ch = pixfont.MACRONS.get(ch, ch)
        rows, adv = g[ch]
        for r in range(pixfont.CELL_H):
            for i in range(pixfont.CELL_W):
                if rows[r] & (0x80 >> i):
                    px.add((x + i, r))
        x += adv
    return x - pixfont.SPACING, px


def patch(f, box, forbid):
    """Cover box with the nearby terrain patch whose 2-px ring best matches box's ring."""
    x0, y0, x1, y1 = box
    ring = [(x, y) for y in range(y0 - 2, y1 + 3) for x in range(x0 - 2, x1 + 3)
            if not (x0 <= x <= x1 and y0 <= y <= y1) and 0 <= x < W and 0 <= y < H]
    best = None
    for dy in range(-40, 41):
        for dx in range(-60, 61):
            if abs(dx) <= x1 - x0 + 2 and abs(dy) <= y1 - y0 + 2:
                continue                                  # overlaps itself
            sx0, sy0, sx1, sy1 = x0 + dx, y0 + dy, x1 + dx, y1 + dy
            if sx0 < 2 or sy0 < 2 or sx1 >= W - 2 or sy1 >= H - 2:
                continue
            if any(sx0 - 2 <= b[2] and b[0] <= sx1 + 2 and sy0 - 2 <= b[3] and b[1] <= sy1 + 2 for b in forbid):
                continue
            s = 0
            for x, y in ring:
                a, b = f.c(x, y), f.c(x + dx, y + dy)
                s += sum((p - q) ** 2 for p, q in zip(a, b))
                if best and s >= best[0]:
                    break
            else:
                # no label pixels and no castle icon (near-black / grey pixels) in the patch
                if any(f.fill(x + dx, y + dy) or f.icon(x + dx, y + dy)
                       for y in range(y0 - 1, y1 + 2) for x in range(x0 - 1, x1 + 2)):
                    continue
                best = (s, dx, dy)
    _, dx, dy = best
    src = [[f.idx(x + dx, y + dy) for x in range(x0, x1 + 1)] for y in range(y0, y1 + 1)]
    # edge rows/columns: dithered mix of the patch and the original (no hard rectangle)
    rnd = random.Random(x0 * 1000 + y0)
    for j, row in enumerate(src):
        for i, v in enumerate(row):
            e = min(i, j, x1 - x0 - i, y1 - y0 - j)
            if e < 2 and rnd.random() < (0.6, 0.3)[e]:
                continue
            f.put(x0 + i, y0 + j, v)


def build(data):
    """MMAP.E3 bytes with the English labels; returns (bytes, count)."""
    d = bytearray(data)
    g = pixfont.glyphs()
    n = 0
    for fi, labels in LABELS.items():
        f = Frame(d, fi)
        boxes = [find_box(f, cx, cy) for cx, cy, _ in labels]
        # label colours from the original art: brightest fill pixel, darkest outline
        fills = [f.c(x, y) for b in boxes for y in range(b[1], b[3] + 1) for x in range(b[0], b[2] + 1) if f.fill(x, y)]
        ink_col = max(fills, key=sum)
        ink = f.nearest(ink_col)
        outline = f.nearest((8, 16, 32))
        plans = []
        for (cx, cy, en), b in zip(labels, boxes):
            tw, px = ink_pixels(en, g)
            dx, dy = SHIFT.get((fi, en), (0, 0))
            bx = (b[0] + b[2] + 1) // 2 + dx - (tw + 1) // 2
            bx = max(2, min(bx, W - 3 - tw))            # keep the outline on screen
            by = (b[1] + b[3] + 1) // 2 + dy - CAP // 2 - 1
            ink_px = {(bx + x, by + y) for x, y in px}
            xs, ys = [p[0] for p in ink_px], [p[1] for p in ink_px]
            tb = (min(xs) - 1, min(ys) - 1, max(xs) + 1, max(ys) + 1)
            plans.append((b, ink_px, tb))
        forbid = [b for b, _, _ in plans] + [tb for _, _, tb in plans]
        for b, _, tb in plans:
            patch(f, b, forbid)
        for b, ink_px, tb in plans:
            for x, y in ink_px:
                for ddx in (-1, 0, 1):
                    for ddy in (-1, 0, 1):
                        if (x + ddx, y + ddy) not in ink_px:
                            f.put(x + ddx, y + ddy, outline)
            for x, y in ink_px:
                f.put(x, y, ink)
            n += 1
    return bytes(d), n


def preview(data, path, scale=3):
    from PIL import Image
    im = Image.new('RGB', (W * scale, H * 3 * scale))
    for fi in range(3):
        f = Frame(bytearray(data), fi)
        fr = Image.new('RGB', (W, H))
        fr.putdata([f.c(x, y) for y in range(H) for x in range(W)])
        im.paste(fr.resize((W * scale, H * scale), Image.NEAREST), (0, fi * H * scale))
    im.save(path)


def main():
    import iso, setup
    disc = iso.Disc(setup.CLEAN)
    out, n = build(disc.file(ISO_NAME, disc.records()))
    preview(out, sys.argv[1] if len(sys.argv) > 1 else 'build/dev/mmap.png')
    print('%d labels' % n)


if __name__ == '__main__':
    main()
