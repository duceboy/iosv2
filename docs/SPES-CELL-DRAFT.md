# SPES Mobilfunk-Schnittstelle en1 – Entwurf

Stand 17.11.2026. **Nur Code-Entwurf: nicht gebaut, nicht gebootet, nicht committet.**

Dateien (Prüfbaum `~/ios-spes/work/xnu`):
- `bsd/dev/spes_cell.c` – Treiber (Schnittstelle en1, ARP-/DHCP-Antworten, TX/RX zum IPA)
- `bsd/dev/spes_cell.h` – Schnittstelle für SpesModem.cpp (`extern "C"`)
- `bsd/conf/files`: Zeile `bsd/dev/spes_cell.c standard` direkt nach `spes_ipa.c` eingetragen (sonst nichts geändert)

Geprüft:
- `clang -fsyntax-only -Wall -Wextra` gegen Stub-Header, mit und ohne `ARM64_BOARD_CONFIG_SWEET`: ohne Fehler, ohne
  Warnung. Die einzige Meldung (unbenutzte Lock-Gruppe) kommt vom Stub-Makro.
- Host-Test: Die Datei wird per `#include` mit Stub-mbufs und Stub-KPIs übersetzt (scratchpad, nicht im Repo). Abgedeckt:
  - DISCOVER→OFFER mit allen Optionen und korrekter IP-Prüfsumme
  - REQUEST→ACK, REQUEST mit fremder Adresse→NAK, Renew über ciaddr→ACK, INFORM→keine Antwort
  - ARP für den Router wird beantwortet, ARP-Probe auf die eigene Adresse nicht
  - TX entfernt Ethernet-Padding, IPv6-TX wird verworfen
  - RX baut den Ethernet-Header, IPv6-RX wird verworfen
  - Link-Ereignisse bei neuer Session (aus/an) und bei Session-Ende

Das alles ist **kein Kernel-Build**.

## Was die Datei macht

iOS baut seine Mobilfunk-Schnittstelle (`pdp_ip0`) über CommCenter und Apples Baseband-Stack, und den gibt es hier nicht.
Deshalb geht der Entwurf wie HackiOS `drivers/modem/hakios.cell.c` vor: Das Modem erscheint als Ethernet-Schnittstelle
**en1** hinter einem erfundenen Router. configd/IPConfiguration behandelt sie wie einen USB-Ethernet-Adapter.

| Richtung | Weg |
|---|---|
| Stack → Modem | `cell_output()`: ARP → lokale Antwort „Adresse ist beim Router“ (außer für die eigene Adresse). DHCP (UDP 68→67) → lokale Antwort. Sonstiges IPv4 → Ethernet-Header weg, Padding über IP-Total-Length weg, `spes_ipa_tx()`. IPv6 und Rest → verworfen, gezählt |
| Modem → Stack | `cell_rx_hook()` (in `spes_ipa_rx_hook` eingetragen): nur IPv4 ≤ 1500 B, Ethernet-Header Router→en1 davor, ein mbuf mit 2-KiB-Cluster (wie sweet_usb.c), `bpf_tap_in` + `ifnet_input` |
| DHCP | DISCOVER→OFFER, REQUEST→ACK (NAK bei anderer Adresse; Renew über ciaddr). Optionen: 53, 54 (Server = Router), 51 (Lease 86400 s), 1 (/24), 3 (Router), 6 (DNS1/2, sofern ≠ 0), 26 (MTU). UDP-Prüfsumme 0, IP-Ziel 255.255.255.255, Ethernet-Ziel = en1 |
| Link | `KEV_DL_LINK_ON/OFF` per `ifnet_event` + `SIOCGIFMEDIA` meldet „aktiv“, solange eine Session besteht (wie redwood_net.c) |

Die DHCP-Netzmaske und der Router stammen nicht vom Modem. Eine Mobilfunk-Session ist Punkt-zu-Punkt, und das WDS-Gateway
liegt oft in keinem gemeinsamen Netz mit der Adresse. Deshalb bekommt en1 ein /24 um die Adresse und den Router auf .1
(bzw. .2, wenn .1 die eigene Adresse ist). Jedes Paket geht ohnehin zum Modem.

MAC en1 `02:73:70:63:6c:01`, Router `…:fe`. Beide lokal administriert und erfunden („spcl“), nicht aus Seriennummer oder
WLAN-MAC abgeleitet.

