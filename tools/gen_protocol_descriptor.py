"""Regenerate the business protocol descriptor from the client's own Lua schema.

The descriptor we had was recovered out of il2cpp string literals by a heuristic, and it is wrong:
the client's Lua defines P1000_Response as {result=1, authToken=2, authKey=3} while the recovered
file says {authToken=1, authKey=2, result=3}. Feeding a response built from the recovered file to
the Lua decoder makes it read our authToken bytes as the nested Result message, which then trips
decoder.lua's SkipField (the client's skip table has nil holes for the group wire types).

protocol_pb.decomp.lua is the decompiled form of Assets/Products/Lua/PB/Protos/protocol_pb.lua, i.e.
the schema the game actually parses with, so field numbers, labels, types and defaults are taken
from here and nowhere else.
"""
import re
import sys
from pathlib import Path

from google.protobuf import descriptor_pb2

SRC = Path(r'C:/lapisbuild/protos/protocol_pb.decomp.lua')
OUT = Path(r'C:/lapisbuild/stubapp/assets/protocol.descriptor.bin')

ASSIGN = re.compile(r'^protocol_pbTable\.([A-Za-z0-9_]+)\.([a-z_]+) = (.*)$')
DECL = re.compile(r'^protocol_pbTable\.([A-Za-z0-9_]+) = protobuf\.(\w+)\(\)$')
LIST_OPEN = re.compile(r'^protocol_pbTable\.([A-Za-z0-9_]+)\.([a-z_]+) = \{$')
REF = re.compile(r'^protocol_pbTable\.([A-Za-z0-9_]+)$')


def parse(text):
    kinds, attrs, lists = {}, {}, {}
    lines = text.split('\n')
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        m = DECL.match(line)
        if m:
            kinds[m.group(1)] = m.group(2)
            i += 1
            continue
        m = LIST_OPEN.match(line)
        if m:
            items, j = [], i + 1
            while j < len(lines) and lines[j].strip() != '}':
                token = lines[j].strip().rstrip(',')
                if token:
                    items.append(token)
                j += 1
            lists[(m.group(1), m.group(2))] = items
            i = j + 1
            continue
        m = ASSIGN.match(line)
        if m:
            attrs.setdefault(m.group(1), {})[m.group(2)] = m.group(3)
        i += 1
    return kinds, attrs, lists


def lua_str(v):
    return v[1:-1] if len(v) >= 2 and v[0] == '"' and v[-1] == '"' else None


def lua_num(v):
    try:
        return int(v)
    except ValueError:
        return None


def target_name(attrs, ref):
    """Resolve 'protocol_pbTable.PBRESULT' to that descriptor's fully-qualified name."""
    m = REF.match(ref)
    if not m or m.group(1) not in attrs:
        return None
    return lua_str(attrs[m.group(1)].get('full_name', ''))


