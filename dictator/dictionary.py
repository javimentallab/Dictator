"""Correction dictionary applied to every transcription.

File format (post_processing.dictionary_file), one rule per line:

    # comment
    wrong=right

Whole-word, case-insensitive replacement that keeps an initial capital.
The file is re-read on every call, so it can be edited without restarting.
"""
import re

from . import config


def load_rules(path):
    rules = []
    try:
        with open(path, encoding='utf-8-sig') as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith('#') or '=' not in line:
                    continue
                wrong, right = line.split('=', 1)
                wrong = wrong.strip()
                if wrong:
                    rules.append((wrong, right.strip()))
    except OSError:
        pass
    return rules


def apply_rules(text, rules):
    for wrong, right in rules:
        def repl(match, right=right):
            word = match.group(0)
            return right[:1].upper() + right[1:] if word[:1].isupper() else right
        text = re.sub(r'(?<!\w)' + re.escape(wrong) + r'(?!\w)', repl, text, flags=re.IGNORECASE)
    return text


def apply(text):
    """Apply the configured dictionary. Returns the text unchanged if there is none or on error."""
    path = config.current().resolve_path(config.get('output', 'dictionary_file'))
    if not path or not text:
        return text
    try:
        return apply_rules(text, load_rules(path))
    except Exception as e:
        config.log(f'Dictionary not applied: {e}')
        return text
