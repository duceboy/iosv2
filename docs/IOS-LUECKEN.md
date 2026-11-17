# iOS-Lücken (erzeugt)

Erzeugt am 2026-11-17 von `tools/inventar/gen_luecken.py` aus der lokalen Inventar-Datenbank (iOS 16.7.16 für iPhone X: Kernel, Gerätebaum, dyld-Cache, Programme). Die Datenbank selbst bleibt lokal, weil sie aus Apple-Dateien abgeleitet ist; hier stehen nur Zahlen und eigene Beschreibungen.

## Gesamtzahlen

| Größe | Wert |
|---|---|
| Kernel-Erweiterungen | 223 |
| IOKit-Personalities | 830 |
| Treiberklassen | 2357 |
| Befehlstabellen / Befehle | 250 / 1996 |
| Befehle mit zugeordneter Treiberklasse | 1110 |
| Befehle mit Funktionsname aus dem Userland (Größen geprüft) | 293 |
| Gerätebaum-Knoten (davon mit Treiber) | 259 (160) |
| Hardware-Aufrufstellen im Userland (Cache + Programme) | 21111 |
| launchd-Jobs | 492 |

## Je Funktion

| Funktion | Apple-Treiberklassen | davon mit Befehlen | Befehle | im Port | Stand im Port | Qualcomm-Baustein | Linux-Treiber | Vorlagen |
|---|---|---|---|---|---|---|---|---|
| Akku | 9 | 1 | 3 | 0 | teilweise (lesend, spesbattery=1) | SM5602 Fuel-Gauge @0x71 | drivers/power/supply/syv/sm5602_fuelgauge.c | ios-topaz 0091, iosv2 SweetBattery |
| Anzeige | 42 | 1 | 59 | 4 | läuft (Helligkeit über DCS 0x51 mit Regler/Fades, sweetbacklight=2; Skalierung in Software) | MDSS/DPU sde@5e00000, DSI0 k7_38_0c_0a, backlight über DSI-DCS | techpack/display (sde-kms, dsi-display, sde_rotator) | iosv2 SweetFramebuffer/Backlight |
| Blitz | 4 | 0 | 0 | 0 | fehlt | PM6125 Flash-LED / aw2016 @0x64 (Status-LED) | drivers/leds/leds-qti-flash | keine |
| Bluetooth | 10 | 0 | 0 | 0 | fehlt (bluetoothd startet ständig neu) | WCN3988 BT über UART QUP0 SE3, bt-sw-ctrl GPIO87 | drivers/bluetooth/btqca, msm_bt_power | HackiOS drivers/bt (Protokoll), Linux btqca |
| Grafik | 139 | 4 | 213 | 2 | teilweise (Oberfläche GL ES über Mesa/EAGL; Metal über NegroniMetal/metal2vulkan/Turnip für Apps, 2026-11-17) | Adreno 610 kgsl-3d0@5900000 | drivers/gpu/msm (kgsl) | iosv2 0156–0168 NegroniMetal, ios-flame Turnip/m2v, HackiOS hakios-metal |
| Haptik | 16 | 3 | 8 | 0 | teilweise (0199 /dev/redwood-haptic + HAL-Plug-in Actuator, Test offen) | PM6125 LPG SID1 0xb300 + GPIO36 (lct-pwm-vibrator) | drivers/pwm/pwm-qti-lpg.c, drivers/leds/leds-qpnp-vibrator-pwm.c (lct-pwm-vibrator) | HackiOS drivers/haptic + audio_plugin Actuator |
| Kamera | 41 | 5 | 118 | 1 | fehlt | CAMSS: CPAS, CSID, CSIPHY, CCI0; S5KJN1 50 MP, ISP (IFE) | techpack/camera-bengal (cam_cpas, cam_isp, cam_sensor_module, cam_ope) | HackiOS hakios.camera.c |
| Laden | 56 | 1 | 36 | 0 | ABL-Einstellung (448 mA), keine eigene Steuerung (Freigabe nötig) | bq2589x/SYV690 @0x6a, sc8551 @0x66, rt1711h Typ-C @0x4e | drivers/power/supply/syv (bq2589x), cp_manager (sc8551) | ios-topaz 0148 |
| Mikrofon | 46 | 3 | 14 | 0 | fehlt | WCD937x TX + VA-Makro | techpack/audio | HackiOS drivers/mic |
| Mobilfunk | 61 | 3 | 105 | 0 | teilweise (Modem bootet, QRTR/QMI-Client vorhanden; fehlt: NAS/WDS/DPM/WDA + IPA-4.2-Datenweg, Vorlage HackiOS hakios.ipa.c (4.11) + Linux ipa_data-v4.2) | MPSS (modem_b), QMI über SMD/GLINK, rmtfs | drivers/soc/qcom (qmi, glink, rmtfs), net/qrtr | HackiOS drivers/modem, docs/cellular.md, iosv2 SpesModem |
| Ortung | 6 | 2 | 13 | 0 | fehlt | GNSS im MPSS (LOC QMI) | Modem-Firmware + QMI LOC | keine (Simulations-Schnittstelle von locationd prüfen) |
| Schlaf | 35 | 0 | 0 | 0 | fehlt (kein Schlaf, Display bleibt an) | RPMh/PSCI cpu-idle, AOSS | drivers/soc/qcom, cpuidle | iosv2 SweetCPU |
| Sensoren | 99 | 10 | 48 | 0 | fehlt | SSC/ADSP Sensoren (BMI160/ICM, AK09918, ALS/Prox stk3x1x) – sensors über ADSP-SSC | kein Linux-Treiber: Sensoren laufen im ADSP-SSC (Live-DTB ohne I2C-Sensor), Zugriff über QMI/sensors.ssc; Konfiguration research/spesn-vendor | keine |
| Speicher | 53 | 2 | 26 | 2 | läuft (UFS, HFSX-Root) | UFS @4804000 | drivers/scsi/ufs | iosv2 sweet_ufs |
| Tasten | 8 | 0 | 0 | 0 | teilweise (SweetHIDButtons) | PM6125 PON (Power, Leiser), GPIO Lauter | drivers/input/misc/qpnp-power-on | iosv2 |
| Thermik | 62 | 3 | 30 | 0 | fehlt (nur Akku-Temperatur geloggt) | TSENS @4410000, PM6125 ADC (xo/pa therm) | drivers/thermal/qcom (tsens24xx), spmi-temp-alarm, iio/adc | keine |
| Ton | 91 | 3 | 15 | 0 | fehlt (ADSP-Boot Stufe 1 SpesAudio, Verstärker-Init; HAL-Plug-in RedwoodAudio installiert, /dev/redwood-audio fehlt) | ADSP (APR/GPR), WCD937x über SoundWire, Bolero rx/tx/va, aw87559 Verstärker @0x58/0x5b | techpack/audio (asoc, codecs/wcd937x, codecs/aw87xxx) | HackiOS audio_plugin.c, iosv2 spes_amp.c |
| Touch | 42 | 3 | 11 | 0 | läuft (gelegentlich verlorene Abheben-Ereignisse?) | FocalTech ft3518 @I2C1 0x38, IRQ GPIO80, Reset GPIO86 | drivers/input/touchscreen/focaltech_touch | iosv2 sweet_touch.c |
| USB | 237 | 6 | 130 | 1 | teilweise (Gerätemodus CDC-ECM für Diagnose, kein Apple-USB-Stack) | DWC3 @4e00000, HS-PHY 1613000 | drivers/usb/dwc3 | iosv2 0183, sweet 0072–0077 |
| Uhrzeit | 10 | 0 | 0 | 0 | teilweise (Zeit über Netz/NTP?) | PM6125 RTC (SPMI) | drivers/rtc/rtc-pm8xxx | keine |
| Video | 9 | 3 | 19 | 0 | fehlt (Software-Decoder, H264SW-Absturz bei 420v) | Venus vidc@5a00000 | techpack/video (msm_vidc) | keine |
| WLAN | 189 | 2 | 9 | 1 | läuft (Auto-Join, DHCP, Safari) | WCN3988 über WCNSS/ath10k-snoc, wlan@c800000 | drivers/net/wireless/cnss2 + ath, icnss | iosv2 RedwoodWLAN |

Hinweise: „Apple-Treiberklassen“ ist eine Namens-Zuordnung (Muster je Funktion), „Befehle“ stammen aus den Befehlstabellen im Kernel (Code). „im Port“ = gleichnamige Klasse im iosv2-Kernel. Details (Klassen, Befehle mit Namen, Gerätebaum-Knoten, aufrufende Daemons) im lokalen Bericht `research/inventar/FUNKTIONEN.md`.
