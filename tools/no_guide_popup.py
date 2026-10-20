#!/usr/bin/env python3
"""Set Guideshow.Popup = 0 so the picture guides never open.

GuideMgr.IsGuided returns "already guided" for any row whose Popup column is not 1, which is the
only gate PageEquip / PageFittingroom and friends check before opening PGuide with
Guideshow[guideId].Pic. PGuide is the first-time overlay drawn entirely from baked Japanese
bitmaps -- 装備強化, レベルUP!, 素材を使用して装備を強化！ -- so in a Simplified-Chinese build it is
unreadable, and on this device it turned out to be uncloseable as well: a tap on the right half
(where BtnNext's click region sits), a tap on the visible chevron, a 1200 px slow left drag
(OnEndDrag only pages past 500 units) and KEYCODE_BACK (OnBackAndroid) all left the panel sitting
on 1/2 with no LuaException and a live heartbeat. That makes it a hard blocker for 魔女装备, and
by extension for every other feature it gates.

The rows live in the master database, which the Lua loader reads with
`select * from Guideshow`, so this is a data-side change and no Lua blob is touched. The help
list is a different column (UnlockHelpShow) and keeps working.

Seed.java refuses to install a source whose SHA-1 does not match its pin, so the pin has to move
with the bytes; no manifest record references this database, so nothing else needs rewriting.
"""
import hashlib
import pathlib
import sqlite3
import sys

DB = pathlib.Path('C:/lapisbuild/game_decoded/assets/res/MasterData/master_data.db')
SEED = pathlib.Path('C:/lapisbuild/stubapp/src/com/klab/lapis/stub/Seed.java')


def sha1(p):
    return hashlib.sha1(p.read_bytes()).hexdigest().upper()


old = sha1(DB)
db = sqlite3.connect(DB)
before = db.execute('select count(*) from Guideshow where Popup = 1').fetchone()[0]
ids = [r[0] for r in db.execute('select ID from Guideshow where Popup = 1 order by ID')]
if before:
    db.execute('update Guideshow set Popup = 0 where Popup = 1')
    db.commit()
after = db.execute('select count(*) from Guideshow where Popup = 1').fetchone()[0]
rows = db.execute('select count(*) from Guideshow').fetchone()[0]
db.close()

new = sha1(DB)
print(f'Guideshow rows={rows} Popup=1 {before} -> {after}')
print(f'cleared ids: {ids}')
print(f'db sha1 {old} -> {new}  size={DB.stat().st_size}')

text = SEED.read_text(encoding='utf-8', newline='')
if old not in text:
    print(f'!! Seed.java pin {old} not found -- refusing to guess where it goes')
    sys.exit(1)
# newline='' both ways: read_text/write_text default to universal-newline translation, which
# rewrites the whole file CRLF on Windows and the pin parser then joins lines with tr and finds a
# stray \r between the two string literals.
SEED.write_text(text.replace(old, new), encoding='utf-8', newline='')
print(f'Seed.java pin rewritten: {old} -> {new}')
