import threading
import time

import numpy as np

from dictator.recorder import Recorder

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


# --- no_voice_stop_s: a single press must not leave the audio muted forever --------------------
class LoudMeansVoice:
    """Stands in for webrtcvad: a frame is speech when it is loud (the recorder also checks the level)."""

    def __init__(self, level):
        pass

    def is_speech(self, data, rate):
        return np.abs(np.frombuffer(data, dtype=np.int16)).max() >= 1000


def scripted(values):
    """Recorder whose stream plays the given block values (then silence), one block every 10 ms."""
    class Stream(FakeStream):
        def _run(self):
            n = 0
            while not self._stop.is_set():
                value = values[n] if n < len(values) else 0
                n += 1
                self.callback(np.full((self.frame_size, 1), value, dtype=np.int16), self.frame_size, None, None)
                time.sleep(0.01)

    return lambda callback, frame_size: Stream(callback, frame_size)


def test_no_voice_stops_by_itself_and_returns_nothing(monkeypatch):
    import webrtcvad
    monkeypatch.setattr(webrtcvad, 'Vad', LoudMeansVoice)
    recorder = Recorder(SR, lead_in_ms=0, trailing_ms=0, no_voice_stop_s=0.3, stream_factory=scripted([]))
    started = time.time()
    audio = recorder.record()
    assert 0.25 <= time.time() - started < 1.0
    assert recorder.stopped_for_no_voice and not recorder.heard_voice and not recorder.stopped_by_user
    assert len(audio) == 0


def test_short_clicks_are_not_voice(monkeypatch):
    """Knocks and clicks (a few loud frames) must not keep the recording alive."""
    import webrtcvad
    monkeypatch.setattr(webrtcvad, 'Vad', LoudMeansVoice)
    clicks = [0, 0, 20000, 20000, 0, 0, 0, 20000, 0, 0] * 20
    recorder = Recorder(SR, lead_in_ms=0, trailing_ms=0, no_voice_stop_s=0.3, stream_factory=scripted(clicks))
    recorder.record()
    assert recorder.stopped_for_no_voice and not recorder.heard_voice


def test_no_voice_also_stops_a_device_that_delivers_nothing(monkeypatch):
    import webrtcvad
    monkeypatch.setattr(webrtcvad, 'Vad', LoudMeansVoice)
    recorder, _ = make(deliver=False, lead_in_ms=0, trailing_ms=0, no_voice_stop_s=0.2)
    started = time.time()
    assert len(recorder.record()) == 0
    assert time.time() - started < 1.0 and recorder.stopped_for_no_voice


def test_words_then_silence_keep_the_words_and_cut_the_silence(monkeypatch):
    import webrtcvad
    from dictator import recorder as recorder_module
    monkeypatch.setattr(webrtcvad, 'Vad', LoudMeansVoice)
    words = [5000] * 20                                       # 20 blocks of 30 ms = 0.6 s of "voice"
    recorder = Recorder(SR, lead_in_ms=0, trailing_ms=0, no_voice_stop_s=0.4, stream_factory=scripted(words))
    audio = recorder.record()
    assert recorder.stopped_for_no_voice and recorder.heard_voice
    frame = int(SR * 0.03)
    keep = int(SR * recorder_module.NO_VOICE_KEEP_MS / 1000)
    assert len(audio) == 20 * frame + keep                    # the words plus a short tail, not the whole silence
    assert (audio[:20 * frame] == 5000).all()


def test_off_by_default_and_the_hotkey_still_stops():
    recorder, _ = make(lead_in_ms=0, trailing_ms=0)
    stop_after(recorder, 0.3)
    recorder.record()
    assert recorder.stopped_by_user and not recorder.stopped_for_no_voice
