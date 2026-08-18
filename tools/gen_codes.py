import re, sys

HEADER = "/usr/include/linux/input-event-codes.h"
raw = {}
order = []
pat = re.compile(r"^#define\s+((?:KEY|BTN|ABS)_[A-Z0-9_]+)\s+(\S+)")
for line in open(HEADER):
    m = pat.match(line)
    if not m:
        continue
    name, val = m.group(1), m.group(2)
    if name.endswith(("_CNT", "_MAX", "_MIN_INTERESTING")):
        continue
    raw[name] = val
    order.append(name)

def resolve(name, seen=()):
    val = raw[name]
    if val.startswith(("0x", "0X")):
        return int(val, 16)
    if val.isdigit():
        return int(val)
    if val in raw and val not in seen:
        return resolve(val, seen + (name,))
    if val.startswith("(") and val.endswith(")"):
        inner = val[1:-1].strip()
        if inner in raw:
            return resolve(inner, seen + (name,))
    return None

keys, btns, abses = {}, {}, {}
for name in order:
    code = resolve(name)
    if code is None:
        continue
    if name.startswith("KEY_"):
        keys[name[4:]] = code
    elif name.startswith("BTN_"):
        btns[name[4:]] = code
    elif name.startswith("ABS_"):
        abses[name[4:]] = code

def emit(varname, mapping, out):
    out.write(f"{varname} = {{\n")
    for k, v in mapping.items():
        out.write(f"    {k!r}: {v},\n")
    out.write("}\n\n")

with open("engine/_codes.py", "w") as out:
    out.write('"""Generated from linux/input-event-codes.h. Do not edit by hand.\n\n')
    out.write('Regenerate with tools/gen_codes.py.\n"""\n\n')
    out.write("# ruff: noqa: E501\n\n")
    emit("KEY_CODES", keys, out)
    emit("BTN_CODES", btns, out)
    emit("ABS_CODES", abses, out)

print("KEY:", len(keys), "BTN:", len(btns), "ABS:", len(abses))
