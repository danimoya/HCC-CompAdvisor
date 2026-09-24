"""
Unit tests for generated-id handling of central history / run rows:

- CentralConnector.execute_dml_returning returns the RETURNING INTO out-bind.
- store_compression_history / store_advisor_run return the id of the row they
  inserted (RETURNING ... INTO) instead of re-selecting MAX(id).
- execute_compression (and batch_execute) update the history row by its
  history_id, never by owner+table alone.

The central DB is replaced by fakes that record every statement and bind.
"""
import re
from contextlib import contextmanager
from unittest.mock import MagicMock, patch

import oracledb
import pandas as pd
import pytest

from hcc_advisor.utils import central_connector as cc_module
from hcc_advisor.utils.central_connector import CentralConnector
from hcc_advisor.utils.central_queries import CentralQueries
from hcc_advisor.utils.target_connector import TargetConnector
from hcc_advisor.utils.target_queries import TargetQueries


def _norm(sql):
    return " ".join(sql.split())


def _placeholders(sql):
    return set(re.findall(r":(\w+)", sql))


class FakeVar:
    def __init__(self, value):
        self._value = value

    def getvalue(self, pos=0):
        return self._value


class FakeCursor:
    """Records statements. Like python-oracledb, rejects binds that don't match
    the statement's placeholders (DPY-4008 / DPY-4010)."""

    def __init__(self, returned=None, fail=False):
        self.statements = []
        self.returned = returned
        self.fail = fail
        self.rowcount = 0
        self.closed = False
        self.vars = []

    def var(self, typ, *args, **kwargs):
        v = FakeVar(self.returned)
        v.type = typ
        self.vars.append(v)
        return v

    def execute(self, sql, params=None):
        self.statements.append((_norm(sql), params))
        if self.fail:
            raise oracledb.DatabaseError("ORA-00001: simulated failure")
        assert _placeholders(sql) == set(params or {}), \
            f"bind mismatch: sql={_placeholders(sql)} binds={set(params or {})}"
        self.rowcount = 1

    def fetchall(self):
        return []

    def close(self):
        self.closed = True


class FakeConn:
    def __init__(self, cursor):
        self._cursor = cursor
        self.commits = 0

    def cursor(self):
        return self._cursor

    def commit(self):
        self.commits += 1


@pytest.fixture
def fake_db(monkeypatch):
    """Factory: install a fake central connection, return (conn, cursor)."""
    def make(**cursor_kwargs):
        cursor = FakeCursor(**cursor_kwargs)
        conn = FakeConn(cursor)

        @contextmanager
        def _get_connection():
            yield conn

        monkeypatch.setattr(CentralConnector, 'get_connection', _get_connection)
        monkeypatch.setattr(cc_module.st, 'error', MagicMock())
        return conn, cursor
    return make


# ============================================================================
# CentralConnector.execute_dml_returning
# ============================================================================

@pytest.mark.unit
class TestExecuteDmlReturning:

    SQL = "INSERT INTO t_foo (name) VALUES (:name) RETURNING foo_id INTO :new_id"

    def test_returns_out_bind_value_and_commits(self, fake_db):
        conn, cur = fake_db(returned=[42])
        params = {'name': 'x'}

        assert CentralConnector.execute_dml_returning(self.SQL, params) == 42

        sql, binds = cur.statements[0]
        assert binds['name'] == 'x'
        assert binds['new_id'] is cur.vars[0]
        assert cur.vars[0].type is oracledb.NUMBER
        assert params == {'name': 'x'}          # caller's dict is not mutated
        assert conn.commits == 1 and cur.closed

    def test_custom_out_bind_name_and_no_commit(self, fake_db):
        conn, cur = fake_db(returned=[7])
        sql = "INSERT INTO t_foo (name) VALUES (:name) RETURNING foo_id INTO :rid"

        assert CentralConnector.execute_dml_returning(
            sql, {'name': 'x'}, out_bind='rid', commit=False) == 7
        assert 'rid' in cur.statements[0][1]
        assert conn.commits == 0

    def test_integral_float_is_returned_as_int(self, fake_db):
        fake_db(returned=[42.0])
        value = CentralConnector.execute_dml_returning(self.SQL, {'name': 'x'})
        assert value == 42 and type(value) is int

    def test_no_row_returns_none(self, fake_db):
        fake_db(returned=[])
        assert CentralConnector.execute_dml_returning(self.SQL, {'name': 'x'}) is None

    def test_database_error_returns_none(self, fake_db):
        fake_db(fail=True)
        assert CentralConnector.execute_dml_returning(self.SQL, {'name': 'x'}) is None
        cc_module.st.error.assert_called_once()


