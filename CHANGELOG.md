# Changelog

## Unreleased

### Changed
- **VoxKeyPaste is now Dictator**: the name, the icon (a red D), the Python package (`python -m dictator`), the settings folder (`%APPDATA%\Dictator`, `~/.config/dictator`), the log (`dictator.log`) and the `DICTATOR_CONFIG` variable, which replaces `VOXKEYPASTE_CONFIG`. Your settings, dictionary and log move to the new folder by themselves the first time it starts.
- If you start it with Windows, replace the old task: `tools\windows\install-autostart.ps1 -TaskName VoxKeyPaste -Remove`, then run the script again as the README says.

## 1.0.2 — 2026-11-02

- The install no longer brings PyAV (`av`), and with it FFmpeg and the x264 and x265 encoders: faster-whisper only uses it to decode audio files and VoxKeyPaste hands it arrays. faster-whisper now goes in a second command with `--no-deps` (see the README), its other dependencies are pinned in `requirements.txt`, and PyAV stays as an option in `requirements-av.txt`.
- Development only: Pillow 13.0.0, for the scripts that draw the icons and the cover, which only open images they generate themselves. It fixes the 39 vulnerabilities reported against 12.3.0 (CVE-2026-96636 to 96644, CVE-2026-96778, CVE-2026-112390 to 112406, CVE-2026-112891 to 112897, CVE-2026-112899 to 112901, CVE-2026-114501 and GHSA-78g4-xqwv-q3g8). It is younger than the usual wait for a new release: accepted on purpose.

## 1.0.1 — 2026-11-01

### Added
- **Stop if nobody speaks** (Recording, default 15 s, 0 = off): in any mode, if no voice is heard for that
  long (from the start or after the last words), the recording ends by itself, the audio comes back and the
  stop sound plays. Before, a single press that was never followed by a second one left the computer muted
  until the safety limit (5 minutes). With no voice at all nothing is transcribed; otherwise what was said is
  transcribed without the trailing silence. Voice detection is stricter than webrtcvad alone, which takes
  clicks and background noise for speech.

### Fixed
- Right after logon (or whenever the audio device list changes, e.g. Voicemeeter starting late), the first
  hotkey press re-initialised PortAudio before the start sound; a second press during that delay cancelled
  the dictation and the start sound still played, so it looked like it was recording but nothing was. The
  device list is now watched in the background while idle, sounds wait for the refresh instead of failing,
  and a dictation cancelled while starting plays no start sound and is logged.
- With no output device set for the sounds, they went to PortAudio's own MME default, which is not the
  Windows default output: it could point at a device another program holds (e.g. a Voicemeeter bus), so
  the sounds failed with "Device unavailable". They now use the current Windows default output and
  follow it when it changes.

### Changed
- CI: actions/checkout v5, actions/setup-python v6, codeql-action/upload-sarif v4.

## 1.0.0 — 2026-10-31

First public version.

- Global hotkey with three modes: toggle, hold to talk, stop after a pause. A single-key hotkey such as F8
  is kept away from the program you type in (including its auto-repeat).
- Local transcription (faster-whisper) or any OpenAI-compatible API.
- Paste the whole text at once (clipboard, restored afterwards) or type it.
- Start, stop and "done" sounds through one persistent output stream; output device by name.
- Silences the system output and/or Voicemeeter strips while dictating (never per-app volumes); undone after a crash.
- Lead-in trim and trailing time so the first and last syllables are clean.
- Microphone by name, robust to Windows renumbering the audio devices; PortAudio refreshed when
  devices are plugged in or out.
- Correction dictionary, optional saving of every dictation with an upload command.
- Tray icon with state colours, pause, settings, restart and quit; single instance.
- Interface in 15 languages.
