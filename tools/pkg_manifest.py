#!/usr/bin/env python3
"""Flip game_decoded/AndroidManifest.xml between the CN and JP application ids.

Two builds come out of one decoded tree. Only the application identity differs, and exactly five
attribute values carry it -- the root `package`, the two provider authorities (Android refuses the
second install outright if both apps claim one authority), the C2D_MESSAGE permission name, and the
deep-link scheme. Component class names like `com.klab.lapis.stub.StubProvider` and the
`com.klab.lapis.v2.playerprefs` file name are deliberately untouched: the first is a Java type the
dex resolves by name, the second is a string the game's own managed code reads back, and renaming
either loses the save rather than isolating it.

The rewrite is canonicalise-then-apply, so running it twice with the same target is a no-op and
either direction restores the other byte for byte.

    python pkg_manifest.py cn|jp [--check]
"""
import pathlib
import sys

MAN = pathlib.Path('C:/lapisbuild/game_decoded/AndroidManifest.xml')
CN = 'com.klab.lapis'
JP = 'com.klab.lapis.jp'

# (cn form, jp form) -- matched whole, never as a bare prefix
SITES = [
    ('package="%s"' % CN, 'package="%s"' % JP),
    ('android:authorities="%s.stubinit"' % CN, 'android:authorities="%s.stubinit"' % JP),
    ('android:authorities="%s.firebaseinitprovider"' % CN,
     'android:authorities="%s.firebaseinitprovider"' % JP),
    ('android:name="%s.permission.C2D_MESSAGE"' % CN, 'android:name="%s.permission.C2D_MESSAGE"' % JP),
    ('android:scheme="%s"' % CN, 'android:scheme="%s"' % JP),
]


def apply(target):
    text = MAN.read_text(encoding='utf-8')
    for cn, jp in SITES:
        text = text.replace(jp, cn)          # canonicalise first: makes this idempotent both ways
    if target == 'jp':
        for cn, jp in SITES:
            text = text.replace(cn, jp)
    if '--check' in sys.argv:
        print('already %s' % target if MAN.read_text(encoding='utf-8') == text else 'DRIFTS')
        return
    MAN.write_text(text, encoding='utf-8')
    hits = sum(text.count(jp) for _, jp in SITES) if target == 'jp' else sum(text.count(cn) for cn, _ in SITES)
    print('manifest -> %s (%d sites)' % (target, hits))


if len(sys.argv) < 2 or sys.argv[1] not in ('cn', 'jp'):
    sys.exit('usage: pkg_manifest.py cn|jp [--check]')
apply(sys.argv[1])
