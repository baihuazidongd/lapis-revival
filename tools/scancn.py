import UnityPy, json, pathlib, re, io
ROOT = pathlib.Path('C:/lapisbuild/device_files/files/JP/AssetBundles/assets/products/resources/story')
KANA = re.compile(u'[\u3041-\u3096\u30a1-\u30fa]')
out = io.open('scn_lang_scan.txt', 'w', encoding='utf-8')
tot = cn = jp = other = 0
lines_cn = lines_jp = 0
jp_bundles = []
for p in sorted(ROOT.glob('*.bdl')):
    try:
        env = UnityPy.load(str(p))
    except Exception as e:
        out.write('LOADFAIL %s %s\n' % (p.name, str(e)[:60])); continue
    tot += 1
    vals = []
    for o in env.objects:
        if o.type.name != 'TextAsset':
            continue
        d = o.read()
        if not d.m_Name.endswith('_language'):
            continue
        raw = o.get_raw_data()
        i = raw.find(b'{"Key"')
        if i < 0:
            break
        blob = raw[i:raw.rfind(b'}') + 1]
        doc = None
        for enc in ('utf-8', 'shift_jis', 'cp932', 'gbk'):
            try:
                doc = json.loads(blob.decode(enc))
                break
            except Exception:
                continue
        if doc:
            vals = [v for v in doc.get('Value', []) if v]
        break
    if not vals:
        other += 1
        out.write('NOLANG\t%s\n' % p.name)
        continue
    k = sum(1 for v in vals if KANA.search(v))
    if k == 0:
        cn += 1; lines_cn += len(vals)
    elif k > len(vals) * 0.5:
        jp += 1; lines_jp += k; jp_bundles.append((p.name, k, len(vals)))
    else:
        other += 1; out.write('MIXED\t%s\tkana %d/%d\n' % (p.name, k, len(vals)))
out.write('BUNDLES %d  all-CN %d (lines %d)  JP-majority %d (kana lines %d)  other %d\n'
          % (tot, cn, lines_cn, jp, lines_jp, other))
for n, k, t in jp_bundles[:60]:
    out.write('JP\t%s\tkana %d/%d\n' % (n, k, t))
out.close()
print('bundles %d, CN %d, JP %d, other %d' % (tot, cn, jp, other))
