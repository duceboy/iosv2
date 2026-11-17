#!/usr/bin/env python3
"""Resolve unslid addresses in an iOS 16 split dyld_shared_cache (read only).

  dsc_a2s.py CACHE_DIR ADDR... | dsc_a2s.py CACHE_DIR --log LOG

Image from the cache's image list and __TEXT ranges; name from the image's LC_SYMTAB
(shared __LINKEDIT) plus the unmapped local symbols in dyld_shared_cache_arm64.symbols.
SMP/CRASH log lines carry `slide 0x.. mh 0x..`; cache addresses are runtime - slide.
"""
import bisect, glob, os, re, struct, sys

LC_SEGMENT_64, LC_SYMTAB = 0x19, 0x2


class Cache:
    def __init__(self, d):
        main = os.path.join(d, 'dyld_shared_cache_arm64')
        files = [main] + sorted(f for f in glob.glob(main + '.*') if not f.endswith('.symbols'))
        self.maps = []                                   # (addr, size, fileobj, fileoff)
        for path in files:
            f = open(path, 'rb')
            h = f.read(0x200)
            if not h.startswith(b'dyld_v1'):
                continue
            mo, mc = struct.unpack_from('<II', h, 0x10)
            f.seek(mo)
            for _ in range(mc):
                a, s, o, _mx, _ip = struct.unpack('<QQQII', f.read(32))
                self.maps.append((a, s, f, o))
        self.maps.sort(key=lambda m: m[0])
        self.starts = [m[0] for m in self.maps]
        mf = open(main, 'rb')
        h = mf.read(0x200)
        io, ic = struct.unpack_from('<II', h, 0x1c0)
        self.base = self.maps[0][0]
        self.images = []
        mf.seek(io)
        raw = mf.read(32 * ic)
        for i in range(ic):
            addr, _mt, _ino, po, _pad = struct.unpack_from('<QQQII', raw, 32 * i)
            mf.seek(po)
            path = mf.read(512).split(b'\0', 1)[0].decode()
            self.images.append([addr, path, None, None])
        self.ranges = []                                  # (lo, hi, image index)
        for idx, im in enumerate(self.images):
            for lo, hi in self.text_ranges(im[0]):
                self.ranges.append((lo, hi, idx))
        self.ranges.sort()
        self.rstarts = [r[0] for r in self.ranges]
        self.local = self.load_local(os.path.join(d, 'dyld_shared_cache_arm64.symbols'))

    def read(self, addr, n):
        i = bisect.bisect_right(self.starts, addr) - 1
        if i < 0:
            return None
        a, s, f, o = self.maps[i]
        if addr + n > a + s:
            return None
        f.seek(o + addr - a)
        return f.read(n)

    def load_cmds(self, mh):
        hdr = self.read(mh, 32)
        if not hdr or struct.unpack_from('<I', hdr)[0] != 0xfeedfacf:
            return []
        ncmds, size = struct.unpack_from('<II', hdr, 16)
        body = self.read(mh + 32, size) or b''
        out, off = [], 0
        for _ in range(ncmds):
            cmd, cs = struct.unpack_from('<II', body, off)
            out.append((cmd, body[off:off + cs]))
            off += cs
        return out

    def text_ranges(self, mh):
        r = []
        for cmd, b in self.load_cmds(mh):
            if cmd == LC_SEGMENT_64:
                name = b[8:24].split(b'\0')[0]
                vm, vs = struct.unpack_from('<QQ', b, 24)
                if name in (b'__TEXT',):
                    r.append((vm, vm + vs))
        return r

    def symtab(self, idx):
        im = self.images[idx]
        if im[2] is not None:
            return im[2], im[3]
        syms = []
        link = None
        for cmd, b in self.load_cmds(im[0]):
            if cmd == LC_SEGMENT_64 and b[8:24].split(b'\0')[0] == b'__LINKEDIT':
                vm, vs, fo, fs = struct.unpack_from('<QQQQ', b, 24)
                link = (vm, fo)
        for cmd, b in self.load_cmds(im[0]):
            if cmd == LC_SYMTAB and link:
                so, ns, sto, sts = struct.unpack_from('<IIII', b, 8)
                nl = self.read(link[0] + so - link[1], 16 * ns) or b''
                st = self.read(link[0] + sto - link[1], sts) or b''
                for k in range(len(nl) // 16):
                    strx, typ, sect, desc, val = struct.unpack_from('<IBBHQ', nl, 16 * k)
                    if (typ & 0x0e) == 0x0e and sect and val:          # N_SECT
                        syms.append((val, st[strx:st.find(b'\0', strx)].decode('ascii', 'replace')))
        for val, name in self.local.get(im[0] - self.base, []):
            syms.append((val, name))
        syms.sort()
        im[2], im[3] = syms, [s[0] for s in syms]
        return im[2], im[3]

    def load_local(self, path):
        out = {}
        if not os.path.exists(path):
            return out
        f = open(path, 'rb')
        h = f.read(0x200)
        lo, ls = struct.unpack_from('<QQ', h, 0x48)
        f.seek(lo)
        info = f.read(24)
        nlo, nlc, sto, sts, eo, ec = struct.unpack('<IIIIII', info)
        f.seek(lo + eo)
        ents = f.read(16 * ec)
        f.seek(lo + nlo)
        nl = f.read(16 * nlc)
        f.seek(lo + sto)
        st = f.read(sts)
        for k in range(ec):
            dyoff, start, cnt = struct.unpack_from('<QII', ents, 16 * k)
            lst = []
            for j in range(start, start + cnt):
                strx, typ, sect, desc, val = struct.unpack_from('<IBBHQ', nl, 16 * j)
                if (typ & 0x0e) == 0x0e and sect and val:
                    lst.append((val, st[strx:st.find(b'\0', strx)].decode('ascii', 'replace')))
            out[dyoff] = lst
        return out

    def a2s(self, addr):
        i = bisect.bisect_right(self.rstarts, addr) - 1
        if i < 0 or addr >= self.ranges[i][1]:
            return '?'
        idx = self.ranges[i][2]
        lib = os.path.basename(self.images[idx][1])
        syms, starts = self.symtab(idx)
        j = bisect.bisect_right(starts, addr) - 1
        if j < 0:
            return f'{lib} +{addr - self.images[idx][0]:#x}'
        return f'{lib}`{syms[j][1]}+{addr - syms[j][0]:#x}'


def main():
    c = Cache(sys.argv[1])
    if sys.argv[2] == '--log':
        slide = 0
        for line in open(sys.argv[3], errors='replace'):
            line = line.rstrip('\n')
            m = re.search(r'slide (0x[0-9a-f]+) mh (0x[0-9a-f]+)', line)
            if m:
                slide = int(m.group(1), 16)
                print(line)
                continue
            if not re.match(r'(SMP|CRASH) ', line):
                continue
            print(line.split(' bt ')[0].split(' pc ')[0])
            for a in re.findall(r'0x[0-9a-f]{8,}', line):
                v = int(a, 16)
                if 0x180000000 <= v - slide < 0x300000000:
                    print(f'    {a} {c.a2s(v - slide)}')
    else:
        for a in sys.argv[2:]:
            print(a, c.a2s(int(a, 16)))


if __name__ == '__main__':
    main()
