#!/usr/bin/env bash
# rebuild_relay.sh — stub sources -> classes3/4.dex -> signed game APK -> install
# PKG=cn (default) builds com.klab.lapis; PKG=jp builds com.klab.lapis.jp beside it.
set -uo pipefail
PKG="${PKG:-cn}"
case "$PKG" in cn|jp) ;; *) echo "PKG must be cn or jp"; exit 1;; esac
BT="C:/Android/Sdk/build-tools/34.0.0"
AJ="C:/Android/Sdk/platforms/android-34/android.jar"
KS_PASS="${KS_PASS:?set KS_PASS to the password of YOUR OWN keystore - see docs/BUILD.md step 1}"
# ADB_BIN overrides which adb installs the APK. More than one adb binary on a host is not neutral:
# they fight over the single server on port 5037, so the device the other one was talking to seems to
# vanish. Pick one and use it everywhere (build, sweep, gate). SERIAL is whatever `adb devices` shows.
ADB="${ADB_BIN:-C:/Android/Sdk/platform-tools/adb.exe}"
export MSYS_NO_PATHCONV=1 MSYS2_ARG_CONV_EXCL='*'
# The CN/JP split must be applied BEFORE anything is compiled. javac/d8 freeze Seed.java's pin
# strings into classes3.dex, and pkg_lang.py flips that pin in the SOURCE -- so with the flip sitting
# after the compile, every JP build shipped the Japanese table while its own dex still demanded the
# CN digest. Seed.pass skips work while the device copy exists, so this only bites at the one moment
# the seeder exists for: after the client deletes the file, when the JP build answers "SEED refused"
# and comes up on an empty Config table. Both flips stay restored on every exit path, so an
# interrupted build cannot leave the tree claiming the wrong package for the next one.
cd /c/lapisbuild
ADIR="${APK_DIR:-C:/lapisbuild}"
# A normal build never carries the multi-gigabyte tree archive; the default stays the 208 MB APK.
# BUNDLE_TREE=1 opts in, and the trap un-stages it so an interrupted full build cannot leave a 5.6 GB
# asset in the decoded tree or a tree gate pointing at an archive that is no longer there.
# Absolute paths on purpose: this trap fires from whatever directory the build died in (javac
# runs after a cd into stubapp), and a relative name there restores nothing -- which would leave the
# decoded tree claiming the wrong package for every later build while the comment claimed it was safe.
trap 'python C:/lapisbuild/pkg_manifest.py cn >/dev/null; python C:/lapisbuild/pkg_lang.py cn >/dev/null; python C:/lapisbuild/pkg_story.py cn >/dev/null; python C:/lapisbuild/pkg_port.py cn >/dev/null; python C:/lapisbuild/pkg_tree.py none >/dev/null' EXIT
python pkg_manifest.py "$PKG" || { echo "MANIFEST FAIL"; exit 1; }
python pkg_lang.py "$PKG" || { echo "LANG TABLE FAIL"; exit 1; }
# The asset-server port is the fourth per-package difference: the stub derives its listen ports and
# the endpoint pref from the package, and the client's one baked http://127.0.0.1:18080/ string has
# to move with it, or the second install on a device is answered by the first install's stub.
python pkg_port.py "$PKG" || { echo "PORT FLIP FAIL"; exit 1; }
# The story tree is the third per-package difference (CN text vs pristine JP bundles). It has to be
# flipped before javac for the same reason the lang pin does: Seed.java's STORY_SHA1 is compiled into
# classes3.dex, so a flip after the compile would ship an archive the running dex refuses to install.
python pkg_story.py "$PKG" || { echo "STORY TREE FAIL"; exit 1; }
if [ "${BUNDLE_TREE:-0}" = 1 ]; then
  python pkg_tree.py "$PKG" || { echo "TREE BUNDLE FAIL"; exit 1; }
fi
cd /c/lapisbuild/stubapp

