"""
Authentication Module for HCC Compression Advisor Dashboard
Handles user authentication and session management
"""

import streamlit as st
from datetime import datetime, timedelta
from typing import Optional
import hashlib
from config import config


class AuthManager:
    """Manages authentication and session state"""

    @staticmethod
    def _hash_password(password: str) -> str:
        """Hash password using SHA-256"""
        return hashlib.sha256(password.encode()).hexdigest()

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
        if st.session_state.login_attempts >= config.MAX_LOGIN_ATTEMPTS:
            st.error(f"Maximum login attempts ({config.MAX_LOGIN_ATTEMPTS}) exceeded. Please try again later.")
            return False

        if password == config.DASHBOARD_PASSWORD:
            st.session_state.authenticated = True
            st.session_state.username = "admin"
            st.session_state.login_attempts = 0
            st.session_state.last_activity = datetime.now()
            return True
        else:
            st.session_state.login_attempts += 1
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
        st.session_state.last_activity = datetime.now()

    @staticmethod
    def is_authenticated() -> bool:
        """Check if user is authenticated"""
        return st.session_state.get('authenticated', False)

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

            st.info("""
            **Default Configuration:**
            - Password is set in `.env` file
            - Default: `admin123` (change immediately!)
            - Session timeout: {0} minutes
            """.format(config.SESSION_TIMEOUT_MINUTES))


def render_logout_button():
    """Render logout button in sidebar"""
    with st.sidebar:
        st.markdown("---")
        col1, col2 = st.columns([3, 1])

        with col1:
            st.caption(f"👤 {st.session_state.username}")

        with col2:
            if st.button("Logout", use_container_width=True):
                AuthManager.logout()
                st.rerun()
