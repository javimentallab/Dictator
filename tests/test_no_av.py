"""VoxKeyPaste installs faster-whisper without PyAV (av), because it only ever hands it arrays.

What gets imported first matters here, so each dictation runs in its own Python process (this same file, see
_worker). Only the part that needs the model's weights is simulated, so nothing is downloaded and no GPU is used:
the rest of faster-whisper is the real code, and it fails if it ever tries to decode something with the empty module.
"""
import ast
import importlib.metadata
import importlib.util
import json
import os
import re
import subprocess
import sys
import types

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PIN = 'faster-whisper==1.2.1'
INSTALL_COMMAND = f'--no-deps {PIN}'


class _NoAv:
    """Import hook: as if PyAV were not installed, whether it really is or not."""

    def find_spec(self, name, path=None, target=None):
        if name == 'av' or name.startswith('av.'):
            raise ModuleNotFoundError(f'No module named {name!r}', name=name)
        return None


class _FakeEngine:
    """Takes the place of ctranslate2.models.Whisper, the only part that needs the model's weights."""
    is_multilingual = False
    n_mels = 80
    device = 'cpu'
    device_index = [0]

    def __init__(self, *args, **kwargs):
        pass

    def encode(self, features, to_cpu=False):
        return features

    def generate(self, encoder_output, prompts, **kwargs):
        return [types.SimpleNamespace(sequences_ids=[[0, 1]], scores=[-0.1], no_speech_prob=0.0)]


def _write_fake_model(folder):
    import tokenizers
    words = ['hola', 'mundo', '[UNK]', '<|endoftext|>', '<|startoftranscript|>', '<|transcribe|>', '<|translate|>',
             '<|startoflm|>', '<|startofprev|>', '<|nospeech|>', '<|notimestamps|>']
    tokenizer = tokenizers.Tokenizer(tokenizers.models.WordLevel({w: i for i, w in enumerate(words)}, unk_token='[UNK]'))
    tokenizer.pre_tokenizer = tokenizers.pre_tokenizers.WhitespaceSplit()
    tokenizer.save(os.path.join(folder, 'tokenizer.json'))


def _worker(mode, folder, vad):
    """Dictate one second of audio with the real Transcriber and report what happened to `av`."""
    sys.path.insert(0, ROOT)
    if mode == 'blocked-in-sys-modules':
        sys.modules['av'] = None
    elif mode == 'blocked-by-import-hook':
        sys.meta_path.insert(0, _NoAv())
    elif mode == 'other-av-on-path':
        sys.path.insert(0, os.path.join(folder, 'site'))

    import ctranslate2
    import numpy as np

    from voxkeypaste import config
    from voxkeypaste.transcriber import Transcriber

    ctranslate2.models.Whisper = _FakeEngine
    _write_fake_model(folder)
    cfg = config.init(os.path.join(folder, 'config.yaml'))
    cfg.set('transcription', 'local_device', 'cpu')
    cfg.set('transcription', 'local_compute_type', 'int8')
    cfg.set('transcription', 'local_vad_filter', vad)
    cfg.values['transcription']['local_model'] = folder     # a folder: nothing to download
    transcriber = Transcriber(cfg)
    transcriber.preload()
    # 44.1 kHz, as a recording can be: the app has to resample it into an array for faster-whisper
    tone = (np.sin(np.arange(44100) * 2 * np.pi * 440 / 44100) * 8000).astype(np.int16)
    text = transcriber.transcribe(tone, 44100)

    import faster_whisper.audio
    av = sys.modules['av']
    print('RESULT ' + json.dumps({'text': text, 'file': getattr(av, '__file__', None), 'mark': getattr(av, 'MARK', None),
                                  'can_decode': hasattr(av, 'open'), 'same': faster_whisper.audio.av is av}))


