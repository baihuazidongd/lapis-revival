# ビルドマニュアル：ゼロから、実際に遊べる端末一台まで

このドキュメントは 3 つのことをする：**成功パス**（各ステップをその場で測る判定基準。回顧談ではない）、**ビルド方法**（コマンドと順序）、
**落とし穴リスト**（すべての落とし穴に、当時それが出した偽の症状を明記する。書かないと、次回はまったく別の問題として調べさせられる）。

前提：手元に公式クライアント `com.klab.lapis` 1.5.0 の APK と、そのリソースアーカイブがあること。このリポジトリにはそれらも、
そこから派生したバイナリ類も置かない。以下のすべての「入力」は、あなた自身のコピーを指す。

---

## 0. ディレクトリの規約

スクリプト内のパス定数はすべて**プレースホルダ**であり、誰か一人のマシンのレイアウトではない：

| プレースホルダ | 意味 | 中身 |
| --- | --- | --- |
| `C:/lapisbuild` | ビルドルート | `game_decoded/`（デコード済み APK ツリー）、`stubapp/`（スタブのソースと成果物）、`tools/`（apktool、JDK）、`delivery/`（検収成果物） |
| `E:/lapis` | ワークスペース | オリジナル APK、上流リソースアーカイブ、ホスト側リソースミラー `revival/local/`、デプロイ用オーバーレイソース `staging/overlay_src/`、納品セット `build_full/` |
| `C:/Android/Sdk` | Android SDK | `build-tools/34.0.0`、`platforms/android-34/android.jar`、`platform-tools/adb.exe`、`cmdline-tools/latest`、`system-images/` |
| `E:/ref-sample` | 自分で用意する対照サンプル | コメントの中にしか現れない。あるフィールド／アセットが「本来どうあるべきか」を説明するためのもので、このリポジトリには含まれない |
| `E:/android-avd` | AVD ホームディレクトリ | `ANDROID_AVD_HOME` がここを指す |

一括で書き換える：

```bash
cd lapis-revival
grep -rl 'C:/lapisbuild' tools | xargs sed -i 's#C:/lapisbuild#/your/build/root#g'
grep -rl 'E:/lapis'       tools | xargs sed -i 's#E:/lapis#/your/workspace#g'
grep -rl 'C:/Android/Sdk' tools | xargs sed -i 's#C:/Android/Sdk#/your/android-sdk#g'
```

3 つの環境変数は必ず自分で設定する。リポジトリ側に値はない：

| 変数 | 用途 |
| --- | --- |
| `KS_PASS` | 自分の keystore のパスワード（§1 参照） |
| `ADB_BIN` | どの adb を使うか。**1 本だけに限定すること**。§7 参照 |
| `SERIAL` | `adb devices` に出てくるターゲット端末 |

ツールチェーン：JDK（コンパイルは 17 以降なら何でも可。スクリプトは `-encoding UTF-8 -nowarn` 前提で書かれている）、`apktool`、
`build-tools 34.0.0`（`zipalign` + `apksigner` + `lib/d8.jar`）、Python 3.13、
`android-34 google_apis x86_64` システムイメージ（エミュレータを使う場合のみ必要）。

---

## 1. 一度だけの準備

```bash
# 1) 基盤 APK をデコード
apktool d -f -o game_decoded <你的官方 APK>

# 2) 自分の keystore を生成（他人のを流用しないこと）
keytool -genkeypair -keystore stubapp/lapis.keystore -alias lapis \
  -keyalg RSA -keysize 2048 -validity 10000 \
  -storepass "$KS_PASS" -keypass "$KS_PASS" -dname "CN=lapis-lab"

# 3) 依存 jar を stubapp/libs/ に置く（protobuf-java、protobuf-java-util など。リポジトリには同梱されない）
```

