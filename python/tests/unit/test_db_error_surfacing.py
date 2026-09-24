"""
Unit tests for surfacing database errors instead of reporting false success:
- the connectors' opt-in strict mode (raise_on_error) vs the default
  st.error + sentinel behaviour,
- the Admin SQL patch applier (a failed statement is recorded as FAILED),
- the Tablespace Manager datafile resize (valid DDL, validated inputs, only
  real successes counted),
- CentralQueries target registration / strategy paths that expect exceptions.

No database: connections come from fake pools whose cursors record every
statement and raise oracledb errors on demand.
"""
import re
from unittest.mock import MagicMock

import oracledb
import pandas as pd
import pytest

from hcc_advisor.utils import central_connector as cc_module
from hcc_advisor.utils import target_connector as tc_module
from hcc_advisor.utils.central_connector import CentralConnector
from hcc_advisor.utils.central_queries import CentralQueries
from hcc_advisor.utils.target_connector import TargetConnector
from hcc_advisor.utils import sql_patches
from hcc_advisor.views import page_09_admin, page_10_tablespaces


MB = 1048576


# ============================================================================
# Fake oracledb pool / connection / cursor
# ============================================================================

class FakeDB:
    """
    Shared state behind the fake connections. `handler(sql, params)` returns
    None or a dict with optional 'rows', 'columns', 'rowcount', or raises.
    """

    def __init__(self):
        self.handler = lambda sql, params: None
        self.executed = []        # (normalised_sql, params)
        self.commits = 0

    def fail_on(self, needle: str, message: str):
        """Raise oracledb.DatabaseError(message) for any statement containing needle."""
        previous = self.handler

        def handler(sql, params):
            if needle in sql:
                raise oracledb.DatabaseError(message)
            return previous(sql, params)
        self.handler = handler


class FakeCursor:
    def __init__(self, db: FakeDB):
        self.db = db
        self.description = None
        self.rowcount = 0
        self._rows = []

    def execute(self, sql, params=None):
        self.db.executed.append((" ".join(sql.split()), params))
        out = self.db.handler(sql, params) or {}
        self._rows = out.get('rows', [])
        columns = out.get('columns')
        self.description = [(c, None, None, None, None, None, None) for c in columns] if columns else None
        self.rowcount = out.get('rowcount', 1)

    def fetchall(self):
        return self._rows

    def fetchone(self):
        return self._rows[0] if self._rows else None

    def close(self):
        pass


class FakeConn:
    def __init__(self, db: FakeDB):
        self.db = db

    def cursor(self):
        return FakeCursor(self.db)

    def commit(self):
        self.db.commits += 1


def _fake_pool(db: FakeDB):
    pool = MagicMock()
    pool.acquire.side_effect = lambda: FakeConn(db)
    return pool


@pytest.fixture
def central_db(monkeypatch):
    """Real CentralConnector methods on a fake pool; st and logging mocked."""
    db = FakeDB()
    db.st = MagicMock()
    db.log_db_error = MagicMock()
    monkeypatch.setattr(CentralConnector, '_pool', _fake_pool(db))
    monkeypatch.setattr(cc_module, 'st', db.st)
    monkeypatch.setattr(cc_module, 'is_debug_enabled', lambda: False)
    monkeypatch.setattr(cc_module, 'log_db_error', db.log_db_error)
    monkeypatch.setattr(cc_module, 'log_error', MagicMock())
    return db


@pytest.fixture
def target_db(monkeypatch):
    """Real TargetConnector methods on a fake pool; st and logging mocked."""
    db = FakeDB()
    db.st = MagicMock()
    db.log_db_error = MagicMock()
    pool = _fake_pool(db)
    monkeypatch.setattr(TargetConnector, 'get_pool', lambda database_id, conn_config: pool)
    # get_connection looks the login up in the central registry when no
    # conn_config is passed (as the Tablespace Manager does)
    monkeypatch.setattr(CentralQueries, 'get_target_database', lambda database_id: {'username': 'u'})
    monkeypatch.setattr(tc_module, 'st', db.st)
    monkeypatch.setattr(tc_module, 'is_debug_enabled', lambda: False)
    monkeypatch.setattr(tc_module, 'log_db_error', db.log_db_error)
    monkeypatch.setattr(tc_module, 'log_error', MagicMock())
    return db


