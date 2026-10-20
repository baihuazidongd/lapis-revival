#!/usr/bin/env python3
"""Pack the verified resource tree into the APK and move Seed.java's tree gate to match it.

Fourth per-package build-time flip, same shape as pkg_lang.py / pkg_story.py: the archive and the
digest + entry-count constants in Seed.java have to move together, and all of it has to happen BEFORE
javac because those constants are compiled into classes3.dex.

    python pkg_tree.py cn|jp

The archive is STORED, not deflated: measurement on this tree gave 0.970 overall (videos 0.998,
SoundBanks 0.997), so compressing buys 3 % and costs a full pass of CPU. Stored also means the zip
central directory carries an exact uncompressed size for every entry, which is what makes Seed's
"same name, same size => same bytes" resume rule sound rather than hopeful.

Entries are rooted at the package's external-files dir, so an entry "JP/AssetBundles/..." lands at
getExternalFilesDir(null)/JP/AssetBundles/...
"""
import hashlib
import os
import pathlib
import re
import sys
import zipfile

STAGING = {
    'cn': pathlib.Path('E:/lapis/build_full/tree_src'),
    'jp': pathlib.Path('E:/lapis/build_full/tree_src_jp'),
}
ASSET = pathlib.Path('C:/lapisbuild/game_decoded/assets/res/JP/tree.zip')
SEED = pathlib.Path('C:/lapisbuild/stubapp/src/com/klab/lapis/stub/Seed.java')
ARCHIVE = {'cn': pathlib.Path('E:/lapis/build_full/tree_cn.zip'),
           'jp': pathlib.Path('E:/lapis/build_full/tree_jp.zip')}
STAGING = {}
SHA_RE = re.compile(r'(TREE_SHA1\s*=\s*")([0-9A-F]{40})(")')
MIN_RE = re.compile(r'(TREE_MIN\s*=\s*)(\d+)(;)')


def build(target):
    # The archive itself is produced by make_tree_zip.py, which walks the DEVICE manifest and picks
    # each file from the pulled overlay or the host mirror. This script only stages it and moves the
    # gate constants; building a 5.6 GB archive here would duplicate that provenance logic.
    out = ARCHIVE[target]
    if not out.is_file():
        sys.exit('missing %s - run make_tree_zip.py first' % out)
    with zipfile.ZipFile(out) as z:
        entries = sum(1 for e in z.namelist() if not e.endswith('/'))
    # Streamed on purpose: this archive is gigabytes and read_bytes()/write_bytes() would try to
    # hold all of it in RAM twice.
    size = out.stat().st_size
    h = hashlib.sha1()
    with out.open('rb') as f:
        for chunk in iter(lambda: f.read(1 << 20), b''):
            h.update(chunk)
    digest = h.hexdigest().upper()
    ASSET.parent.mkdir(parents=True, exist_ok=True)
    ASSET.write_bytes(b'')
    with out.open('rb') as src, ASSET.open('wb') as dst:
        while True:
            chunk = src.read(1 << 20)
            if not chunk:
                break
            dst.write(chunk)
    text = SEED.read_text(encoding='utf-8')
    new, n = SHA_RE.subn(lambda m: m.group(1) + digest + m.group(3), text)
    if n != 1:
        sys.exit('Seed.java TREE_SHA1 site not found')
    new, n2 = MIN_RE.subn(lambda m: m.group(1) + str(entries) + m.group(3), new)
    if n2 != 1:
        sys.exit('Seed.java TREE_MIN site not found')
    SEED.write_text(new, encoding='utf-8')
    print('tree -> %s  %.2f GB  %d files  sha1 %s' % (target, size / 2**30, entries, digest))


def restore(target):
    """Remove the packaged tree and reset the gate, for a build that should not carry one."""
    if ASSET.exists():
        ASSET.unlink()
    text = SEED.read_text(encoding='utf-8')
    text = SHA_RE.sub(lambda m: m.group(1) + '0' * 40 + m.group(3), text)
    text = MIN_RE.sub(lambda m: m.group(1) + '1' + m.group(3), text)
    SEED.write_text(text, encoding='utf-8')
    print('tree removed from staged build')


if len(sys.argv) < 2 or sys.argv[1] not in ('cn', 'jp', 'none'):
    sys.exit('usage: pkg_tree.py cn|jp|none')
if sys.argv[1] == 'none':
    restore('cn')
else:
    build(sys.argv[1])
