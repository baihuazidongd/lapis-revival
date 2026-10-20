#!/usr/bin/env python3
"""Emit stubapp/assets/mirror.json - the club-mirror (时空夹缝 / 幻境) tables the stub needs to answer
P180..P186, read out of the runtime master database so the numbers cannot drift from the client's own.

Why a generated JSON instead of opening master_data.db from Java: every other stateful handler here
follows the same shape (shopgoods.json, arena.json, mail.json, task.json, gacha.json, stageawards.json),
and the DB on device is the client's - the stub would need the klb VFS patch to read it at runtime.

Contribution tiers: Config.ClubMirrorContributionAward is {{12,37},{24,38},{36,39},{48,40},{60,41}} where
the second element is a DropGroup row. Those rows carry a NumMin..NumMax range, i.e. the real server
rolls; we grant NumMin, the guaranteed floor, and say so rather than inventing an average.
"""
import json
import sqlite3

DB = 'E:/lapis/revival/local/resources/master_data.db'
OUT = 'C:/lapisbuild/stubapp/assets/mirror.json'

c = sqlite3.connect(DB)


def cfg(key):
    row = c.execute('select ArgInt, ArgJson from Config where Key=?', (key,)).fetchone()
    return row


def parse_list(s):
    """'{1,2,3}' or '{{1,2},{3,4}}' -> python."""
    s = (s or '').strip()
    if not s:
        return []
    s = s.replace('{', '[').replace('}', ']')
    try:
        return json.loads(s)
    except Exception:
        return []


cfgv = {}
for k in ('ClubMirrorDailyRound', 'ClubMirrorBossWeekPlay', 'ClubMirrorContributionAward',
          'ClubMirrorDelayTime', 'ClubMirrorRefreshTime'):
    r = cfg(k)
    cfgv[k] = parse_list(r[1]) if r and r[1] not in ('', '{}') else (r[0] if r else 0)

mirrors = []
for mid, typ, rnd, brnd, lvl, finish, award, rev in c.execute(
        'select ID,Type,Round,BattleRound,LevelLimit,FinishPoint,Award,RoundEvent from ClubMirror order by ID'):
    if typ != 0:
        continue
    mirrors.append({'id': mid, 'round': rnd, 'battleRound': brnd, 'levelLimit': lvl,
                    'finishPoint': finish, 'award': parse_list(award),
                    # RoundEvent is the per-round door layout: 10 groups of 3 ClubMirrorEvent types.
                    # Without it the client has nothing to rebuild the grid from after one action is
                    # spent, so the corridor renders empty.
                    'roundEvent': parse_list(rev)})

events = []
for eid, mid, maxc, typ, addp, contrib, tval in c.execute(
        'select ID,MirrorId,MaxCount,Type,AddPoint,Contribution,TypeValue from ClubMirrorEvent order by ID'):
    ap = [x for x in parse_list(addp) if isinstance(x, int)]
    tv = parse_list(tval)
    # TypeValue is a list of per-option payloads, e.g. '{{25}}' or '{{1010101,1010103,...}}'.
    # P182's eventParams is the payload of the event that was asked about, not the round's door layout.
    first = tv[0] if tv and isinstance(tv[0], list) else (tv or [])
    events.append({'id': eid, 'mirrorId': mid, 'maxCount': maxc, 'type': typ,
                   # AddPoint is per-round, not a total: {1,1,2,3,4} is what round 1..5 each award.
                   'addPoint': ap, 'contribution': contrib,
                   'params': [x for x in first if isinstance(x, int)]})

boss = [{'id': i, 'bossStage': bs, 'bossLevel': bl} for i, bl, bs in c.execute(
    'select ID,BossLevel,BossStage from ClubMirror where Type=1 order by ID')]

tiers = []
for thr, grp in cfgv.get('ClubMirrorContributionAward') or []:
    rows = c.execute('select ItemID,NumMin,NumMax from DropGroup where ID=?', (grp,)).fetchall()
    items = [[it, lo] for it, lo, hi in rows]
    tiers.append({'need': thr, 'groupId': grp, 'items': items})

doc = {'mirrors': mirrors, 'events': events, 'boss': boss,
       # Rounds per mirror, from ClubMirror.Round (all five are 10).
       'maxRound': (mirrors[0]['round'] if mirrors else 10),
       'dailyRound': cfgv.get('ClubMirrorDailyRound', 10),
       'bossWeekPlay': cfgv.get('ClubMirrorBossWeekPlay', 3),
       'contributionAward': tiers}
with open(OUT, 'w', encoding='utf-8') as f:
    json.dump(doc, f, ensure_ascii=True, separators=(', ', ': '))

print('mirrors=%d events=%d boss=%d dailyRound=%s tiers=%s'
      % (len(mirrors), len(events), len(boss), doc['dailyRound'], [t['need'] for t in tiers]))
for m in mirrors:
    print('   mirror %d finish=%d round=%d award=%s' % (m['id'], m['finishPoint'], m['round'], m['award']))
for t in tiers:
    print('   tier %d -> group %d items %s' % (t['need'], t['groupId'], t['items']))
