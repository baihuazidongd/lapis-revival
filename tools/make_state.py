"""make_state.py - emit stubapp/assets/{player,shop}.json from the master database.

The client builds its home scene from P11/P1024 (player, roles, roleCards, items, gameInfo) and
fills the shop tabs from P120 (shopTab/months). Both payloads used to be a bare playerId, which
left ShopManager.listAll[4] nil (InfoShop.lua:253) and the home scene with no leader/mainCard to
resolve a bundle name from, so its two AssetBundle loads came back as empty streams.

Every id written here is read back out of master_data.db so the client's own table lookups hit.
"""
import json, re, sqlite3, time
from pathlib import Path

DB = Path(r"E:/lapis/revival/local/resources/master_data.db")
OUT = Path(r"C:/lapisbuild/stubapp/assets")
PLAYER_ID = 10001
# Must stay paired with shopfix_landing.py, which gives this Type 6 row TabIndex 4 in the client's
# master database; the emission order below only produces the intended tab map if both hold.
SHOP_LANDING = 2060501

con = sqlite3.connect(DB)
con.row_factory = sqlite3.Row
now = int(time.time() * 1000)
past = now - 30 * 86400000


def one(sql, *a):
    return con.execute(sql, a).fetchall()


def parse_list(text):
    """Master tables store '{1,2,3}' for list columns."""
    if not text:
        return []
    t = str(text).strip()
    if not (t.startswith("{") and t.endswith("}")):
        return []
    out = []
    for part in t[1:-1].split(","):
        part = part.strip().strip('"')
        if part.isdigit():
            out.append(int(part))
    return out


# ---- avatar state: PBRole.avatars (owned) and avatarTemplate (the four dress-up modes) -------------
# Three separate PBRole fields feed the fitting room and they do not mean the same thing:
#   avatars         the OWNED set  - AvatarManager.GetAvatarData: Geted = table.getIndex(pb.avatars, id),
#                   and IsUnlocked reuses it for every part whose AvatarData.Lock is 1
#   avatarTemplate  one entry per dress-up mode; its `avatars` is that mode's EQUIPPED set
#                   (InfoRole:GetEquipAvatarIds returns avatarModes[curModeId].avatars)
#   currentAvatar   which mode the club room wears; 0 is normalised to mode 1 by InfoRole:SetData
# All three shipped empty. With an empty template nothing matches curModeId, so DlgAvatarMode.lua:94
# leaves self.curMode nil and :157 raises "attempt to index field 'curMode' (a nil value)". That aborts
# PageFittingroom:OnEnter before the back arrow registers its handler, so the page cannot be left
# without a process restart, the mode panel and shelf both render empty, and the character on screen is
# the undressed skeleton - legs and shoes only. Mode ids have to equal their 1-based index because
# InfoRole:UpdateAvatarMode indexes avatarModes[id] directly.
AV_ROWS = {r["ID"]: r for r in one("select * from AvatarData")}
# ActorData.DefaultAvatars is the outfit the shipped model is built to wear; it is not a subset of the
# purchasable shelf list, so it has to be granted on its own.
AV_BY_ROLE = {}
for r in one("select cr.ID as RID, a.DefaultAvatars as DEF, cr.WeaponAvatarList as WEA,"
             " cr.CharAvatarListID as LST from CharacterRole cr join ActorData a on a.ID = cr.ActorID"):
    AV_BY_ROLE[r["RID"]] = (parse_list(r["DEF"]), parse_list(r["WEA"]), r["LST"])


def av_stamp(text):
    return time.mktime(time.strptime(text, "%Y-%m-%d %H:%M:%S")) * 1000 if text else 0


def av_usable(aid):
    """Mirrors InfoAvatar.IsExist plus the BP rule: AvatarType 1 rows belong to the battle pass."""
    row = AV_ROWS.get(aid)
    if row is None or row["AvatarType"] == 1:
        return False
    start, end = av_stamp(row["StartTime"]), av_stamp(row["EndTime"])
    if start and start > now:
        return False
    return not (end and end < now)


def av_slots(aid):
    return set(re.findall(r'"([^"]+)"', AV_ROWS[aid]["Slot"] or ""))


