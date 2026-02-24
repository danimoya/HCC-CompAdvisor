"""
Configuration Management for HCC Compression Advisor Dashboard
Loads environment variables and provides centralized configuration.
Supports multi-location .env discovery for pip-installed deployments.
"""

import os
from pathlib import Path
from typing import Optional, List
from dotenv import load_dotenv


def _get_config_dir() -> Path:
    """Get configuration directory (XDG-compliant)."""
    env = os.getenv('HCC_ADVISOR_CONFIG_DIR')
    if env:
        return Path(env)
    return Path.home() / '.config' / 'hcc-advisor'


def _get_data_dir() -> Path:
    """Get data directory (XDG-compliant)."""
    env = os.getenv('HCC_ADVISOR_DATA_DIR')
    if env:
        return Path(env)
    return Path.home() / '.local' / 'share' / 'hcc-advisor'


def _load_env_multi():
    """Load .env from multiple locations (first found wins)."""
    locations = [
        _get_config_dir() / '.env',       # pip install config dir
        Path(__file__).parent / '.env',    # package directory (dev / Docker)
        Path.cwd() / '.env',              # current working directory
    ]
    for loc in locations:
        if loc.exists():
            load_dotenv(dotenv_path=loc, override=True)
            return loc
    return None


# Load environment on import
_active_env_path = _load_env_multi()


