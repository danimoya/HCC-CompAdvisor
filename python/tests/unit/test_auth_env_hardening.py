"""
Unit tests for login-lockout keying, the .env writer and the first-run bootstrap.

- Client IP for the lockout comes from the right-most X-Forwarded-For hop not
  added by one of TRUSTED_PROXY_COUNT proxies (a spoofed left-most value is
  ignored), X-Real-IP with a single proxy, or the TCP peer.
- A global failure ceiling pauses all logins, so rotating identities is useless.
- Config.write_env_file writes 0600 files atomically and quotes values so
  python-dotenv reads back exactly what was written; unrepresentable values are
  rejected before anything is written.
- No 'admin123' default is left anywhere.
- The one-time bootstrap token is accepted only while no admin password exists
  and first-run setup is pending, and never again once setup saved one.
"""
import logging
import os
import stat
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
import streamlit as st
from dotenv import dotenv_values
from streamlit.testing.v1 import AppTest

from hcc_advisor import auth
from hcc_advisor import config as config_module
from hcc_advisor.auth import AuthManager, ROLE_ADMIN
from hcc_advisor.config import Config, env_value_problem, format_env_line


class _Session(dict):
    """Session state stand-in supporting both item and attribute access."""

    def __getattr__(self, name):
        try:
            return self[name]
        except KeyError:
            raise AttributeError(name)

    def __setattr__(self, name, value):
        self[name] = value


@pytest.fixture(autouse=True)
def clean_auth_state(monkeypatch):
    """Fresh lockout and bootstrap state for every test."""
    monkeypatch.setattr(auth, '_LOCKOUT_STATE', {})
    monkeypatch.setattr(auth, '_GLOBAL_STATE',
                        {"fails": auth.deque(), "locked_until": 0.0, "level": 0,
                         "last_trigger": 0.0})
    monkeypatch.setattr(auth, '_BOOTSTRAP', {"token": None, "retired": False})


@pytest.fixture
def session(monkeypatch):
    """auth's streamlit handle replaced by a plain session + mocked output."""
    state = _Session(authenticated=False, login_attempts=0, username=None, role=None)
    fake_st = SimpleNamespace(session_state=state, error=MagicMock(), info=MagicMock(),
                              warning=MagicMock())
    monkeypatch.setattr(auth, 'st', fake_st)
    return fake_st


@pytest.fixture
def isolated_env(tmp_path, monkeypatch):
    """Point the config dir at tmp_path and restore os.environ / Config after
    write_env_file's reload (load_dotenv mutates the process environment)."""
    cfg_dir = tmp_path / 'cfg'
    monkeypatch.setenv('HCC_ADVISOR_CONFIG_DIR', str(cfg_dir))
    saved_env = dict(os.environ)
    saved_attrs = {k: v for k, v in vars(Config).items() if k.isupper()}
    saved_active = config_module._active_env_path
    yield cfg_dir
    os.environ.clear()
    os.environ.update(saved_env)
    for k, v in saved_attrs.items():
        setattr(Config, k, v)
    config_module._active_env_path = saved_active


@pytest.fixture
def first_run(monkeypatch):
    """A fresh install: no .env, no CENTRAL_DB_PASSWORD, no admin password."""
    monkeypatch.setattr(config_module, '_active_env_path', None)
    monkeypatch.delenv('CENTRAL_DB_PASSWORD', raising=False)
    monkeypatch.setattr(Config, 'DASHBOARD_PASSWORD', '')
    monkeypatch.setattr(Config, 'OPERATOR_PASSWORD', '')
    monkeypatch.setattr(Config, 'VIEWER_PASSWORD', '')


def _issued_token(capsys):
    """Issue the bootstrap token and read it back from the console output."""
    assert auth.ensure_bootstrap_token() is True
    err = capsys.readouterr().err
    line = next(l for l in err.splitlines() if l.startswith(auth.BOOTSTRAP_TOKEN_LABEL))
    return line.split(':', 1)[1].strip()


# ---------------------------------------------------------------------------
# Client IP derivation
# ---------------------------------------------------------------------------

