"""The Update… button: check GitHub, ask, update the git clone, offer to restart. Only when clicked."""
import threading

from PySide6.QtCore import QObject, Qt, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QApplication, QMessageBox

from . import __version__, config, i18n, updater

_ICONS = {'information': QMessageBox.Information, 'question': QMessageBox.Question,
          'warning': QMessageBox.Warning}


class UpdateFlow(QObject):
    _finished = Signal(object, object)                 # (callback, (ok, value)), delivered in the GUI thread

    def __init__(self, restart):
        super().__init__()
        self.restart = restart
        self.busy = False
        self.parent = None
        self.release = None
        self._finished.connect(lambda callback, result: callback(*result))

    # --- seams the tests replace -------------------------------------------------------------
    def background(self, work, then):
        """Run `work` in a thread; call `then(ok, value)` back in the GUI thread."""
        def run():
            try:
                result = (True, work())
            except updater.UpdateError as e:
                result = (False, e)
            except Exception as e:                     # never leave the button stuck
                result = (False, updater.UpdateError('failed', f'{type(e).__name__}: {e}'))
            self._finished.emit(then, result)
        threading.Thread(target=run, name='update', daemon=True).start()

    def ask(self, kind, text, buttons):
        """Message box with our own (translated) buttons; returns the key of the one clicked."""
        box = QMessageBox(_ICONS[kind], 'Dictator', text, QMessageBox.NoButton, self.parent)
        clicked = {}
        for key, label in buttons:
            role = QMessageBox.RejectRole if key == 'close' else QMessageBox.AcceptRole
            clicked[box.addButton(label, role)] = key
        box.setDefaultButton(next(iter(clicked)))
        box.exec()
        return clicked.get(box.clickedButton(), 'close')

    def open_page(self, url):
        QDesktopServices.openUrl(QUrl(url))

    def _wait(self, on):
        if on:
            QApplication.setOverrideCursor(Qt.WaitCursor)
        else:
            QApplication.restoreOverrideCursor()

    # --- flow --------------------------------------------------------------------------------
    def start(self, parent=None):
        if self.busy:
            return
        self.busy = True
        self.parent = parent
        self._wait(True)
        self.background(updater.check, self._checked)

    def _done(self):
        self.busy = False
        self.parent = None

    def _checked(self, ok, value):
        self._wait(False)
        if not ok:
            config.log(f'Update check failed: {value.detail or value.code}')
            self.ask('warning', i18n.tr('ui.update.check_failed', error=value.detail[:300]),
                     [('close', i18n.tr('ui.update.close'))])
            return self._done()
        if not value['newer']:
            self.ask('information', i18n.tr('ui.update.up_to_date', version=__version__),
                     [('close', i18n.tr('ui.update.close'))])
            return self._done()
        self.release = value
        config.log(f'Dictator {value["version"]} is available (installed: {__version__}).')
        text = i18n.tr('ui.update.available', latest=value['version'], current=__version__)
        blocker = updater.self_update_blocker()
        if blocker:
            return self._manual(blocker)
        choice = self.ask('question', f'{text}\n\n{i18n.tr("ui.update.confirm")}',
                          [('install', i18n.tr('ui.update.install')), ('notes', i18n.tr('ui.update.notes')),
                           ('close', i18n.tr('ui.update.later'))])
        if choice == 'notes':
            self.open_page(value['url'])
        if choice != 'install':
            return self._done()
        self._wait(True)
        self.background(lambda: updater.install(value['tag']), self._installed)

    def _manual(self, code):
        """This copy cannot update itself: say why and offer the release page."""
        value = self.release
        text = (f'{i18n.tr("ui.update.available", latest=value["version"], current=__version__)}\n\n'
                f'{i18n.tr(f"ui.update.reason.{code}")} {i18n.tr("ui.update.manual")}')
        if self.ask('information', text, [('open', i18n.tr('ui.update.open_page')),
                                          ('close', i18n.tr('ui.update.close'))]) == 'open':
            self.open_page(value['url'])
        self._done()

    def _installed(self, ok, value):
        self._wait(False)
        if not ok:
            config.log(f'Update failed: {value.code} {value.detail}')
            if value.code != 'failed':
                return self._manual(value.code)
            self.ask('warning', i18n.tr('ui.update.failed', error=value.detail[:300]),
                     [('close', i18n.tr('ui.update.close'))])
            return self._done()
        version = self.release['version']
        config.log(f'Updated to Dictator {version} ({value}).')
        choice = self.ask('question', i18n.tr('ui.update.done', version=version),
                          [('restart', i18n.tr('ui.tray.restart')), ('close', i18n.tr('ui.update.later'))])
        self._done()
        if choice == 'restart':
            self.restart()
