"""Dictator: tray app, status window and the dictation controller."""
import os
import queue
import subprocess
import sys
import threading
import time
import traceback

from PySide6.QtCore import QObject, Qt, QTimer, Signal
from PySide6.QtGui import QAction, QColor, QFont, QIcon, QPainter, QPainterPath, QPixmap
from PySide6.QtWidgets import QApplication, QHBoxLayout, QLabel, QMenu, QMessageBox, QSystemTrayIcon, QWidget

from . import (audio_devices, clip_saver, config, cues, dictionary, ducking, i18n, output,
               single_instance)
from .hotkey import HotkeyListener
from .recorder import Recorder
from .transcriber import Transcriber, post_process
from .update_flow import UpdateFlow

ASSETS = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'assets')
IDLE, STARTING, RECORDING, TRANSCRIBING = 'idle', 'starting', 'recording', 'transcribing'


class Controller(QObject):
    """Runs one dictation at a time in a worker thread. Hotkey callbacks only flip flags."""
    state_changed = Signal(str)
    failed = Signal(str)

    def __init__(self, cfg):
        super().__init__()
        self.cfg = cfg
        self.transcriber = Transcriber(cfg)
        self._lock = threading.Lock()
        self._state = IDLE
        self._stop = threading.Event()
        self._stop_feedback_done = False
        self._recorder = None
        self._jobs = queue.Queue()
        self.hotkey = HotkeyListener(cfg.get('recording', 'hotkey'), self._on_press, self._on_release,
                                     swallow=cfg.get('recording', 'swallow_hotkey'))
        threading.Thread(target=self._worker, name='dictation', daemon=True).start()
        threading.Thread(target=self._device_watch, name='device-watch', daemon=True).start()

    @property
    def state(self):
        return self._state

    def _set_state(self, state):
        with self._lock:
            self._state = state
        self.state_changed.emit(state)

    def start(self):
        self.transcriber.preload()
        if self.cfg.get('general', 'start_listening'):
            self.hotkey.start()

    def set_paused(self, paused):
        self.hotkey.start()
        self.hotkey.paused = paused

    # --- hotkey callbacks (must return immediately) ----------------------------------------
    def _on_press(self):
        mode = self.cfg.get('recording', 'mode')
        with self._lock:
            state = self._state
            if state == IDLE:
                self._state = STARTING
                self._stop.clear()
                self._stop_feedback_done = False
                self._jobs.put('dictate')
                return
        if state in (STARTING, RECORDING) and mode in ('toggle', 'voice_activity'):
            self._request_stop()
        elif state == TRANSCRIBING:
            config.log('Still transcribing the previous dictation; hotkey ignored.')

    def _on_release(self):
        if self.cfg.get('recording', 'mode') == 'hold' and self._state in (STARTING, RECORDING):
            self._request_stop()

    def _request_stop(self):
        self._stop.set()
        recorder = self._recorder
        if recorder is not None:
            recorder.request_stop()
        threading.Thread(target=self._stop_feedback, daemon=True).start()

    def _stop_feedback(self):
        """Unmute Voicemeeter and play the stop sound right away, without waiting for the transcription."""
        with self._lock:
            if self._stop_feedback_done:
                return
            self._stop_feedback_done = True
        ducking.stop()                                 # audio back before the stop sound
        cues.play('stop')

    # --- device watcher ----------------------------------------------------------------------
    DEVICE_WATCH_SECONDS = 2.0

    def _device_watch(self):
        """Re-initialise PortAudio while idle when the device list changes (e.g. Voicemeeter starting
        after logon), so the hotkey does not have to do it: that took long enough for a second press
        to cancel the dictation before the start sound."""
        while True:
            time.sleep(self.DEVICE_WATCH_SECONDS)
            if self._state == IDLE:
                audio_devices.refresh_if_changed(only_if=lambda: self._state == IDLE)

    # --- worker ------------------------------------------------------------------------------
    def _worker(self):
        while True:
            self._jobs.get()
            try:
                self._dictate()
            except Exception as e:
                config.log(traceback.format_exc())
                self.failed.emit(f'{type(e).__name__}: {e}')
            finally:
                ducking.stop()
                self._recorder = None
                self._set_state(IDLE)

    def _dictate(self):
        self.state_changed.emit(STARTING)
        audio_devices.refresh_if_changed()             # normally already done by _device_watch
        if self._stop.is_set():                        # cancelled while starting: no start sound
            config.log('Dictation cancelled before recording (hotkey pressed again while starting).')
            return
        cues.play('start', wait=True)                  # before the microphone opens: "you can speak now"
        if self._stop.is_set():
            config.log('Dictation cancelled during the start sound (hotkey pressed again).')
            return
        rec_cfg = lambda key: self.cfg.get('recording', key)
        device = audio_devices.resolve_input_device(rec_cfg('input_device_name'), rec_cfg('input_device_index'))
        recorder = Recorder(rec_cfg('sample_rate'), device=device, mode=rec_cfg('mode'),
                            lead_in_ms=rec_cfg('lead_in_ms'), trailing_ms=rec_cfg('trailing_ms'),
                            silence_ms=rec_cfg('silence_ms'), no_voice_stop_s=rec_cfg('no_voice_stop_s'))
        ducking.start()
        self._recorder = recorder
        if self._stop.is_set():
            recorder.request_stop()
        self._set_state(RECORDING)
        config.log('Recording...')
        audio = recorder.record()
        self._stop_feedback()                          # voice_activity / no voice: it ended by itself
        ducking.stop()
        if recorder.stopped_for_no_voice and not len(audio):
            config.log('Nothing was said: dictation discarded, audio restored.')
            return

        seconds = len(audio) / recorder.sample_rate
        if seconds * 1000 < rec_cfg('min_duration_ms'):
            config.log(f'Recording too short ({seconds:.2f} s), discarded.')
            return
        self._set_state(TRANSCRIBING)
        started = time.time()
        raw = self.transcriber.transcribe(audio, recorder.sample_rate)
        text = dictionary.apply(post_process(raw, self.cfg))
        config.log(f'Transcribed {seconds:.1f} s in {time.time() - started:.2f} s: {text!r}')
        if text.strip():
            output.write(text, self.cfg)
            cues.play('done')
        clip_saver.save(audio, recorder.sample_rate, raw.strip())


