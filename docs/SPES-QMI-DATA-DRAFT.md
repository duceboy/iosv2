# SPES QMI-Datensteuerung (IPA-Handshake + WDS-Session) – Entwurf

Stand 17.11.2026. **Nur Code-Entwurf: nicht gebaut, nicht gebootet, nicht committet.**
Datei: `~/ios-spes/work/xnu/iokit/Kernel/arm/SpesModem.cpp` (Abschnitt „QMI data (modem_ipa_data=1)“, Präfix `qd_`).
Baut auf `bsd/dev/spes_ipa.c` (SPES-IPA-DRAFT.md) und `bsd/dev/spes_cell.c` (SPES-CELL-DRAFT.md) auf.

Geprüft: Der neue Abschnitt wurde mit Stub-Definitionen per `clang++ -std=c++17 -fsyntax-only -Wall -Wextra` ohne
Warnung übersetzt, und eine Host-Simulation hat den kompletten Ablauf durchgespielt (Handshake → DPM → WDA → Bind →
Family → Start → Runtime Settings → `spes_cell_set_session` → Disconnect-Indication → Session aus). Die erzeugten Bytes
von DPM, WDA, Bind, Family, Start und Runtime entsprechen den HackiOS-Arrays (einzige Abweichung: DL-Maximalgröße, s. u.).
**Das ist kein Kernel-Build.** Die Änderungen außerhalb des neuen Abschnitts sind nicht in der Simulation enthalten.

## Schalter (Gate)

Alles ist nur aktiv, wenn **`modem_ipa_data=1` UND `modem_ipa_readonly` ≠ 1 UND `spes_ipa_ready()`** gilt.
`qd_gate_init()` entscheidet das einmal im Modem-Thread, nach `spes_ipa_init()`/`spes_cell_init()` und vor `modem_boot()`.
Ohne Gate bleibt `qd_on` = false. Dann gilt:
- kein zusätzlicher QRTR-Server und keine neuen NEW_SERVER-Einträge
- die SMP2P-Antwort bleibt 1
- `qd_tick` kehrt sofort zurück
- ohne `modem_ipa_data=1` gibt es nicht einmal eine Logzeile

Weitere Boot-Args:
- `modem_apn=NAME`: als String gelesen, nur `[A-Za-z0-9.-]`, max. 63 Zeichen. Ohne Angabe gilt das Standardprofil der SIM.
  Geloggt wird nur die Länge.
- `modem_ipa_mux=N`: dieselbe Variable wie im IPA-Entwurf, Standard 1.
- `modem_nas=1` (vorhanden) wird empfohlen: Damit startet die Session erst bei „registered + PS attached“. Ohne
  `modem_nas=1` wird Start alle 10 s versucht.

## Ablauf (Reihenfolge)

| # | Schritt | Nachricht | Quelle Layout | Log-Präfix |
|---|---|---|---|---|
| 1 | Eigener IPA-Server 0x31:0x101 (Port 0x4008), zusammen mit pd-mapper/tftp/rmtfs angekündigt | QRTR NEW_SERVER | Linux ipa_qmi.c, HackiOS `our_servers[3]` | `ipa-qmi:` |
| 2 | Modem-Dienst 0x31:0x201 erscheint → **INIT_DRIVER 0x21** mit `spes_ipa_modem_info()` (TLV 0x10–0x17, 0x18 nur bei skip_uc, 0x19, 0x1f/0x20). Die Hash-TLVs 0x1b–0x1e und die Drop-Statistik 0x21/0x22 entfallen bei v4.2 | Req von Port 0x4009 | HackiOS `ipa_init_driver` | `ipa-qmi:` |
| 3 | Modem → unser Server: **INDICATION_REGISTER 0x20**, **DRIVER_INIT_COMPLETE 0x35**, ggf. 0x23 (Filterregeln, IDs zurück), 0x24, 0x27: alle mit Erfolg beantwortet | Resp | HackiOS `ipa_host_receive` | `ipa-qmi:` |
| 4 | INIT_DRIVER akzeptiert + uC bereit (0x35) → **Indication INIT_COMPLETE 0x22** → `spes_ipa_modem_start()`. Ersatzweise geht die Indication nach 10 s auch ohne 0x35 raus (so macht es HackiOS); der Kanalstart wartet weiter auf 0x35 | Ind | Linux `ipa_qmi_ready()` | `ipa-qmi:` |
| 5 | **DPM Open Port 0x20** (Dienst 0x2F): embedded/Iface 1, Consumer = TX-Ep 1, Producer = RX-Ep 9 (`spes_ipa_modem_endpoints()`) | Req 0x400C | HackiOS `dpm_server` | `dpm:` |
| 6 | **WDA Set Data Format 0x20** (0x1A): raw IP, QMAP (5) UL/DL ohne Checksum, DL 16 Pakete / **8192 B** (HackiOS: 14336), Endpunkt 4/1 | Req 0x400B | HackiOS `wda_send_format` | `wda:` |
| 7 | **WDS Bind Mux Data Port 0xA2** (Ep 4/1, Mux) → bei Erfolg `spes_ipa_set_mux()`; **Set IP Family 0x4D** = 4 | Req 0x400A | HackiOS `wds_advance` | `wds:` |
| 8 | **WDS Start Network Interface 0x20**: TLV 0x19 = IPv4, TLV 0x14 = APN (optional). Abgelehnt → nach 10 s erneut. Log zeigt result/error/call-end-reason | Req | HackiOS `wds_send_start` | `wds:` |
| 9 | **WDS Get Runtime Settings 0x2D** (Maske 0xa310) → `spes_cell_set_session(ip, gw, dns1, dns2, mtu)` (TLV 0x1E/0x20/0x15/0x16/0x29 als LE-uint32 = Host-Order) | Req | HackiOS `wds_receive` | `wds:` |
| 10 | **Packet Service Status 0x22**: als Indication und alle 30 s abgefragt. Status 1 (disconnected) → `spes_cell_set_session(0,0,0,0,0)`, zurück zu Schritt 8. Connected + Reconfigure → Schritt 9 erneut. Modem-FATAL → Session aus | Ind/Req | libqmi (nicht in HackiOS) | `wds:` |

