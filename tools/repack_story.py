#!/usr/bin/env python3
"""Replace one story scene's dialogue with the Chinese pass and re-pack its bundle.

Story scenes ship their text as a `_language` TextAsset holding a plain JSON object with parallel
`Key`/`Value` arrays, encoded Shift-JIS. Chinese glyphs are not representable in Shift-JIS, so the
new payload is written with `ensure_ascii=True`: every non-ASCII character becomes a `\\uXXXX`
escape, the bytes are pure ASCII (therefore valid under whatever encoding the loader picks), and the
JSON parser on the other side reconstructs the Chinese. Only `Value` is touched - `Key` is what the
scene script indexes by, and a reordered or re-lengthened array would break the scene.

The bundle is gated by its 40-byte `.bdl.hash` sidecar, not by the resource manifest (the manifest
has no `story/` records at all), so the caller pushes both files.
"""
import json
import pathlib
import re
import sys

import UnityPy

# U+30FB is the middle dot that CN names use (学院・食堂): punctuation, not kana.
KANA = re.compile(u'[\u3040-\u30fa\u30fc-\u30ff]')

bundle, cnfile, out = sys.argv[1], sys.argv[2], sys.argv[3]

lines = []
for n, raw in enumerate(pathlib.Path(cnfile).read_text(encoding='utf-8').splitlines()):
    if not raw.strip():
        continue
    idx, _, text = raw.partition('\t')
    if not idx.isdigit():
        sys.exit('%s:%d index is not numeric: %r' % (cnfile, n + 1, raw[:24]))
    if KANA.search(text):
        sys.exit('%s:%d still has kana' % (cnfile, n + 1))
    lines.append((int(idx), text))

env = UnityPy.load(bundle)
hit = None
for obj in env.objects:
    if obj.type.name == 'TextAsset' and obj.read().m_Name.endswith('_language'):
        hit = obj
        break
if hit is None:
    sys.exit('no _language TextAsset in %s' % bundle)
doc = hit.read()
# m_Script is lossy here (UnityPy decodes as UTF-8, several of these payloads are Shift-JIS), so
# read the serialized object's own bytes and slice at the JSON document.
raw = hit.get_raw_data()
i = raw.find(b'{"Key"')
if i < 0:
    sys.exit('%s: no JSON document inside the _language payload' % bundle)
raw = raw[i:raw.rfind(b'}') + 1]
j = None
for enc in ('utf-8', 'shift_jis', 'cp932', 'gbk'):
    try:
        j = json.loads(raw.decode(enc))
        break
    except Exception:
        continue
if j is None:
    sys.exit('%s: _language payload is not decodable' % bundle)
if len(lines) != len(j['Value']):
    sys.exit('cn file has %d records, bundle has %d lines' % (len(lines), len(j['Value'])))
if [i for i, _ in lines] != list(range(len(lines))):
    sys.exit('cn indices are not 0..n-1 in order')

for i, text in lines:
    old = j['Value'][i]
    for token in re.findall(r'\\[ns]|<[^>]*>|\[[A-Z_]+\]|%[sd]', old):
        # A ruby tag carries a Japanese reading (フォーリナー above 来訪者); with the zero-kana rule it
        # has no CN equivalent, so the wrapper is dropped together with its reading. Exempt the whole
        # ruby tag family, opening and closing, from the "must survive" check.
        if KANA.search(token) or 'ruby' in token.lower():
            continue
        if token not in text and not (token == '\\n' and text.endswith('。')):
            sys.exit('line %d dropped the %r token' % (i, token))
    j['Value'][i] = text

payload = json.dumps(j, ensure_ascii=True, separators=(',', ':')).encode('ascii')
doc.m_Script = payload.decode('latin-1')
doc.save()
pathlib.Path(out).write_bytes(env.file.save('original'))
data = pathlib.Path(out).read_bytes()
import hashlib
print('repacked %s -> %s (%d bytes, was %d)' % (pathlib.Path(bundle).name, out, len(data), len(raw)))
print('sha1 %s' % hashlib.sha1(data).hexdigest().upper())
