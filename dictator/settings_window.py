"""Settings window, generated from config.SCHEMA. Every label and help text is translated."""
import os

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QPalette
from PySide6.QtWidgets import (QApplication, QCheckBox, QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox,
                               QFileDialog, QGridLayout, QHBoxLayout, QLabel, QLineEdit, QMessageBox, QPushButton,
                               QScrollArea, QSizePolicy, QSpinBox, QTabWidget, QVBoxLayout, QWidget)

from . import config, i18n


def device_names(kind):
    """Names of the input or output devices, for the editable combo boxes."""
    try:
        import sounddevice as sd
        channels = 'max_input_channels' if kind == 'input' else 'max_output_channels'
        mme = [i for i, api in enumerate(sd.query_hostapis()) if 'MME' in api['name']] if os.name == 'nt' else []
        names = []
        for d in sd.query_devices():
            name = d['name'].strip()
            if mme and d['hostapi'] not in mme:      # Windows: the names Windows itself shows
                continue
            if d[channels] > 0 and name not in names and '@System32' not in name:
                names.append(name)
        return names
    except Exception:
        return []


LABEL_WIDTH = 200


class SettingsWindow(QDialog):
    saved = Signal()

    def __init__(self, cfg):
        super().__init__(None, Qt.Window)
        self.cfg = cfg
        self.widgets = {}
        self.rows = {}
        self.setWindowTitle(i18n.tr('ui.settings.title'))
        self.resize(760, 640)
        self.setMinimumSize(560, 420)

        layout = QVBoxLayout(self)
        self.tabs = QTabWidget()
        self.tabs.setUsesScrollButtons(True)
        layout.addWidget(self.tabs)
        for section, settings in config.SCHEMA:
            if section == 'ducking' and os.name != 'nt':
                continue
            self.tabs.addTab(self._build_tab(section, settings), i18n.tr(f'section.{section}'))
        self.widgets[('transcription', 'backend')][1].currentIndexChanged.connect(self._update_backend_rows)
        self._update_backend_rows()

        hint = QLabel(i18n.tr('ui.settings.file', path=cfg.path))
        hint.setTextInteractionFlags(Qt.TextSelectableByMouse)
        hint.setForegroundRole(QPalette.PlaceholderText)
        hint.setWordWrap(True)
        layout.addWidget(hint)

        buttons = QDialogButtonBox()
        self.save_button = buttons.addButton(i18n.tr('ui.settings.save'), QDialogButtonBox.AcceptRole)
        cancel = buttons.addButton(i18n.tr('ui.settings.cancel'), QDialogButtonBox.RejectRole)
        self.save_button.clicked.connect(self.save)
        cancel.clicked.connect(self.reject)
        layout.addWidget(buttons)

    def _build_tab(self, section, settings):
        # One grid: [name | control] and below it [ | description], so every description gets the full
        # width of the second column (wrapped labels inside nested layouts were clipped).
        page = QWidget()
        grid = QGridLayout(page)
        grid.setColumnMinimumWidth(0, LABEL_WIDTH)
        grid.setColumnStretch(1, 1)
        grid.setHorizontalSpacing(14)
        grid.setVerticalSpacing(3)
        row = 0
        for setting in settings:
            widget = self._make_widget(section, setting)
            label = QLabel(i18n.label(section, setting.key))
            label.setWordWrap(True)
            label.setFixedWidth(LABEL_WIDTH)
            help_text = i18n.help_text(section, setting.key)
            label.setToolTip(help_text)
            widget.setToolTip(help_text)
            if isinstance(widget, QComboBox):
                # long device names must not widen the whole page
                widget.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
                widget.setMinimumContentsLength(12)
            if not isinstance(widget, QCheckBox):
                widget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            description = QLabel(help_text)
            description.setWordWrap(True)
            description.setAlignment(Qt.AlignLeft | Qt.AlignTop)
            description.setForegroundRole(QPalette.PlaceholderText)   # secondary text, light and dark themes
            small = description.font()
            small.setPointSizeF(max(7.5, small.pointSizeF() - 0.5))
            description.setFont(small)
            description.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Minimum)
            description.setContentsMargins(0, 0, 0, 12)   # space before the next setting (collapses when hidden)
            grid.addWidget(label, row, 0, Qt.AlignLeft | Qt.AlignVCenter)
            grid.addWidget(widget, row, 1)
            grid.addWidget(description, row + 1, 1)
            row += 2
            self.widgets[(section, setting.key)] = (setting, widget)
            self.rows[(section, setting.key)] = (label, widget, description)
        grid.setRowStretch(row, 1)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)   # wrap instead of scrolling sideways
        scroll.setWidget(page)
        return scroll

    def _make_widget(self, section, setting):
        value = self.cfg.get(section, setting.key)
        kind = setting.kind
        if kind == 'bool':
            widget = QCheckBox()
            widget.setChecked(bool(value))
        elif kind == 'int':
            widget = QSpinBox()
            widget.setRange(int(setting.minimum or 0), int(setting.maximum or 1_000_000))
            widget.setValue(int(value))
        elif kind == 'float':
            widget = QDoubleSpinBox()
            widget.setDecimals(2)
            widget.setSingleStep(0.1)
            widget.setRange(setting.minimum or 0.0, setting.maximum or 1_000_000.0)
            widget.setValue(float(value))
        elif kind == 'choice':
            widget = QComboBox()
            for option in setting.options:
                text = i18n.option(option)
                if section == 'general' and setting.key == 'language' and option != 'auto':
                    text = i18n.tr(f'language.{option}')
                widget.addItem(text, option)
            index = widget.findData(value)
            widget.setCurrentIndex(max(0, index))
        elif kind in ('input_device', 'output_device'):
            widget = QComboBox()
            widget.setEditable(True)
            widget.addItem('')
            widget.addItems(device_names('input' if kind == 'input_device' else 'output'))
            widget.setCurrentText(str(value or ''))
            widget.lineEdit().setPlaceholderText(i18n.tr('ui.settings.default_device'))
            widget.view().setMinimumWidth(widget.view().sizeHintForColumn(0) + 30)   # full names in the list
        elif kind == 'url':
            widget = QWidget()
            row = QHBoxLayout(widget)
            row.setContentsMargins(0, 0, 0, 0)
            edit = QLineEdit(str(value or ''))
            edit.setPlaceholderText('http://192.168.1.10:8000/v1')
            test = QPushButton(i18n.tr('ui.settings.test_server'))
            test.clicked.connect(self._test_server)
            row.addWidget(edit, 1)
            row.addWidget(test)
            widget.edit = edit
        elif kind == 'server_model':
            widget = QComboBox()
            widget.setEditable(True)
            widget.setCurrentText(str(value or ''))
        elif kind == 'path':
            widget = QWidget()
            row = QHBoxLayout(widget)
            row.setContentsMargins(0, 0, 0, 0)
            edit = QLineEdit(str(value or ''))
            browse = QPushButton(i18n.tr('ui.settings.browse'))
            browse.clicked.connect(lambda _=False, e=edit: self._browse(e))
            row.addWidget(edit, 1)
            row.addWidget(browse)
            widget.edit = edit
        else:
            widget = QLineEdit(str(value or ''))
            if kind == 'secret':
                widget.setEchoMode(QLineEdit.Password)
        return widget

    def _update_backend_rows(self, *_):
        """Show only the settings of the chosen engine (local model or API server)."""
        backend = self.widgets[('transcription', 'backend')][1].currentData()
        for (section, key), parts in self.rows.items():
            if section != 'transcription':
                continue
            if key.startswith('local_'):
                visible = backend == 'local'
            elif key.startswith('api_'):
                visible = backend == 'api'
            else:
                continue
            for part in parts:
                part.setVisible(visible)

    def _test_server(self):
        """Ask the server for its models; fill the model list with them."""
        from .transcriber import list_models
        url = self.widgets[('transcription', 'api_base_url')][1].edit.text().strip()
        key = self.widgets[('transcription', 'api_key')][1].text().strip()
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            models = list_models(url, key)
        except Exception as e:
            QApplication.restoreOverrideCursor()
            QMessageBox.warning(self, 'Dictator', i18n.tr('ui.settings.server_error', error=str(e)[:300]))
            return
        QApplication.restoreOverrideCursor()
        combo = self.widgets[('transcription', 'api_model')][1]
        current = combo.currentText()
        combo.clear()
        combo.addItems(models)
        combo.setCurrentText(current or (models[0] if models else ''))
        QMessageBox.information(self, 'Dictator',
                                i18n.tr('ui.settings.server_ok', models=', '.join(models) if models else '—'))

    def _browse(self, edit):
        path, _ = QFileDialog.getOpenFileName(self, i18n.tr('ui.settings.browse'), edit.text())
        if path:
            edit.setText(path)

    @staticmethod
    def _value(setting, widget):
        if setting.kind == 'bool':
            return widget.isChecked()
        if setting.kind in ('int', 'float'):
            return widget.value()
        if setting.kind == 'choice':
            return widget.currentData()
        if setting.kind in ('input_device', 'output_device', 'server_model'):
            return widget.currentText().strip()
        if setting.kind in ('path', 'url'):
            return widget.edit.text().strip()
        return widget.text().strip()

    def save(self):
        from .hotkey import parse
        hotkey_widget = self.widgets[('recording', 'hotkey')][1]
        try:
            parse(hotkey_widget.text())
        except ValueError:
            self.tabs.setCurrentIndex(config.SECTIONS.index('recording'))
            hotkey_widget.setFocus()
            return
        for (section, key), (setting, widget) in self.widgets.items():
            self.cfg.set(section, key, self._value(setting, widget))
        self.cfg.save()
        self.accept()
        self.saved.emit()
