#!/bin/bash
# Cold start -> (title, terms, optional OP movie) -> home -> one page tap -> report.
#   bash drive_page.sh <tapx> <tapy> <tag>
# Screenshots are read as byte sizes: home 1.29-1.36 MB, terms ~495 KB, title ~1.44 MB,
# event popup ~1.20 MB. Size is a state proxy only; the final png is what gets eyeballed.
export MSYS_NO_PATHCONV=1 MSYS2_ARG_CONV_EXCL='*'
A="/c/Android/Sdk/platform-tools/adb.exe -s ${SERIAL:-emulator-5558}"
OUT=C:/lapisbuild
S() {
  $A shell screencap -p /sdcard/s.png >/dev/null 2>&1
  $A pull /sdcard/s.png "$OUT/$1.png" >/dev/null 2>&1
  stat -c %s "$OUT/$1.png" 2>/dev/null || echo 0
}
# wait_for <tag> <lo> <hi> <tries> -> 0 if a screenshot size lands in [lo,hi]
wait_for() {
  local tag=$1 lo=$2 hi=$3 n=$4 s
  for ((i=0;i<n;i++)); do
    s=$(S "$tag")
    if [ "$s" -ge "$lo" ] && [ "$s" -le "$hi" ]; then echo "  ok $s after $((i*6))s"; return 0; fi
    sleep 6
  done
  echo "  timeout (last $s)"; return 1
}
T() { $A shell input tap "$1" "$2"; }

$A shell am force-stop com.klab.lapis
sleep 2
$A shell am start -n com.klab.lapis/com.klab.jackpot.notification.FirebaseMessagingActivity >/dev/null 2>&1
echo "title:"; wait_for d_title 1380000 1520000 12
T 640 560
echo "terms:"; wait_for d_terms 470000 520000 10 || { echo "no terms dialog (already agreed?)"; }
T 965 622
echo "home:"; wait_for d_home 1280000 1370000 25 || { echo "HOME NOT REACHED"; exit 1; }
$A shell logcat -c
T "$1" "$2"
sleep 12
echo "page:"; S d_page
$A shell logcat -d > "$OUT/page_$3.txt" 2>&1
echo "MD5FAIL=$(grep -c 'MD5 VERIFY' $OUT/page_$3.txt) LuaExc=$(grep -c LuaException $OUT/page_$3.txt)"
grep -A7 'LuaException' "$OUT/page_$3.txt" | head -40
