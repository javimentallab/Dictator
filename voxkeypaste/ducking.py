"""Silence the computer's audio while dictating (Windows only; a no-op elsewhere).

Two independent ways, both optional:
* ducking.mute_system_output: mute the default output device (the Windows
  master mute) and put it back as it was afterwards.
* ducking.voicemeeter_mute_strips: mute some Voicemeeter strips (e.g. its
  virtual inputs, where all the PC's audio goes).

Individual programs are never touched. Everything is undone as soon as the
user stops (so the stop sound can be heard). What was changed is written to a
state file first, so if the app dies in the middle it is undone on the next
start. Errors are logged and never break the dictation.
"""
import json
import os
import sys
import threading
import time

from . import config

IS_WINDOWS = sys.platform == 'win32'

_lock = threading.Lock()
_changed = {}          # what we changed and must undo: {'endpoint': id, 'endpoint_was_muted': bool, 'strips': [...]}
_vm = None
_timer = None


def _cfg(key):
    return config.get('ducking', key)


def enabled():
    return IS_WINDOWS and bool(_cfg('enabled'))


def parse_strips(text):
    strips = []
    for item in str(text or '').split(','):
        item = item.strip()
        if not item:
            continue
        try:
            strips.append(int(item))
        except ValueError:
            config.log(f"ducking: ignoring strip '{item}' (not a number)")
    return strips


def _state_file():
    return os.path.join(config.current().directory, 'ducking-state.json')


def _save_state():
    try:
        with open(_state_file(), 'w', encoding='utf-8') as f:
            json.dump(_changed, f)
    except OSError:
        pass


def _clear_state():
    try:
        os.remove(_state_file())
    except OSError:
        pass


def _with_com(func, *args):
    """Run func in a thread with COM initialised (the calling thread may not have it)."""
    result = {}

    def runner():
        import comtypes
        comtypes.CoInitialize()
        try:
            result['value'] = func(*args)
        except Exception as e:
            config.log(f'ducking: {type(e).__name__}: {e}')
        finally:
            comtypes.CoUninitialize()

    t = threading.Thread(target=runner, daemon=True)
    t.start()
    t.join(timeout=5)
    return result.get('value')


# --- Windows master mute (default output device) ---------------------------------------------
def _endpoint(device_id=None):
    from ctypes import POINTER, cast
    from comtypes import CLSCTX_ALL
    from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume
    if device_id:
        device = next((d for d in AudioUtilities.GetAllDevices() if d.id == device_id), None)
        if device is None:
            return None, None
        raw = device._dev
    else:
        raw = AudioUtilities.GetSpeakers()
        raw = getattr(raw, '_dev', raw)
        device_id = raw.GetId()
    interface = raw.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
    return device_id, cast(interface, POINTER(IAudioEndpointVolume))


def _mute_endpoint():
    device_id, volume = _endpoint()
    was_muted = bool(volume.GetMute())
    if not was_muted:
        volume.SetMute(1, None)
    return device_id, was_muted


def _restore_endpoint(device_id, was_muted):
    _, volume = _endpoint(device_id)
    if volume is not None and not was_muted:
        volume.SetMute(0, None)


# --- Voicemeeter -----------------------------------------------------------------------------------
def _vm_api():
    global _vm
    if _vm is not None:
        return _vm
    import ctypes
    try:
        dll = ctypes.cdll.LoadLibrary(_cfg('voicemeeter_dll'))
        dll.VBVMR_SetParameterFloat.argtypes = [ctypes.c_char_p, ctypes.c_float]
        dll.VBVMR_SetParameterFloat.restype = ctypes.c_long
        dll.VBVMR_Login.restype = ctypes.c_long
        dll.VBVMR_Logout.restype = ctypes.c_long
        dll.VBVMR_Login()
        _vm = dll
    except Exception as e:
        config.log(f'ducking: Voicemeeter not available ({e})')
        _vm = None
    return _vm


def _vm_set(strips, muted):
    """Set Strip[n].Mute for every strip; relogin and retry once if Voicemeeter rejects it.
    (Values are never read back: reading Voicemeeter parameters is unreliable.)"""
    import ctypes
    vm = _vm_api()
    if vm is None or not strips:
        return False
    worst = 0
    for attempt in (1, 2):
        worst = 0
        for s in strips:
            try:
                rc = vm.VBVMR_SetParameterFloat(f'Strip[{s}].Mute'.encode(), ctypes.c_float(1.0 if muted else 0.0))
            except Exception:
                rc = -99
            worst = rc if rc != 0 else worst
        if worst == 0:
            return True
        if attempt == 1:
            try:
                vm.VBVMR_Logout()
                vm.VBVMR_Login()
            except Exception:
                pass
            time.sleep(0.2)
    config.log(f'ducking: Voicemeeter did not accept the mute (rc={worst})')
    return False


# --- Public API (called from the app) --------------------------------------------------------------
def _undo(changed):
    if changed.get('strips'):
        _vm_set(changed['strips'], False)
    if changed.get('endpoint'):
        _with_com(_restore_endpoint, changed['endpoint'], changed.get('endpoint_was_muted', False))


def recover():
    """At startup: undo what a previous run left muted if it died while dictating."""
    if not IS_WINDOWS:
        return
    try:
        with open(_state_file(), encoding='utf-8') as f:
            left = json.load(f)
    except (OSError, ValueError):
        return
    _undo(left)
    _clear_state()
    config.log('ducking: undid the mute left by a previous run.')


def start():
    """Recording is about to start (the start sound has already played)."""
    global _timer
    if not enabled():
        return
    with _lock:
        strips = parse_strips(_cfg('voicemeeter_mute_strips'))
        if strips:
            _changed['strips'] = strips          # recorded BEFORE muting: always undone, even if rc said no
            _save_state()
            _vm_set(strips, True)
        if _cfg('mute_system_output'):
            result = _with_com(_mute_endpoint)
            if result:
                _changed['endpoint'], _changed['endpoint_was_muted'] = result
                _save_state()
        limit = int(_cfg('max_duration_s') or 0)
        if limit > 0:
            _timer = threading.Timer(limit, _timeout)
            _timer.daemon = True
            _timer.start()


def stop():
    """Undo everything right away (stop requested, recording finished or cancelled). Safe to repeat."""
    global _timer
    if not IS_WINDOWS:
        return
    with _lock:
        if _timer is not None:
            _timer.cancel()
            _timer = None
        if not _changed:
            return
        changed = dict(_changed)
        _changed.clear()
        _undo(changed)
        _clear_state()


def _timeout():
    config.log('ducking: max_duration_s reached, restoring the audio.')
    stop()
