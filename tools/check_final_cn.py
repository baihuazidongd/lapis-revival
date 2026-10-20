# -*- coding: utf-8 -*-
# Independent check of the final CN DB. Deliberately not sharing code with
# build_final_cn.py: its verify block and this one agree on nothing except the
# conclusion, so a bug in one shows up here as a disagreement.

import hashlib
import io
import re
import sqlite3
import sys
from collections import Counter, defaultdict
from pathlib import Path

CN = Path(r'C:/lapisbuild/cn')
JP_DB = Path(r'E:/lapis/revival/local/resources/master_data_lang.db')
SHIPPED = CN / 'master_data_lang_cn.db'
FINAL = CN / 'out' / 'master_data_lang.db'
GLYPHSET = CN / 'glyphset.txt'
REPORT = CN / 'out' / 'final_check.txt'

KANA = re.compile(u'[\u3040-\u30fe\uff66-\uff9f]')
MDOT = u'\u30fb'


def tab(path, table):
    d = sqlite3.connect('file:%s?mode=ro' % Path(path).as_posix(), uri=True)
    rows = list(d.execute('select ID,Key,Value from %s' % table))
    d.close()
    return dict((int(i), (k or u'', v or u'')) for i, k, v in rows)


def main():
    f = io.open(str(REPORT), 'w', encoding='utf-8')
    fail = []
    jp_l, jp_t = tab(JP_DB, 'Language'), tab(JP_DB, 'Terms')
    sh_l, sh_t = tab(SHIPPED, 'Language'), tab(SHIPPED, 'Terms')
    fi_l, fi_t = tab(FINAL, 'Language'), tab(FINAL, 'Terms')

    f.write(u'# independent check of %s\n' % FINAL.name)
    f.write(u'size %d  md5 %s  sha1 %s\n\n' % (FINAL.stat().st_size,
              hashlib.md5(FINAL.read_bytes()).hexdigest(),
              hashlib.sha1(FINAL.read_bytes()).hexdigest().upper()))

    # 1. identity: same rows, same keys, only Value may move
    for name, a, b in ((u'Language', sh_l, fi_l), (u'Terms', sh_t, fi_t)):
        if set(a) != set(b):
            fail.append(u'%s id set changed: +%d -%d' % (name, len(set(b) - set(a)), len(set(a) - set(b))))
        keydiff = [i for i in a if i in b and a[i][0] != b[i][0]]
        if keydiff:
            fail.append(u'%s Key column moved on %d rows' % (name, len(keydiff)))
        moved = [i for i in a if i in b and a[i][1] != b[i][1]]
        f.write(u'%s: rows=%d  values changed vs shipped=%d  keys intact=%s\n'
                % (name, len(b), len(moved), not keydiff))

    # 2. nothing was written that the source did not already contain
    glyphs = set(io.open(str(GLYPHSET), encoding='utf-8-sig').read())
    glyphs |= set(chr(i) for i in range(0x20, 0x7F))
    intro = Counter()
    for i, (k, v) in fi_l.items():
        for ch in set(v) - glyphs - set(jp_l.get(i, (u'', u''))[1]):
            intro[ch] += 1
    for i, (k, v) in fi_t.items():
        for ch in set(v) - glyphs - set(jp_t.get(i, (u'', u''))[1]):
            intro[ch] += 1
    if intro:
        fail.append(u'%d chars introduced beyond glyphset+ascii+source' % len(intro))
    f.write(u'new glyphs beyond glyphset+ascii+source: %d\n' % len(intro))

    # 3. script cleanliness
    kana_l = [i for i, (k, v) in fi_l.items() if KANA.search(v)]
    kana_t = [i for i, (k, v) in fi_t.items() if KANA.search(v)]
    mdot = [i for i, (k, v) in fi_l.items() if MDOT in v]
    mdot_t = [i for i, (k, v) in fi_t.items() if MDOT in v]
    f.write(u'kana rows Language=%d Terms=%d ; middle-dot rows=%d/%d\n'
            % (len(kana_l), len(kana_t), len(mdot), len(mdot_t)))
    if kana_l or kana_t or mdot or mdot_t:
        fail.append(u'script residue survived')

    # 4. the exact-string invariant, recomputed from scratch
    by_src = defaultdict(set)
    for i, (k, v) in fi_l.items():
        by_src[jp_l.get(i, (u'', u''))[1]].add(v)
    split = dict((s, v) for s, v in by_src.items() if len(v) > 1)
    f.write(u'source strings with more than one rendering: %d (of %d distinct)\n'
            % (len(split), len(by_src)))
    if split:
        fail.append(u'%d split source strings' % len(split))

    # 5. format placeholders and tags must survive the rewrite, row by row.
    # <br/> is excluded on purpose: it is a hard line-break hint with no closing
    # partner and no styling scope, so dropping it can only change where a bubble
    # wraps. A dropped </color> would print raw markup, and that is what this gate
    # is for. The dropped breaks are counted, not hidden.
    FMT = re.compile(u'%[-0-9.]*[ds]')
    TAG = re.compile(u'</?[a-zA-Z][^<>]*>')
    BR = re.compile(u'<br\\s*/?>', re.I)
    fmt_bad, tag_bad, br_rows = [], [], 0
    for i, (k, v) in fi_l.items():
        src = jp_l.get(i, (u'', u''))[1]
        if Counter(FMT.findall(src)) != Counter(FMT.findall(v)):
            fmt_bad.append(i)
        s_tags = [t for t in TAG.findall(src) if not BR.match(t)]
        v_tags = [t for t in TAG.findall(v) if not BR.match(t)]
        if Counter(t.lower() for t in s_tags) != Counter(t.lower() for t in v_tags):
            tag_bad.append(i)
        if len(BR.findall(src)) != len(BR.findall(v)):
            br_rows += 1
    # attribution: damage this build caused is what must be blocked; damage the
    # shipped table already had is reported but is not this build's regression
    br_rows_sh = 0
    tag_bad_sh = 0
    for i, (k, v) in sh_l.items():
        src = jp_l.get(i, (u'', u''))[1]
        s_tags = [t for t in TAG.findall(src) if not BR.match(t)]
        v_tags = [t for t in TAG.findall(v) if not BR.match(t)]
        if Counter(t.lower() for t in s_tags) != Counter(t.lower() for t in v_tags):
            tag_bad_sh += 1
        if len(BR.findall(src)) != len(BR.findall(v)):
            br_rows_sh += 1
    f.write(u'same gates on the shipped table: tag mismatches=%d  changed line breaks=%d\n'
            % (tag_bad_sh, br_rows_sh))
    f.write(u'placeholder mismatches=%d  tag mismatches(excl br)=%d  rows with a changed '
            u'line-break count=%d\n' % (len(fmt_bad), len(tag_bad), br_rows))
    if fmt_bad or tag_bad:
        fail.append(u'format damage: %d fmt, %d tag' % (len(fmt_bad), len(tag_bad)))

    # 6. the specific calls, each asserted on the row that motivated it
    checks = [
        (u'Flora unified', u'フローラ', u'芙萝拉', False),
        (u'Flora uses 芙罗拉', u'フローラ', u'芙罗拉', True),
        (u'exchange label unified', u'交換所', u'兑换处', False),
        (u'evasion unified', u'回避', u'闪避', False),
        (u'Homura left as-is (font)', u'ホムラ', u'营火', True),
    ]
    for label, ja, needle, want in checks:
        hits = [i for i, (k, v) in fi_l.items() if ja in jp_l.get(i, (u'', u''))[1] and needle in v]
        ok = bool(hits) == want
        f.write(u'  %-30s %-6s in %3d rows  %s\n' % (label, u'present' if want else u'absent',
                                                     len(hits), u'OK' if ok else u'FAIL'))
        if not ok:
            fail.append(u'%s assertion failed' % label)

    d = sqlite3.connect('file:%s?mode=ro' % FINAL.as_posix(), uri=True)
    ic = d.execute('pragma integrity_check').fetchone()[0]
    d.close()
    f.write(u'integrity_check: %s\n' % ic)
    if ic != u'ok':
        fail.append(u'integrity_check %s' % ic)

    f.write(u'\n## verdict\n')
    if fail:
        for x in fail:
            f.write(u'FAIL %s\n' % x)
    else:
        f.write(u'CLEAN -- final db differs from the shipped one only in Values, and passes\n'
                u'every gate the shipped table was built to pass.\n')
    f.close()
    sys.stdout.write('%s  (%s)\n' % (u'CLEAN' if not fail else 'FAIL %d checks' % len(fail), REPORT))
    for x in fail:
        sys.stdout.write('  %s\n' % x.encode('utf-8'))


if __name__ == '__main__':
    main()