CP="src"; for j in libs/*.jar; do CP="$CP;$(cygpath -w "$j")"; done
CP="$CP;$AJ"
# javac/jar are Windows binaries and MSYS_NO_PATHCONV is set, so a "/tmp/..." output dir lands in
# C:\tmp\... while an MSYS `rm -rf /tmp/...` cleans AppData\Local\Temp: the two never met, and every
# build since has repacked .class files whose sources were deleted. Use one absolute path.
OUT="C:/lapisbuild/stubapp/build_out"
rm -rf "$(cygpath -u "$OUT")" "$OUT" && mkdir -p "$(cygpath -u "$OUT")"
javac -J-Duser.language=en -encoding UTF-8 -nowarn -d "$OUT" \
  -cp "$(cygpath -w .);$CP" $(ls src/com/klab/lapis/stub/*.java | tr '\n' ' ') || { echo "JAVAC FAIL"; exit 1; }
echo "[OK] javac"

rm -f classes.jar && jar cf classes.jar -C "$OUT" com
rm -rf dexout && mkdir -p dexout
ARGS=""; for j in libs/*.jar; do b=$(basename "$j"); case "$b" in guava*|failureaccess*) ;; *) ARGS="$ARGS $(cygpath -w "$j")";; esac; done
# -Xmx is explicit on purpose: d8's default max heap is a fraction of physical RAM, and on this host
# that reservation failed outright ("页面文件太小", errno 1455) while other large jobs were resident,
# killing the build after javac had already succeeded. 1 GB is ample for this dex and makes the
# failure mode a clean error instead of an mmap refusal.
java -Xmx1024m -cp "$(cygpath -w "$BT/lib/d8.jar")" com.android.tools.r8.D8 --release --min-api 21 \
  --lib "$AJ" --output "C:/lapisbuild/stubapp/dexout" $ARGS "C:/lapisbuild/stubapp/classes.jar" 2>&1 | grep -aiE "error" | head -5
[ -f dexout/classes.dex ] || { echo "D8 FAIL"; exit 1; }
cp dexout/classes.dex ../game_decoded/classes3.dex
cp dexout/classes2.dex ../game_decoded/classes4.dex
echo "[OK] dex -> classes3/classes4"

# The stub reads its schema from the APK's assets, so regenerate-then-sync; protocol.descriptor.bin
# comes from gen_protocol_descriptor.py (client Lua schema), manifest.xml deliberately does not.
# arena/mail/task/gacha are read in ProtobufCore's constructor, so they must ship in the APK or the
# whole stub fails to initialise. shopgoods.json is P121's cost/grant/limit table (make_shopgoods.py).
for a in protocol.descriptor.bin common.descriptor.bin version.json player.json shop.json \
         shopgoods.json pvpreward.json stageawards.json arena.json mail.json task.json gacha.json \
         mirror.json lab-account.json startup-key.json protocol-static.json; do
  cp -f "assets/$a" "../game_decoded/assets/$a" || { echo "ASSET SYNC FAIL $a"; exit 1; }
done
echo "[OK] assets synced"

# Seed.java pins the SHA-1 of every packaged database and refuses to install a source that does not
# match, so a drift here would ship bytes the running app rejects at each cold boot -- and the
# client deletes these files itself, so the game would come up with an empty Config table.
# The host-side test runs Seed's own hashing code over the staged bytes: pin vs file, sidecar shape
# (40 uppercase hex, no newline) and a one-byte mutation control.
rm -rf stubapp_test_out
AJ="$AJ" javac -J-Duser.language=en -nowarn -encoding UTF-8 -d stubapp_test_out -cp "src;$AJ" \
  src/com/klab/lapis/stub/Seed.java src/com/klab/lapis/stub/L.java \
  test_src/com/klab/lapis/stub/SeedHashTest.java 2>&1 | head -10
# Without this the test runs against whatever classes the last build left in stubapp_test_out, so a
# compile error here reports the PREVIOUS pin's verdict -- a pass that certifies bytes this build
# never compiled.
[ -f stubapp_test_out/com/klab/lapis/stub/SeedHashTest.class ] || { echo "SEED TEST COMPILE FAIL"; exit 1; }
java -cp stubapp_test_out com.klab.lapis.stub.SeedHashTest "C:/lapisbuild/game_decoded/assets" \
  > seedtest.txt 2>&1
grep -aE "^FAIL|PASS$|^[0-9]+ FAIL" seedtest.txt
grep -aq "ALL PASS" seedtest.txt || { echo "SEED HASH TEST FAIL"; exit 1; }
# no longer describe a JP artifact. The in-apk check must compare against build-time truth.
cd /c/lapisbuild
python patch_il2cpp.py || { echo "IL2CPP PATCH FAIL"; exit 1; }
# libklbsqlite3.so carries the two patches that let a seeded plaintext master_data.db be read
# (the sqlite3_open_v2 vfs rewrite and the klb_vfs xOpen name-parse accept). It is rebuilt from
# the pristine backup on every build so the diagnostic detours that once lived in the same cave
# cannot come back: those hard-coded the CN package's klbopen.log paths and, when every one of
# them failed -- which is exactly the JP build's situation -- deliberately stored through the
# packed errno, so the JP client SIGSEGV'd before its title screen on every boot.
python patch_klb_func.py >/dev/null || { echo "KLB PATCH FAIL"; exit 1; }
cp -f libklbsqlite3.so game_decoded/lib/arm64-v8a/libklbsqlite3.so || { echo "KLB COPY FAIL"; exit 1; }
# The identity and language flips now happen at the top of this script, before javac, so that the
# pin strings compiled into classes3.dex are the same ones the packaged assets carry.
bash /c/lapisbuild/pincheck.sh || { echo "STAGED PIN CHECK FAIL"; exit 1; }
# Snapshot now: the exit trap restores the tree to CN, so after this build the live pins no
# longer describe a JP artifact. The in-apk check must compare against build-time truth.
bash /c/lapisbuild/pincheck.sh --dump /c/lapisbuild/pins_at_build.txt || exit 1
APK=$ADIR/game_relay.apk
[ "$PKG" = jp ] && APK=$ADIR/game_relay_jp.apk
java -jar tools/apktool.jar b -o "$ADIR/game_relay_unsigned.apk" game_decoded > "$ADIR/apktool.log" 2>&1 || { echo "APKTOOL FAIL"; tail -5 "$ADIR/apktool.log"; exit 1; }
"$BT/zipalign.exe" -f -p 4 "$ADIR/game_relay_unsigned.apk" "$ADIR/game_relay_aligned.apk" >/dev/null || { echo "ALIGN FAIL"; exit 1; }
"$BT/apksigner.bat" sign --ks "C:\\lapisbuild\\stubapp\\lapis.keystore" --ks-pass "pass:$KS_PASS" \
  --key-pass "pass:$KS_PASS" --out "$APK" "$ADIR/game_relay_aligned.apk" >/dev/null 2>&1 || { echo "SIGN FAIL"; exit 1; }
# The archive is inside the APK by now, so drop the 5.6 GB staged copy before zipalign
# doubles it again - C: cannot hold both.
[ "${BUNDLE_TREE:-0}" = 1 ] && rm -f game_decoded/assets/res/JP/tree.zip
rm -f "$ADIR/game_relay_unsigned.apk" "$ADIR/game_relay_aligned.apk"
echo "[OK] apk built $APK ($(stat -c%s $APK) B)"
# The client carries the asset-server port in one baked Unity string, and the stub binds a
# per-package base. Assert the artifact agrees with the package it was built for -- the tree having
# been flipped is not evidence that apktool packed the flipped bytes.
PORT=$(unzip -p "$APK" "assets/bin/Data/9bdd7e35b810546fdbe3f8fa3ec1fd55" 2>/dev/null | grep -aoE "127\.0\.0\.1:180[0-9][0-9]" | sort -u | paste -sd, -)
WANT_PORT=18080; [ "$PKG" = jp ] && WANT_PORT=18090
echo "$PORT" | grep -aq "$WANT_PORT" || { echo "ASSET PORT FAIL: apk has [$PORT] want $WANT_PORT"; exit 1; }
echo "[OK] in-apk asset port $PORT ($PKG)"
bash /c/lapisbuild/pincheck.sh --apk "$APK" --pins /c/lapisbuild/pins_at_build.txt || { echo "APK PIN CHECK FAIL"; exit 1; }
# An install that prints Failure used to still exit 0, so the caller believed a build that never landed.
# The default target is the AVD; emulator-5560 was LDPlayer's "rev2" instance and that install is gone,
# so a build without SERIAL now lands on a device that exists instead of failing on a dead name.
SERIAL="${SERIAL:-emulator-5554}"
if [ "${NO_INSTALL:-0}" = 1 ]; then
  echo "[SKIP] install (NO_INSTALL=1)"
  exit 0
fi
INSTALL=$("$ADB" -s "$SERIAL" install -r "$APK" 2>&1); RC=$?
printf '%s\n' "$INSTALL" | tail -2
# The old LDPlayer adb printed exactly "Success", so the guard required that word. platform-tools r34
# prints "Install command complete in N ms" and only ever says Failure when it failed -- which turned a
# verified-good install (package lastUpdateTime matching the apk mtime) into a build error. Assert the
# negative and check the exit status instead of hunting for a magic word.
if [ $RC -ne 0 ] || printf '%s' "$INSTALL" | grep -qi "failure"; then
  echo "INSTALL FAIL on $SERIAL (rc=$RC)"; exit 1
fi
