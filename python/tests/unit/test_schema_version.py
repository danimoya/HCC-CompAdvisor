"""
Unit tests for central schema version handling: version parsing/comparison,
the "send this session to the deployment page?" decision, version stamping,
the startup schema check, and consistency of every place the version lives.
"""
import re
import tomllib
from pathlib import Path

import oracledb
import pytest

from hcc_advisor import __version__
from hcc_advisor.config import Config
from hcc_advisor.utils import schema_version as sv
from hcc_advisor.utils.schema_version import (
    STATUS_CURRENT, STATUS_MISSING, STATUS_NEWER, STATUS_OUTDATED,
    STATUS_PATCH_DIFF, STATUS_UNKNOWN,
    needs_upgrade, parse_version, schema_status, stamp_schema_version,
    version_is_behind, version_notice,
)

REPO_ROOT = Path(__file__).resolve().parents[3]
SCHEMA_SQL = REPO_ROOT / 'sql' / 'central' / '01_central_schema.sql'


class FakeCursor:
    def __init__(self, conn):
        self.conn = conn
        self._rows = []
        self.closed = False

    def execute(self, sql, params=None):
        norm = " ".join(sql.split())
        self.conn.executed.append((norm, params))
        for pattern, result in self.conn.rules:
            if pattern in norm:
                if isinstance(result, Exception):
                    raise result
                self._rows = list(result)
                return
        self._rows = []

    def fetchone(self):
        return self._rows[0] if self._rows else None

    def close(self):
        self.closed = True


class FakeConn:
    def __init__(self, rules=()):
        self.rules = list(rules)
        self.executed = []
        self.cursors = []
        self.commits = 0
        self.closed = False

    def cursor(self):
        cur = FakeCursor(self)
        self.cursors.append(cur)
        return cur

    def commit(self):
        self.commits += 1

    def close(self):
        self.closed = True

    def sql(self):
        return [s for s, _ in self.executed]


# ---------------------------------------------------------------------------
# parse_version
# ---------------------------------------------------------------------------

@pytest.mark.parametrize('value, expected', [
    ('3.0.0', (3, 0, 0)),
    ('3.1', (3, 1, 0)),
    ('3', (3, 0, 0)),
    ('v3.1.2', (3, 1, 2)),
    (' 3.0.0 \n', (3, 0, 0)),
    ('3.1.2-rc1', (3, 1, 2)),
    ('3.1.2+build.7', (3, 1, 2)),
    ('10.20.30', (10, 20, 30)),
    (3, (3, 0, 0)),
])
def test_parse_version_valid(value, expected):
    assert parse_version(value) == expected


@pytest.mark.parametrize('value', [None, '', '   ', 'garbage', 'three', '3abc', 'x3.0.0', '3.0.0.1', '.3'])
def test_parse_version_tolerates_none_and_garbage(value):
    assert parse_version(value) is None


def test_package_version_is_parseable():
    assert parse_version(__version__) is not None


# ---------------------------------------------------------------------------
# schema_status / needs_upgrade
# ---------------------------------------------------------------------------

@pytest.mark.parametrize('deployed, schema, app, expected', [
    (False, '3.0.0', '3.0.0', STATUS_MISSING),
    (False, None, '3.0.0', STATUS_MISSING),
    (True, None, '3.0.0', STATUS_UNKNOWN),
    (True, 'garbage', '3.0.0', STATUS_UNKNOWN),
    (True, '2.0.0', '3.0.0', STATUS_OUTDATED),
    (True, '2.9.9', '3.0.0', STATUS_OUTDATED),
    (True, '3.0.9', '3.1.0', STATUS_OUTDATED),
    (True, '3.0.0', '3.0.0', STATUS_CURRENT),
    (True, '3.0', '3.0.0', STATUS_CURRENT),
    (True, '3.0.1', '3.0.0', STATUS_PATCH_DIFF),
    (True, '3.0.0', '3.0.2', STATUS_PATCH_DIFF),
    (True, '3.1.0', '3.0.0', STATUS_NEWER),
    (True, '4.0.0', '3.9.9', STATUS_NEWER),
])
def test_schema_status(deployed, schema, app, expected):
    assert schema_status(deployed, schema, app) == expected


