# SPES IPA 4.2 – Entwurf des Datenpfads AP ↔ Modem

Stand 17.11.2026. **Nur Code-Entwurf: nicht gebaut, nicht gebootet, nicht committet.**
Gegen Stub-Header geprüft: `clang -fsyntax-only -Wall -Wextra` lief ohne Fehler und ohne Warnung (mit und ohne
`ARM64_BOARD_CONFIG_SWEET`). Das ist kein Kernel-Build.

Dateien:
- `bsd/dev/spes_ipa.c` – Treiber (etwa 1150 Zeilen)
- `bsd/dev/spes_ipa.h` – Schnittstelle für SpesModem.cpp und eine spätere en1-Datei
- Noch **nicht** eingetragen: `bsd/conf/files` (`bsd/dev/spes_ipa.c standard`), kein Aufrufer, kein Patch-File.

## Was die Datei macht

Sie richtet die AP-Seite des IPA v4.2 ein (DT `qcom,ipa-hw-ver = <0x10>`) und arbeitet ohne Interrupts.
Ein Kernel-Thread fragt alle 1 ms die Event-Ringe ab. Nichts passiert ohne `modem_ipa_data=1`.

| Rolle | Endpunkt | GSI-Kanal | Event-Ring | Ring/TLV (Entwurf) | Puffer |
|---|---|---|---|---|---|
| Befehle (Immediate Commands) | 6 | 1 | 0 | 32 / 20 | 64 B |
| LAN RX (Default-Route, Ausnahmen; verworfen) | 8 | 2 | 1 | 16 / 6 | 8 KB, Aggregation, Status an |
| AP → Modem (QMAP) | 1 | 0 | 2 | 64 / 8 | 2 KB |
| Modem → AP (QMAP, aggregiert) | 9 | 3 | 3 | 32 / 6 | 8 KB, Aggregation, EOF-Close |

Die Modem-Kanäle 0–3 (EE 1) werden per `GENERIC_CMD ALLOCATE_CHANNEL` vom AP angelegt. Das ist eine Eigenheit von
IPA v4.2 (Linux `gsi.c`: `modem_alloc = version == IPA_VERSION_4_2`).

Der gesamte DMA-Speicher kommt aus dem SpesModem-Pool (`spes_pool_alloc`): zusammenhängend, unter 4 GiB,
Normal-NC. Deshalb ist keine Cache-Pflege nötig, nur `dsb` vor Doorbells. Bedarf etwa 600 KB von 16 MB.

### Schnittstelle (spes_ipa.h)
- `bool spes_ipa_init(void)` – synchron, darf schlafen; aus dem Modem-Thread aufrufen.
- `bool spes_ipa_modem_start(void)` – startet die Kanäle 0/3. Erst **nach** dem IPA-QMI-Handshake
  (wie Linux `ipa_qmi_ready()` → `ipa_modem_start()` → `ipa_open()`).
- `int spes_ipa_tx(const void *ip, size_t len)` – QMAP-Header (pad 0, mux, Länge BE) plus Kopie.
  Rückgabe 0 / ENODEV / EMSGSIZE / ENOBUFS.
- `void (*spes_ipa_rx_hook)(const void *ip, size_t len, uint8_t mux)` – wird je IP-Paket aus dem Poll-Thread
  aufgerufen. Der Zeiger zeigt in den DMA-Puffer, der Aufrufer muss kopieren.
- `spes_ipa_set_mux()`, `spes_ipa_modem_info()` (alle Offsets für QMI INIT_DRIVER),
  `spes_ipa_modem_endpoints()` (1/9 für DPM), `spes_ipa_clock_on()` (für die SMP2P-Antwort), `spes_ipa_status()`.

