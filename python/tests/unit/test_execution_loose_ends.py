"""
Unit tests for loose ends of the execution paths:

- a subpartition recommendation run synchronously (execute_compression,
  batch_execute, the Execute Compression and Recommendations pages, the DDL
  preview) moves, measures, checks and records that subpartition, not its
  parent partition;
- queued rows record EXECUTION_MODE (ONLINE / OFFLINE) from the target's
  version and object level, at enqueue and again when a row is claimed;
- rollback_compression refuses to move a segment that a QUEUED / IN_PROGRESS
  row overlaps (the same segment, the whole table, a parent partition);
- the sidebar target selector keys on database_id, and a display name another
  active target uses (case-insensitively) is refused on add / edit;
- the enqueue / direct-run race on UNQ_HISTORY_OPEN_SEGMENT shows no raw
  ORA-00001 banner (CentralConnector.execute_dml_returning raise_on_error);
- the legacy migration imports extra open rows of a segment as FAILED instead
  of failing on the unique index.

No database: the central and target connectors are faked (see
test_scheduler_queue.FakeCentral / FakeTarget and test_rollback_compression).
"""
from contextlib import contextmanager
from datetime import datetime
from unittest.mock import MagicMock, patch

import oracledb
import pandas as pd
import pytest
import streamlit as st
from streamlit.testing.v1 import AppTest
from streamlit.testing.v1.element_tree import Selectbox

from hcc_advisor.auth import ROLE_ADMIN
from hcc_advisor.utils import central_connector as cc_module
from hcc_advisor.utils import central_queries as cq_module
from hcc_advisor.utils import migration
from hcc_advisor.utils import target_queries as tq
from hcc_advisor.utils.central_connector import CentralConnector
from hcc_advisor.utils.central_queries import CentralQueries, target_selector_labels
from hcc_advisor.utils.target_connector import TargetConnector
from hcc_advisor.utils.target_queries import TargetQueries
from hcc_advisor.views import page_03_execution, page_06_connections
from tests.unit.app_harness import _selectbox_index, app_shell, new_app
from tests.unit.test_rollback_compression import _Recorder
from tests.unit.test_scheduler_queue import FakeCentral, FakeTarget
from tests.unit.test_version_platform_ddl import V11_2, V12_1, V19, _target

TIMEOUT = 15  # seconds per AppTest run
DUP = 'ORA-00001: unique constraint (HCC.UNQ_HISTORY_OPEN_SEGMENT) violated'


class _Central(FakeCentral):
    """FakeCentral whose default (non-strict) execute_dml_returning shows the
    raw error banner, like CentralConnector's does."""

    def dml_returning(self, sql, params=None, out_bind='new_id', commit=True,
                      raise_on_error=False):
        try:
            return super().dml_returning(sql, params, out_bind, commit, raise_on_error=True)
        except oracledb.Error as e:
            if raise_on_error:
                raise
            cc_module.st.error(f"Central database DML error: {e}")
            return None


@pytest.fixture
def dbs(monkeypatch):
    """Fake central history table and target; st.error (shared by the
    connector and CentralQueries) spied as central.st_error."""
    central, target = _Central(), FakeTarget()
    monkeypatch.setattr(CentralConnector, 'execute_query', central.query)
    monkeypatch.setattr(CentralConnector, 'execute_dml', central.dml)
    monkeypatch.setattr(CentralConnector, 'execute_dml_returning', central.dml_returning)
    monkeypatch.setattr(CentralConnector, 'get_connection', central.connection)
    monkeypatch.setattr(TargetConnector, 'execute_query', target.query)
    monkeypatch.setattr(TargetConnector, 'execute_plsql', target.execute_plsql)
    monkeypatch.setattr(tq, '_acting_user', lambda: 'alice')
    central.st_error = MagicMock()
    assert cc_module.st is cq_module.st
    monkeypatch.setattr(cc_module.st, 'error', central.st_error)
    return central, target


def _analysis_updates(central):
    return [p for kind, s, p in central.statements
            if kind == 'dml' and s.startswith('UPDATE t_compression_analysis')]


def _index_queries(target):
    return [p for s, p in target.queries if 'FROM all_indexes' in s]


# ============================================================================
# 1. Synchronous subpartition runs
# ============================================================================

