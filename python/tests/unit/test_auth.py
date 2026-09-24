"""
Unit tests for hcc_advisor.auth: role resolution, login, lockout and session
handling.

- A password maps to the highest configured role it matches; unset or
  known-default passwords never grant a role.
- Failed logins lock the client key from the 5th failure with a doubling
  window (capped at an hour); a success clears it, and a locked key refuses
  even the right password.
- login fails closed when no usable password is configured, and enforces the
  per-session attempt limit.
- Sessions time out after SESSION_TIMEOUT_MINUTES of inactivity.

Client-IP keying, the global ceiling and the first-run token are covered by
test_auth_env_hardening; role gates on pages by test_rbac_gates.
"""
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from hcc_advisor import auth
from hcc_advisor.auth import (
    AuthManager, ROLE_ADMIN, ROLE_OPERATOR, ROLE_VIEWER,
)
from hcc_advisor.config import Config

ADMIN_PW = 'admin-secret-pw'
OPERATOR_PW = 'operator-secret-pw'
VIEWER_PW = 'viewer-secret-pw'


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
    """Fresh lockout / bootstrap state and known passwords for every test."""
    monkeypatch.setattr(auth, '_LOCKOUT_STATE', {})
    monkeypatch.setattr(auth, '_GLOBAL_STATE',
                        {"fails": auth.deque(), "locked_until": 0.0, "level": 0,
                         "last_trigger": 0.0})
    monkeypatch.setattr(auth, '_BOOTSTRAP', {"token": None, "retired": True})
    monkeypatch.setattr(Config, 'DASHBOARD_PASSWORD', ADMIN_PW)
    monkeypatch.setattr(Config, 'OPERATOR_PASSWORD', '')
    monkeypatch.setattr(Config, 'VIEWER_PASSWORD', '')
    monkeypatch.setattr(Config, 'MAX_LOGIN_ATTEMPTS', 3)
    monkeypatch.setattr(Config, 'SESSION_TIMEOUT_MINUTES', 30)


@pytest.fixture
def session(monkeypatch):
    """auth's streamlit handle replaced by a plain session + mocked output."""
    state = _Session(authenticated=False, login_attempts=0, username=None, role=None,
                     last_activity=datetime.now())
    fake_st = SimpleNamespace(session_state=state, error=MagicMock(), info=MagicMock(),
                              warning=MagicMock())
    monkeypatch.setattr(auth, 'st', fake_st)
    return fake_st


def _errors(fake_st) -> str:
    return ' | '.join(c.args[0] for c in fake_st.error.call_args_list)


# ---------------------------------------------------------------------------
# _resolve_role
# ---------------------------------------------------------------------------

@pytest.mark.unit
@pytest.mark.auth
class TestResolveRole:

    def test_admin_password(self):
        assert AuthManager._resolve_role(ADMIN_PW) == ROLE_ADMIN

    @pytest.mark.parametrize('password', ['', None, 'wrong-password', ADMIN_PW + ' ',
                                          ADMIN_PW.upper()])
    def test_no_match(self, password):
        assert AuthManager._resolve_role(password) is None

    def test_operator_and_viewer_when_configured(self, monkeypatch):
        monkeypatch.setattr(Config, 'OPERATOR_PASSWORD', OPERATOR_PW)
        monkeypatch.setattr(Config, 'VIEWER_PASSWORD', VIEWER_PW)
        assert AuthManager._resolve_role(OPERATOR_PW) == ROLE_OPERATOR
        assert AuthManager._resolve_role(VIEWER_PW) == ROLE_VIEWER
        assert AuthManager._resolve_role(ADMIN_PW) == ROLE_ADMIN

    def test_unset_roles_never_match(self):
        # OPERATOR/VIEWER_PASSWORD are '' here: an empty submission is no role.
        assert AuthManager._resolve_role('') is None

    def test_shared_password_resolves_to_the_highest_role(self, monkeypatch):
        monkeypatch.setattr(Config, 'VIEWER_PASSWORD', ADMIN_PW)
        monkeypatch.setattr(Config, 'OPERATOR_PASSWORD', ADMIN_PW)
        assert AuthManager._resolve_role(ADMIN_PW) == ROLE_ADMIN
        monkeypatch.setattr(Config, 'DASHBOARD_PASSWORD', 'another-admin-pw')
        assert AuthManager._resolve_role(ADMIN_PW) == ROLE_OPERATOR

    @pytest.mark.parametrize('weak', sorted(auth._FORBIDDEN_PASSWORDS))
    def test_known_default_never_grants_a_role(self, monkeypatch, weak):
        monkeypatch.setattr(Config, 'DASHBOARD_PASSWORD', weak)
        monkeypatch.setattr(Config, 'OPERATOR_PASSWORD', weak)
        assert AuthManager._resolve_role(weak) is None

    def test_non_ascii_password(self, monkeypatch):
        monkeypatch.setattr(Config, 'DASHBOARD_PASSWORD', 'contraseña-señal-ü')
        assert AuthManager._resolve_role('contraseña-señal-ü') == ROLE_ADMIN
        assert AuthManager._resolve_role('contrasena-senal-u') is None


