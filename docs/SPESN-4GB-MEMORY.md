# spesn 4 GB: XNU RAM below 4 GiB (0174/0175, not built, not run)

Phone: Redmi Note 11 2201117TG, ABL/DT say **spesn** (board-id 0x30022, SM5602 + bq2589x/SYV690 +
sc8551@0x66), **4 GB**. Live FDT memory (ABL-filled):
`0x40000000+0x3dd00000`, `0xc0000000+0x80000000`, `0x80000000+0x40000000`; every fixed
reserved-memory carve-out is below `0x63900000`; dynamic pools have `alloc-ranges` 0..4 GiB.

| Layout | XNU RAM | How |
| --- | --- | --- |
| default (unchanged) | `0x1_00000000` + 1 GiB | `mkadt.py --device spes --memory-dtb LIVE` |
| new, opt-in | `0xa0000000` + 2.5 GiB | `... --memory-floor 0xa0000000` / `SPES_MEMORY_FLOOR=0xa0000000 tools/build-spes-*.sh` |

On the iosv2 author's 6 GB spes the default gave `0x1_00000000` + 3 GiB (NOTES.md "shim range
0x100000000 + 3 GiB").

## Changes

- `tools/spes_memory.py`: `select_memory(blob, floor=4 GiB)`. A floor below 4 GiB must be 32 MB
  aligned and >= `0xa0000000`; then touching banks are merged and iosv2's fixed regions (ABL load
  area, scanout pool, relocated modem pool) are excluded. Default path unchanged (ADT byte-identical
  apart from the random seed, checked against the live FDT).
- `tools/mkadt.py --memory-floor` (spes + `--memory-dtb` only; off by default).
- `tools/build-spes-{diagnostic,ios,ios-graphics,ios-optimized}.sh`: pass `SPES_MEMORY_FLOOR`
  if set; the diagnostic image is then named `...-floor0xa0000000.img`.
- `0174-spesn-modem-pool-outside-kernel-ram.patch`: SpesModem's 16 MB pool (`0xE0000000`, 0099) moves
  to `0x9C000000` when the default lies inside `gPhysBase..+gPhysSize`; boot-arg
  `spesmodempool=PA` overrides; inside kernel RAM, < `0x9C000000` or > `0xF0000000` is refused.
- `0175-spes-amp-probe-board-labels.patch`: log labels for 0x66/0x65 per board (text only).
- tests: 5 new cases in `tests/test_spes.py` (50 tests pass).

## Every place that assumes "XNU RAM is above 4 GiB" (patched tree 8c30543 + 0173)