@pytest.mark.unit
@pytest.mark.auth
class TestClientIp:

    def test_spoofed_leftmost_xff_is_ignored(self):
        # NPM appends the real peer; everything left of it is client-supplied.
        headers = {'X-Forwarded-For': '6.6.6.6, 203.0.113.7'}
        assert auth._derive_client_ip(headers, '172.28.0.5', 1) == '203.0.113.7'

    def test_rotating_spoofed_values_keep_one_key(self, monkeypatch):
        monkeypatch.setattr(Config, 'TRUSTED_PROXY_COUNT', 1)
        keys = set()
        for i in range(10):
            headers = {'X-Forwarded-For': f'10.9.9.{i}, 198.51.100.{i}, 203.0.113.7'}
            with patch.object(auth, '_request_meta', return_value=(headers, '172.28.0.5')):
                keys.add(auth._client_key())
        assert keys == {'203.0.113.7'}

    def test_rightmost_untrusted_hop_with_two_proxies(self):
        headers = {'X-Forwarded-For': '6.6.6.6, 203.0.113.7, 10.0.0.2'}
        assert auth._derive_client_ip(headers, '10.0.0.3', 2) == '203.0.113.7'

    def test_header_names_are_case_insensitive(self):
        headers = {'x-forwarded-for': '6.6.6.6,203.0.113.7'}
        assert auth._derive_client_ip(headers, None, 1) == '203.0.113.7'

    def test_x_real_ip_used_without_xff(self):
        headers = {'X-Real-Ip': '203.0.113.9'}
        assert auth._derive_client_ip(headers, '172.28.0.5', 1) == '203.0.113.9'

    def test_x_real_ip_not_trusted_behind_two_proxies(self):
        # The nearest proxy's X-Real-IP is the next proxy, not the client.
        headers = {'X-Real-Ip': '203.0.113.9'}
        assert auth._derive_client_ip(headers, '10.0.0.3', 2) == '10.0.0.3'

    def test_no_proxy_ignores_headers_and_uses_peer(self):
        headers = {'X-Forwarded-For': '6.6.6.6', 'X-Real-Ip': '7.7.7.7'}
        assert auth._derive_client_ip(headers, '198.51.100.4', 0) == '198.51.100.4'

    def test_chain_shorter_than_trusted_count_falls_back_to_peer(self):
        headers = {'X-Forwarded-For': '6.6.6.6'}
        assert auth._derive_client_ip(headers, '10.0.0.3', 2) == '10.0.0.3'

    def test_non_ip_hop_is_not_used(self):
        headers = {'X-Forwarded-For': 'unknown'}
        assert auth._derive_client_ip(headers, '10.0.0.3', 1) == '10.0.0.3'

    @pytest.mark.parametrize('raw, expected', [
        ('203.0.113.7:4711', '203.0.113.7'),
        ('[2001:db8::1]:443', '2001:db8::1'),
        ('2001:DB8::1', '2001:db8::1'),
    ])
    def test_ports_and_ipv6_are_normalised(self, raw, expected):
        assert auth._derive_client_ip({'X-Forwarded-For': raw}, None, 1) == expected

    def test_fixed_key_when_nothing_is_known(self, monkeypatch):
        monkeypatch.setattr(Config, 'TRUSTED_PROXY_COUNT', 1)
        with patch.object(auth, '_request_meta', return_value=({}, None)):
            assert auth._client_key() == auth._GLOBAL_KEY

    def test_request_meta_degrades_outside_a_session(self):
        assert auth._request_meta() == ({}, None)

    def test_request_meta_reads_streamlit_131_websocket_request(self):
        """Headers and TCP peer come from the session's BrowserWebSocketHandler."""
        from tornado.httputil import HTTPHeaders
        from streamlit.web.server.browser_websocket_handler import BrowserWebSocketHandler

        headers = HTTPHeaders()
        headers.add('X-Forwarded-For', '6.6.6.6')             # sent by the client
        headers.add('X-Forwarded-For', '203.0.113.7')         # appended by NPM
        handler = BrowserWebSocketHandler.__new__(BrowserWebSocketHandler)
        handler.request = SimpleNamespace(headers=headers, remote_ip='172.28.0.5')
        ctx = SimpleNamespace(session_id='s1', gather_usage_stats=False)
        fake_runtime = SimpleNamespace(get_client=lambda sid: handler if sid == 's1' else None)
        with patch('streamlit.runtime.get_instance', return_value=fake_runtime), \
                patch('streamlit.runtime.scriptrunner.get_script_run_ctx', return_value=ctx), \
                patch('streamlit.web.server.websocket_headers.get_script_run_ctx',
                      return_value=ctx):
            got_headers, peer = auth._request_meta()
            assert peer == '172.28.0.5'
            assert got_headers['X-Forwarded-For'] == '6.6.6.6,203.0.113.7'
            with patch.object(Config, 'TRUSTED_PROXY_COUNT', 1):
                assert auth._client_key() == '203.0.113.7'

    def test_default_trusted_proxy_count_matches_docker(self):
        # docker-compose puts exactly one proxy (Nginx Proxy Manager) in front.
        assert Config.TRUSTED_PROXY_COUNT == int(os.getenv('TRUSTED_PROXY_COUNT', '1'))
        assert auth._trusted_proxy_count() >= 0


