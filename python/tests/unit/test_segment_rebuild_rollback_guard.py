"""
Unit tests for three MOVE-safety rules:

- the DBMS_SCHEDULER job action rebuilds only what its MOVE left UNUSABLE on
  the moved segment (the query _rebuild_unusable_indexes uses: the segment's
  local index (sub)partitions by position, unusable global indexes and global
  index partitions, no LOB / IOT-top indexes; names quoted with
  DBMS_ASSERT.ENQUOTE_NAME), never every unusable index of the table;
- rollback_compression holds an IN_PROGRESS history row of its own for its
  segment while the NOCOMPRESS MOVE runs (checked for overlap before and after
  it is written, with and without UNQ_HISTORY_OPEN_SEGMENT), closes it SUCCESS /
  FAILED, marks the compression it undid ROLLED_BACK; that row is kept out of
  the savings / effectiveness aggregates, labelled in the history lists, and
  reconciled like a stale direct run;
- execute_compression refuses a segment that an open row overlaps (the whole
  table, the parent partition, a subpartition), before and after writing its
  own IN_PROGRESS row.

No database: the central history table and the target are the in-memory fakes
of test_scheduler_queue, extended here with the rollback's own row.
"""
import re

import oracledb
import pandas as pd
import pytest
from streamlit.testing.v1.element_tree import Selectbox

from hcc_advisor.utils import target_queries as tq
from hcc_advisor.utils.central_connector import CentralConnector
from hcc_advisor.utils.central_queries import (
    CentralQueries, ROLLBACK_ROW_STATUS, not_rollback_row_sql, rollback_row_sql,
)
from hcc_advisor.utils.target_connector import TargetConnector
from hcc_advisor.utils.target_queries import TargetQueries, rollback_block_reason
from hcc_advisor.views import page_04_history
from tests.unit.app_harness import _selectbox_index
from tests.unit.test_execution_loose_ends import _operator_app
from tests.unit.test_scheduler_queue import FakeCentral, FakeTarget, _check_binds, _df, _norm

DUP = 'ORA-00001: unique constraint (HCC.UNQ_HISTORY_OPEN_SEGMENT) violated'
V11_2 = 'Oracle Database 11g Enterprise Edition Release 11.2.0.4.0 - 64bit Production'


class RollbackCentral(FakeCentral):
    """FakeCentral that also interprets the rollback statements: the
    eligibility check of the compression's row, the rollback's own row
    (INSERT with ROLLBACK_STATUS), ROLLBACK_STATUS in the overlap / reconcile
    reads, and _record_rollback's UPDATE of the compression's row."""

    def add(self, **kw):
        kw.setdefault('rollback_status', None)
        kw.setdefault('rollback_possible', 'Y')
        return super().add(**kw)

    def _select(self, s, p):
        if s.startswith('SELECT operation_status, rollback_status, object_type'):
            r = self.rows.get(p['hid'])
            ok = (r is not None and r['database_id'] == p['db'] and r['owner'] == p['o']
                  and r['object_name'] == p['t']
                  and (r['partition_name'] or '~') == (p['p'] or '~')
                  and (r['subpartition_name'] or '~') == (p['sp'] or '~'))
            return _df([[r['operation_status'], r['rollback_status'], r['object_type'],
                         r['compression_type_applied']]] if ok else [],
                       ['OPERATION_STATUS', 'ROLLBACK_STATUS', 'OBJECT_TYPE',
                        'COMPRESSION_TYPE_APPLIED'])
        df = super()._select(s, p)
        if 'rollback_status' in s and 'HISTORY_ID' in df.columns:
            df['ROLLBACK_STATUS'] = [self.rows[int(h)]['rollback_status'] for h in df['HISTORY_ID']]
        return df

    def dml_returning(self, sql, params=None, out_bind='new_id', commit=True,
                      raise_on_error=False):
        s, p = _norm(sql), dict(params or {})
        if 'rb_marker' not in p:
            return super().dml_returning(sql, params, out_bind, commit, raise_on_error)
        _check_binds(s, p, extra=(out_bind,))
        self.statements.append(('dml', s, p))
        assert s.startswith('INSERT INTO t_compression_history') and 'RETURNING history_id' in s
        assert "'NONE'" in s and "'IN_PROGRESS', SYSTIMESTAMP" in s and "'N', :rb_marker" in s
        try:
            self._maybe_fail(s)
            self._check_unique_open(self._open_key(p['db'], p['owner'], p['tbl'], p['part'], p['sub']))
        except oracledb.Error:
            if raise_on_error:
                raise
            return None
        return self.add(database_id=p['db'], owner=p['owner'], object_name=p['tbl'],
                        object_type=p['otype'], partition_name=p['part'],
                        subpartition_name=p['sub'], compression_type_applied='NONE',
                        compression_clause=p['clause'], execution_mode=p['mode'],
                        parallel_degree=p['dop'], operation_status='IN_PROGRESS',
                        executed_by=p['executed_by'], rollback_possible='N',
                        rollback_status=p['rb_marker'], original_ddl=p['ddl'])

    def dml(self, sql, params=None, commit=True, raise_on_error=False):
        s, p = _norm(sql), dict(params or {})
        if 'rolled_back' not in p:
            return super().dml(sql, params, commit, raise_on_error)
        _check_binds(s, p)                                  # _record_rollback
        self.statements.append(('dml', s, p))
        row = self.rows.get(p['hid'])
        if row is None:
            return 0
        if p['rolled_back'] == 1:
            row.update(operation_status='ROLLED_BACK', rollback_possible='N')
        row['rollback_status'] = p['rb_status']
        if p['msg'] is not None:
            row['error_message'] = p['msg']
        return 1

    def rollback_rows(self):
        return [r for r in self.rows.values() if r['rollback_status'] == ROLLBACK_ROW_STATUS]


