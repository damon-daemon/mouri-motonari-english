"""DATA/R_nn.EEX (chapter) and S_nn.EEX (battle) event scripts: parse, rebuild, list/replace strings.

Format (reversed from the interpreter at 0x80022cfc / block runner 0x80024bf4):
  'EEX\\0' 01 02 | chunk list {u16 type, u16 len, data} ended by type 0 (all files: just 00 00 00 00)
  u32 section offsets (absolute; count = (first offset - 0x0a) / 4)
  section = u16 n_entries, then n x entry
  entry   = u16 len, cond block, u16 body_len, body block
  block   = statements until opcode 0
  stmt    = u16 opcode (< 0x58), operands; opcode 1 ("if") is followed by one condition
            statement, u16 len and a nested block (run when the condition holds)
  operand = u16 tag + value: tag 4 -> u32, tag 5 -> NUL-terminated SJIS string, other -> u16.
            The handler fixes each operand's tag (OPS below); type 1 = untagged u16 array whose
            length is the previous operand's value (ops 0x08, 0x35).
There are no code offsets besides the u16 block lengths and the section table, so strings can
change length freely: build() recomputes every length.

  python tools/eex.py check            parse + rebuild every file byte-exact
  python tools/eex.py dump R_00       print statements
  python tools/eex.py strings R_00    print strings with their index
"""
import glob, os, struct, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, 'extract', 'DATA')

_G1 = [2, 0x26, 0x26, 0x26, 4, 4, 0x2b, 0x33, 0x17]   # Oda (E4): three 0x17
_G2 = [2, 4, 4, 0x2b, 0x33, 0x26, 0x26, 7, 2, 4, 4, 3, 4, 4, 4, 4, 4, 4, 4, 4, 4, 0x17]   # Oda (E4): three 0x17
OPS = {
    0x00: [], 0x01: [], 0x02: [],
    0x03: [2, 0x23, 4, 0x24], 0x04: [3, 4, 0x24], 0x05: [4, 0x24], 0x06: [0x25], 0x07: [0x26],
    0x08: [0x35, 1, 0x35, 1], 0x09: [0x28, 4, 0x24], 0x0a: [0x1c, 0xc], 0x0b: [2], 0x0c: [2, 2],
    0x0d: [0xc], 0x0e: [2, 4, 4], 0x0f: [], 0x10: [], 0x11: [2, 4, 4, 4, 4], 0x12: [5], 0x13: [4],
    0x14: [], 0x15: [2, 2, 0x23], 0x16: [2, 0x23, 0x34, 4], 0x17: [5], 0x18: [0x1b],
    0x19: [4, 4, 4, 4, 0x29], 0x1a: [], 0x1b: [],
    0x1c: [0x26, 0x26, 4, 0x32, 2, 0x32, 2] + _G1 * 30,
    0x1d: [0x26] + _G2 * 60,
    0x1e: [4, 4, 0xb], 0x1f: [2, 4, 4, 0x2b, 0xd], 0x20: [0x2c, 2, 4, 4, 4, 4, 3],
    0x21: [2, 4, 4, 0x2b], 0x22: [2, 0xd, 0x2b], 0x23: [2, 0xd], 0x24: [2, 0x13],
    0x25: [0x2d, 0xc, 0x1a, 0x1c, 4, 4, 0x2b], 0x26: [], 0x27: [5], 0x28: [5], 0x29: [5],
    0x2a: [5], 0x2b: [5], 0x2c: [5], 0x2d: [0x2d, 0xc, 0x1a, 0x1c, 0x15],
    0x2e: [0x2d, 0xc, 0x1a, 0x1c, 4, 4], 0x2f: [], 0x30: [], 0x31: [4, 4, 0x10], 0x32: [],
    0x33: [4, 4], 0x34: [4, 0x27], 0x35: [0xc, 1, 0x26], 0x36: [0x2e], 0x37: [0x36], 0x38: [],
    0x39: [], 0x3a: [0x17], 0x3b: [2, 7, 2, 4, 4], 0x3c: [2, 0xe], 0x3d: [0x28, 0x34, 4],
    0x3e: [2, 4], 0x3f: [2, 3], 0x40: [0x22], 0x41: [2],
    0x42: [0x2c, 2, 4, 4, 4, 4, 3, 0x2f, 0x18, 4, 0x30], 0x43: [], 0x44: [0x2c, 2, 4, 4, 4, 4, 3],
    0x45: [], 0x46: [0x1e, 4], 0x47: [9], 0x48: [], 0x49: [0x12], 0x4a: [0x31], 0x4b: [2],
    0x4c: [], 0x4d: [], 0x4e: [4], 0x4f: [5], 0x50: [0x26], 0x51: [2, 0x37], 0x52: [2, 0x38],
    0x53: [2, 0x38], 0x54: [0x26], 0x55: [4], 0x56: [0x26], 0x57: [3, 4, 4],
}
STRING_OPS = {op for op, t in OPS.items() if 5 in t}


class EEXError(Exception):
    pass


class Reader:
    def __init__(self, d, p):
        self.d, self.p = d, p

    def u16(self):
        v = struct.unpack_from('<H', self.d, self.p)[0]
        self.p += 2
        return v

    def u32(self):
        v = struct.unpack_from('<I', self.d, self.p)[0]
        self.p += 4
        return v


