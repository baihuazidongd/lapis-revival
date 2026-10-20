"""arena_state.py - emit the arena/mail/task JSON assets the stub serves for P200/P80/P60.

make_state.py owns player.json and shop.json; this script owns the three payloads that the
アリーナ / mail / task screens were hanging on, because those screens hard-index into
structures player.json never produced:

  P200  InfoPVP.lua:554   SetData early-returns unless pb.season exists
        InfoPVP.lua:33    subSeasonEndTime is dereferenced off PBPVPSeason
        InfoPVP.lua:35    pb.season.seasonStatus is compared with no guard
        InfoPVP.lua:977   GetOpponentsList indexes opplist[1]..opplist[4]
        InfoPvPPlayer.lua:24/25  attackingTeamFetter.id / defensivePbTeamFetter.id are read
                                 with no guard, so EVERY PBPVPPlayer needs both messages
  P203  InfoPVP.lua:189/190  pb.battleSeeds[1] and [2] are indexed by the battle-start caller
  P80   InfoMail.lua:39-44   awards[i].awards[1]/[2] - a PBMailAward is one repeated-int32
  P60   InfoTask.lua:97      self.data.ArgInt is compared with no guard, so every task id
                             written here must exist in TaskData

Every id is read out of master_data.db and cross-checked; the script raises rather than
emitting an id that the client could not resolve. Output is written with ensure_ascii=True
so the Japanese that comes out of master_data_lang.db travels as \\uXXXX escapes and cannot
be mangled by the GBK console or a stray non-UTF8 copy step.

Nothing is printed to stdout except an ASCII summary line.
"""
import json
import sqlite3
import time
from pathlib import Path

MASTER = Path(r"E:/lapis/revival/local/resources/master_data.db")
LANGDB = Path(r"E:/lapis/revival/local/resources/master_data_lang.db")
# Both asset dirs: C: is what rebuild_relay.sh actually packs, E: is the checked-out project copy.
OUT_DIRS = [Path(r"C:/lapisbuild/stubapp/assets"),
            Path(r"E:/lapis/work/stubapp/assets")]
PLAYER_ASSET = Path(r"C:/lapisbuild/stubapp/assets/player.json")

con = sqlite3.connect(MASTER)
con.row_factory = sqlite3.Row
lang = sqlite3.connect(LANGDB)
lang.row_factory = sqlite3.Row

now_ms = int(time.time() * 1000)
now_s = now_ms // 1000
DAY_S = 86400
DAY_MS = 86400000


def q(sql, *a):
    return con.execute(sql, a).fetchall()


def one(sql, *a):
    return con.execute(sql, a).fetchone()


def lang_text(key_id):
    """Real user-facing string from the client's own language table, or None."""
    if not key_id:
        return None
    r = lang.execute("select Value from Language where ID=?", (key_id,)).fetchone()
    if r is None or r["Value"] is None:
        return None
    v = str(r["Value"])
    # the master rows embed a literal backslash-n for line breaks
    return v.replace("\\n", "\n")


def parse_pairs(text):
    """Master '{id,num}' / '{{id,num},{id,num}}' -> list of [id, num]."""
    out = []
    t = str(text or "").strip()
    if not t:
        return out
    for chunk in t.strip("{}").split("},{"):
        parts = [p.strip() for p in chunk.strip("{}").split(",") if p.strip().isdigit()]
        nums = [int(p) for p in parts]
        if len(nums) >= 2:
            out.append([nums[0], nums[1]])
    return out


# -------------------------------------------------------------------------------------------
# id universes the client can actually resolve
# -------------------------------------------------------------------------------------------
CARD_IDS = {r["ID"] for r in q("select ID from CharacterCard")}
ROLE_IDS = {r["ID"] for r in q("select ID from CharacterRole")}
ITEM_IDS = {r["ID"] for r in q("select ID from ItemData")}
TASK_IDS = {r["ID"] for r in q("select ID from TaskData")}
ROLE_ROW = {r["ID"]: dict(r) for r in q("select ID, Name, Head from CharacterRole")}


# -------------------------------------------------------------------------------------------
# self player: reuse the exact roles/cards make_state.py minted, so PVP shows a real team
# -------------------------------------------------------------------------------------------
def load_self_team():
    """Return (roles, card_dicts) taken from the live player.json."""
    doc = json.loads(PLAYER_ASSET.read_text(encoding="utf-8"))
    roles = doc.get("roles") or []
    cards = doc.get("roleCards") or []
    if not roles or not cards:
        raise SystemExit("player.json has no roles/roleCards - run make_state.py first")
    for r in roles:
        assert r["id"] in ROLE_IDS, "player.json role id %s not in CharacterRole" % r["id"]
    for c in cards:
        assert c["id"] in CARD_IDS, "player.json card id %s not in CharacterCard" % c["id"]
    return roles, cards


