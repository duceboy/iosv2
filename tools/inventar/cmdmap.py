#!/usr/bin/env python3
"""A3: give the numbered user-client commands a meaning. For each user-client class with a dispatch table,
find the userland images that search its service (IOServiceMatching / NameMatching with the service class
or the class name without 'UserClient'), take their IOConnectCall* sites with a constant selector, and
check the constant input sizes against the kernel table. Table ucmd:
  uclass, selector, caller (symbol), image, api, scalar_in_user, struct_in_user, kernel sizes, match.
'match' = sizes agree (code), 'sel' = only selector in range (weak). Read-only, local.  cmdmap.py DB"""
import sys, sqlite3
db = sqlite3.connect(sys.argv[1])
db.executescript('DROP TABLE IF EXISTS ucmd; CREATE TABLE ucmd(uclass TEXT, selector INTEGER, caller TEXT, image TEXT, api TEXT, '
                 'scalar_in_user INTEGER, struct_in_user INTEGER, k_scalar_in INTEGER, k_struct_in INTEGER, entitlement TEXT, match TEXT)')
VAR = 0xffffffff
tables = {}
for cls, sel, a, b, ent in db.execute('SELECT class, selector, scalar_in, struct_in, entitlement FROM kdispatch WHERE class IS NOT NULL'):
    for c in cls.replace(' (über Aufruf)', '').split(','):
        tables.setdefault(c, {})[sel] = (a, b, ent)
pers = db.execute("SELECT ioclass, userclient FROM kpersonality WHERE userclient != ''").fetchall()
svc_for = {}
for ioc, uc in pers:
    svc_for.setdefault(uc, set()).add(ioc)
# gather userland call sites keyed by (image, site)
sites = {}
for tbl, who, fn in (('ucall', 'image', 'caller'), ('ecall', 'binary', 'func')):
    for img, caller, site, api, argi, sval, ival in db.execute(f'SELECT {who}, {fn}, site, api, argi, sval, ival FROM {tbl} WHERE api LIKE "IOConnectCall%"'):
        d = sites.setdefault((img, site), {'caller': caller, 'api': api})
        d[argi] = ival
match_imgs = {}
for tbl, who in (('ucall', 'image'), ('ecall', 'binary')):
    for img, sval in db.execute(f"SELECT DISTINCT {who}, sval FROM {tbl} WHERE api LIKE 'IOService%Matching' AND sval IS NOT NULL"):
        match_imgs.setdefault(sval, set()).add(img)
rows = []
for uc, tab in tables.items():
    svcs = set(svc_for.get(uc, set()))
    base = uc.replace('UserClient', '').replace('UC', '')
    svcs.add(base)
    imgs = set()
    for s in svcs:
        imgs |= match_imgs.get(s, set())
    for (img, site), d in sites.items():
        if img not in imgs:
            continue
        sel = d.get(1)
        if sel is None or sel not in tab:
            continue
        api = d['api']
        si = d.get(3) if api in ('IOConnectCallMethod', 'IOConnectCallScalarMethod') else None
        sti = d.get(5) if api == 'IOConnectCallMethod' else (d.get(3) if api == 'IOConnectCallStructMethod' else None)
        ka, kb, ent = tab[sel]
        ok = True; known = False
        if si is not None:
            known = True; ok &= ka in (VAR, si)
        if sti is not None:
            known = True; ok &= kb in (VAR, sti)
        m = 'match' if known and ok else ('mismatch' if known else 'sel')
        rows.append((uc, sel, d['caller'], img, api, si, sti, ka, kb, ent, m))
db.executemany('INSERT INTO ucmd VALUES (?,?,?,?,?,?,?,?,?,?,?)', rows)
db.commit()
print('rows', len(rows), 'classes', len({r[0] for r in rows}), 'matched selectors',
      len({(r[0], r[1]) for r in rows if r[10] == 'match'}), 'of', sum(len(t) for t in tables.values()))
