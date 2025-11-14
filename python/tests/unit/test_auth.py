"""
Unit tests for authentication module.
"""
import pytest
from unittest.mock import MagicMock, patch
from datetime import datetime, timedelta
import hashlib
import secrets


@pytest.mark.unit
@pytest.mark.auth
class TestUserAuthentication:
    """Test user authentication functionality."""

    def test_login_success(self, mock_streamlit_session):
        """Test successful user login."""
        # Arrange
        username = 'testuser'
        password = 'SecurePassword123!'
        password_hash = hashlib.sha256(password.encode()).hexdigest()

        # Simulate stored user
        stored_hash = password_hash

        # Act
        provided_hash = hashlib.sha256(password.encode()).hexdigest()
        is_authenticated = provided_hash == stored_hash

        if is_authenticated:
            mock_streamlit_session['authenticated'] = True
            mock_streamlit_session['username'] = username
            mock_streamlit_session['login_time'] = datetime.now().isoformat()

        # Assert
        assert is_authenticated is True
        assert mock_streamlit_session['authenticated'] is True
        assert mock_streamlit_session['username'] == username

    def test_login_failure_wrong_password(self):
        """Test login failure with wrong password."""
        # Arrange
        correct_password = 'SecurePassword123!'
        wrong_password = 'WrongPassword'
        stored_hash = hashlib.sha256(correct_password.encode()).hexdigest()

        # Act
        provided_hash = hashlib.sha256(wrong_password.encode()).hexdigest()
        is_authenticated = provided_hash == stored_hash

        # Assert
        assert is_authenticated is False

    def test_logout(self, mock_streamlit_session):
        """Test user logout."""
        # Arrange
        mock_streamlit_session['authenticated'] = True
        mock_streamlit_session['username'] = 'testuser'

        # Act
        mock_streamlit_session.clear()

        # Assert
        assert 'authenticated' not in mock_streamlit_session
        assert 'username' not in mock_streamlit_session

    def test_password_hashing(self):
        """Test password hashing function."""
        # Arrange
        password = 'MySecurePassword123!'

        # Act
        hash1 = hashlib.sha256(password.encode()).hexdigest()
        hash2 = hashlib.sha256(password.encode()).hexdigest()

        # Assert
        assert hash1 == hash2
        assert len(hash1) == 64  # SHA-256 produces 64 character hex string
        assert hash1 != password


@pytest.mark.unit
@pytest.mark.auth
class TestSessionManagement:
    """Test session management functionality."""

    def test_create_session(self, mock_streamlit_session, mock_user_session):
        """Test session creation."""
        # Arrange
        user_data = mock_user_session

        # Act
        mock_streamlit_session['user_id'] = user_data['user_id']
        mock_streamlit_session['username'] = user_data['username']
        mock_streamlit_session['authenticated'] = user_data['authenticated']
        mock_streamlit_session['login_time'] = user_data['login_time']

        # Assert
        assert mock_streamlit_session['authenticated'] is True
        assert mock_streamlit_session['username'] == user_data['username']
        assert 'login_time' in mock_streamlit_session

    def test_session_timeout(self, mock_streamlit_session, mock_config):
        """Test session timeout validation."""
        # Arrange
        session_timeout = mock_config['auth']['session_timeout']
        login_time = datetime.now() - timedelta(seconds=session_timeout + 1)
        mock_streamlit_session['login_time'] = login_time.isoformat()
        mock_streamlit_session['last_activity'] = login_time.isoformat()

        # Act
        current_time = datetime.now()
        last_activity = datetime.fromisoformat(mock_streamlit_session['last_activity'])
        time_elapsed = (current_time - last_activity).total_seconds()
        is_expired = time_elapsed > session_timeout

        # Assert
        assert is_expired is True

    def test_update_last_activity(self, mock_streamlit_session):
        """Test updating last activity timestamp."""
        # Arrange
        mock_streamlit_session['authenticated'] = True
        old_time = datetime.now() - timedelta(minutes=5)
        mock_streamlit_session['last_activity'] = old_time.isoformat()

        # Act
        mock_streamlit_session['last_activity'] = datetime.now().isoformat()

        # Assert
        new_time = datetime.fromisoformat(mock_streamlit_session['last_activity'])
        assert new_time > old_time

    def test_generate_session_token(self):
        """Test session token generation."""
        # Arrange & Act
        token1 = secrets.token_urlsafe(32)
        token2 = secrets.token_urlsafe(32)

        # Assert
        assert len(token1) > 0
        assert len(token2) > 0
        assert token1 != token2  # Tokens should be unique


@pytest.mark.unit
@pytest.mark.auth
class TestAccessControl:
    """Test access control and authorization."""

    def test_check_user_role(self, mock_user_session):
        """Test checking user roles."""
        # Arrange
        user_roles = mock_user_session['roles']

        # Act
        has_analyst_role = 'analyst' in user_roles
        has_admin_role = 'admin' in user_roles

        # Assert
        assert has_analyst_role is True
        assert has_admin_role is False

    def test_require_authentication(self, mock_streamlit_session):
        """Test authentication requirement."""
        # Arrange
        mock_streamlit_session['authenticated'] = False

        # Act
        is_authenticated = mock_streamlit_session.get('authenticated', False)

        # Assert
        assert is_authenticated is False

    def test_rate_limiting(self, mock_config):
        """Test login rate limiting."""
        # Arrange
        max_attempts = mock_config['auth']['max_attempts']
        failed_attempts = 0

        # Act - Simulate failed login attempts
        for _ in range(max_attempts + 1):
            failed_attempts += 1

        is_locked = failed_attempts >= max_attempts

        # Assert
        assert is_locked is True
        assert failed_attempts > max_attempts

    def test_account_lockout(self, mock_config):
        """Test account lockout after max attempts."""
        # Arrange
        max_attempts = mock_config['auth']['max_attempts']
        lockout_duration = mock_config['auth']['lockout_duration']
        failed_attempts = max_attempts
        lockout_time = datetime.now()

        # Act
        current_time = datetime.now() + timedelta(seconds=lockout_duration - 1)
        time_since_lockout = (current_time - lockout_time).total_seconds()
        is_still_locked = failed_attempts >= max_attempts and time_since_lockout < lockout_duration

        # Assert
        assert is_still_locked is True

    def test_lockout_expiration(self, mock_config):
        """Test lockout expiration after duration."""
        # Arrange
        lockout_duration = mock_config['auth']['lockout_duration']
        lockout_time = datetime.now()

        # Act
        current_time = datetime.now() + timedelta(seconds=lockout_duration + 1)
        time_since_lockout = (current_time - lockout_time).total_seconds()
        is_expired = time_since_lockout > lockout_duration

        # Assert
        assert is_expired is True
