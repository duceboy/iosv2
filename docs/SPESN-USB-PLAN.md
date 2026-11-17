# spesn USB device mode: plan (not built, not run)

Goal (ROADMAP-TREIBER.md): network over USB to the Mac, live log, file server, then SSH via dropbear.
Built only after the graphics boot has been evaluated; one change per run.

## Sources

- iosv2 sweet 0072–0077 (`bsd/dev/sweet_usb.c`, SM7150): DWC3 device mode, polled event buffer, ep0,
  CDC-ECM, ifnet. Byte-identical to ios-flame's copies. **Base of the port.**
- NWylynko/ios-flame @ 745c4341 (Pixel 4, SM8150), all in `sweet_usb.c` (read 2026-11-17, research only):
  0081 link state (SIOCGIFMEDIA, KEV_DL_LINK_ON; not in iosv2, whose 0081 is a topaz patch), 0089 tools
  (UDP command server :5141, console-ring mirror, poke scripts, apps-SMMU fix, PHY init), 0091 file server
  (TCP :2223 PUT/GET/MKDIR/LINK/RM/CHMOD, ARP broadcast + 60-byte padding, sync), 0094 READ + /dev/pmem,
  0098 panic log into the ring, 0099 PMIC RTC (read only). Live log: UDP to 192.168.7.1:5140 every
  100 ms. Phone 192.168.7.2/24, Mac 192.168.7.1. Host: flame-live.py, flame-cmd.py, flame-files.py,
  flame-install-ssh.sh (dropbearmulti + dash + toybox to /var/local/bin, job
  /System/Library/LaunchDaemons/org.iosonpixel.dropbear.plist added to the launchd job cache), ~1.2 MB/s.

## SM6225 values (live FDT + run 1, 2026-11-17)

| | SM6225 spesn |
|---|---|
| DWC3 core / QSCRATCH | 0x04e00000 / 0x04ef8800 |
| HS PHY | qcom,usb-hsphy-snps-femto 0x01613000; ABL overrides 0xa6/0x85/0x16 at 0x6c/0x70/0x74 **kept (user rule)** |
| GCC / USB GDSC / CBCRs | 0x01400000 / 0x1a004 / 0x1a010 0x1a014 0x1a018 0x1a080 0x1a084 0x1d008 0x9f000 |
| after fastboot boot | GDSC on, all 7 CBCRs on, DWC3 3.30a run/stop 0, ABL event buffer 0x9df50000 |
| D+/D- switch | GPIO 31 output low = data lines to the SoC (Linux usb_switch 0) |
| apps SMMU / USB SID | 0x0c600000 (qsmmu-v500, skip-init) / 0x120 |

## Decisions

1. Base on sweet 0072–0077 + the generic parts of flame 0081/0089/0091/0094/0098; drop the SM8150
   specifics (GCC offsets, QUSB2/femto init, SMMU at 0x15000000).
2. **No PHY writes**: flame's `ud_hsphy_init` is not ported (user rule: keep ABL overrides while fastboot
   works). GDSC/clocks are not written either (ABL leaves them on; flame does the same).
3. **SMMU**: flame found that ABL drops its stream match on exit and the first DMA resets the SoC.
   iosv2 already solved this for WLAN (SID 0x1a0) and audio (0x1C1) with `spes_smmu_identity()`
   (SpesModem.cpp, run 3: "WLAN identity ... -> OK"). USB uses the same function for SID 0x120, after a
   read-only dump of the SMR/S2CR entries for 0x120.
4. DMA: buffers from the existing modem pool region below 4 GiB or kmem_alloc_contig (XNU RAM now
   starts at 0xa0000000, below 4 GiB); decided when porting.
5. GPIO 31 stays as ABL left it (read and logged, 0181).
6. Stages behind `sweetusb=` like sweet: 1 read (0176 done), 2 device mode + CDC-ECM, then live log,
   command/file server, then SSH install via the file server.

## Reboot into fastboot without keys

ios-flame: the shim writes the IMEM restart cookie (0x77665500 at restart_reason) **and** the PMIC PON
SOFT_RB_SPARE (SID0 0x88f, reason 2 in bits 7:1) plus PS_HOLD reset type, then PSCI SYSTEM_RESET
(0x84000009). Google's ABL reads only the PMIC register.

spesn (live FDT): IMEM restart_reason **0x0c12565c**, pshold 0x0440b000, PM6125 PON SID0 0x800
(qcom,system-reset, store-hard-reset-reason) -> SOFT_RB_SPARE 0x88f (standard PON gen2 layout, not
verified for PM6125). No reboot-mode/dload-mode node. **Never touch dload_type (0x0c12501c).**

Plan: first test only the IMEM cookie (SoC SRAM, no PMIC) + PSCI SYSTEM_RESET. If Xiaomi's ABL then
boots normally instead of fastboot, it reads the PMIC: the 0x88f write is outside the SPMI allow-list
and needs the user's go (described only, not implemented).
