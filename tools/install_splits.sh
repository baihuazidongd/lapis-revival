#!/usr/bin/env bash
# install_splits.sh — sign the freshly built resource splits and commit them alongside the base.
set -uo pipefail
BT="C:/Android/Sdk/build-tools/34.0.0"
ADB="${ADB_BIN:-C:/Android/Sdk/platform-tools/adb.exe}"
KS_PASS="${KS_PASS:?set KS_PASS to the password of YOUR OWN keystore - see docs/BUILD.md step 1}"
export MSYS_NO_PATHCONV=1 MSYS2_ARG_CONV_EXCL='*'
cd /c/lapisbuild

rm -rf splits_signed && mkdir splits_signed
for a in splits/split_*.apk; do
  n=$(basename "$a")
  "$BT/apksigner.bat" sign --ks stubapp/lapis.keystore --ks-pass "pass:$KS_PASS" \
    --key-pass "pass:$KS_PASS" --min-sdk-version 21 --out "splits_signed/$n" "$a" \
    || { echo "SIGN FAIL $n"; exit 1; }
  echo "[OK] signed $n ($(stat -c%s "splits_signed/$n") B)"
done

echo "[i] cert of split_0001 vs base:"
"$BT/apksigner.bat" verify --print-certs --min-sdk-version 21 splits_signed/split_0001.apk | grep "SHA-256 digest"
"$BT/apksigner.bat" verify --print-certs game_relay.apk | grep "SHA-256 digest"

echo "[i] install-multiple (this streams $(du -sh splits_signed | cut -f1))"
"$ADB" -s ${SERIAL:-emulator-5558} install-multiple -r game_relay.apk splits_signed/split_*.apk 2>&1 \
  | grep -iE "^Failure|^Success|INSTALL_" | head -3
