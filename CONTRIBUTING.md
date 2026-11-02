# Contributing

Thanks for your interest. VoxKeyPaste has a single maintainer, so replies can take a while.

## Bugs and ideas

Open an [issue](https://github.com/javimentallab/VoxKeyPaste/issues). Say what you expected, what happened, and which version and system you use. English or Spanish are both fine.

Security problems go through [SECURITY.md](SECURITY.md), not through issues.

## Changing the code

For anything big, open an issue first so we can agree on the approach.

```sh
python -m pip install -r requirements-dev.txt
python -m pytest
```

- **Tests:** anything important that you add comes with a test.
- **Dependencies:** a new one needs a permissive licence (MIT, BSD, Apache…). Check it before adding it.
- **Private data:** no personal paths, hostnames, IP addresses or tokens in the code, the history or the screenshots.
- **Interface text:** new text goes in every language, and has to fit on screen in all of them. Texts are in `voxkeypaste/locales/<language>.json`.
- **Licence:** your contribution is released under the project's [MIT licence](LICENSE).
