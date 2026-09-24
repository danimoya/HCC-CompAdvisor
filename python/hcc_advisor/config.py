"""
Configuration Management for HCC Compression Advisor Dashboard
Loads environment variables and provides centralized configuration.
Supports multi-location .env discovery for pip-installed deployments.
"""

import io
import os
import re
import tempfile
from pathlib import Path
from typing import Optional, List
from dotenv import dotenv_values, load_dotenv


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


# ----- .env writing -----

_ENV_KEY_RE = re.compile(r'[A-Za-z_][A-Za-z0-9_]*')


def _encode_env_value(text: str) -> Optional[str]:
    """How to spell `text` in .env so python-dotenv reads it back exactly, or None.

    Values are single-quoted, where python-dotenv unescapes only \\\\ and \\'.
    Its quoted-value regex, however, reads a backslash right before the closing
    quote as an escaped quote (and then runs into the next lines), so a value
    ending in a backslash is written unquoted, which python-dotenv takes
    literally. The chosen spelling is verified with the installed parser (and
    the same ${VAR} expansion load_dotenv applies), followed by another quoted
    line so a spelling that would swallow the next line is caught too.
    """
    if text.endswith('\\'):
        form = text
    else:
        form = "'" + text.replace('\\', '\\\\').replace("'", "\\'") + "'"
    parsed = dotenv_values(stream=io.StringIO(f"V={form}\nW='w'\n"))
    if parsed.get('V') == text and parsed.get('W') == 'w':
        return form
    return None


def env_value_problem(value) -> Optional[str]:
    """Why `value` can't be written to .env and read back exactly, or None."""
    text = '' if value is None else str(value)
    if '\n' in text or '\r' in text:
        return "contains a line break, which .env cannot store"
    if '\x00' in text:
        return "contains a NUL character, which environment variables cannot hold"
    if _encode_env_value(text) is None:
        if '${' in text:
            return "contains '${...}', which python-dotenv would expand when reading .env"
        if text.endswith('\\'):
            return ("ends with a backslash, which .env can only store in a value "
                    "without leading quotes or spaces and without ' #'")
        return "cannot be stored in .env exactly"
    return None


def format_env_line(key: str, value) -> str:
    """`KEY='value'` line for .env (see _encode_env_value). Raises ValueError
    (naming the key, never the value) when either can't be stored exactly."""
    if not isinstance(key, str) or not _ENV_KEY_RE.fullmatch(key):
        raise ValueError(f"Invalid .env key {key!r}: use letters, digits and underscores.")
    text = '' if value is None else str(value)
    problem = env_value_problem(text)
    if problem:
        raise ValueError(f"{key} {problem}. Choose a different value.")
    return f"{key}={_encode_env_value(text)}"


def _write_private_file(path: Path, text: str) -> None:
    """Atomically create or replace `path` with owner-only (0600) permissions.

    The text goes to a temp file in the same directory, created 0600 with
    O_CREAT|O_EXCL (mkstemp) so it is never readable by others whatever the
    umask, then fsynced and renamed over `path` (os.replace): readers see the
    old file or the complete new one, never a partial or world-readable one.
    """
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=f'.{path.name}.', suffix='.tmp')
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as fh:
            if hasattr(os, 'fchmod'):
                os.fchmod(fh.fileno(), 0o600)
            fh.write(text)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


