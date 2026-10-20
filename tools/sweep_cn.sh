#!/bin/bash
# sweep_cn.sh — walk the CN package's home entry points and record, per page, which protocol the tap
# actually caused and how many exceptions the client filed while it was up.
#
# Page identity is the protocol number, never the PNG: an unmapped protocol is answered with a
# zero-filled response, so a page can render and still be silently empty.
#
# The cold start is driven by the stub's OWN log, not by a timetable. An earlier pass slept a fixed
# 200 s and then tapped 标题/同意 blind; on the second restart of a run the client was still on the
# title screen, every later tap then hit title-screen coordinates while believing it was on home, and
# the whole back half of the sweep reported on frames it never actually navigated to. "verified P1001"
# is what the terms dialog's 同意 causes, so waiting for it proves the accept landed.
#
# Logging is clear-then-dump per visit, not one persistent stream: a streamed `logcat -v time` filled
# 2.1 GB on this host's C: drive during a single run.
export MSYS_NO_PATHCONV=1 MSYS2_ARG_CONV_EXCL='*'
A="${ADB_BIN:-C:/Android/Sdk/platform-tools/adb.exe} -s ${SERIAL:-emulator-5560}"
# Windows-style paths throughout: MSYS_NO_PATHCONV=1 disables the msys->win32 rewrite, so a `/c/...`
# argument reaches adb.exe and python.exe literally, they resolve it against their own working drive,
# and the capture "succeeds" into a file that does not exist here.
cd /c/lapisbuild || exit 1
# Single-instance lock. Two drivers on one device do not fail loudly - they interleave taps and write
# each other's half-pages into the same result file, which reads as "the page opened with no
# protocol" rather than "I am being driven by two scripts at once". A killed background task can leave
# its child bash alive, so this is the guard, not the task manager.
LOCKD=/c/lapisbuild/sweep_cn.lockd
# mkdir is the atomic test-and-set here. A "check the file, then write the file" lock let two drivers
# through in the same instant - they both saw no live holder, both wrote their pid, and the result
# file then interleaved a dead run's abort line with a live run's page lines.
if ! mkdir "$LOCKD" 2>/dev/null; then
  holder=$(cat "$LOCKD/pid" 2>/dev/null)
  if [ -n "$holder" ] && kill -0 "$holder" 2>/dev/null; then
    echo "another sweep (pid $holder) holds $LOCKD - refusing to double-drive the device"; exit 1
  fi
  echo "reclaiming lock from dead pid ${holder:-unknown}"; rm -rf "$LOCKD"; mkdir "$LOCKD" || exit 1
fi
echo $$ > "$LOCKD/pid"; trap 'rm -rf "$LOCKD"' EXIT
OUT=C:/lapisbuild/delivery
TMP=C:/lapisbuild/sweep_tmp_cn
PKG=com.klab.lapis
# The home reference must be captured on the device being driven, at the logical size being driven at.
# The sweep pins the tablet to 1280x720 (its panel is 2000x3200) precisely so that every coordinate
# below and every threshold in boot_state.py land on the geometry they were measured on.
REF=${REF:-$OUT/x_state_tablet.png}
RES=$OUT/sweep_cn.txt
# The per-frame state trail, so an aborted cold start can be read back without re-running it.
TRAIL=$TMP/cold_trail.txt
mkdir -p "$TMP"

