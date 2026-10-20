#!/bin/bash
# delivery_gate.sh — cold start with the radios untouched, walk every originally-online page,
# perform one real purchase and one real arena settlement, count exceptions, prove every socket
# the game opens is loopback, and prove no diagnostic scaffolding is left in the running build.
#
# Everything in this file is measured, not remembered:
#   * coordinates are from 1280x720 captures of THIS build (see the plate table below);
#   * page identity is the protocol the tap caused, never the PNG byte size;
#   * log analysis happens host-side - this toybox `grep -aiE` segfaults, and CJK literals lose
#     their bytes on the way through the shell, so the CN audit is done in python on a pulled DB.
export MSYS_NO_PATHCONV=1 MSYS2_ARG_CONV_EXCL='*'
# Same ADB_BIN override the build and the sweep use, on purpose: two different adb binaries fight over
# the single server on port 5037, and the symptom is a device that appears to drop off the bus.
A="${ADB_BIN:-C:/Android/Sdk/platform-tools/adb.exe} -s ${SERIAL:-emulator-5554}"
OUT=C:/lapisbuild/delivery
FILES=/storage/emulated/0/Android/data/com.klab.lapis/files
mkdir -p $OUT
PKG=com.klab.lapis

shot() { $A shell screencap -p /sdcard/k.png >/dev/null 2>&1; $A pull /sdcard/k.png "$OUT/$1.png" >/dev/null 2>&1; stat -c %s "$OUT/$1.png" 2>/dev/null || echo 0; }
T() { $A shell input tap "$1" "$2"; }
pid() { $A shell "ps -A -o PID,NAME 2>/dev/null | grep -a 'com.klab.lapis$'" | tr -dc '0-9'; }
# logdump — full buffer to a host file. Never `logcat -T <ts>` (returns nothing here) and never a
# line-count offset (another driver can restart the app and wipe the buffer mid-run).
logdump() { $A shell "logcat -d -v time 2>/dev/null" | tr -d '\r' > "$1"; }
cnt() { local n; n=$(grep -acE -- "$1" "$2" 2>/dev/null) || true; echo "${n:-0}"; }
# Seed.java logs "SEED done" on every pass whether or not it installed anything, so counting the
# literal "SEED" reports one line per run and can never fail. The two counts that mean something are
# restores (a DB was missing and got fixed) and anomalies (refused / no source / fatal).
seed_ok()  { cnt 'SEED restored' "$1"; }
seed_bad() { cnt 'SEED (refused|no source|fatal)' "$1"; }
PLATE() { python C:/lapisbuild/plate_diff.py "$1" "$2"; }

# netproof: no `svc wifi/data disable`, no airplane-mode write - those three commands have wedged a
# guest adbd on two instances (5558 on 2026-09-27, 5560 on 2026-09-28) and the state persists in
# /data across a full VM power-cycle. Offline-ness is asserted positively instead: every ESTABLISHED
# socket held by the game uid must be loopback, which is a stronger claim than "airplane mode and
# it still works". uid comes from the live process; `dumpsys package | grep userId=` does not match
# on this build and silently reported established=0 for every page.
netproof() {
  U=$($A shell "ps -A -o UID,NAME 2>/dev/null | grep -a 'com.klab.lapis$' | head -1" | tr -dc '0-9')
  # Field order in /proc/net/tcp{,6} is sl local rem st tx:rx tr:tm->when retrnsmt uid timeout inode
  # - so the uid is $8, not $9. Getting this wrong once made a root-owned socket look like the game's.
  $A shell "cat /proc/net/tcp /proc/net/tcp6" 2>/dev/null | tr -d '\r' | awk -v u="$U" -v lbl="$1" '
    function dip(h,  i,o){ if(length(h)>8) h=substr(h,length(h)-7); o=""; for(i=7;i>=1;i-=2) o=o (i==7?"":".") strtonum("0x" substr(h,i,2)); return o }
    $8 == u && $4 == "01" {
      f = $3; sub(/:.*/, "", f); p = $3; sub(/.*:/, "", p)
      lb = (f ~ /0100007F/ || f ~ /^0+$/ || f ~ /00000000000000000000000001000000$/)
      n++; if (lb) l++; else print "    NON-LOOPBACK uid=" $8 " -> " dip(f) ":" strtonum("0x" p) " local=" $2
    }
    END { printf "  net[%s] uid=%s established=%d loopback=%d external=%d\n", lbl, u, n, l, n - l }'
}

