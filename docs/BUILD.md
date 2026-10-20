# 构建手册：从零到能玩的那台设备

这份文档干三件事：**成功路径**（每一步的当场判据，不是回忆）、**构建方法**（命令与顺序）、
**踩坑清单**（每个坑都写清它当时的假症状，否则下次会当成另一个问题去查）。

前提：你手里已经有官方客户端 `com.klab.lapis` 1.5.0 的 APK 和它的资源归档。本仓库不放这些东西，
也不放任何由它们派生出来的二进制；下面所有"输入"都指你自己那份。

---

## 0. 目录约定

脚本里的路径常量都是**占位**，不是某个人的机器布局：

| 占位 | 含义 | 里面有什么 |
| --- | --- | --- |
| `C:/lapisbuild` | 构建根 | `game_decoded/`（解码后的 APK 树）、`stubapp/`（存根源码与产物）、`tools/`（apktool、JDK）、`delivery/`（验收产物） |
| `E:/lapis` | 工作区 | 原始 APK、上游资源归档、主机资源镜像 `revival/local/`、投放覆盖源 `staging/overlay_src/`、交付集 `build_full/` |
| `C:/Android/Sdk` | Android SDK | `build-tools/34.0.0`、`platforms/android-34/android.jar`、`platform-tools/adb.exe`、`cmdline-tools/latest`、`system-images/` |
| `E:/ref-sample` | 自备对照样本 | 只在注释里出现，用来解释某个字段/资产"应该是什么"，本仓库不含 |
| `E:/android-avd` | AVD 主目录 | `ANDROID_AVD_HOME` 指向这里 |

一次改掉全部：

```bash
cd lapis-revival
grep -rl 'C:/lapisbuild' tools | xargs sed -i 's#C:/lapisbuild#/your/build/root#g'
grep -rl 'E:/lapis'       tools | xargs sed -i 's#E:/lapis#/your/workspace#g'
grep -rl 'C:/Android/Sdk' tools | xargs sed -i 's#C:/Android/Sdk#/your/android-sdk#g'
```

三个环境变量必须自己设，仓库里没有值：

| 变量 | 用途 |
| --- | --- |
| `KS_PASS` | 你自己的 keystore 口令（见 §1） |
| `ADB_BIN` | 用哪个 adb；**只能有一个**，见 §7 |
| `SERIAL` | `adb devices` 里的那台目标设备 |

工具链：JDK（编译用 17 以上皆可，脚本按 `-encoding UTF-8 -nowarn` 写的）、`apktool`、
`build-tools 34.0.0`（`zipalign` + `apksigner` + `lib/d8.jar`）、Python 3.13、
`android-34 google_apis x86_64` 系统镜像（只在用模拟器时需要）。

---

## 1. 一次性准备

```bash
# 1) 解码底座 APK
apktool d -f -o game_decoded <你的官方 APK>

# 2) 自己的签名库（不要复用别人的）
keytool -genkeypair -keystore stubapp/lapis.keystore -alias lapis \
  -keyalg RSA -keysize 2048 -validity 10000 \
  -storepass "$KS_PASS" -keypass "$KS_PASS" -dname "CN=lapis-lab"

# 3) 依赖 jar 放到 stubapp/libs/（protobuf-java、protobuf-java-util 等；不随仓库提供）
```

**为什么必须换签名**：重装同包名要求签名一致，而原包签名我们拿不到。换签名等于放弃与原服的兼容，
对单机化没有代价——但**换签名会让旧存档失效**，所以任何已经装了线上版本的用户，
升级前必须先导出 `shared_prefs`（详见 §6 的存活规则）。

---

## 2. 构建（每个包各跑一次）

```bash
cd /your/build/root
NO_INSTALL=1 PKG=cn bash tools/rebuild_relay.sh     # -> game_relay.apk
NO_INSTALL=1 PKG=jp bash tools/rebuild_relay.sh     # -> game_relay_jp.apk
```

