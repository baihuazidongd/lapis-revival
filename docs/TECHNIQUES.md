# 技术文档 · 成功路径与判据

这份文档只记**能被复跑证明的东西**。每条都给了判据（日志行、协议号、哈希、截图名），
凡是被实测推翻的旧结论，都写在"订正"里，因为那些弯路本身就是这份文档的价值。

---

## 1. 总体策略：不碰 Lua，改数据与网络

客户端有两道完整性防线，决定了整个工程的技术路线：

1. **Lua 有内容绑定的 trailer**。每个 `.lua` 资源尾部带 32 位十六进制校验值，加载时
   `LuaResLoader:DecryptLuaFile` → MD5 比对，不匹配就 `LuaException: MD5 VERIFY FAILED`。
   1,239 个资源 × 340 种 framings/salts 全部试过，零命中：**算法未知，无法就地改 Lua**。
   任何"改一行脚本"的方案都不成立，只能从数据侧、资源侧、网络侧解决。
2. **主数据是运行时 SQLite**。`luaData/*.lua` 其实是加载器，跑 `select * from <表>`，
   所以行为开关是**数据**而不是代码（例：`Config` 表的 `ShopFirstLook`、`Guideshow.Popup`）。

于是路线固定成三条腿：

| 腿 | 改什么 | 完整性怎么过 |
| --- | --- | --- |
| 网络 | 设备内 Java 服务桩回答协议 | 客户端只验会话密钥，不验内容语义 |
| 数据 | `master_data.db` / `master_data_lang.db` | `Seed.java` 里钉 SHA-1，改库必须同步改 pin |
| 资源 | 重打包 `.bdl` | 40 字节 `.bdl.hash` 边车 + manifest 的 Hash/Size 手术 |

## 2. 协议桩

- 18 个协议分支在 `ProtobufCore.call` 里按编号分派；关键编号：
  `P11` 玩家概要、`P120` 商城列表、`P121` 购买、`P132` 活动操作、`P200` 竞技场出战、
  `P204` 竞技场结算、`P1016` 阅读注意、`P1024` 抽卡。
- **页面身份只能靠协议判定**。`P9000` + `P1021` 是 60 秒心跳，点了什么按钮它们都会发，
  拿它们当"页面打开成功"的证据会得出完全错误的结论。
- 判据写法：`logcat -c` → 单击 → 等待 → 数协议号 + `LuaException` 计数 + 截图。
  见 `tools/drive2.sh`。

## 3. 存档与持久化

单文件 `/data/data/com.klab.lapis/shared_prefs/lapis_state.xml`（`ProtobufCore.java` 的
`getSharedPreferences("lapis_state", 0)`）。键族：

```
wal_*        货币（辉圣石/金币/体力）        goods_<id>   每个商品已购数量（→库存角标/售罄）
itm_*        获得的道具                      stage_*      关卡通关与星级
pvp_score    竞技场积分                       av_*         换装间（owned/mode/cur/bind/name）
```

- 全代码没有任何 `clear()` / `remove()` 动这个存储；唯一的 `.delete()` 是 `Seed` 删自己的临时投放件。
- 会丢存档的只有：卸载、`pm clear`、模拟器实例重置、**换签名的 APK**。同签名 `adb install -r` 不丢。
- 客户端侧的货币读 `PlayerInst`（种子字段 `diamondPay`），`items[]` 里塞 `P_*` 类型是无效的；
  功能解锁读 `Newbie`（等级或已通关卡）。

## 4. 商城：一次"看起来无解"的崩溃，根因是服务器时间戳

**症状**：主页点 購買部 → 7~8 次连续崩溃，商城 UI 完全不出现。崩溃栈固定：

```
LuaException: Object reference not set to an instance of an object.
  [C]: in function 'GetChildGameObject'
  PageShop.lua:555: in function 'InitScrollView'
  PageShop.lua:390: in function 'OnEnter'
  UIPanel.lua:216 DealWithEnter / :245 DealWithParentEnter / :231 DealWithEnter / :198 / :165
```

