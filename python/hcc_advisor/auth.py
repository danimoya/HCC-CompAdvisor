"""
Authentication Module for HCC Compression Advisor Dashboard
Handles user authentication and session management
"""

import streamlit as st
from collections import deque
from datetime import datetime, timedelta
from typing import Optional, List, Tuple
import hashlib
import hmac
import ipaddress
import secrets
import sys
import threading
import time
from hcc_advisor.config import config, env_value_problem


# Role hierarchy (ascending privilege). A role grants its own capabilities plus
# all roles below it: admin > operator > viewer.
ROLE_VIEWER = 'viewer'
ROLE_OPERATOR = 'operator'
ROLE_ADMIN = 'admin'
ROLE_LEVELS = {ROLE_VIEWER: 0, ROLE_OPERATOR: 1, ROLE_ADMIN: 2}


# Passwords that must never be accepted, even if accidentally configured.
# (Historical built-in defaults that were shipped in templates/examples.)
_FORBIDDEN_PASSWORDS = frozenset({"admin123", "Dashboard123!", "Dashboard123"})

# Minimum length for a dashboard password chosen in the setup wizard (matches
# the "minimum 12 characters" guidance in the README).
MIN_PASSWORD_LENGTH = 12


# ---------------------------------------------------------------------------
# Server-side brute-force lockout (CWE-307)
# ---------------------------------------------------------------------------
# The per-session st.session_state counter is trivially bypassed by starting a
# fresh session (cleared cookie / scripted requests). This module-level store
# lives in the SERVER process, so it persists ACROSS sessions and cannot be reset
# by the client. It is keyed by client IP (see _derive_client_ip), and a global
# ceiling across all keys stops an attacker who rotates identities.
_LOCKOUT_LOCK = threading.Lock()
# key -> {"fails": int, "locked_until": float_epoch}
_LOCKOUT_STATE: dict = {}
# After this many failures the key is locked; the lock window grows with each
# additional failure (exponential backoff), capped at _LOCKOUT_MAX_SECONDS.
_LOCKOUT_THRESHOLD = 5
_LOCKOUT_BASE_SECONDS = 30
_LOCKOUT_MAX_SECONDS = 3600  # 1 hour cap

# Global ceiling: this many failures across ALL keys within the window pauses
# every login for a while (legitimate users rarely fail more than a few times),
# so spreading guesses over many IPs gains little. Repeated triggers double the
# pause up to the cap; a quiet period resets it. A restart also clears it.
_GLOBAL_FAIL_THRESHOLD = 20
_GLOBAL_FAIL_WINDOW_SECONDS = 300
_GLOBAL_LOCK_BASE_SECONDS = 60
_GLOBAL_LOCK_MAX_SECONDS = 900
_GLOBAL_STATE: dict = {"fails": deque(), "locked_until": 0.0, "level": 0, "last_trigger": 0.0}

_GLOBAL_KEY = "__global__"


def _header(headers: Optional[dict], name: str) -> Optional[str]:
    """Case-insensitive header lookup."""
    for key, value in (headers or {}).items():
        if key.lower() == name.lower():
            return value
    return None


def _normalize_ip(value: Optional[str]) -> Optional[str]:
    """Canonical IP for a header hop or peer address ('[v6]:port' and 'v4:port'
    accepted), or None when it is not an IP address."""
    if not value:
        return None
    candidate = value.strip()
    if candidate.startswith('['):
        candidate = candidate[1:].split(']', 1)[0]
    elif candidate.count(':') == 1:
        candidate = candidate.split(':', 1)[0]
    try:
        return str(ipaddress.ip_address(candidate))
    except ValueError:
        return None