@pytest.fixture
def dbs(monkeypatch):
    central, target = RollbackCentral(), FakeTarget()
    monkeypatch.setattr(CentralConnector, 'execute_query', central.query)
    monkeypatch.setattr(CentralConnector, 'execute_dml', central.dml)
    monkeypatch.setattr(CentralConnector, 'execute_dml_returning', central.dml_returning)
    monkeypatch.setattr(CentralConnector, 'get_connection', central.connection)
    monkeypatch.setattr(TargetConnector, 'execute_query', target.query)
    monkeypatch.setattr(TargetConnector, 'execute_plsql', target.execute_plsql)
    monkeypatch.setattr(tq, '_acting_user', lambda: 'alice')
    return central, target


def _compressed(central, part='P1', sub=None, **kw):
    """A SUCCESS compression row, eligible for rollback."""
    otype = 'SUBPARTITION' if sub else 'PARTITION' if part else 'TABLE'
    return central.add(partition_name=part, subpartition_name=sub, object_type=otype,
                       operation_status='SUCCESS', compression_type_applied='OLTP',
                       original_size_bytes=1000, compressed_size_bytes=400, **kw)


def _overlap_queries(central):
    return [p for kind, s, p in central.statements
            if kind == 'query' and s.startswith('SELECT history_id, operation_status, partition_name')]


def _on_first_overlap_check(central, add):
    """Another session writes a row right after the first overlap check."""
    def hook(s, p):
        if s.startswith('SELECT history_id, operation_status, partition_name') and not hook.done:
            hook.done = True
            add()
    hook.done = False
    central.after_query = hook


# ============================================================================
# 1. Scheduler job action: segment-scoped rebuild
# ============================================================================

def _job_action(central, target, **seg):
    """Submit one queued item for `seg` and return the CREATE_JOB block."""
    central.add(**seg)
    res = TargetQueries.submit_queued_job(TargetQueries.get_queued_compression_jobs(1)[0])
    assert res['status'] == 'SUBMITTED', res
    (block,) = target.plsql
    return block


def _declared(action, var):
    m = re.search(rf"{var} VARCHAR2\(128\) := (NULL|'(\w+)')", action)
    assert m, f"{var} not declared in the job action"
    return m.group(2)


SEGMENTS = [
    pytest.param({}, (None, None), id='table'),
    pytest.param({'partition_name': 'P1'}, ('P1', None), id='partition'),
    pytest.param({'partition_name': 'P1', 'subpartition_name': 'SP1'}, (None, 'SP1'),
                 id='subpartition'),
]


