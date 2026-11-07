"""Check your own disc image and create the working folders extract/ and script/.

extract/ holds the files of the disc, script/ the Japanese text (one file per event script,
same keys as tl/), so both are generated on each machine and never distributed. Run this
once after cloning, then tools/build.py.

usage: .venv/bin/python tools/setup.py [mouri_motonari.bin]
"""
import hashlib, os, sys

sys.path.insert(0, os.path.dirname(__file__))
import iso

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EXTRACT = os.path.join(ROOT, 'extract')
SCRIPT = os.path.join(ROOT, 'script')
CLEAN = os.path.join(ROOT, 'mouri_motonari.bin')     # single data track, no CD-DA
CLEAN_SHA1 = '47e52e18ff3f88dc7b3c08b5fd0de63e912dadef'


def sha1(path):
    h = hashlib.sha1()
    with open(path, 'rb') as f:
        while chunk := f.read(1 << 24):
            h.update(chunk)
    return h.hexdigest()


def check_clean(path, want=CLEAN_SHA1):
    digest = sha1(path)
    if digest != want:
        sys.exit('%s: SHA-1 %s does not match the clean dump (%s)' % (path, digest, want))


def extract(disc):
    n = 0
    for name, lba, size in disc.walk():
        if name.endswith('.STR') or name == iso.PAD_NAME:
            continue                     # movies, padding
        p = os.path.join(EXTRACT, name)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, 'wb') as f:
            f.write(disc.read(lba, size))
        n += 1
    return n


def export_script():
    import tl, text
    os.makedirs(os.path.join(SCRIPT, 'eex'), exist_ok=True)
    total = 0
    for name in tl.names():
        sc = tl.load(name)
        with open(os.path.join(SCRIPT, 'eex', name + '.txt'), 'w', encoding='utf-8') as f:
            for k, jp in sorted(sc.segs.items(), key=lambda i: (i[0][0], i[0][1] or 0)):
                f.write('%s %s%s\n%s\n\n' % (tl.key_str(k), text.KIND.get(sc.kind[k], hex(sc.kind[k])),
                                             tl.who(sc, k), text.jp_show(jp)))
                total += 1
    return total


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else CLEAN
    check_clean(path)
    print('extract/: %d files' % extract(iso.Disc(path)))
    print('script/eex: %d segments' % export_script())
    import datae3
    print('script/data.txt: %d names' % datae3.export())
    import imsg
    print('script/imsg.txt: %d records' % imsg.export())
    print('ready; now run tools/build.py')


if __name__ == '__main__':
    main()