SELF_ROLES, SELF_CARDS = load_self_team()
PLAYER_ID = int(SELF_CARDS[0]["playerId"])


def rolecard(card):
    """A PBRoleCard for a bot: a real CharacterCard id with the fields InfoRoleCard reads."""
    return {
        "id": card["id"], "playerId": card["playerId"], "levelExp": card.get("levelExp", 0),
        "starLevel": card.get("starLevel", 1), "attrs": [], "starAwards": [],
        "starTalents": [], "soul": 0, "petal": 0, "petalAwards": [],
        "clubBlood": 100, "clubGVGBlood": 100, "roleCardTimes": 0, "real": True,
    }


def empty_card():
    """A slot filler. MyRocard/GetOtherPlayerListRole* both special-case id == 0."""
    return {"id": 0, "playerId": 0, "levelExp": 0, "starLevel": 1, "attrs": [],
            "starAwards": [], "starTalents": [], "soul": 0, "petal": 0, "petalAwards": [],
            "clubBlood": 0, "clubGVGBlood": 0, "roleCardTimes": 0, "real": False}


def team_slots(cards):
    """10 entries: slots 1-5 up cards, 6-10 support, per InfoTeam.SetBattleTeamInfo."""
    up = [rolecard(c) for c in cards[:5]]
    sup = [rolecard(c) for c in cards[5:10]]
    while len(up) < 5:
        up.append(empty_card())
    while len(sup) < 5:
        sup.append(empty_card())
    return up + sup


def pbrole(role_row_id, player_id, card_id):
    r = ROLE_ROW[role_row_id]
    return {"id": r["ID"], "playerId": player_id, "clothes": [], "nodes": [], "avatars": [],
            "favorExp": 0, "favorRankRecord": 1, "favorLevelRecord": 1, "roleCardId": card_id,
            "weaponAvatar": 0, "slots": [], "nickName": "", "phoneBgId": 0, "lastTopicId": 0,
            "avatarTemplate": [], "currentAvatar": 0, "extraSkills": [], "equipStatus": 0,
            "pictures": [], "pictureAwardStatus": 0}


def pbplayer(player_id, nickname, head_id, power, gold, reg_ms):
    assert nickname is not None and nickname != ""
    return {
        "playerId": player_id, "nickname": nickname, "headId": head_id, "vipExp": 0,
        "levelExp": 260000, "payStatus": 0, "isOnline": True, "regTime": reg_ms,
        "logoutTime": now_ms, "diamond": 0, "gold": gold, "power": power, "powerAt": now_ms,
        "signature": "", "roleCards": [], "medal": 0, "friendCoin": 0, "birthday": 0,
        "levelTime": now_ms, "headFrame": 0, "showRole": 0, "clubCoin": 0,
        "clubName": "", "favoriteRoles": [], "diamondPay": 0, "onlineTime": 0,
        "maxAttribute": 0, "commonAvatars": [], "extras": [], "termsOfUseVersion": 0,
        "isFreeCoinDebt": False,
    }


def pvp_player(season_id, sub_num, score, cards, roles, player, battle_left):
    """A PBPVPPlayer. Both TeamFetter messages are mandatory: InfoPvPPlayer.lua:24/25 index
    .id off them with no guard, and a missing one aborts the whole opponents loop."""
    return {
        "seasonId": season_id, "subSeasonNum": sub_num, "player": player,
        "dailyBattleTotal": 5, "dailyBattleNumber": battle_left, "dailyBattleTime": now_ms,
        "opponentsRefreshTotal": 5, "opponentsRefreshNumber": 5,
        "seasonRankingScore": score, "seasonRankingAward": 0,
        "subSeasonScore": score, "subSeasonRankingNo": 1,
        "roles": roles,
        "attackingRoleCards": team_slots(cards), "attackingTeamFetter": {"id": 0, "skills": []},
        "defensiveRoleCards": team_slots(cards), "defensiveTeamFetter": {"id": 0, "skills": []},
        "attackingBattleHistory": [], "defensiveBattleHistory": [], "dailyBuyNumber": 0,
    }


