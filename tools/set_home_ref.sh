#!/bin/bash
# set_home_ref.sh — regenerate delivery/home_ref.png the honest way. The gate REFUSES to run without
# this file (see delivery_gate.sh), because a reference invented from an unverified frame is worse
# than none: on 09-29 the auto-created one was the 关卡 stage map - 1,366,494 B, inside the same
# 1.33-1.40 MB window the size heuristic calls home - and every page after it reported "not at home".
#
# Provenance this script establishes: drive2.sh with NOREF=1 waits for the client's OWN home-entry
# report (business_request P251) before it takes the frame, then two more samples 30 s and 60 s later
# so the drift of a live 3D room is measured rather than assumed. The threshold only means something
# next to that number, so it is printed. A human still has to look at home_cand.png and say yes.
export MSYS_NO_PATHCONV=1 MSYS2_ARG_CONV_EXCL='*'
A="/c/Android/Sdk/platform-tools/adb.exe -s ${SERIAL:-emulator-5560}"
OUT=C:/lapisbuild/delivery
shot() { $A shell screencap -p /sdcard/k.png >/dev/null 2>&1; $A pull /sdcard/k.png "$OUT/$1.png" >/dev/null 2>&1; stat -c %s "$OUT/$1.png" 2>/dev/null || echo 0; }

NOREF=1 bash C:/lapisbuild/drive2.sh || { echo "drive2 failed, no candidate"; exit 1; }
cp $OUT/home.png $OUT/home_cand.png
sleep 30; shot home_b >/dev/null
echo "drift(candidate vs +30s) = $(python C:/lapisbuild/plate_diff.py $OUT/home_cand.png $OUT/home_b.png)"
sleep 30; shot home_c >/dev/null
echo "drift(candidate vs +60s) = $(python C:/lapisbuild/plate_diff.py $OUT/home_cand.png $OUT/home_c.png)"
echo "candidate = $OUT/home_cand.png"
echo "if it is the club room with the seven nav plates:  cp $OUT/home_cand.png $OUT/home_ref.png"
echo "then sanity-check the bands against known pages:   python C:/lapisbuild/plate_diff.py home_ref.png <subpage>.png  (expect ~111)"