| # | Where (patch) | Assumption | With XNU RAM `0xa0000000-0x140000000` |
| --- | --- | --- | --- |
| 1 | `tools/spes_memory.py` `max(base, 0x100000000)` | only RAM >= 4 GiB | now the floor; default unchanged |
| 2 | `SpesModem.cpp` `MODEM_POOL_BASE 0xE0000000` (0099) | "RAM the kernel does not manage" | **inside kernel RAM: modem/WLAN/ADSP buffers would overwrite kernel pages** -> 0174 |
| 3 | `SpesAudio.cpp:221/1599` ADSP metadata, stage-3 buffer from that pool, `pa+len <= 4 GiB` (0115, 0148, 0152) | pool below 4 GiB | holds with the pool at `0x9C000000` |
| 4 | `SweetSurface.h` scanout pool `0x90000000-0x9c000000` (0116) | "RAM XNU does not use" | still outside (floor >= `0xa0000000` enforced) |
| 5 | `SweetFramebuffer.cpp:1160` direct scanout needs `pa < 4 GiB` (0109/0116) | scanout memory is the pool | unchanged (pool) |
| 6 | 0109 `inTaskWithPhysicalMask` (contiguous kernel RAM below 4 GiB), 0111 DSI buffer, 0112 black frame | never succeeds on spes | replaced by 0116/0121/0122; no `inTaskWithPhysicalMask` left in the tree -> no effect |
| 7 | `SweetFramebuffer.cpp:349` DSI buffer `0x5cefc000` in the splash carve-out (0121 -> 0122) | 32-bit DMA, kernel RAM unusable | DT-reserved, unchanged |
| 8 | `start.s:681` splash block in the V=P L2 table, "all bring-up RAM below 4GB" (0010) | splash and RAM in L1 entry 0 (0-64 GB) | true for both layouts |
| 9 | `pmap.c:6884` widen before shift (0101) | PA > 32 bit | correct for any PA |
| 10 | `sweet_ufs.c:477` DMA above 4 GiB needs UFSHCI CAP.64AS (0034) | - | DMA may now be below 4 GiB; check simply not hit |
| 11 | `sweet_ufs.c:720`, `sweet_usb.c:821` `kmem_alloc_contig` without limit, hi/lo registers (0028/0073) | 64-bit DMA | pages may come from below 4 GiB; fine |
| 12 | GPU: `sweet_touch.c:1632` SMMU tables, `:2129` ZAP MDT, `:2363`; `spes_gpu_backend.h:92` rejects >= 2^36 (0098) | 64-bit | fine; fixed `0x5ca00000`, `0x56615000` unchanged |
| 13 | GPU cache paths `RedwoodGPU.cpp:451-497` `pushModified`/`hostPush` via `phystokv` (0160/0161); `spes_gpu_backend.h:224` census | `phystokv` panics outside `gPhysBase..+size` | host buffers are kernel RAM in both layouts; pool surfaces (`0x90000000`) outside in both -> same behaviour as today |
| 14 | `sweet_rpmh.c:138` cmd-db `pa < 4 GiB` (0062, sweet) | firmware locator | unrelated |
| 15 | `IOLib.cpp:763` (XNU) physical-mask allocations | - | no spes caller left |
| 16 | `mkadt.py` arm-io `ranges` `(0, 0x01000000, 0xff000000)` | - | XNU reads only `ranges[1]` (`pe_identify_machine.c:192`, SoC base); IODeviceTree translates arm-io child `reg` (gic) only -> overlap with RAM is harmless |
| 17 | `mkadt.py` `HIGH_PHYS_BASE 0x140000000`/`HIGH_MEM_SIZE 4G` | topaz upper bank | `--highmem` only; spes refuses it |
| 18 | `mkadt.py` `PHYS_BASE 0xb0000000`/`MEM_SIZE` | sweet bring-up base | topaz/QEMU default only, never spes |
| 19 | `shim/loader.c:139` payload vs kernel overlap | - | stops with "ramdisk overlaps kernel memory" if the ABL puts the ramdisk at >= `0xa0000000` (visible on screen) |
| 20 | dynamic reserved-memory pools (CMA, qseecom, secure display, adsp, dump) | below 4 GiB = not XNU's | now inside XNU's range; **assumed Linux-only allocations** (nothing allocates them under XNU) |
| 21 | Qualcomm XPU/TZ protection of `0xa0000000-0xffffffff` | - | **unknown**. iosv2 used `0x90000000` (scanout, CPU + MDP) and `0xE0000000` (modem pool, CPU + TZ + modem) on spes without faults; no XNU RAM below 4 GiB was ever run on SM6225 |

## Evidence check: "topaz starts at 0xb0000000" was wrong

- topaz phone: upper bank `0x1_40000000` + 4 GiB (`docs/TOPAZ-UPSTREAM.md:17`, `mkadt.py --highmem`).
- `0xb0000000` is **sweet's** (SM7150) bring-up base: NOTES.md:5074-5076 ("use physBase = 0xb0000000
  (above ramdump_fb 0xaf000000+16M, cdsp_sec, qseecom), end before rmtfs"), NOTES.md:4863 (1.2 GiB,
  before HIGHMEM 0034). It stayed in `mkadt.py` as the non-highmem/QEMU default.
- So: XNU below 4 GiB has run on sweet (SM7150), never on SM6225.

## Test order (each step only after the previous one is understood)

1. Kernel with 0173-0175 from CI. Diagnostic image, **unchanged 1 GiB**:
   `tools/build-spes-diagnostic.sh KERNEL LIVE_FDT storage` -> `fastboot boot`. Shim must print
   `PHYS base=0x100000000 size=0x40000000`; UFS probe as on spes.
2. Same profile, **new layout**: `SPES_MEMORY_FLOOR=0xa0000000 tools/build-spes-diagnostic.sh ...` ->
   `spes-storage-probe-floor0xa0000000.img`. Expect `PHYS base=0xa0000000 size=0xa0000000`.
   Instant reset without panic = XPU/TZ in that range -> back to step 1 layout. Then `touch`,
   `gpu-display` and `wifi` profiles with the floor (`wifi` must log `SpesModem: pool 0x9c000000`).
3. iOS (`build-spes-ios.sh` with the floor) only after the user's explicit go for userdata.
