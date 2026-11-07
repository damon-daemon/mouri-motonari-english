"""Rebuild the disc with the translation and produce a patch.

Output: build/mouri_motonari_en.bin + .cue (boots in an emulator) and
build/mouri_motonari_en.xdelta (clean image -> English image).

usage: .venv/bin/python tools/build.py [clean.bin] [out.bin]
"""
import os, struct, subprocess, sys

sys.path.insert(0, os.path.dirname(__file__))
import asm, bios, datae3, gfx, imsg, iso, mctitle, mmap, names, progstr, setup, tl, vwf

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, 'build', 'mouri_motonari_en.bin')
EXE_BASE = 0x80010000 - 0x800            # MAIN.EXE file offset of an address = va - EXE_BASE


def poke(exe, va, words):
    for i, w in enumerate(words):
        struct.pack_into('<I', exe, va - EXE_BASE + 4 * i, w)


def peek(exe, va, n):
    return list(struct.unpack_from('<%dI' % n, exe, va - EXE_BASE))


# Script string decoder 0x800207b4 (as Oda Nobunaga Den's 0x80023338): single bytes 0x20-0x72
# stand for hiragana and 0x73-0x76 for punctuation (no script uses them; the survey's "plain
# SJIS" was right only for the data). Copy every single byte 0x20-0x7f as it is instead.
ASCII_AT = 0x8002082c
ASCII_OLD = [0x1040000a, 0x2c820080, 0x90c30000, 0x24c60001, 0x2463827f]


def patch_exe(exe):
    assert peek(exe, ASCII_AT, 5) == ASCII_OLD, 'unexpected code at %#x' % ASCII_AT
    poke(exe, ASCII_AT, [0])
    code = asm.assemble(ASCII_AT, [
        ('sltiu', 'v0', 'a0', 0x80),
        ('beqz', 'v0', 0x800208ec),      # >= 0x80: SJIS pair
        ('nop',),
        ('j', 0x8002081c),               # copy one byte
        ('nop',)])
    exe[ASCII_AT - EXE_BASE:ASCII_AT - EXE_BASE + len(code)] = code


# ---- English blob: fixed RAM BLOB..BLOB_END at the top of the heap arena ----
# The game's heap is InitHeap(0x80150000, 0x4a000) (0x8003d128) -> arena up to 0x8019a000 (the
# 4bpp text bitmap starts there); its last ~22-28 KB were never used (survey). The arena is
# shrunk by BLOB_SIZE and the blob is appended to DATA/KFONT.BIN: the font loader 0x8001b120
# reads 0x191f4 bytes of it into a heap buffer with the sequential reader READ(ctx, buf, size)
# (the ctx keeps a byte position), and LOADER reads the rest of the file to BLOB.
BLOB_SIZE = 0x4000
BLOB_END = 0x8019a000
BLOB = BLOB_END - BLOB_SIZE
HEAP_SIZE_AT = 0x8003d13c                # ori a1, a1, 0xa000 (with lui a1, 4)
KFONT = 'DATA/KFONT.BIN'
KFONT_SIZE = 0x191f4
KFONT_READ_AT = 0x8001b188               # jal READ (KFONT -> heap buffer)
READ = 0x80022650
# 1-byte glyphs, 12-px mode (0x8001b354): the digits / + - % / were mapped to 14 cells of an
# 8x12 table at 0x80100f44 (12 bytes per cell, bit 7 = left; the 16-px mode has a full ASCII
# 8x16 table at 0x80100544). Replaced by cell = c - 0x20 in our 96-cell font in the blob;
# the rest of the old mapping code (FREE..FREE_END) holds LOADER.
GLYPH12_AT = 0x8001b36c
GLYPH12_LOOP = 0x8001b3e8                # addu t0, v1, v0 (cell address) then the 12-row loop
GLYPH12_RET = 0x8001b54c
FREE, FREE_END = 0x8001b394, 0x8001b3e8