# ---------------------------------------------------------------------------
# Global failure ceiling
# ---------------------------------------------------------------------------

@pytest.mark.unit
@pytest.mark.auth
class TestGlobalCeiling:

    def test_failures_across_keys_trigger_global_lock(self):
        for i in range(auth._GLOBAL_FAIL_THRESHOLD - 1):
            auth._record_failure(f'198.51.100.{i}')
        assert auth._global_lockout_remaining() == 0
        auth._record_failure('198.51.100.250')
        assert auth._global_lockout_remaining() > auth._GLOBAL_LOCK_BASE_SECONDS - 5

    def test_old_failures_age_out_of_the_window(self, monkeypatch):
        now = [1_000_000.0]
        monkeypatch.setattr(auth.time, 'time', lambda: now[0])
        for i in range(auth._GLOBAL_FAIL_THRESHOLD - 1):
            auth._record_failure(f'k{i}')
        now[0] += auth._GLOBAL_FAIL_WINDOW_SECONDS + 1
        auth._record_failure('late')
        assert auth._global_lockout_remaining() == 0

    def test_repeated_triggers_escalate(self, monkeypatch):
        now = [1_000_000.0]
        monkeypatch.setattr(auth.time, 'time', lambda: now[0])
        windows = []
        for _ in range(3):
            for i in range(auth._GLOBAL_FAIL_THRESHOLD):
                auth._record_failure(f'k{i}')
            windows.append(auth._global_lockout_remaining())
            now[0] += windows[-1] + 1
        base = auth._GLOBAL_LOCK_BASE_SECONDS
        assert windows == [base, base * 2, base * 4]

    def test_global_lock_refuses_even_the_right_password(self, session, monkeypatch):
        monkeypatch.setattr(Config, 'DASHBOARD_PASSWORD', 'correct-horse-battery')
        for i in range(auth._GLOBAL_FAIL_THRESHOLD):
            auth._record_failure(f'198.51.100.{i}')
        with patch.object(auth, '_request_meta', return_value=({}, '192.0.2.1')):
            assert AuthManager.login('correct-horse-battery') is False
        assert session.session_state.authenticated is False
        assert 'paused' in session.error.call_args.args[0]

    def test_rotating_xff_login_attempts_hit_the_ceiling(self, session, monkeypatch):
        """An attacker rotating spoofed XFF values (and sessions) is stopped."""
        monkeypatch.setattr(Config, 'DASHBOARD_PASSWORD', 'correct-horse-battery')
        monkeypatch.setattr(Config, 'TRUSTED_PROXY_COUNT', 0)  # direct exposure
        for i in range(auth._GLOBAL_FAIL_THRESHOLD):
            session.session_state.login_attempts = 0  # new session each time
            headers = {'X-Forwarded-For': f'10.0.{i}.1'}
            with patch.object(auth, '_request_meta', return_value=(headers, f'203.0.113.{i}')):
                AuthManager.login('wrong-guess')
        assert auth._global_lockout_remaining() > 0


# ---------------------------------------------------------------------------
# .env writing
# ---------------------------------------------------------------------------