### Boot-Args
`modem_ipa_data=1` (an) · `modem_ipa_readonly=1` (nach Clock-Vote und Lese-Probe aufhören) ·
`modem_ipa_clk=0` (keinen Clock-Vote) · `modem_ipa_fw=0` (keine Firmware laden) · `modem_ipa_trace=1` ·
`modem_ipa_mux=N` (Standard 1).

## Init-Reihenfolge (nach Linux `ipa_probe()`: config → firmware → setup)

0. Gate prüfen. IPA-Takt per RPM-SMD-Vote (`spes_rpm_kvp`, Ressource „ipa“, 100 000 kHz). Register mappen.
   Lese-Probe: SHARED_MEM_SIZE, FLAVOR_0, COMP_CFG, ROUTE, GSI_STATUS, HW_PARAM_2, Kanal-/Ring-Zustände.
   → bei `modem_ipa_readonly=1` Ende.
1. SMMU-Identitätskontext für SID 0x140, Maske 0 (`spes_smmu_identity`).
2. SMEM-Item 497 (0x2000 B) in der Partition Apps↔Modem anlegen und nullen, falls es fehlt (Linux `ipa_smem_init`).
3. `ipa_config()`:
   - Hardware: BCR=0, TX_CFG.PA_MASK_EN aus, CLKON_CFG GLOBAL|2X, COMP_CFG Bits 15/7/8, QSB 8/12,
     COUNTER_CFG Granularität 15, FILT_ROUT_HASH_EN=0, IDLE 256.
   - Canaries 0xdeadbeef über direkten SRAM-Zugriff.
   - FLAVOR_0-Prüfung der Endpunkte.
   - Ressourcengruppen: SRC {3/63, 3/3, 10/10, 1/1, 5/5}, DST {3/3, 1/63}.
4. Firmware (nur wenn GSI noch nicht `ENABLED`): TZ-PAS-ID 15, `ipa_fws.mdt` + `.b00–.b04` vom iOS-Root
   (`/usr/share/firmware/spes/ipa/`) nach 0x56600000. Ablauf: init_image → mem_setup(0x56600000, 0x5000) →
   Segmente kopieren → auth_and_reset. Danach bis 1 s auf `GSI_STATUS.ENABLED` warten.
5. `gsi_setup()`:
   - Alle GSI-IRQs maskieren, INTSET=IRQ, ERROR_LOG=0.
   - Je Kanal: Event-Ring ALLOCATE + programmieren, dann Kanal ALLOCATE + programmieren
     (CNTXT_0/1/2/3, QOS, GPI-Scratch).
   - Danach die Modem-Kanäle 0–3 per GENERIC_CMD.
6. Alle vier Endpunkte programmieren. Befehlskanal starten, dann `ipa_mem_setup()`:
   HDR_INIT_LOCAL 0x4a8/0x140, Null-DMA für proc-ctx Modem/AP und Modem-Bereich, LOCAL_PKT_PROC_CNTXT.
   Dann `ipa_table_setup()`:
   - Route v4/v6: je 15 Einträge
   - Filter v4/v6: Bitmap (BIT1|BIT4)<<1 plus 2 Einträge; der Rest der Filterregion wird genullt
   Danach LAN RX starten, Puffer einreihen, ROUTE = Endpunkt 8.
7. Poll-Thread starten. `spes_ipa_modem_start()` kommt später vom QMI-Code.

## Herkunft der Werte

