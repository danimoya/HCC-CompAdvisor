"""
Unit tests for hcc_advisor.config (Config and the .env discovery helpers).

- .env discovery: the config dir (HCC_ADVISOR_CONFIG_DIR) wins over the
  working directory; the XDG defaults apply when the env vars are unset.
- Config.validate_config reports a missing central password, a missing or
  unusable Fernet ENCRYPTION_KEY and missing SSL files, and nothing for a
  complete configuration.
- The dashboard secret rules (auth.validate_new_password) agree with what the
  .env writer can store.

The .env writer itself (quoting, 0600, atomic replace) is covered by
test_auth_env_hardening; get_schema_info by test_schema_version.
"""
import io
import os
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from cryptography.fernet import Fernet
from dotenv import dotenv_values

from hcc_advisor import auth
from hcc_advisor import config as config_module
from hcc_advisor.config import Config, format_env_line


@pytest.fixture
def restore_env():
    """Undo os.environ changes made by load_dotenv (monkeypatch can't see them)."""
    saved = dict(os.environ)
    saved_attrs = {k: v for k, v in vars(Config).items() if k.isupper()}
    saved_active = config_module._active_env_path
    yield
    os.environ.clear()
    os.environ.update(saved)
    for k, v in saved_attrs.items():
        setattr(Config, k, v)
    config_module._active_env_path = saved_active


@pytest.fixture
def valid_config(monkeypatch):
    """A configuration validate_config accepts: central password, a real
    Fernet key, SSL off."""
    monkeypatch.setattr(Config, 'CENTRAL_DB_PASSWORD', 'central-secret')
    monkeypatch.setattr(Config, 'ENCRYPTION_KEY', Fernet.generate_key().decode())
    monkeypatch.setattr(Config, 'SSL_ENABLED', False)


# ---------------------------------------------------------------------------
# Config / data directories and .env discovery
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestConfigLoader:

    def test_config_dir_from_env(self, monkeypatch, tmp_path):
        monkeypatch.setenv('HCC_ADVISOR_CONFIG_DIR', str(tmp_path / 'cfg'))
        assert Config.get_config_dir() == tmp_path / 'cfg'

    def test_config_dir_default_is_xdg(self, monkeypatch):
        monkeypatch.delenv('HCC_ADVISOR_CONFIG_DIR', raising=False)
        assert Config.get_config_dir() == Path.home() / '.config' / 'hcc-advisor'

    def test_data_dir_from_env_and_default(self, monkeypatch, tmp_path):
        monkeypatch.setenv('HCC_ADVISOR_DATA_DIR', str(tmp_path / 'data'))
        assert Config.get_data_dir() == tmp_path / 'data'
        monkeypatch.delenv('HCC_ADVISOR_DATA_DIR')
        assert Config.get_data_dir() == Path.home() / '.local' / 'share' / 'hcc-advisor'

    def test_config_dir_env_file_wins_over_cwd(self, monkeypatch, tmp_path, restore_env):
        cfg_dir, cwd = tmp_path / 'cfg', tmp_path / 'cwd'
        cfg_dir.mkdir()
        cwd.mkdir()
        (cfg_dir / '.env').write_text("HCC_TEST_ENV_SOURCE='config-dir'\n")
        (cwd / '.env').write_text("HCC_TEST_ENV_SOURCE='cwd'\n")
        monkeypatch.setenv('HCC_ADVISOR_CONFIG_DIR', str(cfg_dir))
        monkeypatch.chdir(cwd)

        assert config_module._load_env_multi() == cfg_dir / '.env'
        assert os.environ['HCC_TEST_ENV_SOURCE'] == 'config-dir'

    def test_cwd_env_file_is_the_fallback(self, monkeypatch, tmp_path, restore_env):
        if (Path(config_module.__file__).parent / '.env').exists():
            pytest.skip("a package-directory .env takes precedence over the cwd")
        cwd = tmp_path / 'cwd'
        cwd.mkdir()
        (cwd / '.env').write_text("HCC_TEST_ENV_SOURCE='cwd'\n")
        monkeypatch.setenv('HCC_ADVISOR_CONFIG_DIR', str(tmp_path / 'missing'))
        monkeypatch.chdir(cwd)

        assert config_module._load_env_multi() == cwd / '.env'
        assert os.environ['HCC_TEST_ENV_SOURCE'] == 'cwd'

    def test_no_env_file_anywhere(self, monkeypatch, tmp_path, restore_env):
        if (Path(config_module.__file__).parent / '.env').exists():
            pytest.skip("a package-directory .env exists")
        monkeypatch.setenv('HCC_ADVISOR_CONFIG_DIR', str(tmp_path / 'missing'))
        monkeypatch.chdir(tmp_path)
        assert config_module._load_env_multi() is None

    def test_reload_reads_secrets_and_central_fallbacks(self, monkeypatch, tmp_path, restore_env):
        """_reload_from_env (run after the setup wizard writes .env) re-reads the
        secrets and falls back to the legacy DB_* variables."""
        monkeypatch.setenv('HCC_ADVISOR_CONFIG_DIR', str(tmp_path / 'missing'))
        monkeypatch.chdir(tmp_path)
        for name in ('CENTRAL_DB_HOST', 'CENTRAL_DB_PORT', 'CENTRAL_DB_USER',
                     'CENTRAL_DB_PASSWORD', 'CENTRAL_DB_SERVICE'):
            monkeypatch.delenv(name, raising=False)
        monkeypatch.setenv('DB_HOST', 'legacy-host')
        monkeypatch.setenv('DB_PORT', '1600')
        monkeypatch.setenv('DB_PASSWORD', 'legacy-pw')
        monkeypatch.setenv('DASHBOARD_PASSWORD', 'a-long-admin-secret')
        monkeypatch.setenv('OPERATOR_PASSWORD', 'a-long-operator-secret')

        Config._reload_from_env()

        assert Config.CENTRAL_DB_HOST == 'legacy-host'
        assert Config.CENTRAL_DB_PORT == 1600
        assert Config.CENTRAL_DB_PASSWORD == 'legacy-pw'
        assert Config.DASHBOARD_PASSWORD == 'a-long-admin-secret'
        assert Config.OPERATOR_PASSWORD == 'a-long-operator-secret'
        assert Config.get_central_db_dsn() == f'legacy-host:1600/{Config.CENTRAL_DB_SERVICE}'