def _error_messages(st_mock) -> list:
    return [c.args[0] for c in st_mock.error.call_args_list]


# ============================================================================
# Connector strict mode
# ============================================================================

@pytest.mark.unit
class TestCentralConnectorStrictMode:

    ORA_942 = "ORA-00942: table or view does not exist"

    def test_query_default_returns_empty_and_shows_error(self, central_db):
        central_db.fail_on('t_missing', self.ORA_942)
        df = CentralConnector.execute_query("SELECT * FROM t_missing")
        assert isinstance(df, pd.DataFrame) and df.empty
        # One banner: a statement error is not also reported as a "connection error"
        assert _error_messages(central_db.st) == [f"Central database query error: {self.ORA_942}"]
        central_db.log_db_error.assert_called_once()

    def test_query_strict_raises_and_still_logs(self, central_db):
        central_db.fail_on('t_missing', self.ORA_942)
        with pytest.raises(oracledb.DatabaseError, match='ORA-00942'):
            CentralConnector.execute_query("SELECT * FROM t_missing", raise_on_error=True)
        central_db.st.error.assert_not_called()
        central_db.log_db_error.assert_called_once()

    def test_dml_default_returns_zero(self, central_db):
        central_db.fail_on('INSERT', self.ORA_942)
        assert CentralConnector.execute_dml("INSERT INTO t_missing VALUES (1)") == 0
        assert _error_messages(central_db.st) == [f"Central database DML error: {self.ORA_942}"]
        assert central_db.commits == 0

    def test_dml_strict_raises_without_commit(self, central_db):
        central_db.fail_on('INSERT', self.ORA_942)
        with pytest.raises(oracledb.DatabaseError, match='ORA-00942'):
            CentralConnector.execute_dml("INSERT INTO t_missing VALUES (1)", raise_on_error=True)
        central_db.st.error.assert_not_called()
        assert central_db.commits == 0
        central_db.log_db_error.assert_called_once()

    def test_plsql_default_returns_false(self, central_db):
        central_db.fail_on('BEGIN', self.ORA_942)
        assert CentralConnector.execute_plsql("BEGIN NULL; END;") is False
        assert _error_messages(central_db.st) == [
            f"Central database PL/SQL execution error: {self.ORA_942}"]

    def test_plsql_strict_raises(self, central_db):
        central_db.fail_on('BEGIN', self.ORA_942)
        with pytest.raises(oracledb.DatabaseError):
            CentralConnector.execute_plsql("BEGIN NULL; END;", raise_on_error=True)
        central_db.st.error.assert_not_called()

    def test_acquire_failure_still_reported_as_connection_error(self, central_db):
        CentralConnector._pool.acquire.side_effect = oracledb.DatabaseError("DPY-6005: cannot connect")
        with pytest.raises(oracledb.DatabaseError):
            CentralConnector.execute_dml("DELETE FROM t", raise_on_error=True)
        assert _error_messages(central_db.st) == [
            "Central database connection error: DPY-6005: cannot connect"]

    def test_strict_success_path_is_unchanged(self, central_db):
        central_db.handler = lambda sql, params: (
            {'rows': [(1,)], 'columns': ['X']} if sql.startswith('SELECT') else {'rowcount': 3})
        assert CentralConnector.execute_dml("UPDATE t SET x = 1", raise_on_error=True) == 3
        assert CentralConnector.execute_plsql("BEGIN NULL; END;", raise_on_error=True) is True
        df = CentralConnector.execute_query("SELECT 1 AS x FROM dual", raise_on_error=True)
        assert list(df['X']) == [1]
        assert central_db.commits == 2
        central_db.st.error.assert_not_called()


