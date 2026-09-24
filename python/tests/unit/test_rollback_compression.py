"""
Unit tests for compression rollback (History page) and the Index Manager
rebuild job: rollback moves only the compressed segment (table / partition /
subpartition), rebuilds only that segment's unusable index structures, rejects
unsafe identifiers and Oracle-maintained schemas, and records the outcome on
the history row by HISTORY_ID. The target and central connectors are mocked.
"""
import re
from pathlib import Path
from unittest.mock import patch

import pandas as pd
import pytest

from hcc_advisor.utils.central_connector import CentralConnector
from hcc_advisor.utils.target_connector import TargetConnector
from hcc_advisor.utils.target_queries import TargetQueries, rollback_block_reason
from hcc_advisor.views import page_04_history, page_11_indexes


CENTRAL_SCHEMA = Path(__file__).resolve().parents[3] / 'sql' / 'central' / '01_central_schema.sql'

INDEX_COLS = ['INDEX_OWNER', 'INDEX_NAME', 'REBUILD_LEVEL', 'SEGMENT_NAME']
OPEN_ROW_COLS = ['HISTORY_ID', 'OPERATION_STATUS', 'PARTITION_NAME', 'SUBPARTITION_NAME']


def _binds(sql: str) -> set:
    """Named bind placeholders used in a SQL statement."""
    return set(re.findall(r':(\w+)', sql))


def _history_row(status='SUCCESS', rollback_status=None, object_type='TABLE',
                 compression='OLTP') -> pd.DataFrame:
    return pd.DataFrame([{
        'OPERATION_STATUS': status, 'ROLLBACK_STATUS': rollback_status,
        'OBJECT_TYPE': object_type, 'COMPRESSION_TYPE_APPLIED': compression,
    }])


class _Recorder:
    """Patches the connectors and records every statement sent to them."""

    def __init__(self, index_rows=None, history=None, plsql_ok=True, open_rows=None):
        self.plsql = []            # PL/SQL blocks sent to the target
        self.target_queries = []   # (sql, params) sent to the target
        self.central_dml = []      # (sql, params) sent to central
        self.central_queries = []  # (sql, params) sent to central
        self._index_df = pd.DataFrame(index_rows or [], columns=INDEX_COLS)
        self._history = history if history is not None else _history_row()
        self._plsql_ok = plsql_ok
        # QUEUED / IN_PROGRESS rows of the table (TargetQueries._overlapping_open_row)
        self._open_rows = pd.DataFrame(open_rows or [], columns=OPEN_ROW_COLS)

    def _execute_plsql(self, database_id, block, *a, **k):
        self.plsql.append(block)
        ok = self._plsql_ok
        return ok(block) if callable(ok) else ok

    def _target_query(self, database_id, sql, params=None, *a, **k):
        self.target_queries.append((sql, params))
        return self._index_df

    def _central_dml(self, sql, params=None, *a, **k):
        self.central_dml.append((sql, params))
        return 1

    def _central_query(self, sql, params=None, *a, **k):
        self.central_queries.append((sql, params))
        if "operation_status IN ('QUEUED', 'IN_PROGRESS')" in sql:
            return self._open_rows
        return self._history

    @property
    def history_checks(self):
        return [(s, p) for s, p in self.central_queries if 'hid' in (p or {})]

    def __enter__(self):
        self._patches = [
            patch.object(TargetConnector, 'execute_plsql', side_effect=self._execute_plsql),
            patch.object(TargetConnector, 'execute_query', side_effect=self._target_query),
            patch.object(CentralConnector, 'execute_dml', side_effect=self._central_dml),
            patch.object(CentralConnector, 'execute_query', side_effect=self._central_query),
        ]
        for p in self._patches:
            p.start()
        return self

    def __exit__(self, *exc):
        for p in self._patches:
            p.stop()

    @property
    def move_ddl(self) -> str:
        return self.plsql[0]

    @property
    def history_updates(self):
        return [(s, p) for s, p in self.central_dml if 't_compression_history' in s]