**走过的弯路（都被实测推翻，别再走）**：

1. 以为是 `UpdateTag` 的某个分支把 `SafeArea/Main/ScrollArea` `SetActive(false)` 掉了
   （`ScrollAreaMain` 与 `ScrollAreaGrid` 缓存的是同一个节点）。于是从数据侧改落地 tab：
   给一个 Type 6 行改 `TabIndex`、控制 `shopTab` 的**发射顺序**（`ShopManager.SetData` 是
   后写覆盖：`listAllIndex[TabIndex]=Type`、`listAllType[Type]=TabIndex`）。三种配置——落道具、
   落兑换所、让六个类型全部落同一个安全槽——**崩溃栈一字不变**。
2. 以为 prefab 缺节点。用 UnityPy 遍历：`PageShop/SafeArea/Main/ScrollArea` 存在、`active=True`、
   全树唯一；设备与主机 bundle 逐字节相同。排除。

**真因**：`OnUpdateSecond`。`shop.json` 每行的 `freshAt` 是**打包时刻**，早就过期；
`freshAt - 服务器时间 <= 0` 时客户端 `Fire("CloseRecharge")` → `OnBack()` → `Close()` →
`UIPanel.Purge` 把 `UIRootObject` 置 `nil`。`UpdateTag` 自己有 `if self.closed then return end`
挡这一手，`OnEnter` 没有，于是下一句 `InitScrollView` 的 `GetChildGameObject` 拿到 `nil` 抛 .NET 空引用。

**修法**：服务桩出口把每行 `freshAt` 强制写 `0`（含义"永不刷新"，JP 商店自己就用 `freshAt = 0`）。

**副作用（已知，可选修）**：每日限定不会隔天补货。要日切就在 `P1016`/`UpdateServerRefresh`
里回一个**未来**刷新点并按日期重置 `goods_*`，绝不能回过期时间戳。

## 5. 方法学：traceback 行号必须用字节码行表翻译

**ljd 反编译出来的 `.lua` 行号不是运行时行号**（本工程两次踩到，第二次才彻底纠正）。
运行时栈里的行号来自字节码自己的行表，必须直接读 `.bdl`：

```python
env = UnityPy.load(bundle)
for o in env.objects:
    if o.type.name == 'TextAsset':
        raw = o.get_raw_data()          # 序列化对象的原始字节
        # proto.debuginfo.addr_to_line_map 给每条指令的原始行号
```

`tools/pfind.py`（哪个函数覆盖哪段行号 + 它的字符串常量）、`tools/pseq.py`、`tools/palign2.py`
就是干这个的。有了它，"崩溃在哪一句"是**读出来的**，不是猜的。

## 6. 资源投喂：FUSE、权限与两个假象

- `adb push` 到已存在的 FUSE 目标**可能把目标删掉却仍报成功**。规矩：先 push 到
  `/data/local/tmp`，再 `cp` 进 `Android/data/.../files/`。
- `tar x` 解出来的目录是 `0770 shell`，app（other 位）没有 `x` → Unity 报
  `Unable to open archive file`。修：`find . -type d ! -perm -o=x -exec chmod o+x {} +`。
- **可选内容下载器还要目录写权限**：客户端用 `System.IO.File.Replace` 提交下载，只补 `o+x`
  会在传完 77 MB 后抛 `UnauthorizedAccessException`，而客户端把它报成"网络连接已断开"。
  只给 `videos/` 和 `videos/optional/` 两个目录补写权限，不要 mass-chmod。
- `.bdl` 必须配 40 字节大写 SHA-1 的 `.bdl.hash` 边车；文件权限 `0660` 不是拦截原因，别去动它。
- manifest 是 AES-CBC 的 gzip；换 bundle 要同时改它的 Hash 与 Size（`tools/manifest_repoint.py`）。
  **ShortHash 不是内容派生的，别动。** story 包根本不在 manifest 里，只需要换 `.bdl.hash`。
