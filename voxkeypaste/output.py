"""Write the text into the focused window: paste it at once, or type it key by key."""
import sys
import time

from . import config


def _paste(text):
    import pyperclip
    from pynput.keyboard import Controller, Key
    keyboard = Controller()
    try:
        previous = pyperclip.paste()
    except Exception:
        previous = None
    pyperclip.copy(text)
    time.sleep(0.05)
    modifier = Key.cmd if sys.platform == 'darwin' else Key.ctrl
    with keyboard.pressed(modifier):
        keyboard.press('v')
        keyboard.release('v')
    time.sleep(0.3)                     # let the target app read the clipboard before restoring it
    if previous:                        # (only text can be restored; an image on the clipboard is lost)
        try:
            pyperclip.copy(previous)
        except Exception:
            pass


def _type(text, delay):
    from pynput.keyboard import Controller
    keyboard = Controller()
    for char in text:
        keyboard.type(char)
        if delay:
            time.sleep(delay)


def write(text, cfg):
    if not text:
        return
    try:
        if cfg.get('output', 'method') == 'type':
            _type(text, cfg.get('output', 'type_delay_ms') / 1000.0)
        else:
            _paste(text)
    except Exception as e:
        config.log(f'Could not write the text: {type(e).__name__}: {e}')