@pytest.mark.parametrize('status, expected', [
    (STATUS_MISSING, True),
    (STATUS_UNKNOWN, True),
    (STATUS_OUTDATED, True),
    (STATUS_CURRENT, False),
    (STATUS_PATCH_DIFF, False),
    (STATUS_NEWER, False),
])
def test_needs_upgrade_only_for_missing_unknown_or_older_major_minor(status, expected):
    assert needs_upgrade(status) is expected


def test_newer_or_patch_level_schema_never_triggers_deployment_page():
    for schema in ('3.0.1', '3.0.99', '3.1.0', '4.0.0'):
        assert not needs_upgrade(schema_status(True, schema, '3.0.0'))


def test_version_notice():
    assert version_notice(STATUS_CURRENT, '3.0.0', '3.0.0') is None
    assert version_notice(STATUS_OUTDATED, '2.0.0', '3.0.0') is None
    newer = version_notice(STATUS_NEWER, '3.1.0', '3.0.0')
    assert '3.1.0' in newer and '3.0.0' in newer and 'do not re-install' in newer
    patch = version_notice(STATUS_PATCH_DIFF, '3.0.1', '3.0.0')
    assert '3.0.1' in patch and 'No upgrade is required' in patch


@pytest.mark.parametrize('schema, app, expected', [
    ('2.0.0', '3.0.0', True),
    ('3.0.0', '3.0.1', True),
    (None, '3.0.0', True),
    ('garbage', '3.0.0', True),
    ('3.0.0', '3.0.0', False),
    ('3.0.1', '3.0.0', False),   # never stamp a newer schema down
    ('3.1.0', '3.0.0', False),
    ('3.0.0', 'garbage', False),
])
def test_version_is_behind(schema, app, expected):
    assert version_is_behind(schema, app) is expected


# ---------------------------------------------------------------------------
# Single source of truth: the schema seed and pyproject follow __version__
# ---------------------------------------------------------------------------

def _seeded_schema_version() -> str:
    m = re.search(
        r"INSERT INTO T_SCHEMA_METADATA \(KEY, VALUE\) VALUES \('schema_version', '([^']*)'\)",
        SCHEMA_SQL.read_text())
    assert m, "schema_version seed not found in 01_central_schema.sql"
    return m.group(1)


def test_schema_sql_seed_matches_package_version():
    assert _seeded_schema_version() == __version__


def test_fresh_install_is_current_not_an_upgrade():
    """Regression: a fresh install used to record 2.0.0 while the app was
    3.0.0, sending every session into the destructive Upgrade flow."""
    status = schema_status(True, _seeded_schema_version(), __version__)
    assert status == STATUS_CURRENT
    assert not needs_upgrade(status)


def test_pyproject_version_comes_from_package():
    pyproject = tomllib.loads((REPO_ROOT / 'pyproject.toml').read_text())
    assert 'version' not in pyproject['project']
    assert 'version' in pyproject['project']['dynamic']
    path = pyproject['tool']['hatch']['version']['path']
    assert (REPO_ROOT / path).resolve() == (REPO_ROOT / 'python' / 'hcc_advisor' / '__init__.py').resolve()


def test_wheel_bundles_sql_patches():
    pyproject = tomllib.loads((REPO_ROOT / 'pyproject.toml').read_text())
    force_include = pyproject['tool']['hatch']['build']['targets']['wheel']['force-include']
    assert force_include.get('sql/patches') == 'hcc_advisor/sql/patches'


def test_version_bump_patch_check_passes_for_any_v3_or_later():
    """The 3.0.0 bump must not look pending once a later version is stamped
    (re-applying it would stamp the schema back down to 3.0.0)."""
    check = (REPO_ROOT / 'sql' / 'patches' / '20260323-version-bump-v3' / 'check.sql').read_text()
    assert "value = '3.0.0'" not in check
    assert '>= 3' in check


