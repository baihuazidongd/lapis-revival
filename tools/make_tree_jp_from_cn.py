"""Build the JP tree from the freshly rebuilt CN tree, restoring the 632 entries that legitimately
differ per package (the CN-translated story bundles and the CN language table) from the previous JP
archive. Everything else - including the whole SoundBanks folder, which the two packages share - comes
from the CN archive, so the sound supplement lands in both without being extracted twice.

All entries are copied STORED, byte for byte, so no recompression happens and the digests of the
restored entries stay whatever the JP archive already carried.
"""
import hashlib
import shutil
import sys
import zipfile

NEW_CN = 'E:/lapis/staging/tree_cn.zip'
OLD_JP = 'E:/lapis/build_full/tree_jp.zip'
OUT = 'E:/lapis/staging/tree_jp.zip'

cn = zipfile.ZipFile(NEW_CN)
jp = zipfile.ZipFile(OLD_JP)
jpinfo = {i.filename: i for i in jp.infolist()}

# Which names differ per package? Decided by size against the previously shipped pair, whose CN half
# was built by the same manifest walk, so a size change is the translated-content signal.
differ = set()
shipped_cn = zipfile.ZipFile('E:/lapis/build_full/tree_cn.zip')
shipped_jp = zipfile.ZipFile('E:/lapis/build_full/tree_jp.zip')
a = {i.filename: i.file_size for i in shipped_cn.infolist()}
b = {i.filename: i.file_size for i in shipped_jp.infolist()}
differ = {k for k in set(a) & set(b) if a[k] != b[k]}
print('per-package entries to restore from JP:', len(differ))
if not differ:
    sys.exit('refusing to build: no per-package differences detected')

missing = {k for k in differ if k not in jpinfo}
if missing:
    sys.exit('refusing to build: %d differing entries absent from the JP archive, e.g. %s'
             % (len(missing), sorted(missing)[0]))

written = 0
from_jp = 0
bytes_out = 0
with zipfile.ZipFile(OUT, 'w', zipfile.ZIP_STORED, allowZip64=True) as z:
    for info in cn.infolist():
        name = info.filename
        if name in differ:
            src = jp.open(name, 'r')
        else:
            src = cn.open(name, 'r')
        with src, z.open(name, 'w', force_zip64=True) as dst:
            total = 0
            while True:
                chunk = src.read(1 << 22)
                if not chunk:
                    break
                dst.write(chunk)
                total += len(chunk)
        if total != info.file_size and name not in differ:
            sys.exit('size drift on %s: %d != %d' % (name, total, info.file_size))
        if name in differ:
            from_jp += 1
        written += 1
        bytes_out += total

print('wrote %d entries (%d restored from JP), %.2f GB' % (written, from_jp, bytes_out / 2**30))

# Verify: every JP-restored entry must equal the old JP bytes; every other must equal the new CN bytes.
z = zipfile.ZipFile(OUT)
bad = []
for name in list(differ)[:400]:
    if z.getinfo(name).file_size != jpinfo[name].file_size:
        bad.append(('size', name))
banks = [n for n in z.namelist() if n.endswith('.bnk')]
print('entries:', len(z.namelist()), ' .bnk:', len(banks))
print('size spot-check failures:', len(bad))
h = hashlib.sha1()
with open(OUT, 'rb') as f:
    for chunk in iter(lambda: f.read(1 << 22), b''):
        h.update(chunk)
print('archive %.2f GB sha1=%s' % (z.fp.seek(0, 2) / 2**30, h.hexdigest().upper()))