def _derive_client_ip(headers: Optional[dict], peer_ip: Optional[str],
                      trusted_proxies: int) -> Optional[str]:
    """Client IP for the login lockout, trusting only our own proxies' hops.

    Each proxy APPENDS the address it received the request from to
    X-Forwarded-For, so every entry left of the hops our proxies added is
    client-supplied (a client can send any X-Forwarded-For it likes). With N
    trusted proxies the client is therefore the N-th entry from the right: the
    right-most hop that is not one of our own proxies. With a single proxy,
    X-Real-IP (which nginx/NPM overwrite with the TCP peer) is used when there
    is no usable X-Forwarded-For. With no proxy (N=0) the headers are ignored and
    the TCP peer is used. Returns None when no address can be determined.
    """
    if trusted_proxies > 0:
        xff = _header(headers, 'X-Forwarded-For')
        if xff:
            hops = [hop.strip() for hop in xff.split(',') if hop.strip()]
            if len(hops) >= trusted_proxies:
                ip = _normalize_ip(hops[-trusted_proxies])
                if ip:
                    return ip
        if trusted_proxies == 1:
            ip = _normalize_ip(_header(headers, 'X-Real-IP'))
            if ip:
                return ip
    # No proxy, or no forwarding headers: the (unspoofable) TCP peer. Behind a
    # proxy that did not forward the client, this is the proxy's own address.
    return _normalize_ip(peer_ip)


def _request_meta() -> Tuple[dict, Optional[str]]:
    """(headers, peer_ip) of the current session's websocket request.

    Uses the internal accessors available in this Streamlit version (1.31 has no
    st.context); on API drift either part degrades to empty/None.
    """
    headers: dict = {}
    peer_ip: Optional[str] = None
    try:
        from streamlit.web.server.websocket_headers import _get_websocket_headers
        headers = _get_websocket_headers() or {}
    except Exception:
        pass
    try:
        from streamlit import runtime
        from streamlit.runtime.scriptrunner import get_script_run_ctx
        ctx = get_script_run_ctx()
        client = runtime.get_instance().get_client(ctx.session_id) if ctx else None
        # Streamlit's HTTPServer runs without xheaders, so this is the TCP peer.
        peer_ip = getattr(getattr(client, 'request', None), 'remote_ip', None)
    except Exception:
        pass
    return headers, peer_ip


def _trusted_proxy_count() -> int:
    try:
        return max(0, int(getattr(config, 'TRUSTED_PROXY_COUNT', 1)))
    except (TypeError, ValueError):
        return 1


def _client_key() -> str:
    """Client identifier for rate-limiting: the derived client IP, else a single
    global bucket so the limiter still applies (just less granularly)."""
    headers, peer_ip = _request_meta()
    return _derive_client_ip(headers, peer_ip, _trusted_proxy_count()) or _GLOBAL_KEY


def _lockout_remaining(key: str) -> float:
    """Seconds remaining on a key's lockout, or 0 if not locked."""
    with _LOCKOUT_LOCK:
        rec = _LOCKOUT_STATE.get(key)
        if not rec:
            return 0.0
        remaining = rec.get("locked_until", 0) - time.time()
        return remaining if remaining > 0 else 0.0


def _global_lockout_remaining() -> float:
    """Seconds remaining on the global (all clients) lockout, or 0."""
    with _LOCKOUT_LOCK:
        remaining = _GLOBAL_STATE["locked_until"] - time.time()
        return remaining if remaining > 0 else 0.0


def _record_global_failure_locked(now: float) -> None:
    """Count a failure toward the global ceiling. Caller holds _LOCKOUT_LOCK."""
    fails = _GLOBAL_STATE["fails"]
    fails.append(now)
    while fails and fails[0] <= now - _GLOBAL_FAIL_WINDOW_SECONDS:
        fails.popleft()
    if len(fails) < _GLOBAL_FAIL_THRESHOLD:
        return
    if now - _GLOBAL_STATE["last_trigger"] > _GLOBAL_LOCK_MAX_SECONDS + _GLOBAL_FAIL_WINDOW_SECONDS:
        _GLOBAL_STATE["level"] = 0  # quiet since the last trigger: start over
    window = min(_GLOBAL_LOCK_BASE_SECONDS * (2 ** _GLOBAL_STATE["level"]),
                 _GLOBAL_LOCK_MAX_SECONDS)
    _GLOBAL_STATE["level"] += 1
    _GLOBAL_STATE["locked_until"] = now + window
    _GLOBAL_STATE["last_trigger"] = now
    fails.clear()