# ---------------------------------------------------------------------------
# Per-key lockout
# ---------------------------------------------------------------------------

@pytest.mark.unit
@pytest.mark.auth
class TestLockout:

    def test_locks_from_the_threshold_with_doubling_window(self):
        windows = [auth._record_failure('10.0.0.1') for _ in range(8)]
        below = auth._LOCKOUT_THRESHOLD - 1
        assert windows[:below] == [0.0] * below
        base = auth._LOCKOUT_BASE_SECONDS
        assert windows[below:] == [base, base * 2, base * 4, base * 8]
        assert auth._lockout_remaining('10.0.0.1') > 0
        assert auth._lockout_remaining('10.0.0.2') == 0.0

    def test_window_is_capped(self):
        for _ in range(auth._LOCKOUT_THRESHOLD + 20):
            window = auth._record_failure('10.0.0.1')
        assert window == auth._LOCKOUT_MAX_SECONDS

    def test_success_clears_the_record(self):
        for _ in range(auth._LOCKOUT_THRESHOLD):
            auth._record_failure('10.0.0.1')
        auth._record_success('10.0.0.1')
        assert auth._lockout_remaining('10.0.0.1') == 0.0
        assert auth._record_failure('10.0.0.1') == 0.0  # counting starts over

    def test_locked_key_refuses_the_right_password(self, session, monkeypatch):
        monkeypatch.setattr(auth, '_client_key', lambda: '10.0.0.1')
        for _ in range(auth._LOCKOUT_THRESHOLD):
            auth._record_failure('10.0.0.1')

        assert AuthManager.login(ADMIN_PW) is False
        assert session.session_state.authenticated is False
        assert 'Locked for' in _errors(session)

    def test_fifth_failed_login_reports_the_lock(self, session, monkeypatch):
        monkeypatch.setattr(auth, '_client_key', lambda: '10.0.0.1')
        monkeypatch.setattr(Config, 'MAX_LOGIN_ATTEMPTS', 100)
        for _ in range(auth._LOCKOUT_THRESHOLD):
            AuthManager.login('wrong-password')
        assert f'Locked for {auth._LOCKOUT_BASE_SECONDS}s' in _errors(session)

    @pytest.mark.parametrize('value, expected', [(2, 2), (-1, 0), ('bad', 1), (None, 1)])
    def test_trusted_proxy_count(self, monkeypatch, value, expected):
        monkeypatch.setattr(Config, 'TRUSTED_PROXY_COUNT', value)
        assert auth._trusted_proxy_count() == expected


# ---------------------------------------------------------------------------
# login / logout
# ---------------------------------------------------------------------------