**なぜ署名の変更が必須か**：同一パッケージ名での再インストールには署名の一致が必要だが、元パッケージの署名は入手できない。
署名を替えることは元のライブサーバーとの互換を捨てることになる——オフライン化には実害ゼロ——が、
**署名を替えると古いセーブデータは無効になる**。そのため、オンライン版をすでにインストール済みのユーザーは、
アップグレード前に必ず `shared_prefs` を外部へ書き出しておく必要がある（詳細は §6 の生存ルール参照）。

---

## 2. ビルド（パッケージごとに 1 回実行）

```bash
cd /your/build/root
NO_INSTALL=1 PKG=cn bash tools/rebuild_relay.sh     # -> game_relay.apk
NO_INSTALL=1 PKG=jp bash tools/rebuild_relay.sh     # -> game_relay_jp.apk
```

| スイッチ | デフォルト | 作用 |
| --- | --- | --- |
| `PKG` | `cn` | `cn` = `com.klab.lapis`（元セーブを保持）、`jp` = `com.klab.lapis.jp`。2 パッケージは同一端末に共存可 |
| `NO_INSTALL=1` | インストールする | ビルドのみ、端末への導入なし |
| `BUNDLE_TREE=1` | オフ | 数 GB のリソースツリーごと APK に押し込む。**普段は絶対にやらない**。納品形態は「薄い APK + `import.zip` 一本」 |

成果物は約 242 MB（クライアント本体を含み、リソースツリーを含まない）。

### スクリプト内部の順序（判定基準はこの節にすべてある）

1. **パッケージごとに反転させる 4 か所は、必ず `javac` より前に行う。**
   `pkg_manifest.py`（パッケージ名／権限／ラベル）→ `pkg_lang.py`（言語テーブルのダイジェスト pin）→ `pkg_port.py`
   （CN ベースポート 18080 / JP 18090）→ `pkg_story.py`（CN 訳文ストーリーライブラリ vs オリジナル JP ライブラリ）。
   理由は `Seed.java` の pin が **`classes3.dex` にコンパイルされて焼き込まれる**定数だから。反転をコンパイル後にやると、
   「パッケージには JP のテーブルが入っているのに、dex は CN のダイジェストで検証する」という状態になる。結果はビルド中はエラーにならず、
   コールドスタート時に `SEED refused`、Config テーブル空、UI が未ローカライズ状態へ戻る、として現れる。
   スクリプト末尾の `trap` が 4 か所すべてを CN に戻すので、中断してもツリーが間違ったアイデンティティのまま残ることはない——これが
   **同一ソースツリーで異なる PKG を続けて実行しても安全**である根拠。
2. `javac` → `jar` → `java -Xmx1024m ... com.android.tools.r8.D8` → `classes.dex` / `classes2.dex` を
   `game_decoded/classes3.dex` / `classes4.dex` として書き出す。
   `-Xmx` を明示的に固定しているのは、d8 のデフォルトが物理メモリの割合で確保を要求し、メモリが逼迫したホストでは拒否されるため（§8 参照）。
3. **アセット同期リスト**（`rebuild_relay.sh` のあの `for a in ...`）：
   `protocol.descriptor.bin common.descriptor.bin version.json player.json shop.json shopgoods.json
   pvpreward.json stageawards.json arena.json mail.json task.json gacha.json mirror.json
   lab-account.json startup-key.json protocol-static.json`
   新アセットは**必ずこの 1 行にも同時に追加する**こと。でないと APK に入りせず、実行時の症状は「そのページが空白でリクエストゼロ」だけになる。
4. `SeedHashTest`：ホスト上で `Seed.java` 自身のハッシュコードを実行し、データベースごとに pin を突き合わせる。コントロールが 2 つ付属——
   サイドカーの形状（40 文字の大文字 16 進、改行なし）と「1 バイト変えたら必ず失敗すること」。
