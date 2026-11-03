"""Draw the app icon: a red D on a black circle (plus tray variants).

    python tools/make_icons.py

Writes into dictator/assets/:
  icon.png / icon.ico      the app icon (idle state)
  tray-recording.png       red ring = recording
  tray-transcribing.png    amber ring = transcribing
Requires Pillow (only to regenerate the icons, not to run the app).
"""
import os

from PIL import Image, ImageDraw

OUT = os.path.join(os.path.dirname(__file__), '..', 'dictator', 'assets')
RED = (229, 40, 45, 255)
AMBER = (255, 179, 0, 255)
BLACK = (17, 17, 17, 255)
SS = 4          # supersampling for smooth edges


def draw(size, ring=None):
    s = size * SS
    img = Image.new('RGBA', (s, s), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    pad = s * 0.02
    if ring:
        d.ellipse([pad, pad, s - pad, s - pad], fill=ring)
        inner = s * 0.09
        d.ellipse([inner, inner, s - inner, s - inner], fill=BLACK)
    else:
        d.ellipse([pad, pad, s - pad, s - pad], fill=BLACK)
    # The D: a thick stem and a round bowl, with the counter cut out in black
    top, bottom = s * 0.25, s * 0.75
    left, right = s * 0.28, s * 0.74
    stem, bar = s * 0.135, s * 0.115   # stroke width, vertical and horizontal
    half(d, left, right, top, bottom, RED)
    half(d, left + stem, right - stem, top + bar, bottom - bar, BLACK)
    return img.resize((size, size), Image.LANCZOS)


def half(d, left, right, top, bottom, fill):
    """A D shape: straight on the left, a half ellipse on the right."""
    radius = (bottom - top) / 2
    mid = right - radius
    d.rectangle([left, top, mid, bottom], fill=fill)
    d.pieslice([mid - radius, top, right, bottom], -90, 90, fill=fill)


def main():
    os.makedirs(OUT, exist_ok=True)
    base = draw(256)
    base.save(os.path.join(OUT, 'icon.png'))
    base.save(os.path.join(OUT, 'icon.ico'), sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    draw(256, RED).save(os.path.join(OUT, 'tray-recording.png'))
    draw(256, AMBER).save(os.path.join(OUT, 'tray-transcribing.png'))
    print('icons written to', os.path.abspath(OUT))


if __name__ == '__main__':
    main()