- manifest 的 `EncryptKey` 非零而文件是明文 UnityFS 时，报 `Unable to read header from archive file`
  ——把那个 int32 就地归零，就是卡面图全挂的根因。

## 7. 剧情文本的真实位置与重打包

- 关卡对白**不在语言表**里：631 个 `resources/story/*_scene.bdl` 各带一个 `_language` TextAsset，
  是 `{"Key":[...],"Value":[...]}` 的 JSON。总量 46,277 行，其中约 3.08 万行仍是日文。
- **UnityPy 的 `m_Script` 在这批资源上是有损的**：它按 UTF-8 解码，payload 却是 Shift-JIS，
  所有 CJK 变成 `?`。唯一可靠读法是 `obj.get_raw_data()` 里切出 JSON 文档。
  （这条坑差点让整批语料以乱码进入翻译流程。）
- 中文塞不进 Shift-JIS。回写时把 JSON 用 `ensure_ascii=True` 输出成 `\uXXXX` 转义：字节是纯 ASCII，
  在 utf-8/shift_jis/cp932 下都能解出同一串中文，编码问题直接消失。
- 保存必须用 `env.file.save('original')` 保住原压缩，否则体积涨 6 倍（223 KB → 1.37 MB）。

## 8. 简体中文管线

- 语言表装机版：30,687 行 + `Terms` 8 行，码点级 0 假名、0 U+FFFD。
- **字形闸门**：客户端字库不是 `glyphset.txt` 那份清单（日文原文自己就有 232 字在清单外且能显示）。
  判据是 `glyphset ∪ ASCII ∪ 该行的日文原文字符`。超出即豆腐块。
  这条闸门实际拦下了 27 条"词藻漂亮但字库没有"的用字（瑕／淇／噗／缥／萦／萃／哒／诶／彗／沁／痣／咻／嗖／×）。
- 交付格式：AI 工作流回传的是 `id<TAB>译文` 裸文本，长条目会甩出孤儿行。规则是先并回上一条再折叠断行
  （语言表的值里永远不该有换行）。
- 一致性：给翻译代理一份从已交付语料抽出的**锁定短句表**（JP→CN，4,201 条）+ 术语表 + 字库清单，
  而不是让它们读全量文件。

## 9. 验证纪律（这份文档里最值钱的一条）

- **控制台乱码不等于数据坏了**。先用受控实验确认（同一份数据走 Read 工具/写文件再读回来），
  再下结论。本工程两次把显示问题当成数据问题。
- 判据要能自己伪造输入：一个恒为 0 的计数器、一个按节拍发的日志行，都不算证据。
- 报数值要给噪声底：同一对象重复测量的差值，否则"提升了 3"没有意义。
- 说"某个原因排除了"之前，先确认你排除的是它在这条路径上的那个形态。
- 交付前剥脚手架：诊断文件门、SQL/RX/XE 探针、`hide_error_dialogs`、`javax.net.debug`、
  REQDIAG/SIGRAW/MemDump 一类的临时输出，全部从构建里去掉。

## 10. 页面身份只认协议号，不认截图

未映射的协议会被回一个全零响应，页面**照样渲染**，只是内容是空的。所以"这页开了"不等于"这页有数据"，
扫描结果必须记两件事：这次点击实际触发了哪个协议号、客户端在此期间报了几次异常。

- `P9000` 与 `P1021` 是 60 秒心跳。踩过的形状是"点了按钮 → 日志确实动了 → 判成通过"，
  而那两行只是心跳。任何"点击是否生效"的判定都要能把心跳排除掉。
- 美术牌上的可点区通常不在文字中心：实测牌面命中框比标签中心**偏右约 40 px**。
- 冷启动由桩自己的日志驱动而不是睡固定时长：睡 200 s 再盲点的那一版，在第二次重启时客户端其实还在
  标题页，后半程扫描报告的是它根本没到过的帧。

