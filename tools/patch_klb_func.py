"""Instrument libklbsqlite3.so so the client reports its own SQLite activity.

Four detours share one putstr subroutine that appends NUL-separated records to one of four
candidate klbopen.log paths using raw svc (openat/lseek/write/close):

  DT_INIT (from a freed .dynamic slot)  'INIT' (proves the module is mapped and that
                                              putstr can write, independent of SQLite)
  0x2a690 sqlite3_vfs_register  'REG'  + pVfs->zName   (proves SQLite was initialised,
                                                      and which VFS names exist)
  0x925f0 openDatabase          'OPEN' + filename, 'VFS' + requested vfs
  0x7d8d4 sqlite3Prepare        'SQL'  + zSql
  0x10ecc klb_vfs.xOpen         'VX'   + the raw name (the k0.k1.k2 prefix)

Nothing in the cave calls into libc: the imports' addresses were verified against .dynsym
(the k-th entry lives at .plt + (k+1)*16) and open()/close()/write() through them still
returned -1, so the logger goes to the kernel by itself and reads -errno off the return
register.

sqlite3_step is deliberately not hooked: it is the hot path, and with no writable
storage in this module the only available bound is the log's own size -- which the lines
before it are worth more than.

Why these addresses: sqlite3_open/_open_v2/_open16 all tail-jump into openDatabase@0x925f0
(0x92e90, 0x92e94, and a bl at 0x92f28), and every prepare entry point reaches
sqlite3Prepare@0x7d8d4 (prepare_v2 tail-jumps, prepare16 via a bl at 0x7e230), so one
detour each covers UTF-8 and UTF-16 callers alike. Each body opens with a plain
'stp x29,x30,[sp,#-N]!' frame push: no PC-relative operands, so copying those four
bytes verbatim into the cave is exact.

Space: the exec PT_LOAD ends at p_filesz 0xa1e98 but the next segment starts at
0xa28f8, and that 2656-byte hole is zero, owned by no section, and inside the file.
Extending LOAD1 over it yields mapped R+X room -- verified on device, the cave executes.
Everything the hooks read (code and strings) therefore lives in that one mapping. The
page-aligned slack at the head of the RW segment (vaddr 0xb2000..0xb28f8) turned out to
be mapped read-only by the linker (SEGV_ACCERR writing to bias+0xb2808), so no state can
live there, which is also why putstr caches nothing and bounds itself with lseek.

Every word is re-disassembled with capstone and compared to the fully resolved
intended text, so a wrong field layout aborts the build instead of bricking the game.
"""
import pathlib
import re
import struct
import sys

from capstone import Cs, CS_ARCH_ARM64, CS_MODE_ARM

SO = pathlib.Path('C:/lapisbuild/libklbsqlite3.so')
BAK = pathlib.Path('C:/lapisbuild/libklbsqlite3.so.orig')

EXTEND = '--compact' not in sys.argv

PHDR0 = 0x40                         # program header table
P_FILESZ, P_MEMSZ = 32, 40           # field offsets inside an Elf64_Phdr
LOAD1_FILESZ = 0xa28f8               # extend exec segment over the inter-segment hole
CAVE = 0xa1e98
CODE_LIMIT = LOAD1_FILESZ if EXTEND else 0xa2000
SIZE_CAP = 0x10000                   # stop appending once the log reaches 64 KiB
FRAME = 0x40

H_REG, H_OPEN, H_PREP, H_XOPEN = 0x2a690, 0x925f0, 0x7d8d4, 0x10ecc
# klb xRead's exit block: both the delegate-error branch and the loop's b.le land here, with
# x21=zBuf, x24=iOfst and w25=rc live, and its first word is 'mov w0, w25'.
H_XREAD, XREAD_EXIT_WORD = 0x11090, 0x2A1903E0

# klb_vfs.xOpen ends by overwriting pFile->pMethods with its own io_methods, whose xRead
# XORs every byte with a keystream derived from the k0.k1.k2 filename prefix.  With the store
# NOP'd the connection keeps the real unix methods, so a plaintext database reads verbatim.
# Two racing runs (race.sh, 50ms polls of files/MasterData) pinned the two transforms apart:
# with the NOP on, the installer wrote master_data.db_ = served ^ 96482f2e1a19bd65..; with the
# NOP off and the served file plaintext, the installed file came out plaintext (sha1 648ee8ad)
# and xRead handed the caller 53 51 52 .. 7d .. 0e 46, i.e. plaintext ^ 00001ed209a22e20.  So
# the write-side and read-side keystreams are different streams, neither is the one the
# filename triple predicts, and the only reliable way to get a readable database on disk is to
# measure the write transform (serve zeros, catch what lands) and pre-XOR the real file with it.
PATCH_PLAINTEXT = True
XOPEN_SETMETHODS = 0x10f94
XOPEN_SETMETHODS_WORD = 0xF9000261      # str x1, [x19]
NOP = 0xD503201F