@pytest.mark.unit
class TestJobActionRebuild:

    @pytest.mark.parametrize('seg, scope', SEGMENTS)
    def test_rebuild_is_scoped_to_the_moved_segment(self, dbs, seg, scope):
        central, target = dbs
        block = _job_action(central, target, parallel_degree=2, **seg)
        # the same query as _rebuild_unusable_indexes, on PL/SQL variables
        loop = " ".join(TargetQueries._UNUSABLE_INDEXES_TEMPLATE.format(
            o='v_owner', t='v_table', p='v_partition', sp='v_subpartition').split())
        assert f"FOR idx IN ( {loop} ) LOOP" in block
        assert (_declared(block, 'v_owner'), _declared(block, 'v_table')) == ('APP', 'ORDERS')
        # a subpartition MOVE leaves the parent's local index partitions alone
        assert (_declared(block, 'v_partition'), _declared(block, 'v_subpartition')) == scope
        assert 'ONLINE PARALLEL 2' in block

    @pytest.mark.parametrize('seg, scope', SEGMENTS)
    def test_no_table_wide_loop(self, dbs, seg, scope):
        central, target = dbs
        block = _job_action(central, target, **seg)
        assert 'SELECT owner, index_name FROM all_indexes' not in block
        assert "table_owner = 'APP'" not in block and "table_name = 'ORDERS'" not in block
        # every branch of the scoped query is keyed on the moved segment or global
        assert block.count("i.table_owner = v_owner AND i.table_name = v_table") == 3
        assert 'tp.partition_name = v_partition' in block
        assert 'tsp.subpartition_name = v_subpartition' in block
        assert "pi.locality = 'GLOBAL'" in block

    def test_same_scope_as_the_synchronous_rebuild(self, dbs):
        """For each segment the job's variables equal the binds that
        execute_compression passes to _ROLLBACK_UNUSABLE_INDEXES_SQL."""
        central, target = dbs
        assert TargetQueries._ROLLBACK_UNUSABLE_INDEXES_SQL == \
            TargetQueries._UNUSABLE_INDEXES_TEMPLATE.format(o=':o', t=':t', p=':p', sp=':sp')
        for part, sub in [(None, None), ('P1', None), ('P1', 'SP1')]:
            central.rows.clear()
            target.plsql.clear()
            target.queries.clear()
            res = TargetQueries.execute_compression(1, 'APP', 'ORDERS', 'OLTP', part,
                                                    dry_run=False, subpartition_name=sub)
            assert res['success'] is True, res
            (binds,) = [p for s, p in target.queries if 'FROM all_indexes' in s]
            central.rows.clear()
            target.plsql.clear()
            block = _job_action(central, target, partition_name=part, subpartition_name=sub)
            assert (_declared(block, 'v_partition'), _declared(block, 'v_subpartition')) == \
                (binds['p'], binds['sp'])

    def test_skips_lob_and_iot_top_indexes(self, dbs):
        central, target = dbs
        block = _job_action(central, target, partition_name='P1')
        assert block.count("i.index_type NOT IN ('LOB', 'IOT - TOP')") == 3

    def test_names_read_at_run_time_are_enquoted(self, dbs):
        central, target = dbs
        block = _job_action(central, target, partition_name='P1')
        for col in ('index_owner', 'index_name', 'segment_name'):
            assert f"DBMS_ASSERT.ENQUOTE_NAME(idx.{col}, FALSE)" in block
        # no dictionary value is concatenated into the statement unquoted
        stmt = block.split("EXECUTE IMMEDIATE 'ALTER INDEX '", 1)[1].split(';', 1)[0]
        assert re.findall(r"\|\| idx\.\w+ \|\|", stmt) == []

    def test_move_first_then_failures_reported_through_the_job(self, dbs):
        central, target = dbs
        block = _job_action(central, target, partition_name='P1')
        action = block.split("job_action => q'§", 1)[1].split("§'", 1)[0]
        body = action.split(' BEGIN ', 1)[1]
        # the MOVE is the first statement and is not wrapped in a handler:
        # its error fails the job, which reconcile records on the history row
        assert body.startswith("EXECUTE IMMEDIATE 'ALTER TABLE APP.ORDERS MOVE PARTITION P1")
        assert "EXCEPTION WHEN OTHERS THEN v_failed := v_failed + 1;" in action
        assert 'RAISE_APPLICATION_ERROR(-20001' in action
        # no bind-like token (the action sits in a q-quoted literal of the call)
        assert re.search(r":[A-Za-z_]", action) is None

    def test_action_fits_job_action_at_maximum_name_lengths(self):
        name = 'A' * 128
        ddl = TargetQueries.generate_ddl(name, name, 'OLTP', name, name, parallel_degree=128,
                                         oracle_version=V11_2).rstrip().rstrip(';')
        action = TargetQueries._compression_job_action(ddl, name, name, name, name, 128)
        assert len(action.encode()) < 4000

    @pytest.mark.parametrize('owner, table, part, sub, dop', [
        ("APP'; DROP", 'ORDERS', None, None, 4),
        ('APP', 'ORDERS', 'P1 NOCOMPRESS', None, 4),
        ('APP', 'ORDERS', None, "SP1'--", 4),
        ('APP', 'ORDERS', None, None, 0),
    ])
    def test_unsafe_values_rejected(self, owner, table, part, sub, dop):
        with pytest.raises(ValueError):
            TargetQueries._compression_job_action('ALTER TABLE X MOVE', owner, table, part, sub, dop)


# ============================================================================
# 2. Rollback holds its own open row
# ============================================================================