@pytest.mark.unit
class TestSynchronousSubpartition:

    def test_dry_run_ddl_moves_the_subpartition(self):
        res = TargetQueries.execute_compression(1, 'APP', 'SALES', 'OLTP', 'P1', dry_run=True,
                                                subpartition_name='SP1')
        assert res['success'] is True
        assert 'MOVE SUBPARTITION SP1' in res['ddl']
        assert 'PARTITION P1' not in res['ddl']

    def test_positional_callers_are_unchanged(self):
        res = TargetQueries.execute_compression(1, 'APP', 'SALES', 'OLTP', 'P1', True)
        assert 'MOVE PARTITION P1' in res['ddl']

    def test_live_run_moves_measures_and_records_the_subpartition(self, dbs):
        central, target = dbs
        target.sizes = {'SP1': [1000, 250]}          # DBA_SEGMENTS.PARTITION_NAME of the leaf
        res = TargetQueries.execute_compression(1, 'APP', 'SALES', 'OLTP', 'P1', dry_run=False,
                                                subpartition_name='SP1')
        assert res['success'] is True, res
        assert 'MOVE SUBPARTITION SP1' in target.plsql[0]
        assert 'MOVE PARTITION' not in target.plsql[0]

        (row,) = central.rows.values()
        assert (row['partition_name'], row['subpartition_name']) == ('P1', 'SP1')
        assert row['object_type'] == 'SUBPARTITION'
        assert row['execution_mode'] == 'ONLINE'
        assert row['operation_status'] == 'SUCCESS'
        assert row['original_size_bytes'] == 1000 and row['compressed_size_bytes'] == 250
        # before / after size of the subpartition's own segment
        assert [p['partition_name'] for p in target.size_queries()] == ['SP1', 'SP1']
        # unusable index structures: the subpartition's local ones (+ global)
        assert _index_queries(target) == [{'o': 'APP', 't': 'SALES', 'p': None, 'sp': 'SP1'}]
        (upd,) = _analysis_updates(central)
        assert (upd['part'], upd['sub']) == ('P1', 'SP1')

    def test_open_row_of_the_same_subpartition_blocks_the_run(self, dbs):
        central, target = dbs
        queued = central.add(object_name='SALES', partition_name='P1', subpartition_name='SP1',
                             operation_status='QUEUED')
        res = TargetQueries.execute_compression(1, 'APP', 'SALES', 'OLTP', 'P1', dry_run=False,
                                                subpartition_name='SP1')
        assert res['success'] is False and res['duplicate'] is True
        assert f"history_id {queued}" in res['error']
        assert 'APP.SALES subpartition SP1' in res['error']
        assert target.plsql == [] and len(central.rows) == 1

    def test_open_row_of_a_sibling_subpartition_does_not_block(self, dbs):
        central, target = dbs
        central.add(object_name='SALES', partition_name='P1', subpartition_name='SP2',
                    operation_status='IN_PROGRESS')
        res = TargetQueries.execute_compression(1, 'APP', 'SALES', 'OLTP', 'P1', dry_run=False,
                                                subpartition_name='SP1')
        assert res['success'] is True, res
        assert 'MOVE SUBPARTITION SP1' in target.plsql[0]

    @pytest.mark.parametrize('version, mode, modifier', [
        (V11_2, 'OFFLINE', 'UPDATE INDEXES PARALLEL 4'),
        (V12_1, 'ONLINE', 'ONLINE PARALLEL 4'),
    ])
    def test_subpartition_mode_follows_the_version(self, dbs, monkeypatch, version, mode, modifier):
        central, target = dbs
        _target(monkeypatch, version, 'STANDARD')
        res = TargetQueries.execute_compression(1, 'APP', 'SALES', 'OLTP', 'P1', dry_run=False,
                                                subpartition_name='SP1')
        assert res['success'] is True, res
        assert modifier in target.plsql[0]
        (row,) = central.rows.values()
        assert row['execution_mode'] == mode

    def test_local_index_subpartition_left_unusable_is_rebuilt(self, dbs, monkeypatch):
        central, target = dbs
        rows = pd.DataFrame([['APP', 'SALES_LIX', 'SUBPARTITION', 'SYS_SUBP9']],
                            columns=['INDEX_OWNER', 'INDEX_NAME', 'REBUILD_LEVEL', 'SEGMENT_NAME'])
        query = target.query

        def with_indexes(database_id, sql, params=None, **kw):
            if 'FROM all_indexes' in sql:
                target.queries.append((sql, params))
                return rows
            return query(database_id, sql, params, **kw)
        monkeypatch.setattr(TargetConnector, 'execute_query', with_indexes)
        res = TargetQueries.execute_compression(1, 'APP', 'SALES', 'OLTP', 'P1', dry_run=False,
                                                subpartition_name='SP1', parallel_degree=2)
        assert res['success'] is True and '1 indexes rebuilt' in res['message']
        assert target.plsql[1] == ("BEGIN EXECUTE IMMEDIATE 'ALTER INDEX APP.SALES_LIX "
                                   "REBUILD SUBPARTITION SYS_SUBP9 ONLINE PARALLEL 2'; END;")

    def test_batch_items_carry_the_subpartition(self):
        items = [{'owner': 'APP', 'table_name': 'SALES', 'compression_type': 'OLTP',
                  'partition_name': 'P1', 'subpartition_name': 'SP1'},
                 {'owner': 'APP', 'table_name': 'ORDERS', 'compression_type': 'OLTP'}]
        with patch.object(TargetQueries, 'execute_compression',
                          return_value={'success': True}) as ex:
            out = TargetQueries.batch_execute(1, items, dry_run=False, concurrency=2)
        subs = sorted((c.kwargs['table_name'], c.kwargs['subpartition_name'])
                      for c in ex.call_args_list)
        assert subs == [('ORDERS', None), ('SALES', 'SP1')]
        sales = next(r for r in out['results'] if r['table_name'] == 'SALES')
        assert sales['subpartition_name'] == 'SP1'

    def test_batch_dry_run_previews_the_subpartition(self):
        out = TargetQueries.batch_execute(1, [{
            'owner': 'APP', 'table_name': 'SALES', 'compression_type': 'OLTP',
            'partition_name': 'P1', 'subpartition_name': 'SP1'}], dry_run=True)
        assert 'MOVE SUBPARTITION SP1' in out['results'][0]['result']['ddl']


