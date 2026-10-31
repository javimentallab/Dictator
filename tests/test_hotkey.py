import threading
import time

import pytest
from pynput.keyboard import Key, KeyCode

from voxkeypaste import hotkey


def test_parse():
    assert hotkey.parse('F8') == frozenset({'f8'})
    assert hotkey.parse('Ctrl + Shift + Space') == frozenset({'ctrl', 'shift', 'space'})
    assert hotkey.parse('control+win+d') == frozenset({'ctrl', 'cmd', 'd'})
    with pytest.raises(ValueError):
        hotkey.parse(' + ')


def test_key_names():
    assert hotkey.key_name(Key.f8) == 'f8'
    assert hotkey.key_name(Key.ctrl_l) == 'ctrl'
    assert hotkey.key_name(Key.shift_r) == 'shift'
    assert hotkey.key_name(KeyCode.from_char('D')) == 'd'
    assert hotkey.key_name(KeyCode(vk=68, char='\x04')) == 'd'      # Ctrl+D gives a control char
    assert hotkey.key_name(Key.space) == 'space'


def test_chord_edges():
    state = hotkey.ChordState(hotkey.parse('ctrl+d'))
    assert state.update('ctrl', True) is None
    assert state.update('d', True) == 'press'
    assert state.update('d', True) is None                  # key auto-repeat: no new edge
    assert state.update('d', False) == 'release'
    assert state.update('d', True) == 'press'
    assert state.update('ctrl', False) == 'release'


def test_slow_handler_does_not_lose_key_releases():
    """Regression: a handler that takes long (e.g. waiting for the start sound) used to block the
    keyboard hook, the key release was lost and the NEXT press was ignored ("press F8 twice")."""
    presses = []

    def slow_press():
        presses.append(time.time())
        time.sleep(0.6)                                      # as long as the start sound

    listener = hotkey.HotkeyListener('f8', slow_press, lambda: None)
    worker = threading.Thread(target=listener._loop, daemon=True)
    worker.start()
    for _ in range(2):                                       # two quick presses, as a user stopping
        listener._queue.put(('f8', True))
        listener._queue.put(('f8', False))
    listener._queue.put(None)
    worker.join(timeout=3)
    assert len(presses) == 2


def test_only_single_ordinary_keys_are_swallowed():
    assert hotkey.swallowable_vk(hotkey.parse('f8')) == 0x77
    assert hotkey.swallowable_vk(hotkey.parse('f12')) == 0x7B
    assert hotkey.swallowable_vk(hotkey.parse('pause')) is not None
    assert hotkey.swallowable_vk(hotkey.parse('ctrl')) is None            # never a modifier
    assert hotkey.swallowable_vk(hotkey.parse('ctrl+shift+space')) is None  # never inside a combination


class _Data:
    def __init__(self, vk):
        self.vkCode = vk


class _FakeListener:
    def __init__(self):
        self.suppressed = 0

    def suppress_event(self):
        self.suppressed += 1


def test_windows_filter_swallows_the_hotkey_but_still_reports_it():
    listener = hotkey.HotkeyListener('f8', lambda: None, lambda: None, swallow=True)
    listener._listener = _FakeListener()
    assert listener._win32_filter(0x0100, _Data(0x41)) is True             # other keys pass untouched
    listener._win32_filter(0x0100, _Data(0x77))                            # F8 down (and its auto-repeat)
    listener._win32_filter(0x0100, _Data(0x77))
    listener._win32_filter(0x0101, _Data(0x77))                            # F8 up
    assert listener._listener.suppressed == 3
    assert [listener._queue.get_nowait() for _ in range(3)] == [('f8', True), ('f8', True), ('f8', False)]
    listener.paused = True                                                 # paused: F8 reaches the programs
    assert listener._win32_filter(0x0100, _Data(0x77)) is True