@pytest.mark.unit
class TestTargetConnectorStrictMode:

    ORA_1031 = "ORA-01031: insufficient privileges"

    def test_query_default_and_strict(self, target_db):
        target_db.fail_on('dba_extents', self.ORA_1031)
        assert TargetConnector.execute_query(1, "SELECT * FROM dba_extents").empty
        assert any('query error' in m for m in _error_messages(target_db.st))
        target_db.st.reset_mock()
        with pytest.raises(oracledb.DatabaseError, match='ORA-01031'):
            TargetConnector.execute_query(1, "SELECT * FROM dba_extents", raise_on_error=True)
        target_db.st.error.assert_not_called()

    def test_dml_default_and_strict(self, target_db):
        target_db.fail_on('UPDATE', self.ORA_1031)
        assert TargetConnector.execute_dml(1, "UPDATE t SET x = 1") == 0
        target_db.st.reset_mock()
        with pytest.raises(oracledb.DatabaseError):
            TargetConnector.execute_dml(1, "UPDATE t SET x = 1", raise_on_error=True)
        target_db.st.error.assert_not_called()
        assert target_db.commits == 0

    def test_plsql_default_and_strict(self, target_db):
        target_db.fail_on('BEGIN', self.ORA_1031)
        assert TargetConnector.execute_plsql(1, "BEGIN NULL; END;") is False
        target_db.st.reset_mock()
        with pytest.raises(oracledb.DatabaseError):
            TargetConnector.execute_plsql(1, "BEGIN NULL; END;", raise_on_error=True)
        target_db.st.error.assert_not_called()
        assert target_db.log_db_error.call_count == 2

    def test_strict_plsql_success_passes_binds(self, target_db):
        assert TargetConnector.execute_plsql(1, "BEGIN :a := 1; END;", {'a': 0}, raise_on_error=True) is True
        assert target_db.executed == [("BEGIN :a := 1; END;", {'a': 0})]


# ============================================================================
# Admin > SQL Patches
# ============================================================================

PATCH_SQL = """
-- three statements; the PL/SQL block fails in the tests below
ALTER TABLE t_x ADD (c1 NUMBER);

BEGIN
  UPDATE t_x SET c1 = 2;
END;
/

UPDATE t_x SET c1 = 1 WHERE c2 = 'a;b';
"""


def _history_rows(db: FakeDB) -> list:
    return [p for sql, p in db.executed if sql.startswith('INSERT INTO t_patch_history')]


