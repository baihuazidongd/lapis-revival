import sys, io
sys.path.insert(0, r'E:\lapis\work\handoff_lua')
sys.path.insert(0, r'C:\lapisbuild\ljd-lapis-relight-main')
import decrypt_lua as DL, ljd.tools as T, ljd.rawdump.parser as RP, UnityPy
T.set_luajit_version(21)
bundle = sys.argv[1]
lo, hi = int(sys.argv[2]), int(sys.argv[3])
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
plain, _, _ = DL.decrypt(raw)
h, proto = RP.parse(io.BytesIO(plain))

def consts(p):
    return list(getattr(p.constants, 'complex_constants', []) or [])

def walk(p):
    yield p
    for c in consts(p):
        if hasattr(c, 'instructions') and hasattr(c, 'debuginfo'):
            for r in walk(c):
                yield r

for p in walk(proto):
    m = [v for v in p.debuginfo.addr_to_line_map if v]
    if not m or min(m) != lo or max(m) != hi:
        continue
    cs = consts(p)
    def lit(idx):
        try:
            v = cs[idx]
        except Exception:
            return '?'
        return v if isinstance(v, str) else ('<proto>' if hasattr(v, 'instructions') else str(v))
    cur = None
    out = []
    for addr, ins in enumerate(p.instructions):
        ln = p.debuginfo.addr_to_line_map[addr]
        w = getattr(ins, 'Bytecode', 0)
        CD = w >> 16
        if ins.name in ('KSTR', 'GGET', 'KSHORT', 'TGETS', 'TSETS', 'CALL', 'ISF', 'ITERL', 'ILOOP'):
            if ins.name == 'KSTR':
                out.append((ln, 'KSTR %r' % lit(CD)))
            elif ins.name == 'GGET':
                out.append((ln, 'GGET %r' % lit(CD)))
            elif ins.name == 'KSHORT':
                out.append((ln, 'KSHORT %d' % (CD - 32768)))
            else:
                out.append((ln, ins.name))
    last = None
    for ln, txt in out:
        if ln != last:
            print('--- line %d' % ln)
            last = ln
        print('    ', txt)
