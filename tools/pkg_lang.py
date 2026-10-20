#!/usr/bin/env python3
"""Switch the packaged language database between the CN and JP builds.

One decoded tree feeds two APKs, and the only content difference that matters is the language
table. `Seed.java` pins the SHA-1 of the database it will restore at boot and refuses anything that
does not match, so the asset and its pin have to move together -- flipping one without the other
produces a build that certifies bytes it never packaged, or a client that restores the wrong table
over the right one.

    python pkg_lang.py cn|jp

CN  <- C:/lapisbuild/cn/out/master_data_lang.db (the reviewed 30,687-row table)
JP  <- C:/lapisbuild/jp_lang.db           (the shipped Japanese table)
Both paths are snapshots, never the live device file, so this is idempotent and reversible.
"""
import hashlib
import pathlib
import re
import sys

ASSET = pathlib.Path('C:/lapisbuild/game_decoded/assets/res/JP/master_data_lang.db')
SEED = pathlib.Path('C:/lapisbuild/stubapp/src/com/klab/lapis/stub/Seed.java')
SRC = {
    'cn': pathlib.Path('C:/lapisbuild/cn/out/master_data_lang.db'),
    'jp': pathlib.Path('C:/lapisbuild/jp_lang.db'),
}
PIN_RE = re.compile(r'("res/JP/master_data_lang\.db",\s*\n\s*")([0-9A-F]{40})(")')


def main(target):
    src = SRC[target]
    if not src.exists():
        sys.exit('missing snapshot %s' % src)
    data = src.read_bytes()
    ASSET.write_bytes(data)
    digest = hashlib.sha1(data).hexdigest().upper()
    text = SEED.read_text(encoding='utf-8')
    new, n = PIN_RE.subn(lambda m: m.group(1) + digest + m.group(3), text)
    if n != 1:
        sys.exit('Seed.java pin site not found (shape changed?)')
    SEED.write_text(new, encoding='utf-8')
    print('lang table -> %s  %d B  sha1 %s' % (target, len(data), digest))


if len(sys.argv) < 2 or sys.argv[1] not in SRC:
    sys.exit('usage: pkg_lang.py cn|jp')
main(sys.argv[1])