# ----------------------------------------------------------------------------
# Pages: Execute Compression (single / batch), Recommendations
# ----------------------------------------------------------------------------

SUB_REC = pd.DataFrame({
    'recommendation_id': [11], 'table_owner': ['APP'], 'table_name': ['SALES'],
    'partition_name': ['P1'], 'subpartition_name': ['SP1'],
    'recommended_strategy': ['OLTP'], 'savings_pct': [60.0], 'current_size_mb': [10.0],
    'estimated_size_mb': [4.0], 'estimated_rows': [1000], 'current_compression': ['NONE'],
    'compression_ratio': [2.5],
})


def _single_page():
    from hcc_advisor.views.page_03_execution import show_single_execution
    show_single_execution()


def _batch_page():
    from hcc_advisor.views.page_03_execution import show_batch_execution
    show_batch_execution()


@contextmanager
def _page03(execute_result=None):
    # "Select Table" is a format_func'd selectbox (see app_harness._selectbox_index)
    with patch.object(Selectbox, 'index', property(_selectbox_index)), \
            patch.object(CentralQueries, 'get_recommendations', side_effect=lambda **k: SUB_REC.copy()), \
            patch.object(TargetQueries, 'get_available_schemas', return_value=[]), \
            patch.object(TargetQueries, 'get_cpu_count', return_value=8), \
            patch.object(page_03_execution, 'target_ddl_info',
                         return_value={'oracle_version': V19, 'platform_type': 'STANDARD'}), \
            patch.object(TargetQueries, 'execute_compression',
                         return_value=execute_result or {'success': True, 'message': 'done'}) as ex, \
            patch.object(TargetQueries, 'batch_execute',
                         return_value={'success': 1, 'errors': 0}) as batch, \
            patch.object(TargetQueries, 'enqueue_compression_jobs',
                         return_value={'added': 1, 'duplicates': 0, 'rejected': 0,
                                       'errors': []}) as enqueue, \
            patch.object(TargetQueries, 'drain_compression_queue',
                         return_value={'submitted': 1, 'blocked': 0, 'failed': 0,
                                       'not_claimed': 0, 'waiting': 0,
                                       'skipped_databases': [], 'errors': []}):
        yield {'execute': ex, 'batch': batch, 'enqueue': enqueue}


def _operator_app(func):
    at = AppTest.from_function(func, default_timeout=TIMEOUT)
    at.session_state['authenticated'] = True
    at.session_state['role'] = 'operator'
    at.session_state['active_database_id'] = 1
    return at


def _checkbox(at, label):
    return next(c for c in at.checkbox if c.label == label)


@pytest.mark.unit
class TestExecutionPageSubpartition:

    def test_ddl_preview_shows_the_subpartition_move(self):
        with _page03():
            at = _operator_app(_single_page).run()
        assert not at.exception
        ddl = at.code[0].value
        assert 'MOVE SUBPARTITION SP1' in ddl and 'MOVE PARTITION' not in ddl
        assert ddl.rstrip().endswith('ONLINE PARALLEL 4;')

    def test_single_synchronous_run_passes_the_subpartition(self):
        with _page03() as mocks:
            at = _operator_app(_single_page).run()
            at.checkbox(key='single_dry_run').uncheck().run()
            _checkbox(at, 'Confirm Execution').check().run()
            at.checkbox(key='single_background').uncheck().run()
            at.button[0].click().run()
        assert not at.exception
        kwargs = mocks['execute'].call_args.kwargs
        assert (kwargs['partition_name'], kwargs['subpartition_name']) == ('P1', 'SP1')
        assert kwargs['dry_run'] is False

    def test_single_background_job_queues_the_subpartition(self):
        with _page03() as mocks:
            at = _operator_app(_single_page).run()
            at.checkbox(key='single_dry_run').uncheck().run()
            _checkbox(at, 'Confirm Execution').check().run()
            at.button[0].click().run()
        (item,) = mocks['enqueue'].call_args.args[0]
        assert (item['partition_name'], item['subpartition_name']) == ('P1', 'SP1')
        mocks['execute'].assert_not_called()

    def test_batch_synchronous_items_carry_the_subpartition(self):
        with _page03() as mocks:
            at = _operator_app(_batch_page).run()
            at.multiselect[0].set_value(['APP.SALES']).run()

            def rerun():
                at.multiselect[0].set_value(['APP.SALES'])  # AppTest: re-pin by label
                return at.run()
            at.checkbox(key='batch_dry_run').uncheck()
            rerun()
            at.checkbox(key='batch_background').uncheck()
            rerun()
            at.checkbox(key='batch_confirm').check()
            rerun()
            at.button[0].click()
            rerun()
        assert not at.exception
        (item,) = mocks['batch'].call_args.args[1]
        assert (item['partition_name'], item['subpartition_name']) == ('P1', 'SP1')


def _rec_app():
    import pandas as pd
    import streamlit as st
    from hcc_advisor.views.page_02_recommendations import execute_batch_compression
    sel = pd.DataFrame({'ID': [7, 8], 'Table': ['SALES', 'T2'], 'Owner': ['APP', 'APP'],
                        'Advised': ['OLTP', 'OLTP'], 'Partition': ['P1', None],
                        'Subpartition': ['SP1', None]})
    execute_batch_compression(sel, sel, False, 4, background=st.session_state['t_background'],
                              confirmed=True)