@pytest.mark.unit
class TestPatchApplier:

    def test_failed_statement_records_failed_not_success(self, central_db):
        central_db.fail_on('SET c1 = 2', "ORA-00904: \"C1\": invalid identifier")

        result = page_09_admin._apply_patch('20990101-demo', PATCH_SQL)

        assert result['level'] == 'error'
        assert 'Statement 2 of 3' in result['message'] and 'ORA-00904' in result['message']
        assert '1 statement(s) before it already ran' in result['message']
        history = _history_rows(central_db)
        assert len(history) == 1
        assert history[0]['n'] == '20990101-demo' and history[0]['s'] == 'FAILED'
        assert 'ORA-00904' in history[0]['e']
        # The statement after the failure never ran
        assert not any("c2 = 'a;b'" in sql for sql, _ in central_db.executed)
        # Strict mode: the connector did not report the error itself
        assert not any('PL/SQL execution error' in m for m in _error_messages(central_db.st))

    def test_all_statements_ok_records_success(self, central_db):
        result = page_09_admin._apply_patch('20990101-demo', PATCH_SQL)

        assert result['level'] == 'success'
        history = _history_rows(central_db)
        assert history == [{'n': '20990101-demo', 's': 'SUCCESS'}]
        ran = [sql for sql, _ in central_db.executed if not sql.startswith('INSERT INTO t_patch_history')]
        assert len(ran) == 3

    def test_success_but_history_insert_fails_is_a_warning(self, central_db):
        central_db.fail_on('t_patch_history', "ORA-00942: table or view does not exist")
        result = page_09_admin._apply_patch('20990101-demo', PATCH_SQL)
        assert result['level'] == 'warning'
        assert 'applied' in result['message'] and 'T_PATCH_HISTORY' in result['message']

    def test_failure_and_history_insert_fails_says_so(self, central_db):
        central_db.fail_on('SET c1 = 2', "ORA-00904: invalid identifier")
        central_db.fail_on('t_patch_history', "ORA-00942: table or view does not exist")
        result = page_09_admin._apply_patch('20990101-demo', PATCH_SQL)
        assert result['level'] == 'error'
        assert 'could not be recorded' in result['message']

    def test_empty_patch_is_not_success(self, central_db):
        result = page_09_admin._apply_patch('20990101-empty', "-- nothing to do\n")
        assert result['level'] == 'error'
        assert _history_rows(central_db)[0]['s'] == 'FAILED'

    def test_record_patch_reports_failure(self, central_db):
        assert page_09_admin._record_patch('p', 'SUCCESS') is True
        central_db.fail_on('t_patch_history', "ORA-00942: table or view does not exist")
        assert page_09_admin._record_patch('p', 'FAILED', 'boom') is False

    def test_check_sql_error_reads_as_not_applied_without_st_error(self, central_db):
        central_db.fail_on('original_size_bytes', "ORA-00904: invalid identifier")
        # check.sql detection lives in the shared sql_patches module (also used
        # by the deployment page's Upgrade).
        assert sql_patches.check_patch_applied(
            "SELECT COUNT(*) as result FROM t WHERE original_size_bytes > 0") is False
        central_db.st.error.assert_not_called()

    def test_check_sql_detects_applied(self, central_db):
        central_db.handler = lambda sql, params: {'rows': [(1,)], 'columns': ['RESULT']}
        assert sql_patches.check_patch_applied("SELECT 1 as result FROM dual") is True


# ============================================================================
# Tablespace Manager > datafile resize
# ============================================================================

_LIT = r"'(?:[^']|'')*'"
_TOKEN = re.compile(
    rf"\s*(?:(?P<lit>{_LIT})"
    rf"|REPLACE\(\s*:(?P<rbind>\w+)\s*,\s*(?P<frm>{_LIT})\s*,\s*(?P<to>{_LIT})\s*\)"
    rf"|TO_CHAR\(\s*:(?P<cbind>\w+)\s*\)"
    rf"|(?P<cat>\|\|))",
    re.S,
)


def _unquote(literal: str) -> str:
    return literal[1:-1].replace("''", "'")


def _render_execute_immediate(plsql: str, binds: dict) -> str:
    """Evaluate the string expression given to EXECUTE IMMEDIATE, as PL/SQL would."""
    m = re.fullmatch(r"\s*BEGIN\s+EXECUTE IMMEDIATE\s+(?P<expr>.*?);\s*END;\s*", plsql, re.S)
    assert m, plsql
    expr, pos, parts = m.group('expr').strip(), 0, []
    while pos < len(expr):
        tok = _TOKEN.match(expr, pos)
        assert tok, f"unexpected PL/SQL at {expr[pos:]!r}"
        if tok['lit']:
            parts.append(_unquote(tok['lit']))
        elif tok['rbind']:
            parts.append(str(binds[tok['rbind']]).replace(_unquote(tok['frm']), _unquote(tok['to'])))
        elif tok['cbind']:
            parts.append(str(binds[tok['cbind']]))
        pos = tok.end()
    return ''.join(parts)


_VALID_RESIZE_DDL = re.compile(r"ALTER DATABASE DATAFILE '(?:[^']|'')+' RESIZE [1-9]\d*M")