| 开关 | 默认 | 作用 |
| --- | --- | --- |
| `PKG` | `cn` | `cn` = `com.klab.lapis`（保住原存档），`jp` = `com.klab.lapis.jp`，两个包可以同机共存 |
| `NO_INSTALL=1` | 装包 | 只构建不装机 |
| `BUNDLE_TREE=1` | 关 | 把多 GB 资源树打进 APK；**平时不要**，交付形态是"瘦 APK + 一个 `import.zip`" |

产物约 242 MB（含客户端本体，不含资源树）。

### 脚本内部顺序（判据都在这一节）

1. **四个按包翻转，必须发生在 `javac` 之前。**
   `pkg_manifest.py`（包名/权限/标签）→ `pkg_lang.py`（语言表摘要 pin）→ `pkg_port.py`
   （CN 基端口 18080 / JP 18090）→ `pkg_story.py`（CN 译文库 vs 原始 JP 库）。
   原因是 `Seed.java` 里的 pin 是**编译进 `classes3.dex`** 的常量；翻转放在编译之后，就会出现
   "包里装的是 JP 的表，dex 却按 CN 的摘要去验"。后果不在构建时报错，而在冷启动时 `SEED refused`、
   Config 表空、界面回到未本地化状态。
   脚本末尾的 `trap` 会把四个都还原成 CN，所以中断不会把树留在错的身份上——这也是**同一份源码
   连跑两次不同 PKG 是安全的**依据。
2. `javac` → `jar` → `java -Xmx1024m ... com.android.tools.r8.D8` → 把 `classes.dex` / `classes2.dex`
   写成 `game_decoded/classes3.dex` / `classes4.dex`。
   `-Xmx` 是显式写死的：d8 默认按物理内存比例申请，在内存紧张的主机上会被拒（见 §8）。
3. **资产同步清单**（`rebuild_relay.sh` 里那个 `for a in ...`）：
   `protocol.descriptor.bin common.descriptor.bin version.json player.json shop.json shopgoods.json
   pvpreward.json stageawards.json arena.json mail.json task.json gacha.json mirror.json
   lab-account.json startup-key.json protocol-static.json`
   新增资产**必须同时加进这一行**，否则 APK 里没有它，运行期只表现为"那个页面空白且零请求"。
4. `SeedHashTest`：在主机上跑 `Seed.java` 自己的哈希代码，逐个数据库比 pin，附带两个控制——
   sidecar 形状（40 位大写十六进制、无换行）和"改一字节必须失败"。
5. `patch_il2cpp.py`、`patch_klb_func.py`：后者每次从原始备份**重建** `libklbsqlite3.so`
   （`sqlite3_open_v2` 的 vfs 改写 + `klb_vfs.xOpen` 放行明文文件名）。从备份重建而不是原地改，
   是为了让曾经住在同一个洞里的诊断代码不能回来——那些代码硬编码了 CN 包的日志路径，
   JP 包全部失败后又用打包的 errno 存错误，结果 JP 客户端在标题画面之前就 SIGSEGV。
6. `pincheck.sh`（暂存态）→ `apktool b` → `zipalign -f -p 4` → `apksigner`。
7. **产物再核两道**（这一步不能省，因为"树翻对了"不等于"包里有翻对的字节"）：
   `pincheck.sh --apk --pins pins_at_build.txt` 比构建时快照；
   再从 APK 里解出 `assets/bin/Data/9bdd7e35b810546fdbe3f8fa3ec1fd55`，断言那个烤进 Unity 的
   端点串含 18080（cn）/ 18090（jp）。

### 生成类资产（改了主数据就要重跑）

| 脚本 | 产出 | 读什么 |
| --- | --- | --- |
| `make_state.py` | `player.json` | 主数据 + 存档状态：卡池、关卡星级、钱包、社团、房间座位 |
| `make_shopgoods.py` | `shopgoods.json` | P121 的扣费/发放/限购表 |
| `make_pvpreward.py` / `make_stageawards.py` | 对应 json | 竞技场与关卡奖励 |
| `make_mirror.py` | `mirror.json` | 时空夹缝：`ClubMirror` / `ClubMirrorEvent` / `Config` / `DropGroup` |
| `gen_protocol_descriptor.py` | `protocol.descriptor.bin` | 客户端 Lua 里的 schema 声明（**单个 `FileDescriptorProto`，不是 Set**，407 个 message） |