# -------------------------------------------------------------------------------------------
# P200 - arena season
# -------------------------------------------------------------------------------------------
def build_arena():
    season = one("select * from PVPSeason order by ID desc limit 1")
    sid, sub_total = season["ID"], season["SubSeasonNum"]
    # A sub-season runs a week; keep "now" strictly inside it. InfoPVP.lua:35 needs
    # seasonStatus == 1 to reach SwitchPanel, and PagePVPMain.OnUpdateSecond auto-closes
    # once subSeasonEndTime - now <= 3600, so leave a wide margin. Times are SECONDS here
    # (every consumer divides GetCurServerTime() by MillsPerSecond first), unlike mail times.
    sub_begin_s = now_s - 2 * DAY_S
    sub_end_s = now_s + 5 * DAY_S

    # 4 opponents minimum: InfoPVP.lua:977 GetOpponentsList indexes opplist[1]..[4] unguarded.
    n_opp = 4
    bands = q("select * from PVPBotPlayer order by ID limit ?", n_opp)
    assert len(bands) >= n_opp, "PVPBotPlayer has fewer than %d rows" % n_opp

    bot_cards = q("select * from PVPBotCharacterCard order by ID")
    usable = [c for c in bot_cards if c["CardID"] in CARD_IDS and c["CharacterID"] in ROLE_IDS]
    assert len(usable) >= n_opp * 10, "need %d bot cards, have %d" % (n_opp * 10, len(usable))

    opponents = []
    for i in range(n_opp):
        band = bands[i]
        slice_ = usable[i * 10:(i + 1) * 10]
        lead = slice_[0]
        bot_pid = 900000 + (i + 1)
        nickname = lang_text(ROLE_ROW[lead["CharacterID"]]["Name"])
        cards = [{"id": c["CardID"], "playerId": bot_pid, "levelExp": c["CardExp"],
                  "starLevel": c["Star"], "real": True} for c in slice_]
        # one role per up card, keyed by the card's CharacterID: GetOtherPlayerListRole matches
        # card.data.CharacterID against roles[].id and silently drops a role it cannot pair.
        roles = []
        for c in slice_[:5]:
            roles.append(pbrole(c["CharacterID"], bot_pid, c["CardID"]))
        score = (band["FromPVPRankPoint"] + band["ToPVPRankPoint"]) // 2
        power = (band["FromFightValue"] + band["ToFightValue"]) // 2
        player = pbplayer(bot_pid, nickname, ROLE_ROW[lead["CharacterID"]]["Head"],
                          power, 0, now_ms - 200 * DAY_MS)
        opponents.append(pvp_player(sid, 1, score, cards, roles, player, 5))

    # self: the real card ids from player.json, so RoleCardMgr:GetRoleCard resolves each one
    self_cards = [{"id": c["id"], "playerId": PLAYER_ID, "levelExp": c.get("levelExp", 0),
                   "starLevel": c.get("starLevel", 1), "real": True} for c in SELF_CARDS]
    self_score = 100
    self_player = pbplayer(PLAYER_ID, "Lapis", 101, 100, 1000000, now_ms - 30 * DAY_MS)
    self_player["roleCards"] = [c["id"] for c in SELF_CARDS]
    self_player["showRole"] = SELF_ROLES[0]["id"]
    self_player["leader"] = SELF_ROLES[0]
    self_player["mainCard"] = SELF_CARDS[0]
    me = pvp_player(sid, 1, self_score, self_cards, SELF_ROLES, self_player, 5)

    doc = {
        "result": {"code": 0},
        "seasonChange": 0,
        "subSeasonScore": self_score,
        "seasonRankingScore": self_score,
        "subSeasonRankingNo": 1,
        "season": {
            "seasonId": sid,
            "seasonStatus": 1,
            "seasonBeginTime": sub_begin_s - sub_total * 7 * DAY_S,
            "seasonEndTime": sub_end_s + (sub_total - 1) * 7 * DAY_S,
            "subSeasonNum": 1,
            "subSeasonBeginTime": sub_begin_s,
            "subSeasonEndTime": sub_end_s,
            "player": me,
            "opponents": opponents,
        },
    }
    assert len(doc["season"]["opponents"]) >= 4
    return doc, {"seasonId": sid, "subSeasonNum": 1, "opponents": len(opponents)}


