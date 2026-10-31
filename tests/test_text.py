import os
import sys

import numpy as np

from voxkeypaste import clip_saver, dictionary
from voxkeypaste.transcriber import Transcriber, post_process


def test_dictionary_rules(tmp_path, cfg):
    path = tmp_path / 'fixes.txt'
    path.write_text('# comment\nbuguea=pushea\n\nmal = bien\nno-equals-line\n', encoding='utf-8')
    rules = dictionary.load_rules(str(path))
    assert rules == [('buguea', 'pushea'), ('mal', 'bien')]
    text = dictionary.apply_rules('Buguea el cambio, no lo bugueaste. Muy mal.', rules)
    assert text == 'Pushea el cambio, no lo bugueaste. Muy bien.'
    cfg.set('output', 'dictionary_file', str(path))
    assert dictionary.apply('lo buguea') == 'lo pushea'


def test_dictionary_missing_file_is_harmless(cfg):
    cfg.set('output', 'dictionary_file', 'does-not-exist.txt')
    assert dictionary.apply('hola') == 'hola'


def test_post_process(cfg):
    assert post_process('  Hola mundo.  ', cfg) == 'Hola mundo. '
    cfg.set('output', 'remove_trailing_period', True)
    cfg.set('output', 'lowercase', True)
    cfg.set('output', 'add_trailing_space', False)
    assert post_process('Hola Mundo.', cfg) == 'hola mundo'
    assert post_process('Y entonces...', cfg) == 'y entonces...'
    assert post_process('   ', cfg) == ''


def test_api_key_placeholder_for_own_servers(cfg, monkeypatch):
    monkeypatch.delenv('OPENAI_API_KEY', raising=False)
    assert Transcriber(cfg).api_key() == 'not-needed'
    cfg.set('transcription', 'api_key', 'sk-test')
    assert Transcriber(cfg).api_key() == 'sk-test'


def test_build_command_does_not_use_a_shell():
    for windows in (True, False):
        cmd = clip_saver.build_command('scp -q {audio} {text} "user@host:/my clips/"', r'C:\a b\x.flac', 'x.txt',
                                       windows=windows)
        assert cmd == ['scp', '-q', r'C:\a b\x.flac', 'x.txt', 'user@host:/my clips/']


def test_windows_paths_keep_their_backslashes():
    template = r'C:\Windows\System32\OpenSSH\scp.exe -B {audio} "C:\Program Files\x" u@h:/c/'
    assert clip_saver.build_command(template, 'a', 't', windows=True) == [
        r'C:\Windows\System32\OpenSSH\scp.exe', '-B', 'a', r'C:\Program Files\x', 'u@h:/c/']


def _save_now(cfg, tmp_path, command):
    cfg.set('clips', 'enabled', True)
    cfg.set('clips', 'folder', str(tmp_path / 'clips'))
    cfg.set('clips', 'upload_command', command)
    audio = (np.sin(np.arange(32000) / 10) * 3000).astype(np.int16)
    clip_saver._save(audio, 16000, 'hola mundo')
    return sorted(os.listdir(tmp_path / 'clips'))


def test_clip_saved_and_kept_when_upload_fails(cfg, tmp_path):
    exe = sys.executable.replace('\\', '/')
    files = _save_now(cfg, tmp_path, f'"{exe}" -c "raise SystemExit(1)" {{audio}} {{text}}')
    assert [f.rsplit('.', 1)[1] for f in files] == ['flac', 'txt']


def test_clip_deleted_after_successful_upload(cfg, tmp_path):
    exe = sys.executable.replace('\\', '/')
    dest = str(tmp_path / 'sent').replace('\\', '/')
    os.makedirs(dest)
    script = f'import shutil,sys; [shutil.copy(p, \'{dest}\') for p in sys.argv[1:]]'
    files = _save_now(cfg, tmp_path, f'"{exe}" -c "{script}" {{audio}} {{text}}')
    assert files == []
    assert len(os.listdir(dest)) == 2


def test_short_clips_are_not_saved(cfg, tmp_path):
    cfg.set('clips', 'enabled', True)
    cfg.set('clips', 'folder', str(tmp_path / 'clips'))
    clip_saver._save(np.zeros(4000, dtype=np.int16), 16000, 'hola')     # 0.25 s < 1 s
    assert not (tmp_path / 'clips').exists()


def test_list_models_rejects_bad_urls():
    import pytest
    from voxkeypaste.transcriber import TranscriptionError, list_models
    for url in ('', 'ftp://x', 'file:///etc/passwd', '192.168.1.10:8000/v1'):
        with pytest.raises(TranscriptionError):
            list_models(url)
