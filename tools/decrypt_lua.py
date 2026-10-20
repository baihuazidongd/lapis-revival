#!/usr/bin/env python3
"""Recover Lapis Lua assets; keep original proprietary and standard LuaJIT dumps."""
import argparse
import hashlib
import json
from pathlib import Path


def uleb(data, pos):
    value = shift = 0
    while True:
        byte = data[pos]
        pos += 1
        value |= (byte & 127) << shift
        if byte < 128:
            return value, pos
        shift += 7
        if shift > 35:
            raise ValueError('Invalid ULEB128')


def normalize(data):
    """Undo PO/0x82 header, moved upvalues and permuted opcodes, preserving sizes."""
    if data[:4] != b'\x1bPO\x82':
        raise ValueError('Not a Lapis bytecode dump')
    out = bytearray(data)
    out[:4] = b'\x1bLJ\x02'
    flags, pos = uleb(data, 4)
    if flags & 1:
        raise ValueError('Big endian not supported')
    if not flags & 2:
        length, pos = uleb(data, pos)
        pos += length
    count = 0
    while True:
        size, pos = uleb(data, pos)
        if not size:
            if pos != len(data):
                raise ValueError('Trailing data after prototype terminator')
            return bytes(out), count
        end = pos + size
        if end > len(data):
            raise ValueError('Truncated prototype')
        uv_count = data[pos + 3]
        cur = pos + 4
        _, cur = uleb(data, cur)  # GC constants
        _, cur = uleb(data, cur)  # numeric constants
        bc_count, cur = uleb(data, cur)
        if not flags & 2:
            debug_size, cur = uleb(data, cur)
            if debug_size:
                _, cur = uleb(data, cur)
                _, cur = uleb(data, cur)
        uv_end = cur + 2 * uv_count
        bc_end = uv_end + 4 * bc_count
        if bc_end > end:
            raise ValueError('Instruction block exceeds prototype')
        instructions = bytearray(data[uv_end:bc_end])
        for i in range(0, len(instructions), 4):
            opcode = instructions[i]
            if opcode > 0x60:
                raise ValueError(f'Unknown opcode {opcode:#x}')
            if 4 <= opcode <= 7:
                instructions[i] = opcode + 14
            elif 8 <= opcode <= 21:
                instructions[i] = opcode - 4
        out[cur:bc_end] = instructions + data[cur:uv_end]
        count += 1
        pos = end


def decrypt(blob):
    if len(blob) < 58:
        raise ValueError('Truncated asset')
    encrypted = blob[20:-32]
    if hashlib.sha1(encrypted).digest() != blob[:20]:
        raise ValueError('SHA1 prefix mismatch')
    tail = blob[-32:].decode('ascii')
    if len(tail) != 32 or any(c not in '0123456789abcdefABCDEF' for c in tail):
        raise ValueError('Invalid digest trailer')
    plain = bytes(x ^ ((0xABCDEF >> ((i % 1543) % 5)) & 255)
                  for i, x in enumerate(encrypted))
    standard, prototypes = normalize(plain)
    return plain, standard, prototypes


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('directory', nargs='?', type=Path, default=Path(__file__).parent)
    args = parser.parse_args()
    root = args.directory
    for name in ('decrypted', 'decrypted_lapis'):
        (root / name).mkdir(exist_ok=True)
    report = []
    files = sorted(root.glob('lua_*.lua.lua'))
    if not files:
        raise SystemExit('No input assets found')
    for path in files:
        blob = path.read_bytes()
        plain, standard, prototypes = decrypt(blob)
        (root / 'decrypted_lapis' / path.name).write_bytes(plain)
        (root / 'decrypted' / path.name).write_bytes(standard)
        tail = blob[-32:].decode('ascii').lower()
        report.append(dict(file=path.name, sha1_prefix_verified=True,
                           input_sha256=hashlib.sha256(blob).hexdigest(),
                           plain_sha256=hashlib.sha256(plain).hexdigest(),
                           standard_sha256=hashlib.sha256(standard).hexdigest(),
                           bytes=len(plain), prototypes=prototypes, trailer=tail,
                           md5_plain=hashlib.md5(plain).hexdigest(),
                           md5_standard=hashlib.md5(standard).hexdigest(),
                           md5_match=tail in (hashlib.md5(plain).hexdigest(),
                                             hashlib.md5(standard).hexdigest())))
    (root / 'decryption_report.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(f'Recovered {len(report)} files; SHA1 verified for all; '
          f'MD5 matches: {sum(r["md5_match"] for r in report)}')


if __name__ == '__main__':
    main()
