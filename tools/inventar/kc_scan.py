#!/usr/bin/env python3
"""A1: kernel inventory. Decodes the arm64 code of every kext in a merged kernelcache and writes to SQLite:
  kext, personality, class (OSMetaClass name/super/size), vtable slots, user-client dispatch tables
  (selector, function, sizes, entitlement), and every call with a string or constant argument
  (direct calls through stubs to named kernel symbols, virtual calls through IOUserClient-layout slots).
Method: own instruction decoder with per-basic-block register tracking (ADRP/ADD/ADR/LDR/MOV/MOVZ);
'how' column says whether a fact comes from a named symbol ('sym'), a vtable slot ('slot') or only a
string reference ('str'). Read-only; output stays local.   kc_scan.py KERNELCACHE DB
"""
import sys, sqlite3, struct
sys.path.insert(0, __file__.rsplit('/', 1)[0])
from kc import KC, sx, decode_stub, VAR

kc = KC(sys.argv[1])
def H(v):
    return None if v is None else '%x' % v
db = sqlite3.connect(sys.argv[2])
db.executescript(open(__file__.rsplit('/', 1)[0] + '/schema.sql').read())

# ---------- vtable slot names from IOUserClient (covers OSObject/IORegistryEntry/IOService/IOUserClient) ----------
def demangle_short(n):
    # __ZNK15IORegistryEntry11getPropertyEPKc -> IORegistryEntry::getProperty(PKc)
    import re
    m = re.match(r'__ZN(K?)(\d+)(\w+)', n)
    if not m:
        return n
    L = int(m.group(2)); rest = n[len('__ZN') + len(m.group(1)) + len(m.group(2)):]
    cls = rest[:L]; rest = rest[L:]
    m2 = re.match(r'(\d+)', rest)
    if not m2:
        return cls + '::' + rest
    L2 = int(m2.group(1)); meth = rest[len(m2.group(1)):len(m2.group(1)) + L2]
    return f'{cls}::{meth}({rest[len(m2.group(1)) + L2:].lstrip("E")})'

SLOT = {}
vt = kc.addr_of['__ZTV12IOUserClient'] + 16
for i in range(400):
    p = kc.u64(vt + 8 * i)
    if not p or kc.owner(p, True) is None:
        break
    if p in kc.sym:
        SLOT[i * 8] = demangle_short(kc.sym[p])
UC_SLOTS = len(SLOT)
EXT_SLOT = [o for o, n in SLOT.items() if n.startswith('IOUserClient::externalMethod')][0]
GMC_SLOT = [o for o, n in SLOT.items() if 'getMetaClass' in n][0]

METACTOR = {a for a, n in kc.sym.items() if n.startswith('__ZN11OSMetaClassC2EPKcPKS_j')}

# ---------- decoder ----------
def regs_clear(R, lo=0, hi=18):
    for r in range(lo, hi + 1):
        R.pop(r, None)

calls = []      # (kext, func, site, callee, how, argi, sval, ival)
addr_refs = {}  # va -> [(kext, func)]
getmeta = {}    # impl -> metaclass addr
metaclass = {}  # meta addr -> (name, super addr, size, kext)
funcs = {}      # func start -> kext
edges_pc = []   # (call site, local target)
wrappers = {}   # function that constructs a metaclass from its x0
local_x0 = []   # (local call target, x0 address)
local_fwd = []  # (caller, target) with x0 not constant: possible forwarding wrapper

