# SPDX-License-Identifier: GPL-2.0-or-later
from PyQt5.QtWidgets import QVBoxLayout, QPushButton, QWidget, QHBoxLayout, QLabel, QCheckBox
from PyQt5.QtCore import Qt, QTimer, QSettings

import math
import sys
import time

from editor.basic_editor import BasicEditor
from protocol.constants import VIAL_PROTOCOL_MATRIX_TESTER
from widgets.keyboard_widget import KeyboardWidget
from util import tr, play_sound
from vial_device import VialKeyboard
from unlocker import Unlocker


class MatrixTest(BasicEditor):

    def __init__(self, layout_editor):
        super().__init__()

        self.layout_editor = layout_editor

        self.keyboardWidget = KeyboardWidget(layout_editor)
        self.keyboardWidget.set_enabled(False)

        self.unlock_btn = QPushButton("Unlock")
        self.reset_btn = QPushButton("Reset")

        layout = QVBoxLayout()
        layout.addWidget(self.keyboardWidget)
        layout.setAlignment(self.keyboardWidget, Qt.AlignCenter)

        self.addLayout(layout)

        btn_layout = QHBoxLayout()
        # a tone per registered key, a different one when two or more keys register at once (a short or a
        # ghost); the web page plays them, so the option only exists there
        self.chk_sound = QCheckBox(tr("MatrixTest", "Sound"))
        self.chk_sound.setToolTip(tr("MatrixTest", "Beep when a key registers; a lower double beep when two or "
                                                   "more keys register at the same time"))
        self.chk_sound.setChecked(QSettings("Vial", "Vial").value("matrix_tester_sound", True, bool))
        self.chk_sound.toggled.connect(lambda on: QSettings("Vial", "Vial").setValue("matrix_tester_sound", on))
        self.chk_sound.setVisible(sys.platform == "emscripten")
        btn_layout.addWidget(self.chk_sound)
        btn_layout.addStretch()
        self.unlock_lbl = QLabel(tr("MatrixTest", "Unlock the keyboard before testing:"))
        btn_layout.addWidget(self.unlock_lbl)
        btn_layout.addWidget(self.unlock_btn)
        btn_layout.addWidget(self.reset_btn)
        self.addLayout(btn_layout)

        self.keyboard = None
        self.device = None
        self.polling = False
        self.pressed = set()
        self._unlock_confirmed = False
        self._next_unlock_check = 0.0
        self._last_encoder_poll = 0.0

        self.timer = QTimer()
        self.timer.timeout.connect(self.matrix_poller)

        self.unlock_btn.clicked.connect(self.unlock)
        self.reset_btn.clicked.connect(self.reset_keyboard_widget)

        self.grabber = QWidget()

    def rebuild(self, device):
        super().rebuild(device)
        if self.valid():
            self.keyboard = device.keyboard

            self.keyboardWidget.set_keys(self.keyboard.keys, self.keyboard.encoders)
            self.encoder_last = None      # last knob counters from the firmware (VIALRGB 0x54)
            self.encoder_flash = {}       # (idx, dir) -> time the arrow stops showing pressed
        self.keyboardWidget.setEnabled(self.valid())

    def valid(self):
        # Check if vial protocol is v3 or later
        return isinstance(self.device, VialKeyboard) and \
               (self.device.keyboard and self.device.keyboard.vial_protocol >= VIAL_PROTOCOL_MATRIX_TESTER) and \
               ((self.device.keyboard.cols // 8 + 1) * self.device.keyboard.rows <= 28)

    def reset_keyboard_widget(self):
        # reset keyboard widget
        for w in self.keyboardWidget.widgets:
            w.setPressed(False)
            w.setOn(False)

        self.keyboardWidget.update_layout()
        self.keyboardWidget.update()
        self.keyboardWidget.updateGeometry()

    def matrix_poller(self):
        if not self.valid():
            self.timer.stop()
            return

        # The unlock state changes rarely. Query at 1 s intervals while
        # unlocked, and at 100 ms intervals while waiting for an unlock.
        # Unlike a one-time probe, this notices Security -> Lock as well.
        now = time.monotonic()
        if now >= self._next_unlock_check:
            try:
                unlocked = bool(self.keyboard.get_unlock_status(3))
            except (RuntimeError, ValueError):
                self.timer.stop()
                return

            was_unlocked = self._unlock_confirmed
            self._unlock_confirmed = unlocked
            self._next_unlock_check = now + (1.0 if unlocked else 0.1)

            if was_unlocked and not unlocked:
                self.pressed.clear()
                self.encoder_last = None
                self.encoder_flash.clear()
                for widget in self.keyboardWidget.widgets:
                    widget.setPressed(False)
                self.keyboardWidget.update()

        if not self._unlock_confirmed:
            self.unlock_btn.show()
            self.unlock_lbl.show()
            return

        self.unlock_btn.hide()
        self.unlock_lbl.hide()

        # Get size for matrix
        rows = self.keyboard.rows
        cols = self.keyboard.cols
        # Generate 2d array of matrix
        matrix = [[None] * cols for x in range(rows)]

        # Get matrix data from keyboard
        try:
            data = self.keyboard.matrix_poll()
        except (RuntimeError, ValueError):
            self.timer.stop()
            return

        # Calculate the amount of bytes belong to 1 row, each bit is 1 key, so per 8 keys in a row,
        # a byte is needed for the row.
        row_size = math.ceil(cols / 8)

        for row in range(rows):
            # Make slice of bytes for the row (skip first 2 bytes, they're for VIAL)
            row_data_start = 2 + (row * row_size)
            row_data_end = row_data_start + row_size
            row_data = data[row_data_start:row_data_end]

            # Get each bit representing pressed state for col
            for col in range(cols):
                # row_data is array of bytes, calculate in which byte the col is located
                col_byte = len(row_data) - 1 - math.floor(col / 8)
                # since we select a single byte as slice of byte, mod 8 to get nth pos of byte
                col_mod = (col % 8)
                # write to matrix array
                matrix[row][col] = (row_data[col_byte] >> col_mod) & 1

        # knobs: firmware turn counters (VIALRGB 0x54). A changed counter flashes that
        # knob's arrow as pressed for a moment and marks it tested, like a key.
        # Encoder counters accumulate on the device; reading them every
        # 120 ms retains the ability to detect turns without extra HID I/O
        # on every 20 ms matrix poll. Snapshot at activation avoids stale events.
        counts = None
        now = time.monotonic()
        if now - self._last_encoder_poll >= 0.12:
            self._last_encoder_poll = now
            try:
                counts = self.keyboard.get_encoder_events()
            except (RuntimeError, ValueError):
                counts = None
        knob_turned = False
        visual_changed = False
        if counts is not None:
            last = getattr(self, 'encoder_last', None)
            if last is not None:
                for idx, pair in enumerate(counts):
                    for direction in (0, 1):
                        if idx < len(last) and pair[direction] != last[idx][direction]:
                            self.encoder_flash[(idx, direction)] = now + 0.25
                            knob_turned = True
            self.encoder_last = counts
        flash = getattr(self, 'encoder_flash', {})
        for w in self.keyboardWidget.widgets:
            if getattr(w.desc, 'encoder_idx', None) is not None:
                until = flash.get((w.desc.encoder_idx, w.desc.encoder_dir))
                active = until is not None and now < until
                if bool(w.pressed) != active:
                    w.setPressed(active)
                    visual_changed = True
                if active and not w.on:
                    w.setOn(True)
                    visual_changed = True

        # write matrix state to keyboard widget
        pressed = set()
        for w in self.keyboardWidget.widgets:
            if w.desc.row is not None and w.desc.col is not None:
                row = w.desc.row
                col = w.desc.col

                if row < len(matrix) and col < len(matrix[row]):
                    is_pressed = bool(matrix[row][col])
                    if bool(w.pressed) != is_pressed:
                        w.setPressed(is_pressed)
                        visual_changed = True
                    if is_pressed:
                        if not w.on:
                            w.setOn(True)
                            visual_changed = True
                        pressed.add((row, col))

        # sound on a newly registered key: how many keys are down together tells a clean press from a short.
        # A knob turn beeps like a single key (it is one event, not a press held with others)
        if self.chk_sound.isChecked():
            if pressed - self.pressed:
                play_sound("ok" if len(pressed) == 1 else "multi")
            elif knob_turned:
                play_sound("ok")
        self.pressed = pressed

        # Geometry and key positions do not change during a matrix poll.
        # Only repaint when pressed/tested state changed.
        if visual_changed:
            self.keyboardWidget.update()

    def unlock(self):
        # The dialog runs a nested event loop; suspend polling while it is
        # active, then immediately recheck the unlocked state.
        self.timer.stop()
        try:
            Unlocker.unlock(self.keyboard)
        finally:
            self._unlock_confirmed = False
            self._next_unlock_check = 0.0
            if self.valid():
                self.timer.start(20)

    def activate(self):
        self.pressed = set()
        self.encoder_last = None
        self.encoder_flash = {}
        self._unlock_confirmed = False
        self._next_unlock_check = 0.0
        self._last_encoder_poll = 0.0
        self.grabber.grabKeyboard()
        self.timer.start(20)

    def deactivate(self):
        self.grabber.releaseKeyboard()
        self.timer.stop()
