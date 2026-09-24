"""
Unit tests for the non-destructive schema Upgrade and the deployment page's
destructive actions:

- utils/sql_patches: patch directory checks, detection (check.sql + history),
  application and recording, stop-on-first-failure;
- views/page_00_setup: drop-object list vs the schema script, typed
  confirmation, install stamps __version__, Upgrade applies patches then
  stamps (never downgrades).

The central DB is replaced by a fake connection that records statements.
"""
import re
from pathlib import Path

import oracledb
import pytest

from hcc_advisor import __version__
from hcc_advisor.utils import sql_patches
from hcc_advisor.utils.sql_patches import (
    PATCH_APPLIED, PATCH_FAILED, PatchError,
    apply_patch_sql, apply_pending_patches, check_patch_applied,
    find_patches_dir, is_patch_applied, list_patch_dirs, patches_dir_problem,
    resolve_patches_dir, scan_patches,
)
from hcc_advisor.views import page_00_setup as setup

REPO_ROOT = Path(__file__).resolve().parents[3]
SCHEMA_SQL = REPO_ROOT / 'sql' / 'central' / '01_central_schema.sql'


class FakeCursor:
    def __init__(self, conn):
        self.conn = conn
        self._rows = []
        self.description = None
        self.closed = False

    def execute(self, sql, params=None):
        norm = " ".join(sql.split())
        self.conn.executed.append((norm, params))
        for pattern, result in self.conn.rules:
            if pattern in norm:
                if isinstance(result, Exception):
                    raise result
                cols, rows = result if isinstance(result, tuple) else (('RESULT',), result)
                self._rows = list(rows)
                self.description = [(c,) for c in cols]
                return
        self._rows = []
        self.description = None

    def fetchone(self):
        return self._rows[0] if self._rows else None

    def fetchall(self):
        return list(self._rows)

    def close(self):
        self.closed = True


class FakeConn:
    def __init__(self, rules=()):
        self.rules = list(rules)
        self.executed = []
        self.cursors = []
        self.commits = 0
        self.rollbacks = 0
        self.closed = False

    def cursor(self):
        cur = FakeCursor(self)
        self.cursors.append(cur)
        return cur

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1

    def close(self):
        self.closed = True

    def sql(self):
        return [s for s, _ in self.executed]

    def history_inserts(self):
        return [p for s, p in self.executed if s.startswith('INSERT INTO t_patch_history')]


HISTORY_EXISTS = ("table_name = 'T_PATCH_HISTORY'", [(1,)])


def _history(*rows):
    """Rule returning T_PATCH_HISTORY rows (name, status, date, by)."""
    return ('FROM t_patch_history ORDER BY',
            (('PATCH_NAME', 'STATUS', 'APPLIED_DATE', 'APPLIED_BY'), list(rows)))


def _make_patch(root: Path, name: str, check: str = None, patch: str = None) -> Path:
    d = root / name
    d.mkdir()
    if check is not None:
        (d / 'check.sql').write_text(check)
    if patch is not None:
        (d / 'patch.sql').write_text(patch)
    (d / 'readme.md').write_text(f"## {name}")
    return d


@pytest.fixture
def patches_root(tmp_path):
    root = tmp_path / 'patches'
    root.mkdir()
    root.chmod(0o755)
    return root


# ---------------------------------------------------------------------------
# Patch directory
# ---------------------------------------------------------------------------

def test_find_patches_dir_finds_repo_patches():
    found = find_patches_dir()
    assert found is not None
    assert (found / '20260323-version-bump-v3' / 'patch.sql').exists()


def test_patches_dir_problem_rejects_group_or_world_writable(patches_root):
    assert patches_dir_problem(patches_root) is None
    patches_root.chmod(0o775)
    assert 'group/world-writable' in patches_dir_problem(patches_root)
    patches_root.chmod(0o757)
    assert 'group/world-writable' in patches_dir_problem(patches_root)


def test_resolve_patches_dir(patches_root, monkeypatch):
    assert resolve_patches_dir(patches_root) == patches_root
    patches_root.chmod(0o777)
    with pytest.raises(PatchError, match='group/world-writable'):
        resolve_patches_dir(patches_root)
    monkeypatch.setattr(sql_patches, 'find_patches_dir', lambda: None)
    with pytest.raises(PatchError, match='not found'):
        resolve_patches_dir()