@pytest.mark.unit
class TestRecommendationsSubpartition:

    @pytest.mark.parametrize('background', [False, True])
    def test_live_execution_passes_the_subpartition(self, background):
        with _page03() as mocks:
            at = _operator_app(_rec_app)
            at.session_state['t_background'] = background
            at.run()
        assert not at.exception
        if background:
            items = mocks['enqueue'].call_args.args[0]
            got = [(i['partition_name'], i['subpartition_name']) for i in items]
        else:
            got = [(c.kwargs['partition_name'], c.kwargs['subpartition_name'])
                   for c in mocks['execute'].call_args_list]
        assert got == [('P1', 'SP1'), (None, None)]


# ============================================================================
# 2. Queued rows: EXECUTION_MODE from the target's version
# ============================================================================

@pytest.mark.unit
class TestQueuedExecutionMode:

    @pytest.mark.parametrize('version, expected', [
        (V11_2, {'TABLE': 'OFFLINE', 'P1': 'OFFLINE', 'SP1': 'OFFLINE'}),
        (V12_1, {'TABLE': 'OFFLINE', 'P1': 'ONLINE', 'SP1': 'ONLINE'}),
        (V19, {'TABLE': 'ONLINE', 'P1': 'ONLINE', 'SP1': 'ONLINE'}),
        (None, {'TABLE': 'ONLINE', 'P1': 'ONLINE', 'SP1': 'ONLINE'}),   # unknown = modern
    ])
    def test_enqueue_records_mode_per_version_and_level(self, dbs, monkeypatch, version, expected):
        central, _ = dbs
        _target(monkeypatch, version, 'EXADATA')
        out = TargetQueries.enqueue_compression_jobs([
            {'database_id': 1, 'owner': 'APP', 'table_name': 'T', 'compression_type': 'OLTP'},
            {'database_id': 1, 'owner': 'APP', 'table_name': 'P', 'compression_type': 'OLTP',
             'partition_name': 'P1'},
            {'database_id': 1, 'owner': 'APP', 'table_name': 'S', 'compression_type': 'OLTP',
             'partition_name': 'P1', 'subpartition_name': 'SP1'},
        ])
        assert out['added'] == 3
        modes = {r['subpartition_name'] or r['partition_name'] or 'TABLE': r['execution_mode']
                 for r in central.rows.values()}
        assert modes == expected

    def test_claim_sets_mode_from_the_version_at_submit(self, dbs, monkeypatch):
        central, target = dbs
        _target(monkeypatch, None, 'EXADATA')          # queued before the version was known
        TargetQueries.enqueue_compression_jobs([
            {'database_id': 1, 'owner': 'APP', 'table_name': 'T', 'compression_type': 'OLTP',
             'dop': 1}])
        (row,) = central.rows.values()
        assert row['execution_mode'] == 'ONLINE'

        _target(monkeypatch, V12_1, 'EXADATA')         # connection tested since: 12.1
        stats = TargetQueries.drain_compression_queue(1)
        assert stats['submitted'] == 1
        assert row['operation_status'] == 'IN_PROGRESS'
        assert row['execution_mode'] == 'OFFLINE'
        assert 'ONLINE PARALLEL' not in row['original_ddl']

    def test_direct_submit_records_mode(self, dbs, monkeypatch):
        central, _ = dbs
        _target(monkeypatch, V11_2, 'EXADATA')
        res = TargetQueries.submit_compression_job(1, 'APP', 'ORDERS', 'OLTP', partition_name='P1')
        assert res['success'] is True
        assert central.rows[res['history_id']]['execution_mode'] == 'OFFLINE'


# ============================================================================
# 3. Rollback refused while an overlapping job is queued / running
# ============================================================================

def _open(hid, status, part=None, sub=None):
    return [hid, status, part, sub]


