# Changelog

## 1.0.0 — 2026-11

First public version.

- Global hotkey with three modes: toggle, hold to talk, stop after a pause.
- Local transcription (faster-whisper) or any OpenAI-compatible API.
- Paste the whole text at once (clipboard, restored afterwards) or type it.
- Start, stop and "done" sounds through one persistent output stream; output device by name.
- Mutes media apps (and optionally Voicemeeter strips) while dictating; restores them after a crash.
- Lead-in trim and trailing time so the first and last syllables are clean.
- Microphone by name, robust to Windows renumbering the audio devices; PortAudio refreshed when
  devices are plugged in or out.
- Correction dictionary, optional saving of every dictation with an upload command.
- Tray icon with state colours, pause, settings, restart and quit; single instance.
- Interface in 15 languages.
