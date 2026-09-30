#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
"""
Record what a connected Vial keyboard answers, for the web build's demo mode.

*Try the demo* on the start page runs the real Vial app against a virtual keyboard that replays these
answers (vialgui/python/protocol/demo_device.py), so every tab shows what this board showed. Run it
once per firmware release, on a desktop with the board plugged in:

    pip install hidapi PyQt5
    python demo/capture-demo.py sofleplus2-tps65-510h

Everything on the board becomes public in the demo, macros included: capture from a board that holds
the stock layout and settings, or put the stock keymap back in afterwards with demo/stock-keymap.py.
--product relabels the board (see the note it records).
"""
import argparse
import datetime
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
VIALGUI = os.path.join(HERE, "..", "vialgui")
sys.path.insert(0, os.path.join(VIALGUI, "python"))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt5.QtWidgets import QApplication  # noqa: E402

from editor.qmk_settings import QmkSettings  # noqa: E402
from protocol.keyboard_comm import Keyboard  # noqa: E402
from util import find_vial_devices, MSG_LEN  # noqa: E402
from vial_device import VialDevice, VialKeyboard  # noqa: E402


class Recorder:
    """ Stands in for the hid device and remembers the answer to every request """

    def __init__(self, dev):
        self.dev = dev
        self.responses = {}
        self.pending = None

    def write(self, data):
        # data[0] is hidapi's report id
        self.pending = bytes(data[1:]).rstrip(b"\x00").hex()
        return self.dev.write(data)

    def read(self, length, timeout_ms=0):
        data = bytes(self.dev.read(length, timeout_ms=timeout_ms))
        if data and self.pending is not None:
            self.responses[self.pending] = data.rstrip(b"\x00").hex()
        self.pending = None
        return data

    def close(self):
        self.dev.close()


def capture(desc):
    kb = VialKeyboard(desc)
    VialDevice.open(kb)
    rec = Recorder(kb.dev)
    keyboard = Keyboard(rec)
    keyboard.reload()
    # the Security menu, the unlock check before a keymap change and the matrix tester ask these too
    keyboard.get_unlock_status()
    keyboard.get_unlock_keys()
    keyboard.matrix_poll()
    rec.close()
    return keyboard, rec.responses


def summary(keyboard):
    lines = ["layers {}, matrix {}x{}, encoders {}".format(
        keyboard.layers, keyboard.rows, keyboard.cols, len(keyboard.encoderpos))]
    macros = [m for m in keyboard.macro.split(b"\x00")[:keyboard.macro_count] if m]
    lines.append("macros in use: {} of {}".format(len(macros), keyboard.macro_count))
    blank = ("KC_NO", "KC_NO", "KC_NO", "KC_NO")
    lines.append("tap dances in use: {} of {}".format(
        sum(1 for e in keyboard.tap_dance_entries if tuple(e[:4]) != blank), keyboard.tap_dance_count))
    lines.append("combos in use: {} of {}".format(
        sum(1 for e in keyboard.combo_entries if e[4] != "KC_NO"), keyboard.combo_count))
    return lines, len(macros)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("name", help="demo name, becomes demo/<name>.json (e.g. sofleplus2-tps65-510)")
    ap.add_argument("--match", default="", help="pick the board whose product string contains this")
    ap.add_argument("--product", help="product string to show in the demo instead of the board's own")
    ap.add_argument("--note", default="", help="free text recorded in the file, e.g. why --product is used")
    args = ap.parse_args()

    app = QApplication(sys.argv)
    app.get_resource = lambda name: os.path.join(VIALGUI, name)
    QmkSettings.initialize(app)

    boards = [d for d in find_vial_devices({"definitions": {}}, quiet=True)
              if isinstance(d, VialKeyboard) and args.match in (d.desc["product_string"] or "")]
    if len(boards) != 1:
        sys.exit("need exactly one Vial keyboard (found {}); use --match".format(
            [d.desc["product_string"] for d in boards]))
    desc = boards[0].desc

    # two passes: an app talking to the board at the same time would interleave its answers with ours
    keyboard, responses = capture(desc)
    _, again = capture(desc)
    unstable = sorted(k for k in responses if again.get(k) != responses[k])
    if unstable:
        sys.exit("answers differ between two passes for {} requests (another app using the board?)".format(
            len(unstable)))

    product = args.product or desc["product_string"]
    out = {
        "format": 1,
        "name": product,
        "captured": datetime.date.today().isoformat(),
        "captured_from": desc["product_string"],
        "note": args.note,
        "matrix": {"rows": keyboard.rows, "cols": keyboard.cols},
        "desc": {
            "vendor_id": desc["vendor_id"],
            "product_id": desc["product_id"],
            "manufacturer_string": desc["manufacturer_string"],
            "product_string": product,
            "serial_number": desc["serial_number"],
            "release_number": desc["release_number"],
            "usage_page": desc["usage_page"],
            "usage": desc["usage"],
            "interface_number": desc["interface_number"],
        },
        "responses": responses,
    }
    path = os.path.join(HERE, args.name + ".json")
    with open(path, "w", newline="\n") as outf:
        json.dump(out, outf, indent=0, sort_keys=False)
        outf.write("\n")

    lines, macros = summary(keyboard)
    print("captured {} answers from '{}' -> {}".format(len(responses), desc["product_string"], path))
    for line in lines:
        print("  " + line)
    if macros:
        print("WARNING: the board has macros; they will be public in the demo")


if __name__ == "__main__":
    main()