def test_list_patch_dirs_sorted_by_name(patches_root):
    for name in ('20260327-b', '20260319-a', '20260331-c'):
        _make_patch(patches_root, name)
    (patches_root / 'README.md').write_text('not a patch')
    assert [d.name for d in list_patch_dirs(patches_root)] == ['20260319-a', '20260327-b', '20260331-c']


# ---------------------------------------------------------------------------
# Detection
# ---------------------------------------------------------------------------

def test_check_patch_applied_reads_result_column():
    conn = FakeConn(rules=[('probe_yes', (('OTHER', 'RESULT'), [(0, 2)])),
                           ('probe_no', [(0,)]),
                           ('probe_null', [(None,)])])
    assert check_patch_applied("SELECT 0 other, 2 as result FROM probe_yes;", conn=conn) is True
    assert check_patch_applied("SELECT COUNT(*) as result FROM probe_no", conn=conn) is False
    assert check_patch_applied("SELECT NULL as result FROM probe_null", conn=conn) is False
    # trailing ';' is stripped before execution
    assert conn.executed[0][0] == "SELECT 0 other, 2 as result FROM probe_yes"


def test_check_patch_applied_failure_reads_as_not_applied():
    conn = FakeConn(rules=[('t_missing', oracledb.DatabaseError("ORA-00942: table or view does not exist"))])
    assert check_patch_applied("SELECT COUNT(*) as result FROM t_missing", conn=conn) is False


def test_is_patch_applied():
    recorded = {'a': {'status': 'SUCCESS'}, 'b': {'status': 'FAILED'}}
    assert is_patch_applied('a', recorded, {})
    assert not is_patch_applied('b', recorded, {})
    assert is_patch_applied('b', recorded, {'b': True})
    assert not is_patch_applied('c', recorded, {'c': False})


def test_scan_patches_detects_and_auto_records(patches_root):
    p1 = _make_patch(patches_root, '20260101-detected', check='SELECT COUNT(*) as result FROM probe_p1')
    p2 = _make_patch(patches_root, '20260102-pending', check='SELECT COUNT(*) as result FROM probe_p2')
    p3 = _make_patch(patches_root, '20260103-recorded', check='SELECT COUNT(*) as result FROM probe_p3')
    p4 = _make_patch(patches_root, '20260104-no-check', patch='SELECT 1 FROM dual;')
    conn = FakeConn(rules=[
        HISTORY_EXISTS,
        _history(('20260103-recorded', 'SUCCESS', '2026-03-01 10:00:00', 'ADMIN')),
        ('probe_p1', [(1,)]), ('probe_p2', [(0,)]), ('probe_p3', [(0,)]),
    ])
    scan = scan_patches([p1, p2, p3, p4], conn=conn)

    assert scan.has_history_table
    assert scan.detected == {'20260101-detected': True, '20260102-pending': False,
                             '20260103-recorded': False}
    assert scan.auto_marked == 1
    assert conn.history_inserts() == [{'n': '20260101-detected', 's': 'SUCCESS'}]
    assert [d.name for d in scan.pending] == ['20260102-pending', '20260104-no-check']


def test_scan_patches_creates_history_table_when_missing(patches_root):
    conn = FakeConn(rules=[("table_name = 'T_PATCH_HISTORY'", [(0,)])])
    scan = scan_patches([], conn=conn)
    assert scan.has_history_table
    assert any(s.startswith('CREATE TABLE T_PATCH_HISTORY') for s in conn.sql())


# ---------------------------------------------------------------------------
# Application
# ---------------------------------------------------------------------------

def test_apply_patch_sql_runs_each_statement_and_commits():
    conn = FakeConn()
    sql = ("-- comment\n"
           "UPDATE t SET note = 'a;b' WHERE id = 1;\n"
           "BEGIN\n  NULL;\nEND;\n/\n"
           "COMMIT;\n")
    assert apply_patch_sql(sql, conn=conn) == 3
    assert conn.sql() == ["UPDATE t SET note = 'a;b' WHERE id = 1", "BEGIN NULL; END;", "COMMIT"]
    assert conn.commits == 1
    assert all(c.closed for c in conn.cursors)


