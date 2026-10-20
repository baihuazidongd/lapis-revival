#!/usr/bin/env python3
"""Emit the JA->Simplified-Chinese translation worklist as one markdown file.

All Japanese payload text is spliced straight out of the sqlite masters by this script; nothing
player-visible is typed into a tool payload, which is the only reliable way to keep CJK intact
here. The Chinese scaffolding below is short on purpose so it can be proofread after the write.

Layout of the output:
  rules -> high-frequency short words (glossary seed) -> keyed entries grouped by Key prefix ->
  keyless entries in ID order -> Terms (four long legal documents, fenced).

Entry line format is TAB separated and needs no escaping: the Language table contains no tabs and
no real newlines (verified), so `ID<TAB>Key<TAB>text` round-trips byte-for-byte.
"""
import re
import sqlite3
from collections import Counter, defaultdict
from pathlib import Path

RES = Path(r'E:/lapis/revival/local/resources')
OUT = Path(r'E:/lapis/translate/JA-ZH_ALL.md')
CJK = re.compile(r'[\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff\uff66-\uff9f]')

RULES = '''# 宝石幻想 Lapis Re:LiGHTs 日文→简体中文 翻译清单

本文件由脚本从游戏主数据直接导出，共 **@@N@@** 条待译文本。请**整份**按下面的规则处理。

## 输出格式（务必严格遵守）

1. 每条一行：`ID<TAB>简体中文`。ID 用制表符与译文分隔，**不要**重复原文，不要加序号、引号、markdown 表格或任何解释。
2. 只输出译文行，不要输出前言、总结、校对说明。
3. ID 必须与本文件完全一致（数字，不要补零、不要改动）。
4. 第 3 部分（Terms）是长文档，用 `=== BEGIN 名称 ===` / `=== END 名称 ===` 原样包裹，中间只放译文。

## 翻译规则

- 目标：**简体中文**（zh-Hans），不要出现假名或日文汉字写法（例：`確認`→`确认`，`取り消し`→`取消`）。
- 占位符与富文本标签**原样保留、不得翻译、不得改动大小写**：`%s` `%d` `%.1f` `%%` `<color=#xxxxxx>…</color>` `<size=…>` `<b>` `<i>` `<br>` `<nobr>`。标签必须成对、数量与原文一致。
- 原文没有换行，就不要加换行。
- 数字、全角符号（`！` `？` `※` `・` `ー`）保持原有风格；片假名人名与团体名一律按「术语表」的统一译名处理，术语表里没有的先补进术语表再翻译。
- 按钮/标签类（`Btn_`、短词）控制在 **6 个汉字以内**；标题类控制在 **10 个汉字以内**；描述类不限，但尽量不超过原文长度的 1.2 倍（UI 框体宽度有限）。
- 语气：本作是偶像养成游戏，角色第一人称台词保持口语、有少女感；系统提示保持简洁书面语；战斗技能描述使用游戏常用术语（伤害/暴击/回复/增益/减益/连携）。
- 遇到 `｜`（全角竖线）用于对话标注时保留。
- 不翻译：纯 ASCII 词条（本清单已剔除）、玩家名占位、URL、代码片段。
- 同一原文在多处出现时只出现一次（已去重），请给出**通用**译法。

## 术语一致性

下面的「高频短词」和 `## 术语表` 请**先**统一译法，后文全部沿用。同一 Key 前缀内的词条属于同一界面，请保持风格一致。

'''

GLOSSARY_HEAD = '''---

## 术语表（请先填写，后文沿用）

游戏专有名词。日文列已给出，请在译文列填入统一简中译名。

```
日文	简体中文
'''

SHORTWORD_NOTE = '''---

## 高频短词（出现次数＝同一文本被多少个词条引用）

这些是最影响整体观感的界面词，请先给出统一译法。

```
ID	Key	原文	引用数
'''


def load():
    c = sqlite3.connect(str(RES / 'master_data_lang.db'))
    c.text_factory = str
    rows = c.execute('select ID, Key, Value from Language order by ID').fetchall()
    terms = c.execute('select ID, Key, Value from Terms order by ID').fetchall()
    return rows, terms