class Config:
    """Configuration class for application settings"""

    # Application Settings
    APP_TITLE: str = os.getenv('APP_TITLE', 'HCC Compression Advisor')
    APP_ICON: str = os.getenv('APP_ICON', '📊')
    SESSION_TIMEOUT_MINUTES: int = int(os.getenv('SESSION_TIMEOUT_MINUTES', '30'))
    MAX_LOGIN_ATTEMPTS: int = int(os.getenv('MAX_LOGIN_ATTEMPTS', '3'))

    # Authentication
    # SECURITY: no built-in default password. If DASHBOARD_PASSWORD is unset the
    # value is empty and AuthManager.login() fails closed (empty password is
    # rejected), forcing the operator to set an explicit secret.
    #
    # DASHBOARD_PASSWORD is the ADMIN role password (full access). The optional
    # OPERATOR_PASSWORD / VIEWER_PASSWORD enable role separation without a full
    # user store: an operator may run analysis/compression but not manage
    # credentials or patch SQL; a viewer is read-only. Roles are only active when
    # the corresponding password env var is set, so existing single-password
    # deployments keep working unchanged (admin-only).
    #
    # On a first run (no .env, no DASHBOARD_PASSWORD) a one-time token printed to
    # the server console opens the setup wizard instead (auth.ensure_bootstrap_token).
    DASHBOARD_PASSWORD: str = os.getenv('DASHBOARD_PASSWORD', '')
    OPERATOR_PASSWORD: str = os.getenv('OPERATOR_PASSWORD', '')
    VIEWER_PASSWORD: str = os.getenv('VIEWER_PASSWORD', '')

    # Reverse proxies in front of Streamlit whose X-Forwarded-For hops are
    # trusted when keying the login lockout by client IP. The docker deployment
    # has exactly one (Nginx Proxy Manager). Set 0 when browsers reach Streamlit
    # directly: forwarding headers are then client-supplied and the TCP peer
    # address is used instead.
    TRUSTED_PROXY_COUNT: int = int(os.getenv('TRUSTED_PROXY_COUNT', '1'))

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
    # TLS verification for ORDS calls. Defaults to True (secure). For internal
    # self-signed CAs, set ORDS_CA_BUNDLE to a CA bundle path instead of disabling
    # verification. Setting ORDS_VERIFY_SSL=false is an explicit, logged opt-out.
    ORDS_VERIFY_SSL: bool = os.getenv('ORDS_VERIFY_SSL', 'true').lower() == 'true'
    ORDS_CA_BUNDLE: str = os.getenv('ORDS_CA_BUNDLE', '')

    # SSL Configuration
    SSL_ENABLED: bool = os.getenv('SSL_ENABLED', 'true').lower() == 'true'
    SSL_CERT_FILE: str = os.getenv('SSL_CERT_FILE', 'ssl/cert.pem')
    SSL_KEY_FILE: str = os.getenv('SSL_KEY_FILE', 'ssl/key.pem')

    # Logging
    LOG_LEVEL: str = os.getenv('LOG_LEVEL', 'INFO')
    LOG_FILE: str = os.getenv('LOG_FILE', 'logs/app.log')

    # SSRF guard (outbound HTTP from admin-configurable Ollama/webhook URLs).
    # Comma-separated host allowlists. Webhooks must be https and match
    # WEBHOOK_HOST_ALLOWLIST (default: Slack/Teams). Ollama may use http/https
    # but its host must match OLLAMA_HOST_ALLOWLIST. Loopback/link-local/private
    # ranges are blocked unless SSRF_ALLOW_PRIVATE=true (set this only when
    # Ollama legitimately runs on localhost/an internal host).
    WEBHOOK_HOST_ALLOWLIST: str = os.getenv(
        'WEBHOOK_HOST_ALLOWLIST', 'hooks.slack.com,*.webhook.office.com')
    OLLAMA_HOST_ALLOWLIST: str = os.getenv('OLLAMA_HOST_ALLOWLIST', '')
    SSRF_ALLOW_PRIVATE: bool = os.getenv('SSRF_ALLOW_PRIVATE', 'false').lower() == 'true'

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
    TARGET_POOL_MAX: int = int(os.getenv('TARGET_POOL_MAX', '5'))
    # Connections of each target pool kept free for UI reads while a synchronous
    # batch runs: batch_execute holds one connection per concurrent table for
    # the whole MOVE, so its concurrency is capped at TARGET_POOL_MAX minus this.
    # 2 = one for the page that started the batch (other tabs / reruns of the
    # same session: monitor, schema lists) plus one for another session or the
    # Scheduler page's drain/reconcile on the same target.
    TARGET_POOL_UI_HEADROOM: int = 2

    # API Timeout
    API_TIMEOUT: int = 30  # seconds

    # TCP connect timeout (seconds) for the direct central-DB connections of the
    # startup schema check and the deployment page, so an unreachable host
    # fails fast instead of blocking page loads for the driver's 60s default.
    # Also used for the connections of the central connection pool.
    CENTRAL_CONNECT_TIMEOUT: int = int(os.getenv('CENTRAL_CONNECT_TIMEOUT', '10'))
    # TCP connect timeout (seconds) for target-database pool connections and the
    # direct connection test. 0 = driver default (60s).
    TARGET_CONNECT_TIMEOUT: int = int(os.getenv('TARGET_CONNECT_TIMEOUT', '10'))
    # Seconds a caller waits for a free connection of an exhausted pool (central
    # or target) before failing with DPY-4005 instead of blocking forever.
    # 0 = wait indefinitely (the driver's POOL_GETMODE_WAIT).
    POOL_WAIT_TIMEOUT: int = int(os.getenv('POOL_WAIT_TIMEOUT', '30'))
    # Per-round-trip limit (seconds) for interactive reads: the SELECT helpers
    # (CentralConnector/TargetConnector.execute_query). DDL, PL/SQL, DML,
    # DBMS_SCHEDULER calls and the analysis / compression paths run without it
    # (see utils/db_timeouts.py). 0 = no limit.
    DB_CALL_TIMEOUT: int = int(os.getenv('DB_CALL_TIMEOUT', '120'))

    # Compression Strategies (Oracle 23c Free + HCC for Exadata)
    COMPRESSION_STRATEGIES: list = [
        'BASIC',
        'OLTP',
        'QUERY LOW',
        'QUERY HIGH',
        'ARCHIVE LOW',
        'ARCHIVE HIGH',
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

        # Fail fast on a missing encryption key: without it, target-DB
        # credentials would otherwise be stored in cleartext. Validate that the
        # key is a usable Fernet key rather than just non-empty.
        if not cls.ENCRYPTION_KEY:
            errors.append(
                "ENCRYPTION_KEY not set — target-database passwords cannot be "
                "stored securely. Generate a Fernet key (Setup page) and set "
                "ENCRYPTION_KEY before registering target databases."
            )
        else:
            try:
                from cryptography.fernet import Fernet
                key = cls.ENCRYPTION_KEY
                Fernet(key.encode() if isinstance(key, str) else key)
            except ImportError:
                errors.append(
                    "ENCRYPTION_KEY is set but the 'cryptography' library is not "
                    "installed — target credentials cannot be encrypted."
                )
            except Exception:
                errors.append(
                    "ENCRYPTION_KEY is not a valid Fernet key — generate one with "
                    "Fernet.generate_key() (Setup page)."
                )

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
    def connect_central(cls):
        """Open a direct (unpooled) central-DB connection with a connect timeout."""
        import oracledb
        return oracledb.connect(
            user=cls.CENTRAL_DB_USER, password=cls.CENTRAL_DB_PASSWORD,
            dsn=cls.get_central_db_dsn(),
            tcp_connect_timeout=cls.CENTRAL_CONNECT_TIMEOUT,
        )

    @classmethod
    def get_schema_info(cls) -> dict:
        """
        Inspect the central schema over a single connection.

        Returns {'deployed': bool, 'version': Optional[str]}. 'deployed' means
        T_TARGET_DATABASES exists with the DB_HOST column (renamed from HOST in
        2.0.0); 'version' is T_SCHEMA_METADATA.schema_version (None if absent).
        Never raises: an unreachable DB reads as not deployed.
        """
        from hcc_advisor.utils.schema_version import DEPLOYED_CHECK_SQL

        info = {'deployed': False, 'version': None}
        try:
            conn = cls.connect_central()
        except Exception:
            return info
        try:
            cur = conn.cursor()
            cur.execute(DEPLOYED_CHECK_SQL)
            info['deployed'] = cur.fetchone()[0] > 0
            try:
                cur.execute("SELECT value FROM t_schema_metadata WHERE key = 'schema_version'")
                row = cur.fetchone()
                info['version'] = row[0] if row else None
            except Exception:
                pass  # T_SCHEMA_METADATA missing: version unknown
            cur.close()
        except Exception:
            pass
        finally:
            try:
                conn.close()
            except Exception:
                pass
        return info

    @classmethod
    def is_schema_deployed(cls) -> bool:
        """Check if the central schema is deployed and has correct structure."""
        return cls.get_schema_info()['deployed']

    @classmethod
    def get_schema_version(cls) -> Optional[str]:
        """Read schema version from T_SCHEMA_METADATA (returns None if not found)."""
        return cls.get_schema_info()['version']

    @classmethod
    def write_env_file(cls, settings: dict) -> Path:
        """
        Write settings to .env file in the config directory. Reloads config after writing.

        SECURITY: the file holds DASHBOARD_PASSWORD, CENTRAL_DB_PASSWORD and
        ENCRYPTION_KEY, so it is (re)created owner-only (0600) and atomically.
        Values are single-quoted so python-dotenv reads back exactly what was
        written (spaces, '#', quotes, backslashes, '$').

        Args:
            settings: dict of KEY=VALUE pairs to write

        Returns:
            Path to the written .env file

        Raises:
            ValueError: a key or value .env can't hold exactly (e.g. a password
                with a line break or '${VAR}'); nothing is written in that case.
        """
        # Validate everything before touching the existing file.
        lines = [format_env_line(k, v) for k, v in settings.items()]
        content = '\n'.join(lines) + '\n'
        expected = {k: '' if v is None else str(v) for k, v in settings.items()}
        if dict(dotenv_values(stream=io.StringIO(content))) != expected:
            raise ValueError("The settings cannot be written to .env exactly.")

        config_dir = _get_config_dir()
        config_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
        env_file = config_dir / '.env'
        _write_private_file(env_file, content)

        cls._reload_from_env()
        return env_file

    @classmethod
    def _reload_from_env(cls):
        """Re-read all class attributes from environment after .env change."""
        global _active_env_path
        _active_env_path = _load_env_multi()

        cls.DASHBOARD_PASSWORD = os.getenv('DASHBOARD_PASSWORD', '')
        cls.OPERATOR_PASSWORD = os.getenv('OPERATOR_PASSWORD', '')
        cls.VIEWER_PASSWORD = os.getenv('VIEWER_PASSWORD', '')
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
