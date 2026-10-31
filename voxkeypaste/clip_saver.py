"""Save every dictation (FLAC audio + .txt transcription), e.g. to build a voice dataset.

Runs in a background thread and swallows every error: it must never delay or
break the dictation. If clip_saving.upload_command is set, it is run for each
saved clip ({audio} and {text} are replaced by the file paths); on success the
local files are deleted, on failure they stay and are retried next time.
"""
import os
import shlex
import subprocess
import sys
import threading
import time

import soundfile as sf

from . import config

_upload_lock = threading.Lock()


def _cfg(key):
    return config.get('clips', key)


def folder():
    return config.current().resolve_path(_cfg('folder')) or os.path.join(config.current().directory, 'clips')


def save(audio_data, sample_rate, text):
    """Call after the result is emitted. Returns immediately."""
    if not _cfg('enabled'):
        return
    threading.Thread(target=_save, args=(audio_data, sample_rate, text), daemon=True).start()


def _save(audio_data, sample_rate, text):
    try:
        text = (text or '').strip()
        if not text or audio_data is None or not sample_rate:
            return
        if len(audio_data) / sample_rate < float(_cfg('min_duration_s') or 0):
            return
        out = folder()
        os.makedirs(out, exist_ok=True)
        base = time.strftime('%Y%m%d-%H%M%S') + f'-{int(time.time() * 1000) % 1000:03d}'
        sf.write(os.path.join(out, base + '.flac'), audio_data, sample_rate, format='FLAC')
        with open(os.path.join(out, base + '.txt'), 'w', encoding='utf-8', newline='\n') as f:
            f.write(text + '\n')
        upload_pending()
    except Exception as e:
        config.log(f'clip_saving: could not save the clip ({type(e).__name__}: {e})')


def build_command(template, audio, text):
    """Split the template like a shell would and substitute the placeholders (no shell is used)."""
    parts = shlex.split(template, posix=True)
    return [p.replace('{audio}', audio).replace('{text}', text) for p in parts]


def upload_pending():
    template = _cfg('upload_command')
    if not template or not _upload_lock.acquire(blocking=False):
        return
    try:
        out = folder()
        for name in sorted(os.listdir(out)):
            if not name.endswith('.txt'):
                continue
            base = os.path.join(out, name[:-4])
            pair = (base + '.flac', base + '.txt')
            if not os.path.exists(pair[0]):
                continue
            flags = subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0
            result = subprocess.run(build_command(template, *pair), stdout=subprocess.DEVNULL,
                                    stderr=subprocess.DEVNULL, timeout=60, creationflags=flags)
            if result.returncode != 0:
                config.log('clip_saving: upload failed, the clip stays in the folder')
                return
            for p in pair:
                os.remove(p)
    except Exception as e:
        config.log(f'clip_saving: upload error ({type(e).__name__}: {e})')
    finally:
        _upload_lock.release()