T() { $A shell input tap "$1" "$2"; }
cap() { $A shell screencap -p /sdcard/s.png >/dev/null 2>&1; $A pull /sdcard/s.png "$OUT/$1.png" >/dev/null 2>&1; }
off() { python plate_diff.py "$REF" "$1" 2>/dev/null; }
# probe_state captures and names the current frame. A dropped screencap is not a new boot state, so it
# retries once and then returns empty, which the callers treat as "skip this round", never as "unknown".
probe_state() {
  cap _probe
  st=$(python boot_state.py "$OUT/_probe.png" --values 2>/dev/null)
  [ -z "$st" ] && { sleep 3; cap _probe; st=$(python boot_state.py "$OUT/_probe.png" --values 2>/dev/null); }
  printf '%s' "$st"
}
# act STATE: the boot-chain coordinate table. Each entry was verified on this tablet on 2026-10-02 by
# classifying the frame before the tap and after it: notice (1115,75) -> home, campaign (60,300) ->
# notice dialog, terms (962,633) -> campaign banner, title (640,565) -> terms dialog.
act() {
  case "$1" in
    home) return 0;;
    terms) T 962 633;;
    legal) T 640 565;;
    notice) T 1115 75;;
    play) T 966 395;;
    title) T 640 565;;
    campaign) T 60 300;;
    *) return 1;;
  esac
  return 0
}

cold() {
  # Driven by the FRAME, not by a signal from the log. "verified P1001" looked like the terms accept
  # but is really the title-screen handshake: it fires while the 利用規約 dialog is still up, so a
  # driver that waited for it declared login reached and then tapped home coordinates at a dialog.
  # An unnamed frame is waited out rather than fatal: the OP movie produces a fresh anime scene every
  # second and no pixel rule names "a cartoon", so ten consecutive unnamed frames (60 s of them) is
  # the point where "the movie is still playing" stops being the explanation.
  $A shell am force-stop $PKG; sleep 2
  $A shell logcat -c
  $A shell am start -n $PKG/com.klab.jackpot.notification.FirebaseMessagingActivity >/dev/null 2>&1
  : > "$TRAIL"
  miss=0
  for i in $(seq 1 90); do
    sleep 6
    st=$(probe_state)
    [ -z "$st" ] && continue
    echo "$i $st" >> "$TRAIL"
    s=${st%% *}
    s=${st%% *}
    if [ "$s" = home ]; then
      # The boot window is the only place the お知らせ dialog is ever created, and visit() clears
      # logcat on entry - so without this dump the one question worth asking about that spinner
      # ("what did the client ask for?") has already been erased by the time anything is on disk.
      $A shell "logcat -d -v time 2>/dev/null" | tr -d '\r' > "$TMP/boot.log"
      return 0
    fi
    if [ "$s" = unknown ]; then
      miss=$((miss + 1))
      # The campaign banner can classify as unknown: its rail measured 58-62 on one capture and 119.3
      # on the next, same popup, same build. Two replacement features were tried and both measured
      # dead - the bottom nav band raw (banner 85.5 / 88.5 against sub-pages 53.8-92.3) and the same
      # band brightness-normalised (banner 0.441 / 0.465 against sub-pages 0.291-0.547), because the
      # scrim is not a pure scalar and the panel covers part of the row anyway. So rather than abort,
      # escalate through the two proven modal controls: the boot chain has no sub-pages in it, so
      # there is nothing here for those two taps to open by mistake.
      [ $miss -eq 3 ] && T 60 300
      [ $miss -eq 6 ] && T 1115 75
      [ $miss -ge 10 ] && { echo "cold: $miss unnamed frames in a row ($st) - aborting" >> $RES; return 2; }
      continue
    fi
    miss=0
    act "$s" || { echo "cold: frame $i classified as '$st' - no tap, aborting" >> $RES; return 2; }
  done
  return 1
}

# to_home leaves a page through its own control. keyevent 4 is never used - on this game it leaves an
# invisible blocker over the dialog and every later tap on that page is silently swallowed.
# Only the four states proven to sit ON TOP of home get their own coordinate here. Every swept sub-page
# reads a left rail above 120, i.e. "title", so anything the classifier can name as a modal is checked
# by name and everything else is left through its back chevron at (52,44) - tapping the middle of a
# page because a pixel band said "campaign" is how the 課題 pass stalled for six rounds and then
# cold-restarted onto a run where "nicchi" was really the title screen.
to_home() {
  for t in 1 2 3 4 5 6; do
    st=$(probe_state)
    case "${st%% *}" in
      home) return 0;;
      notice) T 1115 75;;
      campaign) T 60 300;;
      legal) T 640 565;;
      terms) T 962 633;;
      # Two different page-back controls, because pages do not agree on where they close. The left
      # chevron at (52,44) is the shop/witch/card/mission header arrow; the 日程 page has no left
      # arrow at all and closes on a diamond X at the top right, measured off this run's capture at
      # (1170,72) - the six rounds that failed on nicchi were six taps on empty sky at (52,44).
      *) if [ $t -le 3 ]; then T 52 44; else T 1170 72; fi;;
    esac
    sleep 5
  done
  return 1
}

