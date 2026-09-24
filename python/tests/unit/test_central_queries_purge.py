"""
Unit tests for CentralQueries.purge_operation_history / get_history_purge_preview
(Admin > Data Reset). The central DB is replaced by an in-memory fake
connection that records every statement, commit and rollback.
"""
import re
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import MagicMock

import numpy as np
import oracledb
import pandas as pd
import pytest

from hcc_advisor.utils import central_queries as cq_module
from hcc_advisor.utils.central_connector import CentralConnector
from hcc_advisor.utils.central_queries import CentralQueries


PURGE_ORDER = [
    't_compression_history',
    't_lob_compression_analysis',
    't_index_compression_analysis',
    't_compression_analysis',
    't_advisor_run',
]
PRESERVED = [
    't_target_databases', 't_compression_strategies', 't_strategy_rules',
    't_schema_metadata', 't_patch_history',
]


class FakeCursor:
    """Records statements; DML rowcount comes from `rowcounts` keyed by table."""

    def __init__(self, rowcounts=None, active=0, fail_on=None):
        self.statements = []          # list of (normalised_sql, params)
        self.rowcounts = rowcounts or {}
        self.active = active
        self.fail_on = fail_on
        self.rowcount = 0
        self.closed = False
        self._row = None

    def execute(self, sql, params=None):
        norm = " ".join(sql.split())
        self.statements.append((norm, params))
        if self.fail_on and self.fail_on in norm:
            raise oracledb.DatabaseError("ORA-00060: simulated failure")
        m = re.match(r"(?:DELETE FROM|UPDATE) (\w+)", norm)
        if m:
            self.rowcount = self.rowcounts.get(m.group(1), 0)
        else:
            self._row = (self.active,)
            self.rowcount = 1

    def fetchone(self):
        return self._row

    def close(self):
        self.closed = True


class FakeConn:
    def __init__(self, cursor):
        self._cursor = cursor
        self.commits = 0
        self.rollbacks = 0

    def cursor(self):
        return self._cursor

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1


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
        return conn, cursor
    return make


@pytest.fixture
def spies(monkeypatch):
    """Spy on logging and cache invalidation."""
    s = {
        'log_info': MagicMock(),
        'log_error': MagicMock(),
        'log_warning': MagicMock(),
        'invalidate': MagicMock(),
    }
    monkeypatch.setattr(cq_module, 'log_info', s['log_info'])
    monkeypatch.setattr(cq_module, 'log_error', s['log_error'])
    monkeypatch.setattr(cq_module, 'log_warning', s['log_warning'])
    monkeypatch.setattr(CentralQueries, 'invalidate_target_databases_cache', s['invalidate'])
    return s


def _dml(cursor):
    return [(sql, p) for sql, p in cursor.statements
            if sql.startswith(('DELETE', 'UPDATE', 'TRUNCATE', 'INSERT', 'MERGE'))]


# ============================================================================
# purge_operation_history
# ============================================================================