_TRICKY = {
    'SPACES': 'pass word with spaces',
    'HASH': 'pa #ss#word',
    'SINGLE': "it's",
    'DOUBLE': 'say "hi"',
    'BACKSLASH': 'C:\\temp\\',          # trailing backslash, followed by quoted lines
    'QUOTE_BACKSLASH': "it's C:\\dir\\",
    'MIXED': '\\\'"\\"',
    'BACKSLASH_QUOTE': 'a\\\'b\\\\',
    'DOLLAR': 'pa$$word$',
    'OPEN_BRACE': '${not closed',
    'UNICODE': 'contraseña-ñandú',
    'EQUALS': '=a=b=',
    'EDGES': '  padded  ',
    'EMPTY': '',
}


@pytest.mark.unit
class TestEnvWriter:

    def test_round_trip_with_python_dotenv(self, isolated_env):
        path = Config.write_env_file(_TRICKY)
        assert dotenv_values(path) == _TRICKY
        # ...and the reload through load_dotenv sees the same values.
        for key, value in _TRICKY.items():
            assert os.environ[key] == value

    def test_config_reloads_secrets_exactly(self, isolated_env):
        settings = {'DASHBOARD_PASSWORD': 'a #b \'c\' "d" \\e $f',
                    'CENTRAL_DB_PASSWORD': 'x y#z', 'ENCRYPTION_KEY': 'k=='}
        Config.write_env_file(settings)
        assert Config.DASHBOARD_PASSWORD == settings['DASHBOARD_PASSWORD']
        assert Config.CENTRAL_DB_PASSWORD == settings['CENTRAL_DB_PASSWORD']
        assert Config.ENCRYPTION_KEY == settings['ENCRYPTION_KEY']

    def test_writes_exactly_the_given_keys_in_order(self, isolated_env):
        settings = {'CENTRAL_DB_HOST': 'db', 'CENTRAL_DB_PORT': '1521',
                    'DASHBOARD_PASSWORD': 'p', 'ENCRYPTION_KEY': 'k'}
        path = Config.write_env_file(settings)
        assert list(dotenv_values(path)) == list(settings)

    def test_file_mode_is_0600_whatever_the_umask(self, isolated_env):
        old = os.umask(0o022)
        try:
            path = Config.write_env_file({'DASHBOARD_PASSWORD': 'secret'})
        finally:
            os.umask(old)
        assert stat.S_IMODE(path.stat().st_mode) == 0o600
        assert stat.S_IMODE(isolated_env.stat().st_mode) == 0o700

    def test_replacing_a_world_readable_file_makes_it_private(self, isolated_env):
        isolated_env.mkdir(parents=True)
        env_file = isolated_env / '.env'
        env_file.write_text("OLD=1\n")
        env_file.chmod(0o644)
        old_inode = env_file.stat().st_ino
        Config.write_env_file({'DASHBOARD_PASSWORD': 'secret'})
        assert stat.S_IMODE(env_file.stat().st_mode) == 0o600
        assert env_file.stat().st_ino != old_inode  # replaced, not rewritten in place
        assert dotenv_values(env_file) == {'DASHBOARD_PASSWORD': 'secret'}
        assert sorted(p.name for p in isolated_env.iterdir()) == ['.env']

    def test_failed_replace_leaves_old_file_and_no_temp(self, isolated_env):
        isolated_env.mkdir(parents=True)
        env_file = isolated_env / '.env'
        env_file.write_text("DASHBOARD_PASSWORD=old\n")
        with patch.object(config_module.os, 'replace', side_effect=OSError('disk full')), \
                pytest.raises(OSError):
            Config.write_env_file({'DASHBOARD_PASSWORD': 'new'})
        assert env_file.read_text() == "DASHBOARD_PASSWORD=old\n"
        assert sorted(p.name for p in isolated_env.iterdir()) == ['.env']

    @pytest.mark.parametrize('value, fragment', [
        ('line\nbreak', 'line break'),
        ('carriage\rreturn', 'line break'),
        ('${HOME}', '${...}'),
        ('pre${UNDEFINED_HCC_VAR}post', '${...}'),
        ('${X:-default}', '${...}'),
        ('nul\x00byte', 'NUL'),
        # python-dotenv reads a backslash before a closing quote as an escaped
        # quote, so a trailing backslash is only storable unquoted.
        (' leading space\\', 'backslash'),
        ("'leading quote\\", 'backslash'),
        ('comment #like\\', 'backslash'),
    ])
    def test_unrepresentable_values_are_rejected(self, isolated_env, value, fragment):
        isolated_env.mkdir(parents=True)
        env_file = isolated_env / '.env'
        env_file.write_text("KEEP=1\n")
        with pytest.raises(ValueError) as exc:
            Config.write_env_file({'CENTRAL_DB_HOST': 'db', 'DASHBOARD_PASSWORD': value})
        message = str(exc.value)
        assert 'DASHBOARD_PASSWORD' in message and fragment in message
        assert value not in message  # never echo the secret
        assert env_file.read_text() == "KEEP=1\n"  # nothing written

    @pytest.mark.parametrize('key', ['1BAD', 'BAD-KEY', 'BAD KEY', '', 'A=B'])
    def test_invalid_keys_are_rejected(self, key):
        with pytest.raises(ValueError):
            format_env_line(key, 'v')

    def test_representable_values_have_no_problem(self):
        for value in _TRICKY.values():
            assert env_value_problem(value) is None


