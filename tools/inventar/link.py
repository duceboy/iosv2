#!/usr/bin/env python3
"""A5 + B: joins the inventory into "function -> daemons -> drivers -> commands/properties -> device-tree nodes"
and puts the Qualcomm side next to it. Writes table func_* and a local report (Markdown) per function.
The function definitions (keywords) and the Qualcomm/port columns are our own work.
   link.py DB REPORT.md OUR_KERNEL"""
import sys, sqlite3, re, subprocess

DB, REP, OURK = sys.argv[1], sys.argv[2], sys.argv[3]
db = sqlite3.connect(DB)

# function: (driver-class/kext keywords, adt node keywords, daemon keywords, MG/sysctl key keywords,
#            Qualcomm block (live DTB), Linux driver (Xiaomi kernel), port status, templates)
F = {
 'Anzeige':   (['IOMobileFramebuffer', 'AppleCLCD', 'AppleDisplay', 'DCP', 'AppleARMBacklight', 'AppleM2Scaler', 'IOAVFamily', 'AppleAcornDisplayPMU'],
               ['disp', 'backlight', 'scaler', 'clcd', 'dither', 'pmgr'], ['backboardd', 'SpringBoard'], ['Display', 'Brightness', 'main-screen'],
               'MDSS/DPU sde@5e00000, DSI0 k7_38_0c_0a, backlight über DSI-DCS', 'techpack/display (sde-kms, dsi-display, sde_rotator)', 'läuft (CPU-Kopie/Skalierung in Software, Helligkeit fest)', 'iosv2 SweetFramebuffer/Backlight'),
 'Grafik':    (['AGX', 'IOGPU', 'IOAccelerator', 'IOSurface', 'IOAcceleratorFamily'], ['sgx', 'gfx', 'agx'], ['backboardd', 'MTLCompilerService'], ['Metal', 'GPU', 'gpu'],
               'Adreno 610 kgsl-3d0@5900000', 'drivers/gpu/msm (kgsl)', 'teilweise (GL ES über Mesa/EAGL, kein Metal)', 'iosv2 0156–0168 NegroniMetal, ios-flame Turnip/m2v, HackiOS hakios-metal'),
 'Video':     (['AppleAVD', 'AppleAVE', 'AppleVXD', 'AppleJPEG', 'AppleH264', 'AppleVideo'], ['avd', 'ave', 'vxd', 'jpeg'], ['mediaserverd', 'VTDecoderXPCService'], ['HEVC', 'H264', 'Video'],
               'Venus vidc@5a00000', 'techpack/video (msm_vidc)', 'fehlt (Software-Decoder, H264SW-Absturz bei 420v)', 'keine'),
 'Ton':       (['AppleEmbeddedAudio', 'AOPAudio', 'IOAudio', 'AppleCS', 'AudioCodec', 'AppleAudio'], ['audio', 'i2s', 'codec', 'speaker', 'aop'], ['mediaserverd', 'audiomxd'], ['Audio', 'Speaker'],
               'ADSP (APR/GPR), WCD937x über SoundWire, Bolero rx/tx/va, aw87559 Verstärker @0x58/0x5b', 'techpack/audio (asoc, codecs/wcd937x, codecs/aw87xxx)', 'fehlt (Verstärker-Init vorhanden)', 'HackiOS audio_plugin.c, iosv2 spes_amp.c'),
 'Mikrofon':  (['VoiceTrigger', 'AOPAudio', 'AppleEmbeddedAudio'], ['mic', 'audio'], ['mediaserverd', 'corespeechd'], ['Microphone'],
               'WCD937x TX + VA-Makro', 'techpack/audio', 'fehlt', 'HackiOS drivers/mic'),
 'Touch':     (['Multitouch', 'AppleHIDTransport', 'AppleMultitouchSPI', 'AppleEmbeddedTouch'], ['multi-touch', 'touch', 'hid'], ['backboardd'], ['Touch'],
               'FocalTech ft3518 @I2C1 0x38, IRQ GPIO80, Reset GPIO86', 'drivers/input/touchscreen/focaltech_touch', 'läuft (gelegentlich verlorene Abheben-Ereignisse?)', 'iosv2 sweet_touch.c'),
 'Tasten':    (['Buttons', 'HIDKeyboard', 'AppleM68Buttons', 'AppleHIDKeyboard'], ['buttons', 'button'], ['backboardd', 'SpringBoard'], ['Button', 'RingerSwitch'],
               'PM6125 PON (Power, Leiser), GPIO Lauter', 'drivers/input/misc/qpnp-power-on', 'teilweise (SweetHIDButtons)', 'iosv2'),
 'Haptik':    (['Actuator', 'Haptic', 'Vibrator', 'AppleSPUHaptics'], ['haptic', 'vib', 'actuator'], ['mediaserverd', 'hapticd'], ['Haptic', 'Vibe'],
               'PM6125 LPG SID1 0xb300 + GPIO36 (lct-pwm-vibrator)', 'drivers/pwm/pwm-qti-lpg.c, drivers/leds/leds-qpnp-vibrator-pwm.c (lct-pwm-vibrator)', 'teilweise (Kernel-Stufe spesvib=4, keine iOS-Anbindung)', 'HackiOS drivers/haptic + audio_plugin Actuator'),
 'Akku':      (['SmartBattery', 'GasGauge', 'IOPMPowerSource', 'AppleSmartBatteryManager', 'Battery'], ['battery', 'gas-gauge', 'charger'], ['powerd', 'thermalmonitord'], ['Battery'],
               'SM5602 Fuel-Gauge @0x71', 'drivers/power/supply/syv/sm5602_fuelgauge.c', 'teilweise (lesend, spesbattery=1)', 'ios-topaz 0091, iosv2 SweetBattery'),
 'Laden':     (['Charger', 'Tristar', 'Hydra', 'AppleTriStar', 'AppleHPM', 'IOAccessoryManager'], ['charger', 'tristar', 'hpm', 'usb-pd'], ['powerd', 'accessoryd'], ['Charg'],
               'bq2589x/SYV690 @0x6a, sc8551 @0x66, rt1711h Typ-C @0x4e', 'drivers/power/supply/syv (bq2589x), cp_manager (sc8551)', 'ABL-Einstellung (448 mA), keine eigene Steuerung (Freigabe nötig)', 'ios-topaz 0148'),
 'Thermik':   (['TempSensor', 'AppleARMPMU', 'ApplePMGR', 'CLPC', 'ApplePPM', 'thermal'], ['temp', 'pmu', 'thermal', 'tsens'], ['thermalmonitord', 'powerd'], ['Thermal'],
               'TSENS @4410000, PM6125 ADC (xo/pa therm)', 'drivers/thermal/qcom (tsens24xx), spmi-temp-alarm, iio/adc', 'fehlt (nur Akku-Temperatur geloggt)', 'keine'),
 'Schlaf':    (['IOPMrootDomain', 'AppleARMPE', 'ApplePMGR', 'AppleCPUIdle'], ['pmgr', 'cpu'], ['powerd', 'SpringBoard'], ['Sleep'],
               'RPMh/PSCI cpu-idle, AOSS', 'drivers/soc/qcom, cpuidle', 'fehlt (kein Schlaf, Display bleibt an)', 'iosv2 SweetCPU'),
 'WLAN':      (['BCMWLAN', 'IO80211', 'AppleBCMWLAN', 'mDNSOffload'], ['wlan', 'wifi'], ['wifid', 'configd', 'apsd'], ['WiFi', 'wifi', 'Wifi'],
               'WCN3988 über WCNSS/ath10k-snoc, wlan@c800000', 'drivers/net/wireless/cnss2 + ath, icnss', 'läuft (Auto-Join, DHCP, Safari)', 'iosv2 RedwoodWLAN'),
 'Bluetooth': (['Bluetooth', 'AppleConvergedIPC', 'AppleOLYHAL', 'BTCtrl'], ['bluetooth', 'bt'], ['bluetoothd', 'BlueTool'], ['Bluetooth', 'BT'],
               'WCN3988 BT über UART QUP0 SE3, bt-sw-ctrl GPIO87', 'drivers/bluetooth/btqca, msm_bt_power', 'fehlt (bluetoothd startet ständig neu)', 'HackiOS drivers/bt (Protokoll), Linux btqca'),
 'Mobilfunk': (['Baseband', 'AppleBaseband', 'ARI', 'AppleConvergedPCI'], ['baseband', 'cellular'], ['CommCenter', 'locationd'], ['Baseband', 'IMEI', 'Cellular', 'SIM'],
               'MPSS (modem_b), QMI über SMD/GLINK, rmtfs', 'drivers/soc/qcom (qmi, glink, rmtfs), net/qrtr', 'teilweise (Modem bootet, keine QMI-Brücke zu CommCenter)', 'HackiOS drivers/modem, docs/cellular.md, iosv2 SpesModem'),
 'Ortung':    (['GPS', 'GNSS', 'AppleSPUGNSS', 'AppleEmbeddedGPS'], ['gps', 'gnss'], ['locationd'], ['GPS', 'Location'],
               'GNSS im MPSS (LOC QMI)', 'Modem-Firmware + QMI LOC', 'fehlt', 'keine (Simulations-Schnittstelle von locationd prüfen)'),
 'Sensoren':  (['AppleSPU', 'Accelerometer', 'Gyro', 'Compass', 'ALS', 'Prox', 'Pressure', 'AppleEmbeddedLightSensor', 'AppleALSColorSensor', 'AppleProx'], ['accel', 'gyro', 'compass', 'als', 'prox', 'pressure', 'spu', 'aop'],
               ['locationd', 'backboardd', 'SpringBoard'], ['Gyro', 'Accel', 'Compass', 'ALS', 'Proximity', 'Pressure'],
               'SSC/ADSP Sensoren (BMI160/ICM, AK09918, ALS/Prox stk3x1x) – sensors über ADSP-SSC', 'kein Linux-Treiber: Sensoren laufen im ADSP-SSC (Live-DTB ohne I2C-Sensor), Zugriff über QMI/sensors.ssc; Konfiguration research/spesn-vendor', 'fehlt', 'keine'),
 'Kamera':    (['CamIn', 'AppleH10', 'AppleH9', 'ISP', 'AppleCamera', 'AppleStockholm'], ['isp', 'camera', 'cam'], ['mediaserverd', 'cameracaptured'], ['Camera', 'camera'],
               'CAMSS: CPAS, CSID, CSIPHY, CCI0; S5KJN1 50 MP, ISP (IFE)', 'techpack/camera-bengal (cam_cpas, cam_isp, cam_sensor_module, cam_ope)', 'fehlt', 'HackiOS hakios.camera.c'),
 'Blitz':     (['Flash', 'Torch', 'AppleLED', 'Strobe'], ['flash', 'torch', 'strobe'], ['mediaserverd'], ['Flash', 'Torch'],
               'PM6125 Flash-LED / aw2016 @0x64 (Status-LED)', 'drivers/leds/leds-qti-flash', 'fehlt', 'keine'),
 'Speicher':  (['NVMe', 'APFS', 'IOStorage', 'IOMedia', 'AppleEffaceable'], ['nvme', 'ans', 'storage'], ['deleted', 'keybagd'], ['Disk', 'NAND', 'Storage'],
               'UFS @4804000', 'drivers/scsi/ufs', 'läuft (UFS, HFSX-Root)', 'iosv2 sweet_ufs'),
 'USB':       (['USB', 'IOUSBDevice', 'IOUserEthernet', 'AppleSynopsysOTG'], ['usb', 'otg'], ['usbd', 'lockdownd'], ['USB'],
               'DWC3 @4e00000, HS-PHY 1613000', 'drivers/usb/dwc3', 'teilweise (Gerätemodus CDC-ECM für Diagnose, kein Apple-USB-Stack)', 'iosv2 0183, sweet 0072–0077'),
 'Uhrzeit':   (['RTC', 'AppleRTC', 'IOPMrootDomain'], ['rtc'], ['timed'], ['Time'],
               'PM6125 RTC (SPMI)', 'drivers/rtc/rtc-pm8xxx', 'teilweise (Zeit über Netz/NTP?)', 'keine'),
}