| Wert | Quelle | Sicherheit |
|---|---|---|
| ipa-base 0x5800000/0x34000, gsi-base 0x5804000/0x28000, ee 0, IRQ SPI 0x101/0x103 | Live-DTB `qcom,ipa@0x5800000` | sicher |
| **IPA-Register = 0x5840000** (ipa-base + 0x40000) | Downstream-ipa3 (`ipa_reg_base_ofst`), gleiches Layout wie sc7180 (ipa 0x1e40000 / gsi 0x1e04000); ipa_fws-ELF hat ein Segment bei vaddr 0x585e000 | **CHECK** – wichtigste Annahme |
| SRAM (ipa-shared) = IPA-Register + 0x7000 + mem_offset, 0x2000 | sc7180-DT, Downstream SW_AREA_RAM_DIRECT_ACCESS_n | CHECK |
| SMMU-SID 0x140 Maske 0 (wlan 0x141, uc 0x142), apps_smmu 0xc600000 | Live-DTB `ipa_smmu_ap`; zusätzliches Mapping 0xc123000+0x2000 (wird vom Identity-Kontext abgedeckt) | sicher |
| PAS 15, firmware-name „ipa_fws“, reserviert 0x56600000+0x10000 (no-map) | Live-DTB `qcom,ipa_fws`, `pil_ipa_fw_mem` | sicher |
| ipa_fws.mdt: 0xd4 Header + 0x1a98 Hash direkt dahinter (7020 B); LOAD-Segmente paddr 0/0x4000/0x4080 (relocatable), vaddr 0x5808000 (GSI-IRAM) / 0x585e000 | eigene ELF-Analyse der Dateien in `spesn-vendor/vendor/firmware` | sicher; scuba_ipa_fws hat dieselben Header, aber eine andere MD5 → nicht verwendet |
| Endpunkte/Kanäle/TLV, Ressourcengrenzen, Speicherkarte, QSB, modem_route_count 8, smem 497/0x2000, Takt 100 MHz | Linux `ipa_data-v4.2.c` | sicher für v4.2 (Takt: CHECK für khaje) |
| Registeroffsets/Feldlayout IPA | `ipa_reg-v4.2.c` (AGGR: TIME_LIMIT 14:10, SW_EOF 21, anders als v4.11!) | sicher |
| GSI-Offsets (EE0 0x1c000/0x1d000/0x1e000/0x1f000), Felder, Opcodes, GENERIC-Ergebnisse | `gsi_reg-v4.0.c`, `gsi_reg.h`, `gsi.c` | sicher |
| Programmierfolge GSI, QOS (Escape-Buffer v4.0–4.4), Scratch, Event-Doorbell | `gsi.c` | sicher |
| Endpunkt-Programmierung, Default-Route, Status | `ipa_endpoint.c` | sicher, aber **ohne Checksum-Offload** (Abweichung, s. u.) |
| Payload-Layout der Befehle, DMA_SHARED_MEM, HDR_INIT_LOCAL, Tabelleninit | `ipa_cmd.c`, `ipa_table.c`, `ipa_mem.c` | sicher |
| Opcode-Nummern (3/4/7/8/9/19) | `ipa_cmd.h` (fehlt lokal), wie HackiOS | CHECK |
| IPA_AGGR_GRANULARITY 500 µs | `ipa.h` (fehlt lokal) | CHECK |
| TRE-Flags (IEOT Bit 9, BEI 10, TYPE 23:16) | `gsi_trans.c` (fehlt lokal), wie HackiOS | CHECK |
| RPM-Ressource 0x00617069 „ipa“, Schlüssel „KHz“, Index 0x0a der rpmcc-bengal | `clk-smd-rpm.c` aus dem Gedächtnis; Index nicht geprüft | **CHECK** |
| QMI-Plattformtyp MSM_ANDROID = 3 | `ipa_qmi_msg.h` (fehlt lokal) | CHECK |

## Was noch fehlt („needs implementing“)

1. **Firmware aufs Telefon**: `ipa_fws.mdt` und `.b00–.b04` aus `iosv2/research/spesn-vendor/vendor/firmware/`
   nach `/usr/share/firmware/spes/ipa/` im iOS-Root kopieren (z. B. über den Dateiserver/SSH).
   **Nie ins Repo.** Die Dateien liegen nicht in modem_b, deshalb hilft `spes_part_fw_*` nicht.