## 11. 客户端的门控只有两处：`PlayerInst` 与 `Newbie`

- 货币余额、拥有物一律读 `PlayerInst`。往 `items[]` 里塞一行是**惰**的——界面不会变。
  辉圣石这类付费货币要种在 `diamondPay`。
- 功能解锁读 `Newbie`：条件形态是"等级达标"或"某关已通过"。所以"某页进不去"先查 `Newbie`，
  不要去猜服务端的权限字段。
- 价格有两列，作用不同：`GoodsPrice` 只是角标显示，`CostValue` 才是 `GetCost` / 可负担判定 / 扣费用到的。
  两列不一致时，客户端会"显示 1980、扣 0"或反之。

## 12. 主数据在运行期是 SQLite，所以行为是数据侧可改的

`luaData/*.lua` 不是逻辑，是加载器：它们跑的实质是 `select * from X`。于是行为开关（某页是否可用、
某功能是否解锁）绝大多数是**数据侧**修法，不需要动代码段。

`Seed` 的自愈判据是**文件存在**，不是文件摘要匹配。所以要把一份改好的 `master_data.db` 弄上设备，
正确做法是"落到暂存 + `cp` 进应用目录"，而不是重编 APK——重编会让 pin 链条全部重来。

## 13. 服务器时间戳会让面板自我清除

`PageShop` 在 `OnEnter` 中途会因为 `freshAt` / `EndTime` 已经过期而把自己 purge 掉，
症状是"点进去闪一下就没了，且没有任何报错"。离线服务这两个字段一律回 `0`。
同理，客户端 traceback 的行号**必须用字节码行表翻译**，直接读 Lua 的行号会把你指到别的函数。

## 14. sidecar 与"缺失是完全静默的"

`.bdl` / `.bnk` 旁边那个 40 字节的摘要文件是加载门，不是元数据。两条实测规则：
`.bnk.hash` = 恰好 40 字节大写 SHA-1、**无**换行；`.bdl.hash` = **41 字节**（带换行）。
把两者"统一"会直接让资源不加载。

缺资源的表现分层：缺 SoundBank 是**整段静默**（不报错、不弹提示、日志无痕），缺 bundle 才有
`Unable to read header from archive file`。而且同一个症状字符串有两种根因：
manifest 里的 `EncryptKey` 是头部 XOR（非零 key + 明文 UnityFS 文件就是这个症状），
以及上游本来就 0 字节的那个 bundle——所以**先看大小，再看密钥**。

## 15. 证明"跑的那份就是我改的那份"

改完先证明产物含改动，再报结果或开始测量。三次不同的踩法：

1. 写盘可能静默失败（工具报了成功，文件内容没变）。要 `grep -c` 目标标识符回读**文件本体**。
2. 构建失败之后我还是装了：命令写成 `build > log; install` 的换行顺序，构建挂了 install 照跑，
   于是把上一轮旧 APK 装进设备当成新包测，`adb` 还回了 `Install command complete`。
   **装机必须是构建成功的同一条件链**（`build && install && test`），装完再比包内资产摘要与
   dex 里的新字面量——`Install command complete` 只证明装了一个包，不证明装的是这个包。
3. 改了脚本后立刻在旧状态上量，得到"改前改后一模一样"，据此判死了正确的方案。

对应的构建性质：构建**不是逐位可复现**（zip 时间戳进包），所以整包哈希不能当身份，只能比包内资产。

## 16. 判定手段本身要先验证

- 用差值判"变好了"之前，先给出同对象重复测量的**噪声底**；两次同帧的差就是这条阈值。
- 掩体饱和的对比不算证据（整屏差异 = 什么都没分辨出来）。
- 最优解贴在搜索边界上时，它否证的是当前模型，不是"找到了答案"。
- 守卫的控制组必须能**自己伪造**被它拦的那种输入；"旧版本应该会被拦"不是控制。
- 恒为 0 的计数器、按节拍发的日志行、失效的 CSS 选择器，都会安静地通过。
