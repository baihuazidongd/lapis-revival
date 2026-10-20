#!/usr/bin/env python3
"""Split every story scene's dialogue into translation batches.

The scenario text is not in the Language table: each `resources/story/*_scene.bdl` carries a
`_language` TextAsset with parallel Key/Value arrays (Shift-JIS JSON), 631 bundles and ~46k lines in
total. This walks them, keeps the speaker/scene identity attached to every line (a bare line list
loses who is talking, which is the difference between a localization and a word swap), and emits
`story_scn/scn_NN_src.tsv` plus a `scenes.json` manifest the repack step reads to put each batch back
into its own bundle.

Bundles are grouped whole - a scene is never split across two batches, because a half-translated
scene repacks as a half-translated scene.
"""
import json
import pathlib
import sys

import UnityPy

ROOT = pathlib.Path('C:/lapisbuild/device_files/files/JP/AssetBundles/assets/products/resources/story')
OUT = pathlib.Path(r'E:/lapis/work/story_scn')
MAX_PER_BATCH = 240

OUT.mkdir(parents=True, exist_ok=True)
scenes = []
for bdl in sorted(ROOT.glob('*.bdl')):
    try:
        env = UnityPy.load(str(bdl))
    except Exception as e:
        print('LOAD FAIL', bdl.name, str(e)[:60])
        continue
    for obj in env.objects:
        if obj.type.name != 'TextAsset' or not obj.read().m_Name.endswith('_language'):
            continue
        # m_Script is lossy here: UnityPy decodes the payload as UTF-8 and this text is
        # Shift-JIS, so every CJK line comes back as '?' replacement characters. The only
        # faithful read is the serialized object's own bytes, sliced at the JSON document.
        raw = obj.get_raw_data()
        i = raw.find(b'{"Key"')
        if i < 0:
            break
        raw = raw[i:raw.rfind(b'}') + 1]
        j = None
        for enc in ('utf-8', 'shift_jis', 'cp932', 'gbk'):
            try:
                j = json.loads(raw.decode(enc))
                break
            except Exception:
                continue
        if j is None:
            j = json.loads(raw.decode('shift_jis', 'replace'))
        vals = j.get('Value', [])
        if vals:
            scenes.append({'bundle': bdl.name, 'asset': obj.read().m_Name, 'lines': len(vals),
                           'keys': j['Key'], 'values': vals})
        break

print('scenes %d, lines %d' % (len(scenes), sum(s['lines'] for s in scenes)))

batch, batches = [], []
used = 0
for s in scenes:
    if used and used + s['lines'] > MAX_PER_BATCH:
        batches.append(batch)
        batch, used = [], 0
    batch.append(s)
    used += s['lines']
if batch:
    batches.append(batch)

manifest = []
for n, group in enumerate(batches, 1):
    src = OUT / ('scn_%03d_src.tsv' % n)
    with src.open('w', encoding='utf-8', newline='\n') as f:
        row = 0
        for s in group:
            for k, v in zip(s['keys'], s['values']):
                f.write('%d\t%d\t%s\t%s\n' % (row, s['lines'], k, v.replace('\n', ' ')))
                row += 1
    manifest.append({'batch': n, 'rows': row, 'out': str(OUT / ('scn_%03d_cn.tsv' % n)),
                     'scenes': [{'bundle': s['bundle'], 'asset': s['asset'], 'lines': s['lines']} for s in group]})
    print('batch %03d rows %d scenes %d' % (n, row, len(group)))

json.dump(manifest, (OUT / 'scenes.json').open('w', encoding='utf-8'), ensure_ascii=False, indent=1)
print('wrote %d batches -> %s' % (len(batches), OUT / 'scenes.json'))
