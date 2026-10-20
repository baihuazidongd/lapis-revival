#!/usr/bin/env python3
"""Switch the packaged story tree between the CN and JP builds.

Same shape as pkg_lang.py and for the same reason: `Seed.java` pins the SHA-1 of the archive it will
extract, so the asset and the constant have to move together. Flipping one without the other produces
a build that either refuses its own tree at boot ("SEED story refused") or, worse, extracts the wrong
language's bundles while its gate reports success.

    python pkg_story.py cn|jp

Sources are zips built from the RUNNING device trees (not from scn_staged, which is 9 files short of
the real tree), each file compared byte for byte against the tree it came from before packing.
JP has no zip yet on purpose: the build then fails loudly rather than shipping CN text in a JP shell.
"""
import hashlib
import pathlib
import re
import sys

ASSET = pathlib.Path('C:/lapisbuild/game_decoded/assets/res/JP/story.zip')
SEED = pathlib.Path('C:/lapisbuild/stubapp/src/com/klab/lapis/stub/Seed.java')
SRC = {
    'cn': pathlib.Path('C:/lapisbuild/story_cn.zip'),
    'jp': pathlib.Path('C:/lapisbuild/story_jp.zip'),
}
PIN_RE = re.compile(r'(STORY_SHA1\s*=\s*")([0-9A-F]{40})(")')
COUNT_RE = re.compile(r'(STORY_MIN\s*=\s*)(\d+)(;)')


def main(target):
    src = SRC[target]
    if not src.exists():
        sys.exit('missing story archive %s - build it from that package\'s device tree first' % src)
    data = src.read_bytes()
    ASSET.parent.mkdir(parents=True, exist_ok=True)
    ASSET.write_bytes(data)
    digest = hashlib.sha1(data).hexdigest().upper()
    import zipfile, io as _io
    with zipfile.ZipFile(_io.BytesIO(data)) as z:
        files = sum(1 for e in z.namelist() if not e.endswith('/'))
    text = SEED.read_text(encoding='utf-8')
    new, n = PIN_RE.subn(lambda m: m.group(1) + digest + m.group(3), text)
    if n != 1:
        sys.exit('Seed.java STORY_SHA1 site not found (shape changed?)')
    new, n2 = COUNT_RE.subn(lambda m: m.group(1) + str(files) + m.group(3), new)
    if n2 != 1:
        sys.exit('Seed.java STORY_MIN site not found (shape changed?)')
    SEED.write_text(new, encoding='utf-8')
    print('story tree -> %s  %.1f MB  %d files  sha1 %s'
          % (target, len(data) / 1048576, files, digest))


if len(sys.argv) < 2 or sys.argv[1] not in SRC:
    sys.exit('usage: pkg_story.py cn|jp')
main(sys.argv[1])