5. `patch_il2cpp.py`、`patch_klb_func.py`：後者は毎回オリジナルバックアップから `libklbsqlite3.so` を
   **再構築**する（`sqlite3_open_v2` の vfs 引数書き換え + `klb_vfs.xOpen` で平文ファイル名を通す）。
   その場でパッチせずバックアップから再構築するのは、かつて同じ穴に住んでいた診断コードを帰らせないため——あのコードは CN パッケージの
   ログパスをハードコードしていて、JP パッケージでは全部失敗した挙句にバンドル同梱の errno でエラーを保存し、結果 JP クライアントは
   タイトル画面より前に SIGSEGV していた。
6. `pincheck.sh`（ステージング状態）→ `apktool b` → `zipalign -f -p 4` → `apksigner`。
7. **成果物の再検証 2 段**（このステップは省けない。「ツリーが正しく反転した」≠「パッケージ内に正しく反転したバイトが入っている」）：
   `pincheck.sh --apk --pins pins_at_build.txt` でビルド時スナップショットと比較、
   さらに APK から `assets/bin/Data/9bdd7e35b810546fdbe3f8fa3ec1fd55` を展開し、Unity に焼き込まれたエンドポイント文字列に
   18080（cn）/ 18090（jp）が含まれることをアサートする。

### 同梱する 16 アセットの入手元（`rebuild_relay.sh` の同期リスト）

| アセット | 入手元 | 説明 |
| --- | --- | --- |
| `protocol.descriptor.bin` | `gen_protocol_descriptor.py` | クライアント Lua 内のスキーマ宣言（**`FileDescriptorProto` 単体、Set ではない**、407 message）。スタブは `DynamicMessage` でこれに従いレスポンスを組み立て、フィールド名も番号もすべてここにある |
| `player.json` | `make_state.py` | マスタデータ + セーブ状態：ガチャプール、ステージ星評価、ウォレット、クラブ、ルーム座席 |
| `shop.json` | `make_state.py` | ショップ画面の構造（`player.json` と同一スクリプト） |
| `shopgoods.json` | `make_shopgoods.py` | `P121` の課金／付与／購入制限テーブル |
| `pvpreward.json` | `make_pvpreward.py` | アリーナ戦後の報酬 |
| `stageawards.json` | `make_stageawards.py` | ステージ報酬 |
| `arena.json` | `arena_state.py` | `P200`/`P203` のシーズンと対戦相手リスト。各 id は `master_data.db` から読み出し相互照合しており、照合できなければ解決不能な id を出さず例外を上げる |
| `mail.json` | `arena_state.py` | `P80` のメールと報酬 |
| `task.json` | `arena_state.py` | `P60` のタスク（書き込む各タスク id は `TaskData` に存在必須） |
| `gacha.json` | `gacha_state.py` | `P1024` のガチャプール |
| `mirror.json` | `make_mirror.py` | 時空の狭間 `P180..P186`：`ClubMirror` / `ClubMirrorEvent` / `Config` / `DropGroup` |
| `common.descriptor.bin` | **自前生成なし**：端末にインストール済みの `base.apk` の `assets/` から取る | クライアント同梱 |
| `version.json` | 同上 | クライアント同梱 |
| `lab-account.json` | 同上 | クライアント設定。ゲーム内容にあたる → リポジトリに含めない |
| `startup-key.json` | 同上 | 同上 |
| `protocol-static.json` | 同上 | 同上 |
| `manifest.xml` | 同じく `base.apk` の `assets/` から | クライアント同梱の bundle 一覧。同期リストには**入らない**（我々が同梱しない）が、リソース解決が依存する |

上の生成スクリプトの入力は、自分が持つ `master_data.db` / `master_data_lang.db` だけです（§0 参照）。
つまりマスタデータを変えたら対応スクリプトを再実行しないと、APK 内のアセットと DB がズレます。

末尾の 5 個（クライアント同梱ほう）の取り方：

```bash
adb -s "$SERIAL" shell pm path com.klab.lapis          # /data/app/.../base.apk を返す
adb -s "$SERIAL" pull <上のパス> base.apk
unzip -o base.apk "assets/common.descriptor.bin" "assets/version.json" \
  "assets/lab-account.json" "assets/startup-key.json" "assets/protocol-static.json"
cp assets/* ../../stubapp/assets/                       # ビルドルートのアセットDirへ
```

