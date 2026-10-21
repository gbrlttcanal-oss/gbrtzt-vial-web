# SPDX-License-Identifier: GPL-2.0-or-later
from PyQt5.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout,
                             QLabel, QLineEdit, QPushButton, QGroupBox,
                             QScrollArea, QFrame, QSizePolicy, QTabWidget, QComboBox)
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QPixmap
from pathlib import Path

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

        # V11: presets em pares. O firmware Plus usa apenas o OLED esquerdo.
        presets_page = QWidget()
        presets_layout = QVBoxLayout()
        presets_layout.setContentsMargins(10, 10, 10, 10)
        presets_layout.setSpacing(12)

        note_presets = QLabel(
            "Cada preset possui duas imagens vinculadas (esquerda/direita). "
            "No Corvo48 Plus, somente o OLED esquerdo muda; "
            "o lado direito continua sendo o touchpad TPS43."
        )
        note_presets.setWordWrap(True)
        presets_layout.addWidget(note_presets)
        presets_layout.addWidget(QLabel("Modo do OLED:"))
        self.mode_combo = QComboBox()
        self.mode_combo.addItems(["Texto atual (nome + layer)", "Imagem pre-compilada"])
        presets_layout.addWidget(self.mode_combo)
        presets_layout.addWidget(QLabel("Preset:"))
        self.preset_combo = QComboBox()
        self.preset_combo.addItems(["Samurai", "Corvo 1", "Corvo 2"])
        presets_layout.addWidget(self.preset_combo)

        preview_row = QHBoxLayout()
        self.preview_left = QLabel()
        self.preview_right = QLabel()
        for label, side in ((self.preview_left, "OLED esquerdo"),
                            (self.preview_right, "OLED direito (somente previa)")):
            column = QVBoxLayout()
            column.addWidget(QLabel(side))
            label.setAlignment(Qt.AlignCenter)
            label.setMinimumSize(80, 205)
            label.setStyleSheet("background: #09080D; border: 1px solid #6640BA;")
            column.addWidget(label)
            preview_row.addLayout(column)
        presets_layout.addLayout(preview_row)

        self.preset_status = QLabel("")
        self.preset_status.setWordWrap(True)
        presets_layout.addWidget(self.preset_status)
        self.btn_apply_preset = QPushButton("Aplicar modo e preset")
        self.btn_apply_preset.clicked.connect(self._on_apply_preset)
        presets_layout.addWidget(self.btn_apply_preset)
        presets_layout.addStretch()

        presets_page.setLayout(presets_layout)
        tabs_widget.addTab(presets_page, "Image Presets")
        self.preset_combo.currentIndexChanged.connect(self._update_preview)
        self._update_preview()

        self.addWidget(tabs_widget)

        version_lbl = QLabel(_PATCH)
        version_lbl.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.addWidget(version_lbl)

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _populate(self):
        cfg = self.keyboard.oled_config
        self.row1_field._edit.setText(cfg.get('row1', 'SOFLE'))
        current = getattr(self.keyboard, 'oled_preset', {'mode': 0, 'preset': 0})
        self.mode_combo.setCurrentIndex(current.get('mode', 0))
        self.preset_combo.setCurrentIndex(current.get('preset', 0))
        self._update_preview()
        supported = getattr(self.keyboard, 'oled_presets_supported', False)
        self.btn_apply_preset.setEnabled(supported)
        self.preset_status.setText(
            "Corvo48 Plus V11: selecao de imagens habilitada."
            if supported else
            "Este firmware nao implementa presets OLED. O modo Texto continua disponivel."
        )

    # ── Button handler ────────────────────────────────────────────────────────

    def _on_apply(self):
        if not self.keyboard:
            return
        self.keyboard.set_oled_row1(self.row1_field._edit.text())

    def _update_preview(self, *args):
        names = ["samurai", "corvo1", "corvo2"]
        preset = names[max(0, min(2, self.preset_combo.currentIndex()))]
        for label, side in ((self.preview_left, "esquerdo"),
                            (self.preview_right, "direito")):
            path = Path(__file__).parent / "oled_images" / (preset + "-" + side + ".png")
            pixmap = QPixmap(str(path))
            if pixmap.isNull():
                label.setText("Previa indisponivel")
            else:
                label.setPixmap(pixmap.scaled(64, 192, Qt.KeepAspectRatio, Qt.FastTransformation))

    def _on_apply_preset(self):
        if not self.keyboard or not getattr(self.keyboard, 'oled_presets_supported', False):
            return
        self.keyboard.set_oled_preset(self.mode_combo.currentIndex(),
                                      self.preset_combo.currentIndex())

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
