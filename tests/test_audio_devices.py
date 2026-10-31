"""Picking the sound output: Windows full names against PortAudio's (MME cuts them to 31 characters)."""
import pytest

from voxkeypaste import audio_devices, cues

HOSTAPIS = [{'name': 'MME'}, {'name': 'Windows WASAPI'}]
DEVICES = [
    {'name': 'Headset Earphone (3- CORSAIR VO', 'hostapi': 0, 'max_output_channels': 8, 'max_input_channels': 0},
    {'name': 'Voicemeeter Input (VB-Audio Voi', 'hostapi': 0, 'max_output_channels': 8, 'max_input_channels': 0},
    {'name': 'Voicemeeter AUX Input (VB-Audio', 'hostapi': 0, 'max_output_channels': 8, 'max_input_channels': 0},
    {'name': 'Voicemeeter Input (VB-Audio Voicemeeter VAIO)', 'hostapi': 1, 'max_output_channels': 2,
     'max_input_channels': 0},
    {'name': 'Speakers', 'hostapi': 0, 'max_output_channels': 2, 'max_input_channels': 0},
    {'name': 'Speakers (Razer Seiren X)', 'hostapi': 0, 'max_output_channels': 2, 'max_input_channels': 0},
]


@pytest.fixture
def fake_devices(monkeypatch):
    monkeypatch.setattr(audio_devices.sd, 'query_devices', lambda: DEVICES)
    monkeypatch.setattr(audio_devices.sd, 'query_hostapis', lambda: HOSTAPIS)
    monkeypatch.setattr(audio_devices, '_IS_WINDOWS', True)


def test_full_name_matches_the_truncated_mme_name(fake_devices):
    assert audio_devices.find_device_by_full_name('Voicemeeter Input (VB-Audio Voicemeeter VAIO)') == 1


def test_full_name_prefers_the_longest_match(fake_devices):
    assert audio_devices.find_device_by_full_name('Speakers (Razer Seiren X)') == 5


def test_full_name_without_match_or_empty(fake_devices):
    assert audio_devices.find_device_by_full_name('Philips UHDTV (NVIDIA High Definition Audio)') is None
    assert audio_devices.find_device_by_full_name('') is None
    assert audio_devices.find_device_by_full_name(None) is None


def test_default_output_is_the_windows_default(fake_devices, monkeypatch):
    monkeypatch.setattr(audio_devices, '_windows_default_output_name',
                        lambda: 'Voicemeeter Input (VB-Audio Voicemeeter VAIO)')
    assert audio_devices.default_output_device() == 1


class FakeStream:
    opened = []

    def __init__(self, device=None, **kw):
        self.device = device
        FakeStream.opened.append(device)

    def start(self):
        pass

    def abort(self):
        pass

    def close(self):
        pass


def test_sounds_follow_the_windows_default_when_it_changes(cfg, fake_devices, monkeypatch):
    default = {'name': 'Voicemeeter Input (VB-Audio Voicemeeter VAIO)'}
    monkeypatch.setattr(audio_devices, '_windows_default_output_name', lambda: default['name'])
    monkeypatch.setattr(cues.sd, 'OutputStream', FakeStream)
    FakeStream.opened = []
    cfg.values['sounds']['output_device_name'] = ''
    cues.close()
    try:
        cues._ensure_stream()
        cues._ensure_stream()                      # same default: the stream is kept
        default['name'] = 'Headset Earphone (3- CORSAIR VOID ELITE Wireless Gaming Headset)'
        cues._ensure_stream()                      # new default: reopened there
        assert FakeStream.opened == [1, 0]
    finally:
        cues.close()


def test_sounds_by_name_ignore_the_windows_default(cfg, fake_devices, monkeypatch):
    monkeypatch.setattr(audio_devices, '_windows_default_output_name', lambda: 'Speakers (Razer Seiren X)')
    monkeypatch.setattr(cues.sd, 'OutputStream', FakeStream)
    FakeStream.opened = []
    cfg.values['sounds']['output_device_name'] = 'Voicemeeter AUX'
    cues.close()
    try:
        cues._ensure_stream()
        assert FakeStream.opened == [2]
    finally:
        cues.close()