# xOpen parses its own filename as '<k0>.<k1>.<k2> <realpath>' and exits through
# 'mov w0, #1' the moment it sees a character that is neither a digit, a dot, nor the
# separating space.  The triple is handed to it by the installer -- the natural run opened
# master_data.db as "3696171498.883465818.2114258981 /storage/.../master_data.db" -- so a
# database seeded past the installer arrives with a bare path, the parse fails on its very
# first byte ('/'), and SQLite gets an error before it ever reads: zero prepared statements,
# and the loader parks on 更新データを確認しています with the splash cards cycling.
# A bare name already asserts "no key", which is exactly what the store NOP above provides,
# so route that branch into the real-open sequence instead of the error return.
XOPEN_NONDIGIT = 0x10f38
XOPEN_NONDIGIT_WORD = 0x54000361        # b.ne #0x10fa4
XOPEN_REALOPEN = 0x10f44                # ldr x0,[x0,#0x20]; add x1,x1,#1; ... blr x5
# xOpen's single epilogue: both the 'mov w0,#1' parse failures and the real-open fallthrough
# reach it with w0 = the return code live, and x19/x29/x30 are all reloaded from the frame
# after this point, so only w0 has to be preserved across the logger call.
H_XOPEN_EXIT = 0x10fa8

# The measured outcome of the redirect above: XE still reports rc 1 and SQL stays at zero, so
# klb's own real-open sequence is not something a hand-built argument register makes work.  Stop
# paying attention to klb internals and take the request one level up instead: the game calls
# sqlite3_open_v2 with the vfs *name* in x3 (proof: the OPEN record prints the bytes at [x3] and
# they read 'klb_vfs'), so for an unprefixed name hand SQLite the real file-system vfs directly
# and let it read the plaintext database verbatim.  That vfs exists in this module: RELA entry at
# file 0xb2d0 writes 0xa16dd into slot +0x18 of the sqlite3_vfs object at 0xb6d38, and 0xa16dd is
# the first of the registered name family 'unix' / 'unix-none' / 'unix-dotfile' that the unix
# os-layer installs.  0xa16dd is below the cave at 0xa1e98 and inside LOAD0, so it is mapped
# read-only and we never write over it.
VFS_UNIX_NAME = 0xa16dd
# The unix vfs's own xOpen, the +0x28 slot of the vfs object at 0xb6d38 -- the same offset that
# holds 0x10ecc for klb_vfs.  The slot layout is pinned by the code itself: 0x4b9ac is unixOpen
# (it parks x1 in x23 as the path, x2 in x19 as the sqlite3_file and w3 in w20 as the flags) and
# the next slot, +0x38 = 0x1a010, is xAccess (mov x0,x1 then tests w2 for the access type).
# Logging its entry separates the two ways the rewrite can still fail: no FU at all means SQLite
# never resolved the name and bailed with SQLITE_CANTOPEN, an FU with no following SQL means the
# OS-level open itself was refused.
H_UNIX_XOPEN = 0x4b9ac

# Every detour site, applied and printed from this one list.
HOOKS = (('h_reg', H_REG), ('h_open', H_OPEN), ('h_prep', H_PREP), ('h_xopen', H_XOPEN),
         ('h_xread', H_XREAD), ('h_xe', H_XOPEN_EXIT), ('h_fux', H_UNIX_XOPEN))
# A load-time marker, because "the logger cannot write" and "nothing called SQLite" look
# identical in an empty log. This module has no constructors: DT_INIT_ARRAY is 0xb28f8 with
# DT_INIT_ARRAYSZ 0x8, that word is zero in the file, and .rela.dyn has no relocation for
# it. (0xb2900, whose addend 0x109fc I first mistook for the second init slot, is
# DT_FINI_ARRAY[0] -- a destructor, so pointing it at a stub proves nothing at load.)
# DT_SYMBOLIC is deprecated and bionic's linker does not even parse it, which leaves its
# .dynamic entry as a free slot to turn into DT_INIT. DT_FLAGS_1 is DF_1_NOW, so every PLT
# slot is resolved before the init function runs either way.
DYN_OFF, DYN_SZ = 0xa4be8, 0x1e0
DT_INIT, DT_SYMBOLIC = 12, 16
# Four candidate log files, tried in order. Which of them the translated native code can
# actually open is exactly what is unknown, so all four are attempted and putstr reports
# every failure code at once; /data/local/tmp is the one adb can read directly, which would
# end the need for the in-app logcat relay if it ever opens.
PATH1 = b'/data/user/0/com.klab.lapis/files/klbopen.log\x00'
PATH2 = b'/data/user/0/com.klab.lapis/cache/klbopen.log\x00'
PATH3 = b'/storage/emulated/0/Android/data/com.klab.lapis/files/klbopen.log\x00'
PATH4 = b'/data/local/tmp/klbopen.log\x00'
NIL = b'(nil)\x00'
T_REG, T_OPEN, T_VFS = b'REG\n\x00', b'OPEN\n\x00', b'VFS\n\x00'
T_SQL, T_VX, T_INIT = b'SQL\n\x00', b'VX\n\x00', b'INIT\n\x00'
T_RX = b'RX\n\x00'
T_XE = b'XE\n\x00'
T_VU = b'VU\n\x00'
T_FU = b'FU\n\x00'
T_FS = b'FS\n\x00'
STRINGS = (('PATH1', PATH1), ('PATH2', PATH2), ('PATH3', PATH3), ('PATH4', PATH4),
           ('NIL', NIL),
           ('T_REG', T_REG), ('T_OPEN', T_OPEN), ('T_VFS', T_VFS), ('T_SQL', T_SQL),
           ('T_VX', T_VX), ('T_INIT', T_INIT), ('T_RX', T_RX), ('T_XE', T_XE),
           ('T_VU', T_VU), ('T_FU', T_FU), ('T_FS', T_FS))

