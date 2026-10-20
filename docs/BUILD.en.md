# Build Manual: From Zero to a Device You Can Actually Play On

This document does three things: **the success path** (in-the-moment acceptance criteria for each step, not recollection), **the build method**
(commands and ordering), and **the pitfall list** (every pit records the false symptom it produced at the time — otherwise next time
you'll chase it as a completely different problem).

Prerequisite: you already have the official client `com.klab.lapis` 1.5.0 APK and its resource archive. This repository ships neither
those nor any binaries derived from them; every "input" below refers to your own copy.

---

## 0. Directory Conventions

The path constants in the scripts are **placeholders**, not anybody's machine layout:

| Placeholder | Meaning | What's inside |
| --- | --- | --- |
| `C:/lapisbuild` | build root | `game_decoded/` (decoded APK tree), `stubapp/` (stub sources and artifacts), `tools/` (apktool, JDK), `delivery/` (acceptance artifacts) |
| `E:/lapis` | workspace | original APK, upstream resource archive, host-side resource mirror `revival/local/`, delivery overlay sources `staging/overlay_src/`, delivery set `build_full/` |
| `C:/Android/Sdk` | Android SDK | `build-tools/34.0.0`, `platforms/android-34/android.jar`, `platform-tools/adb.exe`, `cmdline-tools/latest`, `system-images/` |
| `E:/ref-sample` | your own reference sample | appears only in comments, to explain what a given field/asset "is supposed to be"; not included in this repository |
| `E:/android-avd` | AVD home | `ANDROID_AVD_HOME` points here |

Change all of them at once:

```bash
cd lapis-revival
grep -rl 'C:/lapisbuild' tools | xargs sed -i 's#C:/lapisbuild#/your/build/root#g'
grep -rl 'E:/lapis'       tools | xargs sed -i 's#E:/lapis#/your/workspace#g'
grep -rl 'C:/Android/Sdk' tools | xargs sed -i 's#C:/Android/Sdk#/your/android-sdk#g'
```

Three environment variables you must set yourself; the repository carries no values:

| Variable | Purpose |
| --- | --- |
| `KS_PASS` | your own keystore password (see §1) |
| `ADB_BIN` | which adb to use; **exactly one allowed**, see §7 |
| `SERIAL` | the target device listed by `adb devices` |

Toolchain: JDK (anything 17+ works for compiling; the scripts are written around `-encoding UTF-8 -nowarn`), `apktool`,
`build-tools 34.0.0` (`zipalign` + `apksigner` + `lib/d8.jar`), Python 3.13,
the `android-34 google_apis x86_64` system image (only needed when using an emulator).

---

## 1. One-Time Setup

```bash
# 1) Decode the base APK
apktool d -f -o game_decoded <你的官方 APK>

# 2) Your own keystore (do not reuse someone else's)
keytool -genkeypair -keystore stubapp/lapis.keystore -alias lapis \
  -keyalg RSA -keysize 2048 -validity 10000 \
  -storepass "$KS_PASS" -keypass "$KS_PASS" -dname "CN=lapis-lab"

# 3) Put the dependency jars into stubapp/libs/ (protobuf-java, protobuf-java-util, etc.; not provided with the repo)
```

**Why the signature must change**: reinstalling under the same package name requires a matching signature, and the original package's
signing key is not something we can get. Changing the signature means giving up compatibility with the original live server —
no cost for going standalone — but **a new signature invalidates the old save**, so any user who already has the online version
installed must export `shared_prefs` before upgrading (see the survival rules in §6).

---

## 2. Build (Run Once Per Package)

```bash
cd /your/build/root
NO_INSTALL=1 PKG=cn bash tools/rebuild_relay.sh     # -> game_relay.apk
NO_INSTALL=1 PKG=jp bash tools/rebuild_relay.sh     # -> game_relay_jp.apk
```

| Switch | Default | Effect |
| --- | --- | --- |
| `PKG` | `cn` | `cn` = `com.klab.lapis` (keeps the original save), `jp` = `com.klab.lapis.jp`; the two packages can coexist on one device |
| `NO_INSTALL=1` | installs | build only, no device install |
| `BUNDLE_TREE=1` | off | stuff the multi-GB resource tree into the APK; **never in normal use** — the delivery form is "thin APK + one `import.zip`" |

Output is about 242 MB (includes the client itself, excludes the resource tree).

### What Happens Inside the Script (Every Acceptance Criterion Lives in This Section)

1. **The four per-package flips must happen before `javac`.**
   `pkg_manifest.py` (package name/permissions/label) → `pkg_lang.py` (language-table digest pin) → `pkg_port.py`
   (CN base port 18080 / JP 18090) → `pkg_story.py` (CN translated story library vs original JP library).
   The reason: the pins in `Seed.java` are constants **compiled into `classes3.dex`**. Flipping after compilation produces
   "the package carries the JP tables while the dex validates against the CN digests". That doesn't error at build time; it shows up
   at cold start as `SEED refused`, empty Config tables, and the UI reverted to an unlocalized state.
   The `trap` at the end of the script restores all four to CN, so an interrupted run never leaves the tree in the wrong identity —
   which is the basis for **running two different PKGs back-to-back from the same source tree being safe**.
2. `javac` → `jar` → `java -Xmx1024m ... com.android.tools.r8.D8` → write `classes.dex` / `classes2.dex`
   as `game_decoded/classes3.dex` / `classes4.dex`.
   The `-Xmx` is hardcoded on purpose: d8 by default requests a fraction of physical memory and gets refused on a memory-tight host (see §8).
3. **The asset sync list** (that `for a in ...` in `rebuild_relay.sh`):
   `protocol.descriptor.bin common.descriptor.bin version.json player.json shop.json shopgoods.json
   pvpreward.json stageawards.json arena.json mail.json task.json gacha.json mirror.json
   lab-account.json startup-key.json protocol-static.json`
   New assets **must be added to this same line at the same time**, otherwise the APK won't contain them, and at runtime the only
   symptom is "that page is blank with zero requests".
4. `SeedHashTest`: runs `Seed.java`'s own hashing code on the host, comparing pins against each database one by one, with two controls —
   sidecar shape (40 uppercase hex characters, no newline) and "flipping one byte must fail".
5. `patch_il2cpp.py`, `patch_klb_func.py`: the latter **rebuilds** `libklbsqlite3.so` from the pristine backup every time
   (vfs rewrite of the `sqlite3_open_v2` argument + letting plain filenames through in `klb_vfs.xOpen`). Rebuilding from backup rather
   than patching in place is so the diagnostic code that once lived in the same hole can never come back — that code hardcoded the CN
   package's log path, failed everything on the JP package, then stored the error using the packaged errno, and the JP client SIGSEGV'd
   before even reaching the title screen.
6. `pincheck.sh` (staged state) → `apktool b` → `zipalign -f -p 4` → `apksigner`.
7. **Two final checks on the artifact** (this step cannot be skipped: "the tree was flipped correctly" is not the same as
   "the APK contains the correctly flipped bytes"): `pincheck.sh --apk --pins pins_at_build.txt` compares against the build-time
   snapshot; then extract `assets/bin/Data/9bdd7e35b810546fdbe3f8fa3ec1fd55` from the APK and assert that the endpoint string baked
   into Unity contains 18080 (cn) / 18090 (jp).

### Generated Assets (Re-run Whenever Master Data Changes)

| Script | Produces | Reads |
| --- | --- | --- |
| `make_state.py` | `player.json` | master data + save state: gacha pools, stage star ratings, wallet, club, room seats |
| `make_shopgoods.py` | `shopgoods.json` | P121's deduction/grant/purchase-limit tables |
| `make_pvpreward.py` / `make_stageawards.py` | the matching json | arena and stage rewards |
| `make_mirror.py` | `mirror.json` | Spacetime Rift: `ClubMirror` / `ClubMirrorEvent` / `Config` / `DropGroup` |
| `gen_protocol_descriptor.py` | `protocol.descriptor.bin` | schema declarations in the client Lua (**a single `FileDescriptorProto`, not a Set**, 407 messages) |

`protocol.descriptor.bin` is the entry point for "asking which field the client reads without looking at Lua": the stub assembles
responses with `DynamicMessage` against it; field names and numbers all live here.

---

## 3. Packing the Resource Tree (The Other Half of the Delivery Form)

```bash
python tools/make_tree_zip.py         # -> staging/tree_cn.zip
python tools/make_tree_jp_from_cn.py  # -> staging/tree_jp.zip
```

- Entries are selected by the **device manifest** (a path list counted off a real device), then our own modified files from
  `staging/overlay_src/` are layered on top. The manifest is not decoration: packing the whole tree directly brings in things the
  device never reads and misses the copy that exists only on the device.
- The JP tree isn't repacked from scratch; it is "CN tree + per-entry replay of the per-package differences" (632 entries: CN
  translated story bundles and language tables), with differing bytes copied back one by one from the old JP archive, everything
  `ZIP_STORED` + `force_zip64=True`.