def _record_failure(key: str) -> float:
    """Record a failed attempt; return seconds the key is locked (0 if under
    threshold). Also counts toward the global ceiling (_global_lockout_remaining)."""
    now = time.time()
    with _LOCKOUT_LOCK:
        _record_global_failure_locked(now)
        rec = _LOCKOUT_STATE.setdefault(key, {"fails": 0, "locked_until": 0.0})
        rec["fails"] += 1
        if rec["fails"] >= _LOCKOUT_THRESHOLD:
            over = rec["fails"] - _LOCKOUT_THRESHOLD
            window = min(_LOCKOUT_BASE_SECONDS * (2 ** over), _LOCKOUT_MAX_SECONDS)
            rec["locked_until"] = now + window
            return window
        return 0.0


def _record_success(key: str) -> None:
    """Clear a key's failure record on successful login."""
    with _LOCKOUT_LOCK:
        _LOCKOUT_STATE.pop(key, None)


# ---------------------------------------------------------------------------
# First-run bootstrap token
# ---------------------------------------------------------------------------
# A fresh pip install has no .env and no DASHBOARD_PASSWORD, so nobody could
# sign in to reach the admin-only setup wizard. In exactly that state a random
# one-time token is generated in server memory, printed to the server console
# (never to the app log or disk), and accepted by the login form as an admin
# login for the first-run wizard only. Once setup writes DASHBOARD_PASSWORD the
# token is retired for the life of the process and bootstrap sessions are
# signed out (require_authentication), so the new password must be used.
_BOOTSTRAP_LOCK = threading.Lock()
_BOOTSTRAP: dict = {"token": None, "retired": False}
BOOTSTRAP_SESSION_KEY = 'auth_bootstrap'
BOOTSTRAP_TOKEN_LABEL = 'HCC ADVISOR FIRST-RUN SETUP TOKEN'


def _bootstrap_active_locked() -> bool:
    """Caller holds _BOOTSTRAP_LOCK."""
    if _BOOTSTRAP["retired"]:
        return False
    if config.DASHBOARD_PASSWORD or not config.is_first_run():
        if _BOOTSTRAP["token"] is not None:
            # Setup finished (or a password appeared): never accept it again.
            _BOOTSTRAP["token"] = None
            _BOOTSTRAP["retired"] = True
        return False
    return True


def bootstrap_active() -> bool:
    """True while first-run setup is pending and no admin password is configured."""
    with _BOOTSTRAP_LOCK:
        return _bootstrap_active_locked()


def ensure_bootstrap_token() -> bool:
    """Issue the first-run token once per process and print it to the console.

    Returns True when bootstrap mode is active (a token is available), False
    otherwise. The token itself is never returned or shown in the UI.
    """
    with _BOOTSTRAP_LOCK:
        if not _bootstrap_active_locked():
            return False
        if _BOOTSTRAP["token"] is None:
            _BOOTSTRAP["token"] = secrets.token_urlsafe(24)
            bar = "=" * 72
            print(f"\n{bar}\n{BOOTSTRAP_TOKEN_LABEL}: {_BOOTSTRAP['token']}\n"
                  "No DASHBOARD_PASSWORD is configured. Enter this one-time token on the\n"
                  "dashboard login page to open the setup wizard. It is held in memory\n"
                  "only and stops working once setup saves DASHBOARD_PASSWORD.\n"
                  f"{bar}\n", file=sys.stderr, flush=True)
        return True


def _check_bootstrap_token(candidate: str) -> bool:
    """Constant-time check of a login attempt against the live bootstrap token."""
    with _BOOTSTRAP_LOCK:
        token = _BOOTSTRAP["token"] if _bootstrap_active_locked() else None
    if not token or not candidate:
        return False
    return hmac.compare_digest(str(candidate).encode('utf-8'), token.encode('utf-8'))


