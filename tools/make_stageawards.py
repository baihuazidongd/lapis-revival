#!/usr/bin/env python3
"""make_stageawards.py -- build stubapp/assets/stageawards.json from the delivered master DB.

P43 (stage settlement) has to answer with two things the client reads straight off the response:
`stars`, three per-mission results that DlgUIVictory:847 turns into the mission cells, and `setter`,
whose entries DlgUIVictory:219-252 buckets by the setter's `from` (AF_STAGE_FIRST / AF_NORMAL /
AF_STAGE_STAR(2/26/27)) into the drop columns. Every number in those columns comes from master data
(StageData.Grade / FirstAward / StarNAward / ItemList / DropgroupList / DropChance and DropGroup),
and the stub has no database, so the whole table ships precomputed as this asset.

Usage: python make_stageawards.py <master_data.db> <out.json>
"""
import json
import re
import sqlite3
import sys


def lua_list(text):
    """'{501,120}' -> [501,120]; '{1,2,3}' likewise; '{}' -> []."""
    text = (text or "").strip()
    if not text.startswith("{"):
        return []
    try:
        val = json.loads(text.replace("{", "[").replace("}", "]"))
    except ValueError:
        return []
    return val if isinstance(val, list) else []


def pairs(text):
    """'{{501,120},{801,3}}' -> [[501,120],[801,3]] (single pairs get wrapped)."""
    rows = lua_list(text)
    if not rows:
        return []
    if not isinstance(rows[0], list):
        rows = [rows]
    out = []
    for r in rows:
        if len(r) >= 2 and isinstance(r[0], int) and isinstance(r[1], int) and r[1] > 0:
            out.append([r[0], r[1]])
    return out


def grade(text):
    """'{{Win=1},{LimitTurn=6},{DieNum=0}}' -> [['Win',1],['LimitTurn',6],['DieNum',0]].

    StageData stores Lua dict-lists with '=' instead of ':', so json.loads cannot read them.
    """
    out = []
    for body in re.findall(r"\{([^{}]*)\}", text or ""):
        if "=" not in body:
            continue
        k, v = body.split("=", 1)
        v = v.strip().strip("'\"")
        try:
            out.append([k.strip(), int(float(v))])
        except ValueError:
            continue
    return out


def main():
    db, out = sys.argv[1], sys.argv[2]
    con = sqlite3.connect(db)
    con.row_factory = sqlite3.Row

    used = {}
    all_groups = {}
    for r in con.execute("select GroupID,Weight,ItemID,NumMin,NumMax from DropGroup"):
        all_groups.setdefault(r["GroupID"], []).append(
            [r["Weight"], r["ItemID"], r["NumMin"], r["NumMax"]])

    stages = {}
    for r in con.execute("select ID,ChapterID,Grade,FirstAward,Star1Award,Star2Award,Star3Award,"
                         "ItemList,DropgroupList,DropChance from StageData"):
        g = grade(r["Grade"])
        first = pairs(r["FirstAward"])
        star = [pairs(r["Star1Award"]), pairs(r["Star2Award"]), pairs(r["Star3Award"])]
        gl = lua_list(r["DropgroupList"])
        chance = lua_list(r["DropChance"])
        rolls = []
        for i, gid in enumerate(gl):
            if not isinstance(gid, int):
                continue
            rows = all_groups.get(gid)
            if not rows:
                continue
            pct = chance[i] if i < len(chance) and isinstance(chance[i], (int, float)) else 100
            used[gid] = rows
            rolls.append([int(pct), gid])
        # ItemList is the pre-battle preview of the drops the groups roll: in 2305 of the 2461 stages
        # that carry both, every one of its item ids also appears as a guaranteed group row. Granting
        # both would pay gold and materials twice, so only the ids no group can produce survive here.
        inGroups = set()
        for _pct, gid in rolls:
            for _w, item, _lo, _hi in all_groups[gid]:
                inGroups.add(item)
        fixed = [p for p in pairs(r["ItemList"]) if p[0] not in inGroups]
        if not (g or first or any(star) or fixed or rolls):
            continue
        stages[str(r["ID"])] = {
            "ch": r["ChapterID"], "grade": g, "first": first, "star": star,
            "fixed": fixed, "rolls": rolls,
        }

    doc = {"stages": stages, "groups": {str(k): v for k, v in used.items()}}
    with open(out, "w", encoding="utf-8") as fh:
        json.dump(doc, fh, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    nroll = sum(1 for s in stages.values() if s["rolls"])
    ngrade = sum(1 for s in stages.values() if s["grade"])
    print("stages=%d groups=%d withGrade=%d withDrops=%d bytes=%d"
          % (len(stages), len(used), ngrade, nroll, len(json.dumps(doc, separators=(",", ":")))))
    for probe in ("10002", "10102"):
        if probe in stages:
            print("  %s -> %s" % (probe, json.dumps(stages[probe])))


if __name__ == "__main__":
    main()