def _stmt(r):
    at = r.p
    op = r.u16()
    if op not in OPS:
        raise EEXError('bad opcode %#x at %#x' % (op, at))
    args, last = [], 0
    for t in OPS[op]:
        if t == 1:
            args.append((1, [r.u16() for _ in range(last)]))
            continue
        tag = r.u16()
        if tag != t:
            raise EEXError('op %#x at %#x: tag %#x, expected %#x' % (op, at, tag, t))
        if t == 4:
            v = r.u32()
        elif t == 5:
            q = r.d.index(b'\0', r.p)
            v = r.d[r.p:q]
            r.p = q + 1
        else:
            v = last = r.u16()
        args.append((t, v))
    sub = None
    if op == 1:
        cond = _stmt(r)
        ln = r.u16()
        end = r.p + ln
        sub = (cond, _block(r, end))
        if r.p != end:
            raise EEXError('if block at %#x: length %#x, parsed to %#x' % (at, ln, r.p))
    return [op, args, sub]


def _block(r, end):
    out = []
    while True:
        if r.p >= end:
            raise EEXError('block overruns %#x' % end)
        st = _stmt(r)
        if st[0] == 0:
            return out
        out.append(st)


def parse(d):
    if d[:6] != b'EEX\0\x01\x02' or d[6:10] != b'\0\0\0\0':
        raise EEXError('unexpected header')
    first = struct.unpack_from('<I', d, 10)[0]
    n = (first - 10) // 4
    offs = list(struct.unpack_from('<%dI' % n, d, 10)) + [len(d)]
    secs = []
    for s in range(n):
        r = Reader(d, offs[s])
        ents = []
        for _ in range(r.u16()):
            ln = r.u16()
            end = r.p + ln
            cond = _block(r, end)
            bl = r.u16()
            body = _block(r, r.p + bl)
            if r.p != end:
                raise EEXError('entry length mismatch at %#x' % r.p)
            ents.append((cond, body))
        if r.p != offs[s + 1]:
            raise EEXError('section %d ends at %#x, next at %#x' % (s, r.p, offs[s + 1]))
        secs.append(ents)
    return secs


def _bstmt(st, out):
    op, args, sub = st
    out += struct.pack('<H', op)
    for t, v in args:
        if t == 1:
            out += struct.pack('<%dH' % len(v), *v)
            continue
        out += struct.pack('<H', t)
        if t == 4:
            out += struct.pack('<I', v)
        elif t == 5:
            out += v + b'\0'
        else:
            out += struct.pack('<H', v)
    if op == 1:
        cond, blk = sub
        _bstmt(cond, out)
        b = _bblock(blk)
        if len(b) > 0xffff:
            raise EEXError('if block too long')
        out += struct.pack('<H', len(b)) + b


def _bblock(blk):
    out = bytearray()
    for st in blk:
        _bstmt(st, out)
    out += b'\0\0'
    return bytes(out)


def build(secs):
    body = []
    for ents in secs:
        out = bytearray(struct.pack('<H', len(ents)))
        for cond, blk in ents:
            c, b = _bblock(cond), _bblock(blk)
            e = c + struct.pack('<H', len(b)) + b
            if len(e) > 0xffff:
                raise EEXError('entry too long')
            out += struct.pack('<H', len(e)) + e
        body.append(bytes(out))
    hdr = bytearray(b'EEX\0\x01\x02\0\0\0\0')
    off = 10 + 4 * len(secs)
    for b in body:
        hdr += struct.pack('<I', off)
        off += len(b)
    return bytes(hdr) + b''.join(body)


def walk(secs):
    """Yield every statement in file order (conditions and nested blocks included)."""
    def blk(b):
        for st in b:
            yield st
            if st[2]:
                yield st[2][0]
                yield from blk(st[2][1])
    for ents in secs:
        for cond, body in ents:
            yield from blk(cond)
            yield from blk(body)


def strings(secs):
    """[(op, args, arg index)] for every string operand, in file order (index = entry number)."""
    out = []
    for st in walk(secs):
        for i, (t, v) in enumerate(st[1]):
            if t == 5:
                out.append((st[0], st[1], i))
    return out


def files():
    return sorted(glob.glob(os.path.join(SRC, '[RS]_*.EEX')))


def load(name):
    return open(os.path.join(SRC, name + '.EEX'), 'rb').read()


def main(argv):
    cmd = argv[0] if argv else 'check'
    if cmd == 'check':
        n = 0
        for f in files():
            d = open(f, 'rb').read()
            if build(parse(d)) != d:
                print('MISMATCH', f)
            n += 1
        print('%d files checked' % n)
    elif cmd == 'dump':
        def show(b, ind):
            for op, args, sub in b:
                a = ' '.join('%x:%s' % (t, v.decode('cp932', 'replace').replace('\n', '\\n')
                             if t == 5 else hex(v) if t != 1 else v) for t, v in args)
                print('%s%02x %s' % (ind, op, a))
                if sub:
                    show([sub[0]], ind + '  ?')
                    show(sub[1], ind + '    ')
        for s, ents in enumerate(parse(load(argv[1]))):
            for e, (cond, body) in enumerate(ents):
                print('== section %d entry %d' % (s, e))
                show(cond, '  cond ')
                show(body, '  ')
    elif cmd == 'strings':
        for i, (op, args, k) in enumerate(strings(parse(load(argv[1])))):
            print('%4d %02x %s' % (i, op, args[k][1].decode('cp932', 'replace').replace('\n', '\\n')))


if __name__ == '__main__':
    main(sys.argv[1:])
