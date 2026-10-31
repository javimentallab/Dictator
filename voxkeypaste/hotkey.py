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


class HotkeyListener:
    def __init__(self, hotkey, on_press, on_release):
        self.state = ChordState(parse(hotkey))
        self.on_press = on_press
        self.on_release = on_release
        self._queue = queue.Queue()
        self._listener = None
        self._worker = None
        self.paused = False

    def start(self):
        if self._listener is not None:
            return
        from pynput import keyboard
        self._listener = keyboard.Listener(on_press=lambda k: self._queue.put((k, True)),
                                           on_release=lambda k: self._queue.put((k, False)))
        self._listener.daemon = True
        self._listener.start()
        self._worker = threading.Thread(target=self._loop, name='hotkey', daemon=True)
        self._worker.start()

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
            key, is_press = item
            try:
                edge = self.state.update(key_name(key), is_press)
                if self.paused or edge is None:
                    continue
                (self.on_press if edge == 'press' else self.on_release)()
            except Exception as e:
                config.log(f'Hotkey handler error: {type(e).__name__}: {e}')
