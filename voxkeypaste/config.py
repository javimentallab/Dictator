"""Settings: schema, defaults, loading and saving.

The user's settings live OUTSIDE the program folder, in a YAML file:
  Windows: %APPDATA%\\VoxKeyPaste\\config.yaml
  Linux:   ~/.config/voxkeypaste/config.yaml   (or $XDG_CONFIG_HOME)
  macOS:   ~/Library/Application Support/VoxKeyPaste/config.yaml
It can be overridden with the VOXKEYPASTE_CONFIG environment variable or --config.

Labels and help texts are not here: they are translated in locales/<lang>.json
under setting.<section>.<key>.label / .help.
"""
import os
import sys
import threading
from dataclasses import dataclass, field

import yaml

LANGUAGES = ['en', 'es', 'pt', 'fr', 'de', 'it', 'nl', 'pl', 'ru', 'uk', 'zh-CN', 'ja', 'ko', 'th', 'hi']
LOCAL_MODELS = ['tiny', 'base', 'small', 'medium', 'large-v2', 'large-v3', 'large-v3-turbo',
                'tiny.en', 'base.en', 'small.en', 'medium.en']


@dataclass
class Setting:
    key: str
    kind: str                 # bool, int, float, str, choice, path, secret, input_device, output_device
    default: object
    options: list = field(default_factory=list)
    minimum: float = None
    maximum: float = None


SCHEMA = [
    ('general', [
        Setting('language', 'choice', 'auto', ['auto'] + LANGUAGES),
        Setting('start_listening', 'bool', True),
        Setting('show_status_window', 'bool', True),
        Setting('log_to_console', 'bool', True),
    ]),
    ('recording', [
        Setting('hotkey', 'str', 'ctrl+shift+space'),
        Setting('mode', 'choice', 'toggle', ['toggle', 'hold', 'voice_activity']),
        Setting('input_device_name', 'input_device', ''),
        Setting('input_device_index', 'str', ''),
        Setting('sample_rate', 'choice', 16000, [16000, 22050, 32000, 44100, 48000]),
        Setting('lead_in_ms', 'int', 150, minimum=0, maximum=2000),
        Setting('trailing_ms', 'int', 300, minimum=0, maximum=2000),
        Setting('silence_ms', 'int', 900, minimum=100, maximum=10000),
        Setting('min_duration_ms', 'int', 300, minimum=0, maximum=10000),
    ]),
    ('transcription', [
        Setting('backend', 'choice', 'local', ['local', 'api']),
        Setting('language', 'str', ''),
        Setting('initial_prompt', 'str', ''),
        Setting('temperature', 'float', 0.0, minimum=0.0, maximum=1.0),
        Setting('local_model', 'choice', 'base', LOCAL_MODELS),
        Setting('local_device', 'choice', 'auto', ['auto', 'cuda', 'cpu']),
        Setting('local_compute_type', 'choice', 'default', ['default', 'float16', 'int8_float16', 'int8', 'float32']),
        Setting('local_vad_filter', 'bool', False),
        Setting('api_base_url', 'str', 'https://api.openai.com/v1'),
        Setting('api_model', 'str', 'whisper-1'),
        Setting('api_key', 'secret', ''),
    ]),
    ('output', [
        Setting('method', 'choice', 'clipboard', ['clipboard', 'type']),
        Setting('type_delay_ms', 'int', 5, minimum=0, maximum=200),
        Setting('add_trailing_space', 'bool', True),
        Setting('remove_trailing_period', 'bool', False),
        Setting('lowercase', 'bool', False),
        Setting('dictionary_file', 'path', ''),
    ]),
    ('sounds', [
        Setting('start_sound', 'bool', True),
        Setting('stop_sound', 'bool', True),
        Setting('done_sound', 'bool', False),
        Setting('start_sound_file', 'path', ''),
        Setting('stop_sound_file', 'path', ''),
        Setting('output_device_name', 'output_device', ''),
    ]),
    ('ducking', [
        Setting('enabled', 'bool', False),
        Setting('media_apps', 'str', 'brave.exe, chrome.exe, firefox.exe, msedge.exe, spotify.exe, vlc.exe, mpv.exe'),
        Setting('ducked_volume', 'int', 0, minimum=0, maximum=100),
        Setting('voicemeeter_mute_strips', 'str', ''),
        Setting('voicemeeter_dll', 'path', r'C:\Program Files (x86)\VB\Voicemeeter\VoicemeeterRemote64.dll'),
        Setting('max_duration_s', 'int', 300, minimum=0, maximum=3600),
    ]),
    ('clips', [
        Setting('enabled', 'bool', False),
        Setting('folder', 'path', ''),
        Setting('min_duration_s', 'float', 1.0, minimum=0.0, maximum=60.0),
        Setting('upload_command', 'str', ''),
    ]),
]

