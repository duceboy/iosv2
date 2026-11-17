# What iOS 16 expects from an iPhone X and what spesn provides (gap list)

Method (2026-11-17): instead of chasing single log lines, compare what iOS asks the hardware for with what
the port answers. Sources:
1. iOS unified log of a running boot: `/var/db/diagnostics` + `/var/db/uuidtext` pulled over SSH, laid out
   as a `.logarchive` and read on the Mac with mandiant/macos-UnifiedLogs (`unifiedlog_iterator`). macOS
   `log show` refuses the archive (missing metadata). Archives stay local (research/oslog, gitignored).
2. Kernel IOKit trace (`IOK <proc>: matching ... -> none`) for SpringBoard/backboardd, also in the unified log.
3. Reference: iPhone X device tree (research/ipsw-x/d22ap.adt) and the iOS 16.7.16 kernelcache: which
   IOKit classes/properties exist on the real device.

## Display pipeline (blocks smooth UI and app launches) — first priority
- SpringBoard -> backboardd CoreAnimation commits fail: `Failed to send deferred commits ... (ipc/send)
  invalid memory` (12x), `Failed to commit transaction` (2x); backboardd: `serialization error` (57x),
  `decode_object - ptr = NULL, required_type = 49` (>60x). Apps reach "scene ready" in ~1 s, but their
  layers are missing, so the user sees the icon zoom and taps again. Kernel side: MACH_SEND_INVALID_MEMORY
  from the OOL copyin path -> 0194 logs which region and why.
- SpringBoard: `Rejecting value: <null> For key: contents` (106x).

## IOKit services iOS looks for and does not find (boot of 2026-11-17 13:3x)
| Class / match | Asked by | Real iPhone X | Effect here |
|---|---|---|---|
| AGXAccelerator | backboardd, SpringBoard | Apple GPU driver | CA uses the redwood-gl path |
| AppleM2ScalerCSCDriver | backboardd, SpringBoard | hardware scaler / colour conversion | scaling + 420v conversion on the CPU (slow; mediaserverd 420v) |
| AppleJPEGDriver | SpringBoard | hardware JPEG | software JPEG |
| AppleVXD375/390/393 | SpringBoard | video decoder | software video |
| AppleH9CamIn / AppleH10CamIn | SpringBoard | camera ISP | no camera |
| IONameMatch als | SpringBoard | ambient light sensor | no auto brightness |
| IOPropertyMatch name=gyro | SpringBoard | gyro (SPU) | no rotation sensor |
| IOPropertyMatch backlight-control | backboardd, SpringBoard | backlight node | brightness control |
| AppleSPUTimesync | SpringBoard | sensor processor | — |
| AppleCredentialManager, ApplePearlSEPDriver, /arm-io/pearl-sep | SpringBoard, backboardd | SEP / Face ID | no Face ID (not a goal) |
| IONameMatch sdio / bluetooth | SpringBoard | BT/WLAN nodes | BT open |
| IODeviceTree:/options | SpringBoard | NVRAM | — |

## Userland errors worth a driver (excerpt)
- wifid/configd: `AppleNBindToInterfaceWithService: IOServiceOpen failed` (5x each); captive: `failed to get the Wi-Fi devices`.
- deleted: `IOServiceGetMatchingService failed`; softwareupdateservicesd: `NANDSize: ... disk0 failed`.
- findmydeviced: `IORegistryEntryFromPath returned MACH_PORT_NULL`.
- healthd: no data subscription context (no cellular).

## Order
1. OOL send failure (0194 diagnostic -> fix). 2. Re-measure launches/frame rate from the unified log
(app_launch_measurement signposts, CA commit stalls). 3. Scaler/CSC fallback cost. 4. Sensors/backlight.
