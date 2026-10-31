import os

import yaml

from voxkeypaste import config


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