@pytest.mark.unit
class TestRollbackOverlap:

    @pytest.mark.parametrize('open_row, part, sub, state', [
        (_open(51, 'QUEUED'), 'P1', None, 'queued'),                         # table job
        (_open(52, 'IN_PROGRESS', 'P1'), 'P1', 'SP1', 'running'),            # parent partition
        (_open(53, 'QUEUED', 'P1', 'SP1'), 'P1', None, 'queued'),            # its subpartition
        (_open(54, 'IN_PROGRESS', 'P1'), 'P1', None, 'running'),             # same segment
        (_open(55, 'QUEUED', 'P2'), None, None, 'queued'),                   # table rollback
    ])
    def test_overlapping_open_row_refuses_before_any_ddl(self, open_row, part, sub, state):
        with _Recorder(open_rows=[open_row]) as rec:
            res = TargetQueries.rollback_compression(7, 'SCOTT', 'SALES', part,
                                                     subpartition_name=sub, history_id=42)
        assert res['success'] is False and res['blocked'] is True
        assert res['error'].startswith('Cannot roll back SCOTT.SALES')
        assert f"history_id {open_row[0]}" in res['error'] and f"is {state}" in res['error']
        assert rec.plsql == [] and rec.history_updates == [] and rec.target_queries == []

    def test_other_partition_or_subpartition_does_not_block(self):
        rows = [_open(61, 'IN_PROGRESS', 'P2'), _open(62, 'QUEUED', 'P1', 'SP2')]
        with _Recorder(open_rows=rows) as rec:
            res = TargetQueries.rollback_compression(7, 'SCOTT', 'SALES', 'P1',
                                                     subpartition_name='SP1', history_id=42)
        assert res['success'] is True, res
        assert 'MOVE SUBPARTITION SP1' in rec.move_ddl

    def test_queue_check_failure_refuses(self):
        with _Recorder() as rec, \
                patch.object(TargetQueries, '_overlapping_open_row',
                             side_effect=oracledb.DatabaseError('ORA-03113: end-of-file')):
            res = TargetQueries.rollback_compression(7, 'SCOTT', 'SALES', 'P1', history_id=42)
        assert res['success'] is False and 'ORA-03113' in res['error']
        assert 'not rolled back' in res['error']
        assert rec.plsql == [] and rec.history_updates == []

    def test_check_reads_the_live_queue(self, dbs):
        central, target = dbs
        central.add(object_name='SALES', partition_name=None, operation_status='QUEUED')
        central.add(object_name='OTHER', operation_status='IN_PROGRESS')
        res = TargetQueries.rollback_compression(1, 'APP', 'SALES', 'P1')
        assert res['success'] is False and res['blocked'] is True
        assert res['error'].startswith('Cannot roll back APP.SALES partition P1: '
                                       'a compression of APP.SALES is queued (history_id 101)')
        assert target.plsql == []

    def test_history_page_shows_the_reason(self, monkeypatch):
        history = pd.DataFrame([{
            'EXECUTION_ID': 42, 'DATABASE_ID': 7, 'TABLE_OWNER': 'SCOTT', 'TABLE_NAME': 'SALES',
            'PARTITION_NAME': 'P1', 'SUBPARTITION_NAME': None, 'OBJECT_TYPE': 'PARTITION',
            'STRATEGY': 'OLTP', 'STATUS': 'SUCCESS', 'ROLLBACK_STATUS': None,
            'SAVINGS_PCT': 50.0, 'ERROR_MESSAGE': None, 'EXECUTED_AT': datetime(2026, 9, 1),
        }])
        monkeypatch.setattr(CentralQueries, 'get_execution_history',
                            lambda **k: history.copy())
        # "Select object to rollback" is a format_func'd selectbox
        monkeypatch.setattr(Selectbox, 'index', property(_selectbox_index))

        def page():
            from hcc_advisor.views.page_04_history import show_history_page
            show_history_page()
        with _Recorder(open_rows=[_open(99, 'IN_PROGRESS', None)]) as rec:
            at = _operator_app(page).run()
            at.button(key='rollback_btn').click().run()
        assert not at.exception
        errors = ' '.join(e.value for e in at.error)
        assert 'Cannot roll back SCOTT.SALES partition P1' in errors
        assert 'history_id 99' in errors and 'is running' in errors
        assert rec.plsql == []


# ============================================================================
# 4. Target selector keyed on database_id; duplicate display names refused
# ============================================================================

def _targets(*rows):
    return pd.DataFrame([dict(zip(['DATABASE_ID', 'DATABASE_NAME', 'DISPLAY_NAME', 'DB_HOST',
                                   'SERVICE_NAME'], r)) for r in rows])


@pytest.mark.unit
class TestTargetSelectorLabels:

    def test_unique_names_are_shown_as_is(self):
        df = _targets((1, 'prod-01', 'Prod', 'h1', 'S1'), (2, 'dev-01', 'Dev', 'h2', 'S2'))
        assert target_selector_labels(df) == {1: 'Prod', 2: 'Dev'}

    def test_duplicates_case_insensitive_get_host_and_service(self):
        df = _targets((1, 'a', 'Prod', 'h1', 'S1'), (2, 'b', 'PROD ', 'h2', 'S2'),
                      (3, 'c', 'Dev', 'h3', 'S3'))
        assert target_selector_labels(df) == {1: 'Prod (h1/S1)', 2: 'PROD (h2/S2)', 3: 'Dev'}

    def test_same_host_and_service_fall_back_to_the_id(self):
        df = _targets((4, 'a', 'Prod', 'h1', 'S1'), (9, 'b', 'prod', 'h1', 'S1'))
        assert target_selector_labels(df) == {4: 'Prod (h1/S1) [ID 4]', 9: 'prod (h1/S1) [ID 9]'}

    def test_missing_display_name_uses_database_name(self):
        df = _targets((1, 'prod-01', None, 'h1', 'S1'), (2, 'dev-01', float('nan'), 'h2', 'S2'))
        assert target_selector_labels(df) == {1: 'prod-01', 2: 'dev-01'}
        assert target_selector_labels(pd.DataFrame()) == {}


DUP_REGISTRY = _targets((1, 'prod-01', 'Prod', 'h1', 'S1'), (2, 'prod-02', 'prod', 'h2', 'S2'),
                        (3, 'dev-01', 'Dev', 'h3', 'S3'))


@contextmanager
def _sidebar(active_id):
    """app.py (Overview page) with DUP_REGISTRY registered, run once."""
    registry = MagicMock(side_effect=lambda: DUP_REGISTRY.copy())
    with app_shell('Overview', extra=[(CentralQueries, 'get_target_databases', registry)]):
        at = new_app()
        at.session_state['active_database_id'] = active_id
        yield at.run()