# ============================================================================
# Rollback DDL: table vs partition vs subpartition
# ============================================================================

@pytest.mark.unit
class TestRollbackDDL:

    def test_table_rollback_moves_whole_table(self):
        with _Recorder() as rec:
            res = TargetQueries.rollback_compression(7, 'SCOTT', 'SALES', parallel_degree=8)
        assert res['success'] is True
        assert "ALTER TABLE SCOTT.SALES\nMOVE NOCOMPRESS\nONLINE PARALLEL 8" in rec.move_ddl
        assert 'PARTITION' not in rec.move_ddl
        _, binds = rec.target_queries[0]
        assert binds == {'o': 'SCOTT', 't': 'SALES', 'p': None, 'sp': None}

    def test_partition_rollback_moves_only_that_partition(self):
        with _Recorder() as rec:
            res = TargetQueries.rollback_compression(7, 'SCOTT', 'SALES', 'P2024',
                                                     parallel_degree=4)
        assert res['success'] is True
        assert "MOVE PARTITION P2024\nNOCOMPRESS\nONLINE PARALLEL 4" in rec.move_ddl
        assert 'MOVE NOCOMPRESS' not in rec.move_ddl   # never the whole table
        _, binds = rec.target_queries[0]
        assert binds == {'o': 'SCOTT', 't': 'SALES', 'p': 'P2024', 'sp': None}

    def test_subpartition_rollback_moves_only_that_subpartition(self):
        with _Recorder() as rec:
            res = TargetQueries.rollback_compression(
                7, 'SCOTT', 'SALES', partition_name='P2024', subpartition_name='P2024_SP1')
        assert res['success'] is True
        assert "MOVE SUBPARTITION P2024_SP1\nNOCOMPRESS" in rec.move_ddl
        assert 'MOVE PARTITION' not in rec.move_ddl
        _, binds = rec.target_queries[0]
        # the parent's local index partitions are untouched by a subpartition MOVE
        assert binds == {'o': 'SCOTT', 't': 'SALES', 'p': None, 'sp': 'P2024_SP1'}

    @pytest.mark.parametrize('blank', [None, float('nan'), '', 'None'])
    def test_blank_partition_means_table(self, blank):
        with _Recorder() as rec:
            TargetQueries.rollback_compression(7, 'SCOTT', 'SALES', blank, subpartition_name=blank)
        assert 'MOVE NOCOMPRESS' in rec.move_ddl

    def test_unusable_index_query_binds_match_params(self):
        assert _binds(TargetQueries._ROLLBACK_UNUSABLE_INDEXES_SQL) == {'o', 't', 'p', 'sp'}

    def test_index_rebuilds_are_scoped_statements(self):
        rows = [
            ['SCOTT', 'SALES_GIX', 'INDEX', None],
            ['SCOTT', 'SALES_LIX', 'PARTITION', 'SYS_P101'],
            ['IDXOWN', 'SALES_CLIX', 'SUBPARTITION', 'SYS_SUBP7'],
        ]
        with _Recorder(index_rows=rows) as rec:
            res = TargetQueries.rollback_compression(7, 'SCOTT', 'SALES', 'P1', parallel_degree=2)
        rebuilds = rec.plsql[1:]
        assert rebuilds == [
            "BEGIN EXECUTE IMMEDIATE 'ALTER INDEX SCOTT.SALES_GIX REBUILD ONLINE PARALLEL 2'; END;",
            "BEGIN EXECUTE IMMEDIATE 'ALTER INDEX SCOTT.SALES_LIX REBUILD PARTITION SYS_P101 ONLINE PARALLEL 2'; END;",
            "BEGIN EXECUTE IMMEDIATE 'ALTER INDEX IDXOWN.SALES_CLIX REBUILD SUBPARTITION SYS_SUBP7 ONLINE PARALLEL 2'; END;",
        ]
        assert res['index_failures'] == []
        assert '3 index structure(s) rebuilt' in res['message']

    def test_unsafe_index_identifier_is_skipped_not_executed(self):
        rows = [
            ['SCOTT', "X' ; DROP TABLE T; --", 'INDEX', None],
            ['SCOTT', 'SALES_LIX', 'PARTITION', 'P1 PARALLEL 1; x'],
            ['SCOTT', 'GOOD_IX', 'INDEX', None],
        ]
        with _Recorder(index_rows=rows) as rec:
            res = TargetQueries.rollback_compression(7, 'SCOTT', 'SALES', 'P1')
        assert res['success'] is True
        assert len(rec.plsql) == 2   # MOVE + the one valid rebuild
        assert 'GOOD_IX' in rec.plsql[1]
        assert not any('DROP' in b or 'x' in b.split('PARALLEL')[-1] for b in rec.plsql)
        assert len(res['index_failures']) == 2