@pytest.mark.unit
class TestDatafileResizeStatement:

    def test_statement_is_valid_ddl(self):
        name = '/u01/app/oracle/oradata/FREE/users01.dbf'
        plsql, binds = page_10_tablespaces._build_datafile_resize(name, 111, {name})

        assert "q'[" not in plsql and name not in plsql       # nothing interpolated
        assert binds == {'file_name': name, 'target_mb': 111}
        assert set(re.findall(r':(\w+)', plsql)) == set(binds)
        ddl = _render_execute_immediate(plsql, binds)
        assert ddl == f"ALTER DATABASE DATAFILE '{name}' RESIZE 111M"
        assert _VALID_RESIZE_DDL.fullmatch(ddl)

    def test_embedded_quote_is_doubled(self):
        name = "/u01/o'brien/users01.dbf"
        plsql, binds = page_10_tablespaces._build_datafile_resize(name, 5, [name])
        ddl = _render_execute_immediate(plsql, binds)
        assert ddl == "ALTER DATABASE DATAFILE '/u01/o''brien/users01.dbf' RESIZE 5M"
        assert _VALID_RESIZE_DDL.fullmatch(ddl)

    def test_numpy_integer_target_is_bound_as_int(self):
        import numpy as np
        _, binds = page_10_tablespaces._build_datafile_resize('/f.dbf', np.int64(7), {'/f.dbf'})
        assert binds['target_mb'] == 7 and type(binds['target_mb']) is int

    @pytest.mark.parametrize('file_name', [
        '/u01/other.dbf',                                     # not read from DBA_DATA_FILES
        "/u01/users01.dbf' RESIZE 1M; DROP TABLESPACE users --",
        None, 42, '',
    ])
    def test_unknown_file_names_rejected(self, file_name):
        with pytest.raises(ValueError, match='not a datafile'):
            page_10_tablespaces._build_datafile_resize(file_name, 10, {'/u01/users01.dbf'})

    @pytest.mark.parametrize('target_mb', [0, -5, 10.5, '10', True, None])
    def test_bad_target_sizes_rejected(self, target_mb):
        with pytest.raises(ValueError, match='invalid resize target'):
            page_10_tablespaces._build_datafile_resize('/f.dbf', target_mb, {'/f.dbf'})


DATAFILES = {
    'rows': [
        # file_id, file_name, current_bytes, hwm_bytes
        (4, '/u01/users01.dbf', 500 * MB, 100 * MB),    # resized to 111 MB
        (5, '/u01/users02.dbf', 400 * MB, 50 * MB),     # ORA-03297 -> skipped
        (6, '/u01/users03.dbf', 20 * MB, 15 * MB),      # not enough to reclaim
        (7, '/u01/users04.dbf', 300 * MB, 10 * MB),     # other error -> failed
    ],
    'columns': ['FILE_ID', 'FILE_NAME', 'CURRENT_BYTES', 'HWM_BYTES'],
}


def _datafile_handler(errors: dict):
    def handler(sql, params):
        if 'FROM dba_data_files' in sql:
            return DATAFILES
        if 'ALTER DATABASE DATAFILE' in sql:
            err = errors.get(params['file_name'])
            if err:
                raise oracledb.DatabaseError(err)
        return None
    return handler