@pytest.mark.unit
class TestRollbackOwnRow:

    def test_inserts_and_closes_its_own_row(self, dbs, monkeypatch):
        central, target = dbs
        orig = _compressed(central, part='P1')
        seen = {}

        def move(database_id, block, **kw):
            (own,) = central.rollback_rows()
            seen.update(status=own['operation_status'], hid=own['history_id'],
                        active=own['history_id'] in tq._active_snapshot(tq._ACTIVE_HISTORY_IDS))
            return target.execute_plsql(database_id, block, **kw)
        monkeypatch.setattr(TargetConnector, 'execute_plsql', move)

        res = TargetQueries.rollback_compression(1, 'APP', 'ORDERS', 'P1', parallel_degree=2,
                                                 history_id=orig)

        assert res['success'] is True, res
        assert seen['status'] == 'IN_PROGRESS' and seen['active'] is True
        assert res['rollback_history_id'] == seen['hid']
        assert seen['hid'] not in tq._active_snapshot(tq._ACTIVE_HISTORY_IDS)
        own = central.rows[seen['hid']]
        assert own['operation_status'] == 'SUCCESS' and own['error_message'] is None
        assert (own['object_type'], own['partition_name'], own['subpartition_name']) == \
            ('PARTITION', 'P1', None)
        assert own['compression_type_applied'] == 'NONE'
        assert own['compression_clause'] == f"ROLLBACK of history_id {orig}"
        assert own['rollback_possible'] == 'N' and own['rollback_status'] == ROLLBACK_ROW_STATUS
        assert own['parallel_degree'] == 2 and own['execution_mode'] == 'ONLINE'
        assert own['executed_by'] == 'alice'
        assert 'MOVE PARTITION P1' in own['original_ddl'] and 'NOCOMPRESS' in own['original_ddl']
        # no sizes: nothing can read a (negative) saving from it
        assert own['original_size_bytes'] is None and own['compressed_size_bytes'] is None
        assert central.rows[orig]['operation_status'] == 'ROLLED_BACK'
        assert central.rows[orig]['rollback_status'] == 'ROLLED_BACK'
        # overlap checked before and after the own row was written
        assert len(_overlap_queries(central)) == 2

    def test_own_row_blocks_overlapping_work_while_the_move_runs(self, dbs, monkeypatch):
        central, target = dbs
        orig = _compressed(central, part='P1')
        during = {}

        def move(database_id, block, **kw):
            if 'NOCOMPRESS' in block:
                during['direct'] = TargetQueries.execute_compression(
                    1, 'APP', 'ORDERS', 'OLTP', dry_run=False)             # the whole table
                queued = central.add(partition_name='P1', subpartition_name='SP1')
                item = next(i for i in TargetQueries.get_queued_compression_jobs(1)
                            if i['history_id'] == queued)
                during['claim'] = TargetQueries.submit_queued_job(item)
                during['enqueue'] = TargetQueries.enqueue_compression_jobs(
                    [{'database_id': 1, 'owner': 'APP', 'table_name': 'ORDERS',
                      'partition_name': 'P1', 'compression_type': 'OLTP', 'dop': 2}])
                during['rollback'] = TargetQueries.rollback_compression(
                    1, 'APP', 'ORDERS', 'P1', subpartition_name='SP2')
            return target.execute_plsql(database_id, block, **kw)
        monkeypatch.setattr(TargetConnector, 'execute_plsql', move)

        res = TargetQueries.rollback_compression(1, 'APP', 'ORDERS', 'P1', history_id=orig)

        assert res['success'] is True, res
        assert during['direct']['success'] is False and during['direct']['duplicate'] is True
        assert 'rollback (history_id' in during['direct']['error']
        assert during['claim']['status'] == 'BLOCKED'                   # drain overlap check
        assert during['enqueue']['duplicates'] == 1                     # exact segment
        assert during['rollback']['blocked'] is True
        assert 'a rollback of APP.ORDERS partition P1 is running' in during['rollback']['error']
        assert len(target.plsql) == 1                                   # only our MOVE ran

    @pytest.mark.parametrize('unique_index', [False, True])
    def test_post_insert_overlap_closes_own_row_and_refuses(self, dbs, unique_index):
        """A scheduler job claims the whole table between the pre-check and the
        rollback's insert: the post-insert check sees it (the unique index does
        not cover a different segment)."""
        central, target = dbs
        central.unique_open = unique_index
        orig = _compressed(central, part='P1')
        blockers = []
        _on_first_overlap_check(central, lambda: blockers.append(central.add(
            operation_status='IN_PROGRESS', compression_clause='HCC_ORDERS_77')))

        res = TargetQueries.rollback_compression(1, 'APP', 'ORDERS', 'P1', history_id=orig)

        assert res['success'] is False and res['blocked'] is True
        assert f"a compression of APP.ORDERS is running (history_id {blockers[0]})" in res['error']
        assert target.plsql == []
        own = central.rows[res['rollback_history_id']]
        assert own['operation_status'] == 'FAILED'
        assert own['error_message'].startswith(
            f"Rollback not run: blocked by APP.ORDERS (history_id {blockers[0]}, IN_PROGRESS)")
        assert central.rows[orig]['operation_status'] == 'SUCCESS'   # untouched, retryable
        assert central.rows[orig]['rollback_status'] is None

    def test_same_segment_queued_meanwhile_with_unique_index(self, dbs):
        """UNQ_HISTORY_OPEN_SEGMENT rejects the rollback's row: refused as
        blocked, nothing written, nothing moved."""
        central, target = dbs
        central.unique_open = True
        orig = _compressed(central, part='P1')
        _on_first_overlap_check(central, lambda: central.add(partition_name='P1'))

        res = TargetQueries.rollback_compression(1, 'APP', 'ORDERS', 'P1', history_id=orig)

        assert res['success'] is False and res['blocked'] is True
        assert 'is queued' in res['error'] and 'rollback_history_id' not in res
        assert central.rollback_rows() == [] and target.plsql == []

    def test_same_segment_queued_meanwhile_without_unique_index(self, dbs):
        central, target = dbs
        orig = _compressed(central, part='P1')
        queued = []
        _on_first_overlap_check(central, lambda: queued.append(central.add(partition_name='P1')))

        res = TargetQueries.rollback_compression(1, 'APP', 'ORDERS', 'P1', history_id=orig)

        assert res['success'] is False and res['blocked'] is True
        assert f"(history_id {queued[0]})" in res['error']
        (own,) = central.rollback_rows()
        assert own['operation_status'] == 'FAILED' and target.plsql == []

    def test_move_failure_closes_own_row_failed(self, dbs):
        central, target = dbs
        orig = _compressed(central, part='P1')
        target.plsql_error = oracledb.DatabaseError('ORA-14808: table does not support ONLINE MOVE')

        res = TargetQueries.rollback_compression(1, 'APP', 'ORDERS', 'P1', history_id=orig)

        assert res['success'] is False and 'ORA-14808' in res['error']
        (own,) = central.rollback_rows()
        assert own['operation_status'] == 'FAILED'
        assert own['error_message'].startswith('Rollback failed: ORA-14808')
        assert own['history_id'] not in tq._active_snapshot(tq._ACTIVE_HISTORY_IDS)
        # the compression stays SUCCESS (still compressed) and can be retried
        assert central.rows[orig]['operation_status'] == 'SUCCESS'
        assert central.rows[orig]['rollback_status'] == 'FAILED'

    def test_index_rebuild_failures_noted_on_both_rows(self, dbs, monkeypatch):
        central, target = dbs
        orig = _compressed(central, part='P1')
        query = target.query

        def with_index(database_id, sql, params=None, **kw):
            if 'FROM all_indexes' in sql:
                return pd.DataFrame([['APP', 'IX1', 'INDEX', None]],
                                    columns=['INDEX_OWNER', 'INDEX_NAME', 'REBUILD_LEVEL',
                                             'SEGMENT_NAME'])
            return query(database_id, sql, params, **kw)
        monkeypatch.setattr(TargetConnector, 'execute_query', with_index)
        monkeypatch.setattr(TargetConnector, 'execute_plsql',
                            lambda db, block, **kw: 'ALTER INDEX' not in block)

        res = TargetQueries.rollback_compression(1, 'APP', 'ORDERS', 'P1', history_id=orig)

        assert res['success'] is True and res['index_failures'] == ['APP.IX1']
        (own,) = central.rollback_rows()
        assert own['operation_status'] == 'SUCCESS'
        assert own['error_message'] == 'Rollback: index rebuild failed for APP.IX1'
        assert central.rows[orig]['rollback_status'] == 'ROLLED_BACK_INDEX_ERRORS'

    def test_insert_failure_refuses_without_moving(self, dbs):
        central, target = dbs
        orig = _compressed(central, part='P1')
        central.fail_on[':rb_marker'] = oracledb.DatabaseError('ORA-01654: unable to extend index')

        res = TargetQueries.rollback_compression(1, 'APP', 'ORDERS', 'P1', history_id=orig)

        assert res['success'] is False and 'blocked' not in res
        assert 'Could not record the rollback' in res['error'] and 'ORA-01654' in res['error']
        assert target.plsql == [] and central.rollback_rows() == []

    def test_post_insert_check_failure_closes_own_row(self, dbs):
        central, target = dbs
        orig = _compressed(central, part='P1')

        def fail_second_check(s, p):
            if s.startswith('SELECT history_id, operation_status, partition_name') \
                    and central.rollback_rows():
                raise oracledb.DatabaseError('ORA-03113: end-of-file on communication channel')
        central.after_query = fail_second_check

        res = TargetQueries.rollback_compression(1, 'APP', 'ORDERS', 'P1', history_id=orig)

        assert res['success'] is False and 'ORA-03113' in res['error']
        (own,) = central.rollback_rows()
        assert own['operation_status'] == 'FAILED' and target.plsql == []

    def test_rollback_row_itself_cannot_be_rolled_back(self, dbs):
        central, target = dbs
        orig = _compressed(central, part='P1')
        res = TargetQueries.rollback_compression(1, 'APP', 'ORDERS', 'P1', history_id=orig)
        own = res['rollback_history_id']
        assert 'it is a rollback' in rollback_block_reason('SUCCESS', ROLLBACK_ROW_STATUS,
                                                           'PARTITION', 'NONE')
        again = TargetQueries.rollback_compression(1, 'APP', 'ORDERS', 'P1', history_id=own)
        assert again['success'] is False and 'it is a rollback' in again['error']
        assert len(target.plsql) == 1


