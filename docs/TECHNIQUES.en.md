# Technical Document · Successful Paths and Evidence

This document records only **what a re-run can prove**. Every entry ships with its criterion (a log
line, a protocol id, a hash, a screenshot filename). Old conclusions that measurement overturned are
written into the "corrections", because those wrong turns are themselves the value of this document.

---

## 1. Overall strategy: never touch Lua — change the data and the network

The client has two integrity defenses, and they decided the technical route for the whole project:

1. **Lua carries a content-bound trailer**. Every `.lua` asset ends with a 32-bit hexadecimal check
   value; at load time `LuaResLoader:DecryptLuaFile` → MD5 comparison, and a mismatch gives
   `LuaException: MD5 VERIFY FAILED`.
   1,239 assets × 340 framings/salts, all tried, zero hits: **the algorithm is unknown, Lua cannot be
   edited in place**.
   Any "change one line of script" plan is void; it can only be solved from the data side, the asset
   side, the network side.
2. **The master data is runtime SQLite**. `luaData/*.lua` files are really loaders that run
   `select * from <table>`, so the behaviour switches are **data**, not code (e.g. `ShopFirstLook` in
   the `Config` table, `Guideshow.Popup`).

The route therefore settles into three legs:

| Leg | What changes | How integrity is passed |
| --- | --- | --- |
| Network | An in-device Java service stub answers the protocols | The client only verifies the session key, not the semantics of the content |
| Data | `master_data.db` / `master_data_lang.db` | SHA-1 is pinned in `Seed.java`; changing the DB means changing the pin in the same step |
| Assets | Repacked `.bdl` | 40-byte `.bdl.hash` sidecar + Hash/Size surgery on the manifest |

## 2. Protocol stubs

- 18 protocol branches dispatch by number inside `ProtobufCore.call`; the key numbers:
  `P11` player profile, `P120` shop list, `P121` purchase, `P132` event operation, `P200` arena
  deployment, `P204` arena settlement, `P1016` notice-read, `P1024` gacha.
- **Page identity can only be judged from the protocol**. `P9000` + `P1021` are a 60-second heartbeat;
  they fire whichever button you pressed, and using them as evidence that "the page opened successfully"
  yields a completely wrong conclusion.
- How the criterion is written: `logcat -c` → one tap → wait → count protocol numbers + `LuaException`
  count + screenshot. See `tools/drive2.sh`.

## 3. Save data and persistence

A single file `/data/data/com.klab.lapis/shared_prefs/lapis_state.xml` (`getSharedPreferences("lapis_state", 0)`
in `ProtobufCore.java`). Key families:

```
wal_*        货币（辉圣石/金币/体力）        goods_<id>   每个商品已购数量（→库存角标/售罄）
itm_*        获得的道具                      stage_*      关卡通关与星级
pvp_score    竞技场积分                       av_*         换装间（owned/mode/cur/bind/name）
```

- Nowhere in the entire codebase is there a `clear()` / `remove()` touching this store; the only
  `.delete()` is `Seed` removing its own temporary drop file.
- Only these lose the save: uninstall, `pm clear`, emulator instance reset, **an APK with a different
  signing key**. Same-signature `adb install -r` does not lose it.
- Client-side currency reads `PlayerInst` (seed field `diamondPay`); stuffing `P_*` type rows into
  `items[]` does nothing. Feature unlocks read `Newbie` (level or cleared stages).

## 4. The shop: a crash that looked unsolvable — the root cause was a server timestamp

**Symptom**: on the home page tap the shop → 7~8 crashes in a row, the shop UI never appears. The crash
stack is fixed:

```
LuaException: Object reference not set to an instance of an object.
  [C]: in function 'GetChildGameObject'
  PageShop.lua:555: in function 'InitScrollView'
  PageShop.lua:390: in function 'OnEnter'
  UIPanel.lua:216 DealWithEnter / :245 DealWithParentEnter / :231 DealWithEnter / :198 / :165
```