# to_home — cold start instead of navigating back. This game throws a first-time tutorial popup or a
# scenario cutscene at the entrance of several pages (the card list and the gacha page both do), and
# those swallow the page-back X; a "walk back to home" loop then taps blind and pollutes the state of
# the NEXT page, which is exactly how one run recorded the 魔女考试 popup as "the gacha page will not
# close". A cold start is deterministic and costs ~100 s, and a delivery gate may spend that.
#
# home_ref.png is a VERIFIED ARTIFACT (see set_home_ref.sh) and this script refuses to invent one:
# the 09-29 00:5x run auto-created it from a frame the PNG-size heuristic called home, which was
# actually the 关卡 map - both sit at ~1.34 MB - and every page after that was reported "not at home"
# against a reference that had never been home. A wrong oracle must fail loudly, not quietly skip.
[ -f $OUT/home_ref.png ] || { echo "FATAL: $OUT/home_ref.png is missing - run C:/lapisbuild/set_home_ref.sh and confirm the frame by eye first"; exit 1; }
to_home() {
  bash C:/lapisbuild/drive2.sh >> $OUT/gate_drive.log 2>&1
  for t in 1 2 3; do
    d=$(PLATE $OUT/home_ref.png $OUT/home.png)
    # 8.0, not 3.0: measured against the verified reference, home-vs-home drift tops out at 2.6 across
    # a cold start while the nearest non-home band (a dialog over home) starts at 55.
    awk -v d="$d" 'BEGIN{exit !(d<=8.0)}' && { echo "  to_home ok plate_diff=$d" >> $OUT/gate_drive.log; return 0; }
    echo "  to_home try $t plate_diff=$d (not home, re-sampling)" >> $OUT/gate_drive.log
    sleep 8; shot home >/dev/null
  done
  echo "  to_home FAILED last plate_diff=$d" >> $OUT/gate_drive.log
  return 1
}

echo "=== radio state (read-only) ==="
echo "wifi_on=$($A shell settings get global wifi_on | tr -d '\r') data=$($A shell settings get global mobile_data | tr -d '\r') airplane=$($A shell settings get global airplane_mode_on | tr -d '\r')"

$A shell am force-stop $PKG; sleep 3
# The seed/diag self-heal lines are emitted during process start, so capture them BEFORE the buffer
# is cleared - otherwise the "no scaffolding" section can only ever see an empty buffer and reports
# a pass it did not earn.
logdump $OUT/gate_pre_seed.log
echo "pre-restart stub lines=$(grep -ac LapisStub $OUT/gate_pre_seed.log) seed restored=$(seed_ok $OUT/gate_pre_seed.log) seed anomalies=$(seed_bad $OUT/gate_pre_seed.log)"
T0=$(date +%s)
# The arrival at home is drive2.sh's job (login P1001 -> home entry P251 -> plate proof), not a
# sequence of fixed-sleep taps. drive.sh used to be called here and its blind taps are what turned
# two gate runs into "every page refused to open": see the header of drive2.sh.
to_home && echo "home reached in $(( $(date +%s) - T0 ))s pid=$(pid)" || echo "FAIL: could not reach home on a cold start"
# drive2 clears the buffer at its own start, so the boot-time lines of THIS start are still in it.
logdump $OUT/gate_boot.log
echo "boot-buffer stub lines=$(grep -ac LapisStub $OUT/gate_boot.log) seed restored=$(seed_ok $OUT/gate_boot.log) seed anomalies=$(seed_bad $OUT/gate_boot.log)"
netproof home

