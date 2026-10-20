"""Ship the rebuilt pair (APKs + trees) into build_full and rewrite CHECKSUMS.txt from the bytes that
actually landed. Header lines are preserved verbatim; every digest is streamed, because these archives
are 7 GB and read() would try to hold the whole thing in RAM (it already failed once that way).
"""
import hashlib
import os
import shutil

SRC = {
    'game_relay_cn.apk': 'C:/lapisbuild/game_relay.apk',
    'game_relay_jp.apk': 'C:/lapisbuild/game_relay_jp.apk',
    'tree_cn.zip': 'E:/lapis/staging/tree_cn.zip',
    'tree_jp.zip': 'E:/lapis/staging/tree_jp.zip',
}
DEST = 'E:/lapis/build_full'
CK = os.path.join(DEST, 'CHECKSUMS.txt')


def digest(path):
    h = hashlib.sha1()
    size = 0
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(1 << 22), b''):
            size += len(chunk)
            h.update(chunk)
    return size, h.hexdigest().upper()


raw = open(CK, 'rb').read()
lines = raw.decode('utf-8').splitlines()
head = []
i = 0
while i < len(lines) and lines[i].strip() != '':
    head.append(lines[i])
    i += 1
assert len(head) == 3, head

rows = []
for name, src in sorted(SRC.items()):
    dst = os.path.join(DEST, name + '.new')
    shutil.copyfile(src, dst)
    want = os.path.getsize(src)
    got = os.path.getsize(dst)
    assert want == got, (name, want, got)
    os.replace(dst, os.path.join(DEST, name))
    size, dg = digest(os.path.join(DEST, name))
    assert size == want, (name, size, want)
    rows.append('%s  %d  %s' % (name, size, dg))
    print('%-20s %14s B  %s' % (name, f'{size:,}', dg))

open(CK, 'wb').write(('\n'.join(head) + '\n\n' + '\n'.join(rows) + '\n').encode('utf-8'))
back = open(CK, 'rb').read().decode('utf-8').splitlines()
assert back[:3] == head, 'header drifted'
data = [l for l in back[3:] if l.strip()]
assert len(data) == 4, data
for l in data:
    n, sz, dg = l.split()
    s, d = digest(os.path.join(DEST, n))
    assert s == int(sz) and d == dg, l
print('\nCHECKSUMS.txt re-read and verified:')
print('\n'.join(back))
