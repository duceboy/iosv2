# Offene Treiber – Übergabe an einen zweiten Durchgang (Fable)

Hier stehen Treiber, die in diesem Durchgang mehrfach gescheitert sind oder zu groß für einen Lauf waren, mit dem was
versucht wurde und woran es hing. Regel (Nutzer, 17.11.2026): nach wiederholtem Fehlschlag hier eintragen, überspringen,
mit dem nächsten weitermachen. Quellenlage je Funktion: docs/IOS-LUECKEN.md (erzeugt aus tools/inventar).

| Funktion | Stand | Versuche / woran es hängt | Vorlagen | Nächster Schritt |
|---|---|---|---|---|
| Mobilfunk-Daten | Modem bootet, QRTR/QMI-Client (SpesModem), NAS/UIM/DMS-Sonde 0200–0202 | SIM erst „absent“ (zu frühe Abfrage) → 0202 | HackiOS hakios.mpss/nas/qmi/ipa/cell.c (IPA 4.11), Linux upstream drivers/net/ipa ipa_data-v4.2.c (SC7180, gleiche IPA-Version 0x10) | WDS/DPM/WDA + IPA-4.2-GSI-Kanäle, en1 mit DHCP-Antwort wie HackiOS. Vorarbeit: Linux v6.12 drivers/net/ipa lokal in research-src/linux-ipa (v4.2: AP-Endpunkte cmd 6/ch1, LAN-RX 8/ch2, Modem-TX 1/ch0, Modem-RX 9/ch3); IPA-Firmware scuba_ipa_fws.* / ipa_fws.* in research/spesn-vendor/vendor/firmware (nicht in modem_b → aus dem iOS-Dateisystem laden oder in den Pool kopieren); HackiOS-Datenweg 874 Zeilen (hakios.ipa.c) |
| Mobilfunk-Menü in Einstellungen | fehlt | CommCenter läuft nicht (kein Baseband-Treiber, kein ARI) | keine | Statusleiste/Einstellungen erst nach Daten; ggf. SpringBoard-Hook wie HackiOS inject_sb.c |
| Bluetooth | fehlt | bluetoothd aus launchd genommen (Neustart-Schleife) | Linux btqca.c, HackiOS drivers/bt | UART QUP0 SE3 + WCN3988-BT-Firmware (crbtfw/crnv aus bluetooth_b) + /dev/cu.bluetooth-Shim |
| Kamera | fehlt | — | HackiOS hakios.camera.c, Linux techpack/camera-bengal | CCI + S5KJN1-Init, CSIPHY/CSID/IFE, AppleH10CamIn-User-Client (Befehle in research/inventar) |
| Sensoren | fehlt | laufen im ADSP-SSC, kein I2C-Sensor im Live-DTB | Vendor-Sensor-Config | QMI-SSC-Client über SpesAudio-ADSP-GLINK, AppleSPU-Ersatz |
| Video | mediaserverd SIGBUS im H.264-Software-Decoder (planare 420v-IOSurface) | nicht reproduziert in diesem Durchgang | — | Absturz mit Video in Safari auslösen, CRASH-Zeile + SweetSurface-Planes prüfen |
| Direktes Metal | Metal über metal2vulkan/Turnip für Apps; Oberfläche GL | backboardd auf Metal ~4× langsamer (Autor all45: ~49 ms/Bild) | HackiOS hakios-metal (PM4 direkt, nur POCO-Adreno), Mesa ir3 | AIR→NIR→ir3 statt SPIR-V; A610-Unterschiede prüfen |
| Neustart nach Fastboot bei laufendem ADSP/Modem | PON-Grund wird gesetzt (zurückgelesen), Syncs ok (0205), PAS-Shutdown vor PSCI (0207) | all-5, all-6, all-9: Telefon setzt zurück bzw. hängt, Fastboot erscheint nie; ohne ADSP/Modem klappte es (07:53) | Linux drivers/power/reset/msm-poweroff.c (PS_HOLD auf 0 nach qpnp_pon_system_pwr_off WARM_RESET), qcom,pshold im Live-DTB | PS_HOLD-Weg statt PSCI; prüfen, ob TZ bei aktiven Subsystemen in den Download-Modus geht (USB 05c6:900e am Mac?) |
