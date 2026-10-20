import sqlite3, re, json
jp = sqlite3.connect('file:C:/lapisbuild/jp_lang.db?mode=ro', uri=True)
cn = sqlite3.connect('file:C:/lapisbuild/cn/out/master_data_lang.db?mode=ro', uri=True)
m = sqlite3.connect('file:C:/lapisbuild/chk_dev.db?mode=ro', uri=True)
J = dict((i, v or '') for i, v in jp.execute('select ID,Value from Language'))
C = dict(cn.execute('select ID,Value from Language'))

def pair(i):
    return (J.get(i, ''), C.get(i, ''))

lines = []
lines.append('# Lapis Re:LiGHTs 简中剧情术语表（由已上机验证的语言表提取，翻译时必须沿用）\n')
lines.append('## 魔女（角色名）\n')
for rid, name_id in m.execute('select ID,Name from CharacterRole order by ID'):
    ja, zh = pair(name_id)
    en = m.execute('select Enname from CharacterRole where ID=?', (rid,)).fetchone()[0]
    if zh:
        lines.append('- %s（%s）→ **%s**' % (ja.strip(), en, zh.strip()))
lines.append('\n## 组合（unit 名）\n')
for tid, name_id in m.execute('select ID,Name from CharacterTeam order by ID'):
    ja, zh = pair(name_id)
    if zh:
        lines.append('- %s → **%s**' % (ja.strip(), zh.strip()))
KANA = re.compile(u'[\u3041-\u3096\u30a1-\u30fa]')
lines.append('\n## 高频系统词（JP → 已用简中，勿另造）\n')
seen = {}
for i, k, v in jp.execute('select ID,Key,Value from Language'):
    if not k or not v:
        continue
    z = C.get(i, '')
    if not z or KANA.search(z):
        continue
    if len(v) <= 14 and len(z) <= 10:
        seen.setdefault(v.strip(), z.strip())
term_keys = [t for t in ('開花', '覚醒', '潜在能力', '親愛度', '輝聖石', 'スター', '召喚', '應援', '応援会', '魔獣', '衣装', '装備', 'ストーリー', 'メイン', '課題', 'ポイント', 'チケット', '日付', 'スタミナ', 'バトル') if t in seen]
for t in term_keys:
    lines.append('- %s → **%s**' % (t, seen[t]))
extra = [('サポート', '支援'), ('チケット', '券'), ('ガチャ', '召唤'), ('ストーリー', '剧情')]
lines.append('\n## 约定\n')
lines.append('- 玩家扮演的是「先生」（老师），魔女们称呼主角为 先生／老师，语气按角色性格区分。')
lines.append('- 保留所有富文本标签与占位符原样：`<size=..>` `<color=#xxxxxx>` `</size>` `%s` `%d` `{ArgInt}` `\n`。')
lines.append('- 标点用中文全角，句末不加多余句号；拟声词、语气词按角色口吻处理。')
lines.append('- 译文一行一条，`id<TAB>译文`，条数与顺序必须和源文件完全一致。')
open('story_cn/GLOSSARY.md', 'w', encoding='utf-8', newline='').write('\n'.join(lines) + '\n')
print('glossary lines', len(lines))