Für die Schritte 5–7 gilt: Weiter geht es nach der Antwort, oder nach 20 s ohne Antwort bzw. ohne Dienst (wie HackiOS).
Alles läuft im Watch-Thread (`qrtr_rx → svc_rx → qd_rx`, `modem_watch → qd_tick`), deshalb sind keine Locks nötig.

## Änderungen in SpesModem.cpp

- **Dateianfang** (bei `extern "C" bool spes_ipa_init`):
  - `struct spes_ipa_modem_info` als Kopie, mit `static_assert` Größe 68
  - `extern "C"`-Deklarationen für `spes_ipa_ready/_modem_start/_modem_info/_modem_endpoints/_clock_on/_set_mux` und
    `spes_cell_set_session`
  - Ports `PORT_IPAH/IPAC/WDSC/WDAC/DPMC` = 0x4008–0x400C
  - Variablen `qd_on`, `qd_*_node/port/have`, `qd_nas_reg`
  - Vorwärtsdeklarationen `qd_ipa_server_up`, `qd_modem_gone`
- **`qrtr_rx`**, NEW_SERVER: Nur bei `qd_on` werden 0x31:0x201 (→ INIT_DRIVER), 0x01, 0x1A und 0x2F gemerkt.
- **`svc_name`**: zusätzlich 0x2F „dpm“ (nur Log).
- **`svc_announce`**: Bei `qd_on` wird der IPA-Server 0x31:0x101 angekündigt.
- **`nas_rx`** (0x24): setzt `qd_nas_reg` (registered && PS attached). Ohne Gate hat das keine Wirkung.
- **Neuer Abschnitt vor `svc_rx`**: `qd_*`-Funktionen (Senden, Handshake, Zustandsautomat, `qd_rx`, `qd_tick`,
  `qd_gate_init`).
- **`svc_rx`**: Ports 0x4008–0x400C gehen an `qd_rx`, nur bei `qd_on`.
- **`modem_watch`**:
  - SMP2P-Antwort `qd_on ? (spes_ipa_clock_on() ? 3 : 1) : 1`
  - im FATAL-Zweig `qd_modem_gone()`
  - in der 1-ms-Schleife `qd_tick(ms)`
- **`spes_modem_thread`**: `qd_gate_init()` nach `spes_cell_init()`.

## Offene Fragen (wichtigste zuerst)

1. **INIT_DRIVER-Werte für v4.2:**
   - TLV 0x20 `hw_stats_quota_size` kommt aus `spes_ipa_modem_info()` mit addiertem `ipa_mem_offset` (Linux macht es so).
     HackiOS und Android senden die echte Größe (0x30).
   - Lehnt das Modem ab oder assertiert, zuerst hier ansetzen (im IPA-Entwurf ändern).
   - Ebenfalls ungeprüft: `platform_type` 3 und ob v4.2-Modems die Hash-TLVs wirklich nicht erwarten.
2. **Reihenfolge Indication/uC:** Linux sendet INIT_COMPLETE erst nach DRIVER_INIT_COMPLETE (uC bereit), HackiOS schon
   nach dem akzeptierten INIT_DRIVER. Der Entwurf folgt Linux, mit 10-s-Ersatzweg. Kommt 0x35 nie, startet die IPA nie,
   und dann gibt es keine Datenschritte. Das Log zeigt das. Lädt das Modem den uC selbst (SMMU-Stream 0x142 fehlt im
   IPA-Entwurf)?
