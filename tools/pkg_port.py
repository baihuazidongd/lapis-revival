#!/usr/bin/env python3
"""Flip the baked asset-server port between the CN and JP builds.

Both packages used to bind 18080/18082/..., so with both installed the second app was answered by
the first one's stub and read the wrong save. The gRPC port the client uses comes from
<pkg>.v2.playerprefs (written by StubProvider, already per-package); the *asset* port is the only
one the client carries in its own data, and it lives in exactly one 4.5 KB Unity serialised file as
`http://127.0.0.1:18080/`. Other files that appear to contain "18080" are hash digests and
GoodsIds (1180801...), so this script refuses to touch a hit that is not preceded by "127.0.0.1:".

Canonicalise-then-apply, so it is idempotent in either direction and restores byte for byte.

    python pkg_port.py cn|jp [--check]
"""
import pathlib
import sys

ASSET = pathlib.Path('C:/lapisbuild/game_decoded/assets/bin/Data/9bdd7e35b810546fdbe3f8fa3ec1fd55')
CN = b'18080'
JP = b'18090'
GUARD = b'127.0.0.1:'


def apply(target):
    data = ASSET.read_bytes()
    for port in (CN, JP):
        for i, off in enumerate(_hits(data, port)):
            if data[max(0, off - len(GUARD)):off] != GUARD:
                sys.exit('refusing: hit at %d is not an asset URL (%r)'
                         % (off, data[max(0, off - 20):off + 8]))
    data = data.replace(JP, CN)                      # canonicalise
    if target == 'jp':
        data = data.replace(CN, JP)
    if '--check' in sys.argv:
        print('already %s' % target if ASSET.read_bytes() == data else 'DRIFTS')
        return
    ASSET.write_bytes(data)
    print('port -> %s (%d sites)' % (target, len(_hits(data, CN if target == 'cn' else JP))))


def _hits(data, needle):
    out, i = [], 0
    while True:
        i = data.find(needle, i)
        if i < 0:
            return out
        out.append(i)
        i += len(needle)


if len(sys.argv) < 2 or sys.argv[1] not in ('cn', 'jp'):
    sys.exit('usage: pkg_port.py cn|jp [--check]')
apply(sys.argv[1])