class Config:
    """Configuration class for application settings"""

    # Application Settings
    APP_TITLE: str = os.getenv('APP_TITLE', 'HCC Compression Advisor')
    APP_ICON: str = os.getenv('APP_ICON', '📊')
    SESSION_TIMEOUT_MINUTES: int = int(os.getenv('SESSION_TIMEOUT_MINUTES', '30'))
    MAX_LOGIN_ATTEMPTS: int = int(os.getenv('MAX_LOGIN_ATTEMPTS', '3'))

    # Authentication
    DASHBOARD_PASSWORD: str = os.getenv('DASHBOARD_PASSWORD', 'admin123')

    # Database Configuration
    DB_HOST: str = os.getenv('DB_HOST', 'localhost')
    DB_PORT: int = int(os.getenv('DB_PORT', '1521'))
    DB_SERVICE: str = os.getenv('DB_SERVICE', 'XEPDB1')
    DB_USER: str = os.getenv('DB_USER', 'hcc_advisor')
    DB_PASSWORD: str = os.getenv('DB_PASSWORD', '')

    # ORDS REST API Configuration
    ORDS_BASE_URL: str = os.getenv('ORDS_BASE_URL', 'https://localhost:8443/ords/hcc_advisor')
    ORDS_USERNAME: str = os.getenv('ORDS_USERNAME', 'hcc_advisor')
    ORDS_PASSWORD: str = os.getenv('ORDS_PASSWORD', '')

    # SSL Configuration
    SSL_ENABLED: bool = os.getenv('SSL_ENABLED', 'true').lower() == 'true'
    SSL_CERT_FILE: str = os.getenv('SSL_CERT_FILE', 'ssl/cert.pem')
    SSL_KEY_FILE: str = os.getenv('SSL_KEY_FILE', 'ssl/key.pem')

    # Logging
    LOG_LEVEL: str = os.getenv('LOG_LEVEL', 'INFO')
    LOG_FILE: str = os.getenv('LOG_FILE', 'logs/app.log')

    # Page Configuration
    PAGE_TITLE: str = f"{APP_ICON} {APP_TITLE}"
    LAYOUT: str = "wide"
    INITIAL_SIDEBAR_STATE: str = "expanded"

    # Central Database Configuration (stores analysis results from all targets)
    # Falls back to DB_* vars for backward compatibility with single-DB deployments
    CENTRAL_DB_HOST: str = os.getenv('CENTRAL_DB_HOST', os.getenv('DB_HOST', 'localhost'))
    CENTRAL_DB_PORT: int = int(os.getenv('CENTRAL_DB_PORT', os.getenv('DB_PORT', '1521')))
    CENTRAL_DB_SERVICE: str = os.getenv('CENTRAL_DB_SERVICE', os.getenv('DB_SERVICE', 'FREEPDB1'))
    CENTRAL_DB_USER: str = os.getenv('CENTRAL_DB_USER', os.getenv('DB_USER', 'COMPRESSION_MGR'))
    CENTRAL_DB_PASSWORD: str = os.getenv('CENTRAL_DB_PASSWORD', os.getenv('DB_PASSWORD', ''))

    # Encryption key for target database password storage
    ENCRYPTION_KEY: str = os.getenv('ENCRYPTION_KEY', '')

    # Database Connection Pool (legacy, for backward compatibility)
    POOL_MIN: int = 2
    POOL_MAX: int = 10
    POOL_INCREMENT: int = 1

    # Central Database Connection Pool
    CENTRAL_POOL_MIN: int = 2
    CENTRAL_POOL_MAX: int = 10

    # Target Database Connection Pool (per-target defaults)
    TARGET_POOL_MIN: int = 1
    TARGET_POOL_MAX: int = 5

    # API Timeout
    API_TIMEOUT: int = 30  # seconds

    # Compression Strategies (Oracle 23c Free + HCC for Exadata)
    COMPRESSION_STRATEGIES: list = [
        'BASIC',
        'OLTP',
        'ADV_LOW',
        'ADV_HIGH',
        'QUERY LOW',
        'QUERY HIGH',
        'ARCHIVE LOW',
        'ARCHIVE HIGH'
    ]

    # Chart Colors
    CHART_COLORS: dict = {
        'primary': '#1f77b4',
        'success': '#2ca02c',
        'warning': '#ff7f0e',
        'danger': '#d62728',
        'info': '#17becf',
        'secondary': '#7f7f7f'
    }

    @classmethod
    def get_db_connection_string(cls) -> str:
        """Generate Oracle database connection string (legacy)"""
        return f"{cls.DB_USER}/{cls.DB_PASSWORD}@{cls.DB_HOST}:{cls.DB_PORT}/{cls.DB_SERVICE}"

    @classmethod
    def get_central_db_dsn(cls) -> str:
        """Generate central database DSN string"""
        return f"{cls.CENTRAL_DB_HOST}:{cls.CENTRAL_DB_PORT}/{cls.CENTRAL_DB_SERVICE}"

    @classmethod
    def get_ssl_context(cls) -> Optional[tuple]:
        """Get SSL context for HTTPS"""
        if cls.SSL_ENABLED:
            cert_path = Path(__file__).parent / cls.SSL_CERT_FILE
            key_path = Path(__file__).parent / cls.SSL_KEY_FILE

            if cert_path.exists() and key_path.exists():
                return (str(cert_path), str(key_path))
        return None

    @classmethod
    def validate_config(cls) -> list:
        """Validate configuration and return list of errors"""
        errors = []

        if not cls.CENTRAL_DB_PASSWORD:
            errors.append("CENTRAL_DB_PASSWORD (or DB_PASSWORD) not set")

        if cls.SSL_ENABLED:
            cert_path = Path(__file__).parent / cls.SSL_CERT_FILE
            key_path = Path(__file__).parent / cls.SSL_KEY_FILE

            if not cert_path.exists():
                errors.append(f"SSL certificate not found: {cert_path}")
            if not key_path.exists():
                errors.append(f"SSL key not found: {key_path}")

        return errors

    # ----- Deployment / Setup helpers -----

    @classmethod
    def is_first_run(cls) -> bool:
        """Check if this is a first-run (no .env and no CENTRAL_DB_PASSWORD env var)."""
        return _active_env_path is None and not os.getenv('CENTRAL_DB_PASSWORD')

    @classmethod
    def is_schema_deployed(cls) -> bool:
        """Check if the central schema is deployed and has correct structure."""
        try:
            import oracledb
            dsn = cls.get_central_db_dsn()
            conn = oracledb.connect(user=cls.CENTRAL_DB_USER, password=cls.CENTRAL_DB_PASSWORD, dsn=dsn)
            cur = conn.cursor()
            # Verify table exists AND has the DB_HOST column (renamed from HOST in 2.0.0)
            cur.execute("""
                SELECT COUNT(*) FROM user_tab_columns
                WHERE table_name = 'T_TARGET_DATABASES' AND column_name = 'DB_HOST'
            """)
            count = cur.fetchone()[0]
            cur.close()
            conn.close()
            return count > 0
        except Exception:
            return False

    @classmethod
    def get_schema_version(cls) -> Optional[str]:
        """Read schema version from T_SCHEMA_METADATA (returns None if not found)."""
        try:
            import oracledb
            dsn = cls.get_central_db_dsn()
            conn = oracledb.connect(user=cls.CENTRAL_DB_USER, password=cls.CENTRAL_DB_PASSWORD, dsn=dsn)
            cur = conn.cursor()
            cur.execute("SELECT value FROM t_schema_metadata WHERE key = 'schema_version'")
            row = cur.fetchone()
            cur.close()
            conn.close()
            return row[0] if row else None
        except Exception:
            return None

    @classmethod
    def write_env_file(cls, settings: dict) -> Path:
        """
        Write settings to .env file in the config directory. Reloads config after writing.

        Args:
            settings: dict of KEY=VALUE pairs to write

        Returns:
            Path to the written .env file
        """
        config_dir = _get_config_dir()
        config_dir.mkdir(parents=True, exist_ok=True)
        env_file = config_dir / '.env'

        lines = [f"{k}={v}" for k, v in settings.items()]
        env_file.write_text('\n'.join(lines) + '\n')

        cls._reload_from_env()
        return env_file

    @classmethod
    def _reload_from_env(cls):
        """Re-read all class attributes from environment after .env change."""
        global _active_env_path
        _active_env_path = _load_env_multi()

        cls.DASHBOARD_PASSWORD = os.getenv('DASHBOARD_PASSWORD', 'admin123')
        cls.CENTRAL_DB_HOST = os.getenv('CENTRAL_DB_HOST', os.getenv('DB_HOST', 'localhost'))
        cls.CENTRAL_DB_PORT = int(os.getenv('CENTRAL_DB_PORT', os.getenv('DB_PORT', '1521')))
        cls.CENTRAL_DB_SERVICE = os.getenv('CENTRAL_DB_SERVICE', os.getenv('DB_SERVICE', 'FREEPDB1'))
        cls.CENTRAL_DB_USER = os.getenv('CENTRAL_DB_USER', os.getenv('DB_USER', 'COMPRESSION_MGR'))
        cls.CENTRAL_DB_PASSWORD = os.getenv('CENTRAL_DB_PASSWORD', os.getenv('DB_PASSWORD', ''))
        cls.ENCRYPTION_KEY = os.getenv('ENCRYPTION_KEY', '')

    @classmethod
    def get_config_dir(cls) -> Path:
        """Return the config directory path."""
        return _get_config_dir()

    @classmethod
    def get_data_dir(cls) -> Path:
        """Return the data directory path."""
        return _get_data_dir()


# Export singleton instance
config = Config()
