#!/bin/bash
# drive2.sh <tapx> <tapy> <png-name> -- cold start to home, then one tap and a capture.
# Home is detected with the plate band, not PNG byte size (size is a useless state proxy here).
export MSYS_NO_PATHCONV=1 MSYS2_ARG_CONV_EXCL='*'
A="/c/Android/Sdk/platform-tools/adb.exe -s ${SERIAL:-emulator-5560}"
OUT=C:/lapisbuild
REF=C:/lapisbuild/delivery/x_state.png
SHOT=$OUT/delivery/$3.png
cd /c/lapisbuild || exit 1
S() {
  $A shell screencap -p /sdcard/s.png >/dev/null 2>&1
  $A pull /sdcard/s.png "$1" >/dev/null 2>&1
  python plate_diff.py "$REF" "$1" 2>/dev/null
}
T() { $A shell input tap "$1" "$2"; }

$A shell am force-stop com.klab.lapis
sleep 2
$A shell am start -n com.klab.lapis/com.klab.jackpot.notification.FirebaseMessagingActivity >/dev/null 2>&1
sleep 55
# The title screen sometimes raises "您的设备不支持 Google Play 服务" with 确定 at 949,390; if that
# dialog is up, the start tap at 640,560 lands on nothing and the driver waits for a home it can't reach.
T 949 390
sleep 3
T 640 560
sleep 10
T 965 622
HOMEOFF=999
for i in $(seq 1 16); do
  sleep 7
  [ "$i" -le 3 ] && T 949 390
  HOMEOFF=$(S "$OUT/delivery/hunt.png")
  case "$HOMEOFF" in ''|*[!0-9.]*) HOMEOFF=999;; esac
  OK=$(python -c "print(1 if $HOMEOFF < 3.0 else 0)")
  [ "$OK" = 1 ] && break
done
echo "home plate_diff=$HOMEOFF"
if [ "$OK" != 1 ]; then echo "HOME NOT REACHED"; exit 1; fi
$A shell logcat -c
T "$1" "$2"
sleep 14
D=$(S "$SHOT")
echo "page shot $SHOT (plate_diff vs home: $D)"
$A shell logcat -d > "$OUT/page_$3.txt" 2>&1
echo "MD5FAIL=$(grep -c 'MD5 VERIFY' $OUT/page_$3.txt) LuaExc=$(grep -c LuaException $OUT/page_$3.txt) InitScroll=$(grep -c 'InitScrollView' $OUT/page_$3.txt) P120=$(grep -c 'P120' $OUT/page_$3.txt)"
grep -A8 'LuaException' "$OUT/page_$3.txt" | head -30
