# spes_therm – Temperaturen (TSENS, PM6125-ADC) und Uhr (PM6125-RTC), nur lesend

Entwurf vom 18.11.2026. **Nicht im echten Kernel gebaut, nicht auf dem Telefon gelaufen.**
Geprüft ist nur: `spes_therm.c` übersetzt mit `clang -fsyntax-only -Wall -Wextra -Wshadow -Wconversion
-Wmissing-prototypes` gegen Stub-Header (nicht gegen den XNU-Baum), und `test_spes_therm.py` läuft grün
(Rechen-/Listen-Logik aus `spes_therm.h`, 1 Test mit gut 100 Einzelprüfungen inkl. Gegenproben).

Dateien: `spes_therm.c`, `spes_therm.h` (ohne Kernel-Header, Host-testbar wie `spes_lpg.h`), `test_spes_therm.py`.

## Abweichungen vom Auftrag, die man kennen muss

1. **TSENS-Adresse:** Der Live-DT-Knoten heißt `tsens@c222000`, sein `reg` ist aber `<0x4410000 0x8>` (SROT) und
   `<0x4411000 0x1ff>` (TM). Der Code nimmt `reg` (0x4410000/0x4411000); der Knotenname ist ein Überbleibsel.
2. **Kein Akku-Thermistor am PM6125-ADC:** `vadc@3100` hat im Live-DT genau 11 Kanäle (ref_gnd, vref_1p25, die_temp,
   vph_pwr, vcoin, xo_therm 0x4c, pa_therm0 0x4d, quiet_therm 0x4e, camera_flash_therm 0x52, emmc_ufs_therm 0x53,
   rf_pa1_therm 0x55). Kein `bat_therm` (0x4a) und kein `bat_id` (0x4b). Die Akkutemperatur kommt weiter nur vom SM5602.
3. **Stufe 2 schaltet nichts:** Für TSENS, RTC und ADC gibt es keine Versorgung, keinen Reset und keinen Takt, den der
   Treiber ein- und wieder ausschalten müsste. Stufe 2 ist deshalb ein zusätzlicher Nur-Lese-Dump des ADC-Blocks.
4. Zusätzlich gelesen (roh, eine Zeile): PM6125-Temperaturalarm `qcom,temp-alarm@2400` (Status/Schwelle).

## Stufen (`spestherm=N`, ohne Boot-Arg passiert nichts)

| N | Inhalt | Schreibt? |
|---|---|---|
| 1 | TSENS (16 Sensoren, m°C), RTC-Sekundenzähler, PMIC-Temperaturalarm; Kennzeilen einmal, dann **eine Zeile alle 30 s** | nein |
| 2 | wie 1 + einmaliger Dump ADC 0x3100 (Kennung, Status, 0x3142–0x3147, letztes Ergebnis) + APID/Eigentümer aus der Arbiter-Tabelle | nein |
| 3 | wie 2 + **eine** Runde Wandlungen aller 11 Kanäle | ja: SID 0, 0x3142–0x3147 (noch nicht freigegeben, siehe unten) |
| 4 | wie 3 + die_temp und die sechs Thermistoren in jeder 30-s-Runde | wie 3 |

Zweites Boot-Arg (optional): `spesrtcoff=<Sekunden>` = UTC-Sekunden beim RTC-Zählerstand 0 (siehe „Uhr“).
Beide zusammen ca. 35 Bytes der 600-Byte-Grenze.

## Einbau

1. `bsd/conf/files`, bei den anderen spes-Zeilen (hinter `bsd/dev/spes_usb.c		standard`):

   ```
   bsd/dev/spes_therm.c		standard
   ```

   `spes_therm.c` und `spes_therm.h` nach `bsd/dev/`.

