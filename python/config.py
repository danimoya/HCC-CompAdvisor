"""
Configuration Management for HCC Compression Advisor Dashboard
Loads environment variables and provides centralized configuration
"""

import os
from pathlib import Path
from typing import Optional
from dotenv import load_dotenv

# Load environment variables from .env file
env_path = Path(__file__).parent / '.env'
load_dotenv(dotenv_path=env_path)


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

    # Database Connection Pool
    POOL_MIN: int = 2
    POOL_MAX: int = 10
    POOL_INCREMENT: int = 1

    # API Timeout
    API_TIMEOUT: int = 30  # seconds

    # Compression Strategies
    COMPRESSION_STRATEGIES: list = [
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
        """Generate Oracle database connection string"""
        return f"{cls.DB_USER}/{cls.DB_PASSWORD}@{cls.DB_HOST}:{cls.DB_PORT}/{cls.DB_SERVICE}"

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

        if not cls.DB_PASSWORD:
            errors.append("DB_PASSWORD not set")

        if not cls.ORDS_PASSWORD:
            errors.append("ORDS_PASSWORD not set")

        if cls.SSL_ENABLED:
            cert_path = Path(__file__).parent / cls.SSL_CERT_FILE
            key_path = Path(__file__).parent / cls.SSL_KEY_FILE

            if not cert_path.exists():
                errors.append(f"SSL certificate not found: {cert_path}")
            if not key_path.exists():
                errors.append(f"SSL key not found: {key_path}")

        return errors


# Export singleton instance
config = Config()