# Raw syscall numbers: the libc wrappers were measured returning -1 for open() from inside
# this cave, which left two irreducible explanations -- the translator's libc is not usable
# from here, or the paths are not what we think. Talking to the kernel directly collapses
# that, because a raw syscall returns -errno itself rather than -1 plus a side channel.
SYS = {'lseek': 62, 'openat': 56, 'close': 57, 'write': 64}
# openat's dirfd is never consulted for an absolute path, but AT_FDCWD is what any native
# build would pass, so pass it rather than rely on that reading of the kernel's path_init.
AT_FDCWD, O_WRONLY_CREAT_APPEND, MODE = 100, 0x441, 0x1b6

GT, LT, LE, NE = 0xC, 0xB, 0xD, 0x1
EQ, HI, LS = 0x0, 0x8, 0x9
NUM = re.compile(r'#0x[0-9a-fA-F]+|#\d+|0x[0-9a-fA-F]+|\b\d+\b')
LSL = re.compile(r'(#0x[0-9a-fA-F]+|#\d+)\s*,\s*lsl\s*#(\d+)')


def value(tok):
    body = tok[1:] if tok.startswith('#') else tok
    return int(body[2:], 16) if body.startswith('0x') else int(body)


def norm(s):
    """Canonicalise immediates so capstone's rendering choices are irrelevant: hex vs
    decimal, and the shifted form it prints for CMP when the constant only fits as
    imm<<12. A wrong field layout changes the numeric value, so the check keeps its teeth."""
    def rep(m):
        tok = m.group(0)
        return ('#' if tok.startswith('#') else '') + str(value(tok))
    s = LSL.sub(lambda m: '#%d' % (value(m.group(1)) << int(m.group(2))), s)
    return NUM.sub(rep, s.replace('\t', ' ')).replace(' ', '')


# ---------------- encoders (each one round-trip checked at emit time)
def sub_sp(imm):
    return 0xd1000000 | ((imm & 0xfff) << 10) | (31 << 5) | 31


def add_sp(imm):
    return 0x91000000 | ((imm & 0xfff) << 10) | (31 << 5) | 31


def mem_enc(base, rt, rn, imm, scale=3):
    return base | (((imm >> scale) & 0xfff) << 10) | (rn << 5) | rt


def str64(rt, rn, imm):
    return mem_enc(0xf9000000, rt, rn, imm)


def ldr64(rt, rn, imm):
    return mem_enc(0xf9400000, rt, rn, imm)


def str32(rt, rn, imm):
    return mem_enc(0xb9000000, rt, rn, imm, 2)


def ldr32(rt, rn, imm):
    return mem_enc(0xb9400000, rt, rn, imm, 2)


def movz(rd, imm, w64=False):
    return (0xd2800000 if w64 else 0x52800000) | ((imm & 0xffff) << 5) | rd


def add64(rd, rn, imm):
    return 0x91000000 | ((imm & 0xfff) << 10) | (rn << 5) | rd


def sub64(rd, rn, imm):
    return 0xd1000000 | ((imm & 0xfff) << 10) | (rn << 5) | rd


def cmp32(rn, imm):
    return 0x71000000 | ((imm & 0xfff) << 10) | (rn << 5) | 31


def cmp64imm(rn, imm):
    return 0xf1000000 | ((imm & 0xfff) << 10) | (rn << 5) | 31


def add32(rd, rn, imm):
    return 0x11000000 | ((imm & 0xfff) << 10) | (rn << 5) | rd


def ldrb(rt, rn, imm):
    """0x3840... is the *unscaled* LDURB, which is what the near-miss base reads as."""
    return 0x39400000 | ((imm & 0xfff) << 10) | (rn << 5) | rt


def strb(rt, rn, imm):
    return 0x39000000 | ((imm & 0xfff) << 10) | (rn << 5) | rt


def sub_w(rd, rn, imm):
    return 0x51000000 | ((imm & 0xfff) << 10) | (rn << 5) | rd


def lsl64(rd, rn, imm):
    """LSL immediate is an alias of UBFM xd, xn, #(64-n), #(63-n). (0x9340... is the SBFM
    twin, which capstone renders as sbfiz -- easy to mix up, so it is checked at emit.)"""
    return 0xd3400000 | (((64 - imm) & 0x3f) << 16) | (((63 - imm) & 0x3f) << 10) \
        | (rn << 5) | rd


def orr64(rd, rn, rm):
    return 0xaa000000 | (rm << 16) | (rn << 5) | rd


def sub64reg(rd, rn, rm):
    """SUB shifted register, 64-bit; with rn = 31 (xzr) capstone calls it NEG."""
    return 0xcb000000 | ((rm & 31) << 16) | (rn << 5) | rd


def cmp64(rn, imm):
    """64-bit CMP with the 12-bit immediate shifted left by 12: only multiples of 4096."""
    assert imm % 4096 == 0 and imm // 4096 <= 0xfff, 'cmp x%d, #0x%x' % (rn, imm)
    return 0xf1400000 | (((imm >> 12) & 0xfff) << 10) | (rn << 5) | 31


def mov_reg(rd, rm):
    return 0xaa0003e0 | (rm << 16) | rd


def adrp(rd, target, pc):
    d = ((target & ~0xfff) - (pc & ~0xfff)) >> 12
    # immhi is 19 bits, not 20: a negative page delta sign-extends, and the extra bit lands in
    # the fixed 10000 field, which makes the word undecodable.
    return 0x90000000 | ((d & 3) << 29) | (((d >> 2) & 0x7ffff) << 5) | rd


def b(target, pc):
    return 0x14000000 | (((target - pc) >> 2) & 0x3ffffff)


def bl(target, pc):
    return 0x94000000 | (((target - pc) >> 2) & 0x3ffffff)


