#!/usr/bin/env python3
"""Land the 購買部 plate on 道具 instead of 礼包, in the client's master database.

PageShop.UpdateTag's package branch deactivates SafeArea/Main/ScrollArea, and the very next
statement in OnEnter is InitScrollView, which looks that node up through GOUtil.FindChildGameObject
on a search that does not survive being handed the deactivated subtree: it raises
"Object reference not set to an instance of an object" (PageShop.lua:555), OnEnter never returns,
UIPanel.DealWithEnter therefore never reaches OnRegisterEvent, and none of the five main tabs ever
gets an AddClick. The 購買部 plate hard-codes tabMainIndex = 6 (package) in PageMainStage.lua:1489,
so every entry from home took that branch. Since Lua is trailer-verified and cannot be patched in
place, the landing tab is steered from the data side instead.

ShopManager.SetData builds two parallel maps from the pb rows it is handed, last writer wins:
listAllIndex[TabIndex] = Type and listAllType[Type] = TabIndex. Normally listAllIndex of
listAllType[6] is 6 again, which is why no single-value edit to one column can move the landing.
Give exactly one Type 6 row TabIndex 4 -- the 道具 index -- and make make_state.py emit it last
among the Type 6 rows, immediately before the Type 2 rows: then listAllType[6] = 4 while
listAllIndex[4] = 2, so the plate resolves to the item tab, whose else-branch re-activates the
scroll area and OnEnter completes. The other thirteen Type 6 rows keep TabIndex 3, so index 3 still
holds Type 6 and all five tab labels are unchanged.

The row is 2060501: Type 6, ShopCloseType 0, so SetData's sold-out drop rule can never delete it and
silently pull listAllType[6] back to 3. Its TabIndex is read nowhere else -- listAll is keyed by
Type, and sub-tabs come from SubTabIndex -- so the gift package itself is still listed and buyable
under 礼包.
"""
import hashlib
import sqlite3
import sys

DB = 'C:/lapisbuild/game_decoded/assets/res/MasterData/master_data.db'
SEED = 'C:/lapisbuild/stubapp/src/com/klab/lapis/stub/Seed.java'
DECOY = 2060501

sha1 = lambda p: hashlib.sha1(open(p, 'rb').read()).hexdigest().upper()
old = sha1(DB)

db = sqlite3.connect(DB)
row = db.execute('select Type, TabIndex, SubTabIndex, ShopCloseType from ShopData where ID = ?',
                 (DECOY,)).fetchone()
if row is None:
    sys.exit('decoy shop %d missing' % DECOY)
if row[0] != 6 or row[3] != 0:
    sys.exit('decoy %d is Type %s ShopCloseType %s, wanted 6 and 0' % (DECOY, row[0], row[3]))
db.execute('update ShopData set TabIndex = 4 where ID = ?', (DECOY,))
db.execute("update Config set ArgJson = '{2,1}' where Key = 'ShopFirstLook'")
db.commit()

maps = db.execute('select Type, TabIndex, count(*) from ShopData group by Type, TabIndex '
                  'order by Type, TabIndex').fetchall()
sfl = db.execute("select ArgJson from Config where Key = 'ShopFirstLook'").fetchone()[0]
db.close()
new = sha1(DB)
print('decoy %d TabIndex %d -> 4   ShopFirstLook %s' % (DECOY, row[1], sfl))
print('Type/TabIndex row counts:', maps)
print('db sha1 %s -> %s' % (old, new))

text = open(SEED, encoding='utf-8', newline='').read()
if old not in text:
    sys.exit('Seed.java pin %s not found -- refusing to guess where it goes' % old)
open(SEED, 'w', encoding='utf-8', newline='').write(text.replace(old, new))
print('Seed.java pin rewritten: %s -> %s' % (old, new))
