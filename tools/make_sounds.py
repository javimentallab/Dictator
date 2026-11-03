"""Generate the built-in sounds (dictator/assets/start.wav, stop.wav, done.wav).

They are synthesised here, so the project owns them (no third-party audio).
Low marimba-like tones: a woody fundamental plus the marimba's quiet 4th and
9th partials, fast attack and exponential decay. Start rises C4->G4, stop
falls G4->C4, done is a single soft G4.

    python tools/make_sounds.py [output_dir]
"""
import os
import sys
import wave

import numpy as np

SR = 48000


def env(t, attack, decay):
    return np.minimum(1, t / attack) * np.exp(-t * decay)


def marimba(freq, dur=0.5):
    t = np.arange(int(SR * dur)) / SR
    return (np.sin(2 * np.pi * freq * t) * env(t, .003, 7)
            + 0.25 * np.sin(2 * np.pi * freq * 3.93 * t) * env(t, .002, 30)
            + 0.08 * np.sin(2 * np.pi * freq * 9.2 * t) * env(t, .001, 60))


def sequence(tones, gap):
    total = int(SR * gap * (len(tones) - 1)) + max(len(x) for x in tones)
    out = np.zeros(total)
    for i, tone in enumerate(tones):
        start = int(SR * gap * i)
        out[start:start + len(tone)] += tone
    fade = int(SR * 0.02)                         # gentle fade-out at the very end
    out[-fade:] *= np.linspace(1, 0, fade)
    return out


def write(path, mono, peak=0.4):
    mono = mono / np.max(np.abs(mono)) * peak
    data = (np.repeat(mono[:, None], 2, axis=1) * 32767).astype('<i2')
    with wave.open(path, 'wb') as wf:
        wf.setnchannels(2)
        wf.setsampwidth(2)
        wf.setframerate(SR)
        wf.writeframes(data.tobytes())


def main():
    out_dir = sys.argv[1] if len(sys.argv) > 1 else os.path.join(os.path.dirname(__file__), '..', 'dictator', 'assets')
    c4, g4 = 261.63, 392.0
    write(os.path.join(out_dir, 'start.wav'), sequence([marimba(c4) * .8, marimba(g4)], gap=0.09))
    write(os.path.join(out_dir, 'stop.wav'), sequence([marimba(g4), marimba(c4) * .8], gap=0.09))
    write(os.path.join(out_dir, 'done.wav'), sequence([marimba(g4, 0.4)], gap=0.09), peak=0.25)
    print('written to', os.path.abspath(out_dir))


if __name__ == '__main__':
    main()