# ============================================================================
# 2b. Rollback rows in the aggregates and lists
# ============================================================================

NOT_RB = not_rollback_row_sql()
IS_RB = rollback_row_sql()


@pytest.fixture
def captured(monkeypatch):
    """Every central query's normalized SQL; one non-empty row so the
    two-step aggregates (forecast) run their second query too."""
    calls = []

    def fake(query, params=None, **kw):
        calls.append(_norm(query))
        if 'v_compression_effectiveness' in query:
            raise Exception('ORA-00942: table or view does not exist')
        return pd.DataFrame([{
            'PENDING_COUNT': 1, 'PENDING_CURRENT_MB': 1.0, 'PENDING_PROJECTED_MB': 0.5,
            'PENDING_SAVINGS_MB': 0.5, 'AVG_SEC': 60, 'TOTAL': 1, 'COMPRESSED': 0,
            'PENDING': 1, 'SKIPPED': 0, 'SAVED_MB': 0.0, 'COMPRESSED_ORIGINAL_MB': 0.0,
            'UNCOMPRESSED_MB': 0.0,
        }])
    monkeypatch.setattr(CentralConnector, 'execute_query', fake)
    return calls


@pytest.mark.unit
class TestRollbackRowsInAggregates:

    def test_predicates(self):
        assert NOT_RB == "NVL(rollback_status, '~') <> 'ROLLBACK_OPERATION'"   # NULL-safe
        assert not_rollback_row_sql('h') == "NVL(h.rollback_status, '~') <> 'ROLLBACK_OPERATION'"
        assert IS_RB == "rollback_status = 'ROLLBACK_OPERATION'"
        assert len(ROLLBACK_ROW_STATUS) <= 30                                # VARCHAR2(30)

    def test_savings_timeline(self, captured):
        CentralQueries.get_savings_timeline(database_id=1)
        (sql,) = captured
        assert f"WHERE operation_status = 'SUCCESS' AND original_size_bytes > 0 AND {NOT_RB}" in sql

    def test_forecast_latest_row_and_duration(self, captured):
        CentralQueries.get_forecast_data(database_id=1)
        latest, duration = captured
        assert (f"FROM t_compression_history h2 WHERE {not_rollback_row_sql('h2')} ) h ON"
                in latest)
        assert f"WHERE operation_status = 'SUCCESS' AND {NOT_RB} AND duration_seconds > 0" in duration

    def test_growth_alerts(self, captured):
        CentralQueries.get_growth_alerts(database_id=1)
        (sql,) = captured
        assert f"WHERE operation_status = 'SUCCESS' AND compressed_size_bytes > 0 AND {NOT_RB} ) h ON" in sql

    def test_compression_progress_latest_row(self, captured):
        CentralQueries.get_compression_progress(database_id=1)
        (sql,) = captured
        assert f"FROM t_compression_history WHERE {NOT_RB} AND database_id = :database_id ) h ON" in sql

    def test_effectiveness_fallback(self, captured):
        CentralQueries.get_compression_effectiveness(database_id=1)
        view, fallback = captured
        assert 'v_compression_effectiveness' in view
        assert f"WHERE operation_status = 'SUCCESS' AND {NOT_RB} AND database_id = :database_id" in fallback

    def test_compare_databases(self, captured):
        CentralQueries.compare_databases()
        (sql,) = captured
        assert f"FROM t_compression_history WHERE {NOT_RB} GROUP BY database_id" in sql
        # saved space counts SUCCESS rows only (not ROLLED_BACK ones)
        assert "SUM(CASE WHEN operation_status = 'SUCCESS' THEN space_saved_mb END)" in sql

    def test_recommendations_latest_row(self, captured):
        CentralQueries.get_recommendations(database_id=1)
        (sql,) = captured
        assert f"FROM t_compression_history WHERE {NOT_RB} AND database_id = :database_id ) h ON" in sql

    def test_scheduler_export_leaves_rollbacks_out(self, captured):
        CentralQueries.get_scheduler_jobs_for_export(database_id=1, status_filter='SUCCESS')
        (sql,) = captured
        assert f"WHERE {not_rollback_row_sql('h')} AND h.database_id = :database_id" in sql

    def test_history_lists_label_rollbacks(self, captured):
        CentralQueries.get_execution_history(database_id=1)
        CentralQueries.get_recent_executions(database_id=1)
        CentralQueries.get_running_operations(database_id=1)
        CentralQueries.get_recent_operations(database_id=1)
        CentralQueries.get_scheduler_job_details(database_id=1)
        history, recent, running, operations, monitor = captured
        assert f"CASE WHEN {IS_RB} THEN 'ROLLBACK' ELSE 'COMPRESSION' END as operation_type" in history
        assert f"CASE WHEN {IS_RB} THEN NULL ELSE space_saved_pct END as savings_pct" in history
        assert f"CASE WHEN {IS_RB} THEN 'ROLLBACK (NOCOMPRESS)' ELSE compression_type_applied END as strategy" in recent
        for sql in (running, operations):
            assert f"CASE WHEN {IS_RB} THEN 'ROLLBACK' ELSE 'COMPRESSION' END as operation_type" in sql
        assert (f"CASE WHEN {rollback_row_sql('h')} THEN 'ROLLBACK (NOCOMPRESS)' "
                f"ELSE h.compression_type_applied END as strategy") in monitor

    def test_rollback_operation_details_read_the_history_row(self, captured):
        CentralQueries.get_operation_progress('ROLLBACK', 5)
        (sql,) = captured
        assert 'FROM t_compression_history WHERE history_id = :operation_id' in sql


