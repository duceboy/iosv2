#!/usr/bin/env python3
"""A3 (part 2): standalone executables of an iOS root (daemons, apps, plug-ins outside the shared cache)
plus launchd jobs. For every arm64 Mach-O under ROOT: call sites of the same APIs as us_scan.py with
constant arguments (stubs resolved through chained-fixup imports or classic bind opcodes), and the
entitlements from the code signature. launchd: LaunchDaemons plists -> program, Mach services, IOKit
matching launch events. Read-only; output local.   exe_scan.py ROOT DB
"""
import sys, os, sqlite3, struct, plistlib, re
import numpy as np
sys.path.insert(0, __file__.rsplit('/', 1)[0])
from us_scan_api import API_NAMES, track_fn

ROOT, DBP = sys.argv[1], sys.argv[2]
db = sqlite3.connect(DBP)
db.executescript('''
DROP TABLE IF EXISTS ecall; DROP TABLE IF EXISTS eent; DROP TABLE IF EXISTS ljob;
CREATE TABLE ecall(binary TEXT, func TEXT, site TEXT, api TEXT, argi INTEGER, sval TEXT, ival INTEGER);
CREATE TABLE eent(binary TEXT, key TEXT, value TEXT);
CREATE TABLE ljob(plist TEXT, label TEXT, program TEXT, machservices TEXT, iokit_events TEXT, other_events TEXT);
''')

def sx(v, bits):
    return v - (1 << bits) if v & (1 << (bits - 1)) else v

def uleb(b, p):
    r = s = 0
    while True:
        x = b[p]; p += 1
        r |= (x & 0x7f) << s; s += 7
        if x < 0x80:
            return r, p

def sleb(b, p):
    r = s = 0
    while True:
        x = b[p]; p += 1
        r |= (x & 0x7f) << s; s += 7
        if x < 0x80:
            if x & 0x40: r -= 1 << s
            return r, p

