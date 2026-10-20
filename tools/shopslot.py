#!/usr/bin/env python3
"""Move the 2060501 decoy's TabIndex to whichever tab slot the current experiment needs.

The landing that the 購買部 plate resolves to is listAllIndex[listAllType[6]]: the decoy is the last
Type 6 row the stub emits, so its TabIndex becomes listAllType[6], and the type that owns that slot
decides which branch PageShop.UpdateTag takes -- and only the exchange branch and the else branch
with chargeType ~= protocol_pb.normal leave SafeArea/Main/ScrollArea active for InitScrollView to
find on the next line. Putting the decoy on slot 5 lands the plate on 兑换所 (85 Type 3 rows are
emitted after it, so slot 5 keeps type 3), which is the branch that provably cannot deactivate.

Writes the master database in place and re-pins Seed.java, because Seed refuses to install a source
whose database hash it does not already know.
"""
import hashlib
import sqlite3
import sys

DB = 'C:/lapisbuild/game_decoded/assets/res/MasterData/master_data.db'
SEED = 'C:/lapisbuild/stubapp/src/com/klab/lapis/stub/Seed.java'
DECOY = 2060501
SLOT = int(sys.argv[1])

sha1 = lambda p: hashlib.sha1(open(p, 'rb').read()).hexdigest().upper()
old = sha1(DB)

db = sqlite3.connect(DB)
row = db.execute('select Type, TabIndex, ShopCloseType from ShopData where ID = ?', (DECOY,)).fetchone()
if row is None or row[0] != 6 or row[2] != 0:
    sys.exit('decoy %d must exist as Type 6 ShopCloseType 0, got %r' % (DECOY, row))
db.execute('update ShopData set TabIndex = ? where ID = ?', (SLOT, DECOY))
db.commit()
maps = db.execute('select Type, TabIndex, count(*) from ShopData group by Type, TabIndex '
                  'order by Type, TabIndex').fetchall()
db.close()
new = sha1(DB)
print('decoy %d TabIndex %d -> %d' % (DECOY, row[1], SLOT))
print('Type/TabIndex row counts:', maps)
print('db sha1 %s -> %s' % (old, new))

text = open(SEED, encoding='utf-8', newline='').read()
if old not in text:
    sys.exit('Seed.java pin %s not found -- refusing to guess where it goes' % old)
open(SEED, 'w', encoding='utf-8', newline='').write(text.replace(old, new))
print('Seed.java pin rewritten: %s -> %s' % (old, new))