2. Aufrufstelle `bsd/dev/sweet_ufs.c`:
   - bei den Externs (Zeile ~65, hinter `spes_usb_probe`): `extern void spes_therm_init(void);   /* bsd/dev/spes_therm.c (spestherm=N) */`
   - im spes-Zweig am Ende von `sweet_ufs_init()` (Zeile ~822, hinter `spes_usb_probe();`): `spes_therm_init();`
   - im Log-Modus-Zweig (Zeile ~1011, hinter `spes_usb_probe();`): `spes_therm_init();`
     (damit Stufe 1 auch in Diagnose-Images mit `spesufslog=1` läuft).

   `spes_therm_init()` startet nur einen Kernel-Thread und kehrt sofort zurück; alles Weitere läuft dort.

3. **`bsd/dev/sweet_spmi.c` – Leseliste erweitern (nötig schon für Stufe 1, sonst bleibt die RTC „not readable“).**
   `sweet_spmi_read()` lässt heute nur Akku-Blöcke, LPG und vier PON-Register durch. Ergänzen:

   ```c
   #include "spes_therm.h"                /* oben bei spes_lpg.h */
   ...
   bool therm = spes_therm_spmi_read_allowed(sid, addr);          /* RTC 0x6046/0x6048-b, TZ 0x2405/08/40, ADC 0x31xx */
   if (!sp_ready || !out || addr > 0xffffu || (!battery && !lpg && !pon && !therm)) {
   ```

   Das sind Beobachter-Lesezugriffe (EXT_READL), wie bisher. Genaue Liste: `spes_therm_spmi_read_allowed()` in
   `spes_therm.h`, im Host-Test mit Nachbaradressen und Gegenproben abgedeckt.

4. **Erst nach Freigabe (Stufe 3/4): Schreibliste in `sweet_spmi_write()`**

   ```c
   if (!spes_spmi_write_allowed(sid, addr, 1) && !spes_lpg_write_allowed(sid, addr, 1) &&
       !spes_therm_adc_write_allowed(sid, addr, 1)) {
   ```

   Ohne diese Zeile verweigert `sweet_spmi_write()` den ersten ADC-Schreibzugriff; der Treiber meldet das einmal,
   prüft, dass 0x3142–0x3146 unverändert sind, und versucht es in diesem Boot nicht wieder. Stufe 3/4 ist dann
   gefahrlos, aber nutzlos.

5. Externs, die `spes_therm.c` braucht (alle im Baum vorhanden): `ml_io_map`, `sweet_spmi_init`/`sweet_spmi_read`
   (`sweet_spmi.h`), `sweet_spmi_write` (sweet_spmi.c, 0186), `SecureDTLookupEntry`, `PE_parse_boot_argn`,
   `kernel_thread_start`, `assert_wait_deadline`/`thread_block`, `clock_interval_to_deadline`,
   `absolutetime_to_nanoseconds`/`mach_absolute_time`, `delay`, `snprintf`.

6. Host-Test nach `iosv2/tests/test_spes_therm.py`; `HEADER` dann wie in `test_spes_spmi_allow.py` per
   `new_file_from_patch(PATCH, 'bsd/dev/spes_therm.h')` aus dem Patch holen.

## Freigabeliste: was für eine ADC-Wandlung zusätzlich erlaubt werden müsste

Vorlage: Linux `drivers/iio/adc/qcom-spmi-adc5.c` (xiaomi-spes-devs, lineage-24.0), `adc_configure()` und
`adc_update_dig_param()`; Kanal-Eigenschaften aus `adc_get_dt_channel_data()` + Live-DT `vadc@3100`;
Warten `adc_poll_wait_eoc()`; Ergebnis `adc_read_voltage_data()`.
PM6125 **SID 0**, Block 0x3100, je **1 Byte** pro Zugriff:

