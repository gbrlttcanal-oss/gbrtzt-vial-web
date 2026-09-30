# SPDX-License-Identifier: GPL-2.0-or-later
"""
The keyboard behind the web build's demo mode (*Try the demo* on the start page).

It answers the VIA/Vial protocol from a recording of a real board (demo/capture-demo.py), in place of the
hid device, so the whole app runs unchanged. Writes update the answers of the matching reads, so an edit is
still there when a tab reads the board again (QMK Settings, the Revert buttons, loading a .vil); nothing
outlives the page.
"""
import logging
import struct

from protocol.constants import CMD_VIA_SET_KEYBOARD_VALUE, CMD_VIA_GET_KEYBOARD_VALUE, CMD_VIA_SET_KEYCODE, \
    CMD_VIA_LIGHTING_SET_VALUE, CMD_VIA_LIGHTING_GET_VALUE, CMD_VIA_MACRO_GET_BUFFER, CMD_VIA_MACRO_SET_BUFFER, \
    CMD_VIA_KEYMAP_GET_BUFFER, CMD_VIA_VIAL_PREFIX, CMD_VIAL_GET_ENCODER, CMD_VIAL_SET_ENCODER, \
    CMD_VIAL_QMK_SETTINGS_GET, CMD_VIAL_QMK_SETTINGS_SET, CMD_VIAL_QMK_SETTINGS_RESET, CMD_VIAL_DYNAMIC_ENTRY_OP, \
    VIALRGB_SET_MODE, VIALRGB_SET_TRACKPAD_SETTINGS, VIALRGB_SET_TRACKPAD_LAYERS, VIALRGB_SET_POWER_SETTINGS, \
    VIALRGB_SET_OLED_CONFIG
from util import MSG_LEN

# VialRGB settings whose GET answer is [0x08, sub-id] + the arguments of the last SET
MIRRORED_LIGHTING = {VIALRGB_SET_MODE, VIALRGB_SET_TRACKPAD_SETTINGS, VIALRGB_SET_TRACKPAD_LAYERS,
                     VIALRGB_SET_POWER_SETTINGS}


def _key(msg):
    # requests are zero-padded to MSG_LEN; the recording stores them without the padding
    return bytes(msg).rstrip(b"\x00")


