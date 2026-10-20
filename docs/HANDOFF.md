# 交接文档：复现、现状、以及接手人该先做什么

这份文档假设**你没有本项目的任何历史**。它回答四个问题：要哪些输入、怎么从零跑到首页、
现在到底做到哪一步、以及哪些坑已经用实测关掉了（别再走一遍）。
具体的命令与判据在 `docs/BUILD.md`，方法学与失败案例在 `docs/TECHNIQUES.md`。

---

## 0. 仓库里没有的东西，以及你需要的输入

本仓库**只有自写代码、脚本与文档**。原客户端与它的一切资源都不在里面，也不会进 git：
游戏内容版权归 KLab / KADOKAWA / 盛趣；GitHub 的单文件上限（100 MB）也放不进 7 GB 的资源树。
所以复现的前提是：你自己已经持有这些文件（本项目是从 2022 年停服前的官方归档做出来的）。

| 输入 | 用在哪一步 | 校验 |
| --- | --- | --- |
| 官方客户端 `com.klab.lapis` 1.5.0 的 APK（99,757,060 B，arm64-v8a + armeabi-v7a，内含 `libklbsqlite3.so`） | `apktool d` 建 `game_decoded/`；整个构建的底座 | `manifests/required-inputs.tsv` |
| `Lapis-AssetBundles-20221022.7z`（4,229,156,448 B） | 解出主机资源镜像 → `make_tree_zip.py` 的主体 | 同上 |
| `Lapis-MasterData-20221022.7z`（1,799,924 B） | 解出 `master_data.db` / `master_data_lang.db`：`Seed` 的 pin、`make_state`/`make_mirror`/`make_shopgoods` 的输入 | 同上 |
| `Lapis-SoundBanks-20221022.7z`（1,732,452,189 B） | SoundBank 补全段（设备原本只有 129/1,021 个） | 同上 |
| `Lapis-manifests-20221201.7z`（1,053,953,620 B） | 上游清单/版本记录，用来确定哪些条目设备真的会读 | 同上 |
| 真机或 AVD 上数出来的**设备清单** | `make_tree_zip.py` 的 `DEVICE_LIST`（不是装饰，见 BUILD.md §3） | 自备 |

有一条**很容易踩**：手边若还有一个"整包渠道 APK"（约 1.78 GB、里面直接带 `.bdl`，ABI 只有
armeabi-v7a/x86），**不要拿它当构建底座**。它没有 arm64，也不是我们解码的那一份；用它建出来的包
会在装到 64 位设备上时才暴露。判据很简单：底座必须含 `lib/arm64-v8a/libklbsqlite3.so`。

拿到文件后**先比摘要再动手**：

```bash
sha1sum -c <(awk '$1!~/^#/ {print $3"  "$1}' manifests/required-inputs.tsv)
```

这一步不是形式主义。本项目有三次结论被推翻都是因为"输入不是我以为的那份"：
`font.bdl` 用路径集合比对被判成"一样"（实际内容不同）、JP 构建装上了 CN 的语言表 pin、
以及构建失败之后仍然 `adb install` 了上一轮的旧包。**构建不是逐位可复现**（zip 时间戳进包），
所以身份判定只能比**包内资产**与 dex 里的字面量，不能比整包哈希。

---

## 1. 从零到首页（最短路径，每步的判据）

1. 备好 §0 的输入并核对摘要。
2. `apktool d -f -o game_decoded <官方 APK>`；建自己的 keystore，`export KS_PASS=...`。
3. 按 `docs/BUILD.md` §0 把脚本里的占位路径改成你的目录，`export ADB_BIN=... SERIAL=...`。
4. 跑生成类脚本（`make_state` / `make_shopgoods` / `make_pvpreward` / `make_stageawards` /
   `make_mirror` / `gen_protocol_descriptor`），产出 `stubapp/assets/` 里那 16 个资产。
   **判据**：`SeedHashTest` 通过（它用 `Seed.java` 自己的哈希代码比 pin，含一个"改一字节必须失败"的控制）。
5. `NO_INSTALL=1 PKG=cn bash tools/rebuild_relay.sh`。
   **判据**：脚本内建的六道——javac / d8 / 资产同步 / `SeedHashTest` / `pincheck`（暂存态与 in-apk 两次）/
   烤进 Unity 的端口串含 18080。全绿才产出 APK。