# ---------------------------------------------------------------------------
# No built-in default password
# ---------------------------------------------------------------------------

_REPO_ROOT = Path(__file__).resolve().parents[3]
_PYTHON_DIR = _REPO_ROOT / 'python'
_SCAN_SUFFIXES = {'.py', '.md', '.txt', '.example', '.yml', '.yaml', '.sh', '.toml',
                  '.ini', '.cfg', '.json', '.conf'}


def _scanned_files():
    """Package code plus the docs/config a user reads (no venvs, caches or
    other checkouts, which a plain walk of the repo root could reach)."""
    for root in (_PYTHON_DIR / 'hcc_advisor', _REPO_ROOT / 'docker', _REPO_ROOT / 'docs'):
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [d for d in dirnames if not d.startswith(('.', '__'))]
            for name in filenames:
                path = Path(dirpath) / name
                if path.suffix in _SCAN_SUFFIXES or name == '.env.example':
                    yield path
    yield from _PYTHON_DIR.glob('*.md')
    yield from _PYTHON_DIR.glob('*.txt')
    yield from (_PYTHON_DIR / '.env.example', _REPO_ROOT / 'README.md',
                _REPO_ROOT / 'pyproject.toml')


@pytest.mark.unit
def test_no_admin123_default_anywhere():
    """'admin123' may only appear in auth.py's denylist of forbidden passwords."""
    offenders = []
    for path in _scanned_files():
        if not path.is_file():
            continue
        text = path.read_text(encoding='utf-8', errors='ignore')
        for lineno, line in enumerate(text.splitlines(), 1):
            if 'admin123' in line:
                allowed = path.name == 'auth.py' and '_FORBIDDEN_PASSWORDS' in line
                if not allowed:
                    offenders.append(f"{path.relative_to(_REPO_ROOT)}:{lineno}")
    assert offenders == []
    # The one allowed occurrence is the denylist itself.
    assert 'admin123' in auth._FORBIDDEN_PASSWORDS


@pytest.mark.unit
class TestNewPasswordValidation:

    @pytest.mark.parametrize('pwd, fragment', [
        ('', 'required'),
        ('short-pw', f'at least {auth.MIN_PASSWORD_LENGTH}'),
        ('admin123', f'at least {auth.MIN_PASSWORD_LENGTH}'),
        ('Dashboard123!', 'known default'),
        ('twelve chars\nplus', 'line break'),
        ('${HOME}-long-enough', '${...}'),
    ])
    def test_rejects(self, pwd, fragment):
        assert fragment in auth.validate_new_password(pwd)

    def test_accepts_a_strong_password(self):
        assert auth.validate_new_password('correct horse #battery') is None


# ---------------------------------------------------------------------------
# First-run bootstrap token
# ---------------------------------------------------------------------------

