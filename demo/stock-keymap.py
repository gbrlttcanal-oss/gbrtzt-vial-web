#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
"""
Put the stock keymap and knob map into a demo recording, taken from the firmware build (.elf).

A board with a personal layout can then be recorded for the demo: it shows the layout a freshly flashed
board comes with. Like vial-qmk's dynamic_keymap_reset, layers past the compiled ones are KC_TRNS.
Lighting, trackpad, OLED and QMK settings stay as recorded; --oled sets single OLED labels.

    python demo/stock-keymap.py demo/sofleplus2-tps65-510h.json \\
        ../vial-qmk/.build/xcmkb_sofleplus2_tps65-510h.elf --oled "8=L8   "
"""
import argparse
import json
import os
import struct

KC_TRNS = 0x0001
CMD_VIA_GET_LAYER_COUNT = 0x11
CMD_VIA_KEYMAP_GET_BUFFER = 0x12
CMD_VIA_LIGHTING_GET_VALUE = 0x08
VIALRGB_GET_OLED_CONFIG = 0x52
CMD_VIA_VIAL_PREFIX = 0xFE
CMD_VIAL_GET_ENCODER = 0x03


def elf_symbol(path, name):
    """ Contents of a data symbol in a 32-bit little-endian ELF (the ARM firmware build) """
    with open(path, "rb") as inf:
        b = inf.read()
    if b[:4] != b"\x7fELF" or b[4] != 1 or b[5] != 1:
        raise SystemExit("{}: not a 32-bit little-endian ELF".format(path))
    shoff, = struct.unpack_from("<I", b, 0x20)
    shentsize, shnum = struct.unpack_from("<HH", b, 0x2E)
    sections = [struct.unpack_from("<10I", b, shoff + i * shentsize) for i in range(shnum)]
    for sec in sections:
        if sec[1] != 2:  # SHT_SYMTAB
            continue
        strtab = sections[sec[6]]
        for off in range(sec[4], sec[4] + sec[5], 16):
            st_name, value, size, _, _, shndx = struct.unpack_from("<IIIBBH", b, off)
            start = strtab[4] + st_name
            if b[start:b.index(b"\x00", start)].decode() == name:
                data = sections[shndx]
                pos = data[4] + value - data[3]
                return b[pos:pos + size]
    raise SystemExit("{}: no symbol {}".format(path, name))


def answer(data):
    return bytes(data).rstrip(b"\x00").hex()


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("recording", help="demo/<name>.json from capture-demo.py (changed in place)")
    ap.add_argument("elf", help="the firmware build, e.g. .build/xcmkb_sofleplus2_tps65-510h.elf")
    ap.add_argument("--oled", action="append", default=[], metavar="LAYER=NAME",
                    help="set an OLED label, e.g. 8=L8 (row1=NAME for the keyboard name)")
    args = ap.parse_args()

    with open(args.recording) as inf:
        rec = json.load(inf)
    responses = rec["responses"]
    rows, cols = rec["matrix"]["rows"], rec["matrix"]["cols"]
    layers = bytes.fromhex(responses[bytes([CMD_VIA_GET_LAYER_COUNT]).hex()]).ljust(2, b"\x00")[1]

    keymaps = elf_symbol(args.elf, "keymaps")
    compiled = len(keymaps) // (rows * cols * 2)
    codes = list(struct.unpack("<{}H".format(len(keymaps) // 2), keymaps))
    codes += [KC_TRNS] * (layers * rows * cols - len(codes))
    memory = struct.pack(">{}H".format(len(codes)), *codes)

    encoder_requests = [bytes.fromhex(r) for r in responses
                        if r.startswith(bytes([CMD_VIA_VIAL_PREFIX, CMD_VIAL_GET_ENCODER]).hex())]
    encoders = max((r.ljust(4, b"\x00")[3] for r in encoder_requests), default=-1) + 1
    encoder_map = elf_symbol(args.elf, "encoder_map") if encoders else b""
    encoder_layers = len(encoder_map) // (encoders * 4) if encoders else 0

    changed = 0
    for req in list(responses):
        r = bytes.fromhex(req).ljust(4, b"\x00")
        if r[0] == CMD_VIA_KEYMAP_GET_BUFFER:
            offset, size = struct.unpack(">HB", r[1:4])
            new = answer(r[:4] + memory[offset:offset + size])
        elif r[0] == CMD_VIA_VIAL_PREFIX and r[1] == CMD_VIAL_GET_ENCODER:
            layer, idx = r[2], r[3]
            if layer < encoder_layers:
                # the map holds {clockwise, counter-clockwise}; Vial answers counter-clockwise first
                cw, ccw = struct.unpack_from("<HH", encoder_map, (layer * encoders + idx) * 4)
            else:
                cw = ccw = KC_TRNS
            new = answer(struct.pack(">HH", ccw, cw))
        else:
            continue
        changed += new != responses[req]
        responses[req] = new

    for item in args.oled:
        layer, _, name = item.partition("=")
        idx = 0xFF if layer == "row1" else int(layer)
        req = bytes([CMD_VIA_LIGHTING_GET_VALUE, VIALRGB_GET_OLED_CONFIG, idx])
        responses[answer(req)] = answer(req + name.encode("ascii")[:5].ljust(5, b"\x00"))

    rec["stock_keymap_from"] = os.path.basename(args.elf)
    rec["note"] = " ".join(filter(None, [rec.get("note", ""),
                                         "Keymap and knobs replaced with the defaults compiled into {}.".format(
                                             os.path.basename(args.elf)),
                                         "OLED labels set: {}.".format(", ".join(args.oled)) if args.oled else ""]))
    with open(args.recording, "w", newline="\n") as outf:
        json.dump(rec, outf, indent=0)
        outf.write("\n")
    print("{}: keymap and knobs from {} ({} compiled layers of {}), {} answers changed{}".format(
        args.recording, os.path.basename(args.elf), compiled, layers, changed,
        ", OLED " + ", ".join(args.oled) if args.oled else ""))


if __name__ == "__main__":
    main()