この 5 個には**ダイジェスト門がありません**：`Seed.java` がピン留めしているのは `master_data.db` と
`master_data_lang.db` だけ（値は `manifests/pinned-assets.tsv`。この 2 ファイル自体は
`manifests/required-inputs.tsv` で照合）。よって判定は挙動でしかできません：クライアントは冷起動時に
この 5 個を読み、間違ったものを置くとタイトル画面で固まるか、トップ画面の `Config` テーブルが空になります。
判据はやはりプロトコル番号 + 例外カウント（§7）。

---

## 3. リソースツリーのパック（納品形態のもう一方の半分）

```bash
python tools/make_tree_zip.py         # -> staging/tree_cn.zip
python tools/make_tree_jp_from_cn.py  # -> staging/tree_jp.zip
```

- エントリは**デバイス実測マニフェスト**（実機から数え上げたパス一覧）で選別し、その上に `staging/overlay_src/` の自分たちで変更したファイルを重ねる。
  マニフェストは飾りではない：ツリー丸ごとパックすると、デバイスが決して読まないものまで入り、逆にデバイス上にしか存在しないコピーを漏らす。
- JP ツリーは一から作り直さない。「CN ツリー + パッケージ差分をエントリごとに復元」（632 件：CN 訳文ストーリーバンドルと言語テーブル）、
  差分バイトは古い JP アーカイブから 1 件ずつコピーで戻し、すべて `ZIP_STORED` + `force_zip64=True`。
- **SoundBanks 補完パート**：デバイスには本来 129/1,021 の bank しかなかった。残りは上流では任意の CDN ダウンロード扱い
  （`DownloadConfig.SoundBankName` → `VOX_CHR_*` / `VOX_EVT_*`）。オフラインに CDN は無いので、これらのキャラボイスは
  **全編無音**——エラーも出ず、ダイアログも出ず、ログにも残らない。補完後は 1,040。
- **サイドカーのルールは型によって違う。「統一」しにいかないこと**：`.bnk.hash` = ちょうど 40 バイトの大文字 SHA-1、改行なし、
  `.bdl.hash` = **41 バイト**（改行あり）。サイドカー欠落か長さ不一致なら、アセットはそのままロードされない。
- `SoundBanks/SoundBanks/` のようなネストした重複ディレクトリは除外（実測 484 MB が純粋な重複）。
- ツリー内に 1 個のゼロバイト bundle がある（上流が空だったもの、`.../pickupray4/bg.bdl`）。その症状文字列は「EncryptKey ヘッダの XOR が
  クリアされていない」とまったく同じ（`Unable to read header from archive file`）なので、**鍵を見る前にサイズを見る**。

---

## 4. 納品

```bash
python tools/ship_checksums.py     # build_full/ へコピー -> ストリーミングで SHA-1 計算 -> CHECKSUMS.txt を書き換え -> 読み戻し検証
```

納品物 4 点（`manifests/delivery-sha1.txt` はこの版の指紋）：APK 2 本 + ツリー 2 本、
合計約 14 GB。**6 GB 級のファイルを `read()` してはいけない**——実際に一度 `MemoryError` を踏んでいるので、全部 4 MB チャンクのストリーミング。
`CHECKSUMS.txt` のヘッダ 3 行はバイト単位で動かさず、書き終えたら必ず読み戻して行ごとに再計算する。

ビルドは**ビット単位では再現しない**（zip のタイムスタンプがパッケージに入る）。なので検証は**パッケージ内のアセット**同士比べることしかでき、
パッケージ全体のハッシュは比較対象にならない。これは「端末に入ったのは本当に今ビルドしたあれか」を測る唯一の判定基準でもある：`adb install` が
`Install command complete` を返すのは「いずれかのパッケージが入った」ことしか証明せず、「このパッケージ」は証明しない。
端末への導入はビルドと**同一の `&&` チェーン**に載せ、事後に `assets/player.json` の sha1 と dex 内の新規リテラルを比較する。