@pytest.mark.unit
class TestShrinkTablespace:

    def test_only_real_successes_are_counted(self, target_db):
        target_db.handler = _datafile_handler({
            '/u01/users02.dbf': "ORA-03297: file contains used data beyond requested RESIZE value",
            '/u01/users04.dbf': "ORA-01031: insufficient privileges",
        })

        result = page_10_tablespaces._shrink_tablespace(1, 'USERS')

        by_file = {f['File']: f for f in result['files']}
        assert by_file['/u01/users01.dbf']['Result'] == 'Resized'
        assert by_file['/u01/users02.dbf']['Result'] == 'Skipped'
        assert 'ORA-03297' in by_file['/u01/users02.dbf']['Detail']
        assert by_file['/u01/users04.dbf']['Result'] == 'Failed'
        assert 'ORA-01031' in by_file['/u01/users04.dbf']['Detail']
        assert '/u01/users03.dbf' not in by_file
        assert result['level'] == 'warning'
        assert result['message'].startswith('1 file(s) resized, ~389 MB reclaimed')
        assert '1 skipped' in result['message'] and '1 failed' in result['message']

        resize_calls = [(sql, p) for sql, p in target_db.executed if 'ALTER DATABASE DATAFILE' in sql]
        assert [p['file_name'] for _, p in resize_calls] == [
            '/u01/users01.dbf', '/u01/users02.dbf', '/u01/users04.dbf']
        assert resize_calls[0][1] == {'file_name': '/u01/users01.dbf', 'target_mb': 111}
        # Strict mode: failures were returned to the page, not st.error'd and lost
        target_db.st.error.assert_not_called()

    def test_all_resized_is_success(self, target_db):
        target_db.handler = _datafile_handler({})
        result = page_10_tablespaces._shrink_tablespace(1, 'USERS')
        assert result['level'] == 'success'
        # 500-111 + 400-61 + 300-21
        assert result['message'] == '3 file(s) resized, ~1007 MB reclaimed'

    def test_only_ora_03297_is_a_warning_not_a_crash(self, target_db):
        msg = "ORA-03297: file contains used data beyond requested RESIZE value"
        target_db.handler = _datafile_handler({
            '/u01/users01.dbf': msg, '/u01/users02.dbf': msg, '/u01/users04.dbf': msg})
        result = page_10_tablespaces._shrink_tablespace(1, 'USERS')
        assert result['level'] == 'warning'
        assert result['message'].startswith('0 file(s) resized')
        assert {f['Result'] for f in result['files']} == {'Skipped'}

    def test_all_failed_is_an_error(self, target_db):
        msg = "ORA-01031: insufficient privileges"
        target_db.handler = _datafile_handler({
            '/u01/users01.dbf': msg, '/u01/users02.dbf': msg, '/u01/users04.dbf': msg})
        result = page_10_tablespaces._shrink_tablespace(1, 'USERS')
        assert result['level'] == 'error'
        assert '3 failed' in result['message']

    def test_datafile_query_error_is_reported(self, target_db):
        target_db.fail_on('dba_data_files', "ORA-00942: table or view does not exist")
        result = page_10_tablespaces._shrink_tablespace(1, 'USERS')
        assert result['level'] == 'error'
        assert 'Failed to query datafiles' in result['message'] and 'ORA-00942' in result['message']
        assert not any('ALTER DATABASE' in sql for sql, _ in target_db.executed)

    def test_usage_query_error_falls_back(self, target_db):
        # The primary query reads dba_extents for the HWM; the fallback does not
        target_db.handler = lambda sql, params: {
            'rows': [('USERS', 100.0, 60.0, 40.0, 60.0, 40.0, 'YES')],
            'columns': ['TABLESPACE_NAME', 'ALLOCATED_MB', 'USED_MB', 'FREE_MB',
                        'USED_PCT', 'SHRINKABLE_MB', 'CAN_SHRINK']}
        target_db.fail_on('dba_extents', "ORA-01031: insufficient privileges")
        df = page_10_tablespaces._get_tablespace_usage(1)
        assert list(df['tablespace_name']) == ['USERS']
        target_db.st.error.assert_not_called()


# ============================================================================
# CentralQueries paths that expect the connector to raise
# ============================================================================

@pytest.fixture
def registry(central_db, monkeypatch):
    monkeypatch.setattr(CentralQueries, 'ensure_connection_mode_column', lambda: True)
    monkeypatch.setattr(CentralQueries, 'invalidate_target_databases_cache', MagicMock())
    monkeypatch.setattr(TargetConnector, 'close_pool', MagicMock())
    return central_db