# Nav plates. The painted labels sit ~40px LEFT of the clickable plate, so the old grid
# (635/725/815/905/1140) landed in the gaps almost everywhere - that artifact, not the app, is what
# earlier runs recorded as "arena segfaults" and "the shop will not open". Verified one tap at a
# time from a confirmed home state.
#            plate  expected protocol
#   卡片       695   (card list, no business call on this build)
#   召唤       802   P1024 + P100
#   アリーナ    905   P200
#   購買部     1015   P120 + P1016
#   クエスト   1135   (stage map; the battle itself is proven separately in HANDOFF_playable §2)
PLATES="card,695,- gacha,802,P1024 arena,905,P200 shop,1015,P120 quest,1135,-"
: > $OUT/gate_pages.log
for spec in $PLATES; do
  n=${spec%%,*}; rest=${spec#*,}; x=${rest%%,*}; want=${rest#*,}
  to_home || { echo "$n SKIPPED - not at home, refusing to tap"; continue; }
  logdump $OUT/.gpage_before
  $A shell logcat -c
  T $x 645; sleep 12
  logdump $OUT/.gpage_after
  cat $OUT/.gpage_after >> $OUT/gate_pages.log
  grep -a LapisStub $OUT/.gpage_after | sort -u > $OUT/.gpage_after_u
  got=$(comm -13 <(sort -u $OUT/.gpage_before) $OUT/.gpage_after_u | grep -aoE 'business_request P[0-9]+' | sort -u | tr '\n' ' ')
  shot pg_$n >/dev/null
  moved=$(PLATE $OUT/home.png $OUT/pg_$n.png)
  ok=$(awk -v d="$moved" 'BEGIN{print (d>3.0)?"MOVED":"STUCK"}')
  hit=MISS; case " $got " in *" $want "*) hit=HIT;; esac
  [ "$want" = "-" ] && hit=n/a
  echo "$n x=$x plate_diff=$moved want=$want got=[$got] $ok $hit"
  netproof $n
done

# ---- live proof 1: a real purchase (P121) ----
# Home -> 購買部 -> 兑换所 sub-tab -> first goods cell -> 兑换. The assertion is on the handler's own
# line (`P121 goods=<id> x<n> bought=<n> setters=<k>`): setters>0 means cost and grant both went out
# through the setter pipeline. There is deliberately no 获得-popup check - NetManager:5790 skips that
# popup whenever P121 carries noShowAward, so its absence is not evidence of anything.
to_home || echo "WARN: purchase section is not starting from home"
$A shell logcat -c
T 1015 645; sleep 10
T 145 507; sleep 6; shot g_exchange >/dev/null
T 443 285; sleep 5; shot g_good >/dev/null
# The 兑换确认 dialog is priced in CARDS and starts at "R 0/200", so 兑换 is inert until the quantity
# is filled. (640,528) - the old tap - is dead space between the card row and the button row: it
# dismissed nothing and bought nothing, which is why run e reported P121 handled lines = 0.
T 497 588; sleep 4; shot g_added >/dev/null   # 一括追加: 4x50 R, exactly the price
T 780 588; sleep 10                           # 兑换
logdump $OUT/g_buy.log
echo "P121 handled lines = $(grep -ac 'P121 goods=' $OUT/g_buy.log)"
grep -a 'P121 goods=' $OUT/g_buy.log | tail -2
T 965 152; sleep 3
shot g_after_buy >/dev/null

# ---- live proof 2: a real arena settlement (P204) ----
# 挑战 -> 队伍编成 -> 开始, then tap through the battle's continue prompts until the client sends P204.
# Polling for the protocol instead of a fixed sleep: the 3D fight's length varies by team.
to_home || echo "WARN: arena section is not starting from home"
$A shell logcat -c
T 905 645; sleep 12
T 155 445; sleep 8; shot a_chall >/dev/null
T 1083 648; sleep 40
for i in $(seq 1 10); do
  T 640 360; sleep 8
  logdump $OUT/.arena_poll
  grep -aq 'P204 win=' $OUT/.arena_poll && break