---

## 5. デプロイ（新規インストール時に 1 回だけ）

```bash
adb -s "$SERIAL" install -r /your/build/root/game_relay.apk
cp /your/workspace/build_full/tree_cn.zip /tmp/import.zip
adb -s "$SERIAL" push /tmp/import.zip /sdcard/Android/data/com.klab.lapis/files/import.zip
adb -s "$SERIAL" shell am start -n com.klab.lapis/com.klab.jackpot.notification.FirebaseMessagingActivity
# 完了判定はこの 1 行だけ見る。ファイル数を数えてはいけない：
adb -s "$SERIAL" logcat -d | grep "SEED tree installed"
```

- **絶対に `pm clear` してはいけない**：デプロイ済みツリーごと全部破壊される。作り直すには 7 GB をもう一度 push し直す必要がある。
- push の途中で読み取りに入られるのを見たことがある。`SEED tree fatal: unexpected EOF` が出る。push の完了を待ってから起動すればいい。
- デプロイ用アーカイブはダイジェストゲートの対象外で、インポート成功後はアプリ自身がそれを削除する。
- 再現する落とし穴 2 つ：`adb push` は FUSE の書き込み先だと同名の既存ファイルを消すことがある。`tar x` でツリーを敷くと
  ディレクトリが `0770` になり、アプリが読めなくなる。だから大きなツリーは `/data/local/tmp`（ext4）+ tar を通し、権限は別途調整する。
- ディスクに落ちたファイルの**所有者**が、アプリから読めるかを決める：shell が作った `0660` はアプリのディレクトリ内だとアプリは読めない。
  一方、アプリ自身が書いた `0660` は問題ない。

---

## 6. セーブデータの生存ルール（「アップグレード」可否を決める）

生存：`force-stop`、`adb install -r`（同一署名）、端末再起動、AVD のコールドリスタート（7 GB ツリーでも耐える）。
失効：`pm clear`、アンインストールからの再インストール、**署名の差し替え**。
セーブ本体は `shared_prefs/lapis_state.xml` 単一ファイルで、キーは `wal_1` / `itm_<id>` / `goods_<id>` /
`stage_<id>` / `av_bind_<id>` / `mir_*` の形。

---

## 7. 検収

- ホーム基準画像は自動では生成されません：`tools/set_home_ref.sh` は候補フレームを 1 枚出すだけで、
  **目視で確認してから** `cp home_cand.png home_ref.png` します。`delivery_gate.sh` は `home_ref.png` が
  無い場合、独自の基準を捏造せず FATAL で終了します。

```bash
bash tools/delivery_gate.sh      # コールドスタート + ページごとの判定基準
bash tools/sweep_cn.sh           # ホームの入口からページごとにスキャン：そのページで実際にどのプロトコル番号が発火し、クライアントが何回例外を出したか
python tools/boot_state.py <png> --home <本机自采首页> --cut <切点>   # フレーム分類
```

**ページの識別はプロトコル番号だけで判断し、スクリーンショットでは判断しない**：未マッピングのプロトコルは全ゼロのレスポンスを返されるが、
ページ自体はいつも通り描画される——中身が空のままで。`P9000` と `P1021` は 60 秒心拍で、
**「自分のクリックが届いた」証拠にしてはいけない**——はめられた形は「ボタンをクリック → ログが動いた → 合格と判定」だった。あの 2 行はただの心拍だった。

他の判定基準の詳細：
- コールドスタートはスタブ自身のログ駆動で、固定 sleep には頼らない。初期版は 200 s 眠ってから「タイトル／同意」を手当たり次第にタップしていた。
  2 回目の再起動時、クライアントは実際まだタイトルページにいて、スキャンレポート後半のフレームにはそもそも到達していなかった。