class MachO:
    def __init__(self, d, base=0):
        self.d = d; self.b = base
        magic, cpu, sub, ft, ncmds, sz = struct.unpack_from('<IiiIII', d, base)
        self.ok = magic == 0xfeedfacf and cpu == 0x0100000c
        self.segs = []; self.sects = []; self.cmds = []
        if not self.ok:
            return
        p = base + 32
        for _ in range(ncmds):
            cmd, cs = struct.unpack_from('<II', d, p)
            self.cmds.append((cmd, p, cs))
            if cmd == 0x19:
                name = d[p + 8:p + 24].rstrip(b'\0').decode()
                vm, vms, fo, fs, mp, ip, ns, fl = struct.unpack_from('<QQQQiiII', d, p + 24)
                self.segs.append((name, vm, vms, fo, fs))
                for k in range(ns):
                    q = p + 72 + 80 * k
                    sn = d[q:q + 16].rstrip(b'\0').decode()
                    a, s, o = struct.unpack_from('<QQI', d, q + 32)
                    self.sects.append((name, sn, a, s, o))
            p += cs

    def off(self, va):
        for n, vm, vms, fo, fs in self.segs:
            if vm <= va < vm + fs:
                return self.b + fo + va - vm
        return None

    def u64(self, va):
        o = self.off(va)
        return None if o is None or o + 8 > len(self.d) else struct.unpack_from('<Q', self.d, o)[0]

    def cstr(self, va, n=300):
        o = self.off(va) if va else None
        if o is None:
            return None
        e = self.d.find(b'\0', o, o + n)
        if e <= o:
            return None
        t = self.d[o:e]
        return t.decode() if all(32 <= x < 127 for x in t) else None

    def binds(self):
        """address -> imported symbol name"""
        out = {}
        d = self.d
        for cmd, p, cs in self.cmds:
            if cmd == 0x80000034:                       # LC_DYLD_CHAINED_FIXUPS
                do, ds = struct.unpack_from('<II', d, p + 8)
                h = self.b + do
                ver, so, io, symo, ic, ifmt, sfmt = struct.unpack_from('<IIIIIII', d, h)
                names = []
                for k in range(ic):
                    if ifmt == 1:
                        v = struct.unpack_from('<I', d, h + io + 4 * k)[0]; no = v >> 9
                    elif ifmt == 2:
                        v = struct.unpack_from('<I', d, h + io + 8 * k)[0]; no = v >> 9
                    else:
                        v = struct.unpack_from('<Q', d, h + io + 16 * k)[0]; no = v >> 32
                    q = h + symo + no
                    names.append(d[q:d.find(b'\0', q)].decode('latin1'))
                self.imports = names
                # walk GOT-like sections: any 8-byte slot with bind bit set
                for seg, sn, a, s, o in self.sects:
                    if sn in ('__got', '__auth_got', '__la_symbol_ptr', '__data', '__const') and seg.startswith('__DATA'):
                        for q in range(0, s - 7, 8):
                            v = struct.unpack_from('<Q', d, self.b + o + q)[0]
                            if v >> 63:
                                ordn = v & 0xFFFFFF
                                if ordn < len(names):
                                    out[a + q] = names[ordn]
            elif cmd in (0x22, 0x80000022):             # LC_DYLD_INFO(_ONLY)
                vals = struct.unpack_from('<10I', d, p + 8)
                for bo, bs in ((vals[2], vals[3]), (vals[6], vals[7])):   # bind, lazy bind
                    b = d[self.b + bo:self.b + bo + bs]
                    i = 0; seg = 0; offv = 0; name = None
                    segs = [s for s in self.segs]
                    while i < len(b):
                        x = b[i]; i += 1
                        op, imm = x & 0xF0, x & 0x0F
                        if op == 0x00:
                            continue
                        elif op in (0x10, 0x30):
                            pass
                        elif op == 0x20:
                            _, i = uleb(b, i)
                        elif op == 0x40:
                            e = b.index(0, i); name = b[i:e].decode('latin1'); i = e + 1
                        elif op == 0x50:
                            pass
                        elif op == 0x60:
                            _, i = sleb(b, i)
                        elif op == 0x70:
                            seg = imm; offv, i = uleb(b, i)
                        elif op == 0x80:
                            v, i = uleb(b, i); offv += v
                        elif op in (0x90, 0xA0, 0xB0, 0xC0):
                            if seg < len(segs) and name:
                                out[segs[seg][1] + offv] = name
                            if op == 0x90:
                                offv += 8
                            elif op == 0xA0:
                                v, i = uleb(b, i); offv += 8 + v
                            elif op == 0xB0:
                                offv += 8 + imm * 8
                            else:
                                cnt, i = uleb(b, i); skip, i = uleb(b, i)
                                for _ in range(cnt - 1):
                                    offv += 8 + skip
                                    if seg < len(segs): out[segs[seg][1] + offv] = name
                                offv += 8 + skip
        return out

    def entitlements(self):
        for cmd, p, cs in self.cmds:
            if cmd == 0x1d:
                o, s = struct.unpack_from('<II', self.d, p + 8)
                blob = self.d[self.b + o:self.b + o + s]
                if len(blob) < 12:
                    return None
                magic, ln, cnt = struct.unpack_from('>III', blob, 0)
                for k in range(cnt):
                    typ, bo = struct.unpack_from('>II', blob, 12 + 8 * k)
                    if typ == 5:
                        m, l = struct.unpack_from('>II', blob, bo)
                        try:
                            return plistlib.loads(blob[bo + 8:bo + l])
                        except Exception:
                            return None
        return None

def strval(m, a):
    s = m.cstr(a)
    if s is not None and len(s) >= 2:
        return s
    o = m.off(a)
    if o is not None and o + 32 <= len(m.d):
        isa, flags, p, ln = struct.unpack_from('<QQQQ', m.d, o)
        if (flags & 0xFFFFF000) == 0 and flags & 0x8 and 0 < ln < 400:
            pp = p & 0xFFFFFFFFF
            return m.cstr(pp, ln + 1)
    return None

def ptr_of(m):
    def f(a):
        v = m.u64(a)
        if v is None:
            return None
        return v & 0xFFFFFFFFF if not v >> 63 else None
    return f

