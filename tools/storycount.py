import UnityPy, json, glob, sys, pathlib
root = pathlib.Path('C:/lapisbuild/device_files/files/JP/AssetBundles/assets/products/resources/story')
files = sorted(p for p in root.glob('*.bdl'))
tot = 0; lines = 0; chars = 0; bad = []
out = open('C:/lapisbuild/story_text_inventory.txt', 'w', encoding='utf-8')
for i, p in enumerate(files):
    try:
        env = UnityPy.load(str(p))
        n = 0; c = 0
        for o in env.objects:
            d = o.read()
            if type(d).__name__ == 'TextAsset' and d.m_Name.endswith('_language'):
                b = d.m_Script
                if isinstance(b, str): b = b.encode('latin-1', 'replace')
                j = json.loads(b.decode('shift_jis', 'replace'))
                vals = j.get('Value', [])
                n = len(vals); c = sum(len(v) for v in vals)
        tot += 1; lines += n; chars += c
        out.write('%s\t%d\t%d\n' % (p.name, n, c))
    except Exception as e:
        bad.append((p.name, str(e)[:80]))
out.write('BUNDLES_WITH_LANGUAGE\t%d\nLINES\t%d\nCHARS\t%d\nFAILED\t%d\n' % (tot, lines, chars, len(bad)))
for b in bad[:20]: out.write('BAD\t%s\n' % (b,))
out.close()
print('done', tot, lines, chars, len(bad))