- logcat は「ページごとに先に `-c`、それから `-d`」を使う。常駐ストリームは張らないこと：`logcat -v time` の単発実行 1 回で 2.1 GB 書き込んだことがある。
- 1 台の端末のドライバーは 1 人だけ。ドライバーが 2 人だと大きなエラーは何も出ず、クリックが交互に混ざり、相手の途中ページまで同一の結果ファイルに
  書き込む。読み手には「ページは開いたのにプロトコル無し」に見える。スクリプトは `mkdir` のアトミックロックでこれを弾くが、殺されたバックグラウンドタスクは
  生存した子プロセスを残す。なので**見張り役はロックであり、タスクマネージャではない**。
- ページごとのスキャン前、テスト対象端末をキャリブレーション解像度に固定する：`wm size 1280x720` + `wm density 240`、スキャン後に
  `wm size reset` + `wm density reset`。2 系のキャリブレーション形状（エミュレータ 2400x1080、タブレット 2000x3200）は
  **アスペクト比が違う**ので、ボタン表を写像できる単一のスケール係数など存在しない。
  また `wm density` を変えると Android が「タップで再起動」のオーバーレイを出して、画面は実際とっくにホームなのに、
  フレーム分類器を title/campaign/unknown の間で往復させる——**分類器が震えたら、直接フレームを見ること**。
- ホームの参照画像は「ドライバーが制御しているこの端末と、このセーブデータ」由来でなければならない。ネームプレートとレベルが判定ボックスに
  重なるので、セーブを差し替えると判定がずれる。カットポイント（`--cut`）は**参照画像の属性**であってゲームの属性ではない（AVD 12 / タブレット 25）。
- 座標を目視で決めないこと：guest は `rotation=1` で、`input tap` は横画面空間を使い、`wm size` が報告するのは**ネイティブ方向**の
  1080x2400。この 2 つからは互いは導けない。PIL でボタンの色情報の連続区間を探して中心を算出する（目視では 2 回連続 160 px ずれた）。

---

## 8. テスト機（任意。実機ならこの節を丸ごとスキップ可）

```bash
export ANDROID_AVD_HOME=E:/android-avd ANDROID_SDK_ROOT=C:/Android/Sdk
"$ANDROID_SDK_ROOT/cmdline-tools/latest/bin/avdmanager.bat" create avd \
  -n lapis34 -k "system-images;android-34;google_apis;x86_64" -d pixel_6 --force
# 次に $ANDROID_AVD_HOME/lapis34/config.ini を編集：
#   disk.dataPartition.size=40G   hw.ramSize=6144
#   hw.gpu.mode=swiftshader_indirect   PlayStore.enabled=no
cd "$ANDROID_SDK_ROOT/emulator"
ANDROID_AVD_HOME=E:/android-avd ANDROID_SDK_ROOT=C:/Android/Sdk \
  ./emulator.exe -avd lapis34 -no-window -no-audio -no-boot-anim -no-snapshot \
  -gpu swiftshader_indirect -accel on
```

3 つの落とし穴、どれ一つ取っても調査 1 回分の価値がある：
1. **必ず `emulator.exe` 経由で起動する**こと。`qemu-system-x86_64-headless.exe` を直接起動すると
   `libandroid-emu-curl.dll: cannot open shared object file` になる。
2. `ANDROID_AVD_HOME` なし → `Unknown AVD name`（AVD が `$HOME\.android\avd` に無い場合）。
3. `ANDROID_SDK_ROOT` なし → `Broken AVD system path`（システムイメージがデフォルトの SDK ルート下に無い場合）。

さらに環境側の 2 件：
- 起動のたびに**モーダル**なシステムウィンドウ `ImmersiveModeConfirmation`（"Viewing full screen / Got it"）に塞がれる。
  フォーカスを取りに行くので、ゲームはフリーズしたように見え、リクエストを 1 本も出さない。実測したボタン範囲をクリックして消す。`keyevent 4` は使わないこと。
- クライアントは arm64-v8a/armeabi-v7a しか同梱しておらず、x86 ホストには命令翻訳のレイヤーが 1 つ必須。エミュレータのディスクイメージは実機より一桁遅い
  （§9 の対比タイミング参照）。なので**エミュレータのタイミングで操作感を判断しないこと**。

