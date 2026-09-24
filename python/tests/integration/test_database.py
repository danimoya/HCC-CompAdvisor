"""
Integration tests against a real Oracle database (read-only).

They run only when a test database is named explicitly, and are skipped
otherwise (the settings in .env / CENTRAL_DB_* are deliberately not used, so a
plain `pytest` never touches a configured central or production database):

    HCC_TEST_DB_HOST      e.g. localhost
    HCC_TEST_DB_PORT      default 1521
    HCC_TEST_DB_SERVICE   e.g. FREEPDB1
    HCC_TEST_DB_USER
    HCC_TEST_DB_PASSWORD

Every statement is a SELECT or an empty PL/SQL block; nothing is created,
changed or compressed.
"""
import os

import oracledb
import pytest

from hcc_advisor.utils.oracle_capabilities import parse_oracle_version
from hcc_advisor.utils.sql_executor import execute_sql_file
from hcc_advisor.utils.target_connector import TargetConnector, build_connect_kwargs

_REQUIRED = ('HCC_TEST_DB_HOST', 'HCC_TEST_DB_SERVICE', 'HCC_TEST_DB_USER',
             'HCC_TEST_DB_PASSWORD')
_MISSING = [name for name in _REQUIRED if not os.getenv(name)]

pytestmark = [
    pytest.mark.integration,
    pytest.mark.database,
    pytest.mark.skipif(bool(_MISSING), reason=(
        "no test database configured (set " + ", ".join(_REQUIRED) + ")")),
]

# A database_id no registered target uses: the pool is created from the
# config passed in, never from the central registry.
_TEST_DATABASE_ID = -4242


@pytest.fixture(scope='module')
def conn_config():
    return {
        'host': os.getenv('HCC_TEST_DB_HOST'),
        'port': int(os.getenv('HCC_TEST_DB_PORT', '1521')),
        'service': os.getenv('HCC_TEST_DB_SERVICE'),
        'username': os.getenv('HCC_TEST_DB_USER'),
        'password': os.getenv('HCC_TEST_DB_PASSWORD'),
    }


@pytest.fixture
def connection(conn_config):
    conn = oracledb.connect(**build_connect_kwargs(conn_config), tcp_connect_timeout=10)
    try:
        yield conn
    finally:
        conn.close()


class TestDatabaseIntegration:

    def test_select_from_dual(self, connection):
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1 FROM DUAL")
            assert cursor.fetchone() == (1,)

    def test_version_banner_is_understood(self, connection):
        """The v$version banner stored for a target parses to (major, minor)."""
        with connection.cursor() as cursor:
            cursor.execute("SELECT banner FROM v$version WHERE ROWNUM = 1")
            banner = cursor.fetchone()[0]
        version = parse_oracle_version(banner)
        assert version is not None, banner
        assert version[0] >= 11

    def test_direct_connection_test(self, conn_config):
        assert TargetConnector.test_connection_direct(conn_config) is True

    def test_pooled_query(self, conn_config):
        try:
            df = TargetConnector.execute_query(
                _TEST_DATABASE_ID, "SELECT :n AS n, USER AS username FROM DUAL",
                {'n': 7}, conn_config=conn_config, raise_on_error=True)
        finally:
            TargetConnector.close_pool(_TEST_DATABASE_ID)
        assert df['N'].tolist() == [7]
        assert df['USERNAME'].iloc[0] == conn_config['username'].upper()

    def test_sql_executor_runs_a_script(self, connection, tmp_path):
        script = tmp_path / 'readonly.sql'
        script.write_text(
            "SET SERVEROUTPUT ON\n"
            "SELECT COUNT(*) FROM user_tables;\n"
            "BEGIN\n  NULL;\nEND;\n/\n")
        ok, errors, messages = execute_sql_file(connection, script)
        assert (ok, errors) == (2, 0), messages