def test_apply_patch_sql_raises_and_rolls_back():
    conn = FakeConn(rules=[('boom', oracledb.DatabaseError("ORA-00001: unique constraint violated"))])
    with pytest.raises(oracledb.DatabaseError):
        apply_patch_sql("DELETE FROM a;\nINSERT INTO boom VALUES (1);\nDELETE FROM never_run;", conn=conn)
    assert 'DELETE FROM never_run' not in conn.sql()
    assert conn.rollbacks == 1
    assert conn.commits == 0


def test_apply_pending_patches_applies_in_order_and_records(patches_root):
    _make_patch(patches_root, '20260101-done', check='SELECT COUNT(*) as result FROM probe_done',
                patch='DELETE FROM should_not_run;')
    _make_patch(patches_root, '20260102-first', check='SELECT COUNT(*) as result FROM probe_first',
                patch='ALTER TABLE t ADD (c1 NUMBER);')
    _make_patch(patches_root, '20260103-second', patch='UPDATE t SET c1 = 0;\nCOMMIT;')
    conn = FakeConn(rules=[HISTORY_EXISTS, ('probe_done', [(1,)]), ('probe_first', [(0,)])])

    progress = []
    outcome = apply_pending_patches(conn=conn, patches_dir=patches_root,
                                    on_progress=lambda i, n, name: progress.append((i, n, name)))

    assert outcome.ok
    assert [(r.name, r.status) for r in outcome.results] == [
        ('20260102-first', PATCH_APPLIED), ('20260103-second', PATCH_APPLIED)]
    assert progress == [(0, 2, '20260102-first'), (1, 2, '20260103-second')]
    assert 'DELETE FROM should_not_run' not in conn.sql()
    assert conn.sql().index('ALTER TABLE t ADD (c1 NUMBER)') < conn.sql().index('UPDATE t SET c1 = 0')
    assert conn.history_inserts() == [
        {'n': '20260101-done', 's': 'SUCCESS'},       # auto-marked by detection
        {'n': '20260102-first', 's': 'SUCCESS'},
        {'n': '20260103-second', 's': 'SUCCESS'},
    ]


def test_apply_pending_patches_stops_at_first_failure(patches_root):
    _make_patch(patches_root, '20260101-ok', patch='UPDATE t SET a = 1;')
    _make_patch(patches_root, '20260102-bad', patch='ALTER TABLE boom ADD (x NUMBER);')
    _make_patch(patches_root, '20260103-later', patch='UPDATE later SET a = 1;')
    conn = FakeConn(rules=[HISTORY_EXISTS,
                           ('boom', oracledb.DatabaseError("ORA-01430: column being added already exists"))])

    outcome = apply_pending_patches(conn=conn, patches_dir=patches_root)

    assert not outcome.ok
    assert outcome.failed.name == '20260102-bad'
    assert 'ORA-01430' in outcome.failed.error
    assert [r.status for r in outcome.results] == [PATCH_APPLIED, PATCH_FAILED]
    assert 'UPDATE later SET a = 1' not in conn.sql()
    failed_rows = [p for p in conn.history_inserts() if p.get('s') == 'FAILED']
    assert len(failed_rows) == 1 and failed_rows[0]['n'] == '20260102-bad'
    assert 'ORA-01430' in failed_rows[0]['e']


def test_apply_pending_patches_missing_patch_sql_is_a_failure(patches_root):
    _make_patch(patches_root, '20260101-empty')
    conn = FakeConn(rules=[HISTORY_EXISTS])
    outcome = apply_pending_patches(conn=conn, patches_dir=patches_root)
    assert outcome.failed.name == '20260101-empty'


def test_apply_pending_patches_refuses_unsafe_dir(patches_root):
    _make_patch(patches_root, '20260101-x', patch='UPDATE t SET a = 1;')
    patches_root.chmod(0o777)
    conn = FakeConn(rules=[HISTORY_EXISTS])
    with pytest.raises(PatchError):
        apply_pending_patches(conn=conn, patches_dir=patches_root)
    assert conn.executed == []