def validate_new_password(password: str) -> Optional[str]:
    """Why `password` can't be used as a new dashboard password, or None if it can."""
    if not password:
        return "Dashboard password is required."
    if len(password) < MIN_PASSWORD_LENGTH:
        return f"Dashboard password must be at least {MIN_PASSWORD_LENGTH} characters."
    if password in _FORBIDDEN_PASSWORDS:
        return "That password is a known default and is not allowed."
    problem = env_value_problem(password)
    if problem:
        return f"Dashboard password {problem}; choose another."
    return None


class AuthManager:
    """Manages authentication and session state"""

    @staticmethod
    def _hash_password(password: str) -> str:
        """Hash password using SHA-256"""
        return hashlib.sha256(password.encode()).hexdigest()

    @staticmethod
    def _resolve_role(password: str) -> Optional[str]:
        """Map a submitted password to a role using constant-time comparison.

        Admin (DASHBOARD_PASSWORD) is always enabled. Operator/viewer roles are
        only active when their password env var is set AND differs from the admin
        password. Returns the highest-privilege role that matches, or None.
        Comparing against every configured password (rather than short-circuiting)
        keeps the check constant-time and avoids leaking which role matched.

        SECURITY: a configured password that is empty or appears in the forbidden
        weak-default denylist is treated as "not configured" for that role, so a
        missing or known-default credential can never grant access. The dashboard
        fronts arbitrary DDL on production Oracle targets, so it must fail closed.
        """
        if not password:
            return None
        matched: Optional[str] = None
        # Order matters only for the (degenerate) case of duplicate passwords:
        # check low->high so the highest match wins.
        candidates = [
            (ROLE_VIEWER, config.VIEWER_PASSWORD),
            (ROLE_OPERATOR, config.OPERATOR_PASSWORD),
            (ROLE_ADMIN, config.DASHBOARD_PASSWORD),
        ]
        for role, configured in candidates:
            # SECURITY: never accept an unset or known-weak/built-in default
            # password, even if it was accidentally configured.
            if not configured or configured in _FORBIDDEN_PASSWORDS:
                continue
            # SECURITY: constant-time comparison to avoid leaking the password via
            # timing; do not short-circuit on the first differing byte. Compare
            # bytes: compare_digest rejects non-ASCII str arguments.
            if hmac.compare_digest(str(password).encode('utf-8'),
                                   str(configured).encode('utf-8')):
                if matched is None or ROLE_LEVELS[role] >= ROLE_LEVELS[matched]:
                    matched = role
        return matched

    @staticmethod
    def initialize_session_state():
        """Initialize session state variables"""
        if 'authenticated' not in st.session_state:
            st.session_state.authenticated = False

        if 'login_attempts' not in st.session_state:
            st.session_state.login_attempts = 0

        if 'last_activity' not in st.session_state:
            st.session_state.last_activity = datetime.now()

        if 'username' not in st.session_state:
            st.session_state.username = None

        if 'role' not in st.session_state:
            st.session_state.role = None

    @staticmethod
    def check_session_timeout() -> bool:
        """Check if session has timed out"""
        if 'last_activity' in st.session_state:
            timeout = timedelta(minutes=config.SESSION_TIMEOUT_MINUTES)
            if datetime.now() - st.session_state.last_activity > timeout:
                AuthManager.logout()
                return True
        return False

    @staticmethod
    def update_activity():
        """Update last activity timestamp"""
        st.session_state.last_activity = datetime.now()

    @staticmethod
    def login(password: str) -> bool:
        """
        Authenticate user with password

        Args:
            password: User password

        Returns:
            bool: True if authentication successful
        """
        # SECURITY (CWE-307): server-side, cross-session lockout keyed by client
        # IP, plus a global ceiling across all clients. Unlike the per-session
        # counter below, neither can be reset by clearing cookies / starting a
        # new Streamlit session or by rotating X-Forwarded-For values.
        global_remaining = _global_lockout_remaining()
        if global_remaining > 0:
            st.error(
                "Too many failed login attempts on this server. Sign-in is paused "
                f"for {int(global_remaining) + 1}s. Try again later."
            )
            return False
        key = _client_key()
        remaining = _lockout_remaining(key)
        if remaining > 0:
            st.error(
                f"Too many failed login attempts. Locked for {int(remaining) + 1}s. "
                "Try again later."
            )
            return False

        if st.session_state.login_attempts >= config.MAX_LOGIN_ATTEMPTS:
            st.error(f"Maximum login attempts ({config.MAX_LOGIN_ATTEMPTS}) exceeded. Please try again later.")
            return False

        # SECURITY: fail closed if no usable dashboard password is configured. An
        # unset or known-weak admin password must never grant access. (Operator/
        # viewer roles, if configured, are still evaluated by _resolve_role, and
        # on a first run the one-time bootstrap token opens the setup wizard.)
        bootstrap = bootstrap_active()
        configured_admin = config.DASHBOARD_PASSWORD or ""
        if (not configured_admin or configured_admin in _FORBIDDEN_PASSWORDS) and not bootstrap:
            if not (config.OPERATOR_PASSWORD or config.VIEWER_PASSWORD):
                st.error(
                    "Dashboard authentication is misconfigured (DASHBOARD_PASSWORD is unset "
                    "or set to a known-weak default). Set a strong DASHBOARD_PASSWORD and restart."
                )
                return False

        # SECURITY: resolve the submitted password to a role using constant-time
        # comparison against every configured (non-weak) credential.
        role = AuthManager._resolve_role(password)
        via_bootstrap = False
        if role is None and bootstrap and _check_bootstrap_token(password):
            # First run only: admin for the setup wizard; signed out once setup
            # saves DASHBOARD_PASSWORD (see require_authentication).
            role, via_bootstrap = ROLE_ADMIN, True
        if role is not None:
            _record_success(key)
            st.session_state.authenticated = True
            st.session_state.role = role
            st.session_state[BOOTSTRAP_SESSION_KEY] = via_bootstrap
            # Username reflects the role so the audit trail records who acted.
            st.session_state.username = role
            st.session_state.login_attempts = 0
            st.session_state.last_activity = datetime.now()
            return True
        else:
            locked_for = max(_record_failure(key), _global_lockout_remaining())
            st.session_state.login_attempts += 1
            if locked_for > 0:
                st.error(
                    f"Too many failed login attempts. Locked for {int(locked_for)}s."
                )
                return False
            remaining_attempts = config.MAX_LOGIN_ATTEMPTS - st.session_state.login_attempts

            if remaining_attempts > 0:
                st.error(f"Invalid password. {remaining_attempts} attempt(s) remaining.")
            else:
                st.error(f"Maximum login attempts exceeded. Please try again later.")

            return False

    @staticmethod
    def logout():
        """Logout user and clear session"""
        st.session_state.authenticated = False
        st.session_state.username = None
        st.session_state.role = None
        st.session_state[BOOTSTRAP_SESSION_KEY] = False
        st.session_state.last_activity = datetime.now()

    @staticmethod
    def is_authenticated() -> bool:
        """Check if user is authenticated"""
        return st.session_state.get('authenticated', False)

    @staticmethod
    def get_role() -> Optional[str]:
        """Return the current session role (viewer/operator/admin), or None."""
        return st.session_state.get('role')

    @staticmethod
    def get_current_user() -> str:
        """Return the acting user/role label for audit trails."""
        return st.session_state.get('username') or 'unknown'

    @staticmethod
    def has_role(required_role: str) -> bool:
        """True if the current role is at least `required_role` in the hierarchy.

        Backwards compatible: a session authenticated before roles existed (role
        is None but authenticated) is treated as admin, matching the prior
        single-password 'everyone is admin' behaviour.
        """
        if not AuthManager.is_authenticated():
            return False
        role = AuthManager.get_role()
        if role is None:
            role = ROLE_ADMIN  # legacy single-password session
        return ROLE_LEVELS.get(role, -1) >= ROLE_LEVELS.get(required_role, 99)

    @staticmethod
    def require_role(required_role: str, message: Optional[str] = None) -> bool:
        """Guard a privileged action/section. Renders an error and returns False
        if the current role is insufficient; returns True otherwise. Callers
        should `if not AuthManager.require_role(ROLE_OPERATOR): return`."""
        if AuthManager.has_role(required_role):
            return True
        st.error(
            message
            or f"Insufficient privileges: this action requires the "
               f"'{required_role}' role (you are '{AuthManager.get_role() or 'admin'}')."
        )
        return False

    @staticmethod
    def role_gate(required_role: str) -> Tuple[bool, Optional[str]]:
        """(allowed, help_text) for a widget that performs a privileged action.

        help_text is None when allowed, otherwise a short note for the widget's
        `help=` or a caption. Disabling is only a UI hint: the click handler must
        still re-check (`if st.button(..., disabled=not allowed) and
        AuthManager.require_role(role):`) so a forced click does nothing.
        """
        allowed = AuthManager.has_role(required_role)
        return allowed, None if allowed else f"Requires the {required_role} role."

    @staticmethod
    def require_authentication():
        """Require authentication to access page"""
        AuthManager.initialize_session_state()

        # Check session timeout
        if AuthManager.check_session_timeout():
            st.warning("Session timed out. Please login again.")

        # A bootstrap-token session is only good for the first-run wizard: once
        # setup has saved DASHBOARD_PASSWORD, sign it out so the new password
        # (not the retired token) is what grants access from here on.
        if (AuthManager.is_authenticated() and st.session_state.get(BOOTSTRAP_SESSION_KEY)
                and not bootstrap_active()):
            AuthManager.logout()
            st.info("Initial setup is complete. Sign in with the new dashboard password.")

        if not AuthManager.is_authenticated():
            AuthManager.show_login_page()
            st.stop()
        else:
            # Update activity timestamp
            AuthManager.update_activity()

    @staticmethod
    def show_login_page():
        """Display login page"""
        st.title(f"{config.APP_ICON} {config.APP_TITLE}")
        st.markdown("---")

        # First run with no admin password: make sure the one-time setup token
        # has been issued (printed to the server console, never shown here).
        bootstrap = ensure_bootstrap_token()

        # Center login form
        col1, col2, col3 = st.columns([1, 2, 1])

        with col2:
            st.subheader("🔐 Login")

            with st.form("login_form"):
                password = st.text_input(
                    "Setup token" if bootstrap else "Password",
                    type="password",
                    placeholder="Enter the setup token" if bootstrap else "Enter your password"
                )

                submit_button = st.form_submit_button("Login", use_container_width=True)

                if submit_button:
                    if password:
                        if AuthManager.login(password):
                            st.success("Login successful!")
                            st.rerun()
                    else:
                        st.error("Please enter a password")

            # Show login attempts
            if st.session_state.login_attempts > 0:
                st.warning(
                    f"Failed login attempts: {st.session_state.login_attempts} / {config.MAX_LOGIN_ATTEMPTS}"
                )

            # SECURITY: never disclose the password (or any default) on the
            # unauthenticated login page. Only show non-sensitive session info.
            if bootstrap:
                st.info(
                    "**First-run setup.** No dashboard password is configured yet. Enter "
                    "the one-time setup token printed in the server console (look for "
                    f"`{BOOTSTRAP_TOKEN_LABEL}`) to open the setup wizard, where you "
                    "choose the admin password."
                )
            else:
                st.info(
                    "The dashboard password is configured by the administrator via the "
                    "`DASHBOARD_PASSWORD` environment variable.\n\n"
                    f"- Session timeout: {config.SESSION_TIMEOUT_MINUTES} minutes"
                )


def render_logout_button():
    """Render logout button in sidebar"""
    with st.sidebar:
        st.markdown("---")
        col1, col2 = st.columns([3, 1])

        with col1:
            _role = st.session_state.get('role')
            _label = st.session_state.username or 'user'
            if _role:
                st.caption(f"👤 {_label} ({_role})")
            else:
                st.caption(f"👤 {_label}")

        with col2:
            if st.button("Logout", use_container_width=True):
                AuthManager.logout()
                st.rerun()