class DemoDevice:

    def __init__(self, capture):
        self.captured = {bytes.fromhex(k): bytes.fromhex(v) for k, v in capture["responses"].items()}
        self.answers = dict(self.captured)
        self.rows = capture["matrix"]["rows"]
        self.cols = capture["matrix"]["cols"]
        self.keymap = self._buffer(CMD_VIA_KEYMAP_GET_BUFFER)
        self.macros = self._buffer(CMD_VIA_MACRO_GET_BUFFER)
        self.response = b""
        self.warned = set()

    def _buffer(self, cmd):
        """ Rebuild a memory the app reads in chunks (keymap, macros) from the recorded chunks """
        mem = bytearray()
        for req, resp in self.captured.items():
            if req[0] != cmd:
                continue
            req = req.ljust(4, b"\x00")
            offset, size = struct.unpack(">HB", req[1:4])
            if len(mem) < offset + size:
                mem.extend(b"\x00" * (offset + size - len(mem)))
            mem[offset:offset + size] = resp.ljust(4 + size, b"\x00")[4:4 + size]
        return mem

    # ---- the part of the hid device interface the app uses ----

    def open_path(self, path):
        pass

    def write(self, data):
        # data[0] is hidapi's report id
        msg = bytes(data[1:]).ljust(MSG_LEN, b"\x00")[:MSG_LEN]
        self.response = self.handle(msg).ljust(MSG_LEN, b"\x00")[:MSG_LEN]
        return len(data)

    def read(self, length, timeout_ms=0):
        return self.response[:length]

    def close(self):
        pass

    # ---- protocol ----

    def handle(self, msg):
        cmd = msg[0]

        if cmd in (CMD_VIA_KEYMAP_GET_BUFFER, CMD_VIA_MACRO_GET_BUFFER):
            mem = self.keymap if cmd == CMD_VIA_KEYMAP_GET_BUFFER else self.macros
            offset, size = struct.unpack(">HB", msg[1:4])
            return msg[:4] + bytes(mem[offset:offset + size])
        if cmd == CMD_VIA_MACRO_SET_BUFFER:
            offset, size = struct.unpack(">HB", msg[1:4])
            self.macros[offset:offset + size] = msg[4:4 + size]
            return msg
        if cmd == CMD_VIA_SET_KEYCODE:
            layer, row, col = msg[1:4]
            offset = (layer * self.rows * self.cols + row * self.cols + col) * 2
            self.keymap[offset:offset + 2] = msg[4:6]
            return msg
        if cmd == CMD_VIA_SET_KEYBOARD_VALUE:
            self.answers[_key(bytes([CMD_VIA_GET_KEYBOARD_VALUE]) + msg[1:2])] = \
                bytes([CMD_VIA_GET_KEYBOARD_VALUE]) + msg[1:]
            return msg
        if cmd == CMD_VIA_LIGHTING_SET_VALUE:
            sub = msg[1]
            if sub in MIRRORED_LIGHTING:
                self.answers[_key(bytes([CMD_VIA_LIGHTING_GET_VALUE, sub]))] = \
                    bytes([CMD_VIA_LIGHTING_GET_VALUE]) + msg[1:]
            elif sub == VIALRGB_SET_OLED_CONFIG:
                self.answers[_key(bytes([CMD_VIA_LIGHTING_GET_VALUE]) + msg[1:3])] = \
                    bytes([CMD_VIA_LIGHTING_GET_VALUE]) + msg[1:8]
            return msg
        if cmd == CMD_VIA_VIAL_PREFIX:
            return self.handle_vial(msg)
        return self.recorded(msg)

    def handle_vial(self, msg):
        sub = msg[1]
        if sub == CMD_VIAL_SET_ENCODER:
            layer, idx, direction = msg[2:5]
            req = _key(bytes([CMD_VIA_VIAL_PREFIX, CMD_VIAL_GET_ENCODER, layer, idx]))
            answer = bytearray(self.answers.get(req, b"").ljust(4, b"\x00"))
            answer[direction * 2:direction * 2 + 2] = msg[5:7]
            self.answers[req] = bytes(answer)
            return msg
        if sub == CMD_VIAL_QMK_SETTINGS_SET:
            self.answers[_key(bytes([CMD_VIA_VIAL_PREFIX, CMD_VIAL_QMK_SETTINGS_GET]) + msg[2:4])] = b"\x00" + msg[4:]
            return b"\x00" + msg[1:]
        if sub == CMD_VIAL_QMK_SETTINGS_RESET:
            # back to the recorded values, which stand in for the firmware defaults
            for req in [r for r in self.answers if r[:2] == bytes([CMD_VIA_VIAL_PREFIX, CMD_VIAL_QMK_SETTINGS_GET])]:
                self.answers[req] = self.captured[req]
            return msg
        if sub == CMD_VIAL_DYNAMIC_ENTRY_OP and msg[2] != 0 and msg[2] % 2 == 0:
            # tap dance / combo / key override / alt repeat key SET: op, index, entry -> GET is op - 1
            self.answers[_key(bytes([CMD_VIA_VIAL_PREFIX, CMD_VIAL_DYNAMIC_ENTRY_OP, msg[2] - 1, msg[3]]))] = \
                b"\x00" + msg[4:]
            return b"\x00" + msg[1:]
        return self.recorded(msg)

    def recorded(self, msg):
        req = _key(msg)
        if req in self.answers:
            return self.answers[req]
        # not recorded: a write the app does not read back, or a board feature the recording lacks. VIA
        # firmware answers a SET with the request itself, which is what the app expects.
        if req[:2] not in self.warned:
            self.warned.add(req[:2])
            logging.warning("demo keyboard: no recorded answer for %s, echoing it", req.hex())
        return msg