- **The SoundBanks completion pass**: the device originally had only 129 of 1,021 banks; the rest are an optional CDN download
  upstream (`DownloadConfig.SoundBankName` → `VOX_CHR_*` / `VOX_EVT_*`). Offline there is no CDN, so character voices are
  **silent for the entire span** — no error, no prompt, nothing visible in the log either. After completion: 1,040.
- **Sidecar rules differ by type; do not try to "unify" them**: `.bnk.hash` = exactly 40 bytes, uppercase SHA-1, no newline;
  `.bdl.hash` = **41 bytes** (with newline). Missing sidecar or wrong length and the asset simply doesn't load.
- Exclude nested duplicate directories like `SoundBanks/SoundBanks/` (measured 484 MB of pure duplication).
- The tree contains 1 zero-byte bundle (empty upstream, `.../pickupray4/bg.bdl`), and its symptom string is identical to the
  "EncryptKey header XOR not cleared" symptom (`Unable to read header from archive file`), so **check the size before the key**.

---

## 4. Shipping

```bash
python tools/ship_checksums.py     # copy into build_full/ -> streaming SHA-1 -> rewrite CHECKSUMS.txt -> read-back verification
```

Four delivery artifacts (`manifests/delivery-sha1.txt` is our build's fingerprint): two APKs + two trees,
about 14 GB in total. **Six-GB-class files must not be `read()`** — this was actually hit once as a `MemoryError`, so everything
streams in 4 MB chunks. The first three header lines of `CHECKSUMS.txt` stay byte-for-byte untouched; after writing, read it back
and recompute line by line.

The build is **not bit-reproducible** (zip timestamps go into the package), so verification can only compare **assets inside the
package**, never the whole-package hash. That is also the only criterion for "is what landed on the device actually the thing I
just built": `adb install` returning `Install command complete` only proves a package was installed, not that it was *this*
package. Install must be chained to build in the **same `&&` chain**, and afterwards compare the sha1 of `assets/player.json`
against the new literals in the dex.

---

## 5. Deployment (Once Per Fresh Install)

```bash
adb -s "$SERIAL" install -r /your/build/root/game_relay.apk
cp /your/workspace/build_full/tree_cn.zip /tmp/import.zip
adb -s "$SERIAL" push /tmp/import.zip /sdcard/Android/data/com.klab.lapis/files/import.zip
adb -s "$SERIAL" shell am start -n com.klab.lapis/com.klab.jackpot.notification.FirebaseMessagingActivity
# The only completion criterion is this line, not a file count:
adb -s "$SERIAL" logcat -d | grep "SEED tree installed"
```

- **Never, ever `pm clear`**: it destroys the entire deployed tree along with everything else, and rebuilding means re-pushing 7 GB.
- A half-finished push will get read; we've seen `SEED tree fatal: unexpected EOF`; just wait for the push to finish before starting.
- The deployment archive is not subject to the digest gate, and the app deletes it itself after a successful import.
- Two reproducible pits: `adb push` onto a FUSE target may delete the existing same-named file; laying the tree with `tar x` makes
  directories `0770`, which the app can't read. So big trees go through `/data/local/tmp` (ext4) + tar, with permissions adjusted
  separately.
- The **owner** of a file on disk decides whether the app can read it: a `0660` file created by shell inside the app's own directory
  is unreadable by the app; an `0660` file written by the app itself is fine.

---

## 6. Save Survival Rules (Decide Whether an "Upgrade" Is Possible)

Survives: `force-stop`, `adb install -r` (same signature), device reboot, AVD cold restart (even a 7 GB tree survives it).
Kills the save: `pm clear`, uninstall-then-reinstall, **changing the signature**.
The save itself is a single `shared_prefs/lapis_state.xml`, with keys shaped like `wal_1` / `itm_<id>` / `goods_<id>` /
`stage_<id>` / `av_bind_<id>` / `mir_*`.

---

## 7. Acceptance

```bash
bash tools/delivery_gate.sh      # cold start + per-page acceptance criteria
bash tools/sweep_cn.sh           # page-by-page sweep from the home entries: which protocol number this page actually fired, how many client exceptions
python tools/boot_state.py <png> --home <本机自采首页> --cut <切点>   # frame classification
```

**Page identity is proven only by protocol numbers, never by screenshots**: an unmapped protocol gets an all-zero response back, and
the page still renders fine — with empty content. `P9000` and `P1021` are the 60-second heartbeat and **must never be taken as
evidence of "I clicked it"** — the shape we fell into was "clicked a button → the log moved → marked pass", and those two lines
were just the heartbeat.

Details on the other criteria:
- Cold start is driven by the stub's own logs, not fixed sleeps. An earlier version slept 200 s then blindly tapped
  "title/agree"; on the second restart the client was actually still on the title page, and it had never been to the frames the
  back half of the sweep report claimed.
- For logcat, do `-c` then `-d` per page; don't attach a persistent stream: a single `logcat -v time` run wrote 2.1 GB.
- One device, one driver. Two drivers don't error loudly; they interleave taps and write each other's half-pages into the same
  result file, which reads like "the page opened but no protocol". The scripts guard this with a `mkdir` atomic lock, and a killed
  background task leaves live child processes behind, so **the guard is the lock, not the task manager**.
- Before the per-page sweep, pin the device under test to its calibrated resolution: `wm size 1280x720` + `wm density 240`, and
  after the sweep `wm size reset` + `wm density reset`. The two calibrated geometries (emulator 2400x1080, tablet 2000x3200) have
  **different aspect ratios**, so no single scale factor can map the button tables across.
  Note that changing `wm density` makes Android pop a "Tap to restart" overlay, which thrashes the frame classifier back and forth
  between title/campaign/unknown while the screen is actually already home — **when the classifier thrashes, look at the frames directly**.
- The home reference image must come from *this* driven device with *this* save. The nameplate and level overlay the judgment boxes,
  so a different save makes the judgment drift; the cut point (`--cut`) is **a property of the reference image**, not of the game (AVD 12 / tablet 25).
- Don't derive coordinates by eye: guest has `rotation=1`, `input tap` works in the landscape space, while `wm size` reports the
  **natural orientation** 1080x2400, and neither derives from the other. Use PIL to find button centers via color runs (by eye,
  twice in a row, it was off by 160 px).

---

## 8. Test Machine (Optional; Skip the Whole Section on a Real Device)

```bash
export ANDROID_AVD_HOME=E:/android-avd ANDROID_SDK_ROOT=C:/Android/Sdk
"$ANDROID_SDK_ROOT/cmdline-tools/latest/bin/avdmanager.bat" create avd \
  -n lapis34 -k "system-images;android-34;google_apis;x86_64" -d pixel_6 --force
# Then edit $ANDROID_AVD_HOME/lapis34/config.ini:
#   disk.dataPartition.size=40G   hw.ramSize=6144
#   hw.gpu.mode=swiftshader_indirect   PlayStore.enabled=no
cd "$ANDROID_SDK_ROOT/emulator"
ANDROID_AVD_HOME=E:/android-avd ANDROID_SDK_ROOT=C:/Android/Sdk \
  ./emulator.exe -avd lapis34 -no-window -no-audio -no-boot-anim -no-snapshot \
  -gpu swiftshader_indirect -accel on
```

Each of these three pits is worth one round of debugging:
1. **Launch through `emulator.exe`, always.** Starting `qemu-system-x86_64-headless.exe` directly gives
   `libandroid-emu-curl.dll: cannot open shared object file`.
2. Without `ANDROID_AVD_HOME` → `Unknown AVD name` (when the AVD isn't in `$HOME\.android\avd`).
3. Without `ANDROID_SDK_ROOT` → `Broken AVD system path` (when the system image isn't under the default SDK root).

Two more at the environment level:
- Every fresh start gets blocked by a **modal** system window, `ImmersiveModeConfirmation` ("Viewing full screen / Got it"):
  it grabs focus, the game looks frozen, and it sends zero requests. Click the button's measured bounds; don't use `keyevent 4`.
- The client only ships arm64-v8a/armeabi-v7a, so an x86 host needs an instruction-translation layer; the emulator's disk image is
  an order of magnitude slower than a real device (see the comparison timings in §9), so **never judge game feel by emulator timings**.

### `errno=1455 The paging file is too small` Has Two Causes

When `javac` / `d8` reports `os::commit_memory ... failed; error='页面文件太小' (errno=1455)` it reads like a disk problem,
and neither cause is one:

| Cause | Criterion | Fix |
| --- | --- | --- |
| Headless AVD hogging (measured qemu process at 26.5 GB private, pushing available commit memory below 2 GB) | `Get-Process \| Sort PrivateMemorySize64` | **stop AVD → build → start AVD**; `adb emu kill` doesn't take, use `Stop-Process -Id <pid> -Force` |
| Paging file grew and never shrinks (current usage a few hundred MB, allocation 19 GB+) | `Get-CimInstance Win32_PageFileUsage`, compare `AllocatedBaseSize` vs `CurrentUsage` | Only a reboot releases it; or move the paging file to a drive with free space (a system change, needs admin) |

Good news: stopping the AVD destroys nothing — the 7 GB resource tree survives a reboot (re-swept banks=1040, consistent).

---

## 9. Measured Timings (AVD vs. Real Device)

| Action | AVD (x86_64 + instruction translation) | Real device |
| --- | --- | --- |
| Cold start to interactive | ~90 s | — |
| `adb install` of the 242 MB APK | 19 s | — |
| Push the 6.06 GB tree | 368 s (16.5 MB/s) | — |
| Push the 7.0 GB tree | ~536 s (12.5 MB/s) | — |
| Import extraction | **441 s** | **8 s** |
| Home-screen PSS | 885 MB | — |

Import differs by 55×, and the emulator's disk image is the culprit. **Never use AVD timing conclusions to veto a real-device plan.**

---

## 10. Known Unsolved

| Item | Current state | What to investigate next |
| --- | --- | --- |
| Spacetime Rift "⚡5 challenge" | Went from completely inaccessible to showing a real boss panel; tapping challenge only sends the P1021 heartbeat, never P42 | Check the challenge's **preconditions** (the "owns cards" team-select entry is still in a disabled state; P186 is implemented but nobody calls it); the other lead is recommended power 99999999 vs `player.power` 99999. Stop guessing at P180's fields |
| Font override | Our `font.bdl` is 13.8 MB; Chinese uses 2,026 codepoints, all falling back to the system font | Requires direct byte edits of the serialized file; the UnityPy `m_FontData` assignment route was tried and did nothing (re-read still at the original size) |
| Top-up page (辉圣石) | Blank | Those slots come from Google Play Billing native callbacks, and the 5 main tabs are a fixed prefab; unfixable from the data side |
| Unimplemented protocols | Client requested, we have no handler: P111 friends, P132 event ops, P170 club wishes, P250/P251 beast-repulsion battles, P1014 terms receipt, P1016 secondary confirmation, P1028 specific tasks, P1100 event chapters | Fill them one by one per §7's protocol-number criteria; note that "unmapped" presents as an all-zero response + an empty page |
| Leftover Japanese in stories | Language tables are now at 0 kana; what remains sits in hardcoded Lua, art text baked into the UI, subtitles burned into videos, and untranslated dialogue in 631 story bundles | Dialogue is JSON TextAssets tagged with `_language` inside bundles; reading them through `UnityPy.m_Script` turns them into `?` — use `get_raw_data()` + `save('original')` |