@pytest.mark.unit
@pytest.mark.auth
class TestBootstrapToken:

    def test_token_printed_once_and_labelled(self, first_run, capsys, caplog):
        with caplog.at_level(logging.DEBUG):
            token = _issued_token(capsys)
            assert auth.ensure_bootstrap_token() is True
        assert len(token) >= 24
        assert capsys.readouterr().err == ''  # not re-issued
        assert token not in caplog.text       # console only, not the app log

    def test_token_logs_in_as_admin_on_first_run(self, first_run, session, capsys):
        token = _issued_token(capsys)
        with patch.object(auth, '_request_meta', return_value=({}, '192.0.2.1')):
            assert AuthManager.login(token) is True
        state = session.session_state
        assert state.authenticated is True and state.role == ROLE_ADMIN
        assert state[auth.BOOTSTRAP_SESSION_KEY] is True

    def test_wrong_token_is_a_failed_attempt(self, first_run, session, capsys):
        _issued_token(capsys)
        with patch.object(auth, '_request_meta', return_value=({}, '192.0.2.1')):
            assert AuthManager.login('not-the-token') is False
        assert session.session_state.authenticated is False
        assert auth._LOCKOUT_STATE['192.0.2.1']['fails'] == 1

    def test_no_token_when_an_admin_password_exists(self, first_run, session, monkeypatch, capsys):
        monkeypatch.setattr(Config, 'DASHBOARD_PASSWORD', 'configured-admin-pw')
        assert auth.ensure_bootstrap_token() is False
        assert capsys.readouterr().err == ''
        assert auth._check_bootstrap_token('anything') is False

    def test_no_token_when_not_first_run(self, first_run, monkeypatch, capsys):
        monkeypatch.setattr(config_module, '_active_env_path', Path('/somewhere/.env'))
        assert auth.ensure_bootstrap_token() is False
        assert capsys.readouterr().err == ''

    def test_token_rejected_once_a_password_is_configured(self, first_run, session,
                                                          monkeypatch, capsys):
        token = _issued_token(capsys)
        monkeypatch.setattr(Config, 'DASHBOARD_PASSWORD', 'configured-admin-pw')
        with patch.object(auth, '_request_meta', return_value=({}, '192.0.2.1')):
            assert AuthManager.login(token) is False
        # Retired for good: even if the password vanished again, no bootstrap.
        monkeypatch.setattr(Config, 'DASHBOARD_PASSWORD', '')
        assert auth.bootstrap_active() is False
        assert auth._check_bootstrap_token(token) is False

    def test_setup_write_retires_token_and_signs_out_bootstrap_session(
            self, first_run, isolated_env, session, capsys):
        token = _issued_token(capsys)
        with patch.object(auth, '_request_meta', return_value=({}, '192.0.2.1')):
            assert AuthManager.login(token) is True

        # The wizard saves .env with the chosen admin password.
        env_path = Config.write_env_file({'CENTRAL_DB_PASSWORD': 'central',
                                          'DASHBOARD_PASSWORD': 'chosen-admin-pw'})
        assert token not in env_path.read_text()  # never persisted
        assert auth.bootstrap_active() is False

        # The bootstrap session is signed out on its next page load...
        with patch.object(AuthManager, 'show_login_page'), \
                patch.object(auth.st, 'stop', create=True, side_effect=RuntimeError('stopped')), \
                pytest.raises(RuntimeError, match='stopped'):
            AuthManager.require_authentication()
        assert session.session_state.authenticated is False

        # ...the token no longer works, and the new password does.
        session.session_state.login_attempts = 0
        with patch.object(auth, '_request_meta', return_value=({}, '192.0.2.1')):
            assert AuthManager.login(token) is False
            assert AuthManager.login('chosen-admin-pw') is True
        assert session.session_state[auth.BOOTSTRAP_SESSION_KEY] is False

    def test_regular_admin_session_survives_setup(self, first_run, session, monkeypatch):
        monkeypatch.setattr(Config, 'DASHBOARD_PASSWORD', 'configured-admin-pw')
        with patch.object(auth, '_request_meta', return_value=({}, '192.0.2.1')):
            assert AuthManager.login('configured-admin-pw') is True
        with patch.object(AuthManager, 'show_login_page'):
            AuthManager.require_authentication()
        assert session.session_state.authenticated is True


def _login_app():
    from hcc_advisor.auth import AuthManager
    AuthManager.require_authentication()
    import streamlit as st
    st.write("inside")