def _new_target():
    return {
        'database_name': 'PROD', 'display_name': 'Prod', 'db_host': 'dbhost',
        'port': 1521, 'service_name': 'FREEPDB1', 'username': 'HCC',
        'password_encrypted': 'enc', 'description': '', 'environment': 'PRODUCTION',
        'platform_type': 'STANDARD', 'connection_mode': 'NORMAL',
        'oracle_version': 'Oracle Database 23ai',
    }


@pytest.mark.unit
class TestCentralQueriesSurfaceErrors:

    def test_add_duplicate_name_gets_friendly_message(self, registry):
        registry.fail_on('INSERT INTO t_target_databases',
                         "ORA-00001: unique constraint (HCC.UNQ_DATABASE_NAME) violated")
        ok, msg, new_id = CentralQueries.add_target_database(_new_target())
        assert ok is False and new_id is None
        assert msg.startswith("A target database named 'PROD' already exists")
        assert not any('DML error' in m for m in _error_messages(registry.st))

    def test_add_other_db_error_returns_message(self, registry):
        registry.fail_on('INSERT INTO t_target_databases', "ORA-12899: value too large for column")
        ok, msg, new_id = CentralQueries.add_target_database(_new_target())
        assert ok is False and new_id is None and 'ORA-12899' in msg

    def test_add_precheck_error_falls_through_to_insert(self, registry):
        registry.handler = lambda sql, params: (
            {'rows': [(42,)], 'columns': ['DATABASE_ID']}
            if sql.strip().startswith('SELECT database_id') else None)
        registry.fail_on('is_active FROM t_target_databases', "ORA-00904: invalid identifier")
        ok, _msg, new_id = CentralQueries.add_target_database(_new_target())
        assert ok is True and new_id == 42
        assert not any('query error' in m for m in _error_messages(registry.st))

    def test_update_failure_is_not_success_and_nothing_is_half_applied(self, registry):
        registry.fail_on('UPDATE t_target_databases', "ORA-01031: insufficient privileges")
        ok, msg = CentralQueries.update_target_database(3, _new_target())
        assert ok is False and msg.startswith('Failed to update target database') and 'ORA-01031' in msg
        # The new password and the other fields are written by one statement,
        # so a failure can't leave the password changed on its own
        updates = [sql for sql, _ in registry.executed if sql.startswith('UPDATE t_target_databases')]
        assert len(updates) == 1 and 'password_encrypted = :password_encrypted' in updates[0]
        assert registry.commits == 0
        # Strict mode: the error reached the caller instead of the connector's st.error
        assert not any('DML error' in m for m in _error_messages(registry.st))

    def test_update_without_new_password_keeps_the_stored_one(self, registry):
        data = _new_target()
        del data['password_encrypted']
        ok, _msg = CentralQueries.update_target_database(3, data)
        assert ok is True
        (sql, params), = [(s, p) for s, p in registry.executed if s.startswith('UPDATE t_target_databases')]
        assert 'password_encrypted' not in sql and 'password_encrypted' not in params

    def test_update_unknown_target_is_not_success(self, registry):
        registry.handler = lambda sql, params: (
            {'rowcount': 0} if sql.strip().startswith('UPDATE t_target_databases') else None)
        ok, msg = CentralQueries.update_target_database(99, _new_target())
        assert ok is False and 'not found' in msg

    def test_set_default_strategy_clear_failure_is_not_success(self, registry, monkeypatch):
        monkeypatch.setattr('hcc_advisor.utils.central_queries.log_error', MagicMock())
        registry.fail_on("WHERE is_default = 'Y'", "ORA-00054: resource busy")
        ok, msg = CentralQueries.set_default_strategy(2)
        assert ok is False and 'ORA-00054' in msg
        assert not any('strategy_id = :strategy_id' in sql for sql, _ in registry.executed)