for kname, ss in kc.kexts:
    if kname == 'kernel':
        continue
    stubs = {}
    for seg, vm, vms in ss:
        if seg != '__TEXT_EXEC' or not vms:
            continue
        w = kc.text_words(vm, vms)
        n = len(w)
        for i in range(n):
            g = decode_stub(w, i, vm + 4 * i)
            if g:
                t = kc.u64(g)
                stubs[vm + 4 * i] = kc.sym.get(t, hex(t or 0))
        R = {}
        func = vm
        newf = True
        for i in range(n):
            ins = w[i]
            pc = vm + 4 * i
            if newf:
                func = pc; funcs[pc] = kname; newf = False
                # getMetaClass impl: x0 = adrp/add constant, then ret within 8 instructions, no call
                x0 = None
                for j in range(i, min(i + 8, n)):
                    x = w[j]
                    if (x & 0x9F00001F) == 0x90000000:
                        imm = ((x >> 29) & 3) | (((x >> 5) & 0x7FFFF) << 2)
                        x0 = ((vm + 4 * j) & ~0xFFF) + (sx(imm, 21) << 12)
                    elif (x & 0xFFC003FF) == 0x91000000 and x0 is not None:
                        x0 += (x >> 10) & 0xFFF
                    elif x == 0xD65F03C0:
                        if x0 is not None:
                            getmeta[pc] = x0
                        break
                    elif (x & 0xFC000000) in (0x94000000, 0x14000000) or (x & 0x1F) == 0 and (x & 0x7F000000) not in (0x71000000, 0x6B000000):
                        if not ((x & 0xFF8003FF) == 0xD10003FF or (x & 0xFF8003FF) == 0x910003FF or (x & 0xFFC0001F) == 0xF9000000 or (x & 0xFFE0001F) == 0xF8000000):
                            break
            rd = ins & 31
            if (ins & 0x9F000000) == 0x90000000:            # ADRP
                imm = ((ins >> 29) & 3) | (((ins >> 5) & 0x7FFFF) << 2)
                R[rd] = ('a', (pc & ~0xFFF) + (sx(imm, 21) << 12))
            elif (ins & 0x9F000000) == 0x10000000:          # ADR
                imm = ((ins >> 29) & 3) | (((ins >> 5) & 0x7FFFF) << 2)
                R[rd] = ('a', pc + sx(imm, 21))
                addr_refs.setdefault(R[rd][1], []).append((kname, pc))
            elif (ins & 0xFF800000) == 0x91000000:          # ADD x, x, #imm
                rn = (ins >> 5) & 31; imm = (ins >> 10) & 0xFFF
                if (ins >> 22) & 1: imm <<= 12
                s = R.get(rn)
                if s and s[0] == 'a':
                    R[rd] = ('a', s[1] + imm)
                    addr_refs.setdefault(R[rd][1], []).append((kname, pc))
                else:
                    R.pop(rd, None)
            elif (ins & 0xFFC00000) == 0xF9400000:          # LDR x, [x, #imm]
                rn = (ins >> 5) & 31; o = ((ins >> 10) & 0xFFF) * 8
                s = R.get(rn)
                if s and s[0] == 'a':
                    v = kc.u64(s[1] + o)
                    R[rd] = ('a', v) if v else ('m', s[1] + o)
                elif s and s[0] == 'vt':
                    R[rd] = ('slot', o)
                elif o == 0 and rn != 31:
                    R[rd] = ('vt',)
                else:
                    R.pop(rd, None)
            elif (ins & 0x7F800000) == 0x52800000:          # MOVZ
                R[rd] = ('c', ((ins >> 5) & 0xFFFF) << (((ins >> 21) & 3) * 16))
            elif (ins & 0x7F800000) == 0x12800000:          # MOVN
                v = ~(((ins >> 5) & 0xFFFF) << (((ins >> 21) & 3) * 16))
                R[rd] = ('c', v & (0xFFFFFFFF if not ins >> 31 else 0xFFFFFFFFFFFFFFFF))
            elif (ins & 0x7F800000) == 0x72800000:          # MOVK
                s = R.get(rd)
                if s and s[0] == 'c':
                    sh = ((ins >> 21) & 3) * 16
                    R[rd] = ('c', (s[1] & ~(0xFFFF << sh)) | (((ins >> 5) & 0xFFFF) << sh))
                else:
                    R.pop(rd, None)
            elif (ins & 0x7FE0FFE0) == 0x2A0003E0:          # MOV reg (ORR rd, zr, rm)
                rm = (ins >> 16) & 31
                if rm in R: R[rd] = R[rm]
                else: R.pop(rd, None)
            elif (ins & 0xFC000000) == 0x94000000 or (ins & 0xFFFFFC1F) == 0xD63F0000:   # BL / BLR
                if (ins & 0xFC000000) == 0x94000000:
                    t = pc + sx(ins & 0x3FFFFFF, 26) * 4
                    callee = stubs.get(t) or kc.sym.get(t)
                    how = 'sym'
                    if callee is None:
                        callee = hex(t); how = 'local'
                        edges_pc.append((pc, t))
                        a0 = R.get(0)
                        if a0 and a0[0] == 'a':
                            local_x0.append((t, a0[1]))
                        else:
                            local_fwd.append((func, t))
                    elif t in METACTOR or callee.startswith('__ZN11OSMetaClassC2EPKcPKS_j'):
                        a0, a1, a2, a3 = R.get(0), R.get(1), R.get(2), R.get(3)
                        if a1 and a1[0] == 'a':
                            info = (kc.cstr(a1[1]), a2[1] if a2 and a2[0] == 'a' else None,
                                    a3[1] if a3 and a3[0] == 'c' else None, kname)
                            if a0 and a0[0] == 'a':
                                metaclass[a0[1]] = info
                            else:
                                wrappers[func] = info      # -O0 code: x0 comes in as parameter
                else:
                    s = R.get((ins >> 5) & 31)
                    if s and s[0] == 'slot' and s[1] in SLOT:
                        callee = SLOT[s[1]]; how = 'slot'
                    elif s and s[0] == 'slot':
                        callee = f'slot+0x{s[1]:x}'; how = 'slot'
                    else:
                        callee = None
                if callee is not None:
                    any_arg = False
                    for ai in range(6):
                        s = R.get(ai)
                        if not s:
                            continue
                        if s[0] == 'a':
                            st = kc.cstr(s[1])
                            if st is not None:
                                calls.append((kname, func, pc, callee, how, ai, st, None)); any_arg = True
                        elif s[0] == 'c' and ai > 0:
                            calls.append((kname, func, pc, callee, how, ai, None, s[1])); any_arg = True
                    if not any_arg and how != 'local':
                        calls.append((kname, func, pc, callee, how, -1, None, None))
                regs_clear(R)
            elif ins == 0xD65F03C0 or (ins & 0xFC000000) == 0x14000000 or (ins & 0xFFFFFC1F) == 0xD61F0000:
                R = {}; newf = ins == 0xD65F03C0 or (ins & 0xFC000000) == 0x14000000
            else:
                op0 = (ins >> 25) & 0xF
                if op0 in (0x8, 0x9, 0x5, 0xD):               # data processing: writes rd
                    R.pop(rd, None)
                elif (op0 & 0x5) == 0x4 and (ins >> 22) & 1:  # load
                    R.pop(rd, None)
                    if (ins & 0x3A000000) == 0x28000000:      # LDP: second reg
                        R.pop((ins >> 10) & 31, None)

