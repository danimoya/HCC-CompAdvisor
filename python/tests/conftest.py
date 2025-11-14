"""
Pytest configuration and shared fixtures for HCC Compression Advisor tests.
"""
import os
import pytest
from unittest.mock import Mock, MagicMock, patch
from datetime import datetime
import oracledb


# ============================================================================
# Configuration Fixtures
# ============================================================================

@pytest.fixture
def mock_config():
    """Mock configuration dictionary."""
    return {
        'database': {
            'user': 'test_user',
            'password': 'test_password',
            'dsn': 'localhost:1521/testdb',
            'min_pool': 1,
            'max_pool': 5,
            'increment': 1,
            'timeout': 30
        },
        'api': {
            'base_url': 'http://localhost:8080',
            'timeout': 30,
            'retry_count': 3,
            'api_key': 'test_api_key'
        },
        'auth': {
            'secret_key': 'test_secret_key',
            'session_timeout': 3600,
            'max_attempts': 3,
            'lockout_duration': 300
        },
        'compression': {
            'sample_size': 1000,
            'analysis_threshold': 10000,
            'compression_types': ['QUERY_LOW', 'QUERY_HIGH', 'ARCHIVE_LOW', 'ARCHIVE_HIGH']
        }
    }


@pytest.fixture
def mock_env_vars(monkeypatch):
    """Set mock environment variables."""
    env_vars = {
        'DB_USER': 'test_user',
        'DB_PASSWORD': 'test_password',
        'DB_DSN': 'localhost:1521/testdb',
        'API_KEY': 'test_api_key',
        'SECRET_KEY': 'test_secret_key'
    }
    for key, value in env_vars.items():
        monkeypatch.setenv(key, value)
    return env_vars


# ============================================================================
# Database Fixtures
# ============================================================================

@pytest.fixture
def mock_oracle_connection():
    """Mock Oracle database connection."""
    mock_conn = MagicMock(spec=oracledb.Connection)
    mock_cursor = MagicMock()
    mock_conn.cursor.return_value = mock_cursor
    mock_conn.commit = MagicMock()
    mock_conn.rollback = MagicMock()
    mock_conn.close = MagicMock()
    return mock_conn


@pytest.fixture
def mock_oracle_cursor():
    """Mock Oracle database cursor."""
    mock_cursor = MagicMock()
    mock_cursor.execute = MagicMock()
    mock_cursor.fetchone = MagicMock()
    mock_cursor.fetchall = MagicMock()
    mock_cursor.fetchmany = MagicMock()
    mock_cursor.close = MagicMock()
    mock_cursor.description = [
        ('TABLE_NAME', oracledb.DB_TYPE_VARCHAR, 128, None, None, None, None),
        ('SIZE_MB', oracledb.DB_TYPE_NUMBER, None, None, None, None, None)
    ]
    return mock_cursor


@pytest.fixture
def mock_connection_pool():
    """Mock Oracle connection pool."""
    mock_pool = MagicMock()
    mock_pool.acquire = MagicMock()
    mock_pool.release = MagicMock()
    mock_pool.close = MagicMock()
    mock_pool.min = 1
    mock_pool.max = 5
    mock_pool.increment = 1
    return mock_pool


@pytest.fixture
def sample_table_data():
    """Sample table data for testing."""
    return [
        ('CUSTOMERS', 1024.5, 5000000, 'HEAP', None),
        ('ORDERS', 2048.75, 10000000, 'HEAP', None),
        ('PRODUCTS', 512.25, 1000000, 'HEAP', None),
        ('INVENTORY', 768.5, 2500000, 'HEAP', None)
    ]


@pytest.fixture
def sample_compression_analysis():
    """Sample compression analysis results."""
    return {
        'table_name': 'CUSTOMERS',
        'current_size_mb': 1024.5,
        'row_count': 5000000,
        'recommendations': [
            {
                'compression_type': 'QUERY_LOW',
                'estimated_size_mb': 512.25,
                'compression_ratio': 2.0,
                'space_savings_mb': 512.25,
                'space_savings_pct': 50.0
            },
            {
                'compression_type': 'QUERY_HIGH',
                'estimated_size_mb': 256.125,
                'compression_ratio': 4.0,
                'space_savings_mb': 768.375,
                'space_savings_pct': 75.0
            }
        ]
    }


# ============================================================================
# API Fixtures
# ============================================================================