# ---------------------------------------------------------------------------
# Connection strings and first-run detection
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestConnectionSettings:

    def test_central_dsn(self, monkeypatch):
        monkeypatch.setattr(Config, 'CENTRAL_DB_HOST', 'db.example')
        monkeypatch.setattr(Config, 'CENTRAL_DB_PORT', 1522)
        monkeypatch.setattr(Config, 'CENTRAL_DB_SERVICE', 'CENTRALPDB')
        assert Config.get_central_db_dsn() == 'db.example:1522/CENTRALPDB'

    def test_legacy_connection_string(self, monkeypatch):
        for name, value in (('DB_USER', 'u'), ('DB_PASSWORD', 'p'), ('DB_HOST', 'h'),
                            ('DB_PORT', 1521), ('DB_SERVICE', 's')):
            monkeypatch.setattr(Config, name, value)
        assert Config.get_db_connection_string() == 'u/p@h:1521/s'

    def test_connect_central_uses_the_connect_timeout(self, monkeypatch):
        import oracledb
        connect = MagicMock(name='connect')
        monkeypatch.setattr(oracledb, 'connect', connect)
        monkeypatch.setattr(Config, 'CENTRAL_CONNECT_TIMEOUT', 7)
        monkeypatch.setattr(Config, 'CENTRAL_DB_USER', 'COMPRESSION_MGR')
        monkeypatch.setattr(Config, 'CENTRAL_DB_PASSWORD', 'pw')

        Config.connect_central()

        kwargs = connect.call_args.kwargs
        assert kwargs['tcp_connect_timeout'] == 7
        assert kwargs['user'] == 'COMPRESSION_MGR'
        assert kwargs['dsn'] == Config.get_central_db_dsn()

    @pytest.mark.parametrize('env_path, central_pw, expected', [
        (None, None, True),
        (None, 'pw', False),
        (Path('/somewhere/.env'), None, False),
    ])
    def test_is_first_run(self, monkeypatch, env_path, central_pw, expected):
        monkeypatch.setattr(config_module, '_active_env_path', env_path)
        if central_pw is None:
            monkeypatch.delenv('CENTRAL_DB_PASSWORD', raising=False)
        else:
            monkeypatch.setenv('CENTRAL_DB_PASSWORD', central_pw)
        assert Config.is_first_run() is expected

    def test_schema_helpers_delegate_to_get_schema_info(self, monkeypatch):
        monkeypatch.setattr(Config, 'get_schema_info',
                            MagicMock(return_value={'deployed': True, 'version': '2.1.0'}))
        assert Config.is_schema_deployed() is True
        assert Config.get_schema_version() == '2.1.0'