| Register | Name (Linux) | Was geschrieben wird | Fundstelle |
|---|---|---|---|
| 0x3142 | ADC_USR_DIG_PARAM | nur Bits 6:2 (Maske 0x7c): **0x18** für Thermistoren (Timer-Kal. 0, ratiometrisch 1<<4, Dezimation 2<<2) bzw. **0x28** für ref_gnd/vref/die/vph/vcoin (absolut 2<<4); Bits 7, 1, 0 bleiben | `adc_update_dig_param()`; `ADC_DECIMATION_DEFAULT 2`, `ADC_RATIOMETRIC_CAL 1`, `ADC_ABSOLUTE_CAL 2`, `ADC_TIMER_CAL 0` |
| 0x3143 | ADC_USR_FAST_AVG_CTL | Bits 2:0 → 0 (1 Messwert); Rest bleibt | `adc_configure()`, `VADC_DEF_AVG_SAMPLES 0` |
| 0x3144 | ADC_USR_CH_SEL_CTL | genau einer von 0x00, 0x01, 0x06, 0x83, 0x85, 0x4c, 0x4d, 0x4e, 0x52, 0x53, 0x55 | `adc_configure()`; Live-DT `reg` der Kanal-Knoten |
| 0x3145 | ADC_USR_DELAY_CTL | Bits 3:0 → **2** (200 µs, Thermistoren: `qcom,hw-settle-time = <0xc8>`, Tabelle `data_pmic5.hw_settle` Index 2) bzw. **0** (15 µs, Standard); Rest bleibt | `adc_configure()`, `adc_hw_settle_time_from_dt()` |
| 0x3146 | ADC_USR_EN_CTL1 | Bit 7 setzen (`ADC_USR_EN_CTL1_ADC_EN`); Rest bleibt | `adc_configure()` |
| 0x3147 | ADC_USR_CONV_REQ | **0x80** (`ADC_USR_CONV_REQ_REQ`), Auslöser | `adc_configure()` |
| 0x3146…0x3142 | – | Wiederherstellen der vorher gelesenen Ausgangswerte (in dieser Reihenfolge, nur wenn abweichend) | Vorgabe des Projekts (Linux lässt die Werte stehen) |

Je Wandlung also 6 Schreibzugriffe + bis zu 5 zum Wiederherstellen; Stufe 3: 11 Wandlungen einmal; Stufe 4: 7 Wandlungen
alle 30 s. Zwei Sperren im Code vor jedem Byte: `spes_therm_adc_write_allowed(sid, addr, len)` (Adresse) und
`spes_therm_adc_value_ok(addr, wert, ausgangswert, kanal)` (Wert = Sollwert laut Tabelle oder Ausgangswert), beide im
Host-Test mit Gegenproben. 0x3142–0x3146 werden nach jedem Schreiben zurückgelesen.

**Ausnahme vom „jedes Byte zurücklesen“:** 0x3147 ist ein Auslöser; ob er angenommen wurde, zeigt nur STATUS1 0x3108
(Bit 1 REQ_STS während der Wandlung, danach Bit 0 EOC). Das muss die Freigabe ausdrücklich mit abdecken.

Nicht nötig und nicht vorgesehen: ADC_TM 0x3400/0x3500 (Schwellen-Überwachung), RTC-Register, Temperaturalarm 0x24xx.
Voraussetzung laut Projektregel „Lese-Lauf vorher“: Stufe 2 muss gelaufen sein und zeigen, dass die APID von 0x31 dem
Apps-EE 0 gehört und STATUS1 kein laufendes REQ_STS meldet.

## Testplan

Alle Läufe als Zusatz zu einem normalen iOS-Image (`tools-local/ios-run.sh RUN SUF "spestherm=N"`), Auswertung im Live-Log.

**Stufe 1** (`spestherm=1`). Erwartet, einmal:

```
SPES THERM: stage 1 (1 tsens+rtc, 2 +adc dump, 3 +adc round, 4 +adc every 30 s)
SPES THERM: TSENS srot 0x4410000 tm 0x4411000: ctrl 0x… (enabled) sensor-mask 0xffff trdy 0x… (first round done)
SPES THERM: tsens order: 0 mapss 1 cdsp-hvx 2 wlan 3 camera 4 video 5 mdm-1 6 cpu-1-0 … 15 gpu
SPES THERM: RTC ctrl 0x6046 = 0x80 (running) counter N s = D d hh:mm:ss since RTC start; spesrtcoff 0 -> utc 0 (no plausible offset; system time not offered)
SPES THERM: PMIC temp-alarm 0x2400: subtype 0x9 (gen2, …) status 0x… shutdown_ctrl1 0x… (threshold 1)
```

danach alle 30 s:

```
SPES THERM: up 95s tsens mC 34500 33900 … (16 Werte) max 41200 (cpu-1-2) | rtc N ctrl 0x80 | pmic-alarm status 0x…
```

Bestanden, wenn: alle 16 Werte zwischen ca. 20 000 und 70 000 liegen und zum Akkuwert (SM5602, ~30–34 °C) passen; die
CPU-Sensoren unter Last steigen (App öffnen) und danach fallen; `rtc N` zwischen zwei Zeilen um 30 ± 1 wächst; über einen
Neustart hinweg weiterläuft (nicht bei 0 beginnt). Sensor-Maske ≠ 0xffff ist kein Fehler (dann „-“ an der Stelle), aber
notieren. **Abbruch/Meldung:** „OFF“, „NOT ready“, „RTC not readable“, „STOPPED“, Panic beim ersten TSENS-Zugriff.

**Stufe 2** (`spestherm=2`). Zusätzlich einmal:

```
SPES THERM: ADC 0x3100: rev2 0x… type 0x… subtype 0x… status1 0x… | dig 0x… avg 0x… ch 0x… delay 0x… en 0x… req 0x… | data 0x…
SPES THERM: ADC: ppid 0x31 -> APID n owner EE 0 (apps: writes possible once allow-listed)
```

Die Werte dig/avg/ch/delay/en sind die **Ausgangswerte**, die Stufe 3 wiederherstellen muss – in NOTES.md festhalten.

**Stufe 3** (`spestherm=3`), erst nach Freigabe und Schritt 4 des Einbaus. Erwartet einmal:

```
SPES THERM: adc [mC; uV for ref_gnd/vref/vph/vcoin] ref_gnd=0(0x…) vref_1p25=1250000(0x…) die=3xxxx(0x…) vph_pwr=3900000(0x…) vcoin=…(0x…) xo=3xxxx(0x…) pa0=… quiet=… cam_flash=… ufs=… pa1=…
```

Bestanden, wenn: ref_gnd nahe 0 µV, vref_1p25 = 1 250 000 ± 15 000 µV (das ist die eingebaute Skalen-Probe), vph_pwr
innerhalb ±50 mV der SM5602-Akkuspannung, Thermistoren 20–60 °C und nahe am Akkuwert, und ein zweiter Stufe-2-Lauf
dieselben Ausgangswerte in 0x3142–0x3146 zeigt wie vorher. Ohne Freigabe erwartet (und harmlos):
`SWEET SPMI: write sid=0 addr=0x3142 refused (not allow-listed)` + `SPES THERM: ADC: write refused or failed, starting
values confirmed/restored: no further conversions this boot`.

**Stufe 4** (`spestherm=4`): zusätzlich alle 30 s die `adc …`-Zeile mit die + 6 Thermistoren. 10 Minuten laufen lassen,
auf `ADC: busy`, `no end of conversion` oder `RESTORE … INCOMPLETE` achten (jedes davon = stoppen, Log sichern).

**Host:** `cd iosv2/research/drafts/therm && python3 -m unittest test_spes_therm.py`.

## Uhr: wie XNU die Zeit aus der RTC setzen könnte

