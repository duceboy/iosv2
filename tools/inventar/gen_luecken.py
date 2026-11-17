#!/usr/bin/env python3
"""Generates docs/IOS-LUECKEN.md from the local inventory DB: only counts and our own descriptions
(no strings, tables or excerpts from Apple binaries).   gen_luecken.py DB OUT.md"""
import sys, sqlite3, datetime
db = sqlite3.connect(sys.argv[1])
q = db.execute
o = ['# iOS-Lücken (erzeugt)\n\n',
     f'Erzeugt am {datetime.date.today()} von `tools/inventar/gen_luecken.py` aus der lokalen Inventar-Datenbank '
     '(iOS 16.7.16 für iPhone X: Kernel, Gerätebaum, dyld-Cache, Programme). Die Datenbank selbst bleibt lokal, '
     'weil sie aus Apple-Dateien abgeleitet ist; hier stehen nur Zahlen und eigene Beschreibungen.\n\n',
     '## Gesamtzahlen\n\n']
tot = {
 'Kernel-Erweiterungen': q('select count(*) from kext').fetchone()[0],
 'IOKit-Personalities': q('select count(*) from kpersonality').fetchone()[0],
 'Treiberklassen': q('select count(*) from kclass').fetchone()[0],
 'Befehlstabellen / Befehle': f"{q('select count(distinct table_va) from kdispatch').fetchone()[0]} / {q('select count(*) from kdispatch').fetchone()[0]}",
 'Befehle mit zugeordneter Treiberklasse': q('select count(*) from kdispatch where class is not null').fetchone()[0],
 'Befehle mit Funktionsname aus dem Userland (Größen geprüft)': q("select count(distinct uclass||'/'||selector) from ucmd where match='match'").fetchone()[0],
 'Gerätebaum-Knoten (davon mit Treiber)': f"{q('select count(*) from adtnode').fetchone()[0]} ({q('select count(*) from adtnode where drivers is not null').fetchone()[0]})",
 'Hardware-Aufrufstellen im Userland (Cache + Programme)': q('select (select count(distinct site) from ucall)+(select count(distinct binary||site) from ecall)').fetchone()[0],
 'launchd-Jobs': q('select count(*) from ljob').fetchone()[0],
}
o.append('| Größe | Wert |\n|---|---|\n' + ''.join(f'| {k} | {v} |\n' for k, v in tot.items()))
o.append('\n## Je Funktion\n\n| Funktion | Apple-Treiberklassen | davon mit Befehlen | Befehle | im Port | Stand im Port | Qualcomm-Baustein | Linux-Treiber | Vorlagen |\n|---|---|---|---|---|---|---|---|---|\n')
for fn, n, ip, ws, sel in q('select func, count(*), sum(in_port), sum(selectors>0), sum(selectors) from func_driver group by func order by func'):
    b, l, st, t = q('select block, linux, status, templates from func_qcom where func=?', (fn,)).fetchone()
    o.append(f'| {fn} | {n} | {ws} | {sel} | {ip} | {st} | {b} | {l} | {t} |\n')
o.append('\nHinweise: „Apple-Treiberklassen“ ist eine Namens-Zuordnung (Muster je Funktion), „Befehle“ stammen aus den '
         'Befehlstabellen im Kernel (Code). „im Port“ = gleichnamige Klasse im iosv2-Kernel. Details (Klassen, Befehle mit Namen, '
         'Gerätebaum-Knoten, aufrufende Daemons) im lokalen Bericht `research/inventar/FUNKTIONEN.md`.\n')
open(sys.argv[2], 'w').write(''.join(o))