# ============================================================================
# Validation: injection-style identifiers, protected schemas, DOP
# ============================================================================

@pytest.mark.unit
class TestRollbackValidation:

    @pytest.mark.parametrize('owner, table, part, sub', [
        ("SCOTT; DROP USER X", 'SALES', None, None),
        ('SCOTT', "SALES]'; END; BEGIN NULL", None, None),
        ('SCOTT', 'SALES', 'P1 NOCOMPRESS; --', None),
        ('SCOTT', 'SALES', None, 'SP1\n'),
        ('SCOTT', 'SALES', None, '"QUOTED"'),
        ('SCOTT', 'SALES.X', None, None),
    ])
    def test_injection_identifiers_rejected(self, owner, table, part, sub):
        with _Recorder() as rec:
            res = TargetQueries.rollback_compression(
                7, owner, table, part, subpartition_name=sub, history_id=11)
        assert res['success'] is False
        assert 'Invalid Oracle' in res['error']
        assert rec.plsql == [] and rec.central_dml == [] and rec.central_queries == []

    @pytest.mark.parametrize('owner', ['SYS', 'system', 'AUDSYS', 'XDB'])
    def test_oracle_maintained_schema_refused(self, owner):
        with _Recorder() as rec:
            res = TargetQueries.rollback_compression(7, owner, 'OBJ$')
        assert res['success'] is False
        assert 'Oracle-maintained' in res['error']
        assert rec.plsql == []

    @pytest.mark.parametrize('dop', [0, 129, -1, '4; DROP', None, float('nan')])
    def test_parallel_degree_bounded(self, dop):
        with _Recorder() as rec:
            res = TargetQueries.rollback_compression(7, 'SCOTT', 'SALES', parallel_degree=dop)
        assert res['success'] is False
        assert 'parallel_degree' in res['error']
        assert rec.plsql == []


# ============================================================================
# History bookkeeping (by HISTORY_ID) and eligibility
# ============================================================================

def _allowed_operation_statuses() -> set:
    ddl = CENTRAL_SCHEMA.read_text()
    m = re.search(r'CHK_HISTORY_OPERATION_STATUS CHECK \(\s*OPERATION_STATUS IN \(([^)]*)\)', ddl)
    return set(re.findall(r"'([A-Z_]+)'", m.group(1)))