def dictate(mode, tmp_path, vad=False):
    process = subprocess.run([sys.executable, os.path.abspath(__file__), mode, str(tmp_path), str(vad)], cwd=ROOT,
                             capture_output=True, text=True, errors='replace', timeout=120)
    assert process.returncode == 0, process.stdout + process.stderr
    line = next(x for x in process.stdout.splitlines() if x.startswith('RESULT '))
    return json.loads(line[len('RESULT '):])


@pytest.mark.parametrize('mode', ['blocked-in-sys-modules', 'blocked-by-import-hook'])
def test_dictates_an_array_without_av(mode, tmp_path):
    result = dictate(mode, tmp_path)
    assert result['text'] == 'hola mundo'
    assert result['same'] and result['file'] is None and not result['can_decode']   # the empty module, in use


def test_voice_filter_works_without_av(tmp_path):
    assert dictate('blocked-by-import-hook', tmp_path, vad=True)['same']


def test_an_importable_av_is_not_replaced(tmp_path):
    """Works even where PyAV is not installed: any importable `av` has to be left alone."""
    package = tmp_path / 'site' / 'av'
    package.mkdir(parents=True)
    (package / '__init__.py').write_text("MARK = 'importable'\n", encoding='utf-8')
    result = dictate('other-av-on-path', tmp_path)
    assert result['text'] == 'hola mundo'
    assert result['same'] and result['mark'] == 'importable'


@pytest.mark.skipif(importlib.util.find_spec('av') is None, reason='PyAV is optional (requirements-av.txt)')
def test_installed_pyav_works_the_same_and_is_not_replaced(tmp_path):
    result = dictate('as-installed', tmp_path)
    assert result['text'] == 'hola mundo'
    assert result['same'] and result['can_decode'] and 'site-packages' in result['file']


def _imports(path):
    with open(path, encoding='utf-8') as f:
        tree = ast.parse(f.read())
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            yield from (alias.name.split('.')[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            yield node.module.split('.')[0]


def test_only_the_transcriber_imports_av_and_faster_whisper():
    """They have to go through _whisper_model_class, or the empty module would come too late."""
    found = {}
    for folder in ('voxkeypaste', 'tools'):
        for base, _, files in os.walk(os.path.join(ROOT, folder)):
            for name in files:
                if name.endswith('.py'):
                    path = os.path.join(base, name)
                    for module in {'av', 'faster_whisper'} & set(_imports(path)):
                        found.setdefault(module, set()).add(os.path.relpath(path, ROOT).replace(os.sep, '/'))
    assert found == {'av': {'voxkeypaste/transcriber.py'}, 'faster_whisper': {'voxkeypaste/transcriber.py'}}


def _pinned(name):
    with open(os.path.join(ROOT, name), encoding='utf-8') as f:
        lines = (line.split('#')[0].strip() for line in f)
        return dict(re.match(r'([A-Za-z0-9._-]+)==([^\s;]+)', x).groups() for x in lines if x and not x.startswith('-'))


def _norm(name):
    return re.sub(r'[-_.]+', '-', name).lower()


def test_normal_install_leaves_av_out_and_faster_whisper_pinned():
    base = {_norm(n) for f in ('requirements.txt', 'requirements-dev.txt') for n in _pinned(f)}
    assert not base & {'av', 'faster-whisper'}
    assert 'av' in _pinned('requirements-av.txt')
    for name in ('README.md', 'README.es.md', 'CONTRIBUTING.md', '.github/workflows/trivy.yml'):
        with open(os.path.join(ROOT, name), encoding='utf-8') as f:
            assert INSTALL_COMMAND in f.read(), name


def test_requirements_have_all_that_faster_whisper_needs_except_av():
    assert importlib.metadata.version('faster-whisper') == PIN.split('==')[1]
    needs = {_norm(re.match(r'[A-Za-z0-9._-]+', r).group()) for r in importlib.metadata.requires('faster-whisper')
             if 'extra ==' not in r}
    assert 'av' in needs
    assert needs - {'av'} <= {_norm(n) for n in _pinned('requirements.txt')}


if __name__ == '__main__':
    _worker(sys.argv[1], sys.argv[2], sys.argv[3] == 'True')