### Byte-Reihenfolge

`spes_cell_set_session(ip, gw, dns1, dns2, mtu)` erwartet **Host-Order**: 10.1.2.3 = `0x0a010203`. Das ist genau der Wert,
den man erhält, wenn man die QMI-WDS-TLVs als Little-Endian-uint32 liest. **Nicht** htonl anwenden.

### Boot-Args

| Boot-Arg | Wirkung |
|---|---|
| `modem_cell=1` | en1 anlegen, sobald `spes_ipa_ready()` |
| `modem_cell=2` | en1 auch ohne IPA anlegen; TX liefert dann ENODEV und wird gezählt |
| `modem_cell_test=1` | nur mit `=2`: Schein-Session 192.0.2.2/24, Router/DNS 192.0.2.1 (TEST-NET-1). Damit lässt sich configd/DHCP auf en1 ohne Modem beobachten |
| `modem_cell_trace=N` | die ersten N Pakete/Antworten loggen (Länge/Protokoll, ARP-Ziel) |

## Aufrufreihenfolge

1. `spes_ipa_init()` → true (SpesModem-Thread).
2. `spes_cell_init()`, aus demselben Thread, ohne gehaltene Locks (darf schlafen). Legt en1 an, setzt die MAC, `bpfattach`,
   trägt `spes_ipa_rx_hook = cell_rx_hook` ein. Gibt false zurück, wenn `modem_cell=0` oder die IPA nicht bereit ist.
3. IPA-QMI-Handshake → `spes_ipa_modem_start()` (siehe SPES-IPA-DRAFT.md).
4. WDA Set Data Format, DPM Open Port, WDS Bind Mux (→ `spes_ipa_set_mux`), WDS Start Network Interface.
5. WDS Get Runtime Settings → `spes_cell_set_session(ip, gw, dns1, dns2, mtu)` → Link an → configd macht DHCP → Route.
6. Session weg (WDS Packet Service Status „disconnected“, Modem-Neustart) → `spes_cell_set_session(0,0,0,0,0)` → Link aus.
   Neue Werte bei laufender Session → Link kurz aus/an, damit configd neu fragt.

`spes_cell_set_session()` darf auch **vor** `spes_cell_init()` kommen. Die Werte bleiben gespeichert, und init hebt
dann den Link an. `spes_cell_status()` liefert eine Zählerzeile, z. B. für den USB-Befehlsserver.

## Was die QMI-Seite liefern muss

- **WDS Get Runtime Settings** (0x2D), Request-TLV 0x10 Requested Settings mit Bits für IPv4-Adresse, Gateway, DNS und MTU.
  Antwort-TLVs:
  - 0x1E IPv4-Adresse
  - 0x20 Gateway
  - 0x21 Subnet-Maske (nur fürs Log)
  - 0x15/0x16 primärer/sekundärer DNS
  - 0x29 MTU

  /* CHECK: TLV-Nummern aus libqmi `qmi-service-wds.json`, nicht lokal geprüft */
- Alle Werte als uint32 LE gelesen = Host-Order, direkt übergeben.
- Ein Session-Ende-Signal: WDS Packet Service Status Indication (0x22) oder Event Report. Sonst bleibt en1 nach einem
  Abriss „aktiv“.
- Mux-ID aus Bind Mux Data Port an `spes_ipa_set_mux()`. `cell_rx_hook` nimmt jede Mux-ID an und loggt sie nur
  (eine Session).
- Die APN (Start Network Interface TLV 0x14) ist Sache der QMI-Seite; dieser Entwurf kennt sie nicht.

## Threading (Kurzfassung, Details im Dateikopf)

- **TX** läuft im Sende-Thread des Stacks (Legacy-Schnittstelle, nie im Interrupt). Reihenfolge der Locks:
  `cell_lock` → IPA-`tx_lock`, nie umgekehrt.
- **RX** läuft im IPA-Poll-Thread ohne Lock:
  - Er muss kopieren (DMA-Puffer) und darf nicht schlafen, denn der Ring wird erst danach neu befüllt.
  - mbufs werden mit `MBUF_DONTWAIT` angelegt; schlägt das fehl, wird das Paket verworfen und gezählt.
  - `ifnet_input` reiht bei Legacy-Schnittstellen nur in den DLIL-Eingangs-Thread ein (dlil.c: `IFXF_LEGACY` →
    `dlil_input_async`).
