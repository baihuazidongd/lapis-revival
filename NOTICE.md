# 材料与交付边界 / Materials and delivery boundaries

**中文**
本仓库只包含本工程自行编写的代码、脚本与文档：Android 侧的本地兼容服务桩（Java）、生成与校验数据的
工具脚本、以及研究记录文档。不包含原官服源代码，也不包含任何游戏内容。

不随仓库提供（也不要以本仓库为来源分发）：APK 与 AssetBundle、SoundBank、主数据库与语言表内容、
图片/音频/视频、从客户端提取或反编译的代码（Lua、IL2CPP dump、smali）、协议 descriptor 二进制、
密钥与账号材料、抓包、截图、私有运行日志。仓库内的 `.gitignore` 已按扩展名把这些挡在提交之外。

`manifests/` 里只有我们自己计算的期望摘要（SHA-1），用于让部署者核对自己手里的文件，
不指回任何原始内容。

项目名与作品名仅用于说明本兼容研究的对象，不代表由原发行方提供、授权或认可。
本仓库自写的代码、脚本与文档以 **MIT 许可**开源（见 `LICENSE`）：任何人可出于任何目的使用、复制、
修改、合并、发布、分发、再许可、出售，无需另行授权。该授权只覆盖本仓库里我们自己写出来的东西，
**不覆盖也不可能覆盖任何第三方游戏内容**——客户端 APK、AssetBundle、SoundBank、主数据与语言表、
美术/音频/视频，以及从客户端提取或反编译的代码；那些权利仍归原权利人。

**English**
This repository contains only code, tooling and documentation written for this project: the on-device
local compatibility stub (Java), the scripts that generate and verify data, and the research notes.
It contains no original server source code and no game content.

Not included, and not to be distributed from here: the APK and AssetBundles, sound banks, the master
and language databases, images/audio/video, code extracted or decompiled from the client (Lua, IL2CPP
dumps, smali), protocol descriptor binaries, keys and account material, packet captures, screenshots,
private run logs. The `.gitignore` blocks these by extension.

`manifests/` holds only digests we computed ourselves, so a deployer can check files they already own.
The project and title names identify the target of this interoperability study only; they are not
provided, authorised or endorsed by the original publisher.

The code, scripts and documents we authored in this repository are open under the **MIT License**
(see `LICENSE`): anyone may use, copy, modify, merge, publish, distribute, sublicense and sell it for
any purpose, without asking. That grant covers only what we wrote here. It does not and cannot cover
any third-party game content - the client APK, AssetBundles, sound banks, master and language
databases, art/audio/video, or code extracted or decompiled from them; those rights remain with their owners.

**日本語**
このリポジトリには本プロジェクト自作のコード・スクリプト・ドキュメントのみを収録します（端末内の
ローカル互換スタブ（Java）、データ生成・検証用スクリプト、研究記録）。元サーバーのソースコードも、
ゲームコンテンツも一切含みません。

同梱せず、ここからの配布もしないもの：APK と AssetBundle、SoundBank、マスター／言語データベース、
画像・音声・動画、クライアントから抽出／デコンパイルしたコード（Lua、IL2CPP ダンプ、smali）、
プロトコル descriptor バイナリ、鍵とアカウント情報、パケットキャプチャ、スクリーンショット、
実行ログ。`.gitignore` が拡張子レベルでこれらを除外します。

`manifests/` は自作の期待値ダイジェスト（SHA-1）だけで、配布者が自身の持つファイルを検証するためものです。
プロジェクト名と作品名は相互運用研究の対象を示すためのものであり、元パブリッシャーによる提供・許諾・
後援を示すものではありません。

本リポジトリで自作したコード・スクリプト・ドキュメントは **MIT ライセンス**（`LICENSE` 参照）で公開します：
誰でも目的を問わず使用・複製・変更・統合・出版・配布・再ライセンス・売却できます（個別許可は不要です）。
この許諾はここで自作した部分にのみ及びます。クライアント APK、AssetBundle、SoundBank、マスター／言語データベース、
画像・音声・動画、およびクライアントから抽出／デコンパイルしたコードなど、第三者のゲームコンテンツには及ばず、
それらの権利は元の権利者に帰属します。