2. **Aufrufstelle in SpesModem.cpp** (`spes_modem_thread`): nach `spes_soc_map()` und vor `modem_boot()`
   (oder spätestens vor `modem_online=1`) `spes_ipa_init()` aufrufen.
   HackiOS: Ein Modem, das ohne IPA-Firmware online geht, stirbt in `enl2_dl`.
   `fw_size()` wartet bis 60 s auf das Root-Dateisystem.
3. **SMP2P-Antwort**: `modem_watch()` schreibt heute fest `*ipa_out = 1` (gültig, Takt aus).
   Bei laufender IPA `spes_ipa_clock_on() ? 3 : 1` setzen (Bit 0 gültig, Bit 1 an; Linux `ipa_smp2p.c`).
4. **SMMU**: Im Entwurf ist das nur der Aufruf `spes_smmu_identity(0x140, 0, "IPA")`. Offen ist, ob der
   Hypervisor diese SMR annimmt; für WLAN 0x1A0, Audio 0x1C1 und USB 0x120 hat es funktioniert.
   Der uC-Stream 0x142 wird nicht eingerichtet. Prüfen, ob das Modem den uC lädt und der uC in DDR schreibt.
5. **IPA-QMI-Handshake** (Dienst 0x31) in SpesModem, damit das Modem die Tabellen kennt und seine Filterregeln
   für Endpunkt 1 einträgt. Ohne das gibt es kein Routing zum Modem:
   - Client → Modem-Dienst (Instanz 2): `INIT_DRIVER` (Msg 0x21) mit Werten aus `spes_ipa_modem_info()`.
     TLVs 0x10–0x22 laut `ipa_qmi_msg.c` (CHECK, fehlt lokal).
   - Eigener Server (Instanz 1): `INDICATION_REGISTER` (0x20) und `DRIVER_INIT_COMPLETE` (0x35) beantworten,
     dann die Indication `INIT_COMPLETE` (0x22) senden. Danach `spes_ipa_modem_start()`.
6. **WDA Set Data Format** (Dienst 0x1A, Msg 0x20):
   - Link-Layer raw-IP
   - UL/DL-Aggregationsprotokoll QMAP **ohne Checksum** (passend zu CFG=0 und HDR_LEN 4)
   - Endpunkt-TLV: ep_type embedded (4?), iface 1 (CHECK)
7. **DPM Open Port** (Dienst 0x2F, Msg 0x20): Hardware-Datenport ep_type embedded, iface 1,
   Consumer-Pipe 1, Producer-Pipe 9 (`spes_ipa_modem_endpoints()`). Feldreihenfolge: CHECK.
8. **WDS**: Bind Mux Data Port (0xA2: ep embedded/iface 1, mux 1 → `spes_ipa_set_mux`), Start Network
   Interface (0x20, APN), Get Runtime Settings (0x2D: IP, Gateway, DNS, MTU).
9. **en1-Datei** nach HackiOS `hakios.cell.c`: Ethernet-artige Schnittstelle mit eigenem ARP/DHCP-Responder.
   TX über `spes_ipa_tx`, RX über `spes_ipa_rx_hook` (in mbuf kopieren). Darauf achten, aus dem RX-Hook nur
   `spes_ipa_tx` zu rufen (der Hook läuft ohne TX-Lock, das ist so vorgesehen).
10. **Build-Eintrag** `bsd/conf/files`, Patchnummer (nächste: 0207), Host-Test wie bei 0178/0185 für die
    Payload-/Registerkodierung (z. B. Flags von HDR/AGGR/ROUTE/Tabelleninit gegen Linux-Rechenregeln).
11. Teardown/Neustart fehlen ganz: kein STOP/RESET/DE_ALLOC. Ein zweiter Lauf im selben Boot oder ein
    Modem-Neustart wird abgelehnt.

## Offene Fragen und Risiken