def bcond(cond, target, pc):
    return 0x54000000 | ((((target - pc) >> 2) & 0x7ffff) << 5) | cond


def cbz(rt, target, pc, nz=False, w64=True):
    base = (0xb5000000 if nz else 0xb4000000) if w64 else (0x35000000 if nz else 0x34000000)
    return base | ((((target - pc) >> 2) & 0x7ffff) << 5) | rt


RET = 0xd65f03c0
SVC = 0xd4000001


# ---------------- text helpers mirroring capstone's rendering
def mt(rt, rn, imm, w):
    return '%s%s, [%s%s]' % (w, rt, rn, '' if imm == 0 else ', #0x%x' % imm)


def span(blob):
    """Bytes a data item really occupies: emit() pads to word size, and every address
    calculation here has to agree with that or a tag would point into its own padding."""
    return len(blob) + (-len(blob)) % 4


class Cave:
    """Two-pass mini assembler: labels are resolved before any word is encoded."""

    def __init__(self, base):
        self.base = base
        self.items = []
        self.labels = {}
        self.resolved = False

    def label(self, name):
        self.items.append(('label', name))

    def ins(self, enc, want):
        self.items.append(('ins', enc, want))

    def raw(self, word):
        """Copy an existing instruction verbatim (it has no PC-relative operands)."""
        self.items.append(('raw', int.from_bytes(word, 'little') if hasattr(word, 'hex')
                           else word))

    def data(self, blob):
        self.items.append(('data', blob))

    def size(self):
        return sum(4 if i[0] in ('ins', 'raw') else span(i[1]) for i in self.items if i[0] != 'label')

    def here(self):
        return self.base + self.size()

    # ---- sugar
    def sub_sp(self, imm):
        self.ins(lambda pc: sub_sp(imm), lambda pc: 'sub sp, sp, #0x%x' % imm)

    def add_sp(self, imm):
        self.ins(lambda pc: add_sp(imm), lambda pc: 'add sp, sp, #0x%x' % imm)

    def st(self, rt, imm, w='x', rn=31):
        enc = str64 if w == 'x' else str32
        name = 'sp' if rn == 31 else 'x%d' % rn
        self.ins(lambda pc: enc(rt, rn, imm), lambda pc: 'str ' + mt(rt, name, imm, w))

    def ld(self, rt, imm, w='x', rn=31):
        enc = ldr64 if w == 'x' else ldr32
        name = 'sp' if rn == 31 else 'x%d' % rn
        self.ins(lambda pc: enc(rt, rn, imm), lambda pc: 'ldr ' + mt(rt, name, imm, w))

    def movm(self, rd, imm):
        self.ins(lambda pc: movz(rd, imm), lambda pc: 'mov w%d, #0x%x' % (rd, imm))

    def movx(self, rd, imm):
        self.ins(lambda pc: movz(rd, imm, True), lambda pc: 'mov x%d, #0x%x' % (rd, imm))

    def subw(self, rd, rn, imm):
        self.ins(lambda pc: sub_w(rd, rn, imm),
                 lambda pc: 'sub w%d, w%d, #0x%x' % (rd, rn, imm))

    def lsl8(self, rd, rn):
        self.ins(lambda pc: lsl64(rd, rn, 8), lambda pc: 'lsl x%d, x%d, #0x8' % (rd, rn))

    def orr(self, rd, rn, rm):
        self.ins(lambda pc: orr64(rd, rn, rm),
                 lambda pc: 'orr x%d, x%d, x%d' % (rd, rn, rm))

    def neg(self, rd, rm):
        self.ins(lambda pc: sub64reg(rd, 31, rm), lambda pc: 'neg x%d, x%d' % (rd, rm))

    def svc(self):
        self.ins(lambda pc: SVC, lambda pc: 'svc #0')

    def strzero(self, rn):
        """The fault channel: a store through an address we chose, so the tombstone's
        'fault addr' reads back as the value in rn."""
        self.ins(lambda pc: str64(31, rn, 0), lambda pc: 'str xzr, [%s]' % ('x%d' % rn))

    def cmpi(self, rn, imm, w64=False):
        if not w64:
            self.ins(lambda pc: cmp32(rn, imm), lambda pc: 'cmp w%d, #0x%x' % (rn, imm))
        elif imm <= 0xfff:
            self.ins(lambda pc: cmp64imm(rn, imm), lambda pc: 'cmp x%d, #0x%x' % (rn, imm))
        else:
            self.ins(lambda pc: cmp64(rn, imm), lambda pc: 'cmp x%d, #0x%x' % (rn, imm))

    def addx(self, rd, rn, imm):
        self.ins(lambda pc: add64(rd, rn, imm),
                 lambda pc: 'add x%d, x%d, #0x%x' % (rd, rn, imm))

    def subx(self, rd, rn, imm):
        self.ins(lambda pc: sub64(rd, rn, imm),
                 lambda pc: 'sub x%d, x%d, #0x%x' % (rd, rn, imm))

    def addw(self, rd, rn, imm):
        self.ins(lambda pc: add32(rd, rn, imm),
                 lambda pc: 'add w%d, w%d, #0x%x' % (rd, rn, imm))

    def ldrb(self, rt, rn):
        self.ins(lambda pc: ldrb(rt, rn, 0), lambda pc: 'ldrb w%d, [x%d]' % (rt, rn))

    def stb(self, rt, rn, imm, wzr=False):
        reg = 'wzr' if (wzr or rt == 31) else 'w%d' % rt
        name = 'sp' if rn == 31 else 'x%d' % rn
        enc = strb(31 if wzr else rt, rn, imm)
        self.ins(lambda pc: enc,
                 lambda pc: 'strb %s, [%s%s]' % (reg, name, '' if imm == 0 else ', #0x%x' % imm))

    def addr(self, rd, name):
        """rd <- address of a label, via adrp + add."""
        self.ins(lambda pc: adrp(rd, self.labels[name], pc),
                 lambda pc: 'adrp x%d, #0x%x' % (rd, self.labels[name] & ~0xfff))
        self.ins(lambda pc: add64(rd, rd, self.labels[name] & 0xfff),
                 lambda pc: 'add x%d, x%d, #0x%x' % (rd, rd, self.labels[name] & 0xfff))

    def addr_abs(self, rd, vaddr):
        """rd <- an address that already exists in the module (not one of our labels)."""
        self.ins(lambda pc: adrp(rd, vaddr, pc),
                 lambda pc: 'adrp x%d, #0x%x' % (rd, vaddr & ~0xfff))
        self.ins(lambda pc: add64(rd, rd, vaddr & 0xfff),
                 lambda pc: 'add x%d, x%d, #0x%x' % (rd, rd, vaddr & 0xfff))

    def call(self, name):
        self.ins(lambda pc: bl(self.labels[name], pc), lambda pc: 'bl #0x%x' % self.labels[name])

    def jmp(self, name):
        self.ins(lambda pc: b(self.labels[name], pc), lambda pc: 'b #0x%x' % self.labels[name])

    def jmp_abs(self, target):
        """Branch to a fixed address outside the cave (range is +-1 MiB)."""
        self.ins(lambda pc: b(target, pc), lambda pc: 'b #0x%x' % target)

    def br(self, cond, name):
        text = {LE: 'b.le', GT: 'b.gt', LT: 'b.lt', NE: 'b.ne', EQ: 'b.eq',
                HI: 'b.hi', LS: 'b.ls'}.get(cond)
        if text is None:
            raise SystemExit('unmapped condition %d' % cond)
        self.ins(lambda pc: bcond(cond, self.labels[name], pc),
                 lambda pc: '%s #0x%x' % (text, self.labels[name]))

    def cbz(self, rt, name, w64=True):
        reg = 'x%d' % rt if w64 else 'w%d' % rt
        self.ins(lambda pc: cbz(rt, self.labels[name], pc, w64=w64),
                 lambda pc: 'cbz %s, #0x%x' % (reg, self.labels[name]))

    def ret(self):
        self.ins(lambda pc: RET, lambda pc: 'ret')

    def resolve(self):
        if self.resolved:
            return self.labels
        pc = self.base
        for it in self.items:
            if it[0] == 'label':
                self.labels[it[1]] = pc
            elif it[0] == 'data':
                pc += span(it[1])
            else:
                pc += 4
        assert pc == self.base + self.size(), 'layout disagree'
        self.resolved = True
        return self.labels

    def emit(self):
        self.resolve()
        md = Cs(CS_ARCH_ARM64, CS_MODE_ARM)
        out = bytearray()
        pc = self.base
        for it in self.items:
            if it[0] == 'label':
                continue
            if it[0] == 'data':
                out += it[1] + b'\0' * (span(it[1]) - len(it[1]))
                pc += span(it[1])
                continue
            if it[0] == 'raw':
                out += struct.pack('<I', it[1])
                pc += 4
                continue
            word, want = it[1](pc), it[2](pc)
            out += struct.pack('<I', word)
            try:
                got = next(md.disasm(struct.pack('<I', word), pc))
            except StopIteration:
                raise SystemExit('UNDECODABLE @0x%x: word 0x%08x want "%s"' % (pc, word, want))
            text = got.mnemonic + ' ' + got.op_str
            if norm(text) != norm(want):
                raise SystemExit('BAD @0x%x: got "%s" want "%s"' % (pc, text, want))
            pc += 4
        return out

    def spans(self):
        """(label -> (addr, nbytes)) for every label, so listings print real lengths."""
        self.resolve()
        pts = sorted(((v, k) for k, v in self.labels.items()
                      if any(i[0] == 'label' and i[1] == k for i in self.items)))
        out = {}
        end = self.base + self.size()
        for i, (a, n) in enumerate(pts):
            out[n] = (a, pts[i + 1][0] - a if i + 1 < len(pts) else end - a)
        return out


