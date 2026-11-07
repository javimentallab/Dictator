"""Check GitHub for a newer release and, in a git clone, update to it. Only runs when asked.

Dictator is installed with `git clone` (see the README), so an update is: fetch the release tag from the
official repository, move the clone forward to it (fast-forward only) and, if requirements.txt changed,
install the new pinned dependencies into the same environment. Git checks the integrity of everything it
downloads by its hashes. The settings live outside the program folder and are never touched.

Copies that cannot be updated this way safely (not a git clone, no git, files of your own changed, or
commits of your own) are not touched: the caller opens the release page instead.
"""
import os
import re
import subprocess
import sys
import tempfile

from . import __version__

OWNER_REPO = 'javimentallab/Dictator'
API_URL = f'https://api.github.com/repos/{OWNER_REPO}/releases/latest'
REPO_URL = f'https://github.com/{OWNER_REPO}.git'
RELEASES_URL = f'https://github.com/{OWNER_REPO}/releases'
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CHECK_TIMEOUT = 8.0          # seconds, the whole request
GIT_TIMEOUT = 120
PIP_TIMEOUT = 900

_VERSION = re.compile(r'^v?(\d+)\.(\d+)(?:\.(\d+))?(?:-([0-9A-Za-z.-]+))?$')


class UpdateError(Exception):
    """`code` is one of: not_git, no_git, local_changes, diverged, failed."""

    def __init__(self, code, detail=''):
        super().__init__(detail or code)
        self.code = code
        self.detail = detail


# --- versions -------------------------------------------------------------------------------
def parse_version(text):
    """'v1.2.3', '1.2' or '1.2.3-rc.1' -> a key that sorts like semantic versions; None if not a version."""
    match = _VERSION.match(str(text or '').strip())
    if not match:
        return None
    major, minor, patch, pre = match.groups()
    numbers = (int(major), int(minor), int(patch or 0))
    if not pre:
        return numbers + (1, ())                       # a release sorts after its pre-releases
    parts = tuple((0, int(p), '') if p.isdigit() else (1, 0, p) for p in pre.split('.'))
    return numbers + (0, parts)


def is_newer(candidate, current):
    new, old = parse_version(candidate), parse_version(current)
    return new is not None and old is not None and new > old


# --- check ----------------------------------------------------------------------------------
def check(current=__version__, transport=None):
    """Ask GitHub for the latest release. Returns a dict with 'newer' (bool), 'version', 'tag' and 'url'.
    Raises UpdateError('failed', ...) when offline or when the answer is not what is expected."""
    import httpx
    headers = {'Accept': 'application/vnd.github+json', 'User-Agent': f'Dictator-updater/{current}',
               'X-GitHub-Api-Version': '2022-11-28'}
    try:
        with httpx.Client(timeout=httpx.Timeout(CHECK_TIMEOUT, connect=5.0), transport=transport,
                          follow_redirects=False) as client:
            response = client.get(API_URL, headers=headers)
    except httpx.HTTPError as e:
        raise UpdateError('failed', f'{type(e).__name__}: {e}') from e
    if response.status_code != 200:
        raise UpdateError('failed', f'GitHub: HTTP {response.status_code}')
    try:
        data = response.json()
        tag = str(data['tag_name'])
    except (ValueError, KeyError, TypeError) as e:
        raise UpdateError('failed', 'GitHub: unexpected answer') from e
    if parse_version(tag) is None:
        raise UpdateError('failed', f'GitHub: {tag!r} is not a version')
    url = str(data.get('html_url') or '')
    if not url.startswith(RELEASES_URL + '/'):        # only ever open this repository's own pages
        url = f'{RELEASES_URL}/tag/{tag}'
    return {'newer': is_newer(tag, current), 'version': tag.lstrip('v'), 'tag': tag, 'url': url}


