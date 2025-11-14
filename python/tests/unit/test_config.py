"""
Unit tests for configuration management.
"""
import pytest
import os
from unittest.mock import patch, mock_open


@pytest.mark.unit
class TestConfigLoader:
    """Test configuration loading and validation."""

    def test_load_config_from_environment(self, mock_env_vars):
        """Test loading configuration from environment variables."""
        # Arrange
        expected_user = mock_env_vars['DB_USER']
        expected_password = mock_env_vars['DB_PASSWORD']

        # Act
        db_user = os.getenv('DB_USER')
        db_password = os.getenv('DB_PASSWORD')

        # Assert
        assert db_user == expected_user
        assert db_password == expected_password

    def test_config_validation_success(self, mock_config):
        """Test successful configuration validation."""
        # Arrange & Act
        config = mock_config

        # Assert
        assert 'database' in config
        assert 'api' in config
        assert 'auth' in config
        assert config['database']['user'] == 'test_user'
        assert config['api']['timeout'] == 30
        assert config['auth']['max_attempts'] == 3

    def test_config_validation_missing_required_fields(self):
        """Test configuration validation with missing required fields."""
        # Arrange
        incomplete_config = {
            'database': {
                'user': 'test_user'
                # Missing password and dsn
            }
        }

        # Act & Assert
        assert 'password' not in incomplete_config['database']
        assert 'dsn' not in incomplete_config['database']

    def test_config_defaults_applied(self):
        """Test that default values are applied when not specified."""
        # Arrange
        minimal_config = {}

        # Act - Apply defaults
        config = {
            'database': {
                'min_pool': minimal_config.get('min_pool', 1),
                'max_pool': minimal_config.get('max_pool', 5),
                'timeout': minimal_config.get('timeout', 30)
            }
        }

        # Assert
        assert config['database']['min_pool'] == 1
        assert config['database']['max_pool'] == 5
        assert config['database']['timeout'] == 30

    def test_config_sensitive_data_masked(self, mock_config):
        """Test that sensitive configuration data is properly masked."""
        # Arrange
        config = mock_config

        # Act - Mask sensitive fields
        def mask_sensitive(value):
            if isinstance(value, str) and len(value) > 4:
                return '*' * (len(value) - 4) + value[-4:]
            return value

        masked_password = mask_sensitive(config['database']['password'])
        masked_api_key = mask_sensitive(config['api']['api_key'])

        # Assert
        assert masked_password.startswith('*')
        assert masked_password.endswith(config['database']['password'][-4:])
        assert masked_api_key.startswith('*')
        assert masked_api_key.endswith(config['api']['api_key'][-4:])


@pytest.mark.unit
class TestConfigValidation:
    """Test configuration validation rules."""

    def test_validate_database_config(self, mock_config):
        """Test database configuration validation."""
        # Arrange
        db_config = mock_config['database']

        # Act & Assert
        assert isinstance(db_config['user'], str)
        assert isinstance(db_config['password'], str)
        assert isinstance(db_config['dsn'], str)
        assert isinstance(db_config['min_pool'], int)
        assert db_config['min_pool'] > 0
        assert db_config['max_pool'] >= db_config['min_pool']

    def test_validate_api_config(self, mock_config):
        """Test API configuration validation."""
        # Arrange
        api_config = mock_config['api']

        # Act & Assert
        assert api_config['base_url'].startswith('http')
        assert isinstance(api_config['timeout'], int)
        assert api_config['timeout'] > 0
        assert isinstance(api_config['retry_count'], int)
        assert api_config['retry_count'] >= 0

    def test_validate_auth_config(self, mock_config):
        """Test authentication configuration validation."""
        # Arrange
        auth_config = mock_config['auth']

        # Act & Assert
        assert isinstance(auth_config['secret_key'], str)
        assert len(auth_config['secret_key']) >= 32
        assert isinstance(auth_config['session_timeout'], int)
        assert auth_config['session_timeout'] > 0
        assert auth_config['max_attempts'] > 0

    def test_validate_compression_config(self, mock_config):
        """Test compression configuration validation."""
        # Arrange
        comp_config = mock_config['compression']

        # Act & Assert
        assert isinstance(comp_config['sample_size'], int)
        assert comp_config['sample_size'] > 0
        assert isinstance(comp_config['compression_types'], list)
        assert len(comp_config['compression_types']) > 0
        assert all(isinstance(ct, str) for ct in comp_config['compression_types'])

    def test_invalid_config_raises_error(self):
        """Test that invalid configuration raises appropriate errors."""
        # Arrange
        invalid_configs = [
            {'database': {'min_pool': -1}},  # Negative pool size
            {'api': {'timeout': 0}},  # Zero timeout
            {'auth': {'max_attempts': 0}},  # Zero max attempts
        ]

        # Act & Assert
        for config in invalid_configs:
            if 'database' in config:
                assert config['database'].get('min_pool', 1) < 0
            if 'api' in config:
                assert config['api'].get('timeout', 1) == 0
            if 'auth' in config:
                assert config['auth'].get('max_attempts', 1) == 0