@pytest.mark.unit
class TestSidebarSelector:

    def test_every_target_is_an_option_keyed_by_id(self):
        with _sidebar(2) as at:
            sel = at.selectbox(key='db_selector')
            assert not at.exception
            assert sel.options == ['All Databases', 'Prod (h1/S1)', 'prod (h2/S2)', 'Dev']
            assert sel.value == 2
            assert at.session_state['active_database_id'] == 2

    def test_selecting_a_duplicate_sets_its_own_id(self):
        with _sidebar(2) as at:
            at.selectbox(key='db_selector').select_index(1).run()
            assert not at.exception
            assert at.session_state['active_database_id'] == 1
            at.run()                                  # and it sticks
            assert at.session_state['active_database_id'] == 1
            assert at.selectbox(key='db_selector').value == 1
            at.selectbox(key='db_selector').select_index(0).run()
            assert at.session_state['active_database_id'] is None

    def test_unknown_active_id_falls_back_to_all(self):
        with _sidebar(99) as at:
            assert at.selectbox(key='db_selector').value is None
            assert at.session_state['active_database_id'] is None


class _Registry:
    """Fake CentralConnector for the target registry: records statements."""

    def __init__(self, active_rows):
        self.active = active_rows
        self.queries, self.dml = [], []

    def query(self, sql, params=None, raise_on_error=False, **kw):
        sql = " ".join(sql.split())
        self.queries.append((sql, params))
        if 'display_name FROM t_target_databases' in sql:
            assert "is_active = 'Y'" in sql              # removed targets never count
            return pd.DataFrame(self.active, columns=['DATABASE_ID', 'DATABASE_NAME',
                                                      'DISPLAY_NAME'])
        if 'is_active FROM t_target_databases' in sql:   # database_name pre-check
            return pd.DataFrame(columns=['DATABASE_ID', 'IS_ACTIVE'])
        if 'SELECT database_id' in sql:                  # new id after the insert
            return pd.DataFrame([{'DATABASE_ID': 42}])
        return pd.DataFrame()

    def execute_dml(self, sql, params=None, commit=True, raise_on_error=False):
        self.dml.append((sql, params))
        return 1


@pytest.fixture
def registry(monkeypatch):
    reg = _Registry([(5, 'prod-01', 'Prod'), (7, 'dev-01', '<b>Dev</b>')])
    monkeypatch.setattr(CentralConnector, 'execute_query', reg.query)
    monkeypatch.setattr(CentralConnector, 'execute_dml', reg.execute_dml)
    monkeypatch.setattr(CentralQueries, 'ensure_connection_mode_column', lambda: True)
    monkeypatch.setattr(CentralQueries, 'invalidate_target_databases_cache', MagicMock())
    monkeypatch.setattr(TargetConnector, 'close_pool', MagicMock())
    return reg


def _target_data(**overrides):
    data = {'database_name': 'NEW', 'display_name': 'New', 'db_host': 'h', 'port': 1521,
            'service_name': 'S', 'username': 'HCC', 'password_encrypted': 'enc',
            'description': '', 'environment': 'PRODUCTION', 'platform_type': 'STANDARD',
            'connection_mode': 'NORMAL', 'oracle_version': V19}
    data.update(overrides)
    return data


@pytest.mark.unit
class TestDuplicateDisplayNames:

    @pytest.mark.parametrize('name', ['Prod', 'PROD', '  prod '])
    def test_add_refuses_a_name_in_use(self, registry, name):
        ok, msg, new_id = CentralQueries.add_target_database(_target_data(display_name=name))
        assert (ok, new_id) == (False, None)
        assert "already used by target 'Prod' (prod-01, ID 5)" in msg
        assert registry.dml == []

    def test_add_accepts_a_new_name(self, registry):
        ok, _msg, new_id = CentralQueries.add_target_database(_target_data(display_name='QA'))
        assert ok and new_id == 42
        assert any('INSERT INTO t_target_databases' in s for s, _ in registry.dml)

    def test_update_refuses_another_targets_name(self, registry):
        ok, msg = CentralQueries.update_target_database(7, _target_data(display_name='prod'))
        assert ok is False and 'ID 5' in msg
        assert registry.dml == []

    def test_update_may_keep_or_recase_its_own_name(self, registry):
        ok, _msg = CentralQueries.update_target_database(5, _target_data(display_name='PROD'))
        assert ok is True
        (sql, params), = registry.dml
        assert sql.strip().startswith('UPDATE t_target_databases')
        assert params['display_name'] == 'PROD'

    def test_lookup_failure_is_not_a_conflict(self, registry, monkeypatch):
        monkeypatch.setattr(CentralConnector, 'execute_query',
                            MagicMock(side_effect=oracledb.DatabaseError('ORA-03113')))
        assert CentralQueries.display_name_conflict('Prod') is None

    def test_edit_form_shows_the_message(self, registry, monkeypatch):
        from tests.unit.test_edit_target import (
            KEY, VERSION, _button, _field, _open_editor, _page, _registry,
        )
        monkeypatch.setattr(page_06_connections.config, 'ENCRYPTION_KEY', KEY)
        monkeypatch.setattr(page_06_connections, 'test_target_connection',
                            MagicMock(return_value=(True, 'Connected', VERSION)))
        monkeypatch.setattr(CentralQueries, 'update_target_last_connected', MagicMock())
        monkeypatch.setattr(CentralQueries, 'get_target_databases', lambda: _registry())
        monkeypatch.setattr(st, 'rerun', MagicMock())
        at = AppTest.from_function(_page, default_timeout=TIMEOUT)
        at.session_state['authenticated'] = True
        at.session_state['role'] = ROLE_ADMIN
        at.run()

        at = _open_editor(at, 7)
        _field(at, 7, 'display_name').input('PROD')
        _button(at, 'Test & Save').click().run()
        assert not at.exception
        assert any("already used by target 'Prod'" in e.value for e in at.error)
        assert registry.dml == []                            # nothing saved
        assert at.session_state['edit_target_id'] == 7       # form stays open


