#!/usr/bin/env python3
"""Splice translated CN text back into master_data_lang.db.

    python apply_cn.py --translations T1.md T2.md ... [--out master_data_lang_cn.db] [--apply]

The worklist (`translate/JA-ZH_ALL.md`) carries one representative ID per *distinct* original
value, because 30,687 Language rows collapse to 18,113 unique strings. So a returned translation is
expanded to every row that shared that original value -- matching on the value, never on the ID
alone. The ID->original mapping is re-read from the worklist itself rather than recomputed, which
means this script cannot drift from whatever version of gen_translate_md.py produced the file.

Accepts the formats a chat model actually returns: `ID<TAB>text`, `ID<TAB>original<TAB>text`,
`ID|text`, `- ID: text`, markdown fences, CRLF. Anything it had to guess about is counted in the
report so a wrong shape is visible before it reaches the device.

Refuses to write unless coverage is complete and every placeholder/rich-text tag survived; --force
overrides, nothing overrides the byte-level re-read after writing.
"""
import argparse
import hashlib
import re
import shutil
import sqlite3
import sys
from collections import Counter, defaultdict
from pathlib import Path

WORKLIST = Path(r'E:/lapis/translate/JA-ZH_ALL.md')
SRC_DB = Path(r'E:/lapis/revival/local/resources/master_data_lang.db')
CJK = re.compile(r'[\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff\uff66-\uff9f]')
FMT = re.compile(r'%(?:\d+\$)?[-+ #0]*\d*(?:\.\d+)?[sdfeEgGxXoc%]')
TAG = re.compile(r'</?[a-zA-Z][^>]*>')
BEGIN = re.compile(r'^===\s*BEGIN\s+(\S+?)\s*\(ID\s+(\d+),')
END = re.compile(r'^===\s*END\s+(\S+?)\s*===')
ENTRY = re.compile(r'^\s*(?:[-*]\s*)?(\d{1,8})\s*[\t|:,\s]\s*(.*)$')
TBL = re.compile(r'^\s*\|?\s*(\d{1,8})\s*\|(.*)$')
KANA = re.compile(r'[\u3040-\u30ff\uff66-\uff9f]')


def read_text(path, stats=None):
    """Decode a returned translation file. A Chinese Windows editor can hand back GB18030, and
    decoding it as UTF-8 would mangle every character, so the fallback is recorded not silent."""
    raw = Path(path).read_bytes()
    if raw.startswith(b'\xef\xbb\xbf'):
        if stats is not None:
            stats['utf8-bom'] += 1
        return raw[3:].decode('utf-8').replace('\r\n', '\n')
    try:
        txt = raw.decode('utf-8')
    except UnicodeDecodeError:
        if stats is not None:
            stats['gb18030'] += 1
        return raw.decode('gb18030').replace('\r\n', '\n')
    return txt.replace('\r\n', '\n')


def parse_worklist(path):
    """id -> original value, plus the Terms documents, straight out of the worklist file."""
    texts, terms, in_terms = {}, {}, False
    for line in read_text(path).split('\n'):
        if line.startswith('## '):
            in_terms = '3' in line[:14]
            continue
        m, r = BEGIN.match(line), END.match(line)
        if m:
            terms[m.group(1)] = {'id': int(m.group(2)), 'body': []}
            continue
        if r:
            terms[r.group(1)]['body'] = '\n'.join(terms[r.group(1)]['body'])
            continue
        if in_terms:
            continue
        parts = line.split('\t')
        if not parts[0].strip().isdigit():
            continue
        iid = int(parts[0])
        if len(parts) == 2:
            texts[iid] = parts[1]
        elif len(parts) >= 3:
            texts[iid] = parts[2]
    return texts, terms


def parse_terms(path):
    """Recover each Terms document's original body from the worklist (raw text between markers)."""
    out, name, buf = {}, None, []
    for line in read_text(path).split('\n'):
        m, r = BEGIN.match(line), END.match(line)
        if m:
            name, buf = m.group(1), []
            out.setdefault(name, {'id': int(m.group(2))})
            continue
        if r and name:
            out[name]['body'] = '\n'.join(buf).strip('\n')
            name = None
            continue
        if name is not None:
            buf.append(line)
    return out


