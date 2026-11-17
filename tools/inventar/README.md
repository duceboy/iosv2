# Inventar-Werkzeug (Teil A/B/D von AUFTRAG-INVENTAR-UND-METAL)

Baut aus einem iOS-IPSW eine lokale SQLite-Datenbank: Kernel-Treiber (Klassen, Vtables, Befehlstabellen mit
Größen/Entitlements, Aufrufe mit konstanten Argumenten), Gerätebaum, Userland-Aufrufstellen (IOKit, MobileGestalt,
sysctl, notify, open), Entitlements, launchd-Jobs, Zuordnung Befehlsnummer → aufrufende Funktion, und die
Verknüpfung je Funktion mit der Qualcomm-Seite.

    python3 -m venv .venv && .venv/bin/pip install capstone numpy
    ./build.sh <IPSW> <ausgabeordner> [d22ap]
    .venv/bin/python link.py <db> <bericht.md> <eigener-kernel>
    .venv/bin/python gen_luecken.py <db> ../../docs/IOS-LUECKEN.md

**Die Datenbank und Berichte enthalten Namen und Tabellen aus Apple-Binärdateien und bleiben lokal** (research/,
gitignored). Ins Repo kommt nur dieser Code und die erzeugte Zahlenübersicht docs/IOS-LUECKEN.md.
Methode: eigener ARM64-Decoder mit Registerverfolgung je Funktion (ADRP/ADD/ADR/LDR/MOV/MOVZ/MOVK), Stubs über
GOT/Chained Fixups aufgelöst, Klassen über OSMetaClass-Konstruktoren (auch -O0-Wrapper) und getMetaClass-Vtable-Slots.
Grenzen: Befehle in switch-basierten externalMethod-Implementierungen ohne Tabelle fehlen; Selektor↔Klasse im
Userland über das gesuchte Matching des Bildes plus Größenvergleich (Spalte match).