for _ in range(6):
    for f, t in local_fwd:
        if t in wrappers and f not in wrappers:
            wrappers[f] = wrappers[t]
for t, a in local_x0:
    if t in wrappers and a not in metaclass:
        metaclass[a] = wrappers[t]
db.executemany('INSERT OR IGNORE INTO kext(name) VALUES (?)', [(k,) for k, _ in kc.kexts])
db.executemany('INSERT INTO kcall VALUES (?,?,?,?,?,?,?,?)',
               [(k, H(f), H(s), c, h, a, sv, iv if iv is None or iv < 2**63 else iv - 2**64) for k, f, s, c, h, a, sv, iv in calls])

# ---------- classes and vtables ----------
db.executemany('INSERT OR REPLACE INTO kclass(meta, name, super_meta, size, kext) VALUES (?,?,?,?,?)',
               [(H(m), n, H(s), z, k) for m, (n, s, z, k) in metaclass.items()])
impl2class = {}
vt_rows = []
gm_impls = set(getmeta)
for nm, ss in kc.kexts:
    for seg, vm, vms in ss:
        if seg not in ('__DATA_CONST', '__DATA') or not vms:
            continue
        o = kc.off(vm)
        if o is None:
            continue
        for q in range(0, vms - 8, 8):
            p = struct.unpack_from('<Q', kc.d, o + q)[0]
            if p in gm_impls:
                start = vm + q - GMC_SLOT
                meta = getmeta[p]
                cname = metaclass.get(meta, (None,))[0]
                if not cname:
                    continue
                for i in range(600):
                    f = kc.u64(start + 8 * i)
                    if not f or kc.owner(f, True) is None:
                        break
                    vt_rows.append((cname, i, SLOT.get(8 * i), H(f)))
                    impl2class.setdefault(f, set()).add((cname, i))
db.executemany('INSERT INTO kvslot VALUES (?,?,?,?)', vt_rows)