def parse_translations(paths):
    """id -> list of candidate CN strings (one per line seen). Returns (map, stats, problems).

    A model that echoes the source column back gives two candidates for one id; the caller picks
    the one that isn't the worklist original. Guessing by column position would splice Japanese
    into the DB, so nothing here commits to an order.
    """
    got, stats, problems = defaultdict(list), Counter(), []
    for p in paths:
        raw = read_text(p, stats)
        for line in raw.split('\n'):
            if not line.strip() or line.startswith('#') or line.startswith('```'):
                continue
            parts = [x for x in line.split('\t')]
            head = parts[0].strip()
            if head.startswith('|'):
                m = TBL.match(line)
                if not m:
                    continue
                iid, rest = int(m.group(1)), [x for x in m.group(2).split('|')]
                stats['table'] += 1
            elif head.isdigit():
                iid, rest = int(head), parts[1:]
            else:
                m = ENTRY.match(line)
                if not m:
                    if line.strip():
                        stats['unparsed'] += 1
                        if len(problems) < 12:
                            problems.append('%s: %s' % (Path(p).name, line[:70]))
                    continue
                iid, rest = int(m.group(1)), [m.group(2)]
                stats['lenient'] += 1
            kept = []
            for frag in rest:
                frag = frag.strip().strip('`').strip()
                if frag:
                    kept.append(frag)
            if not kept:
                stats['empty'] += 1
                continue
            got[iid].extend(kept)
    return dict(got), stats, problems


def pick(iid, cands, orig, stats):
    """Choose the CN candidate for an id among what the file actually returned."""
    uniq = list(dict.fromkeys(cands))
    if len(uniq) == 1:
        return uniq[0]
    diff = [c for c in uniq if c != orig]
    if not diff:
        stats['all-equal-original'] += 1
        return uniq[-1]
    if len(diff) == 1:
        stats['echo-original'] += 1
        return diff[0]
    # more than one plausible cell: prefer any that survived translation (kana means untranslated JP)
    nokana = [c for c in diff if not KANA.search(c)]
    if len(nokana) == 1:
        stats['picked-no-kana'] += 1
        return nokana[0]
    stats['ambiguous'] += 1
    return diff[-1]