# ---------------------------------------------------------------------------
# Deployment page: drop list, typed confirmation
# ---------------------------------------------------------------------------

def _created_in_schema(kind: str) -> set:
    text = SCHEMA_SQL.read_text()
    return {m.upper() for m in re.findall(rf"CREATE\s+{kind}\s+(\w+)", text, re.IGNORECASE)}


def test_schema_tables_match_schema_script():
    assert set(setup._SCHEMA_TABLES) == _created_in_schema('TABLE')


def test_drop_list_covers_schema_and_patch_history_only():
    created_tables = _created_in_schema('TABLE')
    assert set(setup._DROP_TABLES) == created_tables | {'T_PATCH_HISTORY'}
    assert len(setup._DROP_TABLES) == len(set(setup._DROP_TABLES))
    # T_PATCH_HISTORY is created by the patch system, not the schema script
    assert 'CREATE TABLE T_PATCH_HISTORY' in sql_patches._PATCH_HISTORY_DDL


def test_drop_sequences_match_schema_script():
    created = _created_in_schema('SEQUENCE')
    assert created == {'SEQ_EXECUTION_ID'}
    assert set(setup._DROP_SEQUENCES) == created
    assert 'SEQ_DATABASE_ID' not in setup._DROP_SEQUENCES


def test_drop_all_hcc_objects(monkeypatch):
    conn = FakeConn(rules=[
        ('DROP TABLE T_PATCH_HISTORY', oracledb.DatabaseError("ORA-00942: table or view does not exist")),
        ('DROP TABLE T_ADVISOR_RUN', oracledb.DatabaseError("ORA-00054: resource busy")),
    ])
    monkeypatch.setattr(setup, '_connect', lambda *a: conn)
    msgs = setup._drop_all_hcc_objects('h', 1521, 's', 'u', 'p')

    dropped = [s for s in conn.sql() if s.startswith('DROP')]
    assert dropped == ([f"DROP TABLE {t} CASCADE CONSTRAINTS PURGE" for t in setup._DROP_TABLES]
                       + ["DROP SEQUENCE SEQ_EXECUTION_ID"])
    assert "Dropped table T_COMPRESSION_HISTORY" in msgs
    assert not any('T_PATCH_HISTORY' in m for m in msgs)        # absent table: silent
    assert any(m.startswith('Could not drop table T_ADVISOR_RUN') for m in msgs)
    assert conn.closed


@pytest.mark.parametrize('typed, phrase, expected', [
    ('REINSTALL', 'REINSTALL', True),
    ('  REINSTALL \n', 'REINSTALL', True),
    ('reinstall', 'REINSTALL', False),
    ('REINSTAL', 'REINSTALL', False),
    ('', 'REINSTALL', False),
    (None, 'REINSTALL', False),
    ('UNINSTALL', 'REINSTALL', False),
    ('UNINSTALL', 'UNINSTALL', True),
])
def test_confirmation_matches(typed, phrase, expected):
    assert setup._confirmation_matches(typed, phrase) is expected


def test_destructive_phrases_are_distinct():
    assert setup._REINSTALL_CONFIRM_PHRASE != setup._CLEANUP_CONFIRM_PHRASE


# ---------------------------------------------------------------------------
# Deployment page: install stamps __version__, Upgrade is non-destructive
# ---------------------------------------------------------------------------

def test_run_schema_install_stamps_package_version(monkeypatch):
    import hcc_advisor.utils.sql_executor as sql_executor
    conn = FakeConn(rules=[("table_name = 'T_SCHEMA_METADATA'", [(1,)])])
    monkeypatch.setattr(setup, '_connect', lambda *a: conn)
    monkeypatch.setattr(sql_executor, 'execute_sql_file',
                        lambda c, path, on_progress=None: (5, 0, [f"[OK] {Path(path).name}"]))

    ok, err, msgs = setup._run_schema_install('h', 1521, 's', 'u', 'p')

    assert err == 0
    assert ({'k': 'schema_version', 'v': __version__}
            in [p for s, p in conn.executed if s.startswith('MERGE INTO t_schema_metadata')])
    assert f"[OK] schema_version set to {__version__}" in msgs
    assert conn.closed