@pytest.mark.unit
class TestPurgeOperationHistory:

    def test_all_databases_runs_deletes_in_fk_order_then_commits_once(self, fake_db, spies):
        rowcounts = {'t_compression_history': 5, 't_lob_compression_analysis': 1,
                     't_index_compression_analysis': 2, 't_compression_analysis': 40,
                     't_advisor_run': 3, 't_target_databases': 2}
        conn, cur = fake_db(rowcounts=rowcounts)

        ok, msg, deleted = CentralQueries.purge_operation_history(acting_user='admin')

        assert ok is True
        # Active-operations guard first, then child -> parent deletes, then reset.
        assert cur.statements[0][0].startswith('SELECT')
        dml = _dml(cur)
        assert [s for s, _ in dml] == (
            [f"DELETE FROM {t}" for t in PURGE_ORDER]
            + ["UPDATE t_target_databases SET last_analysis_date = NULL "
               "WHERE last_analysis_date IS NOT NULL"]
        )
        assert all(p is None for _, p in cur.statements)   # unscoped: no binds
        assert conn.commits == 1 and conn.rollbacks == 0
        assert cur.closed

        assert deleted == {
            'T_COMPRESSION_HISTORY': 5, 'T_LOB_COMPRESSION_ANALYSIS': 1,
            'T_INDEX_COMPRESSION_ANALYSIS': 2, 'T_COMPRESSION_ANALYSIS': 40,
            'T_ADVISOR_RUN': 3, CentralQueries.PURGE_TARGET_RESET_KEY: 2,
        }
        assert '51' in msg
        spies['invalidate'].assert_called_once()
        spies['log_info'].assert_called_once()
        args, kwargs = spies['log_info'].call_args
        assert "'admin'" in args[0] and kwargs['acting_user'] == 'admin'

    def test_single_database_scopes_every_statement(self, fake_db, spies):
        conn, cur = fake_db()

        ok, _, _ = CentralQueries.purge_operation_history(database_id=np.int64(7))

        assert ok is True
        assert len(cur.statements) == 1 + len(PURGE_ORDER) + 1
        for sql, params in cur.statements:
            assert 'database_id = :database_id' in sql
            assert params == {'database_id': 7}
            assert type(params['database_id']) is int      # numpy ids -> plain int
        # Guard query scopes both subqueries.
        assert cur.statements[0][0].count(':database_id') == 2
        for sql, _ in _dml(cur):
            if sql.startswith('DELETE'):
                assert sql.endswith('WHERE database_id = :database_id')
        assert _dml(cur)[-1][0] == (
            "UPDATE t_target_databases SET last_analysis_date = NULL "
            "WHERE last_analysis_date IS NOT NULL AND database_id = :database_id"
        )
        assert conn.commits == 1

    def test_database_id_zero_is_not_treated_as_all(self, fake_db, spies):
        _, cur = fake_db()
        CentralQueries.purge_operation_history(database_id=0)
        for sql, params in cur.statements:
            assert 'database_id = :database_id' in sql
            assert params == {'database_id': 0}

    @pytest.mark.parametrize('database_id', [None, 3])
    def test_preserved_tables_are_never_deleted_or_truncated(self, fake_db, spies, database_id):
        _, cur = fake_db()
        CentralQueries.purge_operation_history(database_id=database_id, include_active=True)

        for sql, _ in cur.statements:
            lowered = sql.lower()
            assert 'truncate' not in lowered and 'drop ' not in lowered
            for table in ('t_compression_strategies', 't_strategy_rules',
                          't_schema_metadata', 't_patch_history'):
                assert table not in lowered
        target_stmts = [s for s, _ in cur.statements if 't_target_databases' in s.lower()]
        assert len(target_stmts) == 1
        assert target_stmts[0].startswith(
            'UPDATE t_target_databases SET last_analysis_date = NULL WHERE')

    def test_failure_rolls_back_and_stops(self, fake_db, spies):
        conn, cur = fake_db(fail_on='DELETE FROM t_compression_analysis')

        ok, msg, deleted = CentralQueries.purge_operation_history(acting_user='admin')

        assert ok is False and deleted == {}
        assert 'rolled back' in msg
        assert conn.rollbacks == 1 and conn.commits == 0
        assert cur.closed
        executed = [s for s, _ in _dml(cur)]
        assert 'DELETE FROM t_advisor_run' not in executed
        assert not any(s.startswith('UPDATE') for s in executed)
        spies['log_error'].assert_called_once()
        spies['log_info'].assert_not_called()
        spies['invalidate'].assert_not_called()

    def test_refuses_when_active_operations_exist(self, fake_db, spies):
        conn, cur = fake_db(active=4)

        ok, msg, deleted = CentralQueries.purge_operation_history(database_id=2)

        assert ok is False and deleted == {}
        assert 'refused' in msg.lower() and '4' in msg
        assert _dml(cur) == []
        assert conn.commits == 0 and conn.rollbacks == 1
        guard = cur.statements[0][0]
        assert "operation_status IN ('QUEUED', 'IN_PROGRESS')" in guard
        assert "run_status = 'RUNNING'" in guard
        spies['log_info'].assert_not_called()

    def test_include_active_skips_guard_and_purges(self, fake_db, spies):
        conn, cur = fake_db(active=4)

        ok, _, _ = CentralQueries.purge_operation_history(include_active=True)

        assert ok is True
        assert not any(s.startswith('SELECT') for s, _ in cur.statements)
        assert [s for s, _ in _dml(cur)][:len(PURGE_ORDER)] == [
            f"DELETE FROM {t}" for t in PURGE_ORDER]
        assert conn.commits == 1


# ============================================================================
# get_history_purge_preview
# ============================================================================