def syscalls(c):
    """The handful of kernel entry points putstr needs, each one 'mov x8, #nr; svc #0'.

    Hand-written because the libc wrappers were measured returning -1 from inside the cave.
    A raw syscall's return value *is* -errno, which is what lets putstr report why a path
    failed rather than only that it did.
    """
    c.label('do_open')                          # x1 = absolute path -> x0 = fd or -errno
    c.movm(0, 0)
    c.subw(0, 0, AT_FDCWD)
    c.movm(2, O_WRONLY_CREAT_APPEND)            # O_WRONLY|O_CREAT|O_APPEND
    c.movm(3, MODE)                             # 0666
    c.movx(8, SYS['openat'])
    c.svc()
    c.ret()

    c.label('do_lseek')                         # x0 = fd, x1 = off, x2 = whence
    c.movx(8, SYS['lseek'])
    c.svc()
    c.ret()

    c.label('do_write')                         # x0 = fd, x1 = buf, x2 = len
    c.movx(8, SYS['write'])
    c.svc()
    c.ret()

    c.label('do_close')                         # x0 = fd
    c.movx(8, SYS['close'])
    c.svc()
    c.ret()

    c.label('slen')                             # x1 = string -> x0 = strlen + 1
    c.movm(0, 0)
    c.label('sloop')
    c.ldrb(2, 1)
    c.cbz(2, 'sdone', w64=False)
    c.addx(1, 1, 1)
    c.addw(0, 0, 1)
    c.jmp('sloop')
    c.label('sdone')
    c.addx(0, 0, 1)
    c.ret()


