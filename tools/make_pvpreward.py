"""Generate arena.json's sibling pvpreward.json: what a finished arena battle pays out.

PVPSeason.DailyBattleDropId -> PVPDrop.FromScore/ToScore -> DropGroupId -> DropGroup rows
(ItemID, NumMin, NumMax). The JP server picked the band from the player's post-battle score, so
that is what ProtobufCore.purchaseArena does; nothing here is invented except the win/loss score
delta, which never ships in the client data.
"""
import json
import sqlite3
import sys

db = sys.argv[1] if len(sys.argv) > 1 else r'C:\lapisbuild\mdev.db'
out = sys.argv[2] if len(sys.argv) > 2 else r'C:\lapisbuild\stubapp\assets\pvpreward.json'

c = sqlite3.connect('file:%s?mode=ro' % db, uri=True)
season = c.execute('select DailyBattleDropId, DailyBattleNum from PVPSeason order by ID desc limit 1').fetchone()
drop_id = season[0]

bands = []
for from_score, to_score, groups in c.execute(
        'select FromScore, ToScore, DropGroupId from PVPDrop where DropId=? order by FromScore', (drop_id,)):
    parsed = json.loads(groups.replace('{', '[').replace('}', ']'))
    ids = [x for row in parsed for x in (row if isinstance(row, list) else [row])]
    grants = []
    for gid in ids:
        for item, lo, hi in c.execute('select ItemID, NumMin, NumMax from DropGroup where ID=?', (gid,)):
            grants.append([item, lo, hi])
    bands.append({'from': from_score, 'to': to_score, 'grants': grants})

doc = {'dropId': drop_id, 'dailyBattleNum': season[1], 'bands': bands}
with open(out, 'w', encoding='ascii', newline='') as f:
    json.dump(doc, f, separators=(',', ':'))
print('dropId=%s bands=%s' % (drop_id, [(b['from'], b['to'], [g[0] for g in b['grants']]) for b in bands]))