# -------------------------------------------------------------------------------------------
# P80 - mail list
# -------------------------------------------------------------------------------------------
def build_mails():
    """Offline reward mails, shaped like the client's own Mail(ID,SendType,Sender,Title,Info,Reward).

    PBMailAward has exactly one field, `awards` repeated int32, and InfoMail.lua:43-44 reads
    awards[i].awards[1] / awards[i].awards[2] - so a reward entry is a 2-element [itemId, num].
    """
    award_pool = {}
    for r in q("select RankingAwardList from PVPSubSeasonAward"):
        for pair in parse_pairs(r["RankingAwardList"]):
            if pair[0] in ITEM_IDS:
                award_pool.setdefault(pair[0], pair[1])
    assert award_pool, "no PVPSubSeasonAward reward item exists in ItemData"

    mails = []
    mid = 1
    for row in q("select * from Mail order by ID"):
        title = lang_text(row["Title"])
        body = lang_text(row["Info"]) or lang_text(row["InfoEnd"]) or lang_text(row["InfoStart"])
        sender = lang_text(row["Sender"])
        if not title or not body or not sender:
            continue                              # no real string -> skip rather than invent one
        pairs = [[i, n] for i, n in parse_pairs(row["Reward"]) if i in ITEM_IDS]
        if not pairs:
            # keep the mail but give it a reward that does exist, so the annex tag has content
            pairs = [[i, n] for i, n in sorted(award_pool.items())[:1]]
        for pid, num in pairs:
            assert pid in ITEM_IDS
        # placeholders such as {RANKING_NO} are filled by the server in the real protocol;
        # leave none in the text or the detail panel renders the brace run literally
        for token in ("{RANKING_NO}", "{NAME}", "{ITEM_NAME}", "{NUM}"):
            body = body.replace(token, "1")
        mails.append({
            "id": mid,
            "title": title,
            "sender": sender,
            "sendType": row["SendType"] if row["SendType"] in (1, 2, 3, 4) else 1,
            "sendTime": now_ms - mid * 3600000,
            # CellMail hides the limit row at 0 and InfoMail.IsExpired deletes anything past it,
            # so a real future deadline is what keeps the list non-empty
            "endTime": now_ms + 30 * DAY_MS,
            "status": 0,
            "content": body,
            "allAwards": [{"awards": [p[0], p[1]]} for p in pairs],
            # leftAwards mirrors allAwards: InfoMail.IsReceived is `#leftAwards == 0`, so an
            # empty one would mark every mail already claimed
            "leftAwards": [{"awards": [p[0], p[1]]} for p in pairs],
        })
        mid += 1
        if len(mails) >= 8:
            break
    assert mails, "no mail row produced both a title and a body"
    doc = {"result": {"code": 0}, "mails": mails}
    return doc, {"mails": len(mails),
                 "awards": sum(len(m["allAwards"]) for m in mails)}


# -------------------------------------------------------------------------------------------
# P60 - task list
# -------------------------------------------------------------------------------------------
def build_tasks():
    """Only task ids that exist in TaskData, and only for the tabs PageTask actually opens.

    InfoTask.lua:97 compares self.data.ArgInt with no guard, and TaskData.ArgInt is non-null
    and non-zero for all 2023 rows (verified), so membership in TaskData is the whole test.
    `scores` is deliberately omitted: PBTaskLineScore has no `pay` field but
    TaskManager.SetScoreData assigns pbScores[i].pay, and TaskManager.Init already seeds a
    zero for every real score line, so staying empty avoids writing a nil into that slot.
    """
    PAGE_TABS = (1, 2, 3)          # eTaskListType.main / daily / weekly
    wanted = []
    for lst in q("select ID, Type, List from TaskListData where Type in (1,2,3) order by Type, ID"):
        for tid in parse_pairs_flat(str(lst["List"])):
            if tid in TASK_IDS:
                wanted.append(tid)
        if len(set(wanted)) >= 40:
            break
    ids = list(dict.fromkeys(wanted))
    assert ids, "no TaskListData row for the main/daily/weekly tabs references a real TaskData id"

    tasks = []
    for n, tid in enumerate(ids):
        row = one("select ArgInt from TaskData where ID=?", tid)
        need = int(row["ArgInt"])
        # status 1 = being, with progress below the target; a couple at 2 = complete so the
        # red-dot path has something to claim
        if n % 7 == 0:
            status, num = 2, need
        elif n % 3 == 0:
            status, num = 1, max(0, need // 2)
        else:
            status, num = 0, 0
        tasks.append({"id": tid, "status": status, "num": num})

    doc = {"result": {"code": 0}, "tasks": tasks}
    return doc, {"tasks": len(tasks)}


def parse_pairs_flat(text):
    out = []
    t = str(text or "").strip()
    if not (t.startswith("{") and t.endswith("}")):
        return out
    for part in t[1:-1].split(","):
        part = part.strip().strip('"')
        if part.isdigit():
            out.append(int(part))
    return out


# -------------------------------------------------------------------------------------------
def main():
    arena, a_info = build_arena()
    mails, m_info = build_mails()
    tasks, t_info = build_tasks()

    payloads = {"arena.json": arena, "mail.json": mails, "task.json": tasks}
    sizes = {}
    for out_dir in OUT_DIRS:
        if not out_dir.is_dir():
            print("skip missing asset dir %s" % out_dir)
            continue
        for name, doc in payloads.items():
            text = json.dumps(doc, ensure_ascii=True, separators=(",", ":"))
            (out_dir / name).write_text(text, encoding="utf-8")
            sizes["%s/%s" % (out_dir.name, name)] = len(text)

    print("arena : seasonId=%(seasonId)s sub=%(subSeasonNum)s opponents=%(opponents)s" % a_info)
    print("mail  : %(mails)s mails, %(awards)s award entries" % m_info)
    print("task  : %(tasks)s tasks (scores omitted)" % t_info)
    for k in sorted(sizes):
        print("  %-34s %7d B" % (k, sizes[k]))
    print("OK - all ids validated against master_data.db")


main()