def like_any(col, kws):
    return '(' + ' OR '.join(f"{col} LIKE ?" for _ in kws) + ')', ['%' + k + '%' for k in kws]

ours = set(subprocess.run(['strings', '-n', '4', OURK], capture_output=True, text=True).stdout.split())

db.executescript('''DROP TABLE IF EXISTS func_driver; DROP TABLE IF EXISTS func_node; DROP TABLE IF EXISTS func_user; DROP TABLE IF EXISTS func_qcom;
CREATE TABLE func_driver(func TEXT, class TEXT, kext TEXT, userclient TEXT, selectors INTEGER, in_port INTEGER);
CREATE TABLE func_node(func TEXT, path TEXT, drivers TEXT);
CREATE TABLE func_user(func TEXT, who TEXT, api TEXT, sval TEXT, ival INTEGER, n INTEGER);
CREATE TABLE func_qcom(func TEXT, block TEXT, linux TEXT, status TEXT, templates TEXT);''')

out = ['# Inventar je Funktion (lokal, enthält Namen aus Apple-Binärdateien – nicht veröffentlichen)\n',
       'Quelle: kernelcache + d22ap.adt + dyld-Cache + Programme von iOS 16.7.16 (iPhone X). Erzeugt von tools-local/inventar/link.py.\n',
       'Kennzeichnung: **Code** = aus Aufrufstellen/Tabellen gelesen, **Name** = Zuordnung nur über Namensmuster.\n']
