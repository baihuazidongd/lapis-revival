# -*- coding: utf-8 -*-
# Build the final CN language DB.
#
# Written as a copy: the shipped master_data_lang_cn.db belongs to the main
# session's pipeline and two processes must not write one db. Nothing here touches
# a device -- promotion and push are the main session's call.
#
# Three passes, in this order, because the arbitration choices were made from the
# pre-fix table and can still carry a retired term:
#   1. arbitration (source-keyed, 1,511 sources)
#   2. terminology unification, each rule scoped to rows whose JAPANESE contains
#      the term it is about -- 冰冻 also lives in skill names from フリーズ, and
#      those are flavour rather than the 凍結 status
#   3. Terms separator: U+30FB KATAKANA MIDDLE DOT is punctuation, and it sat
#      inside the kana range, so every earlier gate was scoring 支付・结算 as
#      untranslated Japanese. CN enumerates with 、.
#
# Verification runs before the file is kept; on any failure the copy is deleted.

import hashlib
import io
import re
import shutil
import sqlite3
import sys
from collections import Counter
from pathlib import Path

CN = Path(r'C:/lapisbuild/cn')
JP_DB = Path(r'E:/lapis/revival/local/resources/master_data_lang.db')
SHIPPED = CN / 'master_data_lang_cn.db'
ARB = CN / 'arb_src2zh.tsv'
GLYPHSET = CN / 'glyphset.txt'
WORK = CN / 'out' / 'master_data_lang_final.db.part'
FINAL = CN / 'out' / 'master_data_lang.db'

KANA = re.compile(u'[\u3040-\u30fe\uff66-\uff9f]')
MDOT = u'\u30fb'
IDEAL = u'\u3001'

# (label, japanese scoping term, bad string, good string)
# Three rules were dropped after measuring: 菖蒲/篝火/皋月 would each introduce a
# character that is in no glyphset AND in no JP source string, so nothing proves
# the client can draw them, while the shipped table keeps zero such characters.
# A tofu card title costs more than a slightly-off kanji in a name; the three are
# written to PENDING for a font-coverage test to revisit.
UNIFY = [
    (u'frozen status', u'凍結', u'冰冻', u'冻结'),
    (u'evasion stat', u'回避', u'闪避', u'回避'),
    (u'Flora name', u'フローラ', u'芙萝拉', u'芙罗拉'),
    (u'Flora name', u'フローラ', u'芙洛拉', u'芙罗拉'),
    (u'exchange label', u'交換所', u'兑换处', u'兑换所'),
    (u'unlock label', u'クリアで解放', u'开放', u'解锁'),
]
PENDING_RULES = [
    (u'iris name', u'アヤメ', u'昌蒲', u'菖蒲'),
    (u'Homura name', u'ホムラ', u'营火', u'篝火'),
    (u'Satsuki name', u'サツキ', u'高月', u'皋月'),
]
PENDING = CN / 'out' / 'term_font_pending.tsv'


def read_tsv(path, ncols):
    out = []
    with io.open(str(path), encoding='utf-8') as f:
        for line in f:
            line = line.rstrip(u'\n')
            if not line or line.startswith(u'#'):
                continue
            p = line.split(u'\t')
            if len(p) >= ncols:
                out.append(p[:ncols])
    return out