- **Lokale ARP-/DHCP-Antworten** werden unter `cell_lock` gebaut, aber erst nach dem Freigeben an `ifnet_input`
  übergeben.
- Die Zähler sind nicht atomar und dienen nur dem Log.

## Offene Fragen

1. **configd/preferences.plist:** Wie bei en0 (WLAN) legt iOS für en1 vermutlich keinen Netzwerkdienst an. Wahrscheinlich
   ist ein Ethernet-Dienst mit DHCP in `preferences.plist` nötig, nach dem Muster von `tools-local/spes-install-wlanprefs.sh`.
   Offen ist auch, ob SCNetworkInterface eine Schnittstelle ohne IOKit-Objekt überhaupt auflistet. Für en0 musste
   `RedwoodWLANStart` ein IOKit-Objekt liefern.
   /* CHECK */
2. **Dienst-Reihenfolge:** Ist WLAN gleichzeitig verbunden, entscheidet die ServiceOrder, welche Default-Route gilt. Ein
   kabelgebundener Ethernet-Dienst steht bei macOS oft vor WLAN. Gewünscht ist WLAN zuerst.
   /* CHECK */
3. **Name en1 frei?** Im Prüfbaum legen nur redwood_net.c (en0) und sweet_usb.c (ue0) Schnittstellen an. Ob iOS-Userland
   (z. B. `ifconfig`-Annahmen in wifid) en1 anders erwartet, ist offen.
   /* CHECK */
4. **DHCP-Empfang:** Liest IPConfiguration DHCP-Antworten über Socket oder BPF? Für beides ist gesorgt (`bpfattach`,
   `bpf_tap_in`, UDP-Prüfsumme 0).
   /* CHECK auf dem Gerät mit `modem_cell=2 modem_cell_test=1` */
5. **MTU > 1500** vom Netz wird auf 1500 begrenzt; Pakete > 1500 aus dem Modem werden verworfen. Der IPA-Entwurf hat
   2-KB-TX-Puffer, also passen 1500 + 4 B.
   /* CHECK: typische Netz-MTU 1400–1500 */
6. **IPv6** wird nicht getragen. Für eine IPv4v6-Session würden v6-Pakete verworfen; das Modem sollte nur IPv4 anfordern
   (WDS IP-Family-Präferenz 4).
7. **Kein Checksum-Offload:** `ifnet_set_offload(0)`, der Stack rechnet selbst. Das passt zum IPA-Entwurf (QMAP ohne
   Checksum-Trailer).
8. **Log-Inhalt:** Die DHCP- und Session-Zeilen enthalten die vom Netz vergebene IP- und DNS-Adresse. Keine
   Geräte-Kennung, aber beim Zitieren aus sweetlogs maskieren und nicht pushen.
9. **Kein Abbau:** kein `ifnet_detach`, der Hook bleibt eingetragen. Ein zweites `spes_cell_init()` liefert nur true zurück.
10. **Barriere:** `dmb ish` zwischen dem Setzen von `cell_ifp` und dem Eintragen des Hooks. Ob der Poll-Thread den Hook
    schon vor `spes_ipa_modem_start()` aufrufen kann, ist egal, weil `cell_ifp` vorher gesetzt ist.

## Vorschlag Testreihenfolge

1. `modem_cell=2 modem_cell_test=1` (ohne Modem): Erwartet werden die Logzeilen „en1 attached“ und „link up“. Dann prüfen,
   ob configd DHCP schickt (Zeile „DHCP DISCOVER -> OFFER“) und `ifconfig en1` per SSH 192.0.2.2 zeigt. Damit ist Frage 1
   geklärt. Ein Ping auf 192.0.2.1 läuft als TX ins Leere (ENODEV, gezählt).
2. Nach dem IPA-Handshake und WDS: `modem_cell=1 modem_cell_trace=50` → erste Pakete in beide Richtungen.
   DNS-Auflösung und Ping über en1 bei abgeschaltetem WLAN.

Für den Build braucht es noch:
- eine Patchnummer (nach dem IPA-Patch)
- den Aufruf von `spes_cell_init()` und `spes_cell_set_session()` in SpesModem.cpp
- optional den Host-Test als `tests/test_spes_cell.c`/`.py` ins Repo
