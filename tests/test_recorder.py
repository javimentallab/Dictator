import threading
import time

import numpy as np

from voxkeypaste.recorder import Recorder

SR = 16000


class FakeStream:
    """Delivers numbered blocks (sample value = block number) every 10 ms, or nothing at all."""

    def __init__(self, callback, frame_size, deliver=True, value=None):
        self.callback, self.frame_size, self.deliver, self.value = callback, frame_size, deliver, value
        self._stop = threading.Event()
        self.blocks = 0

    def __enter__(self):
        if self.deliver:
            threading.Thread(target=self._run, daemon=True).start()
        return self

    def _run(self):
        while not self._stop.is_set():
            self.blocks += 1
            value = self.value if self.value is not None else self.blocks
            self.callback(np.full((self.frame_size, 1), value, dtype=np.int16), self.frame_size, None, None)
            time.sleep(0.01)

    def __exit__(self, *exc):
        self._stop.set()


def make(deliver=True, **kw):
    streams = []

    def factory(callback, frame_size):
        stream = FakeStream(callback, frame_size, deliver=deliver)
        streams.append(stream)
        return stream

    return Recorder(SR, stream_factory=factory, **kw), streams


def stop_after(recorder, seconds):
    threading.Timer(seconds, recorder.request_stop).start()


def test_lead_in_is_discarded():
    recorder, _ = make(lead_in_ms=60, trailing_ms=0)        # 60 ms = 2 blocks of 30 ms
    stop_after(recorder, 0.2)
    audio = recorder.record()
    assert len(audio) > 0
    assert audio[0] == 3                                    # blocks 1 and 2 were dropped


def test_trailing_time_keeps_recording_after_stop():
    recorder, _ = make(lead_in_ms=0, trailing_ms=300)
    stop_after(recorder, 0.15)
    started = time.time()
    recorder.record()
    assert time.time() - started >= 0.4                     # 0.15 + 0.3


def test_stop_works_even_if_the_device_delivers_nothing():
    """A stuck input stream must not hang the recording (the stop request is checked on a timeout)."""
    recorder, _ = make(deliver=False, lead_in_ms=0, trailing_ms=100)
    stop_after(recorder, 0.1)
    started = time.time()
    audio = recorder.record()
    assert time.time() - started < 1.0
    assert len(audio) == 0


def test_voice_activity_mode_waits_for_speech():
    """Silence alone never ends a voice-activity recording; the hotkey still does."""
    recorder, _ = make(mode='voice_activity', lead_in_ms=0, trailing_ms=0, silence_ms=100)
    stop_after(recorder, 0.4)
    started = time.time()
    recorder.record()
    assert time.time() - started >= 0.35