def main():
    jp = sqlite3.connect('file:%s?mode=ro' % JP_DB.as_posix(), uri=True)
    jp_src = dict((int(i), v or u'') for i, v in jp.execute('select ID,Value from Language'))
    jp_terms = dict((int(i), v or u'') for i, v in jp.execute('select ID,Value from Terms'))
    jp.close()

    arb = {}
    for src, zh, chunks in read_tsv(ARB, 3):
        if src == 'source':
            continue
        arb[src] = zh
    sys.stdout.write('arbitration sources: %d\n' % len(arb))

    if WORK.exists():
        WORK.unlink()
    shutil.copyfile(str(SHIPPED), str(WORK))
    d = sqlite3.connect(str(WORK))
    base_changes = d.total_changes

    # ---- pass 1: arbitration, applied to every row carrying that source
    by_source = {}
    for iid, src in jp_src.items():
        by_source.setdefault(src, []).append(iid)
    applied = Counter()
    missing = []
    cur = d.cursor()
    lang_now = dict((int(i), v or u'') for i, v in cur.execute('select ID,Value from Language'))
    for src, want in arb.items():
        ids = by_source.get(src)
        if not ids:
            missing.append(src)
            continue
        for iid in ids:
            if lang_now.get(iid) != want:
                cur.execute('update Language set Value=? where ID=?', (want, iid))
                applied['lang rows'] += 1
                applied['sources landed'] += 1
            else:
                applied['sources already'] += 1
    sys.stdout.write('pass1: %d rows updated, %d sources already correct, %d sources not in table\n'
                     % (applied['lang rows'], applied['sources already'], len(missing)))

    # ---- pass 2: terminology unification
    lang_now = dict((int(i), v or u'') for i, v in cur.execute('select ID,Value from Language'))
    for label, ja_scope, bad, good in UNIFY:
        n = 0
        for iid, src in jp_src.items():
            if ja_scope not in src:
                continue
            v = lang_now.get(iid)
            if v is None or bad not in v:
                continue
            new = v.replace(bad, good)
            if new == v:
                continue
            cur.execute('update Language set Value=? where ID=?', (new, iid))
            lang_now[iid] = new
            n += 1
        applied['unify:%s' % label] = n
        sys.stdout.write('pass2: %-16s %-8s -> %-8s  %d rows\n' % (label, bad, good, n))

    # ---- pass 3: Terms separator.  、 is in the JP source itself, so the font
    # has it; this is not a new glyph.
    n_terms = 0
    for iid, src in jp_terms.items():
        v = cur.execute('select Value from Terms where ID=?', (iid,)).fetchone()
        if not v or not v[0]:
            continue
        new = v[0].replace(MDOT, IDEAL)
        if new != v[0]:
            cur.execute('update Terms set Value=? where ID=?', (new, iid))
            n_terms += 1
    sys.stdout.write('pass3: %d Terms rows re-separated\n' % n_terms)
    d.commit()

    # ---- verification, before the file is kept
    fails = []
    after = dict((int(i), v or u'') for i, v in d.execute('select ID,Value from Language'))
    if len(after) != len(lang_now) or len(after) != len(jp_src):
        fails.append('Language row count changed: %d vs %d' % (len(after), len(jp_src)))
    kana_rows = [i for i, v in after.items() if KANA.search(v)]
    if kana_rows:
        fails.append('%d Language rows still carry kana letters' % len(kana_rows))
    mdot_rows = [i for i, v in after.items() if MDOT in v]
    if mdot_rows:
        fails.append('%d Language rows carry the JP middle dot' % len(mdot_rows))
    terms_after = dict((int(i), v or u'') for i, v in d.execute('select ID,Value from Terms'))
    if len(terms_after) != len(jp_terms):
        fails.append('Terms row count changed')
    tk = [i for i, v in terms_after.items() if KANA.search(v)]
    if tk:
        fails.append('%d Terms rows still carry kana letters: %s' % (tk[:4], len(tk)))
    # every arbitration value must be present, on every one of its rows
    wrong = 0
    for src, want in arb.items():
        for iid in by_source.get(src, []):
            if after.get(iid) != want:
                wrong += 1
    if wrong:
        fails.append('%d arbitration rows did not land' % wrong)
    for label, ja_scope, bad, good in UNIFY:
        left = [i for i, src in jp_src.items() if ja_scope in src and bad in after.get(i, u'')]
        if left:
            fails.append('%s: %d rows still say %s' % (label, len(left), bad))
    # the exact-string invariant that made the shipped table trustworthy
    groups = {}
    for iid, src in jp_src.items():
        groups.setdefault(src, set()).add(after[iid])
    split = [s for s, v in groups.items() if len(v) > 1]
    if split:
        fails.append('%d source strings now render two ways (worst %s)'
                     % (len(split), (split[0][:40] if split else u'')))
    ic = d.execute('pragma integrity_check').fetchone()[0]
    if ic != 'ok':
        fails.append('integrity_check: %s' % ic)
    moved = d.total_changes - base_changes
    d.close()

    glyphs = set(io.open(str(GLYPHSET), encoding='utf-8-sig').read())
    glyphs |= set(chr(i) for i in range(0x20, 0x7F))
    introduced = Counter()
    for iid, src in jp_src.items():
        for ch in set(after[iid]) - glyphs - set(src):
            introduced[ch] += 1
    for iid, src in jp_terms.items():
        for ch in set(terms_after[iid]) - glyphs - set(src):
            introduced[ch] += 1

    if introduced:
        fails.append('%d translator-introduced chars outside glyphset+ascii+source: %s'
                     % (len(introduced), u', '.join(u'U+%04X x%d' % (ord(c), n)
                                                    for c, n in introduced.most_common(8))))

    with io.open(str(PENDING), 'w', encoding='utf-8') as f:
        f.write(u'# deferred until glyph coverage is measured on a real render\n')
        f.write(u'label\tja_scope\tcurrent\twanted\tchar\tin_glyphset\tin_jp_source\n')
        for label, ja, bad, good in PENDING_RULES:
            for ch in set(good) - set(bad):
                f.write(u'%s\t%s\t%s\t%s\tU+%04X\t%s\t%s\n'
                        % (label, ja, bad, good, ord(ch),
                           'no' if ch not in glyphs else 'yes',
                           'yes' if any(ch in (jp_src.get(i) or u'') for i in jp_src) else 'no'))

    if fails:
        sys.stdout.write('VERIFY FAILED\n')
        for x in fails:
            sys.stdout.write('  %s\n' % x)
        WORK.unlink()
        sys.stdout.write('discarded %s, shipped table untouched\n' % WORK.name)
        sys.exit(4)

    if FINAL.exists():
        FINAL.unlink()
    WORK.rename(FINAL)
    data = FINAL.read_bytes()
    sys.stdout.write('\nkept: %s  %d B  rows updated=%d\n' % (FINAL, FINAL.stat().st_size, moved))
    sys.stdout.write('md5   %s\n' % hashlib.md5(data).hexdigest())
    sys.stdout.write('sha1  %s\n' % hashlib.sha1(data).hexdigest().upper())
    sys.stdout.write('Language rows=%d distinct=%d  Terms rows=%d distinct=%d\n'
                     % (len(after), len(set(after.values())), len(terms_after), len(set(terms_after.values()))))
    sys.stdout.write('translator-introduced chars outside glyphset+ascii+source: %d\n' % len(introduced))
    if introduced:
        sys.stdout.write('  %s\n' % u', '.join(u'%s(U+%04X)x%d' % (c, ord(c), n)
                                               for c, n in introduced.most_common(12)))
    sys.stdout.write('shipped table left byte-identical: %s\n' % SHIPPED)


if __name__ == '__main__':
    main()