def av_fill(prefs):
    """One part per slot, first claim wins, overlapping multi-slot parts never double up."""
    taken, out = set(), []
    for aid in prefs:
        slots = av_slots(aid)
        if not slots or slots & taken:
            continue
        taken |= slots
        out.append(aid)
    return out


def wardrobe_for(rid):
    defaults, weapons, list_id = AV_BY_ROLE.get(rid, ([], [], 0))
    shelf_row = one("select Avatar from CharAvatarListData where ID=?", list_id)
    shelf = parse_list(shelf_row[0]["Avatar"]) if shelf_row else []
    owned = [a for a in dict.fromkeys(defaults + shelf + weapons) if av_usable(a)]
    modes = [{"id": 1, "avatars": [a for a in defaults if av_usable(a)], "name": ""}]
    pool = [a for a in dict.fromkeys(shelf + defaults) if av_usable(a)]
    # Rotating the preference order gives modes 2-4 visibly different outfits without inventing any
    # combination the shipped tables do not already pair up.
    step = max(1, len(pool) // 3)
    for m in range(1, 4):
        k = (m * step) % max(1, len(pool))
        modes.append({"id": m + 1, "avatars": av_fill(pool[k:] + pool[:k] + defaults), "name": ""})
    return owned, modes, (weapons[0] if weapons else 0)


# ---- roles: one per CharacterRow, each with its first CharacterCard -------------------------
roles, role_cards, card_ids = [], [], []
for r in one("select ID from CharacterRole order by ID"):
    rid = r["ID"]
    # A card with empty SpineData takes TeamCardSpine:UpdateCardInfo's fallback branch, which is the
    # only path that loads CharacterCard.FullIcon as a RawImage texture; that load fails and the
    # unguarded C# binding throws, killing PageTeam:OnEnter. Prefer a spine-bearing card per role.
    cards = one("select ID from CharacterCard where CharacterID=? "
                "order by (SpineData<>\"\") desc, Rank desc, ID asc limit 1", rid)
    cid = cards[0]["ID"] if cards else 0
    if cid:
        card_ids.append(cid)
    owned_av, modes_av, weapon_av = wardrobe_for(rid)
    roles.append({
        "id": rid, "playerId": PLAYER_ID, "clothes": list(modes_av[0]["avatars"]),
        "nodes": [], "avatars": owned_av,
        "favorExp": 0, "favorRankRecord": 1, "favorLevelRecord": 1, "roleCardId": cid,
        "weaponAvatar": weapon_av, "nickName": "", "phoneBgId": 0, "lastTopicId": 0,
        # One PBEquipSlot per equipment slot, matching EquipmentManager.EquipSlotCnt. An empty list is
        # not harmless: IsEquipSlotUnlocked reads the EquipmentUnlock config (favor 1 for slots 1-4) so
        # it says yes, then RoleEquipRDL.CanEquipIntense indexes role:GetEquipSlot(i).quality on the
        # missing entry and raises. That unwinds out of RoleRDL:Init, which is the first call in
        # RedDotSystemMgr.InitAllLeafNode, so CardRDL/ManualRDL/ChapterRDL/BagRDL/MailRDL/SystemOpenMgr
        # never initialise either -- and ManualVideoRDL's empty CAN_RECEIVE_NIRVANA is what later killed
        # every gacha pull. quality 1 / grade 0 / level 1 is the pristine row the real server sends.
        "slots": [{"slot": i, "quality": 1, "grade": 0, "level": 1, "scroll": 0, "attributes": []}
                  for i in range(1, 7)],
        "avatarTemplate": modes_av, "currentAvatar": 1, "extraSkills": [], "equipStatus": 0,
        "pictures": [], "pictureAwardStatus": 0,
    })
# ---- roster: maxed, because a Lv-1 card cannot scratch a story boss --------------------------------
# InfoRoleCard:UpdateExp -> LevelManager:GetLevel walks LevelConfig.RoleCardExperienceAdd (that column
# is cumulative, the sibling RoleCardExperience is not), and UpdateLimitLevel then clamps to
# min(StarCardLevel[star+1], RoleCardLevelLimit[playerLevel]). The player sits at the cap and star 6
# opens 100, so level plus star is all the ceiling there is. Battle attributes are rebuilt from
# (level, star, petal) in UpdateAtt and never read back out of pb.attrs.
# A passive's battle level comes from GetTalentLevelByPetal, i.e. the card's FlowerSkill rows keyed by
# petal count, and falls back to AllSkills.HighestLevel for talents absent there -- so petal, not
# starTalents, is what strengthens a skill. pb.starTalents only has to name the ids: StarTalent group k
# unlocks at star k-1 (TalentIsUnLock), and a talent missing from this list never enters listSkill.
CARD_MAX_EXP = one("select RoleCardExperienceAdd from LevelConfig order by ID desc limit 1")[0][0]
RANK_IDX = {"R": 1, "SR": 2, "SSR": 3, "UR": 4}
STAR_MAX = parse_list(one("select ArgJson from Config where Key='StarMaxLevel'")[0][0])
FLOWER_MAX = parse_list(one("select ArgJson from Config where Key='FlowerNum'")[0][0])
SKILL_MAX = {r["ID"]: r["HighestLevel"] for r in one("select ID, HighestLevel from AllSkills")}


def star_talents(star_talent_text, star):
    groups = json.loads((star_talent_text or "{}").replace("{", "[").replace("}", "]"))
    out = []
    for k, group in enumerate(groups, 1):
        if k - 1 > star:
            break
        out += [{"id": tid, "level": SKILL_MAX.get(tid, 1)} for tid in group]
    return out


for cid in card_ids:
    card = one("select Rank, StarTalent from CharacterCard where ID=?", cid)[0]
    rank = RANK_IDX.get(card["Rank"], 1)
    star = STAR_MAX[rank - 1] if rank <= len(STAR_MAX) else 1
    role_cards.append({
        "id": cid, "playerId": PLAYER_ID, "levelExp": CARD_MAX_EXP, "starLevel": star, "attrs": [],
        "starAwards": [], "starTalents": star_talents(card["StarTalent"], star), "soul": 0,
        "petal": FLOWER_MAX[rank - 1] if rank <= len(FLOWER_MAX) else 0, "petalAwards": [],
        "clubBlood": 0, "clubGVGBlood": 0, "roleCardTimes": 0, "real": True,
    })

# ---- items: the three currencies plus a slice of bag items ---------------------------------
# InfoItem.SetData routes every I_SOUL row through RoleCardMgr:GetRoleCard(ItemData.Value), and
# ItemData 581-584 carry Value=0, so InfoRoleCard indexes a nil table row and the whole P11
# handler aborts before the title screen will hand over to home. Only souls that resolve.
items = []
for r in one("select ID from ItemData where ID in (501,502,503) order by ID"):
    items.append({"id": r["ID"], "num": 100000, "updateTime": now})
card_ids_all = {r["ID"] for r in one("select ID from CharacterCard")}
souls = [r for r in one("select ID, Value from ItemData where Type='I_SOUL' order by ID")
         if r["Value"] in card_ids_all]
for r in souls[:24]:
    items.append({"id": r["ID"], "num": 50, "updateTime": now})

# ---- every shop and pool cost currency, so "all tabs open" also means "all tabs buyable" ---------
# GoodsData prices its goods in 85 different cost items. Four of them are PlayerInst currencies,
# which the player dict below carries; the other 81 are bag rows (I_SCORE_COIN x59, I_RAID_COIN x12,
# I_GVG_COIN x7, I_PVP_COIN, tickets) that an offline save never receives. ItemManager.GetItemCount
# resolves through InfoItem.GetCurResNum, which for exactly those types falls through to pb.num, so
# with an empty bag 兑换所's 82 sub-tabs all answer "不足" and the storefront reads as nearly empty
# even though every good is served. Seed one row per cost id, at a multiple of the dearest single
# purchase in the table (10000), and exclude P_* (read from PlayerInst, not from the bag) and I_SOUL
# (routed through RoleCardMgr:GetRoleCard, which aborts all of P11 on a Value that is not a card).
COST_SEED = 999999
cost_ids = set()
for row in one("select CostValue from GoodsData"):
    cost_ids.update(int(x) for x in re.findall(r"\{(\d+),\s*\d+", str(row[0] or "")))
# CardPool prices the same way, as {ticketId, ticketNum, currencyId, currencyNum}: with 114 banners
# now listed, the summon page bills tickets 510/511/543/77770024 as well as diamonds, so both slots
# have to exist in the bag or an open pool is still an unusable one.
for row in one("select OneCost, TenCost from CardPool"):
    cost_ids.update(int(x) for x in re.findall(r"\{(\d+),\s*\d+", str(row[0] or "") + " " + str(row[1] or "")))
bag_types = {r["ID"]: r["Type"] for r in one("select ID, Type from ItemData")}
seeded = 0
for cid in sorted(cost_ids):
    t = bag_types.get(cid, "")
    if t.startswith("P_") or t in ("I_SOUL", "I_SOUL_COMMON") or cid in (501, 502, 503):
        continue
    items.append({"id": cid, "num": COST_SEED, "updateTime": now})
    seeded += 1
print("cost currencies seeded into the bag: %d of %d distinct cost ids" % (seeded, len(cost_ids)))

# LevelConfig.PlayerExperienceAdd is cumulative and 252775 is the level-100 step, so this lands the
# player on the cap. It matters because InfoStage:IsUnlock also demands
# GetCurLv() >= StageData.LevelUnlock, which runs up to 100.
LEVEL_EXP = 260000

player = {
    "playerId": PLAYER_ID, "nickname": "Lapis", "headId": 101, "vipExp": 0, "levelExp": LEVEL_EXP,
    "payStatus": 0, "isOnline": True, "regTime": past, "logoutTime": now,
    # The four PlayerInst currencies a shop price can name. diamondPay stays 0 on purpose: every
    # GoodsData row that prices in it (513) carries a CostValue of 0 in this build, so the 127 goods
    # behind it are already free, and a nonzero balance here would only misreport what the dead
    # recharge tab is supposed to sell.
    "diamond": 999999, "gold": 1000000, "power": 100, "powerAt": now,
    "leader": roles[0], "signature": "", "roleCards": card_ids, "medal": 0, "friendCoin": 999999,
    "birthday": 0, "levelTime": now, "mainCard": role_cards[0] if role_cards else {},
    "headFrame": 0, "showRole": roles[0]["id"], "clubCoin": 999999, "clubName": "Lapis",
    "favoriteRoles": [], "diamondPay": 0, "onlineTime": 0, "maxAttribute": 0,
    "commonAvatars": [], "extras": [], "termsOfUseVersion": 0, "isFreeCoinDebt": False,
}

# ---- chapters: the only thing that ever unlocks a stage -----------------------------------------------
# InfoStage:SetData is the sole writer of isUnLock=true outside an event-chapter special case, and
# ChapterMgr.UpdateProcess derives listCurChapter from it, so no chapters means every stage locked,
# GetCurChapter(main) nil, and PageChapter.lua:48 throwing on curChapter.data - which is what hangs
# the quest map. The list the client actually reads is gameRefresh.chapters
# (NetManager:807 SetRefreshData -> InfoGameExtra:201 ChapterMgr:SetData), not gameInfo.chapters.
# Type 4 (event) is left out because those chapters need live activity context from P132.
# Every stage is delivered unlocked and *passed*. Newbie.Stage gates 37 menu entries (PVP needs 10413,
# DrawCard 10102, Tower 10408, ...), and TutorialMgr.IsOpen reads InfoStage.pb.isPass for those, so
# an unpassed sandbox silently swallows the arena and gacha taps with only a "clear to unlock" toast.
# Stars stay 0/3 so no first-clear award claim is offered; the stub has no claim handler.
CHAPTER_TYPES = (1, 2, 3, 5, 6, 101, 102, 104, 119)
stage_ids = {r["ID"] for r in one("select ID from StageData")}
chapters = []
for ch in one("select ID, Type, StageID from ChapterData order by ID"):
    if ch["Type"] not in CHAPTER_TYPES:
        continue
    stages = [s for s in parse_list(ch["StageID"]) if s in stage_ids]
    chapters.append({
        "id": ch["ID"], "awardStatus": [], "playNum": 0, "highAwardTime": 0, "highAwardNum": 0,
        "stages": [{"id": s, "stars": [0, 0, 0], "isPass": True, "playNum": 0, "leftBlood": 0}
                   for s in stages],
    })

# ---- chapterTeams: the five battle teams the stage list hands to the team picker ----------------------
# InfoGameExtra.SetData passes gameInfo.chapterTeams straight into InfoTeam:SetData, and
# InfoTeam.GetUpRoleCardList indexes stageTeams[1] with no guard, so an empty list makes 入る on any
# stage throw "attempt to index local 'chapterTeam' (a nil value)" before P42 is ever sent.
# Slots 1-5 are the up cards and 6-10 the support cards (InfoTeam.SetBattleTeamInfo).
chapter_teams = []
for i in range(5):
    up = card_ids[i * 5:(i + 1) * 5]
    chapter_teams.append({"id": i + 1, "name": "", "fetterTeamId": 0,
                          "roleCardTeams": up + [0] * (10 - len(up))})

game_info = {
    "openServerTime": past, "chapters": [], "songs": [], "changeNameNum": 0, "touchCnt": 0,
    "touchTime": 0, "activeNextTime": now + 86400000, "messages": [], "voices": [],
    "chapterTeams": chapter_teams, "friendHelpTimes": 0, "headFrameList": [], "medals": [], "heads": [],
    "guides": [], "notices": [], "messGroupId": [], "whipAwardBoxNum": 0, "currentTheme": 0,
    "fetterSkills": [], "webType": 0, "webTime": 0, "webUrl": "", "chapterBuyTimes": [],
    "touchDailyNum": 0, "figureId": [], "dropRaidBossTime": 0, "activeGoods": [],
    "figureAward": [], "questionAward": 0, "powerBuyTimes": 0, "birthdayGoods": [],
}

player_doc = {
    "result": {"code": 0},
    "player": player, "roles": roles, "roleCards": role_cards, "items": items,
    "gameInfo": game_info, "gameRefresh": {"friendHelpTimes": 0, "whipAwardBoxNum": 0,
                                           "chapterBuyTimes": [], "touchDailyNum": 0,
                                           "shareNum": 0, "towerDailyTimes": 0,
                                           "chapters": chapters},
    "themes": [], "ads": [],
    "curFreeTenDrawActivityId": 0, "freeTenDrawCount": 0, "usedTenDrawCount": 0,
    "todayTenDrawCount": 0,
}

# ---- shop: every ShopData row with the goods its ShopGoods lists name -----------------------
# Type 1 (charge) must be IN the response even though it is a dead storefront offline. Its two rows
# (1010101, 1010201) are the only ones carrying TabIndex 1, and ShopManager.SetData
# (InfoShop.lua:247/255) fills listAllIndex[TabIndex] = Type from the response alone. PageShop then
# labels its tab bar with `for _, type in ipairs(ShopManager.listAllIndex)` (PageShop.lua:300), and
# ipairs stops at the first nil key -- so with TabIndex 1 absent, every other tab is discarded with it
# and tabMainCount is 0, which sets all six tab buttons inactive. Dropping charge to hide a broken
# payment SDK therefore did not hide one tab, it hid the whole shop: 道具 and 兑换所, the only tabs
# with goods an offline player can actually buy, became unreachable. The charge tab itself is inert
# (JPShopManager replaces listAll[1] with its billing-product list, which needs the KLab SDK), and a
# purchase attempt just returns 购买已取消.
goods_ok = {r["ID"] for r in one("select ID from GoodsData")}
shop_tab, months = [], []
for s in one("select ID, Type, ShopCloseType from ShopData order by ID"):
    ids = []
    for g in one("select GoodsList from ShopGoods where ShopID=?", s["ID"]):
        ids += [i for i in parse_list(g["GoodsList"]) if i in goods_ok]
    if not ids:
        continue
    shop_tab.append({
        "shopId": s["ID"], "freshAt": 0,  # 0 = never refreshes; a past deadline makes PageShop self-purge (see ProtobufCore.shopWithState)
        "goods": [{"id": i, "myCount": 0, "firsted": False} for i in dict.fromkeys(ids)],
    })
    if s["Type"] == 4:
        months += [{"goodsId": i, "endAt": now + 30 * 86400000, "awardAt": 0} for i in ids[:1]]

shop_doc = {"result": {"code": 0}, "shopTab": shop_tab, "months": months}

# The order of shopTab is load-bearing, not cosmetic: ShopManager.SetData writes
# listAllIndex[TabIndex] = Type and listAllType[Type] = TabIndex once per row, last writer wins, and
# PageShop picks its landing branch from listAllIndex[listAllType[6]]. The 購買部 plate hard-codes
# tabMainIndex = 6 (PageMainStage.lua:1489, package), and UpdateTag's package branch deactivates
# SafeArea/Main/ScrollArea before InitScrollView looks it up, so the entry dies on a .NET
# "Object reference not set", OnRegisterEvent never runs and every tab button is unbound.
# Landing on 道具 instead avoids that branch (its else-branch re-activates the scroll area), which
# needs listAllType[6] to point at an index whose listAllIndex holds Type 2: so SHOP_LANDING, the one
# Type 6 row whose TabIndex the client database moves to 4, is emitted after every other Type 6 row
# and the whole Type 2 group is emitted right after it. The remaining Type 6 rows keep TabIndex 3, so
# the tab bar still fills indices 1-5 and shows all five tabs with their usual labels.
STRIP_SLOT = {1: 1, 4: 2, 6: 3, 2: 4, 3: 5, 5: 0}
SHOP_TYPE = {s["ID"]: s["Type"] for s in one("select ID, Type from ShopData")}
strip = {}
for t in shop_tab:
    ty = SHOP_TYPE[t["shopId"]]
    if ty not in strip or t["shopId"] < strip[ty]:
        strip[ty] = t["shopId"]
TAB_INDEX = {}
for t in shop_tab:
    ty = SHOP_TYPE[t["shopId"]]
    TAB_INDEX[t["shopId"]] = STRIP_SLOT[ty] if t["shopId"] == strip[ty] else 4
strip_ids = set(strip.values())


def landing_rank(shop_id):
    if shop_id in strip_ids:
        return 0
    if SHOP_TYPE[shop_id] == 2:
        return 2
    return 1


shop_tab.sort(key=lambda t: (landing_rank(t["shopId"]), t["shopId"]))
(OUT / "shop_tabindex.json").write_text(
    json.dumps({str(k): v for k, v in sorted(TAB_INDEX.items())}, ensure_ascii=False), encoding="utf-8")
_per = {}
for sid, ty in SHOP_TYPE.items():
    if sid in TAB_INDEX:
        _per[ty] = _per.get(ty, 0) + 1
print("rows per type in response:", sorted(_per.items()))
print("strip rows (type -> shopId -> slot):", sorted((t, i, STRIP_SLOT[t]) for t, i in strip.items()))

(OUT / "player.json").write_text(json.dumps(player_doc, ensure_ascii=False), encoding="utf-8")
(OUT / "shop.json").write_text(json.dumps(shop_doc, ensure_ascii=False), encoding="utf-8")
print("roles=%d roleCards=%d items=%d shops=%d months=%d (shop ids with goods)"
      % (len(roles), len(role_cards), len(items), len(shop_tab), len(months)))
print("player.json %d B, shop.json %d B"
      % ((OUT / "player.json").stat().st_size, (OUT / "shop.json").stat().st_size))
types = {s["ID"]: s["Type"] for s in one("select ID, Type from ShopData")}
print("shop tab types present:", sorted({types[t["shopId"]] for t in shop_tab}))
print("chapters=%d stages=%d levelExp=%d"
      % (len(chapters), sum(len(c["stages"]) for c in chapters), LEVEL_EXP))
print("chapterTeams=%d slots/team=%s"
      % (len(chapter_teams), [len(t["roleCardTeams"]) for t in chapter_teams]))
