"""The whole dictation flow with fake audio, transcription and output (no devices, no network)."""
import threading
import time

import numpy as np
import pytest

from voxkeypaste import app as app_module
from voxkeypaste import cues, ducking


class FakeRecorder:
    instances = []

    def __init__(self, sample_rate, **kw):
        self.sample_rate = sample_rate
        self._stop = threading.Event()
        FakeRecorder.instances.append(self)

    def request_stop(self):
        self._stop.set()

    def record(self):
        self._stop.wait(timeout=5)
        return np.ones(self.sample_rate, dtype=np.int16)      # 1 s of "audio"


@pytest.fixture
def controller(cfg, monkeypatch):
    written, played = [], []
    FakeRecorder.instances = []
    monkeypatch.setattr(app_module, 'Recorder', FakeRecorder)
    monkeypatch.setattr(app_module.output, 'write', lambda text, cfg: written.append(text))
    monkeypatch.setattr(cues, 'play', lambda kind, wait=False: played.append(kind))
    monkeypatch.setattr(ducking, 'start', lambda: None)
    monkeypatch.setattr(ducking, 'stop', lambda: None)
    c = app_module.Controller(cfg)
    c.transcriber.transcribe = lambda audio, sr: 'hola mundo'
    c.written, c.played = written, played
    return c


def wait_for(predicate, timeout=3):
    end = time.time() + timeout
    while time.time() < end:
        if predicate():
            return True
        time.sleep(0.01)
    return False


def test_toggle_dictation(controller):
    controller._on_press()
    assert wait_for(lambda: controller.state == app_module.RECORDING)
    controller._on_press()
    assert wait_for(lambda: controller.written == ['hola mundo '])
    assert wait_for(lambda: controller.state == app_module.IDLE)
    assert controller.played.count('start') == 1 and controller.played.count('stop') == 1


def test_hold_mode_stops_on_release(controller, cfg):
    cfg.set('recording', 'mode', 'hold')
    controller._on_press()
    assert wait_for(lambda: controller.state == app_module.RECORDING)
    controller._on_release()
    assert wait_for(lambda: controller.written == ['hola mundo '])


def test_press_while_transcribing_is_ignored(controller):
    gate = threading.Event()

    def slow(audio, sr):
        gate.wait(timeout=5)
        return 'uno'

    controller.transcriber.transcribe = slow
    controller._on_press()
    assert wait_for(lambda: controller.state == app_module.RECORDING)
    controller._on_press()
    assert wait_for(lambda: controller.state == app_module.TRANSCRIBING)
    controller._on_press()                                     # must not start or stop anything
    gate.set()
    assert wait_for(lambda: controller.written == ['uno '])
    assert len(FakeRecorder.instances) == 1


def test_stop_during_start_sound_cancels(controller, monkeypatch):
    monkeypatch.setattr(cues, 'play', lambda kind, wait=False: time.sleep(0.3) if kind == 'start' else None)
    controller._on_press()
    time.sleep(0.05)
    controller._on_press()                                     # stop while the start sound plays
    assert wait_for(lambda: controller.state == app_module.IDLE)
    time.sleep(0.4)
    assert controller.written == [] and FakeRecorder.instances == []


def test_cancel_while_starting_skips_start_sound(controller, monkeypatch):
    gate = threading.Event()
    monkeypatch.setattr(app_module.audio_devices, 'refresh_if_changed', lambda only_if=None: gate.wait(timeout=5))
    controller._on_press()
    assert wait_for(lambda: controller.state == app_module.STARTING)
    controller._on_press()                                     # second press during a slow device refresh
    gate.set()
    assert wait_for(lambda: controller.state == app_module.IDLE)
    time.sleep(0.1)
    assert 'start' not in controller.played and FakeRecorder.instances == []


def test_device_refresh_skipped_unless_idle(monkeypatch):
    from voxkeypaste import audio_devices
    calls = []
    monkeypatch.setattr(audio_devices, '_device_signature', lambda: calls.append(1) or ('changed',))
    assert audio_devices.refresh_if_changed(only_if=lambda: False) is False
    assert calls == []
