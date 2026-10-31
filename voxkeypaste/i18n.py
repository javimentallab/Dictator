"""Interface translations: locales/<lang>.json, English as the fallback.

Keys:
  ui.*                              tray menu, windows, dialogs
  section.<section>                 settings tab titles
  setting.<section>.<key>.label     setting names
  setting.<section>.<key>.help      setting descriptions
  option.<value>                    names of choice values (modes, backends...)
Placeholders use {name} and must be the same in every language.
"""
import json
import locale
import os

from .config import LANGUAGES

LOCALES = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'locales')
_strings = {}
_fallback = {}
_language = 'en'


def _read(lang):
    try:
        with open(os.path.join(LOCALES, f'{lang}.json'), encoding='utf-8') as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def system_language():
    """Best match of the system language among the supported ones (default English)."""
    candidates = []
    try:
        if os.name == 'nt':
            import ctypes
            lcid = ctypes.windll.kernel32.GetUserDefaultUILanguage()
            candidates.append(locale.windows_locale.get(lcid, ''))
    except Exception:
        pass
    for var in ('LC_ALL', 'LC_MESSAGES', 'LANG'):
        candidates.append(os.environ.get(var, ''))
    try:
        candidates.append(locale.getlocale()[0] or '')
    except Exception:
        pass
    for name in candidates:
        name = name.replace('-', '_').split('.')[0]
        if not name:
            continue
        if name.lower().startswith('zh'):
            return 'zh-CN'
        short = name.split('_')[0].lower()
        if short in LANGUAGES:
            return short
    return 'en'


def set_language(lang):
    global _strings, _fallback, _language
    if not lang or lang == 'auto':
        lang = system_language()
    if lang not in LANGUAGES:
        lang = 'en'
    _language = lang
    _fallback = _read('en')
    _strings = _read(lang) if lang != 'en' else _fallback


def language():
    return _language


def tr(key, **params):
    text = _strings.get(key) or _fallback.get(key) or key
    if params:
        try:
            text = text.format(**params)
        except (KeyError, IndexError, ValueError):
            pass
    return text


def label(section, key):
    return tr(f'setting.{section}.{key}.label')


def help_text(section, key):
    return tr(f'setting.{section}.{key}.help')


def option(value):
    key = f'option.{value}'
    text = tr(key)
    return str(value) if text == key else text