for fn, (kw, nodekw, daemons, keykw, block, linux, status, tmpl) in F.items():
    w, a = like_any('p.ioclass', kw)
    w2, a2 = like_any('p.kext', kw)
    drv = db.execute(f'''SELECT DISTINCT p.ioclass, p.kext, p.userclient FROM kpersonality p WHERE {w} OR {w2}''', a + a2).fetchall()
    # classes also via kclass names
    w3, a3 = like_any('name', kw)
    cls = db.execute(f'SELECT DISTINCT name, kext FROM kclass WHERE {w3}', a3).fetchall()
    seen = {}
    for c, k, uc in drv:
        seen[c] = (k, uc)
    for c, k in cls:
        seen.setdefault(c, (k, None))
    rows = []
    for c, (k, uc) in sorted(seen.items()):
        nsel = db.execute('SELECT count(*) FROM kdispatch WHERE class = ? OR class LIKE ?', (c, c + ',%')).fetchone()[0]
        rows.append((fn, c, k, uc, nsel, int(c in ours)))
    db.executemany('INSERT INTO func_driver VALUES (?,?,?,?,?,?)', rows)
    w4, a4 = like_any('path', nodekw)
    nodes = db.execute(f'SELECT path, drivers FROM adtnode WHERE {w4}', a4).fetchall()
    db.executemany('INSERT INTO func_node VALUES (?,?,?)', [(fn, p, d) for p, d in nodes])
    # userland: matching names of the function's driver classes + MG/sysctl keys + daemons' calls
    names = [r[1] for r in rows]
    urows = []
    for tbl, who in (('ucall', 'image'), ('ecall', 'binary')):
        if names:
            q = f"SELECT {who}, api, sval, NULL, count(*) FROM {tbl} WHERE api LIKE 'IOService%Matching' AND sval IN ({','.join('?' * len(names))}) GROUP BY 1,2,3"
            urows += db.execute(q, names).fetchall()
        w5, a5 = like_any('sval', keykw)
        urows += db.execute(f"SELECT {who}, api, sval, NULL, count(*) FROM {tbl} WHERE (api LIKE 'MG%' OR api LIKE 'sysctl%' OR api LIKE 'IORegistryEntry%Property') AND {w5} GROUP BY 1,2,3", a5).fetchall()
    db.executemany('INSERT INTO func_user VALUES (?,?,?,?,?,?)', [(fn,) + tuple(r) for r in urows])
    db.execute('INSERT INTO func_qcom VALUES (?,?,?,?,?)', (fn, block, linux, status, tmpl))

    out.append(f'\n## {fn}\n')
    out.append(f'- **Stand im Port:** {status}\n- **Qualcomm:** {block}\n- **Linux-Treiber:** {linux}\n- **Vorlagen:** {tmpl}\n')
    have = [r for r in rows if r[5]]
    out.append(f'- Apple-Treiberklassen (Name): {len(rows)}, davon im Port vorhanden: {len(have)}; mit Befehlstabelle: {sum(1 for r in rows if r[4])}\n')
    for r in rows:
        if r[4] or r[3]:
            out.append(f'  - `{r[1]}` ({r[2]}) User-Client {r[3] or "?"}, Befehle {r[4]}{" – vorhanden" if r[5] else ""}\n')
    out.append(f'- Gerätebaum-Knoten: {len(nodes)}' + (': ' + ', '.join(f'`{p}`' + (f' → {d}' if d else '') for p, d in nodes[:15]) if nodes else '') + '\n')
    users = {}
    for who, api, sval, iv, n in urows:
        users.setdefault(sval, set()).add(who.split('/')[-1])
    out.append(f'- Userland (Code): {len(users)} verschiedene gesuchte Treiber/Schlüssel\n')
    for sval, whos in sorted(users.items(), key=lambda x: -len(x[1]))[:25]:
        out.append(f'  - `{sval}` ← {", ".join(sorted(whos)[:6])}{" …" if len(whos) > 6 else ""}\n')
db.commit()
open(REP, 'w').write(''.join(out))
print('functions', len(F))
