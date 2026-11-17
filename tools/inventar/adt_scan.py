#!/usr/bin/env python3
"""A2: Apple device tree (ADT, decompressed payload) -> SQLite tables adt (every property) and adtnode
(path, name, compatible, device_type, matching driver classes from the kernel personalities).
Read-only, output local.   adt_scan.py ADT DB"""
import sys, sqlite3, struct

d = open(sys.argv[1], 'rb').read()
db = sqlite3.connect(sys.argv[2])
db.executescript(open(__file__.rsplit('/', 1)[0] + '/schema.sql').read())
db.execute('CREATE TABLE IF NOT EXISTS adtnode(path TEXT, name TEXT, compatible TEXT, device_type TEXT, drivers TEXT)')
db.execute('DELETE FROM adt'); db.execute('DELETE FROM adtnode')

def sval(v):
    parts = [p for p in v.split(b'\0') if p]
    if parts and all(all(32 <= c < 127 for c in p) for p in parts) and len(b''.join(parts)) >= max(1, len(v.rstrip(b'\0')) - len(parts)):
        return '|'.join(p.decode() for p in parts)
    return None

rows, nodes = [], []
def node(p, path):
    nprops, nchild = struct.unpack_from('<II', d, p); p += 8
    props = {}
    for _ in range(nprops):
        name = d[p:p + 32].split(b'\0')[0].decode('latin1'); ln = struct.unpack_from('<I', d, p + 32)[0]
        real = ln & 0x7fffffff
        v = d[p + 36:p + 36 + real]
        props[name] = v
        p += 36 + ((real + 3) & ~3)
    nm = sval(props.get('name', b'')) or '?'
    me = path + '/' + nm if path else nm
    for k, v in props.items():
        rows.append((me, k, len(v), sval(v), v[:64].hex()))
    nodes.append((me, nm, sval(props.get('compatible', b'')), sval(props.get('device_type', b''))))
    for _ in range(nchild):
        p = node(p, me)
    return p

node(0, '')
db.executemany('INSERT INTO adt VALUES (?,?,?,?,?)', rows)

# which driver attaches: IONameMatch entries are matched against name / compatible / device_type
pers = db.execute("SELECT ioclass, provider, match FROM kpersonality WHERE match != ''").fetchall()
index = {}
for ioc, prov, m in pers:
    if m.startswith('{'):
        continue
    for key in m.split('|'):
        index.setdefault(key, set()).add(ioc)
out = []
for path, nm, comp, dt in nodes:
    keys = [nm] + (comp.split('|') if comp else []) + ([dt] if dt else [])
    drv = set()
    for k in keys:
        drv |= index.get(k, set())
    out.append((path, nm, comp, dt, ','.join(sorted(drv)) or None))
db.executemany('INSERT INTO adtnode VALUES (?,?,?,?,?)', out)
db.commit()
print(f'nodes {len(nodes)} props {len(rows)} nodes with driver {sum(1 for o in out if o[4])}')