# ============================================================================
# store_compression_history / store_advisor_run
# ============================================================================

HISTORY_RECORD = {
    'owner': 'APP', 'object_name': 'ORDERS', 'object_type': 'PARTITION',
    'partition_name': 'P1', 'compression_type_applied': 'QUERY HIGH',
    'compression_clause': 'ALTER TABLE APP.ORDERS MOVE PARTITION P1',
    'execution_mode': 'ONLINE', 'parallel_degree': 4,
    'original_size_bytes': 1024, 'operation_status': 'IN_PROGRESS',
    'executed_by': 'tester',
}


@pytest.mark.unit
class TestStoreCompressionHistory:

    def test_returns_new_history_id_via_returning(self, fake_db):
        conn, cur = fake_db(returned=[555])

        assert CentralQueries.store_compression_history(3, dict(HISTORY_RECORD)) == 555

        assert len(cur.statements) == 1
        sql, binds = cur.statements[0]
        assert sql.startswith('INSERT INTO t_compression_history')
        assert sql.endswith('RETURNING history_id INTO :new_id')
        assert binds['database_id'] == 3 and binds['partition_name'] == 'P1'
        assert conn.commits == 1

    def test_failed_insert_returns_none(self, fake_db):
        fake_db(fail=True)
        assert CentralQueries.store_compression_history(3, dict(HISTORY_RECORD)) is None


@pytest.mark.unit
class TestStoreAdvisorRun:

    def test_returns_run_id_via_returning_without_max(self, fake_db):
        _, cur = fake_db(returned=[99])
        with patch.object(CentralConnector, 'execute_query') as q:
            ok, run_id = CentralQueries.store_advisor_run(5, {'run_name': 'r', 'schema_filter': 'APP'})

        assert (ok, run_id) == (True, 99)
        q.assert_not_called()                   # no follow-up SELECT MAX(run_id)
        assert len(cur.statements) == 1
        sql, binds = cur.statements[0]
        assert 'MAX(' not in sql.upper()
        assert sql.endswith('RETURNING run_id INTO :new_run_id')
        assert binds['database_id'] == 5

    def test_failed_insert_returns_false_none(self, fake_db):
        fake_db(fail=True)
        assert CentralQueries.store_advisor_run(5, {}) == (False, None)


# ============================================================================
# execute_compression / batch_execute
# ============================================================================

def _size_query(sizes):
    """Fake TargetConnector.execute_query: segment sizes per partition, no
    LOBs, no unusable indexes. `sizes` maps partition -> [before, after]."""
    calls = {}

    def _q(database_id, query, params=None):
        q = query.lower()
        if 'dba_segments' in q:
            part = (params or {}).get('partition_name')
            n = calls.get(part, 0)
            calls[part] = n + 1
            return pd.DataFrame([{'SIZE_BYTES': sizes[part][min(n, 1)]}])
        if 'all_tab_columns' in q:
            return pd.DataFrame([{'LOB_COUNT': 0}])
        return pd.DataFrame()
    return _q


def _history_updates(dml_mock):
    return [(_norm(c.args[0]), c.args[1]) for c in dml_mock.call_args_list
            if 'UPDATE t_compression_history' in c.args[0]]


def _assert_bound_exactly(sql, binds):
    assert _placeholders(sql) == set(binds), (sql, binds)