visit() { # name x y wait
  local n=$1 x=$2 y=$3 w=${4:-14}
  # PAGES="majo shop" re-runs only those pages; a full sweep is the default.
  if [ "${SWEEP_PAGES:-all}" != all ]; then
    case " $SWEEP_PAGES " in *" $n "*) ;; *) return 0;; esac
  fi
  # Never tap a plate from a frame that is not home. The pass that reported "nicchi req=NONE" had
  # actually cold-restarted onto the title screen and tapped the home layout's coordinates there, and
  # the row read like a dead page. A page that cannot be reached is reported as such instead.
  if ! to_home; then
    echo "$n: SKIPPED (not at home before the tap)" >> $RES
    cold || echo "$n: COLD FAILED" >> $RES
    return 0
  fi
  $A shell logcat -c
  T $x $y; sleep $w
  cap "cn_s_$n"
  $A shell "logcat -d -v time 2>/dev/null" | tr -d '\r' > "$TMP/$n.log"
  local req exc
  req=$(grep -aoE 'business_request P[0-9]+' "$TMP/$n.log" | awk '{print $2}' | grep -avE '^P(9000|1021)$' | sort -u | paste -sd, -)
  exc=$(grep -acE 'LuaException|NullReferenceException|SEED refused' "$TMP/$n.log")
  TOTAL_EXC=$(( TOTAL_EXC + ${exc:-0} ))
  printf '%-14s req=%-7s exc=%-3s plate_diff=%s\n' "$n" "${req:-NONE}" "$exc" "$(off $OUT/cn_s_$n.png)" >> $RES
  # the per-visit log is kept so the identity call can be re-read after the run
  if ! to_home; then
    echo "$n: NOT HOME -> cold restart" >> $RES
    cold || echo "$n: COLD FAILED" >> $RES
  fi
}

: > $RES
TOTAL_EXC=0
# cold() only returns 0 on a frame it can name "home", so the campaign banner is already gone here.
cold || { echo "initial cold start never reached home" >> $RES; cat $RES; exit 1; }
cap cn_s_home
echo "start home plate_diff=$(off $OUT/cn_s_home.png)" >> $RES

if [ -n "${PAGES:-}" ]; then SWEEP_PAGES="$PAGES"; else SWEEP_PAGES="all"; fi
# Plates: the hitbox sits ~29 px right of the printed label (召喚's label is x=773, the working tap is
# 802). Shot names stay ASCII - CJK in a filename loses bytes through this shell and the pull then
# writes nothing, which reads as "the page was blank" rather than "the capture failed".
# Same table as the JP pass, and it is correct for both packages. The CN pass that looked like a
# coordinate problem was a modal raycast blocker: the 新任教員応援 campaign banner sits at y<=620 and
# the plate row is at y~645, so the plates are visibly unobstructed while the banner's full-screen
# backdrop swallows every tap. plate_diff cannot see that (it only reads the top-left title plate),
# which is why to_home() classifies the frame and dismisses a modal through its own control first.
visit yingyuanhui   462 645
visit majo          577 645
visit card          684 645
visit arena         914 645
visit shop         1029 645
visit quest        1159 645
visit kadai         985 130
visit nicchi       1055 130
visit houhou       1130 130
visit tsuushin     1205 130
visit settei       1225  40
echo "TOTAL exc=$TOTAL_EXC" >> $RES
cat $RES