# --- install --------------------------------------------------------------------------------
def _run(args, timeout, cwd=ROOT):
    env = dict(os.environ, GIT_TERMINAL_PROMPT='0', GCM_INTERACTIVE='never', LC_ALL='C')
    flags = subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0
    try:
        return subprocess.run(args, cwd=cwd, env=env, stdin=subprocess.DEVNULL, capture_output=True,
                              text=True, encoding='utf-8', errors='replace', timeout=timeout,
                              creationflags=flags)
    except subprocess.TimeoutExpired as e:
        raise UpdateError('failed', f'{os.path.basename(args[0])}: no answer after {timeout} s') from e
    except OSError as e:
        raise UpdateError('failed', f'{os.path.basename(args[0])}: {e}') from e


def _git_exe():
    import shutil
    return shutil.which('git')


def _git(root, *args, timeout=30, check=True):
    result = _run([_git_exe() or 'git', '-C', root, *args], timeout)
    if check and result.returncode != 0:
        message = (result.stderr or result.stdout).strip().splitlines()
        raise UpdateError('failed', f'git {args[0]}: {message[-1] if message else result.returncode}')
    return result


def self_update_blocker(root=ROOT):
    """None if this copy can update itself, otherwise the UpdateError code that explains why not."""
    if not os.path.exists(os.path.join(root, '.git')):
        return 'not_git'
    if not _git_exe():
        return 'no_git'
    try:
        top = _git(root, 'rev-parse', '--show-toplevel').stdout.strip()
        same = lambda p: os.path.normcase(os.path.realpath(p))
        if not top or same(top) != same(root):
            return 'not_git'
        if _git(root, 'status', '--porcelain', '--untracked-files=no').stdout.strip():
            return 'local_changes'
    except UpdateError:
        return 'not_git'
    return None


def _python_exe():
    """The console interpreter of this environment (pythonw.exe has a python.exe next to it)."""
    folder, name = os.path.split(sys.executable)
    if name.lower() == 'pythonw.exe' and os.path.exists(os.path.join(folder, 'python.exe')):
        return os.path.join(folder, 'python.exe')
    return sys.executable


def _pip_install(requirements_text):
    """Install the new pinned dependencies into this environment."""
    fd, path = tempfile.mkstemp(prefix='dictator-requirements-', suffix='.txt')
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            f.write(requirements_text)
        result = _run([_python_exe(), '-m', 'pip', 'install', '--disable-pip-version-check', '-q', '-r', path],
                      PIP_TIMEOUT)
    finally:
        os.remove(path)
    if result.returncode != 0:
        lines = (result.stderr or result.stdout).strip().splitlines()
        raise UpdateError('failed', f'pip: {lines[-1] if lines else result.returncode}')


def install(tag, root=ROOT, repo_url=REPO_URL, pip_install=_pip_install):
    """Update this git clone to `tag` of the official repository. Nothing in the program folder changes
    unless every check passes; the settings are elsewhere and never touched. Returns the new commit."""
    if parse_version(tag) is None:                     # also keeps it a safe refspec
        raise UpdateError('failed', f'{tag!r} is not a version')
    blocker = self_update_blocker(root)
    if blocker:
        raise UpdateError(blocker)
    _git(root, 'fetch', '--no-tags', '--quiet', repo_url, f'refs/tags/{tag}', timeout=GIT_TIMEOUT)
    new = _git(root, 'rev-parse', '--verify', '--quiet', 'FETCH_HEAD^{commit}').stdout.strip()
    if not re.fullmatch(r'[0-9a-f]{40,64}', new):
        raise UpdateError('failed', 'git: the release tag was not downloaded')
    if _git(root, 'merge-base', '--is-ancestor', 'HEAD', new, check=False).returncode != 0:
        raise UpdateError('diverged')                  # commits of its own: no fast-forward possible
    if _git(root, 'diff', '--quiet', 'HEAD', new, '--', 'requirements.txt', check=False).returncode != 0:
        pip_install(_git(root, 'show', f'{new}:requirements.txt').stdout)
    _git(root, 'merge', '--ff-only', '--quiet', new, timeout=GIT_TIMEOUT)
    return new