# ============================================================================
# 5. The ORA-00001 race shows no raw banner
# ============================================================================

class _Cursor:
    def __init__(self, error):
        self.error = error

    def var(self, *a, **k):
        return MagicMock()

    def execute(self, sql, params=None):
        raise oracledb.IntegrityError(self.error)

    def close(self):
        pass


@contextmanager
def _failing_central(error):
    """Real CentralConnector on a connection whose statement fails with error.
    Yields (st.error spy, connection); both connector modules share st."""
    assert cc_module.st is cq_module.st
    conn = MagicMock()
    conn.cursor.return_value = _Cursor(error)

    @contextmanager
    def get_connection():
        yield conn
    with patch.object(CentralConnector, 'get_connection', get_connection), \
            patch.object(cc_module.st, 'error') as st_error:
        yield st_error, conn


RECORD = {'owner': 'APP', 'object_name': 'ORDERS', 'object_type': 'PARTITION',
          'partition_name': 'P1', 'compression_type_applied': 'OLTP',
          'operation_status': 'IN_PROGRESS'}


def _banners(st_error):
    return [c.args[0] for c in st_error.call_args_list]


@pytest.mark.unit
class TestNoRawBannerOnTheRace:

    def test_strict_dml_returning_raises_without_banner(self):
        with _failing_central(DUP) as (st_error, conn):
            with pytest.raises(oracledb.IntegrityError, match='ORA-00001'):
                CentralConnector.execute_dml_returning(
                    "INSERT INTO t (a) VALUES (:a) RETURNING id INTO :new_id", {'a': 1},
                    raise_on_error=True)
        st_error.assert_not_called()
        conn.commit.assert_not_called()

    def test_default_dml_returning_still_shows_the_banner(self):
        with _failing_central(DUP) as (st_error, _conn):
            assert CentralConnector.execute_dml_returning(
                "INSERT INTO t (a) VALUES (:a) RETURNING id INTO :new_id", {'a': 1}) is None
        (banner,) = _banners(st_error)
        assert banner.startswith('Central database DML error: ORA-00001')

    def test_store_returns_none_quietly_on_the_open_segment_conflict(self):
        with _failing_central(DUP) as (st_error, _):
            assert CentralQueries.store_compression_history(1, dict(RECORD)) is None
        st_error.assert_not_called()

    def test_store_reports_other_errors_once(self):
        with _failing_central('ORA-12899: value too large for column') as (st_error, _):
            assert CentralQueries.store_compression_history(1, dict(RECORD)) is None
        (banner,) = _banners(st_error)                       # not the raw connector banner
        assert banner.startswith('Failed to store compression history: ORA-12899')

    def test_direct_run_losing_the_race_reports_duplicate_only(self, dbs):
        central, target = dbs
        central.unique_open = True

        def enqueue_meanwhile(s, p):
            # another session queues the segment right after the open-row check
            if s.startswith('SELECT history_id, operation_status FROM') and not central.rows:
                central.add(partition_name='P1', operation_status='QUEUED')
        central.after_query = enqueue_meanwhile
        res = TargetQueries.execute_compression(1, 'APP', 'ORDERS', 'OLTP', 'P1', dry_run=False)
        assert res['success'] is False and res['duplicate'] is True
        assert 'already queued or running' in res['error']
        central.st_error.assert_not_called()
        assert target.plsql == []

    def test_direct_submit_losing_the_race_reports_duplicate_only(self, dbs):
        central, target = dbs
        central.unique_open = True

        def enqueue_meanwhile(s, p):
            if s.startswith('SELECT history_id, operation_status FROM') and not central.rows:
                central.add(partition_name='P1', operation_status='QUEUED')
        central.after_query = enqueue_meanwhile
        res = TargetQueries.submit_compression_job(1, 'APP', 'ORDERS', 'OLTP', partition_name='P1')
        assert res['success'] is False and res['duplicate'] is True
        central.st_error.assert_not_called()
        assert target.plsql == []

    def test_direct_submit_other_insert_error_is_in_the_result(self, dbs):
        central, _ = dbs
        central.insert_errors[('ORDERS', 'P1')] = 'ORA-02290: check constraint violated'
        res = TargetQueries.submit_compression_job(1, 'APP', 'ORDERS', 'OLTP', partition_name='P1')
        assert res['success'] is False and 'duplicate' not in res
        assert 'ORA-02290' in res['error']
        central.st_error.assert_not_called()


# ============================================================================
# 6. Legacy migration: extra open rows of a segment
# ============================================================================