def putstr(c):
    """Inert. The diagnostic logger is not part of the deliverable.

    It used to open one of four hard-coded klbopen.log paths, and when every one of them
    failed it deliberately stored through the packed errno so the tombstone's fault address
    read back which path failed and why. Those paths name the CN package, so the JP build
    (uid u0_a72, which cannot traverse com.klab.lapis) failed all four and took the
    deliberate SIGSEGV on every boot -- the client never reached its title screen. Keeping
    the label preserves the shape of every detour body that still calls it; the body must
    do nothing at all.
    """
    c.label('putstr')
    c.ret()


def open_detour(c, name, hook, orig_word):
    """Detour sqlite3_open_v2 that runs plain_vfs_rewrite and logs nothing.

    The argument registers are spilled and reloaded around the rewrite so the callee sees
    the amended x3; x30 is spilled because the body uses no stack of its own beyond this
    frame. The original first instruction is copied verbatim (it has no PC-relative
    operands) and control returns to hook+4, exactly as the unpatched function expected.
    """
    keep = [0, 1, 2, 3, 30]
    c.label(name)
    c.sub_sp(FRAME)
    for i, r in enumerate(keep):
        c.st(r, i * 8)
    plain_vfs_rewrite(c, keep)
    for i, r in enumerate(keep):
        c.ld(r, i * 8)
    c.add_sp(FRAME)
    c.raw(orig_word)
    c.ins(lambda pc: b(hook + 4, pc), lambda pc: 'b #0x%x' % (hook + 4))


def boot_stub(c, name, tag):
    """The DT_INIT entry point: called with no arguments, so it only has to report that the
    module was mapped and that putstr works, then return."""
    c.label(name)
    c.sub_sp(FRAME)
    c.st(30, 0x08)
    c.addr(0, tag)
    c.call('putstr')
    c.ld(30, 0x08)
    c.add_sp(FRAME)
    c.ret()


def hook_stub(c, name, hook, tag, regs, derefs, orig_word, extra=None):
    """Detour prologue: preserve the arguments, log <tag> then each value, then run the
    original first instruction and continue at hook+4.

    regs   - argument registers the body still needs (x30 is appended automatically)
    derefs - (reg, displacement) pairs to log; displacement 0 logs the register itself
    extra  - called after the logging and before the registers are reloaded, so it can amend
             the saved argument slots and have the callee see the amended values
    """
    keep = list(regs) + [30]
    assert len(keep) * 8 <= FRAME, 'spill frame too small for %s' % name
    c.label(name)
    c.sub_sp(FRAME)
    for i, r in enumerate(keep):
        c.st(r, i * 8)
    c.addr(0, tag)
    c.call('putstr')
    for reg, disp in derefs:
        slot = keep.index(reg) * 8
        if disp:
            c.ld(8, slot)
            c.ld(0, disp, rn=8)
        else:
            c.ld(0, slot)
        c.call('putstr')
    if extra is not None:
        extra(c, keep)
    for i, r in enumerate(keep):
        c.ld(r, i * 8)
    c.add_sp(FRAME)
    c.raw(orig_word)
    c.ins(lambda pc: b(hook + 4, pc), lambda pc: 'b #0x%x' % (hook + 4))


def plain_vfs_rewrite(c, keep):
    """Send an unprefixed database to the real file-system vfs instead of klb's wrapper.

    klb_vfs.xOpen only ever accepts names of the form '<k0>.<k1>.<k2> <path>', and the triple
    is minted in memory by the download/installer pass we deliberately bypass -- it appears in
    no file on the device (a full grep of external storage found it nowhere).  A seeded database
    is therefore opened by a bare path, which klb rejects, and since the reject happens before
    any read the connection dies with zero prepared statements.  Handing the same request to the
    'unix' vfs skips the wrapper entirely and reads the seeded plaintext verbatim.

    The guard is the first byte: a digit means the installer is in the loop and its key prefix
    means the file is not plaintext, so that case is left exactly as it was.  b.ls after
    'sub w1, w1, #0x30' is the digit test -- an unsigned value at most 9 can only come from
    '0'..'9', while '/' (0x2f) wraps to 0xffffffff and falls through to the rewrite.
    """
    c.ld(0, keep.index(0) * 8)
    c.cbz(0, 'plain_keep')
    c.ldrb(1, 0)
    c.subw(1, 1, 0x30)
    c.cmpi(1, 9)
    c.br(LS, 'plain_keep')
    c.addr_abs(0, VFS_UNIX_NAME)
    c.st(0, keep.index(3) * 8)
    c.label('plain_keep')