@pytest.fixture
def mock_api_response():
    """Mock API response."""
    mock_response = Mock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        'status': 'success',
        'data': {'result': 'test_data'},
        'timestamp': datetime.now().isoformat()
    }
    mock_response.text = '{"status": "success"}'
    mock_response.headers = {'Content-Type': 'application/json'}
    return mock_response


@pytest.fixture
def mock_api_error_response():
    """Mock API error response."""
    mock_response = Mock()
    mock_response.status_code = 500
    mock_response.json.return_value = {
        'status': 'error',
        'error': 'Internal server error',
        'timestamp': datetime.now().isoformat()
    }
    mock_response.text = '{"status": "error"}'
    mock_response.raise_for_status.side_effect = Exception("API Error")
    return mock_response


@pytest.fixture
def mock_requests_session():
    """Mock requests session."""
    mock_session = MagicMock()
    mock_session.get = MagicMock()
    mock_session.post = MagicMock()
    mock_session.put = MagicMock()
    mock_session.delete = MagicMock()
    mock_session.close = MagicMock()
    return mock_session


# ============================================================================
# Authentication Fixtures
# ============================================================================

@pytest.fixture
def mock_user_session():
    """Mock user session data."""
    return {
        'user_id': 'test_user_123',
        'username': 'testuser',
        'email': 'test@example.com',
        'roles': ['analyst', 'viewer'],
        'authenticated': True,
        'login_time': datetime.now().isoformat(),
        'last_activity': datetime.now().isoformat()
    }


@pytest.fixture
def mock_auth_token():
    """Mock authentication token."""
    return 'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.test_token_payload.signature'


@pytest.fixture
def mock_streamlit_session():
    """Mock Streamlit session state."""
    session_state = {}

    class SessionState:
        def __getitem__(self, key):
            return session_state.get(key)

        def __setitem__(self, key, value):
            session_state[key] = value

        def __contains__(self, key):
            return key in session_state

        def get(self, key, default=None):
            return session_state.get(key, default)

        def clear(self):
            session_state.clear()

    return SessionState()


# ============================================================================
# Data Generation Fixtures
# ============================================================================

@pytest.fixture
def generate_test_tables():
    """Generate test table data."""
    def _generate(count=10):
        tables = []
        for i in range(count):
            tables.append({
                'table_name': f'TEST_TABLE_{i}',
                'size_mb': 100.0 * (i + 1),
                'row_count': 10000 * (i + 1),
                'tablespace': 'USERS',
                'compression': None if i % 2 == 0 else 'QUERY_LOW'
            })
        return tables
    return _generate


@pytest.fixture
def generate_compression_metrics():
    """Generate compression metrics."""
    def _generate(compression_type='QUERY_LOW', ratio=2.0):
        return {
            'compression_type': compression_type,
            'compression_ratio': ratio,
            'space_savings_mb': 500.0,
            'space_savings_pct': 50.0,
            'estimated_size_mb': 500.0,
            'analysis_date': datetime.now().isoformat()
        }
    return _generate


# ============================================================================
# Cleanup and Teardown
# ============================================================================

@pytest.fixture(autouse=True)
def reset_environment():
    """Reset environment after each test."""
    yield
    # Cleanup code here if needed


@pytest.fixture
def temp_test_dir(tmp_path):
    """Create temporary directory for test files."""
    test_dir = tmp_path / "test_data"
    test_dir.mkdir()
    return test_dir


# ============================================================================
# Parametrized Test Data
# ============================================================================

@pytest.fixture(params=['QUERY_LOW', 'QUERY_HIGH', 'ARCHIVE_LOW', 'ARCHIVE_HIGH'])
def compression_types(request):
    """Parametrized compression types."""
    return request.param


@pytest.fixture(params=[10, 100, 1000, 10000])
def table_sizes(request):
    """Parametrized table sizes in MB."""
    return request.param


# ============================================================================
# Mock Patches
# ============================================================================

@pytest.fixture
def mock_oracledb_connect():
    """Patch oracledb.connect."""
    with patch('oracledb.connect') as mock_connect:
        yield mock_connect


@pytest.fixture
def mock_oracledb_pool():
    """Patch oracledb.create_pool."""
    with patch('oracledb.create_pool') as mock_pool:
        yield mock_pool


@pytest.fixture
def mock_requests():
    """Patch requests module."""
    with patch('requests.Session') as mock_session:
        yield mock_session
