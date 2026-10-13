# SPDX-License-Identifier: GPL-2.0-or-later
from PyQt5.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout,
                             QLabel, QLineEdit, QPushButton, QGroupBox,
                             QScrollArea, QFrame, QSizePolicy, QTabWidget)
from PyQt5.QtCore import Qt

from editor.basic_editor import BasicEditor
from vial_device import VialKeyboard

_PATCH = "Patch: F47A"
_MAX_CHARS = 7


def _make_scrollable(inner_layout):
    w = QWidget()
    w.setLayout(inner_layout)
    w.setObjectName("oledInner")
    scroll = QScrollArea()
    scroll.setFrameShape(QFrame.NoFrame)
    scroll.setStyleSheet("QScrollArea { background-color: transparent; }")
    w.setStyleSheet("#oledInner { background-color: transparent; }")
    scroll.setWidgetResizable(True)
    scroll.setWidget(w)
    return scroll


def _centered_scroll(inner_layout):
    """Content constrained to natural width, centred horizontally."""
    content = QWidget()
    content.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Maximum)
    content.setLayout(inner_layout)
    outer = QVBoxLayout()
    outer.addWidget(content)
    outer.setAlignment(content, Qt.AlignHCenter)
    return _make_scrollable(outer)


def _make_char_field(placeholder=""):
    """QLineEdit limited to 5 printable ASCII characters with live counter."""
    row = QWidget()
    row.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
    hl = QHBoxLayout(row)
    hl.setContentsMargins(0, 0, 0, 0)
    hl.setSpacing(6)

    edit = QLineEdit()
    edit.setMaxLength(_MAX_CHARS)
    edit.setFixedWidth(105)
    edit.setPlaceholderText(placeholder)

    counter = QLabel("0/7")
    counter.setFixedWidth(28)

    def _on_change(text):
        counter.setText("{}/{}".format(len(text), _MAX_CHARS))

    edit.textChanged.connect(_on_change)
    hl.addWidget(edit)
    hl.addWidget(counter)
    hl.addStretch()

    row._edit = edit
    return row


class OledConfigurator(BasicEditor):

    def __init__(self):
        super().__init__()
        self.keyboard = None

        tabs_widget = QTabWidget()

        # ── Labels tab ────────────────────────────────────────────────────────
        inner = QVBoxLayout()
        inner.setContentsMargins(4, 4, 4, 4)
        inner.setSpacing(10)

        note = QLabel(
            "Text shown on the left OLED (master side).\n"
            "Maximum 7 characters on Corvo48 V7.\n"
            "Layer names are set per-layer in the Keymap tab.\n"
            "Changes take effect immediately after clicking Apply.\n"
            "OLED sleep time is synced with the Lighting (RGB) sleep time — kindly adjust it on the Lighting tab."
        )
        note.setWordWrap(True)
        inner.addWidget(note)

        # Keyboard name (row 1)
        kb_group = QGroupBox("Keyboard Name  (OLED row 1)")
        kb_layout = QHBoxLayout()
        kb_layout.setContentsMargins(8, 8, 8, 8)
        self.row1_field = _make_char_field("GbrTzT")
        kb_layout.addWidget(QLabel("Display name:"))
        kb_layout.addWidget(self.row1_field)
        kb_layout.addStretch()
        kb_group.setLayout(kb_layout)
        inner.addWidget(kb_group)

        inner.addStretch()

        # Apply button
        btn_row = QHBoxLayout()
        btn_row.addStretch()
        self.btn_apply = QPushButton("Apply to Keyboard")
        self.btn_apply.setMinimumWidth(200)
        self.btn_apply.clicked.connect(self._on_apply)
        btn_row.addWidget(self.btn_apply)
        inner.addLayout(btn_row)

        labels_page = QWidget()
        lp_layout = QVBoxLayout(labels_page)
        lp_layout.setContentsMargins(0, 0, 0, 0)
        lp_layout.addWidget(_centered_scroll(inner))
        tabs_widget.addTab(labels_page, "Labels")

        self.addWidget(tabs_widget)

        version_lbl = QLabel(_PATCH)
        version_lbl.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.addWidget(version_lbl)

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _populate(self):
        cfg = self.keyboard.oled_config
        self.row1_field._edit.setText(cfg.get('row1', 'SOFLE'))

    # ── Button handler ────────────────────────────────────────────────────────

    def _on_apply(self):
        if not self.keyboard:
            return
        self.keyboard.set_oled_row1(self.row1_field._edit.text())

    # ── BasicEditor interface ─────────────────────────────────────────────────

    def valid(self):
        return (isinstance(self.device, VialKeyboard)
                and self.device.keyboard.oled_supported)

    def rebuild(self, device):
        super().rebuild(device)
        if not self.valid():
            self.keyboard = None
            return
        self.keyboard = device.keyboard
        self._populate()
