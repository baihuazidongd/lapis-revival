#!/usr/bin/env python3
"""Stage a rebuilt CN language table for delivery and re-pin it.

`apply_story_cn.py` produces the merged table; this puts it where the client reads it (the APK asset
`assets/res/JP/master_data_lang.db`, which Seed verifies by SHA-1 before installing) and moves the
Seed pin to the new digest in the same step, so a build can never ship a language table the running
app would reject at cold boot. The device copy under
`/sdcard/Android/data/com.klab.lapis/files/JP/master_data_lang.db` is pushed by the caller, because
`adb push` onto that FUSE path has eaten existing targets before.
"""
import hashlib
import re
import shutil
import sys

SRC = sys.argv[1] if len(sys.argv) > 1 else r'C:/lapisbuild/cn/out/master_data_lang.db'
DST = r'C:/lapisbuild/game_decoded/assets/res/JP/master_data_lang.db'
SEED = r'C:/lapisbuild/stubapp/src/com/klab/lapis/stub/Seed.java'
ASSET = 'res/JP/master_data_lang.db'

sha1 = lambda p: hashlib.sha1(open(p, 'rb').read()).hexdigest().upper()
old = sha1(DST)
shutil.copyfile(SRC, DST)
new = sha1(DST)

text = open(SEED, encoding='utf-8', newline='').read()
pat = re.compile(r'("%s",\s*")[0-9A-F]{40}(")' % re.escape(ASSET))
if not pat.search(text):
    sys.exit('no pin for %s in Seed.java -- refusing to guess where it goes' % ASSET)
hits = [m for m in pat.finditer(text)]
if len(hits) != 1:
    sys.exit('%d pins for %s, wanted exactly 1' % (len(hits), ASSET))
found = re.search(r'"%s",\s*"([0-9A-F]{40})"' % re.escape(ASSET), text).group(1)
if found != old:
    sys.exit('pin says %s but the staged file is %s -- the tree is already dirty' % (found, old))
open(SEED, 'w', encoding='utf-8', newline='').write(pat.sub(r'\g<1>%s\g<2>' % new, text))
print('staged %s -> %s' % (SRC, DST))
print('sha1 %s -> %s' % (old, new))
print('Seed.java pin for %s rewritten' % ASSET)
