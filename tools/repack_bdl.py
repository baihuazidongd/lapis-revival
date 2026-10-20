"""Re-pack a Unity AssetBundle (.bdl) by replacing TextAsset payloads.

luajit bundles wrap each chunk as: sha1(enc)[:20] + enc + md5(plain) as 32 hex ascii,
where enc = plain XOR (0xABCDEF >> ((i % 1543) % 5)) & 0xFF. The transform is its own
inverse, so `wrap` is `decrypt`'s mirror and the payload may be bytecode or source.
"""
import argparse
import hashlib
import pathlib
import sys

import UnityPy

sys.path.insert(0, r'E:\lapis\work\handoff_lua')
import decrypt_lua as DL


def xor(data):
    return bytes(x ^ ((0xABCDEF >> ((i % 1543) % 5)) & 255) for i, x in enumerate(data))


def wrap(plain, trailer=None):
    """trailer defaults to md5(plain); real assets carry a build-time value of
    unknown derivation, so patch() passes the original through instead."""
    enc = xor(plain)
    return hashlib.sha1(enc).digest() + enc + (trailer or hashlib.md5(plain).hexdigest()).encode('ascii')


def unwrap(blob):
    """decrypt_lua.decrypt minus normalize(), so plaintext source verifies too."""
    if len(blob) < 58:
        raise ValueError('truncated asset')
    enc = blob[20:-32]
    if hashlib.sha1(enc).digest() != blob[:20]:
        raise ValueError('SHA1 prefix mismatch')
    tail = blob[-32:].decode('ascii')
    if any(c not in '0123456789abcdefABCDEF' for c in tail):
        raise ValueError('invalid digest trailer')
    return xor(enc)


def patch(src_bdl, out_bdl, files, verify=True, packer='original', trailer='original'):
    """trailer: 'original' carries the build-time value through, 'md5' hashes the new
    plaintext (the loader's MD5 VERIFY check), 'md5l'/'md5u' pick the hex case."""
    env = UnityPy.load(str(src_bdl))
    replaced = []
    for obj in env.objects:
        if obj.type.name != 'TextAsset':
            continue
        d = obj.read()
        name = d.m_Name
        if name not in files:
            continue
        original = d.m_Script if isinstance(d.m_Script, bytes) else d.m_Script.encode('utf-8', 'surrogateescape')
        plain = files[name]
        if trailer == 'original':
            tail = original[-32:].decode('ascii')
        else:
            h = hashlib.md5(plain).hexdigest()
            tail = h.upper() if trailer == 'md5u' else h
        blob = wrap(plain, tail)
        if verify:
            assert unwrap(blob) == plain, 'round-trip failed for ' + name
        d.m_Script = blob.decode('utf-8', 'surrogateescape')
        d.save()
        replaced.append((name, len(plain), len(blob)))
    if len(replaced) != len(files):
        raise SystemExit('missing targets, replaced=%s wanted=%s' % (replaced, list(files)))
    pathlib.Path(out_bdl).write_bytes(env.file.save(packer))
    for name, n, m in replaced:
        print('  replaced %-24s plain=%-8d blob=%d' % (name, n, m))


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('bundle')
    ap.add_argument('out')
    ap.add_argument('--set', nargs=2, action='append', required=True, metavar=('NAME', 'FILE'))
    ap.add_argument('--trailer', default='original', choices=('original', 'md5', 'md5u', 'md5l'))
    args = ap.parse_args()
    files = {}
    for name, path in args.set:
        files[name] = pathlib.Path(path).read_bytes()
    patch(args.bundle, args.out, files, trailer=args.trailer)
    size = pathlib.Path(args.out).stat().st_size
    print('wrote %s (%d bytes) sha1=%s' % (args.out, size,
          hashlib.sha1(pathlib.Path(args.out).read_bytes()).hexdigest().upper()))
