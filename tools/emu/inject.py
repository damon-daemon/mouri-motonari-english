"""Write the current build's program patches and English blob into the running emulator
(GDB stub), so a save state made with an older build can be tested without a fresh boot.
Only RAM-resident parts: program words that differ from the original (or did in any earlier
build: build/inject_words.txt), and the blob at
build.BLOB (fonts, widths, code) and the moved program strings at build.STRS. Script files (EEX) are read from the disc image when the game loads them:
the file table (FAT_DATA.BIN, loaded once at boot to FAT_RAM) is refreshed from the built image, else a
state from an older build reads moved files from their old sectors (the scene change after the next
load hangs).

usage: .venv/bin/python tools/emu/inject.py      (headless emulator running, build done)
"""
import os, sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import build, iso, setup

FAT_RAM = 0x800ab36c                 # FAT_DATA.BIN in RAM (24-B records)
from gdbmem import G


def main():
    disc = iso.Disc(setup.CLEAN)
    recs = disc.records()
    files = build.build_files(disc, recs)
    old, new = disc.file(iso.EXE_NAME, recs), files[iso.EXE_NAME]
    g = G()
    g.cmd('?')
    # the GDB port belongs to whichever DuckStation started first: make sure it runs this game
    probe = g.read(build.EXE_BASE + 0x800, 64)
    if probe not in (old[0x800:0x840], new[0x800:0x840]):
        sys.exit('the emulator on the GDB port is not running Mouri Motonari (pgrep -a AppRun): nothing written')
    # words any build ever patched (build/inject_words.txt, cumulative): a state from an
    # older build may hold a patch this build reverted to the original word (e.g. a string
    # pointer that was moved then and is in place now) -> rewrite those too
    seen_path = os.path.join(os.path.dirname(build.OUT), 'inject_words.txt')
    seen = set()
    if os.path.exists(seen_path):
        seen = {int(x, 16) for x in open(seen_path).read().split()}
    seen |= {o for o in range(0x800, len(new), 4) if new[o:o + 4] != old[o:o + 4]}
    open(seen_path, 'w').write('\n'.join('%x' % o for o in sorted(seen)) + '\n')
    n, o = 0, 0x800
    while o < len(new):                   # runs of written words (gaps < 16 B), <= 0x200 B a packet
        if o not in seen:
            o += 4
            continue
        e = o + 4
        while e < len(new) and e - o < 0x200 and any(k in seen for k in range(e, e + 16, 4)):
            e += 4
        g.cmd('M%x,%x:%s' % (o + build.EXE_BASE, e - o, new[o:e].hex()))
        n += sum(k in seen for k in range(o, e, 4))
        o = e
    tail = files[build.KFONT][build.KFONT_SIZE:]          # blob, then the moved program strings
    nb = len(build.make_blob()[0])
    for at, data in ((build.BLOB, tail[:nb]), (build.STRS, tail[nb:])):
        for i in range(0, len(data), 0x200):
            part = data[i:i + 0x200]
            g.cmd('M%x,%x:%s' % (at + i, len(part), part.hex()))
    blob = tail
    out = iso.Disc(build.OUT)
    fat = out.file('FAT_DATA.BIN', out.records())
    for i in range(0, len(fat), 0x200):
        g.cmd('M%x,%x:%s' % (FAT_RAM + i, len(fat[i:i + 0x200]), fat[i:i + 0x200].hex()))
    g.resume()
    print('injected %d program words, blob %d bytes, file table' % (n, len(blob)))


if __name__ == '__main__':
    main()