### `errno=1455 ページファイルが小さすぎます` は原因が 2 種類ある

`javac` / `d8` が `os::commit_memory ... failed; error='页面文件太小' (errno=1455)` を出すとディスク問題のように読めるが、
どちらの場合もディスクではない：

| 成因 | 判定基準 | 処置 |
| --- | --- | --- |
| ヘッドレス AVD の占有（実測で qemu プロセス 26.5 GB private、利用可能なコミット可能メモリが <2 GB まで押し下げられる） | `Get-Process \| Sort PrivateMemorySize64` | **AVD 停止 → ビルド → AVD 起動**。`adb emu kill` は効かない。`Stop-Process -Id <pid> -Force` を使う |
| ページファイルが膨張した後に縮まない（現在使用量は数百 MB、確保量は 19 GB+） | `Get-CimInstance Win32_PageFileUsage` で `AllocatedBaseSize` と `CurrentUsage` を比較 | 再起動しない限り解放されない。またはページファイルを空きのあるディスクへ移す（システム変更、管理者権限が必要） |

朗報：AVD を止めても何も壊れない。7 GB のリソースツリーは再起動に耐える（再スキャンで banks=1040 が一致）。

---

## 9. 実測タイミング（AVD と実機の対比）

| 動作 | AVD（x86_64 + 命令翻訳） | 実機 |
| --- | --- | --- |
| コールドスタートから操作可能まで | 約 90 s | — |
| `adb install` 242 MB APK | 19 s | — |
| 6.06 GB ツリーの push | 368 s（16.5 MB/s） | — |
| 7.0 GB ツリーの push | 約 536 s（12.5 MB/s） | — |
| インポート展開 | **441 s** | **8 s** |
| ホームの PSS | 885 MB | — |

インポートは 55 倍差。原因はエミュレータのディスクイメージ。**AVD のタイミング結論で実機案を却下しないこと。**

---

## 10. 既知の未解決

| 項目 | 現状 | 次に調査すべきこと |
| --- | --- | --- |
| 時空の狭間「⚡5 チャレンジ」 | まったく入れない状態から、実 Boss パネル表示まで実現した。チャレンジクリックは P1021 心拍だけを送信し、P42 を送信しない | チャレンジの**前提条件**を当たれ（「カード所持」のチーム選択入口は無効化されたまま。P186 は実装済みだが誰も呼んでいない）。もう一つのヒントとして推奨戦闘力 99999999 vs `player.power` 99999。P180 のフィールドの推測は打ち切る |
| フォント差し替え | こちらの `font.bdl` は 13.8 MB、中国語は 2,026 のコードポイントを使っており、すべてシステムフォント頼み | serialized file のバイトを直接書き換える必要がある。UnityPy で `m_FontData` に代入する道はすでに試したが無効（読み戻しても元のサイズのまま） |
| 課金ページ（辉圣石） | 空白 | あの枠は Google Play Billing のネイティブコールバック由来で、5 つのメイン tab は固定 prefab。データ側では直せない |
| 未実装プロトコル | クライアントが要求したがこちらのハンドラが無い：P111 フレンド、P132 イベント運営、P170 クラブ願掛け、P250/P251 魔獣撃退戦、P1014 利用規約受領、P1016 二次確認、P1028 特定タスク、P1100 イベント章 | §7 のプロトコル番号判定基準に従い一つずつ埋める。「未マッピング」は全ゼロレスポンス + 空ページとして現れる点に注意 |
| ストーリー内の日本語残留 | 言語テーブルはすでに仮名ゼロ。残りはハードコード Lua、UI に焼き込まれたアート文字、動画に焼き込まれた字幕、631 のストーリーバンドル内の未翻訳の台詞 | 台詞はバンドル内の `_language` 付き JSON TextAsset。`UnityPy.m_Script` で読むと `?` になるので、`get_raw_data()` + `save('original')` を使うこと |