Befund im Baum (`work/xnu`):
- `bsd_init()` → `IOKitInitializeTime()` (iokit/Kernel/IOStartIOKit.cpp) wartet **bis zu 30 s** auf die Ressource `IORTC`
  und ruft dann `clock_initialize_calendar()` → `PEGetUTCTimeOfDay()` → `gIOPlatform->getUTCTimeOfDay()` →
  `IOPlatformExpert::getGMTTimeOfDay()`, das **0 zurückgibt**. `SweetPlatformExpert` überschreibt es nicht, und niemand
  im Baum veröffentlicht `IORTC` (grep). Daher 1970 (in der Zeitzone des Geräts 1969). Ob der Boot heute wirklich
  30 s an dieser Stelle steht, ist ein offener Prüfpunkt (unten).
- Die PM6125-RTC ist ein freilaufender 32-Bit-Sekundenzähler seit dem letzten RTC-Stromverlust, **keine Uhrzeit**.
  Linux beschreibt sie auf diesem Gerät nicht: `rtc-pm8xxx.c pm8xxx_rtc_set_time()` kehrt ohne `allow-set-time` sofort
  zurück, und der Live-DT-Knoten `qcom,pm6125_rtc` hat diese Eigenschaft nicht. UTC = Zähler + Offset; der Offset muss
  außerhalb der RTC liegen.
- **Woher Android den Offset nimmt:** Auf Qualcomm-Geräten üblicherweise der `time_daemon` (QTI time-services), der
  die Differenz in `/data/vendor/time/ats_*` ablegt und beim Start `Zähler + Offset` als Systemzeit setzt; manche
  Custom-ROMs nutzen stattdessen „timekeep“ mit einer persist-Property. **Für Evolution X auf diesem Gerät nicht
  belegt:** In `research/spesn-vendor/` liegen weder `/vendor/bin` noch init-Skripte, und im gesicherten pstore-Log
  steht nichts zu rtc/time_daemon. Da der Offset in userdata lag und userdata jetzt das iOS-Root ist, ist er ohnehin
  weg und muss neu bestimmt werden.

Angebot des Treibers: `spes_therm_rtc_read(&secs, &ctrl)` (nur lesen, initialisiert SPMI selbst, also auch vor
`spes_therm_init()` aufrufbar) und `spes_therm_utc_offer(&utc)` (= Zähler + `spesrtcoff`, nur wenn RTC läuft und das
Ergebnis zwischen 2020 und 2100 liegt). Der Treiber **stellt die Systemzeit nicht selbst**.

Vorschlag für den Anschluss (eigener kleiner Patch, nicht Teil dieses Entwurfs):
1. `SweetPlatformExpert` (iokit/Kernel/arm/SweetPlatformExpert.cpp): `long getGMTTimeOfDay() override` →
   `uint64_t utc; return spes_therm_utc_offer(&utc) == 0 ? (long)utc : 0;` und in `start()`
   `publishResource("IORTC")`, damit `IOKitInitializeTime()` nicht wartet. Voraussetzung: Leseliste (Einbau 3).
2. Offset bestimmen: einmal mit `spestherm=1` booten, die Zeile `RTC … counter N` im Live-Log zur Mac-Zeit T lesen,
   `spesrtcoff = T − N` (auf wenige Sekunden genau; `tools-local/spes-live.py` könnte das ausrechnen). `ios-run.sh`
   hängt `spesrtcoff=…` an jedes Image. Der Wert bleibt gültig, solange die RTC nicht stehen bleibt (Zähler in Stufe 1
   über Neustarts beobachten).
3. Später besser: `setUTCTimeOfDay()` im Platform Expert abfangen (wird über `clock_set_calendar_microtime()` gerufen,
   wenn `timed` die Zeit per NTP/Mobilfunk stellt), dort `Offset = UTC − Zähler` berechnen und über einen
   Userland-Helfer in eine Datei auf dem Root schreiben; beim Boot liest ein launchd-Job sie und ruft
   `settimeofday()`. Dafür fehlt noch ein Weg, den Zähler ins Userland zu geben (sysctl oder Befehl im
   USB-Befehlsserver) – nicht gebaut.

## Lauter-Taste (nur Befund)

- Live-DT `gpio_keys/vol_up`: `gpios = <&pm6125_gpios 5 1>` (PM6125 **GPIO5**, aktiv low), `linux,code = 0x73`
  (KEY_VOLUMEUP), Entprellung 15 ms, Pin-Konfiguration `key_vol_up_default`: Eingang, Pull-up, `power-source 0`.
  Also **kein TLMM-GPIO**, sondern PMIC-GPIO: SID 0, Block 0xc400 (0xc000 + 4·0x100).
  Leiser = PON RESIN (`qcom,pon_2`, `linux,code 0x72`), Power = PON KPDPWR (`qcom,pon_1`, 0x74), beide Block 0x800.
- `bsd/dev/sweet_keys.c` deckt das ab: liest über eigene Beobachter-Kanäle PON 0x810 (Bit 0 Power, Bit 1 Leiser) und
  GPIO5 0xc410 (Bit 0, low = gedrückt), prüft vorher 0xc440/0xc446/0xc405 (Eingang, freigeschaltet) und meldet Index 1 →
  `sweet_hid_key()` → `kHIDUsage_Csmr_VolumeIncrement` (SweetHID.cpp). Abfrage alle 20 ms, schreibt nichts.
- Auf spes nur mit **`sweetkeys=1`** (sweet_ufs.c, spes-Zweig). `tools/build-spes-ios-graphics.sh` (von `ios-run.sh`
  benutzt) setzt `sweetkeys=1`; `build-spes-ios.sh` und `build-spes-ios-optimized.sh` setzen `sweetkeys=0`.
- Beleg auf diesem Gerät: `research/logs/vib-vib-1.txt`:
  `SWEET KEYS: arb=0x50010000 apids=256 pon-apid=143 gpio4-apid=153 pon=0x4/1 gpio=0x1/1 mode=0/1 en=0x80/1 subtype=0x10/1`
  und zwei Ereignisse `key=1 down=1 … gpio4:c110=0` / `key=1 down=0 … =0x1`. Die Taste wird also gelesen.
  Nur Schönheitsfehler: der Logtext sagt „gpio4:c110“ (sweet-Bezeichnung), gemeint ist GPIO5 0xc410.
- Nicht belegt: ob iOS darauf die Lautstärke ändert (im Log steht nur das Kernel-Ereignis) – am Gerät ansehen.

## iOS-Seite (iPhone X, aus `research/inventar/x11.db` und FUNKTIONEN.md; nur Namen/Nummern/Größen)

**Temperatur.** Gerätebaum des iPhone X und zugehörige Klassen (Kext AppleEmbeddedTempSensor, wenn nicht anders genannt):
`arm-io/tempsensor0…6` (`tempsensor,t8015`) → `AppleT8015TempSensor`; `arm-io/dietempctl0` (`dietempctl,t8015`) →
`AppleDieTempController`; `arm-io/vtempctl0` (`vtempctl,t8015`) → `AppleVTempDispatcher`; `arm-io/smctempsensor0`
(`smc-tempsensor`) → `AppleSMCSensorDispatcher` (Kext AppleSMC); `ApplePMPThermal` auf `RTBuddyEndpointService`
(Kext ApplePMP); PMU-Temperaturen über `AppleD2422PMU`/`AppleARMPMUTempSensor`.
`thermalmonitord` (launchd `com.apple.thermalmonitord`) sucht per `IOServiceMatching`: `AppleDieTempController`,
`AppleSMCSensorDispatcher`, `ApplePMPThermal`, `ApplePPM`, `AGXAccelerator`, `AppleHIDKeyboardEventDriverV2`.
User-Client-Tabellen im Kernel (Selektor: Skalare ein / Struktur ein / Skalare aus / Struktur aus):
- `AppleDieTempControllerUserClient`: 0: 2/0/0/0, 1: 1/0/1/0, 2: 2/0/0/0, 3: 1/0/1/0, 4: 1/0/0/0, 5: 0/0/1/0
- `AppleSMCSensorDispatcherUserClient`: 0: 0/0/1/0, 1: 0/0/0/60, 2: 0/0/0/60, 3: 0/88/0/0, 4–6: 0/0/1/0
- `ApplePMPThermalUserClient`: 0: 1/0/0/0, 1: 0/0/1/0
Welche Selektoren `thermalmonitord` davon wirklich ruft, ist in der DB **nicht eindeutig** (die Aufrufstellen sind
allen Klassen zugeordnet, Spalte `match` teils „mismatch“); sicher ist nur ein Struktur-Eingang von 88 Bytes
(passt zu Selektor 3 des SMC-Dispatchers).
Nicht in der DB belegt, aber vermutlich der Hauptweg (offener Prüfpunkt): Die Einzelwerte liest `thermalmonitord`
als HID-Temperaturereignisse von Diensten der Apple-Vendor-Usage-Page (Temperatursensor), nicht über obige
User-Clients; die User-Clients dienen eher der Steuerung (Die-Temp-Regelung, Schwellen).

Was fehlt und zu bauen wäre:
1. Kernel: ein kleiner IOKit-Dienst (C++, `iokit/Kernel/arm/`, neben SweetHID.cpp), der `spes_therm_tsens_read()` /
   `spes_therm_tsens_max()` und die Akkutemperatur als die Schnittstelle anbietet, die `thermalmonitord` tatsächlich
   liest. Zuerst klären, welche das ist: `thermalmonitord` im laufenden iOS beobachten (Log, `ioreg` über SSH), welche
   Dienste er öffnet und was er vermisst. Erst dann Klasse wählen (HID-Temperaturdienst vs. Attrappe
   `AppleSMCSensorDispatcher` mit Selektor 0–3).
2. Ohne das greift keine iOS-Drosselung: `thermalmonitord` kennt keine Temperatur, CLTM/Helligkeits-Absenkung
   (`thermal-mitigation`, von BrightnessControl gelesen) bleiben aus. Als Zwischenlösung reicht ein Kernel-Schutz im
   Treiber selbst (z. B. bei `spes_therm_tsens_max()` > 85 °C über `spes_cpufreq` drosseln) – nicht Teil dieses
   Entwurfs, weil es nicht mehr „nur lesen“ wäre.
3. HackiOS hat dafür **keine Vorlage** (`drivers/` enthält battery, haptic, mic, camera, modem, bt; IOS-LUECKEN.md:
   Thermik „Vorlagen: keine“).

**Uhr.** iPhone X: `arm-io/spmi/spmi-pmu` (`pmu,d2422`) → `AppleD2422PMU` mit Personality `PMURTC` →
`AppleD2422PMURTC` (Basisklasse im Kext `AppleDialogSPMIPMURTC`); dazu `AppleARMRTC` (AppleARMPlatform). Diese Klassen
veröffentlichen die Ressource `IORTC` und bedienen `getGMTTimeOfDay`/`setGMTTimeOfDay` des Platform Expert; im
Port gibt es keine davon. Userland: `timed` (launchd `com.apple.timed`) stellt die Zeit aus NTP/Mobilfunk/GPS über
`settimeofday` und liest `kern.monotonicclock_usecs`, `kern.monotonicclock_rate_usecs`, `kern.monotoniclock_offset_usecs`
(in XNU nur mit einer „monotonic clock“ der Plattform vorhanden; fehlt sie, rechnet `clock_initialize_calendar()` mit
der UTC-Zeit allein). Viele Dienste lesen `kern.boottime` (CommCenter, CloudDocs, …) – mit 1970 als Startzeit sind
Zertifikatsprüfungen (TLS) und Zeitstempel falsch, bis `timed` gestellt hat. `IOPMrootDomain` braucht die RTC
für Weck-Alarme (Schlaf); ohne Schlaf-Unterstützung im Port derzeit ohne Belang, und die Alarmregister 0x61xx bleiben
unangetastet.
Zu bauen: der Platform-Expert-Anschluss aus dem Abschnitt „Uhr“ (Kernel, ~20 Zeilen) und der Offset-Weg; kein
Userland-Plug-in nötig. Vorlage: ios-flame 0099 `flame-rtc` (laut ROADMAP Nachtrag 1; liegt nicht in `research-src/`,
nicht gelesen).

