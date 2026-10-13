# SPDX-License-Identifier: GPL-2.0-or-later
import struct
import json
import lzma
from collections import OrderedDict

from keycodes.keycodes import RESET_KEYCODE, Keycode, recreate_keyboard_keycodes
from kle_serial import Serial as KleSerial
from protocol.alt_repeat_key import ProtocolAltRepeatKey
from protocol.combo import ProtocolCombo
from protocol.constants import CMD_VIA_GET_PROTOCOL_VERSION, CMD_VIA_GET_KEYBOARD_VALUE, CMD_VIA_SET_KEYBOARD_VALUE, \
    CMD_VIA_SET_KEYCODE, CMD_VIA_LIGHTING_SET_VALUE, CMD_VIA_LIGHTING_GET_VALUE, CMD_VIA_LIGHTING_SAVE, \
    CMD_VIA_GET_LAYER_COUNT, CMD_VIA_KEYMAP_GET_BUFFER, CMD_VIA_VIAL_PREFIX, VIA_LAYOUT_OPTIONS, \
    VIA_SWITCH_MATRIX_STATE, QMK_BACKLIGHT_BRIGHTNESS, QMK_BACKLIGHT_EFFECT, QMK_RGBLIGHT_BRIGHTNESS, \
    QMK_RGBLIGHT_EFFECT, QMK_RGBLIGHT_EFFECT_SPEED, QMK_RGBLIGHT_COLOR, VIALRGB_GET_INFO, VIALRGB_GET_MODE, \
    VIALRGB_GET_SUPPORTED, VIALRGB_SET_MODE, VIALRGB_GET_NUMBER_LEDS, VIALRGB_GET_LED_INFO, VIALRGB_DIRECT_FASTSET, \
    VIALRGB_GET_INDICATOR_LEDS, VIALRGB_GET_INDICATOR_COLORS, VIALRGB_SET_INDICATOR_LEDS, VIALRGB_SET_INDICATOR_COLORS, \
    VIALRGB_GET_DIRECT_COLORS, \
    VIALRGB_GET_TRACKPAD_SETTINGS, VIALRGB_SET_TRACKPAD_SETTINGS, \
    VIALRGB_GET_TRACKPAD_LAYERS, VIALRGB_SET_TRACKPAD_LAYERS, \
    VIALRGB_GET_POWER_SETTINGS, VIALRGB_SET_POWER_SETTINGS, \
    CMD_VIAL_GET_KEYBOARD_ID, CMD_VIAL_GET_SIZE, CMD_VIAL_GET_DEFINITION, \
    CMD_VIAL_GET_ENCODER, CMD_VIAL_SET_ENCODER, CMD_VIAL_GET_UNLOCK_STATUS, CMD_VIAL_UNLOCK_START, CMD_VIAL_UNLOCK_POLL, \
    CMD_VIAL_LOCK, CMD_VIAL_QMK_SETTINGS_QUERY, CMD_VIAL_QMK_SETTINGS_GET, CMD_VIAL_QMK_SETTINGS_SET, \
    CMD_VIAL_QMK_SETTINGS_RESET, BUFFER_FETCH_CHUNK, VIAL_PROTOCOL_QMK_SETTINGS
from protocol.dynamic import ProtocolDynamic
from protocol.key_override import ProtocolKeyOverride
from protocol.macro import ProtocolMacro
from protocol.tap_dance import ProtocolTapDance
from unlocker import Unlocker
from util import MSG_LEN, hid_send

SUPPORTED_VIA_PROTOCOL = [-1, 9]
SUPPORTED_VIAL_PROTOCOL = [-1, 0, 1, 2, 3, 4, 5, 6]


class ProtocolError(Exception):
    pass


