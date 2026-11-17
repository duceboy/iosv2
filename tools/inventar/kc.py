#!/usr/bin/env python3
"""Kernelcache helpers for the inventory (merged arm64 iOS kernelcache, MH_EXECUTE + __PRELINK_TEXT,
plain unslid pointers as in the A11 iOS 16 cache). Read-only. Everything derived stays local."""
import re, struct, subprocess, xml.etree.ElementTree as ET
from array import array

VAR = 0xffffffff


class KC:
    def __init__(self, path):
        self.path = path
        self.d = open(path, 'rb').read()
        self.top = self._segs(0)
        self.v2o = [(vm, vm + fs, fo) for _, vm, vms, fo, fs in self.top if fs]
        self._prelink()
        self._kexts()
        self._symbols()

    # ---------- Mach-O ----------
    def _segs(self, off):
        d = self.d
        ncmds = struct.unpack_from('<I', d, off + 16)[0]
        p = off + 32
        out = []
        for _ in range(ncmds):
            cmd, cs = struct.unpack_from('<II', d, p)
            if cmd == 0x19:
                name = d[p + 8:p + 24].rstrip(b'\0').decode()
                vm, vms, fo, fs = struct.unpack_from('<QQQQ', d, p + 24)
                out.append((name, vm, vms, fo, fs))
            p += cs
        return out

    def off(self, va):
        for a, b, fo in self.v2o:
            if a <= va < b:
                return fo + va - a
        return None

    def u64(self, va):
        o = self.off(va)
        return None if o is None else struct.unpack_from('<Q', self.d, o)[0]

    def u32(self, va):
        o = self.off(va)
        return None if o is None else struct.unpack_from('<I', self.d, o)[0]

    def cstr(self, va, maxlen=300):
        o = self.off(va) if va else None
        if o is None:
            return None
        e = self.d.find(b'\0', o, o + maxlen)
        if e <= o:
            return None
        t = self.d[o:e]
        if not all(32 <= c < 127 or c in (9, 10) for c in t):
            return None
        return t.decode()

    # ---------- prelink info ----------
    def _prelink(self):
        d = self.d
        i0 = d.find(b'<dict><key>_PrelinkInfoDictionary</key>')
        root = ET.fromstring(d[i0:d.find(b'\0', i0)])
        ids = {}

        def conv(e):
            ref = e.get('IDREF')
            if ref is not None:
                return ids[ref]
            t = e.tag
            if t == 'dict':
                ch = list(e)
                v = {}
                for x in range(0, len(ch), 2):
                    v[ch[x].text] = conv(ch[x + 1])
            elif t == 'array':
                v = [conv(c) for c in e]
            elif t == 'integer':
                v = int(e.text or '0', 0)
            elif t == 'true':
                v = True
            elif t == 'false':
                v = False
            else:
                v = e.text or ''
            if e.get('ID') is not None:
                ids[e.get('ID')] = v
            return v
        self.info = conv(root)['_PrelinkInfoDictionary']

    def _kexts(self):
        names = {k.get('_PrelinkExecutableLoadAddr'): k.get('CFBundleIdentifier', '?') for k in self.info}
        pt = [s for s in self.top if s[0] == '__PRELINK_TEXT'][0]
        self.kexts = []      # (name, [(seg, vm, vms)])
        for m in re.finditer(rb'\xcf\xfa\xed\xfe\x0c\x00\x00\x01', self.d[pt[3]:pt[3] + pt[4]]):
            o = pt[3] + m.start()
            try:
                ss = self._segs(o)
            except Exception:
                continue
            tv = [s for s in ss if s[0] == '__TEXT']
            nm = names.get(tv[0][1], '?') if tv else '?'
            self.kexts.append((nm, [(s[0], s[1], s[2]) for s in ss]))
        # kernel itself
        self.kexts.append(('kernel', [(s[0], s[1], s[2]) for s in self.top
                                      if s[0] in ('__TEXT_EXEC', '__DATA_CONST', '__DATA', '__TEXT')]))
        self.ranges = []
        for nm, ss in self.kexts:
            for seg, vm, vms in ss:
                if vms:
                    self.ranges.append((vm, vm + vms, nm, seg))
        self.ranges.sort()

    def owner(self, va, exec_only=None):
        for a, b, nm, seg in self.ranges:
            if a <= va < b:
                if exec_only is None or (seg == '__TEXT_EXEC') == exec_only:
                    return nm
        return None

    def _symbols(self):
        out = subprocess.run(['nm', self.path], capture_output=True, text=True).stdout
        self.sym = {}
        self.addr_of = {}
        for line in out.splitlines():
            p = line.split()
            if len(p) == 3:
                a = int(p[0], 16)
                self.sym[a] = p[2]
                self.addr_of[p[2]] = a

    def text_words(self, vm, vms):
        o = self.off(vm)
        a = array('I')
        a.frombytes(self.d[o:o + vms - (vms % 4)])
        return a


def sx(v, bits):
    return v - (1 << bits) if v & (1 << (bits - 1)) else v


def decode_stub(words, i, pc):
    """adrp x16, P; ldr x16, [x16, #o]; br x16  ->  GOT address"""
    if i + 2 >= len(words):
        return None
    a, b, c = words[i], words[i + 1], words[i + 2]
    if (a & 0x9F00001F) == 0x90000010 and (b & 0xFFC003FF) == 0xF9400210 and c == 0xD61F0200:
        imm = ((a >> 29) & 3) | (((a >> 5) & 0x7FFFF) << 2)
        page = (pc & ~0xFFF) + (sx(imm, 21) << 12)
        return page + ((b >> 10) & 0xFFF) * 8
    return None