1. **IPA-Takt / Bus**: Jeder Registerzugriff ohne laufenden IPA-Kerntakt kann den Bus aufhängen
   (NoC-Timeout → Reset). Vor dem Zugriff wird das RPM-SMD „ipa“ mit 100 MHz gevotet; Ressource, ID und Rate
   sind nicht geprüft. Die msm-bus-Votes aus dem DT (Master 90 → EBI/IMEM, APPSS → IPA-CFG) fehlen ganz.
   **Erster Lauf darum `modem_ipa_data=1 modem_ipa_readonly=1`** und den Wert von SHARED_MEM_SIZE/FLAVOR_0 auf
   Plausibilität prüfen.
2. **IPA-Registerbasis 0x5840000** ist abgeleitet, nicht gemessen. Bei falscher Basis schreibt Schritt 3 an die
   falsche Stelle. Die Lese-Probe zeigt es: FLAVOR_0 sollte TX < 8 und RX ab 8 melden, SHARED_MEM_SIZE eine
   Größe ≥ 0x2000.
3. **Firmware-Ladeort/Reihenfolge**:
   - Lädt TZ bei PAS 15 auf khaje wirklich nach 0x56600000 (HackiOS musste auf SM7325 die Adresse wechseln)?
   - Braucht TZ dafür schon SMMU oder Takt?
   - Der Entwurf lädt nur, wenn GSI noch nicht ENABLED ist; ob das Modem selbst lädt (`modem-init` fehlt im DT
     → AP lädt), ist so angenommen.
4. **Abweichungen von Linux, die das Modem stören könnten**:
   - Kein Checksum-Offload (Linux: CS_OFFLOAD_UL/DL, TX-Header 8 B).
   - Kleinere Ringe.
   - Status von Endpunkt 1 an Modem-Endpunkt 10 übernommen (HackiOS: ohne Status).
   - LAN-Status an, aber die Pakete werden verworfen.
   - Modem-Kanäle werden schon in `spes_ipa_init` alloziert, unabhängig vom Modemzustand.
5. **GENERIC_CMD im Polling**: Latcht `GLOB_IRQ_STTS.GP_INT1`, obwohl der Typ in CNTXT_TYPE_IRQ_MSK
   maskiert ist? Der Entwurf akzeptiert ersatzweise ein Ergebnisfeld ≠ 0.
6. SMEM-Item 497: Größe 0x2000 (Linux v4.2). HackiOS brauchte auf SM7325 0x9000 (DT-Wert); im khaje-DT steht
   kein Wert.
7. Pool: Reicht der Rest des 16-MB-Pools nach WLAN/rmtfs? Schlägt die Allokation fehl, kommt eine Logzeile.
   Der Pool kennt kein Freigeben; jeder Fehlversuch verbraucht Platz.
8. `ml_io_map`-Fenster (IPA 16 KB, GSI 80 KB, SRAM 8 KB, Carveout 64 KB) werden nie freigegeben. Bei einmaligem
   Init ist das unkritisch.
9. Die Poll-Schleife mit 1 ms Schlaf kostet Energie und begrenzt den Durchsatz (Aggregation schließt nach
   500 µs oder 6 KB). Für den ersten Datenpfad reicht das.

## Vorschlag Testreihenfolge (jede Stufe ein eigener Lauf)

1. `modem=1 wifi=1 modem_ipa_data=1 modem_ipa_readonly=1`: Clock-Vote und Lese-Probe.
   Erwartet: kein Hänger, plausible SHARED_MEM_SIZE/FLAVOR_0/HW_PARAM_2, GSI „NOT enabled“.
2. Ohne readonly, Firmware auf dem Root: PAS-Log, `GSI_STATUS enabled`, Kanäle ALLOCATED/STARTED,
   „IPA set up“. Das Modem bleibt dabei offline.
3. QMI INIT_DRIVER/Handshake (neuer SpesModem-Patch) → `spes_ipa_modem_start()`.
4. WDA/DPM/WDS + en1, `modem_ipa_trace=1` für die ersten Pakete.