@pytest.mark.unit
@pytest.mark.auth
class TestLogin:

    def test_success_sets_the_session(self, session):
        session.session_state.login_attempts = 2
        assert AuthManager.login(ADMIN_PW) is True
        state = session.session_state
        assert state.authenticated is True
        assert state.role == ROLE_ADMIN
        assert state.username == ROLE_ADMIN
        assert state.login_attempts == 0
        assert state[auth.BOOTSTRAP_SESSION_KEY] is False
        assert AuthManager.get_current_user() == ROLE_ADMIN

    def test_success_clears_earlier_failures_of_the_key(self, session, monkeypatch):
        monkeypatch.setattr(auth, '_client_key', lambda: '10.0.0.1')
        AuthManager.login('wrong-password')
        assert '10.0.0.1' in auth._LOCKOUT_STATE
        AuthManager.login(ADMIN_PW)
        assert '10.0.0.1' not in auth._LOCKOUT_STATE

    def test_operator_login(self, session, monkeypatch):
        monkeypatch.setattr(Config, 'OPERATOR_PASSWORD', OPERATOR_PW)
        assert AuthManager.login(OPERATOR_PW) is True
        assert AuthManager.get_role() == ROLE_OPERATOR
        assert AuthManager.has_role(ROLE_OPERATOR) is True
        assert AuthManager.has_role(ROLE_ADMIN) is False

    def test_failure_counts_attempts(self, session):
        assert AuthManager.login('wrong-password') is False
        assert session.session_state.login_attempts == 1
        assert '2 attempt(s) remaining' in _errors(session)

    def test_session_attempt_limit(self, session):
        for _ in range(Config.MAX_LOGIN_ATTEMPTS):
            AuthManager.login('wrong-password')
        assert 'Maximum login attempts exceeded' in _errors(session)
        session.error.reset_mock()

        assert AuthManager.login(ADMIN_PW) is False
        assert 'Maximum login attempts (3) exceeded' in _errors(session)
        assert session.session_state.authenticated is False

    @pytest.mark.parametrize('admin_pw', ['', 'admin123'])
    def test_fails_closed_without_a_usable_password(self, session, monkeypatch, admin_pw):
        monkeypatch.setattr(Config, 'DASHBOARD_PASSWORD', admin_pw)
        assert AuthManager.login(admin_pw or 'anything-at-all') is False
        assert 'misconfigured' in _errors(session)
        assert session.session_state.login_attempts == 0  # refused before checking

    def test_operator_still_works_when_admin_password_is_a_default(self, session, monkeypatch):
        monkeypatch.setattr(Config, 'DASHBOARD_PASSWORD', 'admin123')
        monkeypatch.setattr(Config, 'OPERATOR_PASSWORD', OPERATOR_PW)
        assert AuthManager.login('admin123') is False
        assert AuthManager.login(OPERATOR_PW) is True
        assert AuthManager.get_role() == ROLE_OPERATOR

    def test_logout(self, session):
        AuthManager.login(ADMIN_PW)
        AuthManager.logout()
        state = session.session_state
        assert state.authenticated is False
        assert state.role is None and state.username is None
        assert AuthManager.is_authenticated() is False
        assert AuthManager.get_current_user() == 'unknown'


# ---------------------------------------------------------------------------
# Session state and timeout
# ---------------------------------------------------------------------------

@pytest.mark.unit
@pytest.mark.auth
class TestSessionManagement:

    def test_initialize_session_state_sets_defaults_once(self, monkeypatch):
        state = _Session()
        monkeypatch.setattr(auth, 'st', SimpleNamespace(session_state=state))
        AuthManager.initialize_session_state()
        assert state.authenticated is False
        assert state.login_attempts == 0
        assert state.username is None and state.role is None
        assert isinstance(state.last_activity, datetime)

        state.login_attempts = 2
        AuthManager.initialize_session_state()
        assert state.login_attempts == 2

    def test_idle_session_times_out(self, session):
        AuthManager.login(ADMIN_PW)
        session.session_state.last_activity = datetime.now() - timedelta(minutes=31)
        assert AuthManager.check_session_timeout() is True
        assert session.session_state.authenticated is False

    def test_active_session_does_not_time_out(self, session):
        AuthManager.login(ADMIN_PW)
        session.session_state.last_activity = datetime.now() - timedelta(minutes=29)
        assert AuthManager.check_session_timeout() is False
        assert session.session_state.authenticated is True

    def test_update_activity(self, session):
        session.session_state.last_activity = datetime.now() - timedelta(minutes=10)
        AuthManager.update_activity()
        assert datetime.now() - session.session_state.last_activity < timedelta(seconds=5)

    def test_require_role_reports_the_missing_role(self, session, monkeypatch):
        monkeypatch.setattr(Config, 'VIEWER_PASSWORD', VIEWER_PW)
        AuthManager.login(VIEWER_PW)
        assert AuthManager.require_role(ROLE_VIEWER) is True
        assert AuthManager.require_role(ROLE_OPERATOR) is False
        assert "requires the 'operator' role (you are 'viewer')" in _errors(session)