6. `python tools/make_tree_zip.py` → `tree_cn.zip`（约 7 GB / 12,718 条目 / 1,040 个 bank）。
   **判据**：条目数与 sidecar 长度（`.bnk.hash` 40 字节无换行、`.bdl.hash` 41 字节）。
7. 装机 + 投放：`adb install -r` → push 成 `import.zip` → 启动一次 →
   **判据只认这一行**：`logcat -d | grep "SEED tree installed"`。别数文件（导入要跑几分钟，中途计数必然偏小）。
8. 冷启动验收 `bash tools/delivery_gate.sh`。
   **判据**：首页到达时 `P11 / P1024 / P120 / P132 / P60 / P1014 / P1028` 有服务记录，异常计数 0。
9. 逐页扫描 `bash tools/sweep_cn.sh`。
   **判据**：每页记"这次点击实际触发的协议号 + 客户端异常次数"，不记截图。
10. JP 包：`NO_INSTALL=1 PKG=jp bash tools/rebuild_relay.sh` +
    `python tools/make_tree_jp_from_cn.py`（同一棵树 + 按条还原 632 条按包差异），两个包同机共存。

**唯一的禁区：不要 `adb shell pm clear`** —— 它会把投放好的 7 GB 树和存档一起毁掉，重建要重推一遍树。

---

## 2. 现在到底做到哪一步（可玩面 / 已知空白）

| 面 | 状态 |
| --- | --- |
| 登录、握手、首页、3D 看板娘（社团房间座位） | 可用 |
| 主线剧情关（下载→标题→对话→战斗→发奖→下一幕） | 可从头打到尾，1,566 关全三星 |
| 商城：开页 / 购买 / 扣费 / 持久 | 可用（`P120`/`P121` 实测） |
| 竞技场出战与结算记分 | 可用（`P200`/`P204`，赢 +20 输 +5 跨重启读得到） |
| 抽卡 | 可用（`P1024` 卡池 + 发卡入档） |
| 语音 | 完整（1,040 bank，全部 sha256 逐条核过） |
| 简体中文 | 语言表 30,687 行、0 假名；剧情对白按包处理，仍有约 30.8k 行是日文 |
| 时空夹缝 | 做到**真实 Boss 面板**；「挑战」按钮仍不发 `P42`（见 §3.1） |
| 充值页（辉圣石格子） | 空白，**已判定数据侧修不了**（见 §4） |
| 好友 / 活动运营 / 魔兽击退战 / 活动章节等 | 客户端会请求，我们**没有处理器**：P111 / P132 / P170 / P250 / P251 / P1014 / P1016 / P1028 / P1100 |

---

## 3. 接手人建议先做的三件事

### 3.1 夹缝的挑战按钮
`P180..P186` 一族已经按实测语义服务了（`bout` = **已用次数**而不是剩余、`round` = 已到层、
周周期用**秒**且取本周一 00:00），面板也真出来了。卡点是点「⚡5 挑战」只发 `P1021` 心跳、不发 `P42`。
**去查挑战的前置条件**，不要再猜 `P180` 的字段：现场是"持有卡片"的选队入口处于禁用态（点了无反应），
而 `P186`（镜像队伍）已经实现但没有任何调用者。另一条线索：面板写推荐魔女力 99999999，
而 `player.power` 是 99999，可能是战力门槛直接吞掉了按钮。

### 3.2 中文字体的真正修法
现在的中文靠**系统字体**兜底。我们的 `font.bdl` 是 13.8 MB，参照实现是 140 MB
（9 个 CJK 字体各内嵌 Noto Sans CJK SC，42,220 码点），而我们要显示的中文用到 2,026 个码点。
**要改的是 serialized file 的字节**：用 UnityPy 给 `m_FontData` 赋值再 `save()` 这条路已经试过且无效
（输出涨了 27.5 MB，重读仍是原尺寸——那只是解压，不是替换）。

### 3.3 剩下的中文
剧情对白在 631 个剧情 `.bdl` 里，是带 `_language` 的 JSON TextAsset（46,277 行）。
读取要点：`UnityPy` 的 `m_Script` 把它读成 `?`，要 `get_raw_data()` + `ensure_ascii` + `save('original')`。
另外三类残留**不在语言表里**，别在表上找：硬编码在 Lua 里的字符串、烤进 UI 美术的字、烧进视频的字幕。

---

## 4. 已经用实测关掉的门（不要重走）

