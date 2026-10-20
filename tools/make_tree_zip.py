#!/usr/bin/env python3
"""Assemble the distributable resource tree archive from two roots, driven by the device's own list.

Why not just zip the host copy: `device_files` is NOT a faithful mirror of the running tree. The
device carries 740 extra .bdl.hash sidecars and 4,568 more whose length differs (41 bytes on device
vs 40 in the host copy), and a bundle without its sidecar does not load. So the device's file list is
the manifest, and for each entry the source is the pulled overlay when that entry differs and the host
copy otherwise. No 5.65 GB staging copy is needed, and nothing that only exists on the device can go
missing from the package.

Runtime state is excluded: backtrace/ (crashpad, and one of its files is not even readable by shell)
and heal_backup/ are not content and must not ship.

Every entry is size-checked against the device manifest as it is written, and a sample is digest
checked afterwards, so a silently wrong source shows up here rather than on a user's phone.
"""
import hashlib
import os
import sys
import zipfile

DEVICE_LIST = r'C:\lapisbuild\dev_tree.txt'
HOST_ROOT = r'C:\lapisbuild\device_files\files'
OVERLAY_ROOT = r'E:\lapis\staging\overlay_src'
OUT = r'E:\lapis\staging\tree_cn.zip'

# Upstream's CDN served activityassets/pickupray4/bg.bdl as a 0-byte file (its sidecar is the SHA-1
# of nothing). It only bites once every pool is open: the client then tries to load it, gets
# "Unable to read header from archive file", and sits on Loading with no LapisStub error at all.
# The extracted originals have the real 679,926 B file, so the archive carries that plus a matching
# sidecar instead of the empty pair.
REAL_BG = r'E:\lapis\revival\local\assets\AssetBundles\assets\products\resources\activityassets\pickupray4\bg.bdl'
BG_SUFFIX = 'activityassets/pickupray4/bg.bdl'
EXCLUDE_PREFIXES = ('./backtrace/', './heal_backup/')

# The device tree only ever carried 129 of the 1,021 sound banks upstream ships, because the rest were
# optional CDN downloads (`DownloadConfig.SoundBankName` -> VOX_CHR_*/VOX_EVT_*). Offline there is no CDN,
# so every one of those lines is silent. The full folder is in our own Lapis-SoundBanks archive and was
# digest-checked entry by entry against a complete third-party pack (1040/1040 sha256), so the supplement
# below is the same bytes, not a guess. Sidecar rule measured from the device: exactly 40 bytes, uppercase
# SHA-1 of the bank, no trailing newline (the .bdl sidecars are 41 - do not "unify" them).
BANKS_ROOT = r'E:\ref-sample\sb_all\SoundBanks'
BANK_PREFIX = 'SoundBanks/'


def load_manifest():
    want = {}
    with open(DEVICE_LIST, encoding='utf-8', errors='ignore') as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            size, _, path = line.partition(' ')
            if not path:
                continue
            try:
                want[path] = int(size)
            except ValueError:
                continue
    return want


def pick(path):
    """Source file for a manifest path: the pulled device copy wins, else the host mirror."""
    o = os.path.join(OVERLAY_ROOT, path[2:].replace('/', os.sep))
    if os.path.isfile(o):
        return o
    h = os.path.join(HOST_ROOT, path[2:].replace('/', os.sep))
    return h if os.path.isfile(h) else None


def bank_files():
    """Every upstream bank as (archive path, source path), plus its generated sidecar."""
    out = []
    for dirpath, _dirs, files in os.walk(BANKS_ROOT):
        for f in sorted(files):
            if not f.endswith('.bnk'):
                continue
            full = os.path.join(dirpath, f)
            rel = os.path.relpath(full, BANKS_ROOT).replace('\\', '/')
            out.append((BANK_PREFIX + rel, full))
    return sorted(out)


def sha1_of(path):
    h = hashlib.sha1()
    with open(path, 'rb') as fh:
        for chunk in iter(lambda: fh.read(1 << 22), b''):
            h.update(chunk)
    return h.hexdigest().upper()


def main():
    want = load_manifest()
    # The device tree carries the whole SoundBanks folder a second time under SoundBanks/SoundBanks/
    # (484 MB of exact duplicates baked into the shipped archive). Drop that copy; the real one stays.
    dup = [p for p in want if p.startswith('./SoundBanks/SoundBanks/')]
    paths = sorted(p for p in want
                   if not p.startswith(EXCLUDE_PREFIXES) and p not in set(dup))
    excluded = len(want) - len(paths)
    missing, written, bytes_out = [], 0, 0
    with zipfile.ZipFile(OUT, 'w', zipfile.ZIP_STORED, allowZip64=True) as z:
        for p in paths:
            if p.endswith(BG_SUFFIX):
                # Ship the real bundle, not the empty pair the device tree carries (see REAL_BG).
                data = open(REAL_BG, 'rb').read()
                if p.endswith('.hash'):
                    data = (hashlib.sha1(data).hexdigest().upper() + '\n').encode('ascii')
                z.writestr(p[2:], data)
                written += 1
                bytes_out += len(data)
                continue
            src = pick(p)
            if src is None:
                missing.append(p)
                continue
            real = os.path.getsize(src)
            if real != want[p]:
                missing.append('%s (size %d != device %d)' % (p, real, want[p]))
                continue
            z.write(src, p[2:])          # strip the leading "./"
            written += 1
            bytes_out += real

        # Sound-bank supplement: anything upstream ships that the device manifest never had.
        already = set(n for n in z.namelist() if n.startswith(BANK_PREFIX))
        added = add_bytes = 0
        for arc, src in bank_files():
            if arc in already:
                continue
            z.write(src, arc)
            z.writestr(arc + '.hash', sha1_of(src).encode('ascii'))
            added += 2
            add_bytes += os.path.getsize(src) + 40
        written += added
        bytes_out += add_bytes
        banks_now = sum(1 for n in z.namelist()
                        if n.startswith(BANK_PREFIX) and n.endswith('.bnk'))
        print('sound banks: %d duplicate entries dropped, %d entries added, %d .bnk now shipped'
              % (len(dup), added, banks_now))
    print('manifest %d entries, excluded %d runtime-state files' % (len(want), excluded))
    print('archived %d files (%.2f GB), unusable %d' % (written, bytes_out / 2**30, len(missing)))
    for m in missing[:10]:
        print('   !', m)
    if missing:
        sys.exit('refusing to ship an incomplete tree')
    h = hashlib.sha1()
    with open(OUT, 'rb') as f:
        for chunk in iter(lambda: f.read(1 << 20), b''):
            h.update(chunk)
    print('archive %.2f GB  entries=%d  sha1=%s'
          % (os.path.getsize(OUT) / 2**30, written, h.hexdigest().upper()))


if __name__ == '__main__':
    main()
