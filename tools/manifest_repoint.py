#!/usr/bin/env python3
"""Re-point one manifest entry at a replacement bundle: 40-char ASCII sha1 swap plus the
int64/int32 size that sits in the 260-byte window before the hash. Same surgery
patch_manifest_luadata.py used, generalised so every bundle swap has one route.

    python manifest_repoint.py <manifest.xml> <old_sha1> <old_size> <new_sha1> <new_size> [out.xml]

Manifests are AES-CBC'd gzip (key in revival/local/keys/resource-crypto.json). The game verifies
each .bdl against the Hash here before it will load it, so a bundle pushed without touching this
dies at require() with 'MD5 VERIFY FAILED'.
"""
import gzip
import io
import json
import struct
import sys
from pathlib import Path

from Crypto.Cipher import AES
from Crypto.Util.Padding import pad, unpad

KEYS = Path(r'E:/lapis/revival/local/keys/resource-crypto.json')


def open_manifest(p):
    k = json.load(open(KEYS, encoding='utf-8'))
    key, iv = bytes.fromhex(k['key_hex']), bytes.fromhex(k['iv_hex'])
    aes = AES.new(key, AES.MODE_CBC, iv)
    return aes, gzip.GzipFile(fileobj=io.BytesIO(unpad(aes.decrypt(Path(p).read_bytes()), 16))).read()


def repoint(path, old_hash, old_size, new_hash, new_size, out=None):
    assert len(old_hash) == 40 and len(new_hash) == 40, 'hashes must be 40-char uppercase sha1'
    aes, nrbf = open_manifest(path)
    d = bytearray(nrbf)
    hits = []
    start = 0
    while True:
        i = d.find(old_hash.encode(), start)
        if i < 0:
            break
        hits.append(i)
        start = i + 40
    if not hits:
        raise SystemExit('%s not present in %s (decrypted %d B) -- stale manifest or wrong hash'
                         % (old_hash, path, len(nrbf)))
    for i in hits:
        win = bytes(d[max(0, i - 260):i])
        j, w = win.rfind(struct.pack('<q', old_size)), 8
        if j < 0:
            j, w = win.rfind(struct.pack('<i', old_size)), 4
        if j < 0:
            raise SystemExit('size %d not found in the window before hash at %d' % (old_size, i))
        base = max(0, i - 260)
        d[i:i + 40] = new_hash.encode()
        d[base + j:base + j + w] = struct.pack('<q' if w == 8 else '<i', new_size)
        print('entry at %d: hash swapped, size at %d (w=%d)' % (i, base + j, w))

    key, iv = (bytes.fromhex(json.load(open(KEYS, encoding='utf-8'))[n])
               for n in ('key_hex', 'iv_hex'))
    blob = AES.new(key, AES.MODE_CBC, iv).encrypt(pad(gzip.compress(bytes(d), mtime=0), 16))
    dest = Path(out or path)
    dest.write_bytes(blob)

    _, back = open_manifest(dest)
    assert back.find(new_hash.encode()) >= 0 and back.count(old_hash.encode()) == 0
    print('%s: %d entries repointed, %d B -> %s' % (Path(path).name, len(hits), len(blob), dest))
    return len(hits)


if __name__ == '__main__':
    a = sys.argv
    repoint(a[1], a[2].upper(), int(a[3]), a[4].upper(), int(a[5]), a[6] if len(a) > 6 else None)