HIST_COLS = migration.TABLE_CONFIGS['T_COMPRESSION_HISTORY']['columns']


def _hist(hid, status, part=None, sub=None, start=None, end=None, error=None, obj='SALES'):
    values = dict.fromkeys(HIST_COLS)
    values.update(HISTORY_ID=hid, OWNER='APP', OBJECT_NAME=obj, PARTITION_NAME=part,
                  SUBPARTITION_NAME=sub, OPERATION_STATUS=status, START_TIME=start,
                  END_TIME=end, ERROR_MESSAGE=error)
    return tuple(values[c] for c in HIST_COLS)


def _col(row, name):
    return row[HIST_COLS.index(name)]


T = datetime(2025, 1, 1)
CLOSED_AT = datetime(2026, 9, 24, 12, 0)


@pytest.mark.unit
class TestMigrationOpenRows:

    def test_one_open_row_kept_per_segment_others_failed(self):
        rows = [
            _hist(1, 'QUEUED', 'P1', start=T.replace(day=1)),
            _hist(2, 'IN_PROGRESS', 'P1', start=T.replace(day=3), error='old error'),
            _hist(3, 'IN_PROGRESS', 'P1', start=T.replace(day=2)),     # kept: oldest running
            _hist(4, 'IN_PROGRESS', 'P2', start=T),                    # alone on its segment
            _hist(5, 'IN_PROGRESS', 'P1', 'SP1', start=T),             # another segment
            _hist(6, 'SUCCESS', 'P1', start=T, end=T),
            _hist(7, 'FAILED', 'P1', start=T, end=T),
        ]
        out, report = migration.close_duplicate_open_rows(HIST_COLS, rows, closed_at=CLOSED_AT)
        assert len(out) == len(rows)                                  # nothing dropped
        status = {_col(r, 'HISTORY_ID'): _col(r, 'OPERATION_STATUS') for r in out}
        assert status == {1: 'FAILED', 2: 'FAILED', 3: 'IN_PROGRESS', 4: 'IN_PROGRESS',
                          5: 'IN_PROGRESS', 6: 'SUCCESS', 7: 'FAILED'}
        closed = {_col(r, 'HISTORY_ID'): r for r in out if _col(r, 'HISTORY_ID') in (1, 2)}
        for hid, row in closed.items():
            assert 'history_id 3 is already running' in _col(row, 'ERROR_MESSAGE')
            assert _col(row, 'END_TIME') == CLOSED_AT
        assert 'original status was QUEUED' in _col(closed[1], 'ERROR_MESSAGE')
        assert _col(closed[2], 'ERROR_MESSAGE').endswith('Previous error: old error')
        assert out[5:] == rows[5:] and out[2:5] == rows[2:5]         # others untouched
        assert len(report) == 2 and all('APP.SALES partition P1' in line for line in report)

    def test_queued_rows_keep_the_oldest(self):
        rows = [_hist(10, 'QUEUED', start=T.replace(day=5)), _hist(11, 'QUEUED', start=T),
                _hist(12, 'QUEUED', start=None)]
        out, report = migration.close_duplicate_open_rows(HIST_COLS, rows)
        assert [_col(r, 'OPERATION_STATUS') for r in out] == ['FAILED', 'QUEUED', 'FAILED']
        assert len(report) == 2

    def test_long_previous_error_fits_the_column(self):
        rows = [_hist(1, 'IN_PROGRESS', start=T), _hist(2, 'IN_PROGRESS', start=T,
                                                         error='é' * 3000)]
        out, _ = migration.close_duplicate_open_rows(HIST_COLS, rows)
        assert len(_col(out[1], 'ERROR_MESSAGE').encode('utf-8')) <= 4000

    def _migrate(self, rows, dry_run):
        target, central = MagicMock(), MagicMock()
        target.cursor.return_value.fetchone.return_value = (1,)    # table exists
        target.cursor.return_value.fetchall.return_value = rows
        n = migration.migrate_table(target, central, 'T_COMPRESSION_HISTORY', 3, dry_run)
        return n, central.cursor.return_value.executemany.call_args_list

    def test_migrate_table_imports_extras_as_failed(self, capsys):
        rows = [_hist(1, 'IN_PROGRESS', start=T), _hist(2, 'IN_PROGRESS', start=T),
                _hist(3, 'SUCCESS', start=T, end=T)]
        n, calls = self._migrate(rows, dry_run=False)
        assert n == 3
        (call,) = calls
        batch = call.args[1]
        assert [b['b_operation_status'] for b in batch] == ['IN_PROGRESS', 'FAILED', 'SUCCESS']
        assert all(b['b_database_id'] == 3 for b in batch)
        assert 'Duplicate open row closed by the migration' in batch[1]['b_error_message']
        out = capsys.readouterr().out
        assert '1 duplicate open (QUEUED/IN_PROGRESS) row(s) imported as FAILED' in out
        assert 'history_id 2 (APP.SALES, IN_PROGRESS)' in out

    def test_dry_run_reports_without_writing(self, capsys):
        rows = [_hist(1, 'IN_PROGRESS', start=T), _hist(2, 'IN_PROGRESS', start=T)]
        n, calls = self._migrate(rows, dry_run=True)
        assert n == 2 and calls == []
        assert 'would be imported as FAILED' in capsys.readouterr().out