# ============================================================================
# 2c. Reconcile: a stale rollback row is a stale direct run
# ============================================================================

def _rollback_row(central, age_hours, **kw):
    return central.add(partition_name='P1', object_type='PARTITION',
                       operation_status='IN_PROGRESS', compression_type_applied='NONE',
                       compression_clause='ROLLBACK of history_id 5', rollback_possible='N',
                       rollback_status=ROLLBACK_ROW_STATUS, age_minutes=age_hours * 60.0, **kw)


@pytest.mark.unit
class TestReconcileRollbackRow:

    def test_stale_rollback_row_is_failed_as_interrupted(self, dbs):
        central, target = dbs
        hid = _rollback_row(central, 48)
        out = TargetQueries.reconcile_operations(1)
        assert central.status(hid) == 'FAILED'
        (upd,) = out['updated']
        assert upd['history_id'] == hid and upd['job_name'] == 'ROLLBACK of history_id 5'
        assert 'after the rollback (NOCOMPRESS move) started' in upd['reason']
        assert 'before rolling back again' in central.rows[hid]['error_message']
        # never looked up as a scheduler job
        assert not any('dba_scheduler' in s for s, _ in target.queries)

    def test_live_rollback_row_is_left_alone(self, dbs):
        central, target = dbs
        hid = _rollback_row(central, 48)
        tq._set_active(tq._ACTIVE_HISTORY_IDS, hid, True)
        try:
            out = TargetQueries.reconcile_operations(1)
        finally:
            tq._set_active(tq._ACTIVE_HISTORY_IDS, hid, False)
        assert central.status(hid) == 'IN_PROGRESS' and out['running'] == 1

    def test_recent_or_still_moving_rollback_row_is_left_alone(self, dbs):
        central, target = dbs
        young = _rollback_row(central, 1)
        out = TargetQueries.reconcile_operations(1)
        assert central.status(young) == 'IN_PROGRESS' and out['running'] == 1
        central.rows[young]['age_minutes'] = 48 * 60.0
        target.sessions = 1                    # a target session is running its MOVE
        out = TargetQueries.reconcile_operations(1)
        assert central.status(young) == 'IN_PROGRESS' and out['updated'] == []

    def test_direct_run_row_keeps_its_message(self, dbs):
        central, _ = dbs
        hid = central.add(operation_status='IN_PROGRESS', compression_clause='ALTER TABLE ...',
                          age_minutes=48 * 60.0)
        TargetQueries.reconcile_operations(1)
        assert 'after the synchronous compression started' in central.rows[hid]['error_message']


