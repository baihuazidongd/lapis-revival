# Lapis Re:LiGHTs Standalone Revival Project (宝石幻想 / ラピスリライツ)

A **local-compatibility and standalone (offline) study** of the already discontinued Unity mobile game 宝石幻想：光芒重现 (`com.klab.lapis`
1.5.0, KLab / KADOKAWA, servers shut down 2022-10-31). The goal is to take a client that originally required a network connection and, on
one machine with no network at all, reach the main menu, fight through stage battles, use the shop and the arena, and turn the UI and text into Simplified Chinese.

This repository holds **code, tools and documentation only**, and no game content whatsoever. It is the reproduction recipe for people who
already own the client and the assets themselves; it is not an installer and not an official server.

## What works today (verified on real hardware: Android 12 tablet 2000x3200 and an x86_64 AVD)

| What originally required the network | Status | Acceptance criterion (rerunnable on the spot) |
| --- | --- | --- |
| Login / handshake / main menu | Works | Cold start reaches the main room with no `LuaException` |
| Stage battles (main story stages) | Playable from start to finish | Download -> title card -> dialogue -> battle -> rewards -> next act, all 1,566 stages at three stars |
| Shop (purchasing department) | Opens, buys, persists | `P120` returns the full UI; `P121 goods=100012 x1 bought=1`; balance debited per `CostValue` |
| Arena | Works | `P200` to enter battle, `P204` to score the settlement; win +20 / loss +5 readable the next time |
| Gacha (summon) | Works | `P1024` banner pool, dealt cards written into the save |
| Home 3D mascot / club room "interaction" | Works | The characters in `SceneMainStage` come from `PBGameInfo.currentTheme` + `P11.themes[].seats`; with an empty seat table that slot is a null GameObject |
| Spacetime rift (Mirrors) | Reached the real Boss panel | The `P180..P186` family is served with measured semantics (`round` = floor reached, `bout` = uses spent, weekly cycle in seconds); the challenge button still does not go through (see `docs/BUILD.md` §10) |
| Voice | Completed | 1,040 SoundBanks in the tree (the original device carried only 129, the rest are optional CDN downloads upstream, so offline **the whole thing goes silent and does not even error**) |
| Simplified Chinese | Language table 30,687 rows, 0 kana; story dialogue lives inside the asset bundles and is processed bundle by bundle | Codepoint-level audit with `tools/cn_audit.py` |
| Two packages side by side | CN and JP packages coexist on one device | CN keeps `com.klab.lapis` to preserve the original save, JP uses `com.klab.lapis.jp`; the asset service derives ports 18080 / 18090 from the package |
| Save data | Survives reboots and reinstalls | Balance / inventory unchanged after `force-stop` and `adb install -r` |

## The architecture in one sentence

Not a single line of Lua is changed and no game logic is re-signed; instead **a fake server is placed on the device**:

```
Client ──gRPC/HTTPS──> TlsProxy(127.0.0.1) ──> HttpFileServer / GrpcApi  (Java, installed inside the APK)
                                              │
                       Protocol stub ProtobufCore ────  28 protocol branches (P11/P120/P121/P132/P180..186/P200/P204/P1024…)
                       SharedPreferences save ─┘  lapis_state.xml: wal_/itm_/goods_/stage_/pvp_score/av_bind_/mir_*
                       Importer (ImporterActivity) ──  unpacks the delivered import.zip into the asset tree on the device
```

- `stubapp/`: the Android-side service stub (Java). `ProtobufCore` assembles protobuf responses by protocol number (the schema comes
  from `protocol.descriptor.bin` inside the APK, messages built on the fly with `DynamicMessage`), `Seed` pins the bundled database with
  SHA-1, and `HttpFileServer`/`TlsProxy` point the client's domains at `127.0.0.1`.
- `tools/`: the scripts that produce the data above (per-package flag flipping, state generation, database rewriting, asset tree zipping, provisioning, verification).
- `manifests/`: expected-digest manifests. The game content is not here; recipients check it against the assets they already hold.

## Build and install (no game data included; you supply the client and the assets yourself)

```bash
export KS_PASS=<password of your own keystore> SERIAL=<serial listed by adb devices>
NO_INSTALL=1 PKG=cn bash tools/rebuild_relay.sh   # service stub -> dex -> apktool -> zipalign -> apksigner
python tools/make_tree_zip.py                     # the 7 GB asset tree (device manifest + override sources + SoundBank completion)
bash tools/provision_files.sh                     # provisioning
bash tools/delivery_gate.sh                       # on-device acceptance: cold start + per-screen protocol-number criteria
```

The complete order, the criterion for every step, why all four per-package flips must happen before `javac`, why the sidecar is 40 bytes for
`.bnk` but 41 bytes for `.bdl`, the two causes of `errno=1455`, and the open items: **see `docs/BUILD.md`**.

## What this repository deliberately does not contain

- any `.bdl` / `.assetbundle` / audio / image / video / main database / language table content;
- decompiled client Lua, IL2CPP dumps, smali;
- build artifacts (the roughly 242 MB APK, the roughly 7 GB tree); GitHub could not host that scale either;
- keys, keystores, passwords, accounts, device serial numbers, save files.

The reason is in `NOTICE.md`: the game content is copyrighted by KLab / KADOKAWA / Shengqu, so this repository keeps only the code we wrote ourselves and the derivation behind it.

## Documentation

| File | Contents |
| --- | --- |
| `docs/BUILD.md` | **Build manual**: the path that works, commands and order, list of pitfalls, measured timings, open items (zh/en/ja) |
| `docs/TECHNIQUES.md` | Technical document: determination methods, field semantics and failure cases (zh/en/ja) |
| `docs/GAME.md` | Game introduction: what kind of game this is and how its systems look (zh/en/ja) |
| `README.ja.md` / `README.en.md` | Japanese / English versions of this file |

## Legal and ethical boundary

Interoperability research only on **a work that is already shut down, on your own device**. No reopening of official services, no distributing
game content, no circumventing any payment or anti-piracy mechanism still in force. All network requests are funnelled to `127.0.0.1`; the crash-reporting channel is original client behaviour and was left unchanged.
