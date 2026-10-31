# Changelog

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
