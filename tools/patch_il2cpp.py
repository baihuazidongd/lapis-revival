"""Apply the documented client-side code patches straight into the repackaged libil2cpp.so.

The reference revival setup writes these into live process memory over adb; a file patch here is
both permanent and adb-free, which is what the standalone-APK goal needs. Sites, original bytes and
replacement bytes are copied verbatim from revival/client/profiles/lapis-1.5.0-arm64.json, which is
keyed to an elf_sha256 of the unpatched build -- the point of checking that hash is that a different
client build must refuse to be patched rather than corrupt a function we have not identified.
Because this script rewrites the file in place, the gate is applied to a reconstructed pre-image:
every site is put back to its original byte first, so the check still says "this is exactly the
1.5.0 build the profile was measured against" on the second and nth run.

Only bootstrap-identity is enabled: PublicEncrypt is what turns the 32-byte session pad into the
128-byte RSA mask the server cannot invert. The SQLite sites are solved on our side by the klb_vfs
hooks in patch_klbhooks.py.
"""
import hashlib
import json
import struct
from pathlib import Path

REVIVAL_PROFILE = Path('E:/\u5b9d\u77f3\u5e7b\u60f3/revival/client/profiles/lapis-1.5.0-arm64.json')
TARGET = Path('C:/lapisbuild/game_decoded/lib/arm64-v8a/libil2cpp.so')
ENABLED = {'bootstrap-identity'}


def file_offset_for_rva(data, rva):
    """RVA and file offset diverge past the first LOAD segment; only the mapping says which."""
    e_phoff, = struct.unpack_from('<Q', data, 0x20)
    e_phnum, = struct.unpack_from('<H', data, 0x38)
    for i in range(e_phnum):
        p_type, p_flags, p_offset, p_vaddr, _, p_filesz, _, _ = struct.unpack_from(
            '<IIQQQQII', data, e_phoff + i * 56)
        if p_type == 1 and p_flags & 1 and p_vaddr <= rva < p_vaddr + p_filesz:
            return p_offset + (rva - p_vaddr)
    raise SystemExit('RVA 0x%x is not inside an executable LOAD segment' % rva)


def main():
    profile = json.loads(REVIVAL_PROFILE.read_text(encoding='utf-8'))
    data = bytearray(TARGET.read_bytes())
    sites = []
    for entry in profile['code_patches']:
        original = bytes.fromhex(entry['original'])
        replacement = bytes.fromhex(entry['replacement'])
        off = file_offset_for_rva(data, int(entry['rva'], 16))
        current = bytes(data[off:off + len(original)])
        if current == original:
            pass
        elif current == replacement:
            data[off:off + len(original)] = original
            print('[pre] %s is already patched, un-applying it to check the build' % entry['name'])
        else:
            raise SystemExit('site %s @0x%x holds %s, neither the profile original %s nor its '
                             'replacement %s -- wrong or unknown build'
                             % (entry['name'], off, current.hex(), original.hex(), replacement.hex()))
        sites.append((entry, off, original, replacement))

    preimage = hashlib.sha256(bytes(data)).hexdigest()
    if preimage != profile['elf_sha256']:
        raise SystemExit('refusing to patch: pre-image sha256 %s != profile %s' % (preimage, profile['elf_sha256']))
    print('[OK] pre-image matches lapis-1.5.0 (%s)' % preimage[:16])

    changed = 0
    for entry, off, original, replacement in sites:
        if entry['name'] not in ENABLED:
            continue
        data[off:off + len(replacement)] = replacement
        changed += 1
        print('[write] %s @0x%x %s -> %s' % (entry['name'], off, original.hex(), replacement.hex()))

    if changed != len(ENABLED):
        raise SystemExit('enabled patch names not all found in the profile: %s' % sorted(ENABLED))
    TARGET.write_bytes(bytes(data))
    print('[OK] %s now %d bytes, sha256=%s' % (TARGET.name, len(data),
                                               hashlib.sha256(bytes(data)).hexdigest()[:16]))


if __name__ == '__main__':
    main()
