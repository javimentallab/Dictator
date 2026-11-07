"""The Update… button: version comparison, the GitHub check with a fake network, the git update against
local repositories in tmp_path, and the dialog flow with fake dialogs. Nothing goes to the internet."""
import os
import shutil
import subprocess

import httpx
import pytest

from dictator import i18n, update_flow, updater
from dictator.updater import UpdateError, is_newer, parse_version


# --- versions -------------------------------------------------------------------------------
@pytest.mark.parametrize('new, old', [
    ('1.10.0', '1.9.0'),          # a text comparison gets this one wrong
    ('v1.2.0', '1.1.9'),
    ('2.0.0', '1.99.99'),
    ('1.2.1', '1.2'),
    ('1.2.0', '1.2.0-rc.2'),      # the release comes after its release candidates
    ('1.2.0-rc.10', '1.2.0-rc.2'),
    ('1.2.0-rc.1', '1.2.0-beta'),
])
def test_is_newer(new, old):
    assert is_newer(new, old)
    assert not is_newer(old, new)


@pytest.mark.parametrize('a, b', [('1.1.0', 'v1.1.0'), ('1.2', '1.2.0')])
def test_same_version_is_not_newer(a, b):
    assert parse_version(a) == parse_version(b)
    assert not is_newer(a, b)


@pytest.mark.parametrize('text', ['', None, 'latest', '1', 'v1.2.x', '1.2.3; rm -rf /', '../1.2.3', '1.2.3 '])
def test_not_a_version(text):
    if text == '1.2.3 ':                               # surrounding spaces are tolerated
        assert parse_version(text) == parse_version('1.2.3')
        return
    assert parse_version(text) is None
    assert not is_newer(text, '1.0.0')


# --- check (fake network) -----------------------------------------------------------------
def fake_github(status=200, body=None, error=None, seen=None):
    def handler(request):
        if seen is not None:
            seen.append(request)
        if error:
            raise error
        if isinstance(body, str):
            return httpx.Response(status, text=body)
        return httpx.Response(status, json=body if body is not None else {})
    return httpx.MockTransport(handler)


def release(tag, url=None):
    return {'tag_name': tag, 'html_url': url or f'https://github.com/javimentallab/Dictator/releases/tag/{tag}'}


def test_check_finds_a_newer_release_and_sends_only_a_generic_user_agent():
    seen = []
    result = updater.check('1.1.0', transport=fake_github(body=release('v1.10.0'), seen=seen))
    assert result == {'newer': True, 'version': '1.10.0', 'tag': 'v1.10.0',
                      'url': 'https://github.com/javimentallab/Dictator/releases/tag/v1.10.0'}
    request, = seen
    assert str(request.url) == 'https://api.github.com/repos/javimentallab/Dictator/releases/latest'
    assert request.headers['User-Agent'] == 'Dictator-updater/1.1.0'
    assert 'Authorization' not in request.headers and 'Cookie' not in request.headers


@pytest.mark.parametrize('tag', ['v1.1.0', 'v1.0.2'])
def test_check_same_or_older_is_up_to_date(tag):
    assert updater.check('1.1.0', transport=fake_github(body=release(tag)))['newer'] is False


def test_check_never_opens_a_page_outside_the_repository():
    result = updater.check('1.1.0', transport=fake_github(body=release('v1.2.0', 'https://evil.example/x')))
    assert result['url'] == 'https://github.com/javimentallab/Dictator/releases/tag/v1.2.0'


@pytest.mark.parametrize('transport', [
    fake_github(error=httpx.ConnectError('offline')),
    fake_github(error=httpx.ReadTimeout('slow')),
    fake_github(status=403, body={'message': 'rate limit'}),
    fake_github(status=301, body={'url': 'https://elsewhere'}),
    fake_github(body='<html>not json</html>'),
    fake_github(body={'name': 'no tag'}),
    fake_github(body=release('nightly')),
])
def test_check_errors_are_update_errors(transport):
    with pytest.raises(UpdateError) as e:
        updater.check('1.1.0', transport=transport)
    assert e.value.code == 'failed' and e.value.detail


def test_check_timeout_is_short():
    assert updater.CHECK_TIMEOUT <= 10


# --- install (local git repositories, no network) -------------------------------------------
needs_git = pytest.mark.skipif(shutil.which('git') is None, reason='git is not installed')
GIT_TEST = ['-c', 'user.name=Test', '-c', 'user.email=test@example.invalid', '-c', 'commit.gpgsign=false',
            '-c', 'tag.gpgsign=false', '-c', 'init.defaultBranch=main', '-c', 'core.autocrlf=false']


