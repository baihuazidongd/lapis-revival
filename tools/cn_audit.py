#!/usr/bin/env python
"""cn_audit.py LANG.db — code-point audit of the language table actually installed on the device.

ASCII on stdout on purpose: the numbers are the verdict, and pushing CJK back out through the
Windows console (gbk) or through adb is where text gets mangled. Any JP left on screen after this
reports zero is baked art, a hard-coded Lua string, or a scenario video - not the data file.
"""
import re
import sqlite3
import sys

path = sys.argv[1]
c = sqlite3.connect(path)
c.text_factory = lambda b: b.decode('utf-8', 'replace')

KANA = re.compile(r'[\u3040-\u30ff]')

rows = c.execute('select count(*) from Language').fetchone()[0]
kana_ids = [r[0] for r in c.execute('select ID,Value from Language')
             if r[1] and KANA.search(r[1])]
story = c.execute('select count(*) from Language where ID>=20000000').fetchone()[0]
story_kana = len([1 for i, v in c.execute('select ID,Value from Language where ID>=20000000')
                  if v and KANA.search(v)])
terms = c.execute('select count(*) from Terms').fetchone()[0]
terms_kana = len([1 for v, in c.execute('select Value from Terms') if v and KANA.search(v)])

print('lang rows            =', rows)
print('rows with kana       =', len(kana_ids), kana_ids[:10])
print('story block (ID>=2e7)=', story, 'of which kana-bearing =', story_kana)
print('terms rows           =', terms, 'of which kana-bearing =', terms_kana)
print('VERDICT', 'PASS - language table is CN' if not kana_ids and not terms_kana else 'FAIL - JP remains in data')