def unix_xopen_stub(c, name, hook, tag, stripped, orig_word):
    """Log the unix vfs xOpen and hand it the path with any key field removed.

    Measured, first run with the rewrite in place: the game asks for
    '/storage/.../MasterData/master_data.db' (that is what the OPEN record prints from x0 of
    sqlite3_open_v2), but by the time the request reaches the vfs the name is
    '// /storage/.../MasterData/master_data.db'.  Something between the two prepends a key field
    and the separating space -- the same '<key> <path>' shape klb_vfs.xOpen parses -- and with no
    installer having run there is no key in it, so the field degenerates to '//'.  No such file
    exists, the open fails with SQLITE_CANTOPEN before a single byte is read, and that is why the
    SQL count stayed at zero even though the vfs swap worked.

    So strip it here, at the one boundary where the name is still just an argument: scan for the
    first space, accept the cut only if an absolute path follows it, and overwrite the saved x1
    slot.  klb's own delegation cannot be disturbed by this, because it steps over its space with
    its own 'add x1, x1, #1' before it ever calls down.
    """
    keep = (0, 1, 2, 3, 4, 30)
    c.label(name)
    c.sub_sp(FRAME)
    for i, r in enumerate(keep):
        c.st(r, i * 8)
    c.addr(0, tag)
    c.call('putstr')
    c.ld(0, 8)
    c.call('putstr')
    c.ld(0, 8)
    c.cbz(0, 'fux_done')
    c.label('fux_scan')
    c.ldrb(1, 0)
    c.cmpi(1, 0x20)
    c.br(EQ, 'fux_space')
    c.cmpi(1, 0)
    c.br(NE, 'fux_step')
    c.jmp('fux_done')
    c.label('fux_step')
    c.addx(0, 0, 1)
    c.jmp('fux_scan')
    c.label('fux_space')
    c.addx(0, 0, 1)
    c.ldrb(1, 0)
    c.cmpi(1, 0x2f)
    c.br(NE, 'fux_done')
    c.st(0, 8)
    c.addr(0, stripped)
    c.call('putstr')
    c.ld(0, 8)
    c.call('putstr')
    c.label('fux_done')
    for i, r in enumerate(keep):
        c.ld(r, i * 8)
    c.add_sp(FRAME)
    c.raw(orig_word)
    c.jmp_abs(hook + 4)


def xread_exit_stub(c, name, hook, tag, orig_word):
    """Detour of klb xRead's shared exit block, which reports what the client really read.

    Both paths reach 0x11090 (the delegate-error cbnz and the loop's b.le), and there
    x21=zBuf, x24=iOfst, w25=rc are all live, so the exit block is the one place the
    post-transform buffer can be observed. Only the offset-0 read is logged: that is
    SQLite's 100-byte header probe, and its first bytes are the fixed string
    'SQLite format 3' -- so the record says directly whether the client's de-XOR of what
    we served came out as the database we meant. Logging every read would be a page read
    per call, and the log's own 64 KiB cap would be spent before the answer.

    rc is produced by re-running the site's own 'mov w0,w25' after putstr rather than by
    stashing it: putstr only touches x0-x3, x8, x19 and x30, so x25 survives it.
    """
    c.label(name)
    c.sub_sp(FRAME)
    c.cmpi(24, 0, w64=True)
    c.br(NE, 'rx_out')
    c.addr(0, tag)
    c.call('putstr')
    c.ld(3, 0, rn=21)
    c.st(3, 8)
    c.stb(0, 31, 16, wzr=True)
    c.ins(lambda pc: add64(0, 31, 8), lambda pc: 'add x0, sp, #8')
    c.call('putstr')
    c.label('rx_out')
    c.raw(orig_word)
    c.add_sp(FRAME)
    c.ins(lambda pc: b(hook + 4, pc), lambda pc: 'b #0x%x' % (hook + 4))


def unix_xopen_strip(c, name, hook, orig_word):
    """Detour the unix vfs's xOpen and hand it the path with any key field removed.

    This is a functional patch, not a log. The name reaching this vfs is
    '// /storage/.../MasterData/master_data.db' -- something between sqlite3_open_v2 and here
    prepends a key field and the separating space, the same '<key> <path>' shape klb_vfs.xOpen
    parses, and with no installer having run the field degenerates to '//'. No such file
    exists, the open fails with SQLITE_CANTOPEN before a single byte is read, and the loader
    dies on 'the given key was not present in the dictionary' while Language.lua:GetAllSync
    queries a table it could not open.

    So scan for the first space, accept the cut only if an absolute path follows it, and
    overwrite the saved x1 slot. klb's own delegation cannot be disturbed by this, because it
    steps over its space with its own 'add x1, x1, #1' before it ever calls down.
    """
    keep = (0, 1, 2, 3, 4, 30)
    c.label(name)
    c.sub_sp(FRAME)
    for i, r in enumerate(keep):
        c.st(r, i * 8)
    c.ld(0, 8)
    c.cbz(0, 'fux_done')
    c.label('fux_scan')
    c.ldrb(1, 0)
    c.cmpi(1, 0x20)
    c.br(EQ, 'fux_space')
    c.cmpi(1, 0)
    c.br(NE, 'fux_step')
    c.jmp('fux_done')
    c.label('fux_step')
    c.addx(0, 0, 1)
    c.jmp('fux_scan')
    c.label('fux_space')
    c.addx(0, 0, 1)
    c.ldrb(1, 0)
    c.cmpi(1, 0x2f)
    c.br(NE, 'fux_done')
    c.st(0, 8)
    c.label('fux_done')
    for i, r in enumerate(keep):
        c.ld(r, i * 8)
    c.add_sp(FRAME)
    c.raw(orig_word)
    c.jmp_abs(hook + 4)


