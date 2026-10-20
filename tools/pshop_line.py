"""Map a runtime LuaException line number onto the statement that raised it.

ljd's rawdump keeps a per-instruction line table, and the string constants of a function are the
literal paths it passes to GetChildGameObject, so dumping the window around the reported line turns
"PageShop.lua:555" into an actual statement instead of a guess fitted to a decompiled file whose
numbering is not the runtime's.
"""
import sys, io
sys.path.insert(0, r'E:\lapis\work\handoff_lua')
sys.path.insert(0, r'C:\lapisbuild\ljd-lapis-relight-main')
import decrypt_lua as DL
import ljd.tools as T
import ljd.rawdump.parser as RP
import UnityPy

T.set_luajit_version(21)
BUNDLE = sys.argv[1]
WANT = [int(x) for x in sys.argv[2:]] or [555]


def load(bundle):
    env = UnityPy.load(bundle)
    for o in env.objects:
        if o.type.name != 'TextAsset':
            continue
        d = o.read()
        raw = d.m_Script
        if isinstance(raw, str):
            raw = raw.encode('utf-8', 'surrogateescape')
        if raw[:4] != b'\x1bLJ':
            plain, _, _ = DL.decrypt(raw)
        else:
            plain = raw
        header, proto = RP.parse(io.BytesIO(plain))
        return proto
    sys.exit('no TextAsset in %s' % bundle)


def consts(p):
    return list(getattr(p.constants, 'complex_constants', []) or [])


def subs(p):
    out = []
    for c in consts(p):
        if hasattr(c, 'instructions') and hasattr(c, 'debuginfo'):
            out.append(c)
            out.extend(subs(c))
    return out


def name_of(p):
    """The function's own name is the first string constant of its parent that is not a path."""
    return [c for c in consts(p) if isinstance(c, str)][:12]


proto = load(BUNDLE)
allp = [proto] + subs(proto)
print('total protos', len(allp))
for p in allp:
    m = p.debuginfo.addr_to_line_map
    vals = [v for v in m if v]
    if not vals:
        continue
    lo, hi = min(vals), max(vals)
    hits = [w for w in WANT if lo <= w <= hi]
    if not hits:
        continue
    print('=== proto lines %d..%d  contains %s  instrs %d' % (lo, hi, hits, len(p.instructions)))
    print('    strings: %s' % name_of(p))
    for w in hits:
        print('    --- window around line %d ---' % w)
        for addr, line in enumerate(m):
            if line and abs(line - w) <= 5 and addr < len(p.instructions):
                ins = p.instructions[addr]
                print('      line %-5d %-14s %s' % (line, ins.name, ins.description))
