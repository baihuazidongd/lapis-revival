#!/usr/bin/env bash
# provision_files.sh — stage the runtime resource tree into the app's external files dir.
# The APK carries the two master databases (Seed restores them); bundles, sound banks, il2cpp
# metadata and manifest.xml only exist on disk, so a fresh device needs this push to get past
# the pre-Unity resource check.
#
# adb push onto an *existing* /sdcard/Android/data file can silently delete it, and the
# pin-verified databases Seed just restored are exactly that, so they are excluded here and the
# tree lands through /data/local/tmp (ext4) with tar rather than per-file FUSE writes.
set -uo pipefail
export MSYS_NO_PATHCONV=1 MSYS2_ARG_CONV_EXCL='*'
ADB="${ADB:-C:/Android/Sdk/platform-tools/adb.exe}"
S="${SERIAL:-emulator-5560}"
SRC="${SRC:-/c/lapisbuild/device_files/files}"
F=/storage/emulated/0/Android/data/com.klab.lapis/files
TAR=/c/lapisbuild/files_provision.tar
# adb is a Windows binary and MSYS_NO_PATHCONV is on, so it needs the drive-letter form while
# tar/stat/md5sum need the POSIX one.
TARWIN=C:/lapisbuild/files_provision.tar
S() { "$ADB" -s "$S" shell "$1"; }

echo "=== staging tar (excludes anything Seed owns) ==="
rm -f "$TAR"
tar -cf "$TAR" -C "$SRC" \
    --exclude='JP/master_data_lang.db' --exclude='*.db' --exclude='*.db.hash' \
    manifest.xml JP SoundBanks il2cpp || { echo "TAR FAIL"; exit 1; }
echo "tar bytes=$(stat -c%s "$TAR")"

echo "=== push to /data/local/tmp ==="
"$ADB" -s "$S" push "$TARWIN" /data/local/tmp/files_provision.tar 2>&1 | tail -1
S "md5sum /data/local/tmp/files_provision.tar" | tr -d '\r'
echo "host md5=$(md5sum "$TAR" | cut -d' ' -f1)"

echo "=== extract into the app files dir ==="
# FUSE refuses utimes, so plain `tar xf` aborts partway (toybox needs -m to skip mtime restore).
# Anything from a previous run goes first: an aborted extract can leave a truncated .bdl whose
# sidecar will never match.
S "cd $F; rm -rf JP/AssetBundles SoundBanks il2cpp manifest.xml; mkdir -p JP; tar xmf /data/local/tmp/files_provision.tar -C .; echo EXTRACT_RC=\$?"
# Directories extracted by tar land as 0770 shell:shell. The app is `other`, so it has no `x` and
# cannot traverse into them -- Unity then reports `Unable to open archive file: <bundle>.bdl` for a
# bundle that is on disk, byte-identical, with a matching sidecar. `adb push` never hit this because
# the FUSE daemon creates dirs the app can use. Only the execute bit on dirs; file modes are fine.
S "cd $F; find . -type d ! -perm -o=x -exec chmod o+x {} + 2>/dev/null; echo NOOX_LEFT=\$(find . -type d ! -perm -o=x | wc -l)"
# Entering a story stage offers a 无语音/有语音 video download that commits by File.Replace into
# JP/AssetBundles/.../resources/videos/optional. o+x lets the app read bundles but not swap one, so
# the 77 MB transfer completes and then dies as UnauthorizedAccessException inside File.Replace,
# which the client surfaces as "network disconnected". Only the two dirs the downloader writes to.
S "cd $F; chmod o+rwx ./JP/AssetBundles/assets/products/resources/videos 2>/dev/null; find ./JP/AssetBundles -type d -name optional -exec chmod o+rwx {} + 2>/dev/null; echo DLDIR=\$(stat -c '%a' ./JP/AssetBundles/assets/products/resources/videos/optional 2>/dev/null)"
S "rm -f /data/local/tmp/files_provision.tar"

echo "=== what landed (expect bdl=5305 hash=4568) ==="
S "cd $F; echo bdl=\$(find . -name '*.bdl' | wc -l) hash=\$(find . -name '*.bdl.hash' | wc -l) bnk=\$(find . -name '*.bnk' | wc -l)"
S "cd $F; for d in ./JP ./SoundBanks ./il2cpp; do echo \"\$d \$(du -sh \$d 2>/dev/null | cut -f1)\"; done"
S "stat -c '%n %s' $F/manifest.xml $F/MasterData/master_data.db $F/MasterData/master_data.db.hash $F/JP/master_data_lang.db 2>/dev/null"

echo "=== sidecar spot-check (a truncated .bdl must never pass) ==="
S "cd $F; i=0; for h in \$(find . -name '*.bdl.hash' | head -40 | sort -R 2>/dev/null | head -5); do b=\${h%.hash}; want=\$(cat \$h); got=\$(sha1sum \$b | cut -d' ' -f1 | tr 'a-f' 'A-F'); if [ \"\$want\" = \"\$got\" ]; then echo \"OK \$(basename \$b)\"; else i=1; echo \"MISMATCH \$(basename \$b) got=\$got want=\$want\"; fi; done; echo SPOT_FAIL=\$i"
S "sha1sum $F/MasterData/master_data.db $F/JP/master_data_lang.db 2>/dev/null" | tr 'a-f' 'A-F'
echo "expected master=35E020FD6DF76B7162B79A5F462D8FEDFF096DF5 lang=04E7190D04B9087B6EF7E4BE7DA80AB4B3BF2717"
