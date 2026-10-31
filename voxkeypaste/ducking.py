"""Lower other audio while dictating (Windows only; a no-op elsewhere).

* Media apps (media_ducking.media_apps): their per-app volume (the Windows
  volume mixer) is lowered to media_ducking.ducked_volume percent while
  recording and restored afterwards. The original volumes are written to a
  state file first, so if the app dies while dictating they are restored on
  the next start.
* Voicemeeter (media_ducking.voicemeeter_mute_strips): optional strips muted
  while recording and unmuted as soon as recording stops.

Everything here is fail-safe: errors are logged and never break dictation.
"""
import json
import os
import sys
import threading
import time

from . import config

IS_WINDOWS = sys.platform == 'win32'

_lock = threading.Lock()
_original = {}          # session key -> original volume
_active = False
_vm = None
_vm_muted = False
_started_at = 0.0
_timer = None


def _state_file():
    return os.path.join(config.current().directory, 'ducking-state.json')


def _cfg(key):
    return config.get('ducking', key)


def enabled():
    return IS_WINDOWS and bool(_cfg('enabled'))


def parse_list(text):
    return [x.strip() for x in str(text or '').split(',') if x.strip()]


def parse_strips(text):
    strips = []
    for item in parse_list(text):
        try:
            strips.append(int(item))
        except ValueError:
            config.log(f"media_ducking: ignoring strip '{item}' (not a number)")
    return strips


# --- Windows per-app volume (pycaw) ---------------------------------------------------------------
def _media_sessions():
    """(key, ISimpleAudioVolume) for every session of a media app on the active OUTPUT devices."""
    import comtypes
    import psutil
    from comtypes import CLSCTX_ALL
    from pycaw.constants import DEVICE_STATE, EDataFlow
    from pycaw.pycaw import AudioUtilities, IAudioSessionControl2, IAudioSessionManager2, ISimpleAudioVolume

    apps = {a.lower() for a in parse_list(_cfg('media_apps'))}
    for device in AudioUtilities.GetAllDevices(EDataFlow.eRender.value, DEVICE_STATE.ACTIVE.value):
        try:
            mgr = device._dev.Activate(IAudioSessionManager2._iid_, CLSCTX_ALL, None).QueryInterface(IAudioSessionManager2)
            enum = mgr.GetSessionEnumerator()
            for i in range(enum.GetCount()):
                ctl = enum.GetSession(i).QueryInterface(IAudioSessionControl2)
                pid = ctl.GetProcessId()
                try:
                    name = psutil.Process(pid).name().lower() if pid else ''
                except psutil.Error:
                    name = ''
                if name in apps:
                    key = f'{device.id}|{pid}|{ctl.GetSessionInstanceIdentifier()}'
                    yield key, ctl.QueryInterface(ISimpleAudioVolume)
        except comtypes.COMError:
            continue


def _with_com(func, *args):
    """Run func in a thread with COM initialised (Qt/key-listener threads may not have it)."""
    result = {}

    def runner():
        import comtypes
        comtypes.CoInitialize()
        try:
            result['value'] = func(*args)
        except Exception as e:
            config.log(f'media_ducking: {type(e).__name__}: {e}')
        finally:
            comtypes.CoUninitialize()

    t = threading.Thread(target=runner, daemon=True)
    t.start()
    t.join(timeout=5)
    return result.get('value')


def _duck_media():
    factor = max(0, min(100, int(_cfg('ducked_volume') or 0))) / 100.0
    changed = 0
    for key, vol in _media_sessions():
        if key not in _original:
            _original[key] = vol.GetMasterVolume()
            vol.SetMasterVolume(_original[key] * factor, None)
            changed += 1
    if changed:
        _save_state()
    return changed


def _restore_media(saved):
    sessions = dict(_media_sessions())
    for key, volume in saved.items():
        if key in sessions:
            sessions[key].SetMasterVolume(float(volume), None)
    return len(saved)


def _save_state():
    try:
        with open(_state_file(), 'w', encoding='utf-8') as f:
            json.dump(_original, f)
    except OSError:
        pass


def _clear_state():
    try:
        os.remove(_state_file())
    except OSError:
        pass


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
        config.log(f'media_ducking: Voicemeeter not available ({e})')
        _vm = None
    return _vm


def _vm_set(strips, muted):
    """Set Strip[n].Mute for every strip; relogin and retry once if Voicemeeter rejects it."""
    import ctypes
    vm = _vm_api()
    if vm is None or not strips:
        return False
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
    config.log(f'media_ducking: Voicemeeter did not accept the mute (rc={worst})')
    return False


# --- Public API (called from the app) --------------------------------------------------------------
def recover():
    """At startup: undo a duck left behind by a previous run that died while dictating."""
    if not IS_WINDOWS:
        return
    if os.path.exists(_state_file()):
        try:
            with open(_state_file(), encoding='utf-8') as f:
                saved = json.load(f)
            _with_com(_restore_media, saved)
            config.log('media_ducking: restored the volumes of a previous run.')
        except Exception:
            pass
        _clear_state()
    if enabled():
        strips = parse_strips(_cfg('voicemeeter_mute_strips'))
        if strips:
            _vm_set(strips, False)


def start():
    """Recording is about to start (the start sound has already played)."""
    global _vm_muted, _started_at, _timer, _active
    if not enabled():
        return
    with _lock:
        _active = True
        _started_at = time.time()
        strips = parse_strips(_cfg('voicemeeter_mute_strips'))
        if strips:
            _vm_muted = _vm_set(strips, True) or _vm_muted
        _with_com(_duck_media)
        limit = int(_cfg('max_duration_s') or 0)
        if limit > 0:
            _timer = threading.Timer(limit, _timeout)
            _timer.daemon = True
            _timer.start()
    threading.Thread(target=_watch_new_sessions, name='ducking-watch', daemon=True).start()


def _watch_new_sessions():
    """Players that start playing in the middle of a dictation are lowered too."""
    import comtypes
    comtypes.CoInitialize()
    try:
        while True:
            time.sleep(0.5)
            with _lock:
                if not _active:
                    return
                try:
                    _duck_media()
                except Exception:
                    pass
    finally:
        comtypes.CoUninitialize()


def release_voicemeeter():
    """Recording stop requested: unmute Voicemeeter right away so the stop sound is heard."""
    global _vm_muted
    if not enabled():
        return
    with _lock:
        if _vm_muted:
            _vm_set(parse_strips(_cfg('voicemeeter_mute_strips')), False)
            _vm_muted = False


def stop():
    """Recording finished (or was cancelled): restore everything. Safe to call several times."""
    global _original, _timer, _active
    if not IS_WINDOWS:
        return
    release_voicemeeter()
    with _lock:
        _active = False
        if _timer is not None:
            _timer.cancel()
            _timer = None
        if _original:
            saved, _original = _original, {}
            _with_com(_restore_media, saved)
            _clear_state()


def _timeout():
    config.log('media_ducking: max_duration reached, restoring the volume.')
    stop()