**Wrong turns taken (all overturned by measurement — don't walk them again)**:

1. Assumed some branch of `UpdateTag` was `SetActive(false)`-ing `SafeArea/Main/ScrollArea`
   (`ScrollAreaMain` and `ScrollAreaGrid` cache the same node). So the landing tab was changed from the
   data side: editing `TabIndex` on a Type 6 row, controlling the **emission order** of `shopTab`
   (`ShopManager.SetData` is last-write-wins: `listAllIndex[TabIndex]=Type`,
   `listAllType[Type]=TabIndex`). Three configurations — land on items, land on the exchange, let all
   six types land in the same safe slot — **the crash stack did not change by one character**.
2. Assumed the prefab was missing a node. Walked the tree with UnityPy: `PageShop/SafeArea/Main/ScrollArea`
   exists, `active=True`, unique in the whole tree; the device and host bundles are byte-for-byte
   identical. Ruled out.

**Real cause**: `OnUpdateSecond`. Each row's `freshAt` in `shop.json` is **the packing moment**, long since
expired; when `freshAt - server time <= 0` the client runs `Fire("CloseRecharge")` → `OnBack()` → `Close()` →
`UIPanel.Purge` sets `UIRootObject` to `nil`. `UpdateTag` guards that move with its own
`if self.closed then return end`, `OnEnter` does not, so the next statement — `GetChildGameObject` inside
`InitScrollView` — receives `nil` and throws a .NET null reference.

**Fix**: at the service stub's exit, force every row's `freshAt` to `0` (meaning "never refresh"; the JP
shop itself uses `freshAt = 0`).

**Side effect (known, optional to fix)**: daily-limited goods no longer restock the next day. If you want a
day rollover, return a **future** refresh point in `P1016`/`UpdateServerRefresh` and reset `goods_*` by date —
never return an expired timestamp.

## 5. Methodology: traceback line numbers must be translated through the bytecode line table

**The `.lua` line numbers from ljd decompilation are not the runtime line numbers** (this project stepped on
it twice; only the second time was it fully corrected). The line numbers in a runtime stack come from the
bytecode's own line table, so you must read the `.bdl` directly:

```python
env = UnityPy.load(bundle)
for o in env.objects:
    if o.type.name == 'TextAsset':
        raw = o.get_raw_data()          # 序列化对象的原始字节
        # proto.debuginfo.addr_to_line_map 给每条指令的原始行号
```

`tools/pfind.py` (which function covers which line range, plus its string constants), `tools/pseq.py`,
`tools/palign2.py` exist for exactly this. With them, "which statement crashed" is **read out**, not guessed.

## 6. Feeding assets: FUSE, permissions, and two illusions

- `adb push` onto an existing FUSE target **can delete the target and still report success**. The rule: push to
  `/data/local/tmp` first, then `cp` into `Android/data/.../files/`.
- A directory unpacked by `tar x` comes out `0770 shell`, so the app (the other bits) has no `x` → Unity reports
  `Unable to open archive file`. Fix: `find . -type d ! -perm -o=x -exec chmod o+x {} +`.
- **The optional-content downloader also needs write permission on the directory**: the client commits a download
  with `System.IO.File.Replace`, and adding only `o+x` throws `UnauthorizedAccessException` after the 77 MB has
  transferred — which the client reports as "the network connection was lost".
  Add write permission to the two directories `videos/` and `videos/optional/` only; no mass-chmod.
- `.bdl` must be paired with a `.bdl.hash` sidecar holding a 40-byte uppercase SHA-1; file permission `0660` is
  not what blocks it, don't go touching it.
- The manifest is AES-CBC'd gzip; swapping a bundle means changing its Hash and its Size together
  (`tools/manifest_repoint.py`). **ShortHash is not content-derived — leave it alone.** The story bundles are not
  in the manifest at all; only the `.bdl.hash` needs replacing.
- When the manifest's `EncryptKey` is non-zero but the file is plaintext UnityFS, it reports
  `Unable to read header from archive file` — zeroing that int32 in place was the root cause of every card image
  failing.

## 7. Where story text actually lives, and repacking

- Stage dialogue is **not in the language table**: 631 `resources/story/*_scene.bdl` files each carry one
  `_language` TextAsset, which is `{"Key":[...],"Value":[...]}` JSON.
  46,277 lines in total, of which roughly 30.8k lines are still Japanese.
- **UnityPy's `m_Script` is lossy on this batch of assets**: it decodes as UTF-8 while the payload is Shift-JIS,
  so every CJK character becomes `?`. The only reliable read is to cut the JSON document out of
  `obj.get_raw_data()`.
  (This trap nearly let the whole corpus into the translation pipeline as mojibake.)
- Chinese does not fit into Shift-JIS. On write-back, output the JSON with `ensure_ascii=True` as `\uXXXX` escapes:
  the bytes are pure ASCII, they decode to the same Chinese string under utf-8/shift_jis/cp932, and the encoding
  problem disappears outright.
- Saving must use `env.file.save('original')` to keep the original compression, otherwise the size grows 6×
  (223 KB → 1.37 MB).

## 8. The Simplified Chinese pipeline

- Installed language table: 30,687 rows + `Terms` 8 rows, codepoint-level 0 kana, 0 U+FFFD.
- **Glyph gate**: the client font is not the list in `glyphset.txt` (the Japanese source itself contains 232
  characters outside that list and they display fine).
  The criterion is `glyphset ∪ ASCII ∪ the Japanese source characters of that row`. Anything outside becomes a
  tofu box.
  This gate actually caught 27 cases of "wording is pretty, glyph is missing" (瑕／淇／噗／缥／萦／萃／哒／诶／彗／沁／痣／咻／嗖／×).
- Delivery format: the AI workflow returns raw `id<TAB>translated text`, and long entries spill orphan lines. The
  rule is to merge them back into the previous entry first, then fold the line breaks
  (a language-table value should never contain a newline).
- Consistency: give the translation agents a **locked short-line table** extracted from the already-delivered
  corpus (JP→CN, 4,201 entries) + the glossary + the glyph list,
  instead of making them read the full files.

## 9. Verification discipline (the most valuable entry in this document)

- **Console mojibake does not mean the data is broken**. Confirm with a controlled experiment first (the same data
  through the Read tool / written to a file and read back), then draw the conclusion. This project twice mistook a
  display problem for a data problem.
- A criterion must be able to forge its own input: a counter that is permanently 0, a log line emitted on a beat —
  neither counts as evidence.
- Report numbers with a noise floor: the delta of repeated measurements on the same object, otherwise "improved by
  3" means nothing.
- Before saying "some cause is ruled out", confirm that what you ruled out is that cause's shape on this path.
- Strip the scaffolding before delivery: the diagnostic file gate, SQL/RX/XE probes, `hide_error_dialogs`,
  `javax.net.debug`,
  REQDIAG/SIGRAW/MemDump style temporary output — all of it removed from the build.

## 10. Page identity is the protocol number, not the screenshot

An unmapped protocol answers with an all-zero response, and the page **still renders** — the content is just
empty. So "the page opened" does not mean "the page has data". A scan result must record two things: which
protocol number this click actually fired, and how many exceptions the client reported during that window.

- `P9000` and `P1021` are the 60-second heartbeat. The trap I walked into was "pressed the button → the log
  did move → judged pass", and those two lines were nothing but heartbeat. Any "did the click take effect"
  verdict has to be able to exclude the heartbeat.
- On an art card the clickable area is usually not at the text center: measured, the card's hit box sits
  **about 40 px right of the label center**.
- Drive the cold start from the stub's own log instead of sleeping a fixed duration: the version that slept
  200 s and then tapped blind — on the second restart the client was actually still on the title screen, and
  the back half of the scan report was describing frames it never reached.

## 11. The client has exactly two gates: `PlayerInst` and `Newbie`

- Currency balances and owned items all read `PlayerInst`. Pushing a row into `items[]` is **inert** — the UI
  does not change. A paid currency like 辉圣石 has to be seeded into `diamondPay`.
- Feature unlocks read `Newbie`: the condition shape is "level reached" or "a stage cleared". So when "a page
  won't open", check `Newbie` first — do not guess at server-side permission fields.
- Prices come in two columns with different jobs: `GoodsPrice` is only the corner badge, `CostValue` is what
  `GetCost` / the affordability check / the deduction use. When the two disagree, the client will
  "show 1980, deduct 0" — or the reverse.

## 12. The master data is SQLite at runtime, so behavior is fixable on the data side

`luaData/*.lua` is not logic, it is a loader: what actually runs is `select * from X`. So behavior switches
(is a page available, is a feature unlocked) are overwhelmingly a **data-side** fix — no code segment needs
touching.

`Seed`'s self-heal criterion is **file existence**, not digest match. So to get a fixed `master_data.db` onto
the device, the right move is "drop it in staging + `cp` into the app directory", not rebuilding the APK —
a rebuild restarts the whole pin chain.

## 13. Server timestamps make a panel purge itself

`PageShop` purges itself mid-`OnEnter` when `freshAt` / `EndTime` have already expired. The symptom is
"tap in, it flashes, it's gone, and no error anywhere". On an offline server both fields answer `0`, always.
Same family: client traceback line numbers **must be translated through the bytecode line table** — reading
the Lua line numbers directly points you at a different function.

## 14. Sidecars, and "missing is completely silent"

The 40-byte digest file next to a `.bdl` / `.bnk` is a load gate, not metadata. Two measured rules:
`.bnk.hash` = exactly 40 bytes of uppercase SHA-1, **no** newline; `.bdl.hash` = **41 bytes** (newline
included). "Unifying" the two stops resources from loading outright.

Missing assets fail in layers: a missing SoundBank is **total silence** (no error, no popup, no trace in the
log); only a missing bundle produces `Unable to read header from archive file`. And one symptom string has
two root causes: the manifest's `EncryptKey` is a header XOR (a non-zero key + a plaintext UnityFS file gives
exactly this symptom), and the upstream bundle that was 0 bytes to begin with — so **check the size first,
then the key**.

