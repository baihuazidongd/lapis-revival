import sys, io
sys.path.insert(0, r'E:\lapis\work\handoff_lua'); sys.path.insert(0, r'C:\lapisbuild\ljd-lapis-relight-main')
import decrypt_lua as DL, ljd.tools as T, ljd.rawdump.parser as RP, UnityPy
T.set_luajit_version(21)
env = UnityPy.load('device_files/files/JP/AssetBundles/assets/products/resources/luajit64/ui/page/pageshop.bdl')
raw = [o.read().m_Script for o in env.objects if o.type.name == 'TextAsset' and str(o.read().m_Name) == 'PageShop.lua'][0]
if isinstance(raw, str): raw = raw.encode('utf-8', 'surrogateescape')
plain, _, _ = DL.decrypt(raw)
h, proto = RP.parse(io.BytesIO(plain))
def consts(p): return list(getattr(p.constants, 'complex_constants', []) or [])
def walk(p):
    yield p
    for c in consts(p):
        if hasattr(c, 'instructions') and hasattr(c, 'debuginfo'):
            for r in walk(c): yield r
TARGETS = {'SafeArea/Main/ScrollArea', 'SafeArea/Main/ScrollAreaList', 'SafeArea/Main/DlgMonth', 'UIPrefabPath'}
for p in walk(proto):
    m = [v for v in p.debuginfo.addr_to_line_map if v]
    if not m or not (100 < min(m) < 300 and max(m) > 420):
        continue
    cs = consts(p)
    want = {i for i, c in enumerate(cs) if isinstance(c, str) and c in TARGETS}
    print('OnEnter proto lines %d..%d instrs %d  target slots %s' % (min(m), max(m), len(p.instructions), sorted(want)))
    for addr, ins in enumerate(p.instructions):
        w = getattr(ins, 'Bytecode', 0)
        CD = (w >> 16) & 0xFFFF
        for cand, how in ((CD - 32768, 'K16'), (CD, 'CD')):
            if cand in want and 0 <= cand < len(cs):
                print('   line %-5d instr %-4d %-8s %-4s -> %r' % (p.debuginfo.addr_to_line_map[addr], addr, ins.name, how, cs[cand]))
    break