def bare_name_stub(c, name):
    """Adopt an unprefixed database name instead of failing xOpen on it.

    Reached from the parse loop's 'not the separating space' branch, so x1 points at the
    offending byte and x0 is still the vfs (nothing between the prologue and here writes
    x0).  The real-open sequence steps over the space with its own 'add x1, x1, #1', so
    back up one byte first and the path it opens is exactly the string we were handed.
    The key triple is left at whatever the digits so far accumulated -- with the store
    NOP'd nothing reads it, and for a bare path nothing ever will.
    """
    c.label(name)
    c.subx(1, 1, 1)
    c.jmp_abs(XOPEN_REALOPEN)


def xopen_exit_stub(c, name, hook, tag, orig_word):
    """Detour of xOpen's single epilogue, which reports the return code.

    Both the parse failures (which load w0 with 1) and the real-open fallthrough reach
    0x10fa8, so this is the one place that says whether an open was accepted.  x19, x29
    and x30 are all reloaded from the caller's frame by the instructions that follow, so
    only w0 needs stashing across putstr -- and it must be stashed, because putstr takes
    its argument in x0.  The code is logged as one ASCII character: '0' is SQLITE_OK and
    '1' is the parse rejection, which is the whole question here.
    """
    c.label(name)
    c.sub_sp(FRAME)
    c.st(0, 8, w='w')
    c.addr(0, tag)
    c.call('putstr')
    c.ld(0, 8, w='w')
    c.addw(0, 0, 0x30)
    c.st(0, 0xc, w='w')
    c.stb(0, 31, 0x10, wzr=True)
    c.ins(lambda pc: add64(0, 31, 0xc), lambda pc: 'add x0, sp, #0xc')
    c.call('putstr')
    c.ld(0, 8, w='w')
    c.add_sp(FRAME)
    c.raw(orig_word)
    c.ins(lambda pc: b(hook + 4, pc), lambda pc: 'b #0x%x' % (hook + 4))


def use_dt_init(d, value):
    """Turn this module's DT_SYMBOLIC entry into DT_INIT pointing at the boot stub.

    .dynamic lives in the file and is copied verbatim into the RW segment, so the swap has
    to keep the table's own size: DT_SYMBOLIC is at a lower index than any tag bionic cares
    about here, and the only requirement is that a slot exists."""
    hits = [pc for pc in range(0, DYN_SZ, 16)
            if struct.unpack_from('<q', d, DYN_OFF + pc)[0] == DT_SYMBOLIC]
    assert len(hits) == 1, 'expected one DT_SYMBOLIC, got %r' % [hex(h) for h in hits]
    assert struct.unpack_from('<Q', d, DYN_OFF + hits[0] + 8)[0] == 0, 'DT_SYMBOLIC has a value'
    struct.pack_into('<qQ', d, DYN_OFF + hits[0], DT_INIT, value)


def main():
    base = BAK.read_bytes()
    assert base[H_XOPEN:H_XOPEN + 4] == bytes.fromhex('fd7bbda9'), 'backup is not pristine'
    d = bytearray(base)
    c = Cave(CAVE)
    putstr(c)
    open_detour(c, 'h_open', H_OPEN, base[H_OPEN:H_OPEN + 4])
    unix_xopen_strip(c, 'h_fux', H_UNIX_XOPEN, base[H_UNIX_XOPEN:H_UNIX_XOPEN + 4])
    bare_name_stub(c, 'h_bare')
    end = c.here()
    assert end <= CODE_LIMIT, 'cave ends 0x%x past limit 0x%x' % (end, CODE_LIMIT)
    blob = c.emit()
    assert c.emit() == blob
    assert all(x == 0 for x in d[CAVE:end]), 'code cave is not free'

    d[CAVE:CAVE + len(blob)] = blob
    d[H_OPEN:H_OPEN + 4] = struct.pack('<I', b(c.labels['h_open'], H_OPEN))
    d[H_UNIX_XOPEN:H_UNIX_XOPEN + 4] = struct.pack('<I', b(c.labels['h_fux'], H_UNIX_XOPEN))
    assert struct.unpack_from('<I', d, XOPEN_SETMETHODS)[0] == XOPEN_SETMETHODS_WORD, \
        'xOpen pMethods store is not where the disassembly says'
    struct.pack_into('<I', d, XOPEN_SETMETHODS, NOP)
    assert struct.unpack_from('<I', d, XOPEN_NONDIGIT)[0] == XOPEN_NONDIGIT_WORD, \
        'xOpen name parse exit branch is not where the disassembly says'
    struct.pack_into('<I', d, XOPEN_NONDIGIT,
                     bcond(NE, c.labels['h_bare'], XOPEN_NONDIGIT))
    SO.write_bytes(bytes(d))

    print('functional build: %d words, cave 0x%x..0x%x (%dB)' %
          (c.size() // 4, CAVE, end, len(blob)))
    print('  h_open   0x%-7x -> 0x%x' % (H_OPEN, c.labels['h_open']))
    print('  h_fux    0x%-7x -> 0x%x' % (H_UNIX_XOPEN, c.labels['h_fux']))
    print('  plaintext-read patch: NOP 0x%x' % XOPEN_SETMETHODS)
    print('  bare-name accept: b.ne 0x%x -> 0x%x' % (XOPEN_NONDIGIT, c.labels['h_bare']))
    md = Cs(CS_ARCH_ARM64, CS_MODE_ARM)
    spans = c.spans()
    for label in ('putstr', 'h_open', 'fux_step', 'fux_space', 'fux_done', 'h_bare'):
        a, n = spans[label]
        print('-- %s @0x%x (%d insns) --' % (label, a, n // 4))
        for i in md.disasm(bytes(d[a:a + n]), a):
            print('  %x  %s\t%s' % (i.address, i.mnemonic, i.op_str))


main()
