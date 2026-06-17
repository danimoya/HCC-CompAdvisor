"""
Authentication Module for HCC Compression Advisor Dashboard
Handles user authentication and session management
"""

import streamlit as st
from datetime import datetime, timedelta
from typing import Optional, List
import hashlib
import hmac
import threading
import time
from hcc_advisor.config import config


# Role hierarchy (ascending privilege). A role grants its own capabilities plus
# all roles below it: admin > operator > viewer.
ROLE_VIEWER = 'viewer'
ROLE_OPERATOR = 'operator'
ROLE_ADMIN = 'admin'
ROLE_LEVELS = {ROLE_VIEWER: 0, ROLE_OPERATOR: 1, ROLE_ADMIN: 2}


# Passwords that must never be accepted, even if accidentally configured.
# (Historical built-in defaults that were shipped in templates/examples.)
_FORBIDDEN_PASSWORDS = frozenset({"admin123", "Dashboard123!", "Dashboard123"})


# ---------------------------------------------------------------------------
# Server-side brute-force lockout (CWE-307)
# ---------------------------------------------------------------------------
# The per-session st.session_state counter is trivially bypassed by starting a
# fresh session (cleared cookie / scripted requests). This module-level store
# lives in the SERVER process, so it persists ACROSS sessions and cannot be reset
# by the client. It is keyed by client IP when the IP is available (read from the
# X-Forwarded-For header set by the TLS reverse proxy), and otherwise falls back
# to a single global bucket so the limiter still applies.
_LOCKOUT_LOCK = threading.Lock()
# key -> {"fails": int, "locked_until": float_epoch}
_LOCKOUT_STATE: dict = {}
# After this many failures the key is locked; the lock window grows with each
# additional failure (exponential backoff), capped at _LOCKOUT_MAX_SECONDS.
_LOCKOUT_THRESHOLD = 5
_LOCKOUT_BASE_SECONDS = 30
_LOCKOUT_MAX_SECONDS = 3600  # 1 hour cap


def _client_key() -> str:
    """Best-effort client identifier for rate-limiting (IP from XFF, else global).

    Uses the internal websocket-headers accessor available in this Streamlit
    version; if it is unavailable (API drift), degrade to a single global bucket
    so the limiter still throttles brute force, just less granularly.
    """
    try:
        from streamlit.web.server.websocket_headers import _get_websocket_headers
        headers = _get_websocket_headers() or {}
        xff = headers.get("X-Forwarded-For") or headers.get("x-forwarded-for")
        if xff:
            # First hop is the original client.
            return xff.split(",")[0].strip()
        real = headers.get("X-Real-Ip") or headers.get("x-real-ip")
        if real:
            return real.strip()
    except Exception:
        pass
    return "__global__"


def _lockout_remaining(key: str) -> float:
    """Seconds remaining on a key's lockout, or 0 if not locked."""
    with _LOCKOUT_LOCK:
        rec = _LOCKOUT_STATE.get(key)
        if not rec:
            return 0.0
        remaining = rec.get("locked_until", 0) - time.time()
        return remaining if remaining > 0 else 0.0


def _record_failure(key: str) -> float:
    """Record a failed attempt; return seconds locked (0 if under threshold)."""
    with _LOCKOUT_LOCK:
        rec = _LOCKOUT_STATE.setdefault(key, {"fails": 0, "locked_until": 0.0})
        rec["fails"] += 1
        if rec["fails"] >= _LOCKOUT_THRESHOLD:
            over = rec["fails"] - _LOCKOUT_THRESHOLD
            window = min(_LOCKOUT_BASE_SECONDS * (2 ** over), _LOCKOUT_MAX_SECONDS)
            rec["locked_until"] = time.time() + window
            return window
        return 0.0


def _record_success(key: str) -> None:
    """Clear a key's failure record on successful login."""
    with _LOCKOUT_LOCK:
        _LOCKOUT_STATE.pop(key, None)


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
            # timing; do not short-circuit on the first differing byte.
            if hmac.compare_digest(str(password), str(configured)):
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
        # IP. Unlike the per-session counter below, this cannot be reset by
        # clearing cookies / starting a new Streamlit session.
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
        # viewer roles, if configured, are still evaluated by _resolve_role.)
        configured_admin = config.DASHBOARD_PASSWORD or ""
        if not configured_admin or configured_admin in _FORBIDDEN_PASSWORDS:
            if not (config.OPERATOR_PASSWORD or config.VIEWER_PASSWORD):
                st.error(
                    "Dashboard authentication is misconfigured (DASHBOARD_PASSWORD is unset "
                    "or set to a known-weak default). Set a strong DASHBOARD_PASSWORD and restart."
                )
                return False

        # SECURITY: resolve the submitted password to a role using constant-time
        # comparison against every configured (non-weak) credential.
        role = AuthManager._resolve_role(password)
        if role is not None:
            _record_success(key)
            st.session_state.authenticated = True
            st.session_state.role = role
            # Username reflects the role so the audit trail records who acted.
            st.session_state.username = role
            st.session_state.login_attempts = 0
            st.session_state.last_activity = datetime.now()
            return True
        else:
            locked_for = _record_failure(key)
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
    def require_authentication():
        """Require authentication to access page"""
        AuthManager.initialize_session_state()

        # Check session timeout
        if AuthManager.check_session_timeout():
            st.warning("Session timed out. Please login again.")

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

        # Center login form
        col1, col2, col3 = st.columns([1, 2, 1])

        with col2:
            st.subheader("🔐 Login")

            with st.form("login_form"):
                password = st.text_input(
                    "Password",
                    type="password",
                    placeholder="Enter your password"
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
