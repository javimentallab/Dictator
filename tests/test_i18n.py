import json
import os
import re

from dictator import config, i18n

PLACEHOLDER = re.compile(r'\{[a-z_]+\}')


def load(lang):
    with open(os.path.join(i18n.LOCALES, f'{lang}.json'), encoding='utf-8') as f:
        return json.load(f)


def test_english_covers_every_setting_and_section():
    en = load('en')
    for section, settings in config.SCHEMA:
        assert f'section.{section}' in en
        for s in settings:
            assert f'setting.{section}.{s.key}.label' in en
            assert f'setting.{section}.{s.key}.help' in en
    for lang in config.LANGUAGES:
        assert f'language.{lang}' in en


def test_every_language_is_complete_and_keeps_placeholders():
    en = {k: v for k, v in load('en').items() if not k.startswith('language.')}
    for lang in config.LANGUAGES:
        strings = load(lang)
        missing = sorted(set(en) - set(strings))
        extra = sorted(set(strings) - set(en) - {k for k in strings if k.startswith('language.')})
        assert not missing, f'{lang} is missing {missing}'
        assert not extra, f'{lang} has unknown keys {extra}'
        for key, text in en.items():
            assert sorted(PLACEHOLDER.findall(strings[key])) == sorted(PLACEHOLDER.findall(text)), (lang, key)
            assert strings[key].strip(), (lang, key)


def test_fallback_and_formatting():
    i18n.set_language('xx')
    assert i18n.language() == 'en'
    assert i18n.tr('ui.status.ready', hotkey='F8') == 'Ready — press F8 to dictate'
    assert i18n.tr('no.such.key') == 'no.such.key'
    assert i18n.option(48000) == '48000'