3. **DL-Aggregation:** WDA-DL-Maximum auf 8192 B gesetzt, passend zu den 8-KB-RX-Puffern des IPA-Entwurfs. HackiOS nutzt
   14336. Ob das Modem kleinere Werte annimmt oder die Hardware-Aggregation des AP-Endpunkts maßgeblich ist: CHECK.
4. **Packet-Service-Status-Indication 0x22:** Layout (TLV 0x01: Status u8, Reconfigure u8; 0x10 Call-End-Reason) stammt
   aus libqmi, nicht aus HackiOS. Ob das Modem sie ohne Registrierung an den Client schickt, ist offen. Deshalb gibt es
   zusätzlich die 30-s-Abfrage mit derselben Nachrichtennummer (Get Packet Service Status).
5. **DPM:** Das Feldlayout (Consumer = AP-TX-Ep, Producer = AP-RX-Ep) ist von HackiOS/ModemManager übernommen. Für v4.2
   mit Ep 1/9 ist es ungetestet.
6. **WDS-Instanz:** Es wird die erste WDS-Instanz genommen, die erscheint. Meldet das Modem mehrere, ist das evtl. nicht
   die richtige.
7. **Kein Abbau / kein Modem-Neustart:**
   - DEL_SERVER wird nicht ausgewertet.
   - Nach einem Modem-Neustart müsste der Handshake neu laufen (mit skip_uc).
   - `spes_ipa_modem_start()` ist einmalig.
8. **Filterregeln (0x23)** werden nur quittiert, nicht in die IPA geschrieben (wie HackiOS). Ob das Uplink-Routing ohne sie
   funktioniert, ist offen.
9. Laufzeit-Log enthält die vom Netz vergebene IP/DNS (keine Geräte-Kennung). Beim Zitieren maskieren, nicht pushen.

## Test Schritt für Schritt (jede Stufe ein eigener Lauf, sweetlog/USB-Live-Log)

Voraussetzung: Die IPA-Stufen 1 und 2 aus SPES-IPA-DRAFT.md sind bestanden (readonly-Probe, Firmware/GSI „IPA set up“).

1. **Gate aus (Regression):** wie bisher booten (`modem=1 wifi=1 modem_nas=1 modem_online=1`, ohne `modem_ipa_data`).
   Erwartet: keine `ipa-qmi:`/`wds:`-Zeilen, „answered IPA power query (…) with 1“, LTE-Registrierung wie bisher.
2. **Gate an, readonly:** `modem_ipa_data=1 modem_ipa_readonly=1`. Erwartet: „modem_ipa_readonly=1: QMI data control
   stays off“, sonst wie Lauf 1.
3. **Handshake:** `modem_ipa_data=1` (ohne readonly), `modem_cell=1`, noch ohne `modem_online=1`. Erwartet:
   - „QMI data control on“ und „announced our IPA server“
   - „modem IPA service 0x31:0x201 up“, INIT_DRIVER-Zeile, „modem ACCEPTS INIT_DRIVER“
   - INDICATION_REGISTER, DRIVER_INIT_COMPLETE, „INIT_COMPLETE indication sent“
   - „IPA modem data channels started“
   - SMP2P-Antwort „with 3“

   Bei REFUSES: result/error notieren → offene Frage 1.
4. **Datenport:** zusätzlich `modem_nas=1 modem_online=1`. Erwartet:
   - „dpm: embedded data port OPEN“
   - „wda: data format SET … link 2, UL 5 DL 5“
   - „wds: bind mux 1 OK“ und „IP family IPv4 set“
   - nach „nas: registered … ps attached“: „wds: start network interface“ → „SESSION STARTED“ → „SESSION UP: …“
   - en1-Log „link up“
5. **Daten:** `modem_cell_trace=50 modem_ipa_trace=1`, WLAN aus (oder ohne `wifi=1`). Per SSH `ifconfig en1`, Ping und
   DNS über en1. Gezählt wird in `spes_cell_status`/`spes_ipa_status`.
6. **Abriss:** Flugmodus ist nicht vorhanden, daher z. B. SIM entfernen bzw. abwarten. Erwartet: „packet service status 1“
   → „session down … en1 link down“, danach neue Startversuche alle 10 s.
7. **APN (nur falls das SIM-Standardprofil abgelehnt wird):** `modem_apn=<apn>`. Im Log erscheint nur „APN length N“.

Für den Build fehlen noch: eine Patchnummer nach den IPA-/en1-Patches und optional ein Host-Test
(`tests/test_spes_qmi_data.*`) aus der Simulation im Scratchpad. Die Simulation liegt nicht im Repo.
