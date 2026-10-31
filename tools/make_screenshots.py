"""Render the README screenshots (in English) into docs/.

    python tools/make_screenshots.py [language]

Uses a throw-away settings file with the defaults, so personal settings never
end up in the pictures. Requires Pillow to compose the cover image.
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
# A generic, non-existent path: the real one would show the user name in the pictures.
os.environ['VOXKEYPASTE_CONFIG'] = r'C:\Users\you\AppData\Roaming\VoxKeyPaste\config.yaml'

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtGui import QAction  # noqa: E402
from PySide6.QtWidgets import QApplication, QMenu  # noqa: E402

from voxkeypaste import config, i18n  # noqa: E402
from voxkeypaste.app import RECORDING, TRANSCRIBING, StatusWindow  # noqa: E402
from voxkeypaste.settings_window import SettingsWindow  # noqa: E402

OUT = os.path.join(ROOT, 'docs')


def grab(widget, name):
    widget.setAttribute(Qt.WA_DontShowOnScreen, True)
    widget.show()
    QApplication.processEvents()
    path = os.path.join(OUT, name)
    widget.grab().save(path)
    return path


def main():
    lang = sys.argv[1] if len(sys.argv) > 1 else 'en'
    os.makedirs(OUT, exist_ok=True)
    cfg = config.init()
    cfg.set('recording', 'hotkey', 'f8')
    i18n.set_language(lang)
    app = QApplication([])

    settings = SettingsWindow(cfg)
    settings.findChild(type(settings.tabs)).setCurrentIndex(config.SECTIONS.index('recording'))
    shots = [grab(settings, 'settings.png')]

    menu = QMenu()
    state = QAction(i18n.tr('ui.status.ready', hotkey='F8'), menu)
    state.setEnabled(False)
    menu.addAction(state)
    menu.addSeparator()
    pause = QAction(i18n.tr('ui.tray.pause'), menu, checkable=True)
    menu.addAction(pause)
    for key in ('ui.tray.settings', None, 'ui.tray.restart', 'ui.tray.quit'):
        menu.addSeparator() if key is None else menu.addAction(QAction(i18n.tr(key), menu))
    shots.append(grab(menu, 'tray-menu.png'))

    for state_name in (RECORDING, TRANSCRIBING):
        pill = StatusWindow()
        pill.setAttribute(Qt.WA_DontShowOnScreen, True)     # never flash on the real screen
        pill.show_state(state_name)
        shots.append(grab(pill, f'status-{state_name}.png'))

    compose_cover(shots)
    print('screenshots written to', OUT)


def compose_cover(paths):
    from PIL import Image
    settings, menu, recording, transcribing = (Image.open(p).convert('RGBA') for p in paths)
    pad = 40
    right_w = max(menu.width, recording.width, transcribing.width)
    width = settings.width + right_w + pad * 3
    height = max(settings.height, menu.height + recording.height + transcribing.height + pad * 2) + pad * 2
    cover = Image.new('RGBA', (width, height), (24, 24, 27, 255))
    cover.alpha_composite(settings, (pad, pad))
    x = settings.width + pad * 2
    y = pad
    for img in (menu, recording, transcribing):
        cover.alpha_composite(img, (x, y))
        y += img.height + pad
    cover.convert('RGB').save(os.path.join(OUT, 'cover.png'), optimize=True)


if __name__ == '__main__':
    main()