| 走过的路 | 结论 |
| --- | --- |
| 破译 Lua 尾部的摘要 | 1,239 个资产 × 340 种 framing/盐，零命中。**不要计划原地改 Lua**，一切从数据侧改 |
| 读客户端代码 | `luaData` 能解（它实质是 `select * from X` 的加载器），`scene`/`manager`/`ui` 解不开（可打印比例约 0.15）。但**数据契约可读**：`protocol.descriptor.bin` 是单个 `FileDescriptorProto`（不是 Set），407 个 message |
| 找官方简体中文包 | 搜遍 JP 侧 CDN 与 APK 工件，**不存在**；只有 61 行 CN 残留 |
| 充值页 | 格子内容来自 Google Play Billing 的原生回调，5 个主 tab 是固定 prefab → 数据侧无解 |
| 用 UnityPy 换字体 | 见 §3.2，无效 |
| 术语冲突批量挖掘 | 滑窗与子串撞出来的绝大多数是假阳性。可信的检验只有一个：**同一来源在界面上出现多种写法**；任何改写都要按 JP 原词限定范围 |
| 给 `pvp`/公告栏做真服务 | 公告栏的 HTTPS URL 烤在客户端里，端口派生只对 HTTP 资产服务有效 |
| root 平板 | 解锁 bootloader 会清数据，且不解决任何阻塞项 → 没做 |
| 用 LDPlayer 当测试机 | x86 主机 + arm-only 包必须翻译，LDPlayer 的 guest 里还叠了**第二层**翻译；已换 AVD/真机 |
| 拿 AVD 的时序判断手感 | 导入解包 AVD 441 s vs 真机 8 s（磁盘镜像慢约 55 倍）。**AVD 的时序不能当真机用** |
| 拿 `wm size` 推坐标 | `wm size` 报的是自然方向（1080x2400），`input tap` 用的是 `rotation=1` 的横屏空间，两者推不出彼此 |
| 全量 `chmod` | shell 建的 `0660` 在应用目录下应用读不到；应用自己写的 `0660` 没问题。别一把 chmod |
| 拿主机上的 `device_files` 镜像当真值 | 对 4,679 个文件是陈的；`adb pull` 还会在应用自有的 `0600` 文件上中断 |
| 拿 PNG 字节数 / 像素差当页面判据 | 都不稳定。页面身份 = 协议号 |

---

## 5. 判定工具箱（这套东西怎么做验证）

- **页面身份用协议号**。未映射的协议会被回全零响应，页面照样渲染但内容空。
- **心跳不算证据**。`P9000` 与 `P1021` 每 60 秒发一次；"日志动了"不能证明点击生效。
- **协议对照表**（实测得到，做 oracle 用）：`P11` 首页含 `themes[].seats` / `P120` 商店 / `P121` 购买 /
  `P132` 活动 / `P180..P186` 夹缝 / `P200` 竞技场出战 / `P204` 结算 / `P1001` 同意条款 /
  `P1024` 抽卡 / `P1028` 任务 / `P42` 战斗开始。
- **异常计数**比截图可靠：每页进一次，`logcat -c` → 操作 → `logcat -d`，数 `LuaException`。
  不要挂常驻 `logcat -v time`（单次扫描写过 2.1 GB）。
- **一台设备一个驱动者**：两个驱动交错点击不会大声报错，只会写出"这页开了但没协议"的假结果。
  脚本用 `mkdir` 原子锁拦；被杀掉的后台任务会留下活的子进程，所以守卫是锁，不是任务管理器。
- **帧分类需要本机自采的参考图**，切点是参考图的属性（不同设备不同），不是游戏的属性。
- **判定手段本身要验证**：报差值先给同对象重复测量的噪声底；掩体饱和的对比不算证据；
  守卫的控制组必须能自己伪造被拦的输入；恒为 0 的计数器和失效的选择器都会安静地通过。

---

## 6. 交付形态（"成品"是什么）

```
game_relay_cn.apk    242,144,815 B   # CN 包，瘦 APK（不含资源树）
game_relay_jp.apk    240,334,383 B   # JP 包
tree_cn.zip        7,003,552,761 B   # 改名 import.zip 投放
tree_jp.zip        7,002,068,161 B
```

指纹见 `manifests/delivery-sha1.txt`（我们自己算的，用于确认"装进去的是哪一版"）。
交付就两件事：**瘦 APK + 一个 `import.zip`**。存档是单个
`shared_prefs/lapis_state.xml`，键空间 `wal_` / `itm_` / `goods_` / `stage_` / `av_bind_` / `mir_` / `pvp_score`；
跨 `force-stop`、跨 `adb install -r`、跨重启存活，`pm clear` / 卸载 / 换签名会失效。