SECTIONS = [name for name, _ in SCHEMA]
_BY_KEY = {(section, s.key): s for section, settings in SCHEMA for s in settings}


def config_dir():
    if sys.platform == 'win32':
        base = os.environ.get('APPDATA') or os.path.expanduser('~')
        return os.path.join(base, 'VoxKeyPaste')
    if sys.platform == 'darwin':
        return os.path.expanduser('~/Library/Application Support/VoxKeyPaste')
    base = os.environ.get('XDG_CONFIG_HOME') or os.path.expanduser('~/.config')
    return os.path.join(base, 'voxkeypaste')


def defaults():
    return {section: {s.key: s.default for s in settings} for section, settings in SCHEMA}


def coerce(setting, value):
    """Convert a value from YAML/the UI to the setting's type. Invalid values fall back to the default."""
    try:
        if value is None:
            return setting.default if setting.kind in ('bool', 'int', 'float') else ''
        if setting.kind == 'bool':
            if isinstance(value, str):
                return value.strip().lower() in ('1', 'true', 'yes', 'on')
            return bool(value)
        if setting.kind == 'int':
            value = int(value)
        elif setting.kind == 'float':
            value = float(value)
        elif setting.kind == 'choice':
            for option in setting.options:
                if str(option) == str(value):
                    return option
            return setting.default
        else:
            return str(value)
        if setting.minimum is not None:
            value = max(setting.minimum, value)
        if setting.maximum is not None:
            value = min(setting.maximum, value)
        return value
    except (TypeError, ValueError):
        return setting.default


class Config:
    def __init__(self, path=None):
        self.path = path or os.environ.get('VOXKEYPASTE_CONFIG') or os.path.join(config_dir(), 'config.yaml')
        self.values = defaults()
        self.loaded_from_file = False
        self.load()

    @property
    def directory(self):
        return os.path.dirname(os.path.abspath(self.path))

    def load(self):
        self.values = defaults()
        self.loaded_from_file = False
        if not os.path.isfile(self.path):
            return
        try:
            with open(self.path, encoding='utf-8') as f:
                data = yaml.safe_load(f) or {}
        except (OSError, yaml.YAMLError) as e:
            log(f'Could not read {self.path} ({e}); using the defaults.')
            return
        for section, items in data.items():
            if not isinstance(items, dict):
                continue
            for key, value in items.items():
                setting = _BY_KEY.get((section, key))
                if setting is None:
                    log(f'Unknown setting {section}.{key} ignored.')
                    continue
                self.values[section][key] = coerce(setting, value)
        self.loaded_from_file = True

    def save(self):
        os.makedirs(self.directory, exist_ok=True)
        tmp = self.path + '.tmp'
        with open(tmp, 'w', encoding='utf-8') as f:
            yaml.safe_dump(self.values, f, allow_unicode=True, sort_keys=False)
        os.replace(tmp, self.path)
        self.loaded_from_file = True

    def get(self, section, key):
        return self.values[section][key]

    def set(self, section, key, value):
        self.values[section][key] = coerce(_BY_KEY[(section, key)], value)

    def resolve_path(self, value):
        """Relative paths in the settings are relative to the config folder; ~ is expanded."""
        if not value:
            return ''
        value = os.path.expandvars(os.path.expanduser(value))
        return value if os.path.isabs(value) else os.path.join(self.directory, value)


_current = None
_log_lock = threading.Lock()


def init(path=None):
    global _current
    _current = Config(path)
    return _current


def current():
    if _current is None:
        init()
    return _current


def get(section, key):
    return current().get(section, key)


def log(message):
    try:
        if _current is not None and not _current.values['general']['log_to_console']:
            return
        with _log_lock:
            print(message, flush=True)
    except Exception:
        pass