def _preview_df(**overrides):
    values = {
        'T_COMPRESSION_HISTORY': 10, 'T_LOB_COMPRESSION_ANALYSIS': 0,
        'T_INDEX_COMPRESSION_ANALYSIS': 4, 'T_COMPRESSION_ANALYSIS': 99,
        'T_ADVISOR_RUN': 6, 'ACTIVE_QUEUED': 2, 'ACTIVE_IN_PROGRESS': 1,
        'ACTIVE_RUNNING_RUNS': 0, 'TARGETS_TO_RESET': 3,
    }
    values.update(overrides)
    # Oracle may return padded CHAR literals from a UNION ALL.
    return pd.DataFrame({'ITEM': [k.ljust(30) for k in values],
                         'CNT': list(values.values())})


@pytest.mark.unit
class TestHistoryPurgePreview:

    def test_parses_counts_and_active(self, monkeypatch):
        eq = MagicMock(return_value=_preview_df())
        monkeypatch.setattr(CentralConnector, 'execute_query', eq)

        preview = CentralQueries.get_history_purge_preview()

        assert list(preview['counts']) == list(CentralQueries.PURGE_HISTORY_TABLES)
        assert preview['counts']['T_COMPRESSION_ANALYSIS'] == 99
        assert preview['targets_to_reset'] == 3
        assert preview['active'] == {'queued': 2, 'in_progress': 1, 'running_runs': 0}
        query, params = eq.call_args[0]
        assert ':database_id' not in query and params is None
        # Read-only: counting must never modify anything.
        assert not re.search(r'\b(DELETE|UPDATE|TRUNCATE|INSERT|MERGE)\b', query, re.I)

    def test_scoped_to_one_database(self, monkeypatch):
        eq = MagicMock(return_value=_preview_df())
        monkeypatch.setattr(CentralConnector, 'execute_query', eq)

        CentralQueries.get_history_purge_preview(database_id=np.int64(5))

        query, params = eq.call_args[0]
        assert params == {'database_id': 5}
        branches = query.split('UNION ALL')
        assert len(branches) == len(CentralQueries.PURGE_HISTORY_TABLES) + 4
        assert all('database_id = :database_id' in b for b in branches)

    @pytest.mark.parametrize('df', [pd.DataFrame(), _preview_df().iloc[:-1]])
    def test_returns_none_when_counts_unavailable(self, monkeypatch, df):
        monkeypatch.setattr(CentralConnector, 'execute_query', MagicMock(return_value=df))
        assert CentralQueries.get_history_purge_preview() is None


# ============================================================================
# Table classification vs. the actual central schema
# ============================================================================

_REPO_ROOT = Path(__file__).resolve().parents[3]
_SQL_FILES = sorted((_REPO_ROOT / 'sql' / 'central').glob('*.sql')) + \
    sorted((_REPO_ROOT / 'sql' / 'patches').glob('*/patch.sql'))


@pytest.mark.unit
@pytest.mark.skipif(not _SQL_FILES, reason="central schema SQL not found")
class TestPurgeTableClassification:

    def _schema_text(self):
        return "\n".join(p.read_text() for p in _SQL_FILES)

    def test_every_central_table_is_classified(self):
        created = {t.upper() for t in re.findall(
            r"CREATE\s+TABLE\s+(\w+)", self._schema_text(), re.I)}
        classified = set(CentralQueries.PURGE_HISTORY_TABLES) | set(
            CentralQueries.PURGE_PRESERVED_TABLES)
        assert created, "no CREATE TABLE statements parsed"
        assert created <= classified, (
            f"unclassified central tables: {sorted(created - classified)}")
        assert not set(CentralQueries.PURGE_HISTORY_TABLES) & set(
            CentralQueries.PURGE_PRESERVED_TABLES)

    def test_purge_order_deletes_children_before_parents(self):
        order = list(CentralQueries.PURGE_HISTORY_TABLES)
        preserved = set(CentralQueries.PURGE_PRESERVED_TABLES)
        current = None
        fks = []
        for m in re.finditer(r"(?:CREATE|ALTER)\s+TABLE\s+(\w+)|REFERENCES\s+(\w+)",
                             self._schema_text(), re.I):
            if m.group(1):
                current = m.group(1).upper()
            elif current:
                fks.append((current, m.group(2).upper()))
        assert fks, "no foreign keys parsed"
        for child, parent in fks:
            if child in order and parent in order and child != parent:
                assert order.index(child) < order.index(parent), (child, parent)
            # A preserved table must not depend on purged rows.
            if child in preserved:
                assert parent not in order, (child, parent)
