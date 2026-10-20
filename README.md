# Lapis Re:LiGHTs 单机化复活工程（宝石幻想 / ラピスリライツ）

已停运的 Unity 手游《宝石幻想：光芒重现》（`com.klab.lapis` 1.5.0，KLab / KADOKAWA，2022-10-31 停服）
的**本地兼容与单机化（オフライン化）研究**。目标是让一个原本必须联网的客户端，在一台不联网的机器上
完整进入主界面、打通关卡战斗、使用商城与竞技场，并把界面与文本转成简体中文。

本仓库只放**代码、工具与文档**，不放任何游戏内容。它是给"已经自己持有客户端与资源"的人看的复现说明，
不是安装包，也不是官方服务端。

## 现在能做到什么（在 Android 12 平板 2000x3200 与 x86_64 AVD 上实机验证）

| 原本联网的部分 | 状态 | 判据（当场可复跑） |
| --- | --- | --- |
| 登录 / 握手 / 主界面 | 可用 | 冷启动进主房间，无 `LuaException` |
| 关卡战斗（主线剧情关） | 可从头打到尾 | 下载→标题卡→对话→战斗→发奖→下一幕，1,566 关全三星 |
| 商城（購買部） | 可开、可买、可持久 | `P120` 出完整 UI；`P121 goods=100012 x1 bought=1`；余额按 `CostValue` 扣 |
| 竞技场（アリーナ） | 可用 | `P200` 出战、`P204` 结算记分，赢 +20 输 +5 下次读得到 |
| 抽卡（召唤） | 可用 | `P1024` 卡池、发卡入档 |
| 主页 3D 看板娘 / 社团房间「交流」 | 可用 | `SceneMainStage` 的角色来自 `PBGameInfo.currentTheme` + `P11.themes[].seats`；座位表为空时那一格是 null GameObject |
| 时空夹缝（Mirrors） | 做到真实 Boss 面板 | `P180..P186` 一族按实测语义服务（`round` = 已到层、`bout` = 已用次数、每周周期用秒）；挑战按钮仍未通（见 `docs/BUILD.md` §10） |
| 语音 | 补全 | 树里 1,040 个 SoundBank（原本设备只带 129 个，其余在上游是可选 CDN 下载，离线时**整段静默且不报错**） |
| 简体中文 | 语言表 30,687 行 0 假名；剧情对白在资源包里，逐包处理 | `tools/cn_audit.py` 码点级审计 |
| 双包共存 | 中/日两个包同机并存 | CN 保留 `com.klab.lapis` 以保住原存档，JP 用 `com.klab.lapis.jp`；资产服务按包派生端口 18080 / 18090 |
| 存档 | 跨重启与跨重装存活 | `force-stop` 与 `adb install -r` 后余额/库存不变 |

## 架构一句话

不改一行 Lua、不重签名游戏逻辑，而是**在设备上放一个假的服务端**：

```
客户端 ──gRPC/HTTPS──> TlsProxy(127.0.0.1) ──> HttpFileServer / GrpcApi  (Java, 随 APK 装入)
                                              │
                       协议桩 ProtobufCore ────  28 个协议分支（P11/P120/P121/P132/P180..186/P200/P204/P1024…）
                       SharedPreferences 存档 ─┘  lapis_state.xml：wal_/itm_/goods_/stage_/pvp_score/av_bind_/mir_*
                       导入器 ImporterActivity ──  把交付的 import.zip 解成设备上的资源树
```

- `stubapp/`：Android 侧的服务桩（Java）。`ProtobufCore` 按协议号组装 protobuf 响应（schema 来自
  APK 内的 `protocol.descriptor.bin`，用 `DynamicMessage` 现场建消息），`Seed` 用 SHA-1 钉住随包数据库，
  `HttpFileServer`/`TlsProxy` 把客户端的域名指向 `127.0.0.1`。
- `tools/`：产出上面那些数据的脚本（按包翻转、状态生成、数据库改写、资源树打包、投喂、验证）。
- `manifests/`：期望摘要清单。游戏内容不在这里，接收方用自己手里的资源核对。

## 构建与安装（不含游戏数据，需要你自备客户端与资源）

```bash
export KS_PASS=<你自己 keystore 的口令> SERIAL=<adb devices 里的序列号>
NO_INSTALL=1 PKG=cn bash tools/rebuild_relay.sh   # 服务桩 -> dex -> apktool -> zipalign -> apksigner
python tools/make_tree_zip.py                     # 7 GB 资源树（按设备清单 + 覆盖源 + SoundBank 补全）
bash tools/provision_files.sh                     # 投放
bash tools/delivery_gate.sh                       # 实机验收：冷启动 + 逐页协议号判据
```

完整顺序、每一步的判据、四个按包翻转为什么必须在 `javac` 之前、sidecar 为什么 `.bnk` 40 字节而
`.bdl` 41 字节、`errno=1455` 的两种成因、以及未解项：**见 `docs/BUILD.md`**。

## 这个仓库刻意不包含的东西

- 任何 `.bdl` / `.assetbundle` / 音频 / 图片 / 视频 / 主数据库 / 语言表内容；
- 反编译得到的客户端 Lua、IL2CPP dump、smali；
- 构建产物（约 242 MB 的 APK、约 7 GB 的树）；GitHub 也放不了这个量级；
- 密钥、keystore、口令、账号、设备序列号、存档。

原因见 `NOTICE.md`：游戏内容版权归 KLab / KADOKAWA / 盛趣，本仓库只保留我们自己写的代码与推导过程。

## 文档

| 文件 | 内容 |
| --- | --- |
| `docs/BUILD.md` | **构建手册**：成功路径、命令与顺序、踩坑清单、实测时序、未解项（中/英/日） |
| `docs/TECHNIQUES.md` | 技术文档：判定方法、字段语义与失败案例（中/英/日） |
| `docs/GAME.md` | 游戏介绍：这是一款什么游戏、它的系统长什么样（中/英/日） |
| `README.ja.md` / `README.en.md` | 本文件的日文 / 英文版 |

## 法律与道德边界

只对**自己设备上的已停运作品**做互操作研究。不重开官方服务、不分发游戏内容、不绕过任何仍在生效的
付费或防盗机制。所有网络请求都被收敛到 `127.0.0.1`；崩溃上报通道属于原客户端行为，未做改动。
