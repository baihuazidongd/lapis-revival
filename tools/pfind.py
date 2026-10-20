import sys, io
sys.path.insert(0, r'E:\lapis\work\handoff_lua')
sys.path.insert(0, r'C:\lapisbuild\ljd-lapis-relight-main')
import decrypt_lua as DL, ljd.tools as T, ljd.rawdump.parser as RP, UnityPy
T.set_luajit_version(21)

bundle, needle, line = sys.argv[1], sys.argv[2], int(sys.argv[3])
env = UnityPy.load(bundle)
raw = None
for o in env.objects:
    if o.type.name != 'TextAsset':
        continue
    d = o.read()
    r = d.m_Script
    if isinstance(r, str):
        r = r.encode('utf-8', 'surrogateescape')
    if 'pageshop' in str(d.m_Name).lower():
        raw = r
        print('asset', d.m_Name, len(r))
plain, _, _ = DL.decrypt(raw)
h, proto = RP.parse(io.BytesIO(plain))

def consts(p):
    return list(getattr(p.constants, 'complex_constants', []) or [])

seen = 0
def walk(p, depth=0, parent=None):
    global seen
    seen += 1
    m = [v for v in p.debuginfo.addr_to_line_map if v]
    lo, hi = (min(m), max(m)) if m else (0, 0)
    own = [c for c in consts(p) if isinstance(c, str)]
    if needle in own or (m and abs(hi - line) < 400 and needle in ' '.join(own)):
        pass
    if needle in ' | '.join(own):
        print('%sproto depth%d lines %d..%d instrs %d  HAS-NEEDLE  parent_lines=%s' % (' ' * depth, depth, lo, hi, len(p.instructions), (parent if parent else '-')))
        print('    strings: %s' % own[:14])
        if lo <= line <= hi:
            print('    *** and covers runtime line %d ***' % line)
            for addr, ln in enumerate(p.debuginfo.addr_to_line_map):
                if ln and abs(ln - line) <= 4 and addr < len(p.instructions):
                    print('      line %-5d %-12s %s' % (ln, p.instructions[addr].name, p.instructions[addr].description))
    for c in consts(p):
        if hasattr(c, 'instructions') and hasattr(c, 'debuginfo'):
            walk(c, depth + 1, '%d..%d' % (lo, hi))

walk(proto)
print('protos walked', seen)