## 15. Proving "the copy that ran is the copy I changed"

After a change, prove the artifact contains the change before reporting results or starting measurements.
Three different traps I walked into:

1. Writes can fail silently (the tool reports success, the file content never changed). `grep -c` the target
   identifier and read it back **from the file itself**.
2. I installed after a failed build: the command was written as `build > log; install` on consecutive lines,
   the build died, install ran anyway, so the previous round's old APK went onto the device and got tested as
   the new package — and `adb` even answered `Install command complete`. **Install must chain on build
   success** (`build && install && test`), and after installing compare the in-package asset digests and the
   new literals in the dex — `Install command complete` proves a package got installed, not that it was this
   package.
3. I measured on the stale state right after editing a script, got "identical before and after", and on that
   basis killed the correct solution.

The matching build property: builds are **not bit-for-bit reproducible** (zip timestamps go into the
package), so the whole-package hash cannot serve as identity — only in-package assets can be compared.

## 16. Verify the judgment method itself first

- Before using a delta to call something "an improvement", state the **noise floor** from repeated
  measurements of the same object; the delta of two samples of the same frame is that threshold.
- A saturated mask comparison is not evidence (a whole-screen difference = nothing was resolved).
- When the optimum sits on the search boundary, it falsifies the current model — it is not "an answer found".
- A guard's control group must be able to **forge the very input class it blocks**; "the old version would
  have blocked this" is not a control.
- A permanently-0 counter, a log line emitted on the beat, a dead CSS selector — they all pass quietly.