@pytest.mark.unit
@pytest.mark.auth
def test_login_page_accepts_bootstrap_token(first_run, capsys):
    with patch.object(st, 'rerun'):
        at = AppTest.from_function(_login_app, default_timeout=10).run()
        token = next(l for l in capsys.readouterr().err.splitlines()
                     if l.startswith(auth.BOOTSTRAP_TOKEN_LABEL)).split(':', 1)[1].strip()
        box = at.text_input[0]
        assert box.label == 'Setup token'
        assert any(auth.BOOTSTRAP_TOKEN_LABEL in i.value for i in at.info)
        assert token not in str(at)  # never rendered
        box.input(token)
        at.button[0].click().run()
    assert at.session_state['authenticated'] is True
    assert at.session_state['role'] == ROLE_ADMIN


# ---------------------------------------------------------------------------
# Setup wizard: password step and save
# ---------------------------------------------------------------------------

def _security_app():
    from hcc_advisor.views.page_00_setup import _wizard_security
    _wizard_security()


def _finish_app():
    from hcc_advisor.views.page_00_setup import _wizard_finish
    _wizard_finish()


_CONN = {'host': 'db', 'port': 1521, 'service': 'FREEPDB1',
         'username': 'COMPRESSION_MGR', 'password': 'central-pw'}


@pytest.mark.unit
class TestWizardPassword:

    def _submit(self, pwd, confirm):
        with patch.object(st, 'rerun'):
            at = AppTest.from_function(_security_app, default_timeout=10)
            at.session_state['setup_conn'] = dict(_CONN)
            at.session_state['setup_step'] = 4
            at.run()
            next(t for t in at.text_input if t.label == 'Dashboard Password').input(pwd)
            next(t for t in at.text_input if t.label == 'Confirm Password').input(confirm)
            next(b for b in at.button if b.label == 'Save Configuration').click().run()
        return at

    def test_short_password_rejected(self):
        at = self._submit('short', 'short')
        assert 'at least' in at.error[0].value
        assert at.session_state['setup_step'] == 4
        assert 'dashboard_password' not in at.session_state['setup_conn']

    def test_mismatch_rejected(self):
        at = self._submit('long-enough-password', 'long-enough-passw0rd')
        assert 'do not match' in at.error[0].value

    def test_valid_password_advances(self):
        at = self._submit('long-enough-password', 'long-enough-password')
        assert not at.error
        assert at.session_state['setup_step'] == 5
        assert at.session_state['setup_conn']['dashboard_password'] == 'long-enough-password'

    def test_finish_without_password_does_not_save(self):
        with patch.object(Config, 'write_env_file') as write:
            at = AppTest.from_function(_finish_app, default_timeout=10)
            at.session_state['setup_conn'] = dict(_CONN)
            at.run()
        write.assert_not_called()
        assert 'Security step' in at.error[0].value
        assert not any(b.label == 'Save & Launch Dashboard' for b in at.button)

    def test_finish_saves_chosen_password(self):
        conn = dict(_CONN, dashboard_password='long-enough-password', encryption_key='k')
        with patch.object(Config, 'write_env_file', return_value=Path('/x/.env')) as write, \
                patch('time.sleep'), patch.object(st, 'rerun'):
            at = AppTest.from_function(_finish_app, default_timeout=10)
            at.session_state['setup_conn'] = conn
            at.run()
            next(b for b in at.button if b.label == 'Save & Launch Dashboard').click().run()
        settings = write.call_args.args[0]
        assert settings['DASHBOARD_PASSWORD'] == 'long-enough-password'
        assert at.session_state['setup_complete'] is True

    def test_finish_reports_unstorable_value(self):
        conn = dict(_CONN, dashboard_password='long-enough-password', encryption_key='k')
        with patch.object(Config, 'write_env_file',
                          side_effect=ValueError('CENTRAL_DB_PASSWORD contains a line break')), \
                patch('time.sleep'), patch.object(st, 'rerun'):
            at = AppTest.from_function(_finish_app, default_timeout=10)
            at.session_state['setup_conn'] = conn
            at.run()
            next(b for b in at.button if b.label == 'Save & Launch Dashboard').click().run()
        assert 'CENTRAL_DB_PASSWORD contains a line break' in at.error[0].value
        assert 'setup_complete' not in at.session_state
