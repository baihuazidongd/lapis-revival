# Handoff doc: reproduction, current state, and what the incoming person should do first

This document assumes **you have zero history with this project**. It answers four questions: which inputs are required, how to get
from scratch to the home screen, where things actually stand right now, and which pits have already been closed by measurement (don't walk them again).
The concrete commands and acceptance criteria are in `docs/BUILD.md`; the methodology and failure cases are in `docs/TECHNIQUES.md`.

---

## 0. What is not in the repo, and the inputs you need

This repo contains **only our own code, scripts, and documentation**. The original client and every one of its assets are not in it and never will be in git:
game content is copyrighted by KLab / KADOKAWA / Shengqu, and GitHub's 100 MB single-file limit can't hold a 7 GB asset tree anyway.
So the precondition for reproducing is that you already own these files yourself (this project was built from the official archive taken before the 2022 shutdown).

| Input | Used in which step | Verification |
| --- | --- | --- |
| Official client `com.klab.lapis` 1.5.0 APK (99,757,060 B, arm64-v8a + armeabi-v7a, contains `libklbsqlite3.so`) | `apktool d` to build `game_decoded/`; the base of the whole build | `manifests/required-inputs.tsv` |
| `Lapis-AssetBundles-20221022.7z` (4,229,156,448 B) | Extract the host asset mirror → the bulk of `make_tree_zip.py` | Same as above |
| `Lapis-MasterData-20221022.7z` (1,799,924 B) | Extract `master_data.db` / `master_data_lang.db`: the `Seed` pin, input for `make_state`/`make_mirror`/`make_shopgoods` | Same as above |
| `Lapis-SoundBanks-20221022.7z` (1,732,452,189 B) | The SoundBank backfill stage (the device originally had only 129/1,021 of them) | Same as above |
| `Lapis-manifests-20221201.7z` (1,053,953,620 B) | Upstream manifests/version records, used to determine which entries the device actually reads | Same as above |
| The **device-side file list** counted on a real device or AVD | `DEVICE_LIST` for `make_tree_zip.py` (not decorative, see BUILD.md §3) | Bring your own |

There is one trap that's **very easy to step in**: if you also have a "full-channel APK" lying around (~1.78 GB, `.bdl` files shipped directly inside,
ABI only armeabi-v7a/x86), **do not use it as the build base**. It has no arm64 and is not the copy we decoded; a package built from it
only reveals the problem once installed on a 64-bit device. The criterion is simple: the base must contain `lib/arm64-v8a/libklbsqlite3.so`.

Once you have the files, **compare digests before touching anything**:

```bash
sha1sum -c <(awk '$1!~/^#/ {print $3"  "$1}' manifests/required-inputs.tsv)
```

This step is not ritual. Three conclusions in this project were overturned, each because "the input wasn't the one I thought it was":
`font.bdl` judged "identical" by comparing path sets (the contents actually differed), a JP build installed with the CN language-table pin,
and a stale APK from the previous round getting `adb install`ed even though the build had failed. **The build is not bit-for-bit reproducible** (zip timestamps go into the package),
so identity can only be judged by the **assets inside the package** and the literals in the dex — never by a whole-package hash.

---

This repository holds code, tooling and documents only. The complete offline pack (two installable APKs plus the two
resource trees, about 13 GB) is not here and not on any public file host: it is derived third-party game content, and
publishing it is not ours to decide. A taker who needs it contacts the repository owner through the route in `NOTICE.md`
and receives it by invitation (collaborator access, or a release on a private repository). First move after receiving it:
`bash assemble_and_verify.sh --selftest`, then `bash assemble_and_verify.sh tree_cn.zip` to verify every volume.

## 1. From scratch to the home screen (shortest path, with the criterion for each step)