# Moved program strings (progstr.py) live in STRS..STRS_END: free RAM between the end of the
# BSS (0x80145cf8, cleared at entry) and the memory-card buffer flags/data at 0x80148df0..
# 0x8014ff00 (heap from 0x80150000); zero and unreferenced in every state (roam, battle,
# memory-card prompt, settings). LOADER reads it from KFONT.BIN after the blob.
STRS, STRS_END = 0x80145d00, 0x80148de0


def patch_blob(exe, blob_len, font_at, strs_len=4):
    assert peek(exe, HEAP_SIZE_AT - 4, 2) == [0x0c020f33, 0x34a5a000], 'unexpected InitHeap call'
    poke(exe, HEAP_SIZE_AT, [0x34a50000 | (0xa000 - BLOB_SIZE)])
    assert 0xa000 - BLOB_SIZE >= 0
    assert peek(exe, KFONT_READ_AT, 2) == [0x0c008994, 0x34c691f4], 'unexpected KFONT read'
    assert peek(exe, GLYPH12_AT, 1) == [0x2464ffd0] and peek(exe, GLYPH12_LOOP, 1) == [0x00624021]
    code = asm.assemble(GLYPH12_AT, [
        ('addiu', 'a0', 'v1', -0x20),
        ('sltiu', 'v0', 'a0', 0x60),
        ('beqz', 'v0', GLYPH12_RET),
        ('sll', 'v1', 'a0', 1),
        ('addu', 'v1', 'v1', 'a0'),
        ('sll', 'v1', 'v1', 2),          # 12 bytes per cell
        ('lui', 'v0', asm.hi(font_at)),
        ('j', GLYPH12_LOOP),
        ('addiu', 'v0', 'v0', asm.lo(font_at))])
    assert GLYPH12_AT + len(code) <= FREE
    exe[GLYPH12_AT - EXE_BASE:GLYPH12_AT - EXE_BASE + len(code)] = code
    poke(exe, GLYPH12_AT + len(code), [0] * ((FREE - GLYPH12_AT - len(code)) // 4))
    loader = asm.assemble(FREE, [
        ('addiu', 'sp', 'sp', -24),
        ('sw', 'ra', 16, 'sp'),
        ('jal', READ),                   # the font, as before
        ('sw', 'a0', 20, 'sp'),
        ('lw', 'a0', 20, 'sp'),
        ('lui', 'a1', asm.hi(BLOB)),
        ('addiu', 'a1', 'a1', asm.lo(BLOB)),
        ('jal', READ),                   # the blob
        ('ori', 'a2', 'zero', blob_len),
        ('lw', 'a0', 20, 'sp'),
        ('lui', 'a1', asm.hi(STRS)),
        ('addiu', 'a1', 'a1', asm.lo(STRS)),
        ('jal', READ),                   # the moved program strings
        ('ori', 'a2', 'zero', strs_len),
        ('lw', 'ra', 16, 'sp'),
        ('nop',),
        ('jr', 'ra'),
        ('addiu', 'sp', 'sp', 24)])
    assert FREE + len(loader) <= FREE_END
    exe[FREE - EXE_BASE:FREE - EXE_BASE + len(loader)] = loader
    poke(exe, FREE + len(loader), [0] * ((FREE_END - FREE - len(loader)) // 4))
    poke(exe, KFONT_READ_AT, [0x0c000000 | (FREE >> 2) & 0x3ffffff])


def make_blob():
    """-> (blob bytes, labels): vwf part (fonts, widths, code), then the English officer names
    (names.blob_names) and the new GETNAME (names.hook; labels names, names_short, names_raw)."""
    lab, data = vwf.listing(BLOB)
    data += bytes(-len(data) % 4)
    nbase = BLOB + len(data)
    data += names.blob_names(nbase)
    data += bytes(-len(data) % 4)
    at = BLOB + len(data)
    code, short, raw = names.hook(at, nbase, names.MSGW)
    data += code
    lab.update(names=at, names_short=short, names_raw=raw)
    data += bytes(-len(data) % 4)
    part, lab['title'] = mctitle.blob(BLOB + len(data))
    data += part
    data += bytes(-len(data) % 4)
    part, lab['town'] = datae3.blob(BLOB + len(data))
    data += part
    return data, lab


def build_files(disc, recs):
    """{iso path: bytes} of every rebuilt file."""
    eexs, done, errs = tl.english()
    if errs:
        sys.exit('\n'.join(errs) + '\n%d errors in tl/ (tools/tl.py check)' % len(errs))
    print('EEX: %d English segments in %d files' % (done, len(eexs)))
    out = {'DATA/%s.EEX' % n: d for n, d in eexs.items()}
    clean_exe = disc.file(iso.EXE_NAME, recs)
    exe = bytearray(clean_exe)
    patch_exe(exe)
    blob, lab = make_blob()
    assert len(blob) <= BLOB_SIZE and len(blob) < 0x8000, 'blob too large: %d bytes' % len(blob)
    vwf.patch(exe, EXE_BASE, lab)
    names.patch(exe, EXE_BASE, lab['names'], lab['names_short'], lab['names_raw'])
    mctitle.patch(exe, EXE_BASE, lab['title'])
    datae3.patch(exe, EXE_BASE, lab['town'])
    out[datae3.ISO_NAME], n = datae3.build(disc.file(datae3.ISO_NAME, recs))
    print('DATA.E3: %d names' % n)
    out[imsg.ISO_NAME], n = imsg.build(disc.file(imsg.ISO_NAME, recs))
    print('IMSG.E3: %d records' % n)
    bios.patch(exe, EXE_BASE)
    out[bios.ISO_NAME], n = bios.build(disc.file(bios.ISO_NAME, recs))
    print('PROFILE.E3: %d English entries' % n)
    out[gfx.ISO_NAME], n = gfx.build(disc.file(gfx.ISO_NAME, recs), exe, EXE_BASE)
    print('MARK.E3: %d labels' % n)
    out[mmap.ISO_NAME], n = mmap.build(disc.file(mmap.ISO_NAME, recs))
    print('MMAP.E3: %d province labels' % n)
    # program strings last: repointing asserts the clean words (catches clashes with the patches)
    n, moved, pool, strs = progstr.apply({'PROG': exe}, {'PROG': clean_exe}, (STRS, STRS_END - STRS))
    strs += bytes(max(4 - len(strs), 0) + (-len(strs) % 4))
    assert len(strs) <= STRS_END - STRS
    print('progstr: %d strings (%d moved, %d bytes at %#x; slack left %d)' % (n, moved, len(strs), STRS, pool.room()))
    patch_blob(exe, len(blob), lab['font12'], len(strs))
    kf = disc.file(KFONT, recs)
    assert len(kf) == KFONT_SIZE
    out[KFONT] = kf + blob + strs
    print('blob: %d bytes at %#x' % (len(blob), BLOB))
    if exe != clean_exe:
        out[iso.EXE_NAME] = bytes(exe)
    return out


def write(clean, out, files):
    os.makedirs(os.path.dirname(out), exist_ok=True)
    moved = iso.write_image(clean, out, files)
    print('rebuilt %s%s' % (out, ' (moved: %s)' % ', '.join(moved) if moved else ''))
    iso.verify(out, files)
    iso.write_cue(out[:-4] + '.cue', out, [])
    patch = out[:-4] + '.xdelta'
    try:
        subprocess.run(['xdelta3', '-e', '-f', '-9', '-S', 'djw', '-B', str(1 << 28), '-s', clean, out, patch], check=True)
        print('patch %s (%d bytes)' % (patch, os.path.getsize(patch)))
    except FileNotFoundError:
        print('xdelta3 not installed; skipped patch')
    return moved


def main():
    args = sys.argv[1:]
    clean = args[0] if args else setup.CLEAN
    out = args[1] if len(args) > 1 else OUT
    disc = iso.Disc(clean)
    write(clean, out, build_files(disc, disc.records()))


if __name__ == '__main__':
    main()
