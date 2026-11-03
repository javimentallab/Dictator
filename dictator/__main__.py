"""python -m dictator [--config PATH] [--list-devices]"""
import argparse
import sys


def _utf8_console():
    """Transcriptions can be in any script; never let printing them fail on a cp1252 console."""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding='utf-8', errors='replace')
        except Exception:          # pythonw has no console (stream is None)
            pass


def main():
    _utf8_console()
    parser = argparse.ArgumentParser(prog='dictator', description='Dictate anywhere with a hotkey.')
    parser.add_argument('--config', help='settings file to use instead of the default one')
    parser.add_argument('--list-devices', action='store_true', help='list the audio devices and exit')
    args, _ = parser.parse_known_args()

    if args.list_devices:
        import sounddevice as sd
        print(sd.query_devices())
        return 0

    from .app import run
    passthrough = ['--config', args.config] if args.config else []
    return run(passthrough, args.config)


if __name__ == '__main__':
    sys.exit(main())