# ---------------------------------------------------------------------------
# validate_config / SSL
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestConfigValidation:

    def test_complete_config_has_no_errors(self, valid_config):
        assert Config.validate_config() == []

    def test_missing_central_password(self, valid_config, monkeypatch):
        monkeypatch.setattr(Config, 'CENTRAL_DB_PASSWORD', '')
        errors = Config.validate_config()
        assert len(errors) == 1
        assert 'CENTRAL_DB_PASSWORD' in errors[0]

    def test_missing_encryption_key(self, valid_config, monkeypatch):
        monkeypatch.setattr(Config, 'ENCRYPTION_KEY', '')
        errors = Config.validate_config()
        assert len(errors) == 1
        assert 'ENCRYPTION_KEY not set' in errors[0]

    @pytest.mark.parametrize('key', ['not-a-key', 'x' * 44, Fernet.generate_key().decode()[:-2]])
    def test_unusable_encryption_key(self, valid_config, monkeypatch, key):
        monkeypatch.setattr(Config, 'ENCRYPTION_KEY', key)
        errors = Config.validate_config()
        assert len(errors) == 1
        assert 'not a valid Fernet key' in errors[0]
        assert key not in errors[0]  # never echo the secret

    def test_ssl_enabled_without_files(self, valid_config, monkeypatch, tmp_path):
        monkeypatch.setattr(Config, 'SSL_ENABLED', True)
        monkeypatch.setattr(Config, 'SSL_CERT_FILE', str(tmp_path / 'cert.pem'))
        monkeypatch.setattr(Config, 'SSL_KEY_FILE', str(tmp_path / 'key.pem'))
        errors = Config.validate_config()
        assert any('SSL certificate not found' in e for e in errors)
        assert any('SSL key not found' in e for e in errors)
        assert Config.get_ssl_context() is None

    def test_ssl_enabled_with_files(self, valid_config, monkeypatch, tmp_path):
        cert, key = tmp_path / 'cert.pem', tmp_path / 'key.pem'
        cert.write_text('cert')
        key.write_text('key')
        monkeypatch.setattr(Config, 'SSL_ENABLED', True)
        monkeypatch.setattr(Config, 'SSL_CERT_FILE', str(cert))
        monkeypatch.setattr(Config, 'SSL_KEY_FILE', str(key))
        assert Config.validate_config() == []
        assert Config.get_ssl_context() == (str(cert), str(key))

    def test_ssl_disabled_has_no_context(self, valid_config):
        assert Config.get_ssl_context() is None

    def test_validate_auth_config(self):
        """The dashboard secret rules as the app enforces them today.

        This test used to assert a 32-character secret on a 15-character
        fixture, a rule the app never had. The real rule is
        auth.validate_new_password: at least MIN_PASSWORD_LENGTH (12)
        characters, not a known default, and storable in .env exactly (the
        setup wizard writes it there with format_env_line). The login policy
        values default to positive numbers.
        """
        assert auth.MIN_PASSWORD_LENGTH == 12
        # 15 characters, the length of the old fixture's secret: acceptable.
        assert auth.validate_new_password('test_secret_key') is None
        # The boundary sits at MIN_PASSWORD_LENGTH.
        assert auth.validate_new_password('x' * 12) is None
        assert 'at least 12' in auth.validate_new_password('x' * 11)
        # Whatever passes validation round-trips through the .env writer.
        for password in ('test_secret_key', "it's #1 \\ $HOME ok", 'x' * 12):
            assert auth.validate_new_password(password) is None
            line = format_env_line('DASHBOARD_PASSWORD', password)
            parsed = dotenv_values(stream=io.StringIO(line + '\n'))
            assert parsed['DASHBOARD_PASSWORD'] == password
        assert Config.SESSION_TIMEOUT_MINUTES > 0
        assert Config.MAX_LOGIN_ATTEMPTS > 0