`protocol.descriptor.bin` 是"不看 Lua 也能问出客户端读哪个字段"的入口：桩用
`DynamicMessage` 按它组装响应，字段名与编号都在这里。

---

## 3. 资源树打包（交付形态的另一半）

```bash
python tools/make_tree_zip.py         # -> staging/tree_cn.zip
python tools/make_tree_jp_from_cn.py  # -> staging/tree_jp.zip
```

- 条目按**设备清单**挑选（从真机数出来的路径列表），再叠 `staging/overlay_src/` 里我们自己改过的文件。
  清单不是装饰：直接打全树会带进设备根本不读的东西，也会漏掉只存在于设备上的那份。
- JP 树不是重打一遍，而是"CN 树 + 按条还原按包差异"（632 条：CN 译文剧情包与语言表），
  差异字节从旧 JP 归档逐条拷回，全部 `ZIP_STORED` + `force_zip64=True`。
- **SoundBanks 补全段**：设备原本只有 129/1,021 个 bank，其余在上游是可选 CDN 下载
  （`DownloadConfig.SoundBankName` → `VOX_CHR_*` / `VOX_EVT_*`）。离线没有 CDN，所以这些角色语音
  是**整段静默**——不报错、不弹提示，日志里也看不出来。补全后 1,040 个。
- **sidecar 规则按类型不同，别去"统一"它**：`.bnk.hash` = 恰好 40 字节大写 SHA-1 无换行；
  `.bdl.hash` = **41 字节**（带换行）。缺 sidecar 或长度不对，资源直接不加载。
- 排除 `SoundBanks/SoundBanks/` 这种嵌套重复目录（实测 484 MB 纯重复）。
- 树里有 1 个 0 字节 bundle（上游就是空的，`.../pickupray4/bg.bdl`），它和"EncryptKey 头 XOR 没清零"
  的症状字符串一模一样（`Unable to read header from archive file`），所以**先看大小再看密钥**。

---

## 4. 交付

```bash
python tools/ship_checksums.py     # 拷进 build_full/ -> 流式算 SHA-1 -> 重写 CHECKSUMS.txt -> 回读校验
```

四件交付物（`manifests/delivery-sha1.txt` 是我们这版的指纹）：两个 APK + 两个树，
合计约 14 GB。**六 GB 级文件不能 `read()`**——真踩过一次 `MemoryError`，所以全部 4 MB 分块流式。
`CHECKSUMS.txt` 表头三行按字节不动，写完必须回读逐行再算一遍。

构建**不是逐位可复现**（zip 时间戳进包），所以核对只能比**包内资产**，不能比整包哈希。
这也是"装进设备的到底是不是我刚构建的那份"的唯一判据：`adb install` 回 `Install command complete`
只证明装了一个包，不证明装的是这个包。装机必须和构建在**同一条 `&&` 链**上，
事后比 `assets/player.json` 的 sha1 与 dex 里的新增字面量。

---

## 5. 投放（新装一次即可）

```bash
adb -s "$SERIAL" install -r /your/build/root/game_relay.apk
cp /your/workspace/build_full/tree_cn.zip /tmp/import.zip
adb -s "$SERIAL" push /tmp/import.zip /sdcard/Android/data/com.klab.lapis/files/import.zip
adb -s "$SERIAL" shell am start -n com.klab.lapis/com.klab.jackpot.notification.FirebaseMessagingActivity
# 完成判据只看这一行，别看文件计数：
adb -s "$SERIAL" logcat -d | grep "SEED tree installed"
```

- **绝对不要 `pm clear`**：那会连整棵投放树一起毁掉，重建要重新推 7 GB。
- 半截推送会被读到，见过 `SEED tree fatal: unexpected EOF`；等 push 完再启动就好。
- 投放归档不受摘要门限制，导入成功后应用自己删掉它。
- 两个可复现的坑：`adb push` 在 FUSE 目标上可能删掉同名既有文件；用 `tar x` 铺树会把目录做成
  `0770`，应用读不到。所以大树走 `/data/local/tmp`（ext4）+ tar，权限另调。
- 落盘文件的**属主**决定应用能不能读：shell 建的 `0660` 在应用目录下应用是读不到的；
  而应用自己写的 `0660` 没问题。

