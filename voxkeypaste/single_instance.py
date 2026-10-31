"""Make sure only one WhisperWriter runs at a time (two would fight over the hotkey).

Windows: a named mutex in the session namespace (shared by elevated and
non-elevated processes). Elsewhere: an exclusive lock on a file.
"""
import os
import sys
import tempfile

_handle = None
_NAME = 'VoxKeyPasteSingleton'


def acquire():
    """True if this is the only instance; False if another one is running."""
    global _handle
    if sys.platform == 'win32':
        import ctypes
        kernel32 = ctypes.windll.kernel32
        kernel32.CreateMutexW.restype = ctypes.c_void_p
        _handle = kernel32.CreateMutexW(None, False, _NAME)
        return kernel32.GetLastError() != 183   # ERROR_ALREADY_EXISTS
    import fcntl
    path = os.path.join(tempfile.gettempdir(), f'{_NAME}-{os.getuid()}.lock')
    _handle = open(path, 'w')
    try:
        fcntl.flock(_handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return True
    except OSError:
        return False


def release():
    """Release the lock (before starting a new copy of the app on restart)."""
    global _handle
    if _handle is None:
        return
    if sys.platform == 'win32':
        import ctypes
        ctypes.windll.kernel32.CloseHandle(ctypes.c_void_p(_handle))
    else:
        try:
            _handle.close()
        except OSError:
            pass
    _handle = None
