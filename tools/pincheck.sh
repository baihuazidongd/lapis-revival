#!/usr/bin/env bash
# pincheck.sh — verify the database bytes Seed.java pins, in the staged tree and inside a built APK.
#
# Seed refuses to restore a source whose SHA-1 does not match, so a build that ships different bytes
# than it certified comes up with an empty Config table. The pin table is parsed here rather than with
# a line-anchored grep (each entry wraps across two lines) and CR is stripped, because python on this
# host writes CRLF and a trailing CR makes two identical digests compare unequal.
#
# An APK must be checked against the pins AS OF BUILD TIME, not the current tree: the build restores
# the tree to CN on exit, so a JP artifact legitimately carries a table the restored pins no longer
# describe. Snapshot with --dump before apktool runs and pass it back with --pins.
#
#   pincheck.sh                        verify the staged tree against the current Seed pins
#   pincheck.sh --dump FILE            write the current pins to FILE
#   pincheck.sh --apk APK --pins FILE  verify the databases inside APK against a pinned snapshot
set -uo pipefail
cd /c/lapisbuild/stubapp || exit 1

DUMP=""
APK=""
PINS_FILE=""
while [ $# -gt 0 ]; do
  case "$1" in
    --dump) DUMP="$2"; shift 2;;
    --apk) APK="$2"; shift 2;;
    --pins) PINS_FILE="$2"; shift 2;;
    *) APK="$1"; shift;;
  esac
done

read_pins() {
  python -c "import re,sys
t=re.sub(r'\s+',' ',open('src/com/klab/lapis/stub/Seed.java',encoding='utf-8').read())
rows=[m[0]+' '+m[1] for m in re.findall(r'\"(res/[^\"]+)\", *\"([0-9A-F]{40})\"', t)]
# The story archive is declared as two separate constants rather than a TARGETS pair, so it needs its
# own pattern. Without this line a 126 MB tree ships with no gate at all.
s=re.search(r'STORY_ASSET\s*=\s*\"([^\"]+)\".*?STORY_SHA1\s*=\s*\"([0-9A-F]{40})\"', t)
if s: rows.append(s.group(1)+' '+s.group(2))
sys.stdout.write('\n'.join(rows))" | tr -d '\r'
}

if [ -n "$DUMP" ]; then
  read_pins > "$DUMP" || exit 1
  [ -s "$DUMP" ] || { echo "PIN PARSE FAIL (Seed.java shape changed?)"; exit 1; }
  echo "pins -> $DUMP"
  exit 0
fi

if [ -n "$PINS_FILE" ]; then
  [ -s "$PINS_FILE" ] || { echo "MISSING PINS FILE $PINS_FILE"; exit 1; }
  PINS=$(tr -d '\r' < "$PINS_FILE")
else
  PINS=$(read_pins)
fi
[ -n "$PINS" ] || { echo "PIN PARSE FAIL (Seed.java shape changed?)"; exit 1; }

fail=0
if [ -n "$APK" ]; then
  case "$APK" in /*|[A-Za-z]:*) ;; *) APK="/c/lapisbuild/$APK";; esac
  [ -f "$APK" ] || { echo "MISSING APK $APK"; exit 1; }
  # The asset check alone cannot see this build's real failure mode: Seed.java's pin is compiled into
  # classes3.dex, so a source tree flipped after the compile yields an APK whose packaged table and
  # packaged pin disagree while every source-level comparison still passes. Compare the pin against
  # the artifact the app actually runs - the dex, not the .java it was built from.
  rm -rf ../dexcheck && mkdir -p ../dexcheck
  unzip -o -q "$APK" "classes*.dex" -d ../dexcheck || { echo "DEX EXTRACT FAIL $APK"; exit 1; }
  while read -r asset want; do
    [ -n "$asset" ] || continue
    if grep -aq "$want" ../dexcheck/classes3.dex; then echo "[OK] in-dex $asset $want"
    else echo "DEX PIN FAIL $asset compiled dex does not contain $want"; fail=1; fi
  done <<< "$PINS"
  rm -rf ../assetcheck && mkdir -p ../assetcheck
  while read -r asset want; do
    [ -n "$asset" ] || continue
    unzip -o -q "$APK" "assets/$asset" -d ../assetcheck || { echo "EXTRACT FAIL $asset"; fail=1; continue; }
    got=$(sha1sum "../assetcheck/assets/$asset" | cut -c1-40 | tr 'a-z' 'A-Z')
    if [ "$got" != "$want" ]; then echo "APK PIN FAIL $asset got=$got want=$want"; fail=1
    else echo "[OK] in-apk $asset $got"; fi
  done <<< "$PINS"
else
  while read -r asset want; do
    [ -n "$asset" ] || continue
    got=$(sha1sum "../game_decoded/assets/$asset" | cut -c1-40 | tr 'a-z' 'A-Z')
    if [ "$got" != "$want" ]; then echo "STAGED PIN FAIL $asset got=$got want=$want"; fail=1
    else echo "[OK] staged $asset $got"; fi
  done <<< "$PINS"
fi

exit $fail