# ---------------------------------------------------------------------------
# stamp_schema_version
# ---------------------------------------------------------------------------

def test_stamp_schema_version_upserts_and_commits():
    conn = FakeConn(rules=[("table_name = 'T_SCHEMA_METADATA'", [(1,)])])
    stamp_schema_version(conn, '3.0.0')
    merges = [(s, p) for s, p in conn.executed if s.startswith('MERGE INTO t_schema_metadata')]
    assert len(merges) == 1
    assert merges[0][1] == {'k': 'schema_version', 'v': '3.0.0'}
    assert not any('CREATE TABLE' in s for s in conn.sql())
    assert not any('last_upgraded_at' in s for s in conn.sql())
    assert conn.commits == 1
    assert all(c.closed for c in conn.cursors)


def test_stamp_schema_version_defaults_to_package_version():
    conn = FakeConn(rules=[("table_name = 'T_SCHEMA_METADATA'", [(1,)])])
    stamp_schema_version(conn)
    assert ({'k': 'schema_version', 'v': __version__}
            in [p for s, p in conn.executed if s.startswith('MERGE')])


def test_stamp_schema_version_creates_missing_table_and_marks_upgrade():
    conn = FakeConn(rules=[("table_name = 'T_SCHEMA_METADATA'", [(0,)])])
    stamp_schema_version(conn, '3.0.0', upgraded=True)
    sql = conn.sql()
    assert any(s.startswith('CREATE TABLE T_SCHEMA_METADATA') for s in sql)
    assert any('last_upgraded_at' in s for s in sql)
    assert conn.commits == 1


def test_stamp_schema_version_raises_and_closes_cursor():
    conn = FakeConn(rules=[
        ("table_name = 'T_SCHEMA_METADATA'", [(1,)]),
        ('MERGE INTO', oracledb.DatabaseError("ORA-01031: insufficient privileges")),
    ])
    with pytest.raises(oracledb.DatabaseError):
        stamp_schema_version(conn, '3.0.0')
    assert conn.commits == 0
    assert all(c.closed for c in conn.cursors)


# ---------------------------------------------------------------------------
# Config.get_schema_info (startup check): one connection, with a timeout
# ---------------------------------------------------------------------------

def test_get_schema_info_uses_one_connection_with_timeout(monkeypatch):
    calls = []
    conn = FakeConn(rules=[
        ("column_name = 'DB_HOST'", [(1,)]),
        ("key = 'schema_version'", [('3.0.0',)]),
    ])

    def fake_connect(**kwargs):
        calls.append(kwargs)
        return conn

    monkeypatch.setattr(oracledb, 'connect', fake_connect)
    info = Config.get_schema_info()
    assert info == {'deployed': True, 'version': '3.0.0'}
    assert len(calls) == 1
    assert calls[0]['tcp_connect_timeout'] == Config.CENTRAL_CONNECT_TIMEOUT
    assert conn.closed


def test_get_schema_info_without_metadata_table(monkeypatch):
    conn = FakeConn(rules=[
        ("column_name = 'DB_HOST'", [(1,)]),
        ("t_schema_metadata", oracledb.DatabaseError("ORA-00942: table or view does not exist")),
    ])
    monkeypatch.setattr(oracledb, 'connect', lambda **kw: conn)
    assert Config.get_schema_info() == {'deployed': True, 'version': None}
    assert conn.closed


def test_get_schema_info_unreachable_db(monkeypatch):
    def fail(**kwargs):
        raise oracledb.OperationalError("DPY-6005: cannot connect to database")

    monkeypatch.setattr(oracledb, 'connect', fail)
    assert Config.get_schema_info() == {'deployed': False, 'version': None}
    assert Config.is_schema_deployed() is False
    assert Config.get_schema_version() is None


def test_deployed_check_sql_is_shared():
    assert 'DB_HOST' in sv.DEPLOYED_CHECK_SQL