1. Stage the §0 inputs and verify their digests.
2. `apktool d -f -o game_decoded <official APK>`; create your own keystore, `export KS_PASS=...`.
3. Follow `docs/BUILD.md` §0 to replace the placeholder paths in the scripts with your directories, `export ADB_BIN=... SERIAL=...`.
4. Assemble the 16 assets in `stubapp/assets/`: 11 are produced by generators shipped here
   (`make_state` → `player.json`+`shop.json` / `make_shopgoods` / `make_pvpreward` / `make_stageawards` /
   `arena_state` → `arena.json`+`mail.json`+`task.json` / `gacha_state` / `make_mirror` / `gen_protocol_descriptor`),
   while the remaining 5 (`common.descriptor.bin` / `version.json` / `lab-account.json` / `startup-key.json` /
   `protocol-static.json`) are **not generated** - take them from the `assets/` of the `base.apk` installed on a
   device; the exact commands are in the source table of `docs/BUILD.md` §2.
   **Criterion**: `SeedHashTest` passes (it checks the pin with `Seed.java`'s own hash code, including a "flip one byte and it must fail" control).
5. `NO_INSTALL=1 PKG=cn bash tools/rebuild_relay.sh`.
   **Criterion**: the six gates built into the script — javac / d8 / asset sync / `SeedHashTest` / `pincheck` (once on the staged copy and once in-apk) /
   the port string baked into Unity containing 18080. Only an all-green run produces the APK.
6. `python tools/make_tree_zip.py` → `tree_cn.zip` (~7 GB / 12,718 entries / 1,040 banks).
   **Criterion**: entry count and sidecar lengths (`.bnk.hash` 40 bytes with no newline, `.bdl.hash` 41 bytes).
7. Install + deliver: `adb install -r` → push as `import.zip` → launch once →
   **this one line is the only criterion**: `logcat -d | grep "SEED tree installed"`. Don't count files (the import runs for minutes; a mid-run count is always low).
8. Cold-start acceptance: `bash tools/delivery_gate.sh`.
   **Criterion**: on reaching home, `P11 / P1024 / P120 / P60` are answered by their own handlers, while
   `P132 / P1014 / P1028` are only caught by the all-zero fallback (they do appear in the log but have **no handler** —
   see §2 and §4), and the exception count for the run is 0.
   The distinction matters: an unmapped protocol answers all zeros, so the page still opens and is simply empty.
9. Page-by-page sweep: `bash tools/sweep_cn.sh`.
   **Criterion**: for each page record "the protocol numbers this click actually triggered + client exception count", not screenshots.
10. JP package: `NO_INSTALL=1 PKG=jp bash tools/rebuild_relay.sh` +
    `python tools/make_tree_jp_from_cn.py` (same tree + per-entry restore of the 632 per-package deltas); both packages coexist on one device.

**The one forbidden move: never `adb shell pm clear`** — it destroys the delivered 7 GB tree and the save together, and recovery means re-pushing the whole tree.

---

## 2. Where things actually stand (playable surface / known gaps)

| Surface | Status |
| --- | --- |
| Login, handshake, home screen, 3D mascot girls (club-room seats) | Working |
| Main story stages (download → title → dialogue → battle → rewards → next act) | Playable end to end, all 1,566 stages at three stars |
| Shop: open page / purchase / charge / persistence | Working (`P120`/`P121` verified in practice) |
| Arena deployment and settlement scoring | Working (`P200`/`P204`, win +20 / lose +5 survives restarts) |
| Gacha | Working (`P1024` pools + cards written into the save) |
| Voice | Complete (1,040 banks, every one sha256-verified individually) |
| Simplified Chinese | Language table 30,687 rows, 0 kana; story dialogue is handled per package, ~30.8k rows are still Japanese |
| Spacetime Rift | Done up to the **real boss panel**; the "Challenge" button still sends no `P42` (see §3.1) |
| Top-up page (Holy Stone tiles) | Blank, **adjudicated unfixable from the data side** (see §4) |
| Friends / live ops / demon repel battles / event chapters, etc. | The client requests them, we **have no handlers**: P111 / P132 / P170 / P250 / P251 / P1014 / P1016 / P1028 / P1100 |

---

## 3. The first three things the incoming person should do

### 3.1 The Rift's Challenge button
The `P180..P186` family is already served per its measured semantics (`bout` = **uses consumed**, not remaining; `round` = floor reached;
the weekly cycle is in **seconds** anchored at this week's Monday 00:00), and the panel genuinely shows up. The sticking point: clicking "⚡5 Challenge" only emits the `P1021` heartbeat, never `P42`.
**Go investigate the challenge's preconditions**, stop guessing at `P180`'s fields: on site, the "card inventory" team-selection entry sits in a disabled state (clicking does nothing),
and `P186` (mirror team) is implemented but has no caller at all. One more lead: the panel states a recommended witch power of 99999999
while `player.power` is 99999 — a power gate may be swallowing the button outright.

### 3.2 The real fix for the Chinese font
Chinese currently falls back to the **system font**. Our `font.bdl` is 13.8 MB; the reference implementation is 140 MB
(9 CJK fonts each embedding Noto Sans CJK SC, 42,220 codepoints), and the Chinese we display touches 2,026 codepoints.
**What has to change is the bytes of the serialized file**: the UnityPy route of assigning `m_FontData` and then `save()` has been tried and does not work
(the output grew by 27.5 MB, and re-reading still shows the original size — that was just decompression, not replacement).

### 3.3 The remaining Chinese
Story dialogue lives in 631 story `.bdl` files as JSON TextAssets carrying `_language` (46,277 rows).
Reading gotcha: UnityPy's `m_Script` reads it back as `?`; you need `get_raw_data()` + `ensure_ascii` + `save('original')`.
Three other classes of residue are **not in the language table**, so stop looking in the table for them: strings hardcoded in Lua, text baked into UI art, subtitles burned into videos.

---

## 4. Doors already closed by measurement (do not walk them again)

| Route tried | Conclusion |
| --- | --- |
| Cracking the digest at the tail of Lua files | 1,239 assets × 340 framing/salt variants, zero hits. **Do not plan on editing Lua in place**, change everything from the data side |
| Reading client code | `luaData` decodes (it's essentially a `select * from X` loader); `scene`/`manager`/`ui` do not (printable ratio ~ 0.15). But **the data contract is readable**: `protocol.descriptor.bin` is a single `FileDescriptorProto` (not a Set), 407 messages |
| Finding an official Simplified Chinese package | JP-side CDNs and APK artifacts searched exhaustively — **it does not exist**; only 61 lines of CN residue |
| The top-up page | Tile content comes from Google Play Billing's native callbacks, and the 5 main tabs are fixed prefabs → no data-side solution |
| Swapping the font with UnityPy | See §3.2, ineffective |
| Bulk mining of terminology conflicts | The vast majority of sliding-window and substring hits are false positives. Only one check is trustworthy: **the same source term appearing in multiple written forms in the UI**; any rewrite must be scoped by the original JP term |
| Building real services for `pvp` / the notice board | The notice board's HTTPS URL is baked into the client; port derivation only works for HTTP-served assets |
| A rooted tablet | Unlocking the bootloader wipes data and unblocks nothing → not done |
| Using LDPlayer as the test device | x86 host + arm-only package requires translation, and LDPlayer's guest stacks a **second** layer of translation on top; already switched to AVD / real device |
| Judging feel by AVD timing | Import/unpack: AVD 441 s vs real device 8 s (the disk image is ~55 times slower). **Never treat AVD timing as real-device timing** |
| Deriving coordinates from `wm size` | `wm size` reports the natural orientation (1080x2400) while `input tap` works in the `rotation=1` landscape space; neither can be derived from the other |
| Blanket `chmod` | `0660` created by shell is unreadable to the app inside the app directory; `0660` written by the app itself is fine. Don't chmod in one sweep |
| Treating the host-side `device_files` mirror as ground truth | Stale for 4,679 files; `adb pull` also chokes on the app's own `0600` files |
| Using PNG byte counts / pixel diffs as page identity | Both unstable. Page identity = protocol numbers |

---

## 5. The adjudication toolbox (how this project validates anything)

- **Page identity is the protocol number.** Unmapped protocols get an all-zero response back; the page still renders, but with empty content.
- **Heartbeats are not evidence.** `P9000` and `P1021` fire every 60 seconds; "the log moved" proves nothing about a click landing.
- **Protocol map** (obtained by measurement, used as the oracle): `P11` home (includes `themes[].seats`) / `P120` shop / `P121` purchase /
  `P132` events / `P180..P186` the Rift / `P200` arena deploy / `P204` settlement / `P1001` terms consent /
  `P1024` gacha / `P42` battle start. (`P132`/`P1014`/`P1028` have only the all-zero fallback, not a handler.)
- **Exception counts beat screenshots**: enter each page once, `logcat -c` → operate → `logcat -d`, count `LuaException`.
  Never leave a persistent `logcat -v time` attached (a single sweep once wrote 2.1 GB).
- **One driver per device**: two drivers interleaving clicks won't fail loudly — they just write fake results like "the page opened but no protocol".
  Scripts guard with an atomic `mkdir` lock; killed background tasks leave live children behind, so the guard is the lock, not the task manager.
- **Frame classification needs reference images captured on the device itself**; the cut points are a property of the reference images (they vary per device), not of the game.
- **Validate the adjudication method itself**: before reporting a delta, publish the noise floor from repeated measurements of the same object; a comparison at shield saturation is not evidence;
  a guard's control group must be able to forge, by itself, the exact input it's meant to block; always-zero counters and dead selectors both pass silently.

---

## 6. Delivery form (what the "finished product" is)

```
game_relay_cn.apk    242,144,815 B   # CN package, thin APK (asset tree not included)
game_relay_jp.apk    240,334,383 B   # JP package
tree_cn.zip        7,003,552,761 B   # renamed to import.zip for delivery
tree_jp.zip        7,002,068,161 B
```

Fingerprints are in `manifests/delivery-sha1.txt` (computed by us, to confirm "which version actually got installed").
Delivery is just two things: **the thin APK + one `import.zip`**. The save is a single
`shared_prefs/lapis_state.xml`, keyspace `wal_` / `itm_` / `goods_` / `stage_` / `av_bind_` / `mir_` / `pvp_score`;
it survives `force-stop`, survives `adb install -r`, survives reboots; `pm clear` / uninstall / a signature change will kill it.

---

## 7. Things that vary by environment (these bite when reproducing across machines)

- **Drive letters and directories drift.** This machine moved the SDK and the AVDs from C: to E:, then to D:, within two weeks, and then the whole `D:` volume vanished
  (folded back into C:). Treat every absolute path in any document as **stale**, `stat` it before using it; this repo standardizes on placeholder paths.
- **`errno=1455 page file too small` has two causes**: a headless AVD eating all available commit memory (measured: the qemu process at 26.5 GB private),
  and the page file not shrinking back after being stretched (reboot required). First `Get-Process | Sort PrivateMemorySize64`,
  then `Get-CimInstance Win32_PageFileUsage` comparing `AllocatedBaseSize` against `CurrentUsage` — don't look at the disk at all.
- **Only one adb binary**: several adb instances fighting over the single server on port 5037 produces "the device suddenly disappeared" and "USB dropped".
- **The three AVD launch traps** (must go through `emulator.exe`, must set `ANDROID_AVD_HOME`, must set `ANDROID_SDK_ROOT`)
  and the modal `ImmersiveModeConfirmation` that appears on every fresh launch (click its measured bounds, don't use `keyevent 4`) are documented in `docs/BUILD.md` §8.
- **Changing `wm density` pops a "tap to restart" overlay** that thrashes the frame classifier back and forth while the screen has actually been on the home page the whole time — when it thrashes, look at the frames directly.
- **`keyevent 4` (back key) deadens dialog input in this game**, after which you're testing a wedged client; tap the on-screen X instead.

---

## 8. Cheat sheet: fields and rules newcomers ask about most

| Name | Measured semantics |
| --- | --- |
| `PlayerInst` / `Newbie` | These are the client's only two gates: balance and ownership read `PlayerInst` (paid currencies live in `diamondPay`; inserting a row into `items[]` is inert); feature unlocks read `Newbie` (level reached or a given stage cleared) |
| `GoodsPrice` / `CostValue` | The former only drives the badge display; the latter is what `GetCost`, the affordability check, and the actual charge use |
| `mir_*` state keys | `bout` = uses consumed (resets by local day), `round` = floor reached, `week` = this week's Monday 00:00 in **seconds** |
| `themes[].seats` | The roster source for the home-screen 3D characters (club room); an empty seat table → a null GameObject in `SceneMainStage` |
| `.bdl.hash` / `.bnk.hash` | Load gates, not metadata: 41 bytes vs 40 bytes (no newline). Missing or wrong length = the asset won't load |
| `EncryptKey` | This int32 in the manifest is a **header XOR**; nonzero + a plaintext UnityFS file = `Unable to read header from archive file` |
| `Unable to read header...` | Two root causes, one symptom: `EncryptKey` not zeroed, and the bundle that was already 0 bytes upstream. **Check the size before the key** |
| How missing assets manifest | A missing SoundBank is **total silence for the whole section** (no error, no prompt, no trace in the log); only a missing bundle produces exception text |
| `Seed` self-healing | The criterion is **file existence**, not digest match. So to get a fixed db onto the device, use "stage + `cp`" — don't recompile the APK |
| Server timestamps | Once `freshAt` / `EndTime` are in the past, `PageShop` self-clears mid-`OnEnter`; offline, always return `0` |
| Traceback line numbers | Must be translated through the bytecode line table (`proto.debuginfo.addr_to_line_map`); reading Lua line numbers directly points at the wrong function |

---

## 9. The boundaries of this project (read before taking over)

The code, scripts and documents we authored in this repository are open under the **MIT License** (see `LICENSE`):
any use is allowed, including closed-source commercial derivatives, with no further permission required. That grant
covers **only our own material** - never any third-party game content.

Interoperability research only on **a title already shut down on your own device**: no reopening of official services, no distributing game content,
no circumventing any paywall or anti-piracy mechanism still in force. All network requests converge on `127.0.0.1`;
the crash-report channel is original client behavior and was left untouched. Signing uses our own keystore (a signature change invalidates the original save — that's the trade-off).
The repo holds no keys, passwords, accounts, device serials, saves, and no game content or decompilation output —
this boundary is the precondition for this document existing publicly; keep holding it after you take over.
