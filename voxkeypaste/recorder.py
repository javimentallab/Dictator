"""Microphone recording.

* lead_in_ms: audio at the start is DISCARDED (key click, device pre-roll and
  speaker sound that leaks in before other audio is muted).
* trailing_ms: after a stop request the stream keeps recording a little, so
  the last syllable is not cut off.
* voice_activity mode: stops by itself after silence_ms of silence once
  speech has been detected (webrtcvad).
* Every wait has a timeout: if the device stops delivering audio, a stop
  request still ends the recording (no hang).
"""
import collections
import threading
import time

import numpy as np

from . import config

FRAME_MS = 30            # webrtcvad accepts 10/20/30 ms frames
VAD_RATES = (8000, 16000, 32000, 48000)


class Recorder:
    def __init__(self, sample_rate, device=None, mode='toggle', lead_in_ms=150, trailing_ms=300,
                 silence_ms=900, stream_factory=None):
        self.sample_rate = int(sample_rate)
        self.device = device
        self.mode = mode
        self.lead_in_ms = max(0, int(lead_in_ms))
        self.trailing_ms = max(0, int(trailing_ms))
        self.silence_ms = max(FRAME_MS, int(silence_ms))
        self._stop = threading.Event()
        self._stream_factory = stream_factory      # tests inject a fake stream here
        self.stopped_by_user = False

    def request_stop(self):
        self.stopped_by_user = True
        self._stop.set()

    def _open_stream(self, callback, frame_size):
        if self._stream_factory is not None:
            return self._stream_factory(callback=callback, frame_size=frame_size)
        import sounddevice as sd
        return sd.InputStream(samplerate=self.sample_rate, channels=1, dtype='int16', blocksize=frame_size,
                              device=self.device, callback=callback)

    def record(self, max_seconds=600):
        """Record until stopped. Returns int16 mono numpy array (possibly empty)."""
        frame_size = int(self.sample_rate * FRAME_MS / 1000)
        buffer = collections.deque()
        ready = threading.Event()
        lock = threading.Lock()

        def callback(indata, frames, time_info, status):
            with lock:
                buffer.append(np.array(indata[:, 0], dtype=np.int16, copy=True))
            ready.set()

        vad = None
        if self.mode == 'voice_activity':
            if self.sample_rate in VAD_RATES:
                import webrtcvad
                vad = webrtcvad.Vad(2)
            else:
                config.log(f'Voice activity mode needs a sample rate of {VAD_RATES}; it will only stop with the hotkey.')

        skip = int(self.sample_rate * self.lead_in_ms / 1000)
        chunks = []
        speech = False
        silent_ms = 0
        deadline = time.time() + max_seconds
        trailing_until = None
        pending = np.zeros(0, dtype=np.int16)

        with self._open_stream(callback, frame_size):
            while True:
                now = time.time()
                if now > deadline:
                    config.log('Maximum recording length reached.')
                    break
                if self._stop.is_set() and trailing_until is None:
                    trailing_until = now + self.trailing_ms / 1000.0
                if trailing_until is not None and now >= trailing_until:
                    break
                if not ready.wait(timeout=0.05):
                    continue
                ready.clear()
                with lock:
                    blocks = list(buffer)
                    buffer.clear()
                for block in blocks:
                    if skip > 0:
                        dropped = min(skip, len(block))
                        skip -= dropped
                        block = block[dropped:]
                    if not len(block):
                        continue
                    chunks.append(block)
                    if vad is None:
                        continue
                    pending = np.concatenate([pending, block])
                    while len(pending) >= frame_size:
                        frame, pending = pending[:frame_size], pending[frame_size:]
                        if vad.is_speech(frame.tobytes(), self.sample_rate):
                            speech, silent_ms = True, 0
                        else:
                            silent_ms += FRAME_MS
                    if speech and silent_ms >= self.silence_ms and not self._stop.is_set():
                        self._stop.set()        # natural end: no trailing needed beyond the silence
                        trailing_until = time.time()

        if not chunks:
            return np.zeros(0, dtype=np.int16)
        return np.concatenate(chunks)
