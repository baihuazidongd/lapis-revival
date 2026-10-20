#!/usr/bin/env python3
"""Merge the premium story-translation batches into the shipped CN language database.

The batches come from subagents as `id<TAB>简体` files under E:/lapis/work/story_cn. Nothing from
their chat replies is ever spliced into the data -- CJK mutates when it travels through a tool
payload -- so this reads only the files they wrote, and it refuses the whole merge on the first
record that breaks the contract, because a malformed row becomes a broken string inside the game.

Gates, in order: id set and order equal to the batch's source file, exactly one tab per line, no
newline inside a value, no kana left, rich-text tags and format placeholders multiset-identical to
the source, and every character in the result inside glyphset + ASCII + the characters the JP source
of that same row already used (that union is what the client's own font is known to draw).
"""
import glob
import hashlib
import io
import os
import re
import shutil
import sqlite3
import sys

STORY = r'E:/lapis/work/story_cn'
# Layer on top of the table that is actually on the device (base + arbitration + UNIFY), so rows the
# premium pass does not touch keep the fixes that put them there.
BASE = r'C:/lapisbuild/cn/out/master_data_lang.db'
JPDB = r'C:/lapisbuild/jp_lang.db'
GLYPHSET = r'C:/lapisbuild/cn/glyphset.txt'
WORK = r'C:/lapisbuild/cn/out/master_data_lang_story.db.part'
FINAL = r'C:/lapisbuild/cn/out/master_data_lang.db'

KANA = re.compile(u'[\u3040-\u30fe\uff66-\uff9f]')
# Only the real rich-text tags are markup. The JP text also uses <...> to bracket a skill or card
# name (<ヒールソード>), and translating the inside of one of those is correct, not a tag mismatch.
TAG = re.compile(u'</?(?:size|color|b|i|u|s|nobreak|alpha|font)[^>]*>')
PLACE = re.compile(u'%[sd]|\\\\n|\\{[A-Za-z_0-9]+\\}|\\[[0-9a-z%]+\\]')


def read_batch(path):
    out = []
    with io.open(path, encoding='utf-8') as f:
        for n, line in enumerate(f, 1):
            line = line.rstrip(u'\n').rstrip(u'\r')
            if not line:
                continue
            parts = line.split(u'\t')
            if len(parts) != 2:
                sys.exit('%s:%d expected 2 tab-separated fields, got %d' % (os.path.basename(path), n, len(parts)))
            if not parts[0].isdigit():
                sys.exit('%s:%d id is not numeric: %r' % (os.path.basename(path), n, parts[0]))
            out.append((int(parts[0]), parts[1]))
    return out


def main():
    problems = []
    glyphset = set(io.open(GLYPHSET, encoding='utf-8-sig').read()) | set(chr(c) for c in range(0x20, 0x7F))
    jp = sqlite3.connect('file:%s?mode=ro' % JPDB.replace('\\', '/'), uri=True)
    src_val = dict((int(i), v or u'') for i, v in jp.execute('select ID,Value from Language'))
    jp.close()

    done = sorted(glob.glob(os.path.join(STORY, 'batch_*_cn.tsv')))
    if not done:
        sys.exit('no batch output files yet')
    fixes = {}
    fix_path = os.path.join(STORY, 'fixes.tsv')
    if os.path.exists(fix_path):
        for i, v in read_batch(fix_path):
            fixes[i] = v
    merged = {}
    report = []
    for out_path in done:
        src_path = out_path.replace('_cn.tsv', '_src.tsv')
        want = read_batch(src_path)
        got = read_batch(out_path)
        if [i for i, _ in want] != [i for i, _ in got]:
            sys.exit('%s ids diverge from %s' % (os.path.basename(out_path), os.path.basename(src_path)))
        for (i, s), (j, v) in zip(want, got):
            v = fixes.get(i, v)
            if not v.strip():
                problems.append('%s id %d empty value' % (os.path.basename(out_path), i)); continue
            if KANA.search(v):
                problems.append('%s id %d still contains kana' % (os.path.basename(out_path), i)); continue
            if sorted(TAG.findall(s)) != sorted(TAG.findall(v)):
                problems.append('%s id %d tags %r vs %r' % (os.path.basename(out_path), i, sorted(TAG.findall(s)), sorted(TAG.findall(v))))
            if sorted(PLACE.findall(s)) != sorted(PLACE.findall(v)):
                problems.append('%s id %d placeholders %r vs %r' % (os.path.basename(out_path), i, sorted(PLACE.findall(s)), sorted(PLACE.findall(v))))
            allowed = glyphset | set(src_val.get(i, u''))
            bad = set(v) - allowed
            if bad:
                problems.append('%s id %d introduces %s' % (os.path.basename(out_path), i, ' '.join('U+%04X' % ord(c) for c in sorted(bad))))
            merged[i] = v
        report.append('%s %d rows' % (os.path.basename(out_path), len(got)))

    if problems:
        with io.open(os.path.join(STORY, 'gate_problems.txt'), 'w', encoding='utf-8') as fh:
            for line in problems:
                fh.write(line + u'\n')
        print('%d records rejected, see story_cn/gate_problems.txt' % len(problems))
        sys.exit(1)

    out_path = sys.argv[1] if len(sys.argv) > 1 else FINAL
    shutil.copyfile(BASE, WORK)
    db = sqlite3.connect(WORK)
    db.executemany('update Language set Value = ? where ID = ?', [(v, k) for k, v in sorted(merged.items())])
    db.commit()
    total = db.execute('select count(*) from Language').fetchone()[0]
    db.close()
    os.replace(WORK, out_path)
    data = open(out_path, 'rb').read()
    print('\n'.join(report))
    print('merged rows  %d -> %s' % (len(merged), out_path))
    print('table rows   %d (expected 30687)' % total)
    print('md5   %s' % hashlib.md5(data).hexdigest())
    print('sha1  %s' % hashlib.sha1(data).hexdigest().upper())


main()