@pytest.mark.unit
class TestRollbackHistory:

    def test_success_recorded_by_history_id(self):
        with _Recorder() as rec:
            res = TargetQueries.rollback_compression(7, 'SCOTT', 'SALES', 'P1', history_id=42)
        assert res['success'] is True
        # pre-check is keyed on the exact row + object
        chk_sql, chk_params = rec.central_queries[0]
        assert chk_params['hid'] == 42 and chk_params['db'] == 7 and chk_params['p'] == 'P1'
        assert _binds(chk_sql) == set(chk_params)
        (sql, params), = rec.history_updates
        assert 'WHERE history_id = :hid' in sql
        assert 'owner' not in sql.lower().split('where', 1)[1]
        assert _binds(sql) == set(params)
        assert params == {'rolled_back': 1, 'rb_status': 'ROLLED_BACK', 'msg': None, 'hid': 42}

    def test_status_written_is_allowed_by_check_constraint(self):
        allowed = _allowed_operation_statuses()
        assert 'ROLLED_BACK' in allowed
        with _Recorder() as rec:
            TargetQueries.rollback_compression(7, 'SCOTT', 'SALES', history_id=42)
        (sql, _), = rec.history_updates
        written = set(re.findall(r"THEN '([A-Z_]+)'", sql.split('rollback_possible')[0]))
        assert written and written <= allowed

    def test_index_failures_recorded_as_partial(self):
        rows = [['SCOTT', 'IX1', 'INDEX', None]]
        fail_rebuilds = lambda block: 'ALTER INDEX' not in block
        with _Recorder(index_rows=rows, plsql_ok=fail_rebuilds) as rec:
            res = TargetQueries.rollback_compression(7, 'SCOTT', 'SALES', history_id=42)
        assert res['success'] is True and res['index_failures'] == ['SCOTT.IX1']
        (_, params), = rec.history_updates
        assert params['rolled_back'] == 1
        assert params['rb_status'] == 'ROLLED_BACK_INDEX_ERRORS'
        assert 'SCOTT.IX1' in params['msg']

    def test_ddl_failure_recorded_and_row_stays_retryable(self):
        with _Recorder(plsql_ok=False) as rec:
            res = TargetQueries.rollback_compression(7, 'SCOTT', 'SALES', history_id=42)
        assert res['success'] is False
        assert rec.target_queries == []   # no index rebuild after a failed MOVE
        (_, params), = rec.history_updates
        assert params['rolled_back'] == 0 and params['rb_status'] == 'FAILED'
        assert params['msg'].startswith('Rollback failed')

    def test_no_history_id_writes_no_history(self):
        with _Recorder() as rec:
            TargetQueries.rollback_compression(7, 'SCOTT', 'SALES')
        assert rec.history_updates == [] and rec.history_checks == []
        # the only central read: the queue check every rollback makes
        (sql, params), = rec.central_queries
        assert "operation_status IN ('QUEUED', 'IN_PROGRESS')" in sql
        assert params == {'db': 7, 'o': 'SCOTT', 't': 'SALES'}

    @pytest.mark.parametrize('history', [
        _history_row(status='ROLLED_BACK'),
        _history_row(rollback_status='ROLLED_BACK'),   # legacy rows
        _history_row(status='FAILED'),
        _history_row(object_type='INDEX'),
        _history_row(compression='NONE'),
        pd.DataFrame(),                                 # row not found / mismatched
    ])
    def test_ineligible_history_row_refused_before_ddl(self, history):
        with _Recorder(history=history) as rec:
            res = TargetQueries.rollback_compression(7, 'SCOTT', 'SALES', history_id=42)
        assert res['success'] is False
        assert rec.plsql == [] and rec.history_updates == []

    def test_analysis_update_scoped_to_segment(self):
        with _Recorder() as rec:
            TargetQueries.rollback_compression(7, 'SCOTT', 'SALES', 'P1', subpartition_name='SP1')
        (sql, params), = [(s, p) for s, p in rec.central_dml if 't_compression_analysis' in s]
        assert _binds(sql) == set(params)
        assert params == {'db': 7, 'o': 'SCOTT', 't': 'SALES', 'p': 'P1', 'sp': 'SP1'}


