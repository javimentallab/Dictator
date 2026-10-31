"""Global hotkey listener (pynput).

Two rules learnt the hard way:
* The callbacks run inside the operating system's keyboard hook. They must
  return immediately: on Windows a hook that takes too long stops receiving
  events and key releases get lost (the app then believes the key is still
  held and the next press is ignored). Here they only put an event in a queue;
  a separate thread delivers it.
* Only ONE listener is ever created; start() is idempotent.
"""
import queue
import sys
import threading

from . import config

MODIFIERS = {'ctrl', 'shift', 'alt', 'cmd'}
ALIASES = {'control': 'ctrl', 'win': 'cmd', 'super': 'cmd', 'meta': 'cmd', 'command': 'cmd',
           'option': 'alt', 'altgr': 'alt', 'return': 'enter', 'escape': 'esc', 'del': 'delete',
           'pgup': 'page_up', 'pgdn': 'page_down', 'spacebar': 'space'}


def parse(text):
    """'ctrl+shift+space' -> frozenset({'ctrl', 'shift', 'space'}). Raises ValueError if empty."""
    keys = set()
    for part in str(text or '').lower().replace(' ', '').split('+'):
        if not part:
            continue
        keys.add(ALIASES.get(part, part))
    if not keys:
        raise ValueError('empty hotkey')
    return frozenset(keys)


def key_name(key):
    """Normalise a pynput key to the names used by parse()."""
    name = getattr(key, 'name', None)            # pynput.keyboard.Key members
    if name:
        for mod in MODIFIERS:
            if name == mod or name.startswith(mod + '_'):
                return mod
        if name == 'alt_gr':
            return 'alt'
        return name
    char = getattr(key, 'char', None)
    vk = getattr(key, 'vk', None)
    if vk is not None and (48 <= vk <= 57 or 65 <= vk <= 90):
        return chr(vk).lower()                   # letters/digits even with Ctrl held (char is a control code then)
    if char:
        return char.lower()
    if vk is not None:
        return f'vk{vk}'
    return None


class ChordState:
    """Tracks pressed keys and reports press/release EDGES of the chord."""

    def __init__(self, chord):
        self.chord = chord
        self.pressed = set()
        self.active = False

    def update(self, name, is_press):
        """Returns 'press', 'release' or None."""
        if name is None:
            return None
        if is_press:
            self.pressed.add(name)
        else:
            self.pressed.discard(name)
        now = self.chord <= self.pressed
        if now and not self.active:
            self.active = True
            return 'press'
        if not now and self.active:
            self.active = False
            return 'release'
        return None

    def reset(self):
        self.pressed.clear()
        self.active = False


_WM_KEYDOWN, _WM_SYSKEYDOWN = 0x0100, 0x0104


def windows_vk(name):
    """Virtual-key code of a single key name ('f8', 'd', '5', 'pause'...), or None if unknown."""
    if name.startswith('f') and name[1:].isdigit() and 1 <= int(name[1:]) <= 24:
        return 0x70 + int(name[1:]) - 1
    if len(name) == 1 and name.isalnum():
        return ord(name.upper())
    try:
        from pynput.keyboard import Key
        return getattr(Key, name).value.vk
    except Exception:
        return None


def swallowable_vk(chord):
    """The key to keep away from the other programs: only a hotkey made of ONE ordinary key.
    Modifiers are never swallowed (a lost Ctrl/Alt/Shift/Win release leaves the key 'stuck' for the
    whole system), and neither are keys of a combination (Ctrl+Shift alone switches the keyboard layout)."""
    if len(chord) != 1:
        return None
    name = next(iter(chord))
    if name in MODIFIERS:
        return None
    return windows_vk(name)


class HotkeyListener:
    def __init__(self, hotkey, on_press, on_release, swallow=False):
        self.state = ChordState(parse(hotkey))
        self.on_press = on_press
        self.on_release = on_release
        self._queue = queue.Queue()
        self._listener = None
        self._worker = None
        self.paused = False
        self._swallow_vk = swallowable_vk(self.state.chord) if swallow else None

    def start(self):
        if self._listener is not None:
            return
        from pynput import keyboard
        options = {}
        if self._swallow_vk is not None and sys.platform == 'win32':
            options['win32_event_filter'] = self._win32_filter
        self._listener = keyboard.Listener(on_press=lambda k: self._queue.put((key_name(k), True)),
                                           on_release=lambda k: self._queue.put((key_name(k), False)),
                                           **options)
        self._listener.daemon = True
        self._listener.start()
        self._worker = threading.Thread(target=self._loop, name='hotkey', daemon=True)
        self._worker.start()

    def _win32_filter(self, msg, data):
        """Runs inside the Windows keyboard hook: must be instant. Keeps the hotkey (and its auto-repeat)
        away from the focused program, while still telling VoxKeyPaste about it."""
        if data.vkCode != self._swallow_vk or self.paused:
            return True
        name = next(iter(self.state.chord))
        self._queue.put((name, msg in (_WM_KEYDOWN, _WM_SYSKEYDOWN)))
        self._listener.suppress_event()

    def stop(self):
        if self._listener is not None:
            self._listener.stop()
            self._listener = None
        self._queue.put(None)

    def _loop(self):
        while True:
            item = self._queue.get()
            if item is None:
                return
            name, is_press = item
            try:
                edge = self.state.update(name, is_press)
                if self.paused or edge is None:
                    continue
                (self.on_press if edge == 'press' else self.on_release)()
            except Exception as e:
                config.log(f'Hotkey handler error: {type(e).__name__}: {e}')
