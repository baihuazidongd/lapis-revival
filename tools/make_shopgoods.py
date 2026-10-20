#!/usr/bin/env python3
"""make_shopgoods.py — build stubapp/assets/shopgoods.json from the delivered master DB.

P121 (purchase) has to answer with PBSetter entries, and the client resolves those through
SetterData.DealData, which switches on the `asset` enum: the currency codes (P_GOLD, P_DIAMOND,
P_DIAMOND_PAY, ...) move PlayerInst, everything else falls through to
ItemManager:ChangeItemCount(id, num). So the server needs, per good, its cost item + quantity,
its grant list, and the item -> Asset code map. All three live in master_data.db.

Usage: python make_shopgoods.py <master_data.db> <out.json> [descriptor.bin]
"""
import json
import sqlite3
import sys

from google.protobuf import descriptor_pb2

CURRENCY_ASSETS = ("P_GOLD", "P_DIAMOND", "P_DIAMOND_PAY", "P_POWER", "P_MEDAL",
                   "P_FRIEND_COIN", "P_CLUB_COIN", "P_LEVEL_EXP", "P_HEAD", "P_HEAD_FRAME")


def parse_pairs(text):
    """'{513,60}' -> [[513,60]];  '{{502,60},{503,10}}' -> [[502,60],[503,10]]"""
    text = (text or "").strip()
    if not text.startswith("{"):
        return []
    try:
        val = json.loads(text.replace("{", "[").replace("}", "]"))
    except ValueError:
        return []
    if not isinstance(val, list) or not val:
        return []
    if not isinstance(val[0], list):
        val = [val]
    return [[int(x) for x in row] for row in val if isinstance(row, list)]


def main():
    db, out = sys.argv[1], sys.argv[2]
    desc = sys.argv[3] if len(sys.argv) > 3 else None
    con = sqlite3.connect(db)

    asset_of = {}
    if desc:
        raw = open(desc, "rb").read()
        fp = descriptor_pb2.FileDescriptorProto()
        try:
            fds = descriptor_pb2.FileDescriptorSet()
            fds.ParseFromString(raw)
            fp = fds.file[0]
        except Exception:
            fp.ParseFromString(raw)
        code = {}
        for e in fp.enum_type:
            if e.name == "Asset":
                code = {v.name: v.number for v in e.value}
        # ItemData.Type holds the Asset enum *name* for the currency rows ('P_DIAMOND' for 502),
        # which is what decides whether a setter lands on PlayerInst or on ItemManager.
        cols = [r[1] for r in con.execute("PRAGMA table_info('ItemData')").fetchall()]
        for cand in ("Type", "Asset", "AssetName"):
            if cand not in cols:
                continue
            hits = {str(iid): code[t] for iid, t in con.execute(
                "select ID, %s from ItemData" % cand) if t in code}
            if hits:
                asset_of = hits
                break

    # A cost row the client cannot represent is worse than no row at all. P121 answers with one
    # PBSetter per cost row, SetterData.DealWithItem files a non-currency under the generic item
    # asset, and the next login re-serves the banked delta as an `items[]` row. ItemManager.SetData
    # routes every I_SOUL row through RoleCardMgr:GetRoleCard(item.Value), so items 581-584 -- I_SOUL
    # rows whose Value is 0, not a CharacterCard -- index a nil card and abort the whole P1024
    # callback with a LuaException, taking the gacha page and every other bag reader with them.
    # These are the universal-soul currencies the shipped bag never carries, so drop the row: the
    # client prints the price from its own master data either way.
    cards = {r[0] for r in con.execute("select ID from CharacterCard")}
    unrepresentable = {iid for iid, t, v in con.execute("select ID, Type, Value from ItemData")
                       if t == "I_SOUL" and v not in cards}

    goods = {}
    for gid, ctype, cost, items, store, unlock in con.execute(
            "select ID, CostType, CostValue, GoodsItemList, StoreNumber, UnlockLevel from GoodsData"):
        pairs = parse_pairs(items)
        entry = {
            "costType": ctype,
            "cost": [c for c in (parse_pairs(cost)[:1] or []) if c[0] not in unrepresentable],
            "items": [[p[0], p[1] if len(p) > 1 else 1] for p in pairs],
            "limit": store,
            "unlock": unlock,
        }
        if entry["cost"] and len(entry["cost"][0]) == 1:
            # CostType 1 rows carry a price in the same column, not an item/quantity pair.
            entry["priceOnly"] = entry["cost"][0][0]
            entry["cost"] = []
        goods[str(gid)] = entry

    doc = {"assetOf": asset_of, "goods": goods}
    with open(out, "w", encoding="utf-8") as fh:
        json.dump(doc, fh, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    ct = {}
    for g in goods.values():
        ct[g["costType"]] = ct.get(g["costType"], 0) + 1
    print("goods=%d costTypes=%s assetOf=%d" % (len(goods), sorted(ct.items()), len(asset_of)))
    for probe in ("12001", "30006", "21025"):
        if probe in goods:
            print("  %s -> %s" % (probe, json.dumps(goods[probe])))


if __name__ == "__main__":
    main()