def test_run_upgrade_applies_patches_then_stamps(monkeypatch, patches_root):
    _make_patch(patches_root, '20260101-add-col', patch='ALTER TABLE t ADD (c NUMBER);')
    conn = FakeConn(rules=[HISTORY_EXISTS, ("table_name = 'T_SCHEMA_METADATA'", [(1,)])])
    monkeypatch.setattr(setup, '_connect', lambda *a: conn)
    monkeypatch.setattr(sql_patches, 'find_patches_dir', lambda: patches_root)

    outcome, stamped = setup._run_upgrade('h', 1521, 's', 'u', 'p', schema_version='2.0.0')

    assert outcome.ok and stamped
    sql = conn.sql()
    assert not any(s.startswith('DROP') for s in sql)          # nothing is dropped
    assert sql.index('ALTER TABLE t ADD (c NUMBER)') < max(
        i for i, s in enumerate(sql) if s.startswith('MERGE INTO t_schema_metadata'))
    merges = [p for s, p in conn.executed if s.startswith('MERGE INTO t_schema_metadata')]
    assert {'k': 'schema_version', 'v': __version__} in merges
    assert any('last_upgraded_at' in s for s in sql)
    assert conn.closed


def test_run_upgrade_does_not_stamp_after_failed_patch(monkeypatch, patches_root):
    _make_patch(patches_root, '20260101-bad', patch='ALTER TABLE boom ADD (c NUMBER);')
    conn = FakeConn(rules=[HISTORY_EXISTS, ("table_name = 'T_SCHEMA_METADATA'", [(1,)]),
                           ('boom', oracledb.DatabaseError("ORA-00942: table or view does not exist"))])
    monkeypatch.setattr(setup, '_connect', lambda *a: conn)
    monkeypatch.setattr(sql_patches, 'find_patches_dir', lambda: patches_root)

    outcome, stamped = setup._run_upgrade('h', 1521, 's', 'u', 'p', schema_version='2.0.0')

    assert not outcome.ok and not stamped
    assert not any(s.startswith('MERGE INTO t_schema_metadata') for s in conn.sql())


def test_run_upgrade_never_stamps_newer_schema_down(monkeypatch, patches_root):
    conn = FakeConn(rules=[HISTORY_EXISTS, ("table_name = 'T_SCHEMA_METADATA'", [(1,)])])
    monkeypatch.setattr(setup, '_connect', lambda *a: conn)
    monkeypatch.setattr(sql_patches, 'find_patches_dir', lambda: patches_root)

    outcome, stamped = setup._run_upgrade('h', 1521, 's', 'u', 'p', schema_version='9.0.0')

    assert outcome.ok and not stamped
    assert not any(s.startswith('MERGE INTO t_schema_metadata') for s in conn.sql())


def test_run_upgrade_creates_metadata_table_before_patches(monkeypatch, patches_root):
    """A schema without T_SCHEMA_METADATA (version unknown) must be upgradable:
    the 3.0.0 bump patch writes to that table."""
    _make_patch(patches_root, '20260101-bump',
                patch="UPDATE t_schema_metadata SET value = '3.0.0' WHERE key = 'schema_version';")
    conn = FakeConn(rules=[HISTORY_EXISTS, ("table_name = 'T_SCHEMA_METADATA'", [(0,)])])
    monkeypatch.setattr(setup, '_connect', lambda *a: conn)
    monkeypatch.setattr(sql_patches, 'find_patches_dir', lambda: patches_root)

    outcome, stamped = setup._run_upgrade('h', 1521, 's', 'u', 'p', schema_version=None)

    sql = conn.sql()
    create = sql.index(next(s for s in sql if s.startswith('CREATE TABLE T_SCHEMA_METADATA')))
    assert create < sql.index("UPDATE t_schema_metadata SET value = '3.0.0' WHERE key = 'schema_version'")
    assert outcome.ok and stamped


# ---------------------------------------------------------------------------
# Admin page reuses the shared helpers
# ---------------------------------------------------------------------------

def test_admin_page_uses_shared_patch_helpers():
    from hcc_advisor.views import page_09_admin
    assert page_09_admin._record_patch is sql_patches.record_patch
    assert page_09_admin.scan_patches is sql_patches.scan_patches