# ============================================================================
# 2d. History page
# ============================================================================

def _history_df():
    return pd.DataFrame([
        {'EXECUTION_ID': 42, 'DATABASE_ID': 1, 'TABLE_OWNER': 'APP', 'TABLE_NAME': 'ORDERS',
         'PARTITION_NAME': 'P1', 'SUBPARTITION_NAME': None, 'OBJECT_TYPE': 'PARTITION',
         'STRATEGY': 'OLTP', 'OPERATION_TYPE': 'COMPRESSION', 'STATUS': 'SUCCESS',
         'ROLLBACK_STATUS': None, 'SAVINGS_PCT': 60.0, 'ERROR_MESSAGE': None,
         'EXECUTED_AT': pd.Timestamp('2026-09-01 08:00')},
        {'EXECUTION_ID': 43, 'DATABASE_ID': 1, 'TABLE_OWNER': 'APP', 'TABLE_NAME': 'ORDERS',
         'PARTITION_NAME': 'P2', 'SUBPARTITION_NAME': None, 'OBJECT_TYPE': 'PARTITION',
         'STRATEGY': 'NONE', 'OPERATION_TYPE': 'ROLLBACK', 'STATUS': 'SUCCESS',
         'ROLLBACK_STATUS': ROLLBACK_ROW_STATUS, 'SAVINGS_PCT': None, 'ERROR_MESSAGE': None,
         'EXECUTED_AT': pd.Timestamp('2026-09-02 08:00')},
    ])


@pytest.mark.unit
class TestHistoryPage:

    def test_mask_from_operation_type_or_marker(self):
        df = _history_df()
        df.columns = [c.lower() for c in df.columns]
        assert page_04_history._rollback_rows_mask(df).tolist() == [False, True]
        assert page_04_history._rollback_rows_mask(
            df.drop(columns=['operation_type'])).tolist() == [False, True]
        assert page_04_history._rollback_rows_mask(
            df.drop(columns=['operation_type', 'rollback_status'])).tolist() == [False, False]

    def test_rollback_rows_labelled_and_not_offered(self, monkeypatch):
        monkeypatch.setattr(CentralQueries, 'get_execution_history', lambda **k: _history_df())
        monkeypatch.setattr(Selectbox, 'index', property(_selectbox_index))

        def page():
            from hcc_advisor.views.page_04_history import show_history_page
            show_history_page()
        at = _operator_app(page).run()
        assert not at.exception
        table = at.dataframe[0].value
        assert table['Operation'].tolist() == ['Compression', 'Rollback']
        assert table['Rollback'].isna().tolist() == [True, True]      # marker not shown as a state
        assert next(m for m in at.metric if m.label == 'Avg Savings').value == '60.0%'
        (picker,) = [s for s in at.selectbox if s.key == 'rollback_select']
        assert len(picker.options) == 1 and 'partition P1' in picker.options[0]


