"""VRAM from a DuckStation save state (zstd data, 'GPU-VRAM' tag + 1 MB, 1024x512 u16).

  vram.py STATE.sav OUT.png                       whole VRAM as 15-bit colour
  vram.py STATE.sav OUT.png X Y W H BPP CX CY [S] a texture: rect in VRAM halfwords (X, W) and
                                                  rows, BPP 4/8, CLUT at (CX, CY), scale S
  vram.py STATE.sav find FILE                     where FILE's 2 KB pieces sit in VRAM
  vram.py STATE.sav put OUT.sav FILE OFF X Y W H  copy W x H halfwords of FILE (from byte OFF,
                                                  rows of 2W bytes) to VRAM (X, Y) -> new state
                                                  (test a redrawn texture without a cold boot)
"""
import struct, sys
from compression import zstd

TAG = b'GPU-VRAM'


def load(path):
    d = open(path, 'rb').read()
    assert d[:4] == b'DUCC'
    # header layout differs between DuckStation versions -> try every zstd frame
    i = d.find(b'\x28\xb5\x2f\xfd')
    while i >= 0:
        try:
            u = zstd.ZstdDecompressor().decompress(d[i:])
            if TAG in u:
                j = u.index(TAG) + len(TAG)
                return u[j:j + 0x100000]
        except zstd.ZstdError:
            pass
        i = d.find(b'\x28\xb5\x2f\xfd', i + 1)
    raise ValueError('no VRAM in ' + path)


def put(path, out, data, x, y, w, h):
    """Rewrite the state's VRAM rect (x, y, w, h halfwords) with data (h rows of 2w bytes).
    Header (DuckStation 0x5c): data compression, compressed size, uncompressed size, offset at
    0xc8; only zstd states."""
    d = bytearray(open(path, 'rb').read())
    ctype, csize, usize, off = struct.unpack_from('<4I', d, 0xc8)
    assert d[:4] == b'DUCC' and ctype == 2 and off + csize == len(d), 'unknown state layout'
    u = bytearray(zstd.ZstdDecompressor().decompress(bytes(d[off:off + csize])))
    assert len(u) == usize
    j = u.index(TAG) + len(TAG)
    for r in range(h):
        o = j + ((y + r) * 1024 + x) * 2
        u[o:o + 2 * w] = data[r * 2 * w:(r + 1) * 2 * w]
    c = zstd.compress(bytes(u))
    struct.pack_into('<2I', d, 0xcc, len(c), len(u))
    open(out, 'wb').write(bytes(d[:off]) + c)


def px(v):
    return ((v & 31) << 3, ((v >> 5) & 31) << 3, ((v >> 10) & 31) << 3)


def u16(vr, x, y):
    return vr[(y * 1024 + x) * 2] | vr[(y * 1024 + x) * 2 + 1] << 8


def whole(vr):
    from PIL import Image
    im = Image.new('RGB', (1024, 512))
    im.putdata([px(v) for v in struct.unpack('<524288H', vr)])
    return im


def texture(vr, x, y, w, h, bpp, cx, cy):
    from PIL import Image
    per = 16 // bpp
    pal = [px(u16(vr, cx + i, cy)) for i in range(1 << bpp)]
    im = Image.new('RGB', (w * per, h))
    out = []
    for r in range(h):
        for c in range(w):
            v = u16(vr, x + c, y + r)
            for k in range(per):
                out.append(pal[(v >> (k * bpp)) & ((1 << bpp) - 1)])
    im.putdata(out)
    return im


def find(vr, data):
    """VRAM rows are 2048 B: look up each file row-piece of 64 B at any position."""
    rows = [vr[i * 2048:(i + 1) * 2048] for i in range(512)]
    hits = []
    for o in range(0, len(data) - 64, 2048):
        piece = data[o:o + 64]
        if piece.count(piece[:2]) * 2 >= 60:
            continue
        for y, r in enumerate(rows):
            x = r.find(piece)
            if x >= 0 and x % 2 == 0:
                hits.append((o, x // 2, y))
                break
    return hits


def main():
    a = sys.argv[1:]
    vr = load(a[0])
    if a[1] == 'put':
        out, f = a[2], a[3]
        off, x, y, w, h = (int(v, 0) for v in a[4:9])
        put(a[0], out, open(f, 'rb').read()[off:off + 2 * w * h], x, y, w, h)
        return
    if a[1] == 'find':
        data = open(a[2], 'rb').read()
        for o, x, y in find(vr, data):
            print('file %#08x -> vram x=%d y=%d' % (o, x, y))
        return
    if len(a) == 2:
        whole(vr).save(a[1])
        return
    x, y, w, h, bpp, cx, cy = map(int, a[2:9])
    s = int(a[9]) if len(a) > 9 else 1
    im = texture(vr, x, y, w, h, bpp, cx, cy)
    if s > 1:
        im = im.resize((im.width * s, im.height * s), 0)
    im.save(a[1])


if __name__ == '__main__':
    main()
