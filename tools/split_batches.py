import sqlite3, re, os, json

JPDB = 'file:C:/lapisbuild/jp_lang.db?mode=ro'
CNDB = 'file:C:/lapisbuild/cn/out/master_data_lang.db?mode=ro'
OUT = 'story_cn'
KANA = re.compile(u'[\u3041-\u3096\u30a1-\u30fa]')
# Narrative prose test: JP sentence punctuation. Short UI labels ("battle start", "confirm") are
# excluded because they are already terse and correct; the premium pass is for lines people read.
PROSE = re.compile(u'[\u3002\uff1f\uff01\u300c\u300d\u300e\u300f\uff1a]')

jp = sqlite3.connect(JPDB, uri=True)
cn = sqlite3.connect(CNDB, uri=True)
CV = dict(cn.execute('select ID,Value from Language'))

rows = []
for i, k, v in jp.execute('select ID,Key,Value from Language'):
    v = v or ''
    if KANA.search(v) and (PROSE.search(v) or len(v) >= 26):
        rows.append((i, v, CV.get(i) or ''))
rows.sort()

B = 250
manifest = []
for n in range(0, len(rows), B):
    part = rows[n:n + B]
    idx = n // B + 1
    src = os.path.join(OUT, 'batch_%02d_src.tsv' % idx)
    ref = os.path.join(OUT, 'batch_%02d_ref.tsv' % idx)
    with open(src, 'w', encoding='utf-8', newline='') as f:
        for i, v, o in part:
            f.write('%d\t%s\n' % (i, v.replace('\n', ' ')))
    with open(ref, 'w', encoding='utf-8', newline='') as f:
        for i, v, o in part:
            f.write('%d\t%s\n' % (i, (o or '−').replace('\n', ' ')))
    manifest.append({'batch': idx, 'first': part[0][0], 'last': part[-1][0], 'rows': len(part),
                     'src': src, 'out': os.path.join(OUT, 'batch_%02d_cn.tsv' % idx)})

json.dump(manifest, open(os.path.join(OUT, 'batches.json'), 'w', encoding='utf-8'), indent=1)
open(os.path.join(OUT, 'ids.txt'), 'w', encoding='utf-8').write('\n'.join(str(r[0]) for r in rows))
print('rows', len(rows), 'batches', len(manifest))