def build(text):
    kinds, attrs, lists = parse(text)
    messages = [k for k, v in kinds.items() if v == 'Descriptor']
    enums = [k for k, v in kinds.items() if v == 'EnumDescriptor']

    fd = descriptor_pb2.FileDescriptorProto()
    fd.name = 'protocol.proto'
    fd.syntax = 'proto2'

    # Descriptors are keyed by their fully-qualified name because the protocol nests types
    # (".P120_Response.PBShopTab"); emitting those flat collides on the leaf name.
    by_full = {}

    def new_enum(key):
        a = attrs.get(key, {})
        full = lua_str(a['full_name'])
        ed = descriptor_pb2.EnumDescriptorProto()
        ed.name = lua_str(a['name'])
        by_full[full] = ed
        for item in lists.get((key, 'values'), []):
            va = attrs.get(item.split('.')[-1], {})
            ev = ed.value.add()
            ev.name = lua_str(va['name'])
            ev.number = lua_num(va['number'])
        return full, ed

    def new_message(key):
        a = attrs.get(key, {})
        full = lua_str(a['full_name'])
        md = descriptor_pb2.DescriptorProto()
        md.name = lua_str(a['name'])
        by_full[full] = md
        return full, md

    created = []
    for key in enums + messages:
        created.append(new_enum(key) if kinds[key] == 'EnumDescriptor' else new_message(key))

    required = []
    # The field lists are keyed by table variable, so walk messages by variable name.
    for key in messages:
        a = attrs.get(key, {})
        md = by_full[lua_str(a['full_name'])]
        for item in lists.get((key, 'fields'), []):
            fk = item.split('.')[-1]
            fa = attrs.get(fk, {})
            f = md.field.add()
            f.name = lua_str(fa['name'])
            f.number = lua_num(fa['number'])
            f.label = lua_num(fa['label'])
            f.type = lua_num(fa['type'])
            if f.type == descriptor_pb2.FieldDescriptorProto.TYPE_MESSAGE:
                f.type_name = target_name(attrs, fa.get('message_type', ''))
            elif f.type == descriptor_pb2.FieldDescriptorProto.TYPE_ENUM:
                f.type_name = target_name(attrs, fa.get('enum_type', ''))
            if lua_str(fa.get('default_value', '')) is not None:
                f.default_value = lua_str(fa['default_value'])
            elif 'default_value' in fa and fa['default_value'] not in ('nil', '{}'):
                f.default_value = fa['default_value']
            if f.label == descriptor_pb2.FieldDescriptorProto.LABEL_REQUIRED:
                required.append('%s.%s' % (md.name, f.name))

    attach_nested(fd, by_full)
    return fd, required


def attach_nested(fd, by_full):
    """Move dotted descriptors into their parent's nested_type / nested_enum lists."""
    # Deepest first: a parent must already contain its children when it is copied upward.
    for full, desc in sorted(by_full.items(), key=lambda kv: -kv[0].count('.')):
        parent, _, leaf = full.rpartition('.')
        if not parent:
            continue
        container = by_full.get(parent)
        if container is None:
            raise SystemExit('%s is nested inside unknown %s' % (full, parent))
        if isinstance(desc, descriptor_pb2.DescriptorProto):
            container.nested_type.append(desc)
        else:
            container.enum_type.append(desc)
    # Only the roots belong at file scope; the rest now live inside their parents.
    del fd.message_type[:]
    del fd.enum_type[:]
    fd.message_type.extend(m for f, m in sorted(by_full.items())
                           if isinstance(m, descriptor_pb2.DescriptorProto) and '.' not in f[1:])
    fd.enum_type.extend(e for f, e in sorted(by_full.items())
                        if isinstance(e, descriptor_pb2.EnumDescriptorProto) and '.' not in f[1:])
    return fd


def main():
    fd, required = build(SRC.read_text(encoding='utf-8', errors='replace'))
    blob = fd.SerializeToString()

    check = descriptor_pb2.FileDescriptorProto()
    check.ParseFromString(blob)
    # protobuf-java runs FileDescriptor.buildFrom on this bytes blob, which resolves every
    # type_name and rejects duplicates -- do the same check here so a bad blob is caught now.
    from google.protobuf import descriptor_pool
    descriptor_pool.DescriptorPool().Add(check)
    names = {m.name: m for m in check.message_type}
    for probe in ('P1000_Response', 'P1001_Request', 'P1001_Response'):
        m = names.get(probe)
        print('%-18s %s' % (probe, ['%s=%d/%s' % (f.name, f.number,
              descriptor_pb2.FieldDescriptorProto.Type.Name(f.type).replace('TYPE_', ''))
              for f in m.field] if m else 'MISSING'))
    print('messages=%d enums=%d bytes=%d required-fields=%d'
          % (len(check.message_type), len(check.enum_type), len(blob), len(required)))
    if required:
        print('required (responses must set these or build() throws): %s' % ', '.join(required[:12]))

    if OUT.exists():
        backup = OUT.with_suffix('.bin.recovered')
        if not backup.exists():
            backup.write_bytes(OUT.read_bytes())
            print('kept the heuristic recovery at %s' % backup.name)
    OUT.write_bytes(blob)
    print('wrote %s' % OUT)


if __name__ == '__main__':
    main()