def check(original, new, iid, issues):
    if CJK.search(new) and re.search(r'[\u3040-\u30ff\uff66-\uff9f]', new):
        issues.append((iid, 'kana-left', new[:48]))
    a, b = FMT.findall(original), FMT.findall(new)
    if Counter(a) != Counter(b):
        issues.append((iid, 'fmt-count', '%r -> %r' % (a, b)))
    ta, tb = [t.lower() for t in TAG.findall(original)], [t.lower() for t in TAG.findall(new)]
    if Counter(ta) != Counter(tb):
        issues.append((iid, 'tag-count', '%d -> %d' % (len(ta), len(tb))))
    if '\n' in new or '\t' in new:
        issues.append((iid, 'newline-or-tab', new[:40]))
    if new == original:
        issues.append((iid, 'unchanged', new[:40]))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--translations', nargs='+', required=True)
    ap.add_argument('--out', default=str(SRC_DB.with_name('master_data_lang_cn.db')))
    ap.add_argument('--apply', action='store_true', help='write the db (default: dry run)')
    ap.add_argument('--force', action='store_true', help='write despite missing entries')
    ap.add_argument('--report', default=r'C:/lapisbuild/apply_cn_report.txt')
    a = ap.parse_args()

    originals, _ = parse_worklist(WORKLIST)
    terms_orig = parse_terms(WORKLIST)
    got, stats, problems = parse_translations(a.translations)

    value_new, issues, unknown = {}, [], []
    for iid, cands in sorted(got.items()):
        if iid not in originals:
            unknown.append(iid)
            continue
        orig = originals[iid]
        txt = pick(iid, cands, orig, stats)
        if orig in value_new and value_new[orig] != txt:
            stats['value_conflict'] += 1
            continue
        check(orig, txt, iid, issues)
        value_new[orig] = txt

    missing = sorted(set(originals) - set(got))
    terms_new = {name: doc['body'] for name, doc in terms_orig.items()}

    for p in a.translations:
        for name, doc in parse_terms(Path(p)).items():
            if name in terms_new and doc['body'] != terms_new[name]:
                terms_new[name] = doc['body']

    lines = ['worklist entries      : %d' % len(originals),
             'translation lines read: %d' % len(got),
             'parse stats           : %s' % (dict(stats) or 'clean'),
             'ids not in worklist   : %d %s' % (len(unknown), unknown[:8]),
             'distinct values mapped: %d' % len(value_new),
             'missing entries       : %d %s' % (len(missing), missing[:8]),
             'quality issues        : %d' % len(issues),
             'terms docs present    : %d' % len(terms_new)]
    for kind in ('kana-left', 'fmt-count', 'tag-count', 'newline-or-tab', 'unchanged'):
        n = sum(1 for i in issues if i[1] == kind)
        if n:
            lines.append('   %-14s %d  e.g. %s' % (kind, n, issues[[i[1] for i in issues].index(kind)][:3]))
    if problems:
        lines.append('unparsed samples      :')
        lines += ['   ' + p for p in problems]

    c = sqlite3.connect('file:%s?mode=ro' % SRC_DB, uri=True)
    c.text_factory = str
    rows = c.execute('select ID, Value from Language').fetchall()
    c.close()
    plan = {iid: value_new[v] for iid, v in rows if v in value_new}
    lines.append('db rows total         : %d' % len(rows))
    lines.append('db rows to be updated : %d (from %d distinct values)' % (len(plan), len(value_new)))
    jp_left = sum(1 for iid, v in rows if v and CJK.search(v) and iid not in plan)
    lines.append('db rows still Japanese: %d' % jp_left)
    dup = len(rows) - len({iid for iid, _ in rows})
    lines.append('duplicate row ids     : %d' % dup)
    if dup:
        print('ABORT: Language.ID is not unique; an id-keyed plan would silently pick one value.')
        return 3

    report = '\n'.join(lines)
    Path(a.report).write_text(report + '\n' + '\n'.join('%d\t%s\t%s' % i for i in issues),
                              encoding='utf-8')
    print(report)

    if not a.apply:
        print('\nDRY RUN, nothing written. Re-run with --apply.')
        return 0
    if (missing or issues) and not a.force:
        print('\nREFUSING to write: %d missing, %d issues. Fix them or pass --force.'
              % (len(missing), len(issues)))
        return 2

    out = Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(SRC_DB, out)
    d = sqlite3.connect(str(out))
    d.text_factory = str
    base_changes = d.total_changes
    with d:
        d.executemany('update Language set Value=? where ID=?',
                      [(txt, iid) for iid, txt in sorted(plan.items())])
        for name, body in terms_new.items():
            if body == terms_orig[name]['body']:
                continue          # no translation came back; leave the JP text rather than rewriting it
            d.execute('update Terms set Value=? where ID=?', (body, terms_orig[name]['id']))
    changed = d.total_changes - base_changes
    d.commit()
    d.close()

    # row-exact re-read: every planned id must hold its intended text, and nothing else may have moved
    chk = sqlite3.connect('file:%s?mode=ro' % out.as_posix(), uri=True)
    chk.text_factory = str
    ok = chk.execute('pragma integrity_check').fetchone()[0]
    after = dict(chk.execute('select ID, Value from Language').fetchall())
    terms_after = {i: v for i, v in chk.execute('select ID, Value from Terms').fetchall()}
    chk.close()
    bad = [i for i, txt in plan.items() if after.get(i) != txt]
    before = dict(rows)
    drifted = [i for i, v in before.items() if i not in plan and after.get(i) != v]
    t_bad = [i for i, v in terms_after.items()
             if i in {d_['id'] for d_ in terms_orig.values()} and v is None]
    left = len(after)
    jp = sum(1 for i, v in after.items() if v and CJK.search(v) and i not in plan)
    data = out.read_bytes()
    print('\nwrote %s  %d B  rows=%d  updated=%d  still-Japanese=%d'
          % (out, len(data), left, changed, jp))
    print('plan mismatches       : %d %s' % (len(bad), bad[:8]))
    print('unplanned rows moved  : %d %s' % (len(drifted), drifted[:8]))
    print('null terms rows       : %d %s' % (len(t_bad), t_bad[:8]))
    print('sqlite integrity      : %s' % ok)
    print('sha1=%s  md5=%s' % (hashlib.sha1(data).hexdigest().upper(),
                               hashlib.md5(data).hexdigest().upper()))
    if bad or drifted or t_bad or ok != 'ok':
        print('VERIFY FAILED -- do not serve this file.')
        return 4
    print('NOTE: the client rename-swaps the installed .db, so replace the served copy and let it '
          'reinstall rather than editing /data in place. See mirror_hash.sh for the sidecar trap.')
    return 0


if __name__ == '__main__':
    sys.exit(main())