@pytest.mark.unit
class TestExecuteCompressionHistoryUpdates:

    def _run(self, store_return, plsql, partition_name=None):
        sizes = {partition_name: [1000, 400]}
        dml = MagicMock(return_value=1)
        with patch.object(CentralQueries, 'store_compression_history',
                          return_value=store_return) as store, \
                patch.object(CentralConnector, 'execute_dml', dml), \
                patch.object(TargetConnector, 'execute_query', side_effect=_size_query(sizes)), \
                patch.object(TargetConnector, 'execute_plsql', **plsql):
            res = TargetQueries.execute_compression(
                7, 'APP', 'ORDERS', 'QUERY HIGH',
                partition_name=partition_name, dry_run=False)
        return res, store, _history_updates(dml)

    def test_success_updates_by_history_id(self):
        res, store, updates = self._run(555, {'return_value': True}, partition_name='P1')

        assert res['success'] is True
        store.assert_called_once()
        assert store.call_args.args[1]['partition_name'] == 'P1'
        assert len(updates) == 1
        sql, binds = updates[0]
        assert "SET operation_status = 'SUCCESS'" in sql
        assert sql.endswith('WHERE history_id = :hist_id')
        assert 'owner' not in sql.lower().split('where')[1]
        assert binds['hist_id'] == 555
        assert binds['comp_size'] == 400 and binds['ratio'] == 2.5
        _assert_bound_exactly(sql, binds)

    def test_ddl_failure_updates_by_history_id(self):
        res, _, updates = self._run(556, {'return_value': False})

        assert 'error' in res
        assert len(updates) == 1
        sql, binds = updates[0]
        assert "SET operation_status = 'FAILED'" in sql
        assert sql.endswith('WHERE history_id = :hist_id')
        assert binds['hist_id'] == 556
        _assert_bound_exactly(sql, binds)

    def test_exception_updates_by_history_id(self):
        res, _, updates = self._run(557, {'side_effect': RuntimeError('ORA-01652 boom')})

        assert res == {'error': 'ORA-01652 boom'}
        assert len(updates) == 1
        sql, binds = updates[0]
        assert "SET operation_status = 'FAILED'" in sql
        assert sql.endswith('WHERE history_id = :hist_id')
        assert binds == {'err': 'ORA-01652 boom', 'hist_id': 557}

    def test_without_history_id_falls_back_to_database_and_partition(self):
        res, _, updates = self._run(None, {'return_value': True}, partition_name='P1')

        assert res['success'] is True
        sql, binds = updates[0]
        where = sql.split('WHERE', 1)[1]
        assert 'history_id' not in where
        assert 'database_id = :hist_db' in where
        assert "NVL(partition_name, '~') = NVL(:hist_part, '~')" in where
        assert 'subpartition_name IS NULL' in where
        assert 'compression_clause = :hist_clause' in where    # not a scheduler job row
        assert binds['hist_db'] == 7 and binds['hist_part'] == 'P1'
        assert binds['hist_owner'] == 'APP' and binds['hist_tbl'] == 'ORDERS'
        assert binds['hist_clause'].startswith('ALTER TABLE APP.ORDERS')
        _assert_bound_exactly(sql, binds)

    def test_batch_partitions_of_one_table_update_their_own_rows(self):
        """Concurrent partitions of the same table used to race for the first
        IN_PROGRESS owner+table row; each must now update its own history_id."""
        ids = {'P1': 101, 'P2': 102, 'P3': 103}
        sizes = {'P1': [1000, 500], 'P2': [2000, 500], 'P3': [3000, 1000]}
        dml = MagicMock(return_value=1)
        with patch.object(CentralQueries, 'store_compression_history',
                          side_effect=lambda db, rec: ids[rec['partition_name']]), \
                patch.object(CentralConnector, 'execute_dml', dml), \
                patch.object(TargetConnector, 'execute_query', side_effect=_size_query(sizes)), \
                patch.object(TargetConnector, 'execute_plsql', return_value=True):
            out = TargetQueries.batch_execute(
                7, [{'owner': 'APP', 'table_name': 'ORDERS', 'compression_type': 'QUERY HIGH',
                     'partition_name': p} for p in ids],
                dry_run=False, concurrency=3)

        assert out['success'] == 3
        updates = _history_updates(dml)
        assert len(updates) == 3
        by_id = {b['hist_id']: b for _, b in updates}
        assert set(by_id) == set(ids.values())
        for part, hid in ids.items():
            assert by_id[hid]['comp_size'] == sizes[part][1]
        for sql, _ in updates:
            assert sql.endswith('WHERE history_id = :hist_id')
