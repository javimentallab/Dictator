"""Audio device helpers.

* Find input/output devices by NAME instead of by index: Windows renumbers the
  audio devices after a reboot or when USB devices are plugged in/out, and a
  fixed index ends up pointing at another device (recording silence).
* PortAudio reads the device list only once, when sounddevice is imported, so
  it does not notice those changes. On Windows the live MME device list is
  cheap to read through winmm; when it differs from the one PortAudio started
  with, PortAudio is re-initialised (only when no stream is open).
"""
import sys
import threading

import sounddevice as sd

from . import config

_IS_WINDOWS = sys.platform == 'win32'
_refresh_callbacks = []
_lock = threading.Lock()
refresh_lock = _lock   # held while PortAudio is re-initialised: open streams only outside it


def _preferred_hostapi_index():
    """On Windows prefer MME (same names Windows shows; widest compatibility)."""
    if not _IS_WINDOWS:
        return None
    for i, api in enumerate(sd.query_hostapis()):
        if 'MME' in api['name']:
            return i
    return None


def find_device(name, kind='input'):
    """Index of the first device whose name starts with `name` (case-insensitive), or None."""
    if not name or not str(name).strip():
        return None
    name = str(name).strip().lower()
    channels_key = 'max_input_channels' if kind == 'input' else 'max_output_channels'
    try:
        devices = sd.query_devices()
        preferred = _preferred_hostapi_index()
        candidates = [i for i, d in enumerate(devices)
                      if d[channels_key] > 0 and d['name'].strip().lower().startswith(name)]
        if not candidates:
            return None
        if preferred is not None:
            for i in candidates:
                if devices[i]['hostapi'] == preferred:
                    return i
        return candidates[0]
    except Exception:
        return None


def find_device_by_full_name(full_name, kind='output'):
    """Index of the device Windows calls `full_name`. MME cuts names to 31 characters, so a device
    matches when its name is the whole name or the start of it; the longest match wins and MME is
    preferred. None if there is no match."""
    if not full_name or not str(full_name).strip():
        return None
    full = str(full_name).strip().lower()
    channels_key = 'max_input_channels' if kind == 'input' else 'max_output_channels'
    try:
        devices = sd.query_devices()
        preferred = _preferred_hostapi_index()
        candidates = [i for i, d in enumerate(devices)
                      if d[channels_key] > 0 and d['name'].strip() and full.startswith(d['name'].strip().lower())]
        if not candidates:
            return None
        if preferred is not None and any(devices[i]['hostapi'] == preferred for i in candidates):
            candidates = [i for i in candidates if devices[i]['hostapi'] == preferred]
        return max(candidates, key=lambda i: len(devices[i]['name'].strip()))
    except Exception:
        return None


def _windows_default_output_name():
    """Friendly name of the Windows default playback device (Core Audio, multimedia role), or None.
    Runs in its own thread with COM initialised (the calling thread may not have it)."""
    result = {}

    def runner():
        try:
            import comtypes
            from pycaw.pycaw import AudioUtilities
            comtypes.CoInitialize()
            try:
                result['name'] = AudioUtilities.GetSpeakers().FriendlyName
            finally:
                comtypes.CoUninitialize()
        except Exception:
            pass

    t = threading.Thread(target=runner, name='default-output', daemon=True)
    t.start()
    t.join(timeout=2)
    return result.get('name')


def default_output_device():
    """Index of the device Windows uses as its default output right now, or None (= PortAudio's default).
    PortAudio's own MME default is not the Windows default: it can point at a device another program
    holds (e.g. a Voicemeeter bus) and does not follow later changes."""
    if not _IS_WINDOWS:
        return None
    return find_device_by_full_name(_windows_default_output_name(), 'output')


def resolve_input_device(name, configured=None):
    """Device to record from: by name if configured and found, else the numeric index, else default."""
    try:
        configured = int(configured) if configured not in (None, '') else None
    except (TypeError, ValueError):
        configured = None
    if name:
        index = find_device(name, 'input')
        if index is not None:
            if configured is not None and index != configured:
                config.log(
                    f"Input device '{name}' is now at index {index} (config says {configured}); using {index}.")
            return index
        config.log(f"Input device '{name}' not found; falling back to the configured index.")
    return configured


# --- Windows: detect changes in the device list -------------------------------------------------
if _IS_WINDOWS:
    import ctypes

    class _WAVEINCAPSW(ctypes.Structure):
        _fields_ = [('wMid', ctypes.c_ushort), ('wPid', ctypes.c_ushort), ('vDriverVersion', ctypes.c_uint),
                    ('szPname', ctypes.c_wchar * 32), ('dwFormats', ctypes.c_uint),
                    ('wChannels', ctypes.c_ushort), ('wReserved1', ctypes.c_ushort)]

    class _WAVEOUTCAPSW(ctypes.Structure):
        _fields_ = _WAVEINCAPSW._fields_ + [('dwSupport', ctypes.c_uint)]


def _device_signature():
    """Names of the MME inputs and outputs Windows sees right now (None elsewhere or on error)."""
    if not _IS_WINDOWS:
        return None
    try:
        w = ctypes.windll.winmm
        sig = []
        for get_num, get_caps, cls in ((w.waveInGetNumDevs, w.waveInGetDevCapsW, _WAVEINCAPSW),
                                       (w.waveOutGetNumDevs, w.waveOutGetDevCapsW, _WAVEOUTCAPSW)):
            names = []
            for i in range(get_num()):
                caps = cls()
                if get_caps(ctypes.c_size_t(i), ctypes.byref(caps), ctypes.sizeof(caps)) == 0:
                    names.append(caps.szPname)
            sig.append(tuple(names))
        return tuple(sig)
    except Exception:
        return None


_signature = _device_signature()   # the list PortAudio was initialised with


def on_refresh(callback):
    """Register a function called right BEFORE PortAudio is re-initialised (to close open streams)."""
    _refresh_callbacks.append(callback)


def refresh_if_changed(only_if=None):
    """Re-initialise PortAudio if the system device list changed. Call only with no recording open.
    only_if: optional callable checked under the lock (e.g. "still idle"); False skips the refresh.
    Returns True if it refreshed. Never raises."""
    global _signature
    with _lock:
        if only_if is not None and not only_if():
            return False
        sig = _device_signature()
        if sig is None or sig == _signature:
            return False
        try:
            for cb in _refresh_callbacks:
                try:
                    cb()
                except Exception:
                    pass
            sd._terminate()
            sd._initialize()
            _signature = sig
            config.log('Audio device list changed: PortAudio refreshed.')
            return True
        except Exception:
            return False