done
logdump $OUT/g_arena.log
grep -aoE 'business_request P20[0-9]|P204 win=[0-9]+ score=[0-9]+ to [0-9]+ drops=[0-9]+' $OUT/g_arena.log | sort | uniq -c
shot a_settle >/dev/null
T 640 520; sleep 6
: # stay where the settlement left us

# ---- exception + scaffolding audit, host-side ----
# The buffer is cleared at every page transition, so no single dump covers the session. Union all the
# dumps taken during the run and de-duplicate on the timestamped line (`logcat -v time` prefixes every
# line with MM-DD HH:MM:SS.mmm, so a repeated read of the buffer collapses to one copy). Counting
# exceptions off the LAST dump alone would have been a pass earned by an empty buffer.
logdump $OUT/gate_full.log
cat $OUT/gate_full.log $OUT/gate_boot.log $OUT/gate_pre_seed.log $OUT/gate_pages.log \
    $OUT/g_buy.log $OUT/g_arena.log $OUT/.arena_poll 2>/dev/null | sort -u > $OUT/gate_session.log
L=$OUT/gate_session.log
echo "session lines=$(wc -l < $L) (union of all dumps, de-duplicated)"
echo "=== client-side exceptions (expect all 0) ==="
for pat in LuaException 'Unable to open archive' 'Unable to read header from archive' 'Failed to read data for the AssetBundle' 'Fatal signal'; do
  echo "$pat = $(cnt "$pat" $L)"
done
echo "=== stub-side notes (benign, counted so they are not misread as errors) ==="
# ProtobufCore.java:924 logs one of these per JSON key the client's own proto has no field for, then
# skips it. On this build it is the P1024 payload (result/ads/gameInfo/gameRefresh/roleCards/roles/
# themes) - the gacha page renders and pays out, so this is payload hygiene on our side, not a client
# error. It must not sit in the exception list, where 14 of them once read as "the build has 14 errors".
echo "'json has no home' (stub skip note) = $(cnt 'json has no home' $L)"
echo "=== forbidden diagnostic tags in the running build (expect all 0) ==="
for tag in REQDIAG SIGRAW SIGDIAG SENDSKEY MEMDUMP KEYSCAN SESSION_XOR_DRIFT "tombstone relay" "diag armed" "javax.net.debug" KLBSQL; do
  echo "$tag = $(cnt "$tag" $L)"
done
# Seed.java is a legitimate self-heal (it re-materialises the two SHA-1-pinned master DBs from this
# APK's own assets, because the client deletes them after its install pass). It logs "SEED done" every
# run regardless of whether it installed anything, so that line proves nothing; "SEED restored" only
# appears when a DB was actually missing, and refused/no source/fatal are the failure paths.
echo "seed self-heal: restored=$(seed_ok $OUT/gate_pre_seed.log) anomalies=$(seed_bad $OUT/gate_pre_seed.log)  [0/0 = both DBs already present]"
echo "=== master data still in place ==="
$A shell "for f in MasterData/master_data.db MasterData/master_data.db.hash JP/master_data_lang.db; do echo \"\$f \$(stat -c %s $FILES/\$f 2>/dev/null || echo MISSING)\"; done; ls $FILES/diag $FILES/seeddb 2>/dev/null || echo 'no diag/seeddb markers'"
echo "hide_error_dialogs=$($A shell settings get global hide_error_dialogs | tr -d '\r')"

# ---- CN audit ----
# Device-side `sqlite3 ... like '%の%'` puts CJK through the shell and through adb, where bytes are
# not preserved; the verdict has to come from code points in a pulled file.
$A pull $FILES/JP/master_data_lang.db $OUT/gate_lang.db >/dev/null 2>&1
python C:/lapisbuild/cn_audit.py $OUT/gate_lang.db
