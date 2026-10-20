#!/usr/bin/env python3
"""Repack and (optionally) push translated story scenes back into their bundles.

`split_scn.py` emitted one `scn_NNN_src.tsv` per batch with rows `row<TAB>sceneLineCount<TAB>Key<TAB>JP`
and a `scenes.json` that says which bundles each batch covers, in the same order. The translation comes
back as `row<TAB>中文`. This stitches those rows back into each bundle's `Key`/`Value` JSON - a batch
spans several scenes and a scene is never split across batches - writes the payload with
`ensure_ascii=True` so the bytes are pure ASCII (Chinese cannot be encoded in Shift-JIS, which is what
several of these bundles use), saves with the bundle's own compression, and refreshes the 40-byte
`.bdl.hash` sidecar that gates the load. Story bundles have no resource-manifest record, so there is
nothing to re-point.

    python ship_scn.py scn_001_cn.tsv [scn_002_cn.tsv ...] [--push]
"""
import json
import pathlib
import re
import subprocess
import sys

import UnityPy

STORY_SRC = pathlib.Path('C:/lapisbuild/device_files/files/JP/AssetBundles/assets/products/resources/story')
OUT_DIR = pathlib.Path(r'E:/lapis/work/story_scn')
STAGED = pathlib.Path('C:/lapisbuild/scn_staged')
ADB = r'C:/Android/Sdk/platform-tools/adb.exe'
SERIAL = 'emulator-5560'
DEVICE_DIR = '/sdcard/Android/data/com.klab.lapis/files/JP/AssetBundles/assets/products/resources/story'
KANA = re.compile(u'[\u3040-\u30ff]')

push = '--push' in sys.argv
names = [a for a in sys.argv[1:] if not a.startswith('--')]
if not names:
    sys.exit('usage: ship_scn.py scn_NNN_cn.tsv [...] [--push]')

manifest = json.load((OUT_DIR / 'scenes.json').open(encoding='utf-8'))
by_batch = {m['batch']: m for m in manifest}
STAGED.mkdir(exist_ok=True)

env_cache = {}


def language_asset(bundle):
    key = bundle.name
    if key not in env_cache:
        env = UnityPy.load(str(bundle))
        for obj in env.objects:
            if obj.type.name == 'TextAsset' and obj.read().m_Name.endswith('_language'):
                d = obj.read()
                raw = d.m_Script
                if isinstance(raw, str):
                    raw = raw.encode('latin-1', 'replace')
                j = None
                for enc in ('utf-8', 'shift_jis', 'cp932', 'gbk'):
                    try:
                        j = json.loads(raw.decode(enc))
                        break
                    except Exception:
                        continue
                if j is None:
                    sys.exit('%s: undecodable _language' % bundle.name)
                env_cache[key] = (env, obj, j)
                return env_cache[key]
        sys.exit('%s: no _language TextAsset' % bundle.name)
    return env_cache[key]


for arg in names:
    path = pathlib.Path(arg)
    if not path.is_absolute():
        path = OUT_DIR / arg
    rows = []
    for n, line in enumerate(path.read_text(encoding='utf-8').splitlines()):
        if not line.strip():
            continue
        idx, _, text = line.partition('\t')
        if not idx.isdigit():
            sys.exit('%s:%d bad row index %r' % (path.name, n + 1, idx))
        if KANA.search(text):
            sys.exit('%s:%d still has kana' % (path.name, n + 1))
        rows.append((int(idx), text))
    num = int(re.search(r'(\d+)', path.name).group(1))
    entry = by_batch.get(num)
    if entry is None:
        sys.exit('scenes.json has no batch %d' % num)
    if len(rows) != entry['rows'] or [i for i, _ in rows] != list(range(entry['rows'])):
        sys.exit('%s has %d rows, manifest expects %d (or indices out of order)'
                 % (path.name, len(rows), entry['rows']))

    pos = 0
    for scene in entry['scenes']:
        take = rows[pos:pos + scene['lines']]
        pos += scene['lines']
        bundle = STORY_SRC / scene['bundle']
        env, obj, j = language_asset(bundle)
        if j['Value'] and scene['asset'] not in obj.read().m_Name:
            sys.exit('%s: asset name drifted' % bundle.name)
        values = [t for _, t in take]
        for i, v in enumerate(values):
            old = j['Value'][i]
            for token in re.findall(r'<[^>]*>|\[[A-Z_]+\]|%[sd]|\\n', old):
                if token not in v:
                    sys.exit('%s line %d dropped token %r' % (bundle.name, i, token))
        j['Value'] = values
        d = obj.read()
        payload = json.dumps(j, ensure_ascii=True, separators=(',', ':')).encode('ascii')
        d.m_Script = payload.decode('latin-1')
        d.save()
        out = STAGED / bundle.name
        out.write_bytes(env.file.save('original'))
        sha1 = __import__('hashlib').sha1(out.read_bytes()).hexdigest().upper()
        (STAGED / (bundle.name + '.hash')).write_text(sha1, encoding='ascii')
        print('%-34s %8d -> %8d  %s' % (bundle.name, bundle.stat().st_size, out.stat().st_size, sha1[:12]))

if push:
    env = dict(A=__import__('os').environ)
    env['MSYS_NO_PATHCONV'] = '1'
    env['MSYS2_ARG_CONV_EXCL'] = '*'
    import os
    for f in sorted(STAGED.iterdir()):
        subprocess.run([ADB, '-s', SERIAL, 'push', str(f).replace('\\', '/'), '/data/local/tmp/' + f.name],
                       check=True, capture_output=True, env=env)
    subprocess.run([ADB, '-s', SERIAL, 'shell',
                    'cd /data/local/tmp && for f in %s; do cp -f "$f" %s/"$f"; done'
                    % (' '.join(p.name for p in STAGED.iterdir()), DEVICE_DIR)], check=True, env=env)
    print('pushed %d files' % len(list(STAGED.iterdir())))
else:
    print('staged only (pass --push to install on device)')
