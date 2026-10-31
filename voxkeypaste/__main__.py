"""python -m voxkeypaste [--config PATH] [--list-devices]"""
import argparse
import sys


def main():
    parser = argparse.ArgumentParser(prog='voxkeypaste', description='Dictate anywhere with a hotkey.')
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
