#!/usr/bin/env python3
"""A3: userland inventory from an iOS arm64 (non-arm64e) split dyld_shared_cache.
Finds every call site of the hardware-facing APIs (IOKit matching/properties/open/methods, MobileGestalt,
sysctlbyname, notify, open) and resolves constant arguments (C strings, CFString constants, integers)
with a short forward pass over the instructions before the call. Writes table ucall:
  image, caller (symbol), site, api, argi, sval, ival.
Method: numpy pre-filter of BL instructions whose target is the API or a stub/island that leads to it,
then register tracking from the start of the caller (symbol start, max 600 instructions back).
Read-only; output local.   us_scan.py CACHE_DIR DB
"""
import sys, os, sqlite3, struct, bisect
import numpy as np
sys.path.insert(0, __file__.rsplit('/', 1)[0])
from dsc_a2s import Cache

sys.path.insert(0, __file__.rsplit('/', 1)[0])
from us_scan_api import API, track_fn

c = Cache(sys.argv[1])
db = sqlite3.connect(sys.argv[2])
db.execute('DROP TABLE IF EXISTS ucall')
db.execute('CREATE TABLE ucall(image TEXT, caller TEXT, site TEXT, api TEXT, argi INTEGER, sval TEXT, ival INTEGER)')

target = {}
for idx, im in enumerate(c.images):
    base = os.path.basename(im[1]).split('.')[0]
    if base not in API:
        continue
    syms, _ = c.symtab(idx)
    want = set(API[base])
    for val, name in syms:
        if name in want:
            target[val] = name[1:]
print('api functions found', len(target), file=sys.stderr)

def u64(a):
    b = c.read(a, 8)
    return struct.unpack('<Q', b)[0] if b else None

def ptr(a):
    v = u64(a)
    return None if v is None else (v & 0xFFFFFFFFFF)

def cstr(a, n=200):
    b = c.read(a, n)
    if not b:
        return None
    e = b.find(b'\0')
    if e <= 0:
        return None
    t = b[:e]
    return t.decode() if all(32 <= x < 127 for x in t) else None

def strval(a):
    s = cstr(a)
    if s is not None and len(s) >= 2:
        return s
    # CFString constant: isa, flags, char *, length
    b = c.read(a, 32)
    if b:
        isa, flags, p, ln = struct.unpack('<QQQQ', b)
        if (flags & 0xFFFFF000) == 0 and flags & 0x8 and 0 < ln < 400:
            s = cstr(p & 0xFFFFFFFFFF, ln + 1)
            if s is not None:
                return s
    return None

def sx(v, bits):
    return v - (1 << bits) if v & (1 << (bits - 1)) else v

stubcache = {}
def through_stub(t):
    if t in target:
        return target[t]
    if t in stubcache:
        return stubcache[t]
    r = None
    b = c.read(t, 12)
    if b:
        a, b2, cc = struct.unpack('<III', b)
        if (a & 0x9F00001F) == 0x90000010 and cc == 0xD61F0200:
            imm = ((a >> 29) & 3) | (((a >> 5) & 0x7FFFF) << 2)
            page = (t & ~0xFFF) + (sx(imm, 21) << 12)
            if (b2 & 0xFFC003FF) == 0xF9400210:      # ldr x16, [x16, #o]  -> GOT
                g = ptr(page + ((b2 >> 10) & 0xFFF) * 8)
                r = target.get(g)
            elif (b2 & 0xFFC003FF) == 0x91000210:    # add x16, x16, #o    -> island
                r = target.get(page + ((b2 >> 10) & 0xFFF))
    stubcache[t] = r
    return r

def track(words, start_pc, upto):
    return track_fn(words, start_pc, upto, ptr)

rows = []
for (a, size, f, o) in [m for m in c.maps]:
    pass
# exec mappings: read mapping table again for protections
import glob
main = os.path.join(sys.argv[1], 'dyld_shared_cache_arm64')
files = [main] + sorted(x for x in glob.glob(main + '.*') if not x.endswith('.symbols'))
nsites = 0
for path in files:
    fh = open(path, 'rb'); h = fh.read(0x200)
    if not h.startswith(b'dyld_v1'):
        continue
    mo, mc = struct.unpack_from('<II', h, 0x10)
    fh.seek(mo)
    maps = [struct.unpack('<QQQII', fh.read(32)) for _ in range(mc)]
    for addr, size, foff, maxp, initp in maps:
        if not initp & 4:
            continue
        fh.seek(foff)
        w = np.frombuffer(fh.read(size), dtype='<u4')
        isbl = (w & 0xFC000000) == 0x94000000
        idx = np.nonzero(isbl)[0]
        imm = (w[idx] & 0x3FFFFFF).astype(np.int64)
        imm = np.where(imm & 0x2000000, imm - 0x4000000, imm)
        tgt = addr + idx.astype(np.int64) * 4 + imm * 4
        uniq = np.unique(tgt)
        good = np.array([through_stub(int(t)) is not None for t in uniq], dtype=bool)
        hit_t = set(int(t) for t in uniq[good])
        sel = np.isin(tgt, np.array(sorted(hit_t), dtype=np.int64)) if hit_t else np.zeros(len(tgt), bool)
        for j in np.nonzero(sel)[0]:
            site = addr + int(idx[j]) * 4
            api = through_stub(int(tgt[j]))
            ii = bisect.bisect_right(c.rstarts, site) - 1
            if ii < 0 or site >= c.ranges[ii][1]:
                continue
            imx = c.ranges[ii][2]
            syms, starts = c.symtab(imx)
            k = bisect.bisect_right(starts, site) - 1
            fstart = syms[k][0] if k >= 0 else site - 4 * 200
            caller = syms[k][1] if k >= 0 else '?'
            fstart = max(fstart, site - 4 * 600)
            wi = int(idx[j]) - (site - fstart) // 4
            R = track(w[max(0, wi):int(idx[j])], fstart, site)
            img = os.path.basename(c.images[imx][1])
            got = False
            for ai in range(6):
                s = R.get(ai)
                if not s:
                    continue
                if s[0] == 'a' and s[1]:
                    sv = strval(s[1])
                    if sv is not None:
                        rows.append((img, caller, '%x' % site, api, ai, sv, None)); got = True
                elif s[0] == 'c' and ai > 0:
                    rows.append((img, caller, '%x' % site, api, ai, None, s[1])); got = True
            if not got:
                rows.append((img, caller, '%x' % site, api, -1, None, None))
            nsites += 1
        print(f'{os.path.basename(path)} {addr:#x} sites so far {nsites}', file=sys.stderr)
db.executemany('INSERT INTO ucall VALUES (?,?,?,?,?,?,?)', rows)
db.commit()
print(f'call sites {nsites}, rows {len(rows)}')
