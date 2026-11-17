#!/bin/bash
# Build the full inventory database from one IPSW (Teil A/D). Read-only on the IPSW; results stay local.
#   build.sh IPSW OUTDIR [ADT_NAME e.g. d22ap]
# Needs: compression_tool, lipo, hdiutil (macOS), venv with capstone+numpy (tools-local/inventar/.venv).
set -eu
IPSW=$1; OUT=$2; ADTN=${3:-}
T=$(cd "$(dirname "$0")" && pwd); PY="$T/.venv/bin/python -I"
mkdir -p "$OUT/kc" "$OUT/mnt"
# kernelcache: first one listed in the IPSW (pick by ADT name if given)
KCN=$(unzip -Z1 "$IPSW" | grep '^kernelcache\.release' | head -1)
unzip -o -q "$IPSW" "$KCN" -d "$OUT/kc"
python3 -I - "$OUT/kc/$KCN" "$OUT/kc/kc.lzfse" <<'P'
import sys; d=open(sys.argv[1],'rb').read(); i=d.find(b'bvx2')
assert i>0, 'kernelcache not LZFSE (bvx2) - LZSS/AEA not handled yet'
open(sys.argv[2],'wb').write(d[i:])
P
compression_tool -decode -a lzfse -i "$OUT/kc/kc.lzfse" -o "$OUT/kc/kc.macho"
lipo -thin arm64 "$OUT/kc/kc.macho" -output "$OUT/kc/kc.thin" 2>/dev/null || lipo -thin arm64e "$OUT/kc/kc.macho" -output "$OUT/kc/kc.thin" 2>/dev/null || cp "$OUT/kc/kc.macho" "$OUT/kc/kc.thin"
DB=$OUT/inventar.db; rm -f "$DB"
$PY "$T/kc_scan.py" "$OUT/kc/kc.thin" "$DB"
# device tree
if [ -n "$ADTN" ]; then
  DT=$(unzip -Z1 "$IPSW" | grep -i "DeviceTree.$ADTN" | head -1)
  unzip -o -q "$IPSW" "$DT" -d "$OUT"
  python3 -I - "$OUT/$DT" "$OUT/adt.raw" <<'P'
import sys; d=open(sys.argv[1],'rb').read(); i=d.find(b'bvx2')
open(sys.argv[2],'wb').write(d[i:] if i>0 else d)
P
  if head -c4 "$OUT/adt.raw" | grep -q bvx2; then compression_tool -decode -a lzfse -i "$OUT/adt.raw" -o "$OUT/adt.bin"; else
    python3 -I -c "import sys;d=open(sys.argv[1],'rb').read();i=d.find(b'\x00\x00\x00\x00',0);open(sys.argv[2],'wb').write(d)" "$OUT/adt.raw" "$OUT/adt.bin"; fi
  $PY "$T/adt_scan.py" "$OUT/adt.bin" "$DB"
fi
# root file systems: mount all DMGs read-only, scan the shared cache and the executables
for dmg in $(unzip -Z1 "$IPSW" | grep '\.dmg$'); do
  [ -f "$OUT/$dmg" ] || unzip -o -q "$IPSW" "$dmg" -d "$OUT"
  hdiutil attach -readonly -nobrowse -noverify -mountpoint "$OUT/mnt/${dmg%.dmg}" "$OUT/$dmg" >/dev/null 2>&1 || true
done
for m in "$OUT"/mnt/*; do
  [ -d "$m/System/Library/Caches/com.apple.dyld" ] && $PY "$T/us_scan.py" "$m/System/Library/Caches/com.apple.dyld" "$DB"
  [ -d "$m/usr/libexec" ] && $PY "$T/exe_scan.py" "$m" "$OUT/exe.db"
done
sqlite3 "$DB" "attach '$OUT/exe.db' as e; create table ecall as select * from e.ecall; create table eent as select * from e.eent; create table ljob as select * from e.ljob;"
$PY "$T/cmdmap.py" "$DB"
echo "fertig: $DB"
