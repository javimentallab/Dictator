import os

import yaml

from dictator import config


def test_defaults_cover_every_setting(cfg):
    for section, settings in config.SCHEMA:
        for s in settings:
            assert cfg.get(section, s.key) == s.default
    assert not cfg.loaded_from_file


def test_save_and_load_roundtrip(cfg):
    cfg.set('recording', 'hotkey', 'f8')
    cfg.set('recording', 'sample_rate', '48000')
    cfg.set('output', 'type_delay_ms', 7)
    cfg.save()
    again = config.Config(cfg.path)
    assert again.loaded_from_file
    assert again.get('recording', 'hotkey') == 'f8'
    assert again.get('recording', 'sample_rate') == 48000
    assert again.get('output', 'type_delay_ms') == 7


def test_invalid_and_unknown_values_fall_back(cfg):
    with open(cfg.path, 'w', encoding='utf-8') as f:
        yaml.safe_dump({'recording': {'mode': 'nonsense', 'lead_in_ms': 'abc', 'trailing_ms': 99999,
                                      'not_a_setting': 1},
                        'general': {'start_listening': 'no'}}, f)
    cfg.load()
    assert cfg.get('recording', 'mode') == 'toggle'
    assert cfg.get('recording', 'lead_in_ms') == 150
    assert cfg.get('recording', 'trailing_ms') == 2000          # clamped to the maximum
    assert cfg.get('general', 'start_listening') is False


def test_broken_yaml_uses_defaults(cfg):
    with open(cfg.path, 'w', encoding='utf-8') as f:
        f.write('recording: [unclosed')
    cfg.load()
    assert cfg.get('recording', 'hotkey') == 'ctrl+shift+space'


def test_relative_paths_are_relative_to_the_config_folder(cfg):
    assert cfg.resolve_path('') == ''
    assert cfg.resolve_path('fixes.txt') == os.path.join(cfg.directory, 'fixes.txt')
    absolute = os.path.abspath('somewhere.txt')
    assert cfg.resolve_path(absolute) == absolute


def _old_dir(monkeypatch, tmp_path):
    """Point the settings folder at tmp_path and return (old folder, new folder)."""
    monkeypatch.setenv('APPDATA', str(tmp_path))
    monkeypatch.setenv('XDG_CONFIG_HOME', str(tmp_path))
    monkeypatch.delenv('DICTATOR_CONFIG', raising=False)
    new = config.config_dir()
    old = os.path.join(os.path.dirname(new), 'VoxKeyPaste' if os.path.basename(new) == 'Dictator' else 'voxkeypaste')
    os.makedirs(old)
    with open(os.path.join(old, 'config.yaml'), 'w', encoding='utf-8') as f:
        yaml.safe_dump({'recording': {'hotkey': 'f9'}}, f)
    with open(os.path.join(old, 'voxkeypaste.log'), 'w', encoding='utf-8') as f:
        f.write('old log\n')
    return old, new


def test_old_settings_folder_moves_on_first_start(monkeypatch, tmp_path):
    old, new = _old_dir(monkeypatch, tmp_path)
    c = config.Config()
    assert c.directory == new
    assert c.loaded_from_file and c.get('recording', 'hotkey') == 'f9'
    assert not os.path.exists(old)
    assert os.path.exists(os.path.join(new, 'dictator.log'))
    assert not os.path.exists(os.path.join(new, 'voxkeypaste.log'))


def test_existing_settings_folder_is_not_overwritten(monkeypatch, tmp_path):
    old, new = _old_dir(monkeypatch, tmp_path)
    os.makedirs(new)
    c = config.Config()
    assert not c.loaded_from_file
    assert os.path.exists(os.path.join(old, 'config.yaml'))


def test_explicit_settings_path_leaves_the_old_folder_alone(monkeypatch, tmp_path):
    old, new = _old_dir(monkeypatch, tmp_path)
    config.Config(str(tmp_path / 'other' / 'config.yaml'))
    monkeypatch.setenv('DICTATOR_CONFIG', str(tmp_path / 'other' / 'config.yaml'))
    config.Config()
    assert os.path.exists(old) and not os.path.exists(new)