def main():
    rows, terms = load()
    # representative row per distinct value: smallest ID, first non-empty Key seen
    best = {}
    refcount = Counter()
    for i, k, v in rows:
        if not v or not v.strip():
            continue
        if not CJK.search(v):
            continue
        refcount[v] += 1
        if v not in best:
            best[v] = (i, k or '')
    uniq = sorted(best.items(), key=lambda kv: kv[1][0])
    keyed = [(v, iid, k) for v, (iid, k) in uniq if k]
    keyless = [(v, iid, k) for v, (iid, k) in uniq if not k]

    lines = [RULES.replace('@@N@@', str(len(uniq)))]

    # ---- glossary: derived from the data, never hand-typed, so nothing can be corrupted ----
    # Katakana-only short values are this game's proper nouns (character and group names);
    # anything hanging off a *Name* key is a name too. Both need one fixed rendering everywhere.
    kata = re.compile(r'^[\u30a1-\u30ff\uff66-\uff9f\u30fc]+$')
    gloss = {}
    for v, (iid, k) in best.items():
        if (kata.match(v) and 3 <= len(v) <= 10) or re.search(r'(^|_)Name', k or ''):
            gloss.setdefault(v, (iid, k or '-'))
    lines.append(GLOSSARY_HEAD)
    for v in sorted(gloss, key=lambda x: (-refcount[x], len(x), gloss[x][0]))[:120]:
        lines.append('%s\t' % v)
    lines.append('```\n')

    # ---- high frequency short words ----
    shorts = sorted(((v, best[v][0], best[v][1], refcount[v]) for v in best
                     if len(v) <= 6 and refcount[v] >= 4), key=lambda x: -x[3])[:120]
    lines.append(SHORTWORD_NOTE)
    for v, iid, k, n in shorts:
        lines.append('%d\t%s\t%s\t%d' % (iid, k or '-', v, n))
    lines.append('```\n')

    # ---- part 1: keyed, grouped by key prefix ----
    groups = defaultdict(list)
    for v, iid, k in keyed:
        groups[k.split('_')[0]].append((iid, k, v))
    lines.append('---\n\n## 第 1 部分　带 Key 的词条（按界面模块分组）\n')
    for pref in sorted(groups, key=lambda p: (-len(groups[p]), p)):
        g = groups[pref]
        lines.append('### %s　%d 条\n' % (pref, len(g)))
        lines.append('```\nID\tKey\t原文')
        for iid, k, v in sorted(g):
            lines.append('%d\t%s\t%s' % (iid, k, v))
        lines.append('```\n')

    # ---- part 2: keyless, in ID order, chunked ----
    lines.append('---\n\n## 第 2 部分　无 Key 的词条（运行时按 ID 取用，按 ID 升序）\n')
    for start in range(0, len(keyless), 400):
        chunk = keyless[start:start + 400]
        lines.append('### ID %d–%d　%d 条\n' % (chunk[0][1], chunk[-1][1], len(chunk)))
        lines.append('```\nID\t原文')
        for v, iid, k in chunk:
            lines.append('%d\t%s' % (iid, v))
        lines.append('```\n')

    # ---- part 3: legal documents ----
    lines.append('---\n\n## 第 3 部分　Terms（用户协议等长文档，译文用相同标记包裹）\n')
    seen = []
    for idx, (iid, k, v) in enumerate(terms):
        if not v:
            continue
        twin = next((p for p in seen if p[2] == v), None)
        if twin:
            lines.append('（`%s` 与 `%s` 内容完全相同，沿用其译文即可）\n' % (k, twin[1]))
            continue
        seen.append((iid, k, v))
        body = v.replace('\r\n', '\n')
        lines.append('=== BEGIN %s (ID %d, %d 字) ===\n' % (k, iid, len(body)))
        lines.append(body)
        lines.append('=== END %s ===\n' % k)

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text('\n'.join(lines) + '\n', encoding='utf-8')
    data = OUT.read_bytes()
    print('unique=%d keyed=%d keyless=%d shortwords=%d' % (len(uniq), len(keyed), len(keyless), len(shorts)))
    print('groups=%d' % len(groups))
    print('wrote %s  %d bytes  %d lines' % (OUT, len(data), data.count(b'\n') + 1))


if __name__ == '__main__':
    main()
