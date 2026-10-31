"""Start/stop sounds played through ONE persistent output stream.

Opening and closing an output device for every sound competed with the
recording stream and caused random gaps and delays, so the stream is opened
once and its callback outputs the requested sound (and silence otherwise).
The output device can be chosen by name (sounds.output_device_name).
"""
import os
import threading
import wave

import numpy as np
import sounddevice as sd

from . import audio_devices
from . import config

ASSETS = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'assets')
_SR = 48000
_CH = 2
_lock = threading.Lock()
_data = None          # int16 array (N, _CH) being played, or None
_pos = 0
_done = threading.Event()
_stream = None
_cache = {}


def _callback(outdata, frames, time_info, status):
    global _data, _pos
    with _lock:
        if _data is None:
            outdata.fill(0)
            return
        n = min(frames, len(_data) - _pos)
        outdata[:n] = _data[_pos:_pos + n]
        if n < frames:
            outdata[n:].fill(0)
            _data = None
            _pos = 0
            _done.set()
        else:
            _pos += n


def _ensure_stream():
    global _stream
    if _stream is not None:
        return _stream
    with audio_devices.refresh_lock:               # never open it while PortAudio is being re-initialised
        if _stream is not None:
            return _stream
        try:
            name = config.get('sounds', 'output_device_name')
            device = audio_devices.find_device(name, 'output') if name else None
            _stream = sd.OutputStream(samplerate=_SR, channels=_CH, dtype='int16',
                                      device=device, callback=_callback)
            _stream.start()
        except Exception as e:
            config.log(f'Sounds disabled: could not open the output device ({e}).')
            _stream = None
    return _stream


def close():
    """Close the persistent stream (it is reopened on the next sound)."""
    global _stream, _data, _pos
    old, _stream = _stream, None
    if old is not None:
        try:
            old.abort()
            old.close()
        except Exception:
            pass
    with _lock:
        _data = None
        _pos = 0
    _done.set()


audio_devices.on_refresh(close)


def _load(path):
    """WAV -> int16 (N, 2) at 48 kHz. Mono is duplicated; other rates are resampled linearly."""
    if path not in _cache:
        with wave.open(path, 'rb') as wf:
            ch, width, rate = wf.getnchannels(), wf.getsampwidth(), wf.getframerate()
            raw = wf.readframes(wf.getnframes())
        if width != 2:
            raise ValueError('only 16-bit WAV files are supported')
        data = np.frombuffer(raw, dtype='<i2').reshape(-1, ch)
        if ch == 1:
            data = np.repeat(data, 2, axis=1)
        elif ch > 2:
            data = data[:, :2]
        if rate != _SR:
            n = int(len(data) * _SR / rate)
            x_old = np.linspace(0, 1, len(data))
            x_new = np.linspace(0, 1, n)
            data = np.stack([np.interp(x_new, x_old, data[:, c]) for c in range(2)], axis=1).astype(np.int16)
        _cache[path] = np.ascontiguousarray(data)
    return _cache[path]


def _sound_path(kind):
    key = f'{kind}_sound_file'
    sounds = config.current().values['sounds']
    custom = config.current().resolve_path(sounds[key]) if key in sounds else ''
    if custom:
        return custom
    return os.path.join(ASSETS, f'{kind}.wav')


def play_file(path, wait=False):
    """Queue a WAV on the persistent stream. wait=True blocks until it has played. Never raises."""
    global _data, _pos
    try:
        if _ensure_stream() is None:
            return
        data = _load(path)
        _done.clear()
        with _lock:
            _data = data
            _pos = 0
        if wait:
            _done.wait(timeout=3.0)
    except Exception as e:
        config.log(f'Could not play {path}: {e}')


def play(kind, wait=False):
    """kind = 'start', 'stop' or 'done'; honours sounds.<kind>_sound."""
    if not config.get('sounds', f'{kind}_sound'):
        return
    play_file(_sound_path(kind), wait=wait)