## Offene Prüfpunkte

1. **TSENS unter XNU lesbar?** Linux liest SROT+4 und TM+0xa0… vom HLOS; ob der Zugriff aus XNU ohne Abort klappt und
   `TRDY` Bit 3 nach dem ABL gesetzt ist, zeigt erst Stufe 1 (erste Zeile). Ist TRDY nicht gesetzt, hält der Treiber die
   Werte zurück; Linux würde dann per SCM (`tsens-reinit-wa`, SVC TSENS, ID 5) die TrustZone neu initialisieren lassen –
   das ist bewusst **nicht** eingebaut.
2. **SPMI-Zuordnung:** Gibt es APIDs für PPID 0x060 (RTC), 0x024 (Temperaturalarm), 0x031 (ADC), und gehört 0x031 dem
   Apps-EE 0? Stufe 1 (RTC/Alarm lesbar) und Stufe 2 (`ADC: ppid 0x31 -> APID … owner EE …`). Ein Lese-Timeout sperrt
   die betroffene APID in `sweet_spmi.c` für den Rest des Boots (dort so vorgesehen).
3. **RTC läuft und behält den Stand?** `ctrl` Bit 7 und Zähler über Neustart, Fastboot und OrangeFox hinweg. Bleibt sie
   bei leerem Akku stehen, ist `spesrtcoff` danach falsch – deshalb die Plausibilitätsgrenze 2020–2100.
4. **Wartet der Boot 30 s auf `IORTC`?** Im vorhandenen Log die Zeit um „calling IOKitInitializeTime“ ansehen; wenn ja,
   spart `publishResource("IORTC")` 30 s Bootzeit.
5. **ADC-Ausgangszustand:** EN_CTL1 nach dem ABL an oder aus? Liefert die Wandlung, wenn der Treiber EN danach wieder
   auf den Ausgangswert (evtl. aus) setzt, beim nächsten Mal sauber? Reicht Abfragen ohne EOC-Interrupt (Linux:
   40 × 10 ms)? Stufe 2 zeigt den Zustand, Stufe 3 die Antwort.
6. **Umrechnung gegenprüfen:** OrangeFox (`fastboot boot recovery.img`, nur RAM) hat die Linux-Thermalzonen:
   `/sys/class/thermal/thermal_zone*/{type,temp}` einmal mitschreiben (mapss-usr … gpu-usr, xo-therm-usr, pa-therm0-usr,
   quiet-therm-usr, pm6125-tz) und mit Stufe 1/3 kurz danach vergleichen. Erwartung: gleiche Größenordnung, nicht
   identisch (anderer Lastzustand).
7. **Sensor-Namen:** Reihenfolge 0–15 stammt aus den `*-usr`-Zonen des Live-DT; ob `cpu-1-*` wirklich die großen Kerne
   sind, zeigt ein Lasttest (cpus=4 vs. Last auf einem Kern).
8. **Temperaturalarm-Deutung:** nur roh geloggt; Subtyp (gen1/gen2) entscheidet, welche Statusbits die Stufe sind.
9. **Android-Offsetquelle** (time_daemon/ats-Datei) ist allgemeines Qualcomm-Wissen, am Gerät nicht belegt (siehe „Uhr“).
10. **thermalmonitord-Schnittstelle** (HID-Ereignisse vs. User-Client) ist nicht belegt; erst beobachten, dann bauen.