def git(cwd, *args):
    result = subprocess.run(['git', *GIT_TEST, *args], cwd=cwd, capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
    return result.stdout.strip()


def write(folder, name, text):
    path = os.path.join(folder, name)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', encoding='utf-8', newline='\n') as f:
        f.write(text)


@pytest.fixture
def repos(tmp_path):
    """upstream: v1.1.0, then v1.2.0 (annotated tag, new requirements). app: a clone still on v1.1.0."""
    upstream, app = str(tmp_path / 'upstream'), str(tmp_path / 'app')
    os.makedirs(upstream)
    git(upstream, 'init', '-q')
    write(upstream, 'dictator/__init__.py', "__version__ = '1.1.0'\n")
    write(upstream, 'requirements.txt', 'httpx==0.28.1\n')
    git(upstream, 'add', '.')
    git(upstream, 'commit', '-q', '-m', 'Version 1.1.0')
    git(upstream, 'tag', 'v1.1.0')
    git(str(tmp_path), 'clone', '-q', upstream, app)
    write(upstream, 'dictator/__init__.py', "__version__ = '1.2.0'\n")
    write(upstream, 'requirements.txt', 'httpx==0.28.2\n')
    git(upstream, 'commit', '-q', '-am', 'Version 1.2.0')
    git(upstream, 'tag', '-a', 'v1.2.0', '-m', 'Dictator 1.2.0')
    return upstream, app


def head(folder):
    return git(folder, 'rev-parse', 'HEAD')


@needs_git
def test_install_moves_the_clone_to_the_release_and_installs_the_new_requirements(repos):
    upstream, app = repos
    write(app, 'config.yaml', 'mine: true\n')          # untracked files of the user are kept
    installed = []
    new = updater.install('v1.2.0', root=app, repo_url=upstream, pip_install=installed.append)
    assert new == head(app) == git(upstream, 'rev-parse', 'v1.2.0^{commit}')
    assert installed == ['httpx==0.28.2\n']
    with open(os.path.join(app, 'dictator', '__init__.py'), encoding='utf-8') as f:
        assert '1.2.0' in f.read()
    with open(os.path.join(app, 'config.yaml'), encoding='utf-8') as f:
        assert f.read() == 'mine: true\n'


@needs_git
def test_install_skips_pip_when_requirements_did_not_change(repos):
    upstream, app = repos
    write(upstream, 'README.md', 'only docs\n')
    git(upstream, 'add', '.')
    git(upstream, 'commit', '-q', '-m', 'Docs')
    git(upstream, 'tag', 'v1.2.1')
    git(app, 'fetch', '-q', upstream, 'refs/tags/v1.2.0')
    git(app, 'merge', '-q', '--ff-only', 'FETCH_HEAD')
    installed = []
    updater.install('v1.2.1', root=app, repo_url=upstream, pip_install=installed.append)
    assert installed == []
    assert head(app) == git(upstream, 'rev-parse', 'v1.2.1')


@needs_git
def test_install_leaves_local_changes_alone(repos):
    upstream, app = repos
    before = head(app)
    write(app, 'dictator/__init__.py', "__version__ = '1.1.0'  # my change\n")
    assert updater.self_update_blocker(app) == 'local_changes'
    with pytest.raises(UpdateError) as e:
        updater.install('v1.2.0', root=app, repo_url=upstream, pip_install=lambda text: pytest.fail('pip'))
    assert e.value.code == 'local_changes'
    assert head(app) == before


@needs_git
def test_install_refuses_a_copy_with_commits_of_its_own(repos):
    upstream, app = repos
    write(app, 'notes.txt', 'mine\n')
    git(app, 'add', '.')
    git(app, 'commit', '-q', '-m', 'Mine')
    before = head(app)
    with pytest.raises(UpdateError) as e:
        updater.install('v1.2.0', root=app, repo_url=upstream, pip_install=lambda text: pytest.fail('pip'))
    assert e.value.code == 'diverged'
    assert head(app) == before


@needs_git
def test_install_changes_nothing_when_pip_fails(repos):
    upstream, app = repos
    before = head(app)

    def failing_pip(text):
        raise UpdateError('failed', 'pip: no network')
    with pytest.raises(UpdateError) as e:
        updater.install('v1.2.0', root=app, repo_url=upstream, pip_install=failing_pip)
    assert e.value.code == 'failed'
    assert head(app) == before


@needs_git
def test_install_a_tag_that_does_not_exist_fails_cleanly(repos):
    upstream, app = repos
    before = head(app)
    with pytest.raises(UpdateError) as e:
        updater.install('v9.9.9', root=app, repo_url=upstream, pip_install=lambda text: None)
    assert e.value.code == 'failed'
    assert head(app) == before


def test_install_rejects_anything_that_is_not_a_version(tmp_path):
    with pytest.raises(UpdateError):
        updater.install('main; echo', root=str(tmp_path), repo_url='nowhere')


def test_a_folder_that_is_not_a_clone_cannot_update_itself(tmp_path):
    assert updater.self_update_blocker(str(tmp_path)) == 'not_git'


def test_without_git_it_cannot_update_itself(tmp_path, monkeypatch):
    os.makedirs(tmp_path / '.git')
    monkeypatch.setattr(updater, '_git_exe', lambda: None)
    assert updater.self_update_blocker(str(tmp_path)) == 'no_git'


# --- dialog flow (fake dialogs, fake network) -----------------------------------------------
class Flow(update_flow.UpdateFlow):
    """Runs the work in the same thread and answers the dialogs from a script."""

    def __init__(self, answers=()):
        self.restarted = []
        super().__init__(lambda: self.restarted.append(True))
        self.answers = list(answers)
        self.dialogs = []
        self.opened = []

    def background(self, work, then):
        try:
            then(True, work())
        except UpdateError as e:
            then(False, e)

    def ask(self, kind, text, buttons):
        self.dialogs.append((kind, text, [key for key, _ in buttons]))
        return self.answers.pop(0) if self.answers else 'close'

    def open_page(self, url):
        self.opened.append(url)

    def _wait(self, on):
        pass


AVAILABLE = {'newer': True, 'version': '1.2.0', 'tag': 'v1.2.0',
             'url': 'https://github.com/javimentallab/Dictator/releases/tag/v1.2.0'}


@pytest.fixture
def flow_env(monkeypatch):
    i18n.set_language('en')
    monkeypatch.setattr(update_flow, '__version__', '1.1.0')
    calls = {'install': []}
    monkeypatch.setattr(updater, 'check', lambda: dict(AVAILABLE))
    monkeypatch.setattr(updater, 'self_update_blocker', lambda: None)
    monkeypatch.setattr(updater, 'install', lambda tag: calls['install'].append(tag) or 'abc123')
    return calls


def test_flow_up_to_date(flow_env, monkeypatch):
    monkeypatch.setattr(updater, 'check', lambda: dict(AVAILABLE, newer=False))
    flow = Flow()
    flow.start()
    (kind, text, buttons), = flow.dialogs
    assert kind == 'information' and 'latest version' in text and '1.1.0' in text
    assert not flow.busy and flow_env['install'] == []


def test_flow_offline(flow_env, monkeypatch):
    def offline():
        raise UpdateError('failed', 'ConnectError: offline')
    monkeypatch.setattr(updater, 'check', offline)
    flow = Flow()
    flow.start()
    (kind, text, _), = flow.dialogs
    assert kind == 'warning' and 'internet connection' in text and 'ConnectError: offline' in text
    assert not flow.busy


def test_flow_update_and_restart(flow_env):
    flow = Flow(['install', 'restart'])
    flow.start()
    assert flow_env['install'] == ['v1.2.0']
    first, second = flow.dialogs
    assert first[0] == 'question' and 'Dictator 1.2.0' in first[1] and 'version 1.1.0' in first[1]
    assert 'settings will not change' in first[1]
    assert first[2] == ['install', 'notes', 'close']
    assert '1.2.0 is installed' in second[1]
    assert flow.restarted == [True] and not flow.busy


def test_flow_update_without_restart(flow_env):
    flow = Flow(['install', 'close'])
    flow.start()
    assert flow_env['install'] == ['v1.2.0'] and flow.restarted == []


def test_flow_not_now_installs_nothing(flow_env):
    flow = Flow(['close'])
    flow.start()
    assert flow_env['install'] == [] and flow.opened == [] and not flow.busy


def test_flow_release_notes_open_the_release_page(flow_env):
    flow = Flow(['notes'])
    flow.start()
    assert flow.opened == [AVAILABLE['url']] and flow_env['install'] == []


def test_flow_copy_that_cannot_update_itself_offers_the_release_page(flow_env, monkeypatch):
    monkeypatch.setattr(updater, 'self_update_blocker', lambda: 'not_git')
    flow = Flow(['open'])
    flow.start()
    (kind, text, buttons), = flow.dialogs
    assert 'git clone' in text and 'release page' in text and buttons == ['open', 'close']
    assert flow.opened == [AVAILABLE['url']] and flow_env['install'] == []


def test_flow_diverged_copy_falls_back_to_the_release_page(flow_env, monkeypatch):
    def diverged(tag):
        raise UpdateError('diverged')
    monkeypatch.setattr(updater, 'install', diverged)
    flow = Flow(['install', 'open'])
    flow.start()
    assert 'commits of its own' in flow.dialogs[-1][1]
    assert flow.opened == [AVAILABLE['url']] and flow.restarted == []


def test_flow_failed_install_says_nothing_changed(flow_env, monkeypatch):
    def failed(tag):
        raise UpdateError('failed', 'git fetch: could not resolve host')
    monkeypatch.setattr(updater, 'install', failed)
    flow = Flow(['install'])
    flow.start()
    kind, text, _ = flow.dialogs[-1]
    assert kind == 'warning' and 'has not been changed' in text and 'could not resolve host' in text
    assert flow.restarted == [] and not flow.busy


def test_flow_ignores_a_second_click_while_busy(flow_env):
    flow = Flow()
    flow.busy = True
    flow.start()
    assert flow.dialogs == []