---

## 7. 环境层面的可变项（跨机器复现时会咬人）

- **盘符与目录会漂移**。这台机器在两周内把 SDK 和 AVD 从 C: 挪到 E:、再挪到 D:、然后 `D:` 整个卷消失
  （并进 C:）。所以任何文档里的绝对路径都当**过期**处理，先 `stat` 再用；本仓库统一用占位路径。
- **`errno=1455 页面文件太小` 有两种成因**：无头 AVD 把可用提交内存吃光（实测 qemu 进程 26.5 GB private），
  以及页面文件被撑大后不自缩（要重启）。先 `Get-Process | Sort PrivateMemorySize64`，
  再 `Get-CimInstance Win32_PageFileUsage` 比 `AllocatedBaseSize` 与 `CurrentUsage`，都别看磁盘。
- **adb 只能有一个 binary**：多个 adb 抢 5037 端口的单 server，症状是"设备忽然不见了"和"USB 掉了"。
- **AVD 的三个启动坑**（必须走 `emulator.exe`、必须带 `ANDROID_AVD_HOME`、必须带 `ANDROID_SDK_ROOT`）
  和每次新启动的模态 `ImmersiveModeConfirmation`（点它的实测边界，别用 `keyevent 4`）在 `docs/BUILD.md` §8。
- **改 `wm density` 会弹"点按以重启"浮层**，把帧分类器搅成来回跳，而画面其实早就在首页——抖动时直接看帧。
- **`keyevent 4`（返回键）会让这游戏的对话框输入失效**，之后测的都是一个被卡住的客户端；点屏上的 X。

---

## 8. 速查：新人最容易问的字段与规则

| 名称 | 实测语义 |
| --- | --- |
| `PlayerInst` / `Newbie` | 客户端只有这两处门控：余额与拥有物读 `PlayerInst`（付费货币种在 `diamondPay`，往 `items[]` 塞一行是惰的）；功能解锁读 `Newbie`（等级达标或某关已通过） |
| `GoodsPrice` / `CostValue` | 前者只是角标显示，后者才是 `GetCost`、可负担判定和扣费用到的 |
| `mir_*` 状态键 | `bout` = 已用次数（按本地日重置）、`round` = 已到层、`week` = 本周一 00:00 的**秒** |
| `themes[].seats` | 首页 3D 角色（社团房间）的名单来源；座位表为空 → `SceneMainStage` 里是 null GameObject |
| `.bdl.hash` / `.bnk.hash` | 加载门，不是元数据：41 字节 vs 40 字节（无换行）。缺或长度不对 = 资源不加载 |
| `EncryptKey` | manifest 里的这个 int32 是**头部 XOR**；非零 + 明文 UnityFS 文件 = `Unable to read header from archive file` |
| `Unable to read header...` | 两种根因同症状：`EncryptKey` 没清零，以及那个上游本来就 0 字节的 bundle。**先看大小再看密钥** |
| 缺资源的表现 | 缺 SoundBank 是**整段静默**（无报错、无提示、日志无痕）；缺 bundle 才有异常文本 |
| `Seed` 的自愈 | 判据是**文件存在**，不是摘要匹配。所以要把改好的 db 弄上设备，用"暂存 + `cp`"，不要重编 APK |
| 服务器时间戳 | `freshAt` / `EndTime` 一旦是过去时间，`PageShop` 会在 `OnEnter` 中途自我清除；离线一律回 `0` |
| traceback 行号 | 必须用字节码行表（`proto.debuginfo.addr_to_line_map`）翻译，直接读 Lua 行号会指向别的函数 |

---

## 9. 这个项目的边界（接手前请读）

只对**自己设备上已经停运的作品**做互操作研究：不重开官方服务、不分发游戏内容、
不绕过任何仍在生效的付费或防盗机制。所有网络请求都收敛在 `127.0.0.1`；
崩溃上报通道是原客户端行为，没有改动。签名是我们自己的 keystore（换签名会让原存档失效，这是取舍）。
仓库里不放密钥、口令、账号、设备序列号、存档，也不放任何游戏内容与反编译产物 —— 
这条边界是这份文档能公开存在的前提，接手后请继续守住。