---

## 6. 存档存活规则（决定能不能"升级"）

存活：`force-stop`、`adb install -r`（同签名）、重启设备、AVD 冷重启（7 GB 树也扛得住）。
失效：`pm clear`、卸载重装、**换签名**。
存档本体是单个 `shared_prefs/lapis_state.xml`，键形如 `wal_1` / `itm_<id>` / `goods_<id>` /
`stage_<id>` / `av_bind_<id>` / `mir_*`。

---

## 7. 验收

```bash
bash tools/delivery_gate.sh      # 冷启动 + 逐页判据
bash tools/sweep_cn.sh           # 首页入口逐页扫描：这一页实际触发了哪个协议号、客户端报了几次异常
python tools/boot_state.py <png> --home <本机自采首页> --cut <切点>   # 帧分类
```

**页面身份只认协议号，不认截图**：未映射的协议会被回一个全零响应，页面照样渲染得出来，
但内容是空的。`P9000` 与 `P1021` 是 60 秒心跳，**不能当作"我点到了"的证据**——
踩过的形状是"点了按钮 → 日志动了 → 判成通过"，而那两行只是心跳。

其他判据细节：
- 冷启动由桩自己的日志驱动，不是靠固定 sleep。早先版本睡 200 s 再盲点"标题/同意"，
  第二次重启时客户端其实还在标题页，后半程扫描报告的帧它根本没去过。
- logcat 用"每页先 `-c` 再 `-d`"，不要挂常驻流：一条 `logcat -v time` 单次运行就写了 2.1 GB。
- 一台设备只能有一个驱动者。两个驱动不会大声报错，而是交错点击、把对方的半页写进同一个结果文件，
  读起来像"这页开了但没协议"。脚本用 `mkdir` 原子锁拦这个，被杀掉的后台任务会留下活的子进程，
  所以**守卫是锁，不是任务管理器**。
- 逐页扫描前把被测设备钉到标定分辨率：`wm size 1280x720` + `wm density 240`，扫完
  `wm size reset` + `wm density reset`。因为两套标定几何（模拟器 2400x1080、平板 2000x3200）
  是**不同宽高比**，不存在一个缩放系数能把按钮表映射过去。
  注意改 `wm density` 会让 Android 弹"点按以重启"浮层，把帧分类器搅成
  title/campaign/unknown 来回跳，而画面其实早就在首页——**分类器抖动时直接看帧**。
- 首页参考图必须来自"被驱动的这台设备和这份存档"。名牌和等级盖在判定框里，
  换一份存档判定就飘；切点（`--cut`）是**参考图的属性**，不是游戏的属性（AVD 12 / 平板 25）。
- 坐标不要靠眼睛：guest 是 `rotation=1`，`input tap` 用的是横屏空间，而 `wm size` 报的是**自然方向**
  1080x2400，两者推不出彼此。用 PIL 探按钮的颜色游程求中心（凭眼力两次都差 160 px）。

---

## 8. 测试机（可选，真机能跳过整节）

```bash
export ANDROID_AVD_HOME=E:/android-avd ANDROID_SDK_ROOT=C:/Android/Sdk
"$ANDROID_SDK_ROOT/cmdline-tools/latest/bin/avdmanager.bat" create avd \
  -n lapis34 -k "system-images;android-34;google_apis;x86_64" -d pixel_6 --force
# 然后改 $ANDROID_AVD_HOME/lapis34/config.ini：
#   disk.dataPartition.size=40G   hw.ramSize=6144
#   hw.gpu.mode=swiftshader_indirect   PlayStore.enabled=no
cd "$ANDROID_SDK_ROOT/emulator"
ANDROID_AVD_HOME=E:/android-avd ANDROID_SDK_ROOT=C:/Android/Sdk \
  ./emulator.exe -avd lapis34 -no-window -no-audio -no-boot-anim -no-snapshot \
  -gpu swiftshader_indirect -accel on
```

三个坑各值一轮排查：
1. **必须走 `emulator.exe`**。直接起 `qemu-system-x86_64-headless.exe` 会
   `libandroid-emu-curl.dll: cannot open shared object file`。
