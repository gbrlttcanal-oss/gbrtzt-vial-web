# SPDX-License-Identifier: GPL-2.0-or-later
import json

from PyQt5.QtWidgets import QHBoxLayout, QLabel, QLineEdit, QPushButton, QVBoxLayout, QMessageBox, QWidget, \
    QSizePolicy
from PyQt5.QtCore import Qt, pyqtSignal

from any_keycode_dialog import AnyKeycodeDialog
from editor.basic_editor import BasicEditor
from widgets.keyboard_widget import KeyboardWidget, EncoderWidget
from keycodes.keycodes import Keycode
from widgets.square_button import SquareButton
from tabbed_keycodes import TabbedKeycodes, keycode_filter_masked
from util import tr, KeycodeDisplay
from vial_device import VialKeyboard


class ClickableWidget(QWidget):

    clicked = pyqtSignal()

    def mousePressEvent(self, evt):
        super().mousePressEvent(evt)
        self.clicked.emit()


class KeymapEditor(BasicEditor):

    layer_name_changed = pyqtSignal()
    layout_restored = pyqtSignal()

    def __init__(self, layout_editor):
        super().__init__()

        self.layout_editor = layout_editor

        self.layout_layers = QHBoxLayout()
        self.layout_size = QVBoxLayout()
        layer_label = QLabel(tr("KeymapEditor", "Layer"))

        layout_labels_container = QHBoxLayout()
        layout_labels_container.addWidget(layer_label)
        layout_labels_container.addLayout(self.layout_layers)
        layout_labels_container.addStretch()
        layout_labels_container.addLayout(self.layout_size)

        # contains the actual keyboard
        self.container = KeyboardWidget(layout_editor)
        self.container.clicked.connect(self.on_key_clicked)
        self.container.deselected.connect(self.on_key_deselected)

        # OLED layer name row — hidden until keyboard reports oled_supported
        self.layer_name_edit = QLineEdit()
        self.layer_name_edit.setMaxLength(5)
        self.layer_name_edit.setFixedWidth(60)
        self.layer_name_edit.setPlaceholderText("name")
        self.layer_name_counter = QLabel("0/5")
        self.layer_name_counter.setFixedWidth(28)
        self.layer_name_edit.textChanged.connect(
            lambda t: self.layer_name_counter.setText("{}/5".format(len(t))))
        self.layer_name_btn = QPushButton("Set")
        self.layer_name_btn.setFixedWidth(50)
        self.layer_name_btn.clicked.connect(self._on_layer_name_set)
        self.layer_name_edit.returnPressed.connect(self._on_layer_name_set)

        layer_name_row = QHBoxLayout()
        layer_name_row.setContentsMargins(0, 2, 0, 2)
        layer_name_row.addWidget(QLabel("OLED name:"))
        layer_name_row.addWidget(self.layer_name_edit)
        layer_name_row.addWidget(self.layer_name_counter)
        layer_name_row.addWidget(self.layer_name_btn)
        layer_name_row.addStretch()
        self.layer_name_widget = QWidget()
        self.layer_name_widget.setLayout(layer_name_row)
        self.layer_name_widget.hide()

        # Reset layout: its own row under the layer buttons, right-aligned, so it can never
        # share space with the Layer buttons, the layout-size buttons or the OLED name row.
        self.btn_reset_layout = QPushButton(tr("KeymapEditor", "Reset layout..."))
        self.btn_reset_layout.setToolTip(tr("KeymapEditor",
            "Restore this keyboard's default keymap from the firmware (all layers). "
            "Macros, combos, tap dance and lighting are kept."))
        self.btn_reset_layout.clicked.connect(self.on_reset_layout)
        self.btn_reset_layout.setFixedWidth(140)  # like the other fixed-width buttons here, not the row width
        reset_row = QHBoxLayout()
        reset_row.setContentsMargins(0, 2, 0, 2)
        reset_row.addStretch()
        reset_row.addWidget(self.btn_reset_layout)
        self.reset_row_widget = QWidget()
        self.reset_row_widget.setLayout(reset_row)
        self.reset_row_widget.hide()

        layout = QVBoxLayout()
        layout.addLayout(layout_labels_container)
        layout.addWidget(self.reset_row_widget)
        layout.addWidget(self.layer_name_widget)
        layout.addWidget(self.container)
        layout.setAlignment(self.container, Qt.AlignHCenter)
        w = ClickableWidget()
        w.setLayout(layout)
        w.clicked.connect(self.on_empty_space_clicked)

        self.layer_buttons = []
        self.keyboard = None
        self.current_layer = 0

        layout_editor.changed.connect(self.on_layout_changed)

        self.container.anykey.connect(self.on_any_keycode)

        self.tabbed_keycodes = TabbedKeycodes()
        self.tabbed_keycodes.keycode_changed.connect(self.on_keycode_changed)
        self.tabbed_keycodes.anykey.connect(self.on_any_keycode)

        self.addWidget(w)
        self.addWidget(self.tabbed_keycodes)

        self.device = None
        KeycodeDisplay.notify_keymap_override(self)

    def on_empty_space_clicked(self):
        self.container.deselect()
        self.container.update()

    def on_keycode_changed(self, code):
        self.set_key(code)

    def rebuild_layers(self):
        # delete old layer labels
        for label in self.layer_buttons:
            label.hide()
            label.deleteLater()
        self.layer_buttons = []

        # create new layer labels
        for x in range(self.keyboard.layers):
            btn = SquareButton(str(x))
            btn.setFocusPolicy(Qt.NoFocus)
            btn.setRelSize(1.667)
            btn.setCheckable(True)
            btn.clicked.connect(lambda state, idx=x: self.switch_layer(idx))
            self.layout_layers.addWidget(btn)
            self.layer_buttons.append(btn)
        for x in range(0,2):
            btn = SquareButton("-") if x else SquareButton("+")
            btn.setFocusPolicy(Qt.NoFocus)
            btn.setCheckable(False)
            btn.clicked.connect(lambda state, idx=x: self.adjust_size(idx))
            self.layout_size.addWidget(btn)
            self.layer_buttons.append(btn)

    def adjust_size(self, minus):
        if minus:
            self.container.set_scale(self.container.get_scale() - 0.1)
        else:
            self.container.set_scale(self.container.get_scale() + 0.1)
        self.refresh_layer_display()

    def rebuild(self, device):
        super().rebuild(device)
        self.reset_row_widget.setVisible(self.valid())
        if self.valid():
            self.keyboard = device.keyboard

            # get number of layers
            self.rebuild_layers()

            self.container.set_keys(self.keyboard.keys, self.keyboard.encoders)

            self.current_layer = 0
            self.on_layout_changed()

            self.tabbed_keycodes.recreate_keycode_buttons()
            TabbedKeycodes.tray.recreate_keycode_buttons()
            self.refresh_layer_display()

            if getattr(self.keyboard, 'oled_supported', False):
                self.layer_name_widget.show()
                self._update_layer_name_field()
            else:
                self.layer_name_widget.hide()
        else:
            self.layer_name_widget.hide()
        self.container.setEnabled(self.valid())

    def valid(self):
        return isinstance(self.device, VialKeyboard)

    def save_layout(self):
        return self.keyboard.save_layout()

    def layout_matches(self, saved):
        """ Whether a saved layout has the shape of the connected keyboard: layers, matrix and encoders.
        The Vial UID is not compared, it changes between firmware versions of the same board. """
        layout = saved.get("layout", [])
        encoders = saved.get("encoder_layout", [])
        return len(layout) == self.keyboard.layers and \
            all(len(layer) == self.keyboard.rows for layer in layout) and \
            all(len(row) == self.keyboard.cols for layer in layout for row in layer) and \
            all(len(layer) == self.keyboard.encoder_count for layer in encoders)

    def restore_layout(self, data):
        if self.layout_matches(json.loads(data.decode("utf-8"))):
            self.do_restore_layout(data)
            return
        # a blocking QMessageBox.question() would spin a nested event loop, which the web build cannot do
        self.dlg_restore = QMessageBox(QMessageBox.Question, "",
                                       tr("KeymapEditor", "Saved keymap belongs to a different keyboard,"
                                                          " are you sure you want to continue?"),
                                       QMessageBox.Yes | QMessageBox.No)
        self.dlg_restore.setModal(True)
        self.dlg_restore.finished.connect(lambda ret: ret == QMessageBox.Yes and self.do_restore_layout(data))
        self.dlg_restore.show()

    def do_restore_layout(self, data):
        self.keyboard.restore_layout(data)
        self.refresh_layer_display()
        self.layout_restored.emit()

    def on_reset_layout(self):
        if self.keyboard is None:
            return
        # non-blocking confirm, same reason as restore_layout(): no nested event loop on the web build
        self.dlg_reset = QMessageBox(QMessageBox.Warning, "",
                                     tr("KeymapEditor", "Reset all layers to the keyboard's default layout?\n\n"
                                                        "Your current layers will be replaced. Macros, combos, "
                                                        "tap dance, key overrides and lighting are kept.\n\n"
                                                        "Tip: save your layout first (File -> Save current layout)."),
                                     QMessageBox.Yes | QMessageBox.No)
        self.dlg_reset.setModal(True)
        self.dlg_reset.finished.connect(lambda ret: ret == QMessageBox.Yes and self.do_reset_layout())
        self.dlg_reset.show()

    def do_reset_layout(self):
        self.keyboard.reset_keymap()
        # same path as loading a .vil: main window rebuilds from the keyboard
        self.layout_restored.emit()

    def on_any_keycode(self):
        if self.container.active_key is None:
            return
        current_code = self.code_for_widget(self.container.active_key)
        if self.container.active_mask:
            kc = Keycode.find_inner_keycode(current_code)
            current_code = kc.qmk_id

        self.dlg = AnyKeycodeDialog(current_code)
        self.dlg.finished.connect(self.on_dlg_finished)
        self.dlg.setModal(True)
        self.dlg.show()

    def on_dlg_finished(self, res):
        if res > 0:
            self.on_keycode_changed(self.dlg.value)

    def code_for_widget(self, widget):
        if widget.desc.row is not None:
            return self.keyboard.layout[(self.current_layer, widget.desc.row, widget.desc.col)]
        else:
            return self.keyboard.encoder_layout[(self.current_layer, widget.desc.encoder_idx,
                                                 widget.desc.encoder_dir)]

    def refresh_layer_display(self):
        """ Refresh text on key widgets to display data corresponding to current layer """

        self.container.update_layout()

        for idx, btn in enumerate(self.layer_buttons):
            btn.setEnabled(idx != self.current_layer)
            btn.setChecked(idx == self.current_layer)

        for widget in self.container.widgets:
            code = self.code_for_widget(widget)
            KeycodeDisplay.display_keycode(widget, code)
        self.container.update()
        self.container.updateGeometry()

    def switch_layer(self, idx):
        self.container.deselect()
        self.current_layer = idx
        self._update_layer_name_field()
        self.refresh_layer_display()

    def _update_layer_name_field(self):
        if not self.layer_name_widget.isVisible():
            return
        names = self.keyboard.oled_config.get('layer_names', [])
        name = names[self.current_layer] if self.current_layer < len(names) else ''
        self.layer_name_edit.blockSignals(True)
        self.layer_name_edit.setText(name.rstrip('\x00').strip()[:5])
        self.layer_name_edit.blockSignals(False)
        self.layer_name_counter.setText("{}/5".format(len(self.layer_name_edit.text())))

    def _on_layer_name_set(self):
        if not self.keyboard or not getattr(self.keyboard, 'oled_supported', False):
            return
        self.keyboard.set_oled_layer_name(self.current_layer, self.layer_name_edit.text())
        self.layer_name_changed.emit()

    def set_key(self, keycode):
        """ Change currently selected key to provided keycode """

        if self.container.active_key is None:
            return

        if isinstance(self.container.active_key, EncoderWidget):
            self.set_key_encoder(keycode)
        else:
            self.set_key_matrix(keycode)

        self.container.select_next()

    def set_key_encoder(self, keycode):
        l, i, d = self.current_layer, self.container.active_key.desc.encoder_idx,\
                            self.container.active_key.desc.encoder_dir

        # if masked, ensure that this is a byte-sized keycode
        if self.container.active_mask:
            if not Keycode.is_basic(keycode):
                return
            kc = Keycode.find_outer_keycode(self.keyboard.encoder_layout[(l, i, d)])
            if kc is None:
                return
            keycode = kc.qmk_id.replace("(kc)", "({})".format(keycode))

        self.keyboard.set_encoder(l, i, d, keycode)
        self.refresh_layer_display()

    def set_key_matrix(self, keycode):
        l, r, c = self.current_layer, self.container.active_key.desc.row, self.container.active_key.desc.col

        if r >= 0 and c >= 0:
            # if masked, ensure that this is a byte-sized keycode
            if self.container.active_mask:
                if not Keycode.is_basic(keycode):
                    return
                kc = Keycode.find_outer_keycode(self.keyboard.layout[(l, r, c)])
                if kc is None:
                    return
                keycode = kc.qmk_id.replace("(kc)", "({})".format(keycode))

            self.keyboard.set_key(l, r, c, keycode)
            self.refresh_layer_display()

    def on_key_clicked(self):
        """ Called when a key on the keyboard widget is clicked """
        self.refresh_layer_display()
        if self.container.active_mask:
            self.tabbed_keycodes.set_keycode_filter(keycode_filter_masked)
        else:
            self.tabbed_keycodes.set_keycode_filter(None)

    def on_key_deselected(self):
        self.tabbed_keycodes.set_keycode_filter(None)

    def on_layout_changed(self):
        if self.keyboard is None:
            return

        self.refresh_layer_display()
        self.keyboard.set_layout_options(self.layout_editor.pack())

    def on_keymap_override(self):
        self.refresh_layer_display()