# ============================================================================
# 3. Direct runs refuse overlapping (not only exact) open rows
# ============================================================================

@pytest.mark.unit
class TestDirectRunOverlap:

    @pytest.mark.parametrize('open_seg, run_seg, blocker_label', [
        ({'partition_name': 'P1'}, (None, None), 'APP.ORDERS partition P1'),        # table run
        ({}, ('P1', None), 'APP.ORDERS'),                                           # table job
        ({'partition_name': 'P1'}, ('P1', 'SP1'), 'APP.ORDERS partition P1'),       # parent
        ({'partition_name': 'P1', 'subpartition_name': 'SP2'}, ('P1', None),
         'APP.ORDERS subpartition SP2'),                                            # its subpart
    ])
    @pytest.mark.parametrize('status', ['QUEUED', 'IN_PROGRESS'])
    def test_overlapping_open_row_refuses_before_any_ddl(self, dbs, open_seg, run_seg,
                                                         blocker_label, status):
        central, target = dbs
        blocker = central.add(operation_status=status, **open_seg)
        part, sub = run_seg
        res = TargetQueries.execute_compression(1, 'APP', 'ORDERS', 'OLTP', part, dry_run=False,
                                                subpartition_name=sub)
        assert res['success'] is False and res['duplicate'] is True
        assert f"overlaps {blocker_label}, which has a queued or running compression " \
               f"(history_id {blocker}, {status})" in res['error']
        assert 'not compressed' in res['error']
        assert target.plsql == [] and list(central.rows) == [blocker]      # no own row

    def test_exact_segment_message_unchanged(self, dbs):
        central, target = dbs
        blocker = central.add(partition_name='P1', operation_status='QUEUED')
        res = TargetQueries.execute_compression(1, 'APP', 'ORDERS', 'OLTP', 'P1', dry_run=False)
        assert res['duplicate'] is True
        assert res['error'].startswith(f"APP.ORDERS partition P1 is already queued or running "
                                       f"(history_id {blocker}, QUEUED)")

    def test_other_partition_does_not_block(self, dbs):
        central, target = dbs
        central.add(partition_name='P2', operation_status='IN_PROGRESS')
        res = TargetQueries.execute_compression(1, 'APP', 'ORDERS', 'OLTP', 'P1', dry_run=False)
        assert res['success'] is True, res
        # checked before and after its own row; its own row never blocks it
        assert len(_overlap_queries(central)) == 2

    @pytest.mark.parametrize('unique_index', [False, True])
    def test_overlap_written_after_the_check_closes_own_row(self, dbs, unique_index):
        central, target = dbs
        central.unique_open = unique_index
        blockers = []
        _on_first_overlap_check(central, lambda: blockers.append(central.add(
            operation_status='IN_PROGRESS', compression_clause='HCC_ORDERS_9')))

        res = TargetQueries.execute_compression(1, 'APP', 'ORDERS', 'OLTP', 'P1', dry_run=False)

        assert res['success'] is False and res['duplicate'] is True
        assert f"overlaps APP.ORDERS, which has a queued or running compression " \
               f"(history_id {blockers[0]}, IN_PROGRESS)" in res['error']
        assert target.plsql == []
        (own,) = [r for r in central.rows.values() if r['history_id'] != blockers[0]]
        assert own['operation_status'] == 'FAILED' and own['partition_name'] == 'P1'
        assert own['error_message'].startswith(
            f"Not run: blocked by APP.ORDERS (history_id {blockers[0]}, IN_PROGRESS)")
        assert own['history_id'] not in tq._active_snapshot(tq._ACTIVE_HISTORY_IDS)

    def test_post_insert_check_failure_closes_own_row(self, dbs):
        central, target = dbs

        def fail_second_check(s, p):
            if s.startswith('SELECT history_id, operation_status, partition_name') and central.rows:
                raise oracledb.DatabaseError('ORA-03113: end-of-file on communication channel')
        central.after_query = fail_second_check

        res = TargetQueries.execute_compression(1, 'APP', 'ORDERS', 'OLTP', 'P1', dry_run=False)

        assert res['success'] is False and 'ORA-03113' in res['error']
        (own,) = central.rows.values()
        assert own['operation_status'] == 'FAILED' and target.plsql == []

    def test_rollback_in_progress_blocks_a_direct_run(self, dbs):
        central, target = dbs
        rb = _rollback_row(central, 0)
        res = TargetQueries.execute_compression(1, 'APP', 'ORDERS', 'OLTP', dry_run=False)
        assert res['duplicate'] is True
        assert f"which has a queued or running rollback (history_id {rb}, IN_PROGRESS)" in res['error']
        assert target.plsql == []