def tray_icon(name):
    return QIcon(os.path.join(ASSETS, name))


class StatusWindow(QWidget):
    """Small always-on-top pill at the bottom of the screen: recording / transcribing."""

    def __init__(self):
        super().__init__(None, Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool
                         | Qt.WindowDoesNotAcceptFocus)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(18, 10, 22, 10)
        self.icon = QLabel()
        self.text = QLabel()
        self.text.setFont(QFont('Segoe UI', 11))
        self.text.setStyleSheet('color: white;')
        layout.addWidget(self.icon)
        layout.addWidget(self.text)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        path = QPainterPath()
        path.addRoundedRect(self.rect().adjusted(1, 1, -1, -1), self.height() / 2 - 1, self.height() / 2 - 1)
        painter.fillPath(path, QColor(17, 17, 17, 230))

    def show_state(self, state):
        if state == RECORDING:
            icon, text = 'tray-recording.png', i18n.tr('ui.status.recording')
        elif state == TRANSCRIBING:
            icon, text = 'tray-transcribing.png', i18n.tr('ui.status.transcribing')
        else:
            self.hide()
            return
        self.icon.setPixmap(QPixmap(os.path.join(ASSETS, icon)).scaled(28, 28, Qt.KeepAspectRatio,
                                                                         Qt.SmoothTransformation))
        self.text.setText(text)
        self.adjustSize()
        screen = QApplication.primaryScreen().availableGeometry()
        self.move(screen.center().x() - self.width() // 2, screen.bottom() - self.height() - 60)
        self.show()


class TrayApp(QObject):
    def __init__(self, app, cfg, argv):
        super().__init__()
        self.app = app
        self.cfg = cfg
        self.argv = argv
        self.controller = Controller(cfg)
        self.status = StatusWindow() if cfg.get('general', 'show_status_window') else None
        self.settings = None

        self.tray = QSystemTrayIcon(tray_icon('icon.png'), app)
        self.menu = QMenu()
        self.state_action = QAction(self.menu)
        self.state_action.setEnabled(False)
        self.pause_action = QAction(i18n.tr('ui.tray.pause'), self.menu, checkable=True)
        self.pause_action.toggled.connect(self.toggle_pause)
        settings_action = QAction(i18n.tr('ui.tray.settings'), self.menu)
        settings_action.triggered.connect(self.open_settings)
        self.updates = UpdateFlow(self.restart)
        update_action = QAction(i18n.tr('ui.update.button'), self.menu)
        update_action.triggered.connect(lambda: self.updates.start(self.settings))
        restart_action = QAction(i18n.tr('ui.tray.restart'), self.menu)
        restart_action.triggered.connect(self.restart)
        quit_action = QAction(i18n.tr('ui.tray.quit'), self.menu)
        quit_action.triggered.connect(self.quit)
        for action in (self.state_action, None, self.pause_action, settings_action, update_action, None,
                       restart_action, quit_action):
            self.menu.addSeparator() if action is None else self.menu.addAction(action)
        self.tray.setContextMenu(self.menu)
        self.tray.activated.connect(self._on_tray_click)

        self.controller.state_changed.connect(self.on_state)
        self.controller.failed.connect(self.on_error)
        self.on_state(IDLE)
        self.tray.show()

    def start(self):
        ducking.recover()
        self.controller.start()
        if not self.cfg.get('general', 'start_listening'):
            self.pause_action.setChecked(True)
        if not self.cfg.loaded_from_file:              # first run: save the defaults and show the settings
            self.cfg.save()
            QTimer.singleShot(300, self.open_settings)

    def _on_tray_click(self, reason):
        if reason == QSystemTrayIcon.DoubleClick:
            self.open_settings()

    def on_state(self, state):
        icons = {RECORDING: 'tray-recording.png', TRANSCRIBING: 'tray-transcribing.png'}
        self.tray.setIcon(tray_icon(icons.get(state, 'icon.png')))
        hotkey = self.cfg.get('recording', 'hotkey')
        if self.pause_action.isChecked():
            text = i18n.tr('ui.status.paused')
        elif state in (RECORDING, TRANSCRIBING):
            text = i18n.tr(f'ui.status.{state}')
        else:
            text = i18n.tr('ui.status.ready', hotkey=hotkey.upper())
        self.state_action.setText(text)
        self.tray.setToolTip(f'Dictator — {text}')
        if self.status is not None:
            self.status.show_state(state)

    def on_error(self, message):
        self.tray.showMessage('Dictator', i18n.tr('ui.error.dictation', error=message),
                              QSystemTrayIcon.Warning, 8000)

    def toggle_pause(self, paused):
        self.controller.set_paused(paused)
        self.on_state(self.controller.state)

    def open_settings(self):
        from .settings_window import SettingsWindow
        if self.settings is None:
            self.settings = SettingsWindow(self.cfg)
            self.settings.saved.connect(self.on_settings_saved)
            self.settings.update_requested.connect(lambda: self.updates.start(self.settings))
            self.settings.finished.connect(lambda _: setattr(self, 'settings', None))
        self.settings.show()
        self.settings.raise_()
        self.settings.activateWindow()

    def on_settings_saved(self):
        answer = QMessageBox.question(None, 'Dictator', i18n.tr('ui.settings.restart_question'),
                                      QMessageBox.Yes | QMessageBox.No, QMessageBox.Yes)
        if answer == QMessageBox.Yes:
            self.restart()

    def _shutdown(self):
        self.controller.hotkey.stop()
        ducking.stop()
        cues.close()
        self.tray.hide()

    def restart(self):
        """Start a fresh copy (same interpreter, same arguments, same privileges) and exit this one."""
        self._shutdown()
        single_instance.release()
        args = [sys.executable, '-m', 'dictator'] + list(self.argv)
        flags = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP if sys.platform == 'win32' else 0
        subprocess.Popen(args, cwd=os.getcwd(), creationflags=flags, close_fds=True)
        os._exit(0)

    def quit(self):
        self._shutdown()
        self.app.quit()


def run(argv, config_path=None):
    cfg = config.init(config_path)
    i18n.set_language(cfg.get('general', 'language'))
    app = QApplication.instance() or QApplication(sys.argv[:1])
    app.setQuitOnLastWindowClosed(False)
    app.setApplicationName('Dictator')
    app.setWindowIcon(tray_icon('icon.png'))
    if not single_instance.acquire():
        config.log('Dictator is already running.')
        return 0
    tray = TrayApp(app, cfg, argv)
    tray.start()
    config.log(f'Dictator ready. Hotkey: {cfg.get("recording", "hotkey")}. Settings: {cfg.path}')
    return app.exec()