@pytest.mark.unit
class TestRollbackEligibility:

    @pytest.mark.parametrize('args, blocked', [
        (('SUCCESS', None, 'TABLE', 'OLTP'), False),
        (('SUCCESS', 'FAILED', 'PARTITION', 'QUERY HIGH'), False),   # retry allowed
        (('SUCCESS', None, 'SUBPARTITION', 'BASIC'), False),
        (('SUCCESS', float('nan'), float('nan'), 'OLTP'), False),
        (('ROLLED_BACK', 'ROLLED_BACK', 'TABLE', 'OLTP'), True),
        (('SUCCESS', 'ROLLED_BACK', 'TABLE', 'OLTP'), True),
        (('IN_PROGRESS', None, 'TABLE', 'OLTP'), True),
        (('FAILED', None, 'TABLE', 'OLTP'), True),
        (('SUCCESS', None, 'LOB', 'OLTP'), True),
        (('SUCCESS', None, 'TABLE', 'NONE'), True),
    ])
    def test_rollback_block_reason(self, args, blocked):
        assert (rollback_block_reason(*args) is not None) is blocked

    def test_page_uses_row_database_and_history_ids(self):
        row = pd.Series({'execution_id': 5, 'database_id': 3, 'status': 'SUCCESS',
                         'rollback_status': None, 'object_type': 'PARTITION',
                         'strategy': 'OLTP', 'table_owner': 'SCOTT', 'table_name': 'SALES',
                         'partition_name': 'P1', 'subpartition_name': None})
        assert page_04_history._rollback_block_reason(row) is None
        assert page_04_history._rollback_object_label(row) == 'SCOTT.SALES partition P1'
        assert 'database' in page_04_history._rollback_block_reason(
            row.drop('database_id'))
        assert 'rolled back' in page_04_history._rollback_block_reason(
            row.replace({'SUCCESS': 'ROLLED_BACK'}))


# ============================================================================
# Index Manager: rebuild job action
# ============================================================================

@pytest.mark.unit
class TestIndexRebuildJobAction:

    def test_valid_non_partitioned(self):
        action = page_11_indexes._rebuild_job_action('SCOTT', 'SALES_IX', 6)
        assert "ALTER INDEX SCOTT.SALES_IX REBUILD ONLINE PARALLEL 6" in action

    def test_valid_partitioned_quotes_dictionary_names(self):
        action = page_11_indexes._rebuild_job_action('SCOTT', 'SALES_LIX', '3', 'YES')
        assert "index_owner = 'SCOTT' AND index_name = 'SALES_LIX'" in action
        assert 'DBMS_ASSERT.ENQUOTE_NAME(p.partition_name, FALSE)' in action
        assert 'DBMS_ASSERT.ENQUOTE_NAME(sp.subpartition_name, FALSE)' in action
        assert 'ONLINE PARALLEL 3' in action

    @pytest.mark.parametrize('owner, name', [
        ("SCOTT'||x||'", 'IX'),
        ('SCOTT', "IX]'; DBMS_SCHEDULER.DROP_JOB('X'); --"),
        ('SCOTT', 'IX REBUILD'),
        ('SCOTT', 'IX\n'),
        ('', 'IX'),
        (None, 'IX'),
    ])
    def test_unsafe_identifiers_rejected(self, owner, name):
        with pytest.raises(ValueError, match='Invalid Oracle'):
            page_11_indexes._rebuild_job_action(owner, name, 4)

    def test_protected_schema_rejected(self):
        with pytest.raises(ValueError, match='Oracle-maintained'):
            page_11_indexes._rebuild_job_action('SYS', 'I_OBJ1', 4)

    @pytest.mark.parametrize('dop', [0, 129, '8; DROP', float('nan'), None])
    def test_dop_bounded(self, dop):
        with pytest.raises(ValueError, match='parallel_degree'):
            page_11_indexes._rebuild_job_action('SCOTT', 'IX', dop)

    def test_submit_refuses_without_creating_job(self):
        with patch.object(TargetConnector, 'execute_plsql') as plsql:
            res = page_11_indexes._submit_rebuild_job(1, 'SCOTT', "IX'; x", 4)
        assert res['success'] is False
        assert res['error'].startswith('Not submitted')
        plsql.assert_not_called()

    def test_submit_valid_creates_job(self):
        with patch.object(TargetConnector, 'execute_plsql', return_value=True) as plsql:
            res = page_11_indexes._submit_rebuild_job(1, 'SCOTT', 'SALES_IX', 4)
        assert res['success'] is True and res['job_name'].startswith('IDXR_SALES_IX_')
        block = plsql.call_args[0][1]
        assert 'DBMS_SCHEDULER.CREATE_JOB' in block
        assert 'ALTER INDEX SCOTT.SALES_IX REBUILD ONLINE PARALLEL 4' in block