2. 不带 `ANDROID_AVD_HOME` → `Unknown AVD name`（AVD 不在 `$HOME\.android\avd` 时）。
3. 不带 `ANDROID_SDK_ROOT` → `Broken AVD system path`（系统镜像不在默认 SDK 根下时）。

另外两条环境层面的：
- 每次新启动都会被一个**模态**系统窗口 `ImmersiveModeConfirmation`（"Viewing full screen / Got it"）
  挡住：它握着焦点，游戏看起来卡死、且一条请求都不发。点它实测的边界，不要用 `keyevent 4`。
- 客户端只带 arm64-v8a/armeabi-v7a，x86 主机必须做一层指令翻译；模拟器的磁盘镜像比真机慢一个数量级
  （见 §9 的对照时序），所以**别用模拟器的时序判断手感**。

### `errno=1455 页面文件太小` 有两种成因

`javac` / `d8` 报 `os::commit_memory ... failed; error='页面文件太小' (errno=1455)` 读起来像磁盘问题，
两种情况都不是：

| 成因 | 判据 | 处置 |
| --- | --- | --- |
| 无头 AVD 占用（实测 qemu 进程 26.5 GB private，可用提交内存压到 <2 GB） | `Get-Process \| Sort PrivateMemorySize64` | **停 AVD → 构建 → 起 AVD**；`adb emu kill` 不生效，要 `Stop-Process -Id <pid> -Force` |
| 页面文件被撑大后不缩（当前用量几百 MB，分配却 19 GB+） | `Get-CimInstance Win32_PageFileUsage` 比 `AllocatedBaseSize` 与 `CurrentUsage` | 重启才释放；或把页面文件挪到空闲盘（系统改动，要管理员权限） |

好消息：停 AVD 不毁东西，7 GB 资源树能扛住重启（复点 banks=1040 一致）。

---

## 9. 实测时序（AVD 与真机对照）

| 动作 | AVD（x86_64 + 指令翻译） | 真机 |
| --- | --- | --- |
| 冷启动到可交互 | 约 90 s | — |
| `adb install` 242 MB APK | 19 s | — |
| push 6.06 GB 树 | 368 s（16.5 MB/s） | — |
| push 7.0 GB 树 | 约 536 s（12.5 MB/s） | — |
| 导入解包 | **441 s** | **8 s** |
| 首页 PSS | 885 MB | — |

导入差 55 倍，是模拟器磁盘镜像的锅。**不要用 AVD 的时序结论去否决真机方案。**

---

## 10. 已知未解

| 项 | 现状 | 下一步该查什么 |
| --- | --- | --- |
| 时空夹缝「⚡5 挑战」 | 从完全进不去做到出现真实 Boss 面板；点挑战只发 P1021 心跳，不发 P42 | 查挑战的**前置条件**（"持有卡片"选队入口是禁用态；P186 已实现但无人调用）；另一条线索是推荐战力 99999999 vs `player.power` 99999。别再猜 P180 的字段 |
| 字体覆盖 | 我们的 `font.bdl` 13.8 MB，中文用到 2,026 个码点，全靠系统字体兜底 | 需要直接改 serialized file 的字节；UnityPy 赋 `m_FontData` 这条路试过且无效（重读仍是原尺寸） |
| 充值页（辉圣石） | 空白 | 那些格子来自 Google Play Billing 原生回调，5 个主 tab 是固定 prefab，数据侧修不了 |
| 未实现协议 | 客户端请求过、我们没处理器：P111 好友、P132 活动运营、P170 社团许愿、P250/P251 魔兽击退战、P1014 条款回执、P1016 二次确认、P1028 特定任务、P1100 活动章节 | 逐个按 §7 的协议号判据补；注意"未映射"的表现是全零响应 + 空页面 |
| 剧情残留日文 | 语言表已是 0 假名；剩下的在硬编码 Lua、烤进 UI 的美术字、烧进视频的字幕，以及 631 个剧情包里未翻完的对白 | 对白是 bundle 里带 `_language` 的 JSON TextAsset；`UnityPy.m_Script` 读它会变成 `?`，要用 `get_raw_data()` + `save('original')` |