# ---------- dispatch tables ----------
def is_fn(v):
    return kc.owner(v, True) is not None

def ok(c):
    return c <= 0x4000 or c == VAR

tables = []
for RS in (40, 24):
    for name, vm, vms, fo, fs in kc.top:
        if name not in ('__PLK_DATA_CONST', '__PRELINK_DATA', '__DATA_CONST'):
            continue
        p = fo; end = fo + fs
        while p + 2 * RS <= end:
            n = 0; q = p
            while q + RS <= end:
                fn, a, b, c, e = struct.unpack_from('<QIIII', kc.d, q)
                good = is_fn(fn) and ok(a) and ok(b) and ok(c) and ok(e)
                if good and RS == 40:
                    pad, ent = struct.unpack_from('<QQ', kc.d, q + 24)
                    good = (pad & ~0xff) == 0 and (ent == 0 or kc.cstr(ent) is not None)
                if not good:
                    break
                n += 1; q += RS
            va = vm + p - fo
            if n >= 2 and not any(t[0] <= va < t[0] + t[1] * t[2] for t in tables):
                tables.append((va, n, RS)); p = q
            else:
                p += 8
GTM = [o for o, nm in SLOT.items() if 'getTargetAndMethodForIndex' in nm or 'getExternalMethodForIndex' in nm or 'externalMethod' in nm]
ext_impls = {}
for (cname_, slot_, base_, impl_) in vt_rows:
    if base_ and slot_ * 8 in GTM:
        ext_impls[(cname_, slot_)] = int(impl_, 16)
import bisect
_starts = sorted(set(int(r[3], 16) for r in vt_rows) | {t for _, t in edges_pc} | set(getmeta))
def true_start(f):
    j = bisect.bisect_right(_starts, f) - 1
    return _starts[j] if j >= 0 else f
edges = {}
for pc_, t_ in edges_pc:
    edges.setdefault(true_start(pc_), set()).add(t_)
rows = []
for va, n, RS in tables:
    # which class uses it: functions referencing the table address -> vtable slot owner
    users = [(k, true_start(f)) for k, f in addr_refs.get(va, [])]
    cls = set()
    for k, f in users:
        for c, i in impl2class.get(f, ()):
            cls.add(c)
    how_c = 'slot'
    if not cls:
        # helper called (up to 2 levels) from a class's externalMethod / getTargetAndMethodForIndex
        ufs = {f for k, f in users}
        for (c, i), f0 in ext_impls.items():
            lv1 = edges.get(f0, set())
            lv2 = set().union(*(edges.get(x, set()) for x in lv1)) if lv1 else set()
            if ufs & ({f0} | lv1 | lv2):
                cls.add(c); how_c = 'call'
    cname = (','.join(sorted(cls)) + ('' if how_c == 'slot' else ' (über Aufruf)')) if cls else None
    ufn = users[0][1] if users else None
    for i in range(n):
        fn, a, b, c, e = struct.unpack_from('<QIIII', kc.d, kc.off(va + RS * i))
        ent = kc.cstr(kc.u64(va + RS * i + 32)) if RS == 40 else None
        rows.append((kc.owner(fn, True), H(va), cname, H(ufn), i, H(fn), a, b, c, e, ent, RS))
db.executemany('INSERT INTO kdispatch VALUES (?,?,?,?,?,?,?,?,?,?,?,?)', rows)

# ---------- personalities ----------
def s(v):
    return '|'.join(map(str, v)) if isinstance(v, list) else ('' if v is None else str(v))
prow = []
for k in kc.info:
    for pname, pers in (k.get('IOKitPersonalities') or {}).items():
        m = pers.get('IONameMatch') or pers.get('IOPropertyMatch') or pers.get('IOResourceMatch') or ''
        prow.append((k.get('CFBundleIdentifier', '?'), pname, s(pers.get('IOClass')), s(pers.get('IOProviderClass')),
                     s(m), s(pers.get('IOUserClientClass')), s(pers.get('IOMatchCategory'))))
db.executemany('INSERT INTO kpersonality VALUES (?,?,?,?,?,?,?)', prow)
db.commit()
print(f'kexts {len(kc.kexts)} calls {len(calls)} classes {len(metaclass)} vtable slots {len(vt_rows)} '
      f'dispatch tables {len(tables)} ({len(rows)} selectors) personalities {len(prow)}')