class Keyboard(ProtocolMacro, ProtocolDynamic, ProtocolTapDance, ProtocolCombo, ProtocolKeyOverride, ProtocolAltRepeatKey):
    """ Low-level communication with a vial-enabled keyboard """

    def __init__(self, dev, usb_send=hid_send):
        self.dev = dev
        self.usb_send = usb_send
        self.definition = None

        # n.b. using OrderedDict here to make order of layout requests consistent for tests
        self.rowcol = OrderedDict()
        self.encoderpos = OrderedDict()
        self.encoder_count = 0
        self.layout = dict()
        self.encoder_layout = dict()
        self.rows = self.cols = self.layers = 0
        self.layout_labels = None
        self.layout_options = -1
        self.keys = []
        self.encoders = []
        self.vibl = False
        self.custom_keycodes = None
        self.midi = None

        self.lighting_qmk_rgblight = self.lighting_qmk_backlight = self.lighting_vialrgb = False

        # underglow
        self.underglow_brightness = self.underglow_effect = self.underglow_effect_speed = -1
        self.underglow_color = (0, 0)
        # backlight
        self.backlight_brightness = self.backlight_effect = -1
        # vialrgb
        self.rgb_mode = self.rgb_speed = self.rgb_version = self.rgb_maximum_brightness = -1
        self.rgb_hsv = (0, 0, 0)
        self.sleep_timeout_min = 1   # shared OLED+RGB sleep timeout (minutes)
        self.rgb_supported_effects = set()
        self.vialrgb_direct_supported = False
        self.vialrgb_num_leds = 0
        self.vialrgb_led_map = {}
        # LEDs with no matrix position (underglow): list of LED indices, plus
        # (x, y, flags) for every LED as reported by VIALRGB_GET_LED_INFO
        self.vialrgb_unkeyed_leds = []
        self.vialrgb_led_info = []
        self.vialrgb_direct_colors = []
        self.indicator_supported = False
        # Firmware stores a colour per LED within each role (VIALRGB 0x48). When False the
        # board only has one colour per role, and 'led_colors' below is ignored.
        self.indicator_led_colors_supported = False
        # None = not probed yet, False = firmware has no VIALRGB 0x54 (matrix tester knobs)
        self.encoder_events_supported = None
        self.trackpad_supported = False
        self.oled_supported = False
        self.oled_config = {
            'row1': 'SOFLE',
            'layer_names': ['L{}'.format(i) for i in range(10)],
        }
        self.trackpad_settings = {
            'cursor_dpi': 3, 'scroll_speed': 4,
            'scroll_invert_v': False, 'scroll_invert_h': False,
            'zoom_enabled': True, 'trackpad_enabled': True,
            'sniper_scale': 1, 'taps_as_clicks': False,
            'sniper_modifier_mask': 0,
        }
        self.trackpad_layers = {'scroll': 0, 'swipe2': 0, 'swipe3': 0}
        # 10 role slots: index 0 = Caps Lock, 1-9 = Layers 1-9
        # Each entry: {'leds': [int, ...] (unlimited list of LED indices), 'r','g','b': int}
        # Stored as flat LED→role map in firmware; converted here for GUI convenience.
        self.indicator_assignments = [
            {'leds': [], 'r': 128, 'g':   0, 'b':   0},  # caps
            {'leds': [], 'r': 128, 'g':   0, 'b': 128},  # layer 1
            {'leds': [], 'r': 255, 'g': 215, 'b':   0},  # layer 2
            {'leds': [], 'r':   0, 'g': 128, 'b': 128},  # layer 3
            {'leds': [], 'r': 255, 'g': 128, 'b':   0},  # layer 4
            {'leds': [], 'r':   0, 'g':   0, 'b': 128},  # layer 5
            {'leds': [], 'r': 128, 'g':   0, 'b': 128},  # layer 6
            {'leds': [], 'r': 255, 'g': 192, 'b': 203},  # layer 7
            {'leds': [], 'r':   0, 'g': 255, 'b': 127},  # layer 8
            {'leds': [], 'r': 255, 'g': 255, 'b': 255},  # layer 9
        ]

        self.via_protocol = self.vial_protocol = self.keyboard_id = -1

    def reload(self, sideload_json=None):
        """ Load information about the keyboard: number of layers, physical key layout """

        self.rowcol = OrderedDict()
        self.encoderpos = OrderedDict()
        self.layout = dict()
        self.encoder_layout = dict()

        self.reload_layout(sideload_json)
        self.reload_layers()

        self.reload_macros_early()
        self.reload_persistent_rgb()
        self.reload_rgb()
        self.reload_settings()

        self.reload_dynamic()

        # based on the number of macros, tapdance, etc, this will generate global keycode arrays
        recreate_keyboard_keycodes(self)

        # at this stage we have correct keycode info and can reload everything that depends on keycodes
        self.reload_keymap()
        self.reload_macros_late()
        self.reload_tap_dance()
        self.reload_combo()
        self.reload_key_override()
        self.reload_alt_repeat_key()

    def reload_layers(self):
        """ Get how many layers the keyboard has """

        self.layers = self.usb_send(self.dev, struct.pack("B", CMD_VIA_GET_LAYER_COUNT), retries=20)[1]

    def reload_via_protocol(self):
        data = self.usb_send(self.dev, struct.pack("B", CMD_VIA_GET_PROTOCOL_VERSION), retries=20)
        self.via_protocol = struct.unpack(">H", data[1:3])[0]

    def check_protocol_version(self):
        if self.via_protocol not in SUPPORTED_VIA_PROTOCOL or self.vial_protocol not in SUPPORTED_VIAL_PROTOCOL:
            raise ProtocolError()

    def reload_layout(self, sideload_json=None):
        """ Requests layout data from the current device """

        self.reload_via_protocol()

        self.sideload = False
        if sideload_json is not None:
            self.sideload = True
            payload = sideload_json
        else:
            # get keyboard identification
            data = self.usb_send(self.dev, struct.pack("BB", CMD_VIA_VIAL_PREFIX, CMD_VIAL_GET_KEYBOARD_ID), retries=20)
            self.vial_protocol, self.keyboard_id = struct.unpack("<IQ", data[0:12])

            # get the size
            data = self.usb_send(self.dev, struct.pack("BB", CMD_VIA_VIAL_PREFIX, CMD_VIAL_GET_SIZE), retries=20)
            sz = struct.unpack("<I", data[0:4])[0]

            # get the payload
            payload = b""
            block = 0
            while sz > 0:
                data = self.usb_send(self.dev, struct.pack("<BBI", CMD_VIA_VIAL_PREFIX, CMD_VIAL_GET_DEFINITION, block),
                                     retries=20)
                if sz < MSG_LEN:
                    data = data[:sz]
                payload += data
                block += 1
                sz -= MSG_LEN

            payload = json.loads(lzma.decompress(payload))

        self.check_protocol_version()

        self.definition = payload

        if "vial" in payload:
            vial = payload["vial"]
            self.vibl = vial.get("vibl", False)
            self.midi = vial.get("midi", None)

        self.layout_labels = payload["layouts"].get("labels")

        self.rows = payload["matrix"]["rows"]
        self.cols = payload["matrix"]["cols"]

        self.custom_keycodes = payload.get("customKeycodes", None)

        serial = KleSerial()
        kb = serial.deserialize(payload["layouts"]["keymap"])

        self.keys = []
        self.encoders = []

        for key in kb.keys:
            key.row = key.col = None
            key.encoder_idx = key.encoder_dir = None
            if key.labels[4] == "e":
                idx, direction = key.labels[0].split(",")
                idx, direction = int(idx), int(direction)
                key.encoder_idx = idx
                key.encoder_dir = direction
                self.encoderpos[idx] = True
                self.encoder_count = max(self.encoder_count, idx + 1)
                self.encoders.append(key)
            elif key.decal or (key.labels[0] and "," in key.labels[0]):
                row, col = 0, 0
                if key.labels[0] and "," in key.labels[0]:
                    row, col = key.labels[0].split(",")
                    row, col = int(row), int(col)
                key.row = row
                key.col = col
                self.rowcol[(row, col)] = True
                self.keys.append(key)

            # bottom right corner determines layout index and option in this layout
            key.layout_index = -1
            key.layout_option = -1
            if key.labels[8]:
                idx, opt = key.labels[8].split(",")
                key.layout_index, key.layout_option = int(idx), int(opt)

    def reload_keymap(self):
        """ Load current key mapping from the keyboard """

        keymap = b""
        # calculate what the size of keymap will be and retrieve the entire binary buffer
        size = self.layers * self.rows * self.cols * 2
        for x in range(0, size, BUFFER_FETCH_CHUNK):
            offset = x
            sz = min(size - offset, BUFFER_FETCH_CHUNK)
            data = self.usb_send(self.dev, struct.pack(">BHB", CMD_VIA_KEYMAP_GET_BUFFER, offset, sz), retries=20)
            keymap += data[4:4+sz]

        for layer in range(self.layers):
            for row, col in self.rowcol.keys():
                if row >= self.rows or col >= self.cols:
                    raise RuntimeError("malformed vial.json, key references {},{} but matrix declares rows={} cols={}"
                                       .format(row, col, self.rows, self.cols))
                # determine where this (layer, row, col) will be located in keymap array
                offset = layer * self.rows * self.cols * 2 + row * self.cols * 2 + col * 2
                keycode = Keycode.serialize(struct.unpack(">H", keymap[offset:offset+2])[0])
                self.layout[(layer, row, col)] = keycode

        for layer in range(self.layers):
            for idx in self.encoderpos:
                data = self.usb_send(self.dev, struct.pack("BBBB", CMD_VIA_VIAL_PREFIX, CMD_VIAL_GET_ENCODER, layer, idx),
                                     retries=20)
                self.encoder_layout[(layer, idx, 0)] = Keycode.serialize(struct.unpack(">H", data[0:2])[0])
                self.encoder_layout[(layer, idx, 1)] = Keycode.serialize(struct.unpack(">H", data[2:4])[0])

        if self.layout_labels:
            data = self.usb_send(self.dev, struct.pack("BB", CMD_VIA_GET_KEYBOARD_VALUE, VIA_LAYOUT_OPTIONS),
                                 retries=20)
            self.layout_options = struct.unpack(">I", data[2:6])[0]

    def reload_persistent_rgb(self):
        """
            Reload RGB properties which are slow, and do not change while keyboard is plugged in
            e.g. VialRGB supported effects list
        """

        if "lighting" in self.definition:
            self.lighting_qmk_rgblight = self.definition["lighting"] in ["qmk_rgblight", "qmk_backlight_rgblight"]
            self.lighting_qmk_backlight = self.definition["lighting"] in ["qmk_backlight", "qmk_backlight_rgblight"]
            self.lighting_vialrgb = self.definition["lighting"] == "vialrgb"

        if self.lighting_vialrgb:
            data = self.usb_send(self.dev, struct.pack("BB", CMD_VIA_LIGHTING_GET_VALUE, VIALRGB_GET_INFO),
                                 retries=20)[2:]
            self.rgb_version = data[0] | (data[1] << 8)
            if self.rgb_version != 1:
                raise RuntimeError("Unsupported VialRGB protocol ({}), update your Vial version to latest"
                                   .format(self.rgb_version))
            self.rgb_maximum_brightness = data[2]

            self.rgb_supported_effects = {0}
            max_effect = 0
            while max_effect < 0xFFFF:
                data = self.usb_send(self.dev, struct.pack("<BBH", CMD_VIA_LIGHTING_GET_VALUE, VIALRGB_GET_SUPPORTED,
                                                           max_effect))[2:]
                for x in range(0, len(data), 2):
                    value = int.from_bytes(data[x:x+2], byteorder="little")
                    if value != 0xFFFF:
                        self.rgb_supported_effects.add(value)
                    max_effect = max(max_effect, value)

            if self.rgb_supported_effects & {1, 45}:  # Direct Control or Customise
                self.reload_vialrgb_direct_leds()
                try:
                    self.reload_vialrgb_indicator_config()
                except Exception:
                    pass
                try:
                    self.reload_trackpad_settings()
                    self.reload_trackpad_layers()
                except Exception:
                    pass
                try:
                    self.reload_oled_config()
                except Exception:
                    pass

    def reload_rgb(self):
        if self.lighting_qmk_rgblight:
            self.underglow_brightness = self.usb_send(
                self.dev, struct.pack(">BB", CMD_VIA_LIGHTING_GET_VALUE, QMK_RGBLIGHT_BRIGHTNESS), retries=20)[2]
            self.underglow_effect = self.usb_send(
                self.dev, struct.pack(">BB", CMD_VIA_LIGHTING_GET_VALUE, QMK_RGBLIGHT_EFFECT), retries=20)[2]
            self.underglow_effect_speed = self.usb_send(
                self.dev, struct.pack(">BB", CMD_VIA_LIGHTING_GET_VALUE, QMK_RGBLIGHT_EFFECT_SPEED), retries=20)[2]
            color = self.usb_send(
                self.dev, struct.pack(">BB", CMD_VIA_LIGHTING_GET_VALUE, QMK_RGBLIGHT_COLOR), retries=20)[2:4]
            # hue, sat
            self.underglow_color = (color[0], color[1])

        if self.lighting_qmk_backlight:
            self.backlight_brightness = self.usb_send(
                self.dev, struct.pack(">BB", CMD_VIA_LIGHTING_GET_VALUE, QMK_BACKLIGHT_BRIGHTNESS), retries=20)[2]
            self.backlight_effect = self.usb_send(
                self.dev, struct.pack(">BB", CMD_VIA_LIGHTING_GET_VALUE, QMK_BACKLIGHT_EFFECT), retries=20)[2]

        if self.lighting_vialrgb:
            data = self.usb_send(self.dev, struct.pack("BB", CMD_VIA_LIGHTING_GET_VALUE, VIALRGB_GET_MODE),
                                 retries=20)[2:]
            self.rgb_mode = int.from_bytes(data[0:2], byteorder="little")
            self.rgb_speed = data[2]
            self.rgb_hsv = (data[3], data[4], data[5])
            try:
                pdata = self.usb_send(self.dev, struct.pack("BB", CMD_VIA_LIGHTING_GET_VALUE,
                                                            VIALRGB_GET_POWER_SETTINGS), retries=20)[2:]
                self.sleep_timeout_min = max(1, min(30, pdata[0] if len(pdata) else 1))
            except Exception:
                pass

    def reload_settings(self):
        self.settings = dict()
        self.supported_settings = set()
        if self.vial_protocol < VIAL_PROTOCOL_QMK_SETTINGS:
            return
        cur = 0
        while cur != 0xFFFF:
            data = self.usb_send(self.dev, struct.pack("<BBH", CMD_VIA_VIAL_PREFIX, CMD_VIAL_QMK_SETTINGS_QUERY, cur),
                                 retries=20)
            for x in range(0, len(data), 2):
                qsid = int.from_bytes(data[x:x+2], byteorder="little")
                cur = max(cur, qsid)
                if qsid != 0xFFFF:
                    self.supported_settings.add(qsid)

        for qsid in self.supported_settings:
            from editor.qmk_settings import QmkSettings

            if not QmkSettings.is_qsid_supported(qsid):
                continue

            data = self.usb_send(self.dev, struct.pack("<BBH", CMD_VIA_VIAL_PREFIX, CMD_VIAL_QMK_SETTINGS_GET, qsid),
                                 retries=20)
            if data[0] == 0:
                self.settings[qsid] = QmkSettings.qsid_deserialize(qsid, data[1:])

    def set_key(self, layer, row, col, code):
        key = (layer, row, col)
        if self.layout[key] != code:
            if code == RESET_KEYCODE:
                Unlocker.unlock(self)

            self.usb_send(self.dev, struct.pack(">BBBBH", CMD_VIA_SET_KEYCODE, layer, row, col,
                                                Keycode.deserialize(code)), retries=20)
            self.layout[key] = code

    def set_encoder(self, layer, index, direction, code):
        key = (layer, index, direction)
        if self.encoder_layout[key] != code:
            if code == RESET_KEYCODE:
                Unlocker.unlock(self)

            self.usb_send(self.dev, struct.pack(">BBBBBH", CMD_VIA_VIAL_PREFIX, CMD_VIAL_SET_ENCODER,
                                                layer, index, direction, Keycode.deserialize(code)), retries=20)
            self.encoder_layout[key] = code

    def set_layout_options(self, options):
        if self.layout_options != -1 and self.layout_options != options:
            self.layout_options = options
            self.usb_send(self.dev, struct.pack(">BBI", CMD_VIA_SET_KEYBOARD_VALUE, VIA_LAYOUT_OPTIONS, options),
                          retries=20)

    def set_qmk_rgblight_brightness(self, value):
        self.underglow_brightness = value
        self.usb_send(self.dev, struct.pack(">BBB", CMD_VIA_LIGHTING_SET_VALUE, QMK_RGBLIGHT_BRIGHTNESS, value),
                      retries=20)

    def set_qmk_rgblight_effect(self, index):
        self.underglow_effect = index
        self.usb_send(self.dev, struct.pack(">BBB", CMD_VIA_LIGHTING_SET_VALUE, QMK_RGBLIGHT_EFFECT, index),
                      retries=20)

    def set_qmk_rgblight_effect_speed(self, value):
        self.underglow_effect_speed = value
        self.usb_send(self.dev, struct.pack(">BBB", CMD_VIA_LIGHTING_SET_VALUE, QMK_RGBLIGHT_EFFECT_SPEED, value),
                      retries=20)

    def set_qmk_rgblight_color(self, h, s, v):
        self.set_qmk_rgblight_brightness(v)
        self.usb_send(self.dev, struct.pack(">BBBB", CMD_VIA_LIGHTING_SET_VALUE, QMK_RGBLIGHT_COLOR, h, s))

    def set_qmk_backlight_brightness(self, value):
        self.backlight_brightness = value
        self.usb_send(self.dev, struct.pack(">BBB", CMD_VIA_LIGHTING_SET_VALUE, QMK_BACKLIGHT_BRIGHTNESS, value))

    def set_qmk_backlight_effect(self, value):
        self.backlight_effect = value
        self.usb_send(self.dev, struct.pack(">BBB", CMD_VIA_LIGHTING_SET_VALUE, QMK_BACKLIGHT_EFFECT, value))

    def save_rgb(self):
        self.usb_send(self.dev, struct.pack(">B", CMD_VIA_LIGHTING_SAVE), retries=20)

    def save_layout(self):
        """ Serializes current layout to a binary """

        data = {"version": 1, "uid": self.keyboard_id}

        layout = []
        for l in range(self.layers):
            layer = []
            layout.append(layer)
            for r in range(self.rows):
                row = []
                layer.append(row)
                for c in range(self.cols):
                    val = self.layout.get((l, r, c), -1)
                    row.append(val)

        encoder_layout = []
        for l in range(self.layers):
            layer = []
            for e in range(self.encoder_count):
                cw = (l, e, 0)
                ccw = (l, e, 1)
                layer.append([self.encoder_layout.get(cw, -1),
                              self.encoder_layout.get(ccw, -1)])
            encoder_layout.append(layer)

        data["layout"] = layout
        data["encoder_layout"] = encoder_layout
        data["layout_options"] = self.layout_options
        data["macro"] = self.save_macro()
        data["vial_protocol"] = self.vial_protocol
        data["via_protocol"] = self.via_protocol
        data["tap_dance"] = self.save_tap_dance()
        data["combo"] = self.save_combo()
        data["key_override"] = self.save_key_override()
        data["alt_repeat_key"] = self.save_alt_repeat_key()
        data["settings"] = self.settings

        if self.oled_supported:
            data["oled_config"] = {
                "row1": self.oled_config.get("row1", ""),
                "layer_names": list(self.oled_config.get("layer_names", [])),
            }

        if self.lighting_vialrgb:
            data["rgb_mode"] = self.rgb_mode
            data["rgb_speed"] = self.rgb_speed
            data["rgb_hsv"] = list(self.rgb_hsv)

        if getattr(self, 'vialrgb_direct_supported', False) and self.vialrgb_direct_colors:
            data["vialrgb_direct_colors"] = [list(c) for c in self.vialrgb_direct_colors]

        if getattr(self, 'indicator_supported', False):
            data["indicator_assignments"] = [
                {'leds': list(a['leds']), 'r': a['r'], 'g': a['g'], 'b': a['b'],
                 # JSON object keys are strings; restore converts back to int
                 'led_colors': {str(k): list(v) for k, v in a.get('led_colors', {}).items()}}
                for a in self.indicator_assignments
            ]

        if getattr(self, 'trackpad_supported', False):
            data["trackpad_settings"] = dict(self.trackpad_settings)
            data["trackpad_layers"] = dict(self.trackpad_layers)

        return json.dumps(data).encode("utf-8")

    def restore_layout(self, data):
        """ Restores saved layout """

        data = json.loads(data.decode("utf-8"))

        # restore keymap
        for l, layer in enumerate(data["layout"]):
            for r, row in enumerate(layer):
                for c, code in enumerate(row):
                    if (l, r, c) in self.layout:
                        self.set_key(l, r, c, Keycode.serialize(Keycode.deserialize(code)))

        # restore encoders
        for l, layer in enumerate(data["encoder_layout"]):
            for e, encoder in enumerate(layer):
                self.set_encoder(l, e, 0, Keycode.serialize(Keycode.deserialize(encoder[0])))
                self.set_encoder(l, e, 1, Keycode.serialize(Keycode.deserialize(encoder[1])))

        self.set_layout_options(data["layout_options"])
        self.restore_macros(data.get("macro"))

        self.restore_tap_dance(data.get("tap_dance", []))
        self.restore_combo(data.get("combo", []))
        self.restore_key_override(data.get("key_override", []))
        self.restore_alt_repeat_key(data.get("alt_repeat_key", []))

        for qsid, value in data.get("settings", dict()).items():
            from editor.qmk_settings import QmkSettings

            qsid = int(qsid)
            if QmkSettings.is_qsid_supported(qsid):
                self.qmk_settings_set(qsid, value)

        if self.oled_supported and "oled_config" in data:
            oled = data["oled_config"]
            self.set_oled_config(
                oled.get("row1", ""),
                oled.get("layer_names", []),
            )

        if getattr(self, 'vialrgb_direct_supported', False) and "vialrgb_direct_colors" in data:
            saved = data["vialrgb_direct_colors"]
            if len(saved) == self.vialrgb_num_leds:
                colors = [tuple(c) for c in saved]
                self.vialrgb_direct_colors = colors
                self.set_vialrgb_direct_fastset(0, colors)

        if self.lighting_vialrgb and "rgb_mode" in data:
            self.rgb_mode = data["rgb_mode"]
            self.rgb_speed = data.get("rgb_speed", self.rgb_speed)
            hsv = data.get("rgb_hsv")
            if hsv and len(hsv) == 3:
                self.rgb_hsv = tuple(hsv)
            self._vialrgb_set_mode()

        if getattr(self, 'indicator_supported', False) and "indicator_assignments" in data:
            saved = data["indicator_assignments"]
            assignments = list(self.indicator_assignments)
            for i, a in enumerate(saved[:10]):
                assignments[i] = {
                    'leds': list(a.get('leds', [])),
                    'r': a.get('r', 0),
                    'g': a.get('g', 0),
                    'b': a.get('b', 0),
                    'led_colors': {int(k): tuple(v) for k, v in a.get('led_colors', {}).items()},
                }
            self.indicator_assignments = assignments
            self.set_vialrgb_indicator_leds(assignments)
            self.set_vialrgb_indicator_colors(assignments)
            self.set_vialrgb_indicator_led_colors(assignments)

        if getattr(self, 'trackpad_supported', False) and "trackpad_settings" in data:
            self.set_trackpad_settings(data["trackpad_settings"])
        if getattr(self, 'trackpad_supported', False) and "trackpad_layers" in data:
            self.set_trackpad_layers(data["trackpad_layers"])

        # Persist the restored lighting to EEPROM (mode via eeconfig flush,
        # per-key colors and indicators via vialrgb_save_user) so it survives
        # a reboot without the user pressing Save in the Lighting tab.
        if self.lighting_vialrgb and ("rgb_mode" in data or "vialrgb_direct_colors" in data
                                      or "indicator_assignments" in data):
            self.save_rgb()

    def reset(self):
        self.usb_send(self.dev, struct.pack("B", 0xB))
        self.dev.close()

    def reset_keymap(self):
        """Restore the firmware's default keymap and re-read it. Only layers/encoders."""
        from protocol.constants import CMD_VIA_DYNAMIC_KEYMAP_RESET
        self.usb_send(self.dev, struct.pack("B", CMD_VIA_DYNAMIC_KEYMAP_RESET), retries=20)
        self.reload_keymap()

    def get_uid(self):
        """ Retrieve UID from the keyboard, explicitly sending a query packet """
        data = self.usb_send(self.dev, struct.pack("BB", CMD_VIA_VIAL_PREFIX, CMD_VIAL_GET_KEYBOARD_ID), retries=20)
        keyboard_id = data[4:12]
        return keyboard_id

    def get_unlock_status(self, retries=20):
        # VIA keyboards are always unlocked
        if self.vial_protocol < 0:
            return 1

        data = self.usb_send(self.dev, struct.pack("BB", CMD_VIA_VIAL_PREFIX, CMD_VIAL_GET_UNLOCK_STATUS),
                             retries=retries)
        return data[0]

    def get_unlock_in_progress(self):
        # VIA keyboards are never being unlocked
        if self.vial_protocol < 0:
            return 0

        data = self.usb_send(self.dev, struct.pack("BB", CMD_VIA_VIAL_PREFIX, CMD_VIAL_GET_UNLOCK_STATUS), retries=20)
        return data[1]

    def get_unlock_keys(self):
        """ Return keys users have to hold to unlock the keyboard as a list of rowcols """

        # VIA keyboards don't have unlock keys
        if self.vial_protocol < 0:
            return []

        data = self.usb_send(self.dev, struct.pack("BB", CMD_VIA_VIAL_PREFIX, CMD_VIAL_GET_UNLOCK_STATUS), retries=20)
        rowcol = []
        for x in range(15):
            row = data[2 + x * 2]
            col = data[3 + x * 2]
            if row != 255 and col != 255:
                rowcol.append((row, col))
        return rowcol

    def unlock_start(self):
        if self.vial_protocol < 0:
            return

        self.usb_send(self.dev, struct.pack("BB", CMD_VIA_VIAL_PREFIX, CMD_VIAL_UNLOCK_START), retries=20)

    def unlock_poll(self):
        if self.vial_protocol < 0:
            return b""

        data = self.usb_send(self.dev, struct.pack("BB", CMD_VIA_VIAL_PREFIX, CMD_VIAL_UNLOCK_POLL), retries=20)
        return data

    def lock(self):
        if self.vial_protocol < 0:
            return

        self.usb_send(self.dev, struct.pack("BB", CMD_VIA_VIAL_PREFIX, CMD_VIAL_LOCK), retries=20)

    def get_encoder_events(self):
        """Knob turn counters for the matrix tester (VIALRGB 0x54): list of (ccw, cw) per
        encoder, wrapping uint8. None when the firmware does not have it (it echoes the
        request); probed once, then not asked again."""
        if self.encoder_events_supported is False or not getattr(self, 'lighting_vialrgb', False):
            return None
        from protocol.constants import VIALRGB_GET_ENCODER_EVENTS, VIALRGB_ENCODER_EVENTS_MAGIC
        data = self.usb_send(self.dev, struct.pack("BB", CMD_VIA_LIGHTING_GET_VALUE,
                                                   VIALRGB_GET_ENCODER_EVENTS), retries=3)[2:]
        if len(data) < 2 or data[0] != VIALRGB_ENCODER_EVENTS_MAGIC:
            self.encoder_events_supported = False
            return None
        self.encoder_events_supported = True
        n = min(data[1], (len(data) - 2) // 2)
        return [(data[2 + i * 2], data[3 + i * 2]) for i in range(n)]

    def matrix_poll(self):
        if self.via_protocol < 0:
            return

        data = self.usb_send(self.dev, struct.pack("BB", CMD_VIA_GET_KEYBOARD_VALUE, VIA_SWITCH_MATRIX_STATE),
                             retries=3)
        return data

    def qmk_settings_set(self, qsid, value):
        from editor.qmk_settings import QmkSettings
        self.settings[qsid] = value
        data = self.usb_send(self.dev, struct.pack("<BBH", CMD_VIA_VIAL_PREFIX, CMD_VIAL_QMK_SETTINGS_SET, qsid)
                             + QmkSettings.qsid_serialize(qsid, value),
                             retries=20)
        return data[0]

    def qmk_settings_reset(self):
        self.usb_send(self.dev, struct.pack("BB", CMD_VIA_VIAL_PREFIX, CMD_VIAL_QMK_SETTINGS_RESET))

    def _vialrgb_set_mode(self):
        self.usb_send(self.dev, struct.pack("BBHBBBB", CMD_VIA_LIGHTING_SET_VALUE, VIALRGB_SET_MODE,
                                            self.rgb_mode, self.rgb_speed,
                                            self.rgb_hsv[0], self.rgb_hsv[1], self.rgb_hsv[2]))

    def set_vialrgb_brightness(self, value):
        self.rgb_hsv = (self.rgb_hsv[0], self.rgb_hsv[1], value)
        self._vialrgb_set_mode()

    def set_vialrgb_speed(self, value):
        self.rgb_speed = value
        self._vialrgb_set_mode()

    def set_vialrgb_mode(self, value):
        self.rgb_mode = value
        self._vialrgb_set_mode()

    def set_vialrgb_color(self, h, s, v):
        self.rgb_hsv = (h, s, v)
        self._vialrgb_set_mode()

    def set_power_settings(self, minutes):
        """Set the shared OLED+RGB sleep timeout (whole minutes, 1-30)."""
        minutes = max(1, min(30, int(minutes)))
        self.sleep_timeout_min = minutes
        self.usb_send(self.dev, struct.pack("BBB", CMD_VIA_LIGHTING_SET_VALUE,
                                            VIALRGB_SET_POWER_SETTINGS, minutes), retries=20)

    def reload_vialrgb_direct_leds(self):
        """Fetch LED count and per-LED matrix positions from the keyboard."""
        data = self.usb_send(self.dev, struct.pack("BB", CMD_VIA_LIGHTING_GET_VALUE,
                                                   VIALRGB_GET_NUMBER_LEDS), retries=20)[2:]
        self.vialrgb_num_leds = data[0] | (data[1] << 8)
        if self.vialrgb_num_leds == 0:
            return
        self.vialrgb_direct_colors = [(0, 0, 0)] * self.vialrgb_num_leds
        self.vialrgb_led_map = {}
        self.vialrgb_unkeyed_leds = []
        self.vialrgb_led_info = []
        for led_idx in range(self.vialrgb_num_leds):
            data = self.usb_send(self.dev, struct.pack("<BBH", CMD_VIA_LIGHTING_GET_VALUE,
                                                       VIALRGB_GET_LED_INFO, led_idx), retries=20)[2:]
            # x, y (0-224 / 0-64 g_led_config space), flags, then matrix row, col
            self.vialrgb_led_info.append((data[0], data[1], data[2]))
            row, col = data[3], data[4]
            if row != 0xFF and col != 0xFF:
                self.vialrgb_led_map[(row, col)] = led_idx
            else:
                # Not under a key (underglow): the RGB tabs draw these as extra
                # LED-only widgets so they can be coloured / used as indicators
                self.vialrgb_unkeyed_leds.append(led_idx)
        self.vialrgb_direct_supported = True
        self.reload_vialrgb_direct_colors()

    def reload_vialrgb_direct_colors(self):
        """Read back the current per-key Customise colors from the keyboard (0x47).

        Firmware without this command echoes the request back, which parses as
        count=0 on the first packet and leaves the all-black defaults in place.
        """
        led = 0
        while led < self.vialrgb_num_leds:
            data = self.usb_send(self.dev, struct.pack("<BBH", CMD_VIA_LIGHTING_GET_VALUE,
                                                       VIALRGB_GET_DIRECT_COLORS, led), retries=20)[2:]
            count = data[0]
            if count == 0 or len(data) < 1 + count * 3:
                break
            for x in range(count):
                if led + x < self.vialrgb_num_leds:
                    self.vialrgb_direct_colors[led + x] = (data[1 + x * 3],
                                                           data[2 + x * 3],
                                                           data[3 + x * 3])
            led += count

    def set_vialrgb_direct_fastset(self, first_idx, hsv_list):
        """Send per-LED HSV colors to the keyboard. hsv_list is [(H, S, V), ...]."""
        LEDS_PER_PKT = 9  # 27 bytes / 3 bytes per LED; firmware limit per packet
        for offset in range(0, len(hsv_list), LEDS_PER_PKT):
            batch = hsv_list[offset:offset + LEDS_PER_PKT]
            payload = struct.pack("<BBH", CMD_VIA_LIGHTING_SET_VALUE,
                                  VIALRGB_DIRECT_FASTSET, first_idx + offset)
            payload += struct.pack("B", len(batch))
            for h, s, v in batch:
                payload += struct.pack("BBB", h, s, v)
            self.usb_send(self.dev, payload, retries=20)

    def set_vialrgb_key_color(self, row, col, h, s, v):
        """Set the direct RGB color for a single key by matrix position."""
        led = self.vialrgb_led_map.get((row, col))
        if led is not None:
            self.vialrgb_direct_colors[led] = (h, s, v)
            self.set_vialrgb_direct_fastset(led, [(h, s, v)])

    def reload_vialrgb_indicator_config(self):
        """Fetch per-role indicator bitmasks and colors from the keyboard.

        One GET request per role (0x45 with role_idx). Response: 8-byte LE uint64 mask.
        """
        for role_idx in range(10):
            data = self.usb_send(self.dev,
                                 struct.pack("BBB", CMD_VIA_LIGHTING_GET_VALUE,
                                             VIALRGB_GET_INDICATOR_LEDS, role_idx),
                                 retries=20)[2:]
            mask_bytes = (data + b'\x00' * 8)[:8]
            mask = int.from_bytes(mask_bytes, 'little')
            self.indicator_assignments[role_idx]['leds'] = [
                i for i in range(min(self.vialrgb_num_leds, 64)) if (mask >> i) & 1
            ]
        # GET colors (0x46): 30 bytes, [r,g,b] per role (unchanged)
        data = self.usb_send(self.dev, struct.pack("BB", CMD_VIA_LIGHTING_GET_VALUE,
                                                   VIALRGB_GET_INDICATOR_COLORS), retries=20)[2:]
        for i in range(10):
            base = i * 3
            if base + 2 < len(data):
                self.indicator_assignments[i]['r'] = data[base]
                self.indicator_assignments[i]['g'] = data[base + 1]
                self.indicator_assignments[i]['b'] = data[base + 2]
        self.reload_vialrgb_indicator_led_colors()
        self.indicator_supported = True

    def reload_vialrgb_indicator_led_colors(self):
        """Fetch per-LED indicator colours (0x48) into assignments[i]['led_colors'].

        Old firmware echoes the GET, so the first reply carries the role index rather than
        VIALRGB_INDICATOR_LED_COLORS_MAGIC; then every LED of a role shows the role colour.
        """
        from protocol.constants import VIALRGB_GET_INDICATOR_LED_COLORS, \
            VIALRGB_INDICATOR_LED_COLORS_MAGIC, VIALRGB_INDICATOR_LED_COLORS_MAX

        def read_chunk(role, first):
            data = self.usb_send(self.dev, struct.pack("BBBB", CMD_VIA_LIGHTING_GET_VALUE,
                                                       VIALRGB_GET_INDICATOR_LED_COLORS, role, first),
                                 retries=20)[2:]
            if len(data) < 2 or data[0] != VIALRGB_INDICATOR_LED_COLORS_MAGIC:
                return None
            count = min(data[1], VIALRGB_INDICATOR_LED_COLORS_MAX)
            return [tuple(data[2 + n * 3: 5 + n * 3]) for n in range(count)]

        for a in self.indicator_assignments:
            a['led_colors'] = {}
        self.indicator_led_colors_supported = read_chunk(0, 0) is not None
        if not self.indicator_led_colors_supported:
            return
        if self.vialrgb_num_leds > 64:
            # LEDs 64.. live in a second mask page (0x45 with role | MASK_HI), which only
            # firmware with per-LED colours understands -- hence read only now.
            from protocol.constants import VIALRGB_INDICATOR_MASK_HI
            for role, a in enumerate(self.indicator_assignments):
                data = self.usb_send(self.dev, struct.pack("BBB", CMD_VIA_LIGHTING_GET_VALUE,
                                                           VIALRGB_GET_INDICATOR_LEDS,
                                                           role | VIALRGB_INDICATOR_MASK_HI),
                                     retries=20)[2:]
                hi = int.from_bytes((data + b'\x00' * 8)[:8], 'little')
                a['leds'] = [l for l in a['leds'] if l < 64] + [
                    64 + i for i in range(min(self.vialrgb_num_leds - 64, 64)) if (hi >> i) & 1]
        step = VIALRGB_INDICATOR_LED_COLORS_MAX
        for role, a in enumerate(self.indicator_assignments):
            # only the chunks that hold this role's LEDs
            for first in sorted({led - led % step for led in a['leds']}):
                colors = read_chunk(role, first)
                if colors is None:
                    continue
                for n, rgb in enumerate(colors):
                    if first + n in a['leds'] and len(rgb) == 3:
                        a['led_colors'][first + n] = rgb

    def set_vialrgb_indicator_leds(self, assignments):
        """Send per-role bitmasks to the keyboard (one SET request per role)."""
        hi_page = self.indicator_led_colors_supported and self.vialrgb_num_leds > 64
        for role_idx in range(10):
            leds = assignments[role_idx].get('leds', [])
            mask = 0
            for led in leds:
                if led < 64:
                    mask |= (1 << led)
            mask_bytes = mask.to_bytes(8, 'little')
            self.usb_send(self.dev,
                          struct.pack("BBB", CMD_VIA_LIGHTING_SET_VALUE,
                                      VIALRGB_SET_INDICATOR_LEDS, role_idx) + mask_bytes,
                          retries=20)
            if hi_page:
                # LEDs 64.. (72-LED boards): second page, role | MASK_HI
                from protocol.constants import VIALRGB_INDICATOR_MASK_HI
                hi = 0
                for led in leds:
                    if 64 <= led < 128:
                        hi |= (1 << (led - 64))
                self.usb_send(self.dev,
                              struct.pack("BBB", CMD_VIA_LIGHTING_SET_VALUE, VIALRGB_SET_INDICATOR_LEDS,
                                          role_idx | VIALRGB_INDICATOR_MASK_HI) + hi.to_bytes(8, 'little'),
                              retries=20)
            limit = 128 if hi_page else 64
            self.indicator_assignments[role_idx]['leds'] = [l for l in leds if l < limit]

    def set_vialrgb_indicator_colors(self, colors_per_role):
        """Send 30 bytes of [r,g,b] per role to the keyboard."""
        msg = bytearray([CMD_VIA_LIGHTING_SET_VALUE, VIALRGB_SET_INDICATOR_COLORS])
        for i in range(10):
            if i < len(colors_per_role):
                c = colors_per_role[i]
                msg += bytes([c['r'], c['g'], c['b']])
            else:
                msg += b'\x00\x00\x00'
        self.usb_send(self.dev, bytes(msg), retries=20)
        for i, c in enumerate(colors_per_role[:10]):
            self.indicator_assignments[i]['r'] = c['r']
            self.indicator_assignments[i]['g'] = c['g']
            self.indicator_assignments[i]['b'] = c['b']

    def set_vialrgb_indicator_led_colors(self, assignments):
        """Send per-LED indicator colours (0x48). Call after set_vialrgb_indicator_colors():
        firmware repaints each role in its role colour on a 0x46 SET.

        assignments[i]['led_colors'] maps LED index -> (r, g, b); LEDs without an entry
        get the role colour. Only chunks holding the role's LEDs are sent.
        """
        if not self.indicator_led_colors_supported:
            return
        from protocol.constants import VIALRGB_SET_INDICATOR_LED_COLORS, VIALRGB_INDICATOR_LED_COLORS_MAX
        step = VIALRGB_INDICATOR_LED_COLORS_MAX
        n_leds = min(self.vialrgb_num_leds, 255)
        for role, a in enumerate(assignments[:10]):
            leds = [l for l in a.get('leds', []) if l < n_leds]
            per_led = {int(k): tuple(v) for k, v in a.get('led_colors', {}).items()}
            role_rgb = (a['r'], a['g'], a['b'])
            for first in sorted({led - led % step for led in leds}):
                count = min(step, n_leds - first)
                payload = struct.pack("BBBBB", CMD_VIA_LIGHTING_SET_VALUE,
                                      VIALRGB_SET_INDICATOR_LED_COLORS, role, first, count)
                for led in range(first, first + count):
                    payload += bytes(per_led.get(led, role_rgb))
                self.usb_send(self.dev, payload, retries=20)
            self.indicator_assignments[role]['led_colors'] = {l: per_led.get(l, role_rgb) for l in leds}

    def reload_trackpad_settings(self):
        """Fetch trackpad settings from the keyboard (sub-ID 0x50)."""
        data = self.usb_send(self.dev, struct.pack("BB", CMD_VIA_LIGHTING_GET_VALUE,
                                                   VIALRGB_GET_TRACKPAD_SETTINGS), retries=20)[2:]
        def _b(i, default=0): return data[i] if len(data) > i else default
        self.trackpad_settings = {
            'cursor_dpi':           max(1, min(6, _b(0, 3))),
            'scroll_speed':         max(1, min(8, _b(1, 4))),
            'scroll_invert_v':      bool(_b(2)),
            'scroll_invert_h':      bool(_b(3)),
            'zoom_enabled':         bool(_b(4, 1)),
            'trackpad_enabled':     bool(_b(5, 1)),
            'sniper_scale':         max(1, min(6, _b(6, 1))),
            'taps_as_clicks':       bool(_b(7)),
            'sniper_modifier_mask': _b(8),
        }
        self.trackpad_supported = True

    def set_trackpad_settings(self, settings):
        """Push trackpad settings to the keyboard (sub-ID 0x50) and save locally."""
        msg = struct.pack("BBBBBBBBBBB",
                          CMD_VIA_LIGHTING_SET_VALUE, VIALRGB_SET_TRACKPAD_SETTINGS,
                          settings.get('cursor_dpi', 3),
                          settings.get('scroll_speed', 4),
                          1 if settings.get('scroll_invert_v') else 0,
                          1 if settings.get('scroll_invert_h') else 0,
                          1 if settings.get('zoom_enabled', True) else 0,
                          1 if settings.get('trackpad_enabled', True) else 0,
                          settings.get('sniper_scale', 1),
                          1 if settings.get('taps_as_clicks') else 0,
                          settings.get('sniper_modifier_mask', 0))
        self.usb_send(self.dev, msg, retries=20)
        self.trackpad_settings = dict(settings)

    def reload_trackpad_layers(self):
        """Fetch trackpad layer behaviour bitmasks (sub-ID 0x51)."""
        data = self.usb_send(self.dev, struct.pack("BB", CMD_VIA_LIGHTING_GET_VALUE,
                                                   VIALRGB_GET_TRACKPAD_LAYERS), retries=20)[2:]
        def _w(i): return (data[i] | (data[i+1] << 8)) if len(data) > i+1 else 0
        self.trackpad_layers = {
            'scroll': _w(0),
            'swipe2': _w(2),
            'swipe3': _w(4),
        }

    def set_trackpad_layers(self, layers):
        """Push trackpad layer bitmasks to the keyboard (sub-ID 0x51)."""
        s = layers.get('scroll', 0)
        s2 = layers.get('swipe2', 0)
        s3 = layers.get('swipe3', 0)
        msg = struct.pack("BBBBBBBB",
                          CMD_VIA_LIGHTING_SET_VALUE, VIALRGB_SET_TRACKPAD_LAYERS,
                          s & 0xFF, (s >> 8) & 0xFF,
                          s2 & 0xFF, (s2 >> 8) & 0xFF,
                          s3 & 0xFF, (s3 >> 8) & 0xFF)
        self.usb_send(self.dev, msg, retries=20)
        self.trackpad_layers = dict(layers)

   
    def reload_oled_config(self):
        """GbrTzT: OLED com suporte a 5 ou 7 caracteres."""
        from protocol.constants import VIALRGB_GET_OLED_CONFIG

        data = self.usb_send(
            self.dev,
            struct.pack("BBB", CMD_VIA_LIGHTING_GET_VALUE,
                        VIALRGB_GET_OLED_CONFIG, 0xFF),
            retries=20
        )

        self.oled_config['row1'] = data[3:8].rstrip(b'\x00').decode('ascii', errors='replace')
        self.oled_name_max_chars = 5

        # Verificar suporte ao OLED de 7 caracteres da V7
        try:
            data = self.usb_send(
                self.dev,
                struct.pack("BB", CMD_VIA_LIGHTING_GET_VALUE, 0x53),
                retries=20
            )
            if len(data) >= 10 and data[2] == 0xA7:
                self.oled_name_max_chars = 7
                self.oled_config['row1'] = data[3:10].split(b'\x00', 1)[0].decode('ascii', errors='replace')
        except Exception:
            pass

        names = []
        for i in range(10):
            data = self.usb_send(
                self.dev,
                struct.pack("BBB", CMD_VIA_LIGHTING_GET_VALUE,
                            VIALRGB_GET_OLED_CONFIG, i),
                retries=20
            )
            names.append(data[3:8].rstrip(b'\x00').decode('ascii', errors='replace'))

        self.oled_config['layer_names'] = names
        self.oled_supported = True


    def set_oled_config(self, row1, layer_names):
        """Push OLED label config to keyboard (sub-ID 0x52), one item per packet."""
        from protocol.constants import VIALRGB_SET_OLED_CONFIG
        def _send(item, name):
            nb = name.encode('ascii', errors='replace')[:5].ljust(5, b'\x00')
            self.usb_send(self.dev,
                          struct.pack("BBB5s", CMD_VIA_LIGHTING_SET_VALUE,
                                      VIALRGB_SET_OLED_CONFIG, item, nb),
                          retries=20)
        _send(0xFF, row1)
        for i, name in enumerate(layer_names[:10]):
            _send(i, name)
        self.oled_config['row1'] = row1
        self.oled_config['layer_names'] = list(layer_names[:10])

        def set_oled_row1(self, name):
        """GbrTzT: enviar nome com ate 7 caracteres na V7."""
        if getattr(self, 'oled_name_max_chars', 5) == 7:
            nb = name.encode('ascii', errors='replace')[:7].ljust(7, b'\x00')
            self.usb_send(
                self.dev,
                struct.pack("BB7s", CMD_VIA_LIGHTING_SET_VALUE, 0x53, nb),
                retries=20
            )
            self.oled_config['row1'] = name[:7]
        else:
            from protocol.constants import VIALRGB_SET_OLED_CONFIG
            nb = name.encode('ascii', errors='replace')[:5].ljust(5, b'\x00')
            self.usb_send(
                self.dev,
                struct.pack("BBB5s", CMD_VIA_LIGHTING_SET_VALUE,
                            VIALRGB_SET_OLED_CONFIG, 0xFF, nb),
                retries=20
            )
            self.oled_config['row1'] = name[:5]

    def set_oled_layer_name(self, layer_idx, name):
        """Push a single layer name to the OLED (layer_idx 0-9)."""
        from protocol.constants import VIALRGB_SET_OLED_CONFIG
        nb = name.encode('ascii', errors='replace')[:5].ljust(5, b'\x00')
        self.usb_send(self.dev,
                      struct.pack("BBB5s", CMD_VIA_LIGHTING_SET_VALUE,
                                  VIALRGB_SET_OLED_CONFIG, layer_idx, nb),
                      retries=20)
        names = self.oled_config.get('layer_names', [''] * 10)
        while len(names) <= layer_idx:
            names.append('')
        names[layer_idx] = name[:5]
        self.oled_config['layer_names'] = names