ecalls, eents = [], []
nfiles = 0
for dp, dn, fn in os.walk(ROOT):
    if '/dyld' in dp or dp.endswith('com.apple.dyld'):
        continue
    for f in fn:
        path = os.path.join(dp, f)
        try:
            if os.path.islink(path) or os.path.getsize(path) < 4096:
                continue
            with open(path, 'rb') as fh:
                head = fh.read(8)
            if head[:4] not in (b'\xcf\xfa\xed\xfe', b'\xca\xfe\xba\xbe'):
                continue
            d = open(path, 'rb').read()
        except Exception:
            continue
        bases = [0]
        if d[:4] == b'\xca\xfe\xba\xbe':
            n = struct.unpack_from('>I', d, 4)[0]; bases = []
            for k in range(n):
                cpu, sub, o, s, al = struct.unpack_from('>iiIII', d, 8 + 20 * k)
                if cpu == 0x0100000c and (sub & 0xff) != 2:
                    bases.append(o)
        rel = path[len(ROOT):]
        for b in bases[:1]:
            try:
                m = MachO(d, b)
            except Exception:
                continue
            if not m.ok:
                continue
            nfiles += 1
            ent = m.entitlements()
            if isinstance(ent, dict):
                for k, v in ent.items():
                    eents.append((rel, k, v if isinstance(v, str) else repr(v)[:300]))
            try:
                bind = m.binds()
            except Exception:
                bind = {}
            stubs = {}
            for seg, sn, a, s, o in m.sects:
                if sn in ('__stubs', '__auth_stubs'):
                    for q in range(0, s - 11, 12):
                        w1, w2, w3 = struct.unpack_from('<III', d, b + o + q)
                        if (w1 & 0x9F00001F) == 0x90000010 and (w2 & 0xFFC003FF) == 0xF9400210:
                            imm = ((w1 >> 29) & 3) | (((w1 >> 5) & 0x7FFFF) << 2)
                            g = ((a + q) & ~0xFFF) + (sx(imm, 21) << 12) + ((w2 >> 10) & 0xFFF) * 8
                            nm = bind.get(g)
                            if nm and nm in API_NAMES:
                                stubs[a + q] = nm[1:]
            if not stubs:
                continue
            for seg, sn, a, s, o in m.sects:
                if sn != '__text':
                    continue
                w = np.frombuffer(d[b + o:b + o + s - s % 4], dtype='<u4')
                idx = np.nonzero((w & 0xFC000000) == 0x94000000)[0]
                imm = (w[idx] & 0x3FFFFFF).astype(np.int64)
                imm = np.where(imm & 0x2000000, imm - 0x4000000, imm)
                tgt = a + idx.astype(np.int64) * 4 + imm * 4
                sel = np.isin(tgt, np.array(sorted(stubs), dtype=np.int64))
                for j in np.nonzero(sel)[0]:
                    site = a + int(idx[j]) * 4
                    api = stubs[int(tgt[j])]
                    st = max(0, int(idx[j]) - 120)
                    # start after the last ret/unconditional branch before the call
                    for k in range(int(idx[j]) - 1, st, -1):
                        x = int(w[k])
                        if x == 0xD65F03C0 or (x & 0xFC000000) == 0x14000000:
                            st = k + 1; break
                    R = track_fn(w[st:int(idx[j])], a + 4 * st, site, ptr_of(m))
                    got = False
                    for ai in range(6):
                        sv = R.get(ai)
                        if not sv:
                            continue
                        if sv[0] == 'a' and sv[1]:
                            t = strval(m, sv[1])
                            if t is not None:
                                ecalls.append((rel, '%x' % (a + 4 * st), '%x' % site, api, ai, t, None)); got = True
                        elif sv[0] == 'c' and ai > 0:
                            ecalls.append((rel, '%x' % (a + 4 * st), '%x' % site, api, ai, None, sv[1])); got = True
                    if not got:
                        ecalls.append((rel, '%x' % (a + 4 * st), '%x' % site, api, -1, None, None))
db.executemany('INSERT INTO ecall VALUES (?,?,?,?,?,?,?)', ecalls)
db.executemany('INSERT INTO eent VALUES (?,?,?)', eents)

jobs = []
for sub in ('System/Library/LaunchDaemons', 'System/Library/LaunchAgents', 'Library/LaunchDaemons'):
    dd = os.path.join(ROOT, sub)
    if not os.path.isdir(dd):
        continue
    for f in sorted(os.listdir(dd)):
        try:
            pl = plistlib.load(open(os.path.join(dd, f), 'rb'))
        except Exception:
            continue
        ev = pl.get('LaunchEvents') or {}
        iok = ev.get('com.apple.iokit.matching') or {}
        jobs.append((sub + '/' + f, str(pl.get('Label')), str(pl.get('Program') or ' '.join(str(x) for x in (pl.get('ProgramArguments') or []))),
                     ','.join(sorted((pl.get('MachServices') or {}).keys())),
                     repr(iok)[:2000] if iok else None,
                     ','.join(k for k in ev.keys() if k != 'com.apple.iokit.matching') or None))
db.executemany('INSERT INTO ljob VALUES (?,?,?,?,?,?)', jobs)
db.commit()
print(f'binaries {nfiles} calls {len(ecalls)} entitlements {len(eents)} launchd jobs {len(jobs)}')
