"""Chunk files for the progstr translation workers: notes/chunks/pNN.txt.

Line: key<TAB>room<TAB>F/M<TAB>jp px<TAB>Japanese; hint lines '# gl: English' (notes/glossary.txt,
(items: not yet)) and '# msg: English' (an EEX segment with the same Japanese).
usage: pchunks.py NN FIRST_KEY LAST_KEY   (keys inclusive, address order)
"""
import os, re, sys, unicodedata
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
import progstr, tl

ROOT = progstr.ROOT


def norm(s):
    s = re.sub(r'\\n|[\s　]', '', s)
    return unicodedata.normalize('NFKC', s)


def hints():
    gl = {}
    for ln in open(os.path.join(ROOT, 'notes', 'glossary.txt'), encoding='utf-8'):
        f = ln.rstrip('\n').split('\t')
        if len(f) >= 2 and not ln.startswith('#'):
            gl.setdefault(norm(f[0]), f[1])
    scripts = {n: tl.load(n) for n in tl.names()}
    msg = {norm(j): e for j, e in tl.memory(scripts, tl.load_tls()).items()}
    return gl, msg


def main():
    nn, lo, hi = sys.argv[1:4]
    gl, msg = hints()
    out, done = [], progstr.load_tl()
    for r in progstr.rows():
        if not r['ui'] or r['key'] in done or progstr._order(r['key']) < progstr._order(lo) or progstr._order(r['key']) > progstr._order(hi):
            continue
        out.append('%s\t%d\t%s\t%d\t%s' % (r['key'], r['room'], 'F' if r['block'] else 'M',
                                           progstr.px(r['jp'], True), r['jp'].replace('\n', '\\n')))
        j = norm(r['jp'])
        if j in gl:
            out.append('# gl: ' + gl[j])
        elif j in msg and len(msg[j]) < 120:
            out.append('# msg: ' + msg[j])
    path = os.path.join(ROOT, 'notes', 'chunks', 'p%s.txt' % nn)
    open(path, 'w', encoding='utf-8').write('\n'.join(out) + '\n')
    print(path, sum(not l.startswith('#') for l in out), 'strings', sum(l.startswith('#') for l in out), 'hints')


if __name__ == '__main__':
    main()
