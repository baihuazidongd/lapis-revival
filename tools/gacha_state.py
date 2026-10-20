"""gacha_state.py - emit gacha.json, the resolved drop tables the stub rolls P101 from.

P101/P100 had no branch in ProtobufCore.buildBody, so the response carried only result.code=0 and
DlgDrawCard.OnDrawNext indexed self.listDraw[index] on an empty list -> "attempt to index a nil
value" every frame, which froze the summon animation on the constellation screen.

The client never rolls. It reads the drawn cards straight out of the response's repeated PBSetter,
keeping only entries whose `from` is AF_DRAW_CARD (6) or AF_INFINITE_DRAW_CARD (21), and
UpdateCell resolves each one by `id` through RoleCardMgr:GetRoleCard. So the stub has to pick the
cards, and every id emitted here must exist in CharacterCard or the reveal throws again.

CardPool.DropGroupList is {{groupId, weight}, ...}; each DropGroup row is {GroupID, Weight, ItemID,
NumMin, NumMax} and for a card pool the card id rides in NumMin==NumMax (ItemID is 10100, which is
not an Asset enum value - the Asset for a pulled card is RC_RECEIVE=46, chosen by the client side).
Weights are flattened to one list per pool so the stub rolls with a single cumulative draw.

Output is written with ensure_ascii=True; nothing but an ASCII summary reaches stdout.
"""
import json
import re
import sqlite3
from pathlib import Path

MASTER = Path(r"E:/lapis/revival/local/resources/master_data.db")
OUT_DIRS = [Path(r"C:/lapisbuild/stubapp/assets"),
            Path(r"E:/lapis/work/stubapp/assets")]

con = sqlite3.connect(MASTER)
con.row_factory = sqlite3.Row

card_ids = {r["ID"] for r in con.execute("select ID from CharacterCard")}


def parse_list(text):
    if not text:
        return []
    return [int(x) for x in re.findall(r"-?\d+", str(text))]


def group_rows(gid):
    return con.execute(
        "select Weight, NumMin, NumMax from DropGroup where GroupID = ?", (gid,)).fetchall()


pools = {}
skipped = []
for p in con.execute("select ID, OneCost, TenCost, DropGroupList, PoolType from CardPool"):
    flat = []
    for entry in re.findall(r"\{[^{}]*\}", str(p["DropGroupList"] or "")):
        nums = [int(x) for x in re.findall(r"-?\d+", entry)]
        if len(nums) < 2:
            continue
        gid, gweight = nums[0], nums[1]
        if gweight <= 0:
            continue
        rows = group_rows(gid)
        if not rows:
            skipped.append((p["ID"], gid, "no group"))
            continue
        total_w = sum(r["Weight"] for r in rows) or 1
        for r in rows:
            # NumMin == NumMax for card pools; a range would mean a random count, not a card id.
            cid = r["NumMin"]
            if cid not in card_ids:
                skipped.append((p["ID"], cid, "not a CharacterCard"))
                continue
            flat.append([cid, max(1, round(gweight * r["Weight"] / total_w))])
    if flat:
        # OneCost and TenCost are each {ticketId, ticketNum, currencyId, currencyNum}. The stub has
        # to bill the currency, so it needs the id and not just the amount: 20001 prices in item 511,
        # 90001 in 543, 9990001 in 77770024 and only 10001-style banners in 502.
        costs = [int(x) for x in re.findall(r"-?\d+", str(p["OneCost"] or ""))]
        tenc = [int(x) for x in re.findall(r"-?\d+", str(p["TenCost"] or ""))]
        pools[str(p["ID"])] = {
            "items": flat,
            "one": costs[3] if len(costs) > 3 else 0,
            "oneItem": costs[2] if len(costs) > 3 else 502,
            "ten": tenc[3] if len(tenc) > 3 else 0,
            "tenItem": tenc[2] if len(tenc) > 3 else 502,
        }

if not pools:
    raise SystemExit("no pool resolved a single card id - master data layout changed")

payload = json.dumps({"pools": pools}, ensure_ascii=True, separators=(",", ":"))
for d in OUT_DIRS:
    if d.is_dir():
        (d / "gacha.json").write_text(payload, encoding="utf-8")

print("gacha.json %d B pools=%d cards=%d skipped=%d" % (
    len(payload), len(pools), sum(len(v["items"]) for v in pools.values()), len(skipped)))
sample = sorted(pools)[:3]
for k in sample:
    v = pools[k]
    print("  pool %s one=%s ten=%s distinct=%s" % (k, v["one"], v["ten"], len(v["items"])))
