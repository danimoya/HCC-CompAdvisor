"""
Unit tests for the scheduler job queue and the stale-operation reconciler:

- the queue keeps QUEUED rows in place: enqueue only inserts, a drainer claims
  one row atomically (QUEUED -> IN_PROGRESS, rowcount 1) and submits it; a
  second claimer gets 0 rows and skips; blocked / retryable items go back to
  QUEUED at their FIFO position, failures end FAILED - nothing is dropped;
- the duplicate/concurrency key includes partition and subpartition;
- one open row per segment (UNQ_HISTORY_OPEN_SEGMENT, patch 20260924): the
  patch/schema SQL, a racing add counted as a duplicate (ORA-00001), no MOVE
  or CREATE_JOB when the history insert is rejected or fails, claims and
  closes that never collide;
- reconcile_operations maps scheduler outcomes (running / succeeded / failed /
  stopped / missing) and stale synchronous rows / advisor runs, updating by
  history_id + database_id and counting only rows actually updated;
- before/after sizes use the job's own partition / subpartition segment;
- a long DDL no longer breaks the history insert; batch_execute survives a
  bad item; index rebuilds are counted only when they succeed; the Wizard and
  bulk submit send leaf segments only.

No database: the central T_COMPRESSION_HISTORY / T_ADVISOR_RUN rows live in an
in-memory fake that interprets the queue statements; the target's scheduler
views and DBA_SEGMENTS are faked as well. Both reject binds that don't match
the statement's placeholders, like python-oracledb.
"""
import re
from contextlib import contextmanager
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

import oracledb
import pandas as pd
import pytest

from hcc_advisor.utils import target_queries as tq
from hcc_advisor.utils.central_connector import CentralConnector
from hcc_advisor.utils.central_queries import CentralQueries, history_clause
from hcc_advisor.utils.sql_executor import parse_sql_file, parse_sql_text
from hcc_advisor.utils.target_connector import TargetConnector
from hcc_advisor.utils.target_queries import TargetQueries, segments_overlap


def _norm(sql):
    return " ".join(sql.split())


def _check_binds(sql, params, extra=()):
    """Like python-oracledb: binds must match the statement's placeholders."""
    names = set(re.findall(r":(\w+)", re.sub(r"'[^']*'", "''", sql)))
    assert names == set(params or {}) | set(extra), \
        f"bind mismatch: sql={sorted(names)} binds={sorted(params or {})}\n{sql}"


def _df(rows, columns):
    return pd.DataFrame(rows, columns=columns)


T0 = datetime(2026, 9, 1, 8, 0, 0)


# ============================================================================
# Fake central database (T_COMPRESSION_HISTORY / T_ADVISOR_RUN)
# ============================================================================

class FakeCentral:
    def __init__(self):
        self.rows = {}
        self.next_id = 100
        self.clock = 0
        self.advisor_runs = {}
        self.statements = []
        self.analysis_updates = []
        self.fail_on = {}          # needle -> exception, for any statement
        self.lost_updates = set()  # history_ids whose next close/success UPDATE hits 0 rows
        self.unique_open = False   # enforce UNQ_HISTORY_OPEN_SEGMENT (patch applied)
        self.after_query = None    # hook(sql, binds) after a query: another session commits
        self.insert_errors = {}    # (object_name, partition_name) -> error of that row's INSERT

    @staticmethod
    def _open_key(db, owner, obj, part, sub):
        return (db, owner, obj, part or '~', sub or '~')

    def _check_unique_open(self, key, exclude=None):
        """UNQ_HISTORY_OPEN_SEGMENT: no other open row may have this key."""
        if not self.unique_open:
            return
        for r in self.rows.values():
            if (r['history_id'] != exclude and r['operation_status'] in ('QUEUED', 'IN_PROGRESS')
                    and self._open_key(r['database_id'], r['owner'], r['object_name'],
                                       r['partition_name'], r['subpartition_name']) == key):
                raise oracledb.IntegrityError(
                    'ORA-00001: unique constraint (HCC.UNQ_HISTORY_OPEN_SEGMENT) violated')

    def _check_row_stays_unique(self, row):
        self._check_unique_open(self._open_key(row['database_id'], row['owner'], row['object_name'],
                                               row['partition_name'], row['subpartition_name']),
                                exclude=row['history_id'])

    def _tick(self):
        self.clock += 1
        return T0 + timedelta(minutes=self.clock)

    def add(self, **kw):
        hid = kw.pop('history_id', None)
        if hid is None:
            self.next_id += 1
            hid = self.next_id
        row = dict(
            database_id=1, owner='APP', object_name='ORDERS', object_type='TABLE',
            partition_name=None, subpartition_name=None,
            compression_type_applied='QUERY HIGH', compression_clause=None,
            parallel_degree=4, operation_status='QUEUED', start_time=self._tick(),
            original_size_bytes=None, compressed_size_bytes=None,
            compression_ratio_achieved=None, duration_seconds=None,
            error_message=None, error_code=None, executed_by=None, original_ddl=None,
            age_minutes=0.0,
        )
        row.update(kw)
        row['history_id'] = hid
        self.rows[hid] = row
        return hid

    def status(self, hid):
        return self.rows[hid]['operation_status']

    def dml_statements(self, needle):
        return [(s, p) for kind, s, p in self.statements if kind == 'dml' and needle in s]

    def _maybe_fail(self, s):
        for needle, exc in self.fail_on.items():
            if needle in s:
                raise exc

    # -- SELECT --------------------------------------------------------------
    def query(self, sql, params=None, raise_on_error=False):
        s, p = _norm(sql), dict(params or {})
        _check_binds(s, p)
        self.statements.append(('query', s, p))
        self._maybe_fail(s)
        result = self._select(s, p)
        if self.after_query:
            self.after_query(s, p)
        return result

    def _select(self, s, p):
        rows = list(self.rows.values())
        if 'FROM t_compression_history' not in s:
            raise AssertionError(f"unexpected central query: {s}")

        if s.startswith('SELECT owner, object_name, partition_name, subpartition_name'):
            sel = [r for r in rows if r['database_id'] == p['db']
                   and r['operation_status'] in ('QUEUED', 'IN_PROGRESS')]
            return _df([[r['owner'], r['object_name'], r['partition_name'], r['subpartition_name']]
                        for r in sel], ['OWNER', 'OBJECT_NAME', 'PARTITION_NAME', 'SUBPARTITION_NAME'])
        if s.startswith('SELECT history_id, operation_status FROM t_compression_history'):
            assert 'ROWNUM = 1' in s                                    # _open_segment_row
            key = self._open_key(p['db'], p['o'], p['t'], p['p'], p['sp'])
            sel = [r for r in rows if r['operation_status'] in ('QUEUED', 'IN_PROGRESS')
                   and self._open_key(r['database_id'], r['owner'], r['object_name'],
                                      r['partition_name'], r['subpartition_name']) == key]
            return _df([[r['history_id'], r['operation_status']] for r in sel[:1]],
                       ['HISTORY_ID', 'OPERATION_STATUS'])
        if "WHERE operation_status = 'QUEUED'" in s:
            sel = [r for r in rows if r['operation_status'] == 'QUEUED'
                   and ('db' not in p or r['database_id'] == p['db'])]
            assert 'ORDER BY start_time, history_id' in s
            sel.sort(key=lambda r: (r['start_time'], r['history_id']))
            cols = ['HISTORY_ID', 'DATABASE_ID', 'OWNER', 'OBJECT_NAME', 'PARTITION_NAME',
                    'SUBPARTITION_NAME', 'COMPRESSION_TYPE_APPLIED', 'PARALLEL_DEGREE', 'START_TIME']
            return _df([[r['history_id'], r['database_id'], r['owner'], r['object_name'],
                         r['partition_name'], r['subpartition_name'], r['compression_type_applied'],
                         r['parallel_degree'], r['start_time']] for r in sel], cols)
        if 'history_id <> :hid' in s:
            sel = [r for r in rows if r['database_id'] == p['db'] and r['owner'] == p['o']
                   and r['object_name'] == p['t'] and r['operation_status'] == 'IN_PROGRESS'
                   and r['history_id'] != p['hid']]
            return _df([[r['history_id'], r['compression_clause'], r['partition_name'],
                         r['subpartition_name']] for r in sel],
                       ['HISTORY_ID', 'COMPRESSION_CLAUSE', 'PARTITION_NAME', 'SUBPARTITION_NAME'])
        if 'age_minutes' in s:
            sel = sorted((r for r in rows if r['database_id'] == p['db']
                          and r['operation_status'] == 'IN_PROGRESS'), key=lambda r: r['history_id'])
            cols = ['HISTORY_ID', 'OWNER', 'OBJECT_NAME', 'PARTITION_NAME', 'SUBPARTITION_NAME',
                    'COMPRESSION_TYPE_APPLIED', 'COMPRESSION_CLAUSE', 'ORIGINAL_SIZE_BYTES',
                    'AGE_MINUTES']
            return _df([[r['history_id'], r['owner'], r['object_name'], r['partition_name'],
                         r['subpartition_name'], r['compression_type_applied'],
                         r['compression_clause'], r['original_size_bytes'], r['age_minutes']]
                        for r in sel], cols)
        if 'total_dop' in s:
            total = sum(r['parallel_degree'] or 1 for r in rows
                        if r['database_id'] == p['db'] and r['operation_status'] == 'IN_PROGRESS')
            return _df([[total]], ['TOTAL_DOP'])
        raise AssertionError(f"unexpected central query: {s}")

    # -- INSERT / UPDATE -----------------------------------------------------
    def _insert(self, p):
        assert set(p) >= {'db', 'owner', 'tbl', 'otype', 'part', 'sub', 'comp', 'dop', 'executed_by'}
        if (p['tbl'], p['part']) in self.insert_errors:
            raise oracledb.DatabaseError(self.insert_errors[(p['tbl'], p['part'])])
        self._check_unique_open(self._open_key(p['db'], p['owner'], p['tbl'], p['part'], p['sub']))
        return self.add(database_id=p['db'], owner=p['owner'], object_name=p['tbl'],
                        object_type=p['otype'], partition_name=p['part'],
                        subpartition_name=p['sub'], compression_type_applied=p['comp'],
                        parallel_degree=p['dop'], executed_by=p['executed_by'],
                        operation_status='QUEUED')

    def dml(self, sql, params=None, commit=True, raise_on_error=False):
        s, p = _norm(sql), dict(params or {})
        _check_binds(s, p)
        self.statements.append(('dml', s, p))
        self._maybe_fail(s)
        if s.startswith('UPDATE t_compression_history') and 'hist_id' in p:
            # execute_compression's outcome, on its own IN_PROGRESS row
            assert s.endswith('WHERE history_id = :hist_id')
            row = self.rows.get(p['hist_id'])
            if row is None:
                return 0
            if "SET operation_status = 'SUCCESS'" in s:
                row.update(operation_status='SUCCESS', compressed_size_bytes=p['comp_size'])
            else:
                assert "SET operation_status = 'FAILED'" in s
                row.update(operation_status='FAILED', error_message=p.get('err'))
            return 1
        if s.startswith('UPDATE t_compression_history'):
            row = self.rows.get(p.get('hid'))
            if row is None or ('db' in p and row['database_id'] != p['db']):
                return 0
            assert 'history_id = :hid' in s and 'database_id = :db' in s
            if "SET operation_status = 'IN_PROGRESS'" in s:            # claim
                assert "AND operation_status = 'QUEUED'" in s
                if row['operation_status'] != 'QUEUED':
                    return 0
                self._check_row_stays_unique(row)
                row.update(operation_status='IN_PROGRESS', compression_clause=p['job'],
                           original_ddl=p['ddl'], start_time=self._tick(), age_minutes=0.0,
                           error_message=None)
                return 1
            if "SET operation_status = 'QUEUED'" in s:                 # requeue
                if row['operation_status'] != 'IN_PROGRESS':
                    return 0
                self._check_row_stays_unique(row)
                row.update(operation_status='QUEUED', compression_clause=None,
                           error_message=p['msg'])
                if 'orig_start' in p:
                    row['start_time'] = p['orig_start']
                return 1
            if row['history_id'] in self.lost_updates:
                return 0
            if 'SET operation_status = :st' in s:                      # close
                if row['operation_status'] != p['from_st']:
                    return 0
                row.update(operation_status=p['st'], error_message=p['msg'],
                           error_code=p['code'], duration_seconds=p['dur'])
                return 1
            if "SET operation_status = 'SUCCESS'" in s:
                assert "AND operation_status = 'IN_PROGRESS'" in s
                if row['operation_status'] != 'IN_PROGRESS':
                    return 0
                row.update(operation_status='SUCCESS', compressed_size_bytes=p['cs'],
                           compression_ratio_achieved=p['ratio'], duration_seconds=p['dur'],
                           error_message=None)
                return 1
            if 'SET original_size_bytes = :sz' in s:
                row['original_size_bytes'] = p['sz']
                return 1
        if s.startswith('UPDATE t_compression_analysis'):
            self.analysis_updates.append(p)
            return 1
        if s.startswith('UPDATE t_advisor_run'):
            excluded = {v for k, v in p.items() if re.fullmatch(r'r\d+', k)}
            n = 0
            for rid, run in self.advisor_runs.items():
                if (run['database_id'] == p['db'] and run['status'] == 'RUNNING'
                        and run['age_hours'] > p['hrs'] and rid not in excluded):
                    run.update(status='FAILED', error=p['msg'])
                    n += 1
            return n
        raise AssertionError(f"unexpected central DML: {s}")

    def dml_returning(self, sql, params=None, out_bind='new_id', commit=True):
        s, p = _norm(sql), dict(params or {})
        _check_binds(s, p, extra=(out_bind,))
        self.statements.append(('dml', s, p))
        assert s.startswith('INSERT INTO t_compression_history') and 'RETURNING history_id' in s
        try:
            self._maybe_fail(s)
            if 'SEQ_EXECUTION_ID.NEXTVAL' in s:                  # store_compression_history
                self._check_unique_open(self._open_key(
                    p['database_id'], p['owner'], p['object_name'],
                    p['partition_name'], p['subpartition_name']))
                return self.add(
                    database_id=p['database_id'], owner=p['owner'], object_name=p['object_name'],
                    object_type=p['object_type'], partition_name=p['partition_name'],
                    subpartition_name=p['subpartition_name'],
                    compression_type_applied=p['compression_type_applied'],
                    compression_clause=p['compression_clause'], parallel_degree=p['parallel_degree'],
                    operation_status=p['operation_status'], executed_by=p['executed_by'],
                    original_size_bytes=p['original_size_bytes'], original_ddl=p['original_ddl'])
            assert "'QUEUED', SYSTIMESTAMP" in s
            return self._insert(p)
        except oracledb.Error:
            return None   # CentralConnector.execute_dml_returning logs it and returns None

    @contextmanager
    def connection(self):
        central = self

        class _BatchError:
            """An executemany(batcherrors=True) row error, like oracledb's."""
            def __init__(self, offset, message):
                self.offset, self.message = offset, message

            def __str__(self):
                return self.message

        class _Cursor:
            def __init__(self, conn):
                self.conn = conn
                self.batch_errors = []

            def executemany(self, sql, rows, batcherrors=False):
                s = _norm(sql)
                central.statements.append(('executemany', s, rows))
                central._maybe_fail(s)
                assert s.startswith('INSERT INTO t_compression_history')
                assert 'DELETE' not in s.upper()
                for r in rows:
                    _check_binds(s, r)
                self.batch_errors = []
                for i, r in enumerate(rows):
                    try:
                        self.conn.pending.append(central._insert(r))
                    except oracledb.Error as e:
                        if not batcherrors:
                            raise
                        self.batch_errors.append(_BatchError(i, str(e)))

            def getbatcherrors(self):
                return list(self.batch_errors)

            def execute(self, sql, params=None):
                raise AssertionError(f"unexpected cursor.execute: {sql}")

            def close(self):
                pass

        class _Conn:
            """Rows inserted through this connection vanish on rollback."""
            commits = rollbacks = 0

            def __init__(self):
                self.pending = []

            def cursor(self):
                return _Cursor(self)

            def commit(self):
                _Conn.commits += 1
                self.pending.clear()

            def rollback(self):
                _Conn.rollbacks += 1
                for hid in self.pending:
                    central.rows.pop(hid, None)
                self.pending.clear()

        yield _Conn()


# ============================================================================
# Fake target database (scheduler views, DBA_SEGMENTS, V$SESSION)
# ============================================================================

class FakeTarget:
    def __init__(self):
        self.sizes = {}          # DBA_SEGMENTS.PARTITION_NAME (None = table) -> bytes or [bytes...]
        self.running = set()
        self.jobs = {}           # job_name -> state
        self.runs = {}           # job_name -> [run dict, ...] (ascending log_id)
        self.sessions = 0
        self.fail_on = {}        # needle -> exception
        self.plsql = []
        self.plsql_error = None
        self.queries = []

    def query(self, database_id, sql, params=None, conn_config=None, raise_on_error=False):
        s, p = _norm(sql), dict(params or {})
        _check_binds(s, p)
        self.queries.append((s, p))
        for needle, exc in self.fail_on.items():
            if needle in s:
                raise exc
        if 'FROM dba_segments' in s:
            v = self.sizes.get(p.get('partition_name'), 0)
            if isinstance(v, list):
                v = v.pop(0) if len(v) > 1 else v[0]
            return _df([[v]], ['SIZE_BYTES'])
        if 'v$parameter' in s:
            return _df([['8']], ['VALUE'])
        if 'FROM all_tab_columns' in s:                              # execute_compression LOB check
            return _df([[0]], ['LOB_COUNT'])
        if 'FROM all_indexes' in s:                                  # unusable indexes after a MOVE
            return _df([], ['OWNER', 'INDEX_NAME'])
        names = [v for k, v in sorted(p.items()) if re.fullmatch(r'j\d+', k)]
        if 'FROM dba_scheduler_running_jobs' in s:
            return _df([[n] for n in names if n in self.running], ['JOB_NAME'])
        if 'FROM dba_scheduler_jobs' in s:
            return _df([[n, self.jobs[n]] for n in names if n in self.jobs], ['JOB_NAME', 'STATE'])
        if 'FROM dba_scheduler_job_run_details' in s:
            out, log_id = [], 0
            for n in names:
                for run in self.runs.get(n, []):
                    log_id += 1
                    out.append([n, run['status'], run.get('error'), run.get('info'),
                                run.get('seconds'), log_id])
            return _df(out, ['JOB_NAME', 'STATUS', 'ERROR_NUM', 'ADDITIONAL_INFO',
                             'RUN_SECONDS', 'LOG_ID'])
        if 'FROM v$session' in s:
            return _df([[self.sessions]], ['N'])
        raise AssertionError(f"unexpected target query: {s}")

    def execute_plsql(self, database_id, block, params=None, commit=True, conn_config=None,
                      raise_on_error=False):
        self.plsql.append(block)
        if self.plsql_error is not None:
            raise self.plsql_error
        return True

    def size_queries(self):
        return [p for s, p in self.queries if 'FROM dba_segments' in s]


@pytest.fixture
def dbs(monkeypatch):
    central, target = FakeCentral(), FakeTarget()
    monkeypatch.setattr(CentralConnector, 'execute_query', central.query)
    monkeypatch.setattr(CentralConnector, 'execute_dml', central.dml)
    monkeypatch.setattr(CentralConnector, 'execute_dml_returning', central.dml_returning)
    monkeypatch.setattr(CentralConnector, 'get_connection', central.connection)
    monkeypatch.setattr(TargetConnector, 'execute_query', target.query)
    monkeypatch.setattr(TargetConnector, 'execute_plsql', target.execute_plsql)
    monkeypatch.setattr(tq, '_acting_user', lambda: 'alice')
    return central, target


def _item(**kw):
    item = {'database_id': 1, 'owner': 'APP', 'table_name': 'ORDERS',
            'compression_type': 'QUERY HIGH', 'dop': 2}
    item.update(kw)
    return item


# ============================================================================
# Duplicate / concurrency key
# ============================================================================

@pytest.mark.unit
class TestSegmentsOverlap:

    def test_different_partitions_may_run_concurrently(self):
        assert segments_overlap('P1', None, 'P2', None) is False

    def test_same_partition_overlaps(self):
        assert segments_overlap('P1', None, 'p1', None) is True

    def test_table_level_job_overlaps_partitions_both_ways(self):
        assert segments_overlap(None, None, 'P1', None) is True
        assert segments_overlap('P1', None, None, None) is True

    def test_partition_overlaps_its_subpartitions(self):
        assert segments_overlap('P1', None, 'P1', 'SP1') is True
        assert segments_overlap('P1', 'SP1', 'P1', None) is True

    def test_subpartitions(self):
        assert segments_overlap('P1', 'SP1', 'P1', 'SP2') is False
        assert segments_overlap('P1', 'SP1', 'P1', 'SP1') is True
        assert segments_overlap('P1', 'SP1', 'P2', 'SP9') is False

    def test_missing_names_are_treated_as_table_level(self):
        assert segments_overlap(float('nan'), None, 'P1', None) is True
        assert segments_overlap('None', None, 'P1', None) is True


# ============================================================================
# Enqueue
# ============================================================================

@pytest.mark.unit
class TestEnqueue:

    def test_inserts_new_queued_rows_without_touching_existing_ones(self, dbs):
        central, _ = dbs
        other_db = central.add(database_id=2, object_name='CUSTOMERS')
        before = dict(central.rows[other_db])

        out = TargetQueries.enqueue_compression_jobs([
            _item(partition_name='P1'), _item(partition_name='P2', compression_type='QUERY_HIGH'),
        ])

        assert out == {'added': 2, 'duplicates': 0, 'rejected': 0, 'errors': []}
        assert central.rows[other_db] == before                       # untouched
        new = [r for r in central.rows.values() if r['database_id'] == 1]
        assert {r['partition_name'] for r in new} == {'P1', 'P2'}
        assert all(r['operation_status'] == 'QUEUED' and r['executed_by'] == 'alice'
                   and r['object_type'] == 'PARTITION' for r in new)
        assert {r['compression_type_applied'] for r in new} == {'QUERY HIGH'}  # CHECK-safe spelling
        assert not [s for k, s, _ in central.statements if 'DELETE' in s.upper()]
        (kind, sql, rows), = [x for x in central.statements if x[0] == 'executemany']
        assert "'QUEUED', SYSTIMESTAMP" in sql and len(rows) == 2

    def test_segment_already_queued_or_running_is_a_duplicate(self, dbs):
        central, _ = dbs
        central.add(partition_name='P1', operation_status='QUEUED')
        central.add(partition_name='P2', operation_status='IN_PROGRESS')
        central.add(partition_name='P3', operation_status='SUCCESS')

        out = TargetQueries.enqueue_compression_jobs([
            _item(partition_name='P1'), _item(partition_name='P2'),
            _item(partition_name='P3'), _item(partition_name='P4'), _item(partition_name='P4'),
        ])

        assert (out['added'], out['duplicates']) == (2, 3)         # P3 again + P4 once
        queued = sorted(r['partition_name'] for r in central.rows.values()
                        if r['operation_status'] == 'QUEUED')
        assert queued == ['P1', 'P3', 'P4']

    def test_invalid_items_are_rejected_with_a_reason(self, dbs):
        central, _ = dbs
        out = TargetQueries.enqueue_compression_jobs([
            _item(table_name='BAD NAME'), _item(owner='SYS'),
            _item(compression_type='SUPER'), _item(dop=500), _item(database_id=None),
            _item(),
        ])
        assert out['added'] == 1 and out['rejected'] == 5
        assert len(out['errors']) == 5
        assert any('SYS' in e for e in out['errors'])

    def test_subpartition_item(self, dbs):
        central, _ = dbs
        out = TargetQueries.enqueue_compression_jobs(
            [_item(partition_name='p1', subpartition_name='sp1')])
        assert out['added'] == 1
        row = next(iter(central.rows.values()))
        assert (row['partition_name'], row['subpartition_name'], row['object_type']) == \
            ('P1', 'SP1', 'SUBPARTITION')

    def test_write_failure_is_reported_not_raised(self, dbs):
        central, _ = dbs
        central.fail_on['INSERT INTO t_compression_history'] = oracledb.DatabaseError('ORA-02290')
        out = TargetQueries.enqueue_compression_jobs([_item(), _item(partition_name='P1')])
        assert out['added'] == 0 and out['rejected'] == 2
        assert 'ORA-02290' in out['errors'][0]


# ============================================================================
# Claim / submit / drain
# ============================================================================

@pytest.mark.unit
class TestClaimAndSubmit:

    def test_claim_is_atomic_second_claimer_skips(self, dbs):
        central, target = dbs
        hid = central.add(partition_name='P1', parallel_degree=2)
        # Two tabs load the same queue ...
        view_a = TargetQueries.get_queued_compression_jobs(1)
        view_b = TargetQueries.get_queued_compression_jobs(1)

        first = TargetQueries.submit_queued_job(view_a[0])
        second = TargetQueries.submit_queued_job(view_b[0])

        assert first['status'] == 'SUBMITTED'
        assert second['status'] == 'NOT_CLAIMED'
        assert len(target.plsql) == 1                                 # one CREATE_JOB only
        row = central.rows[hid]
        assert row['operation_status'] == 'IN_PROGRESS'
        assert row['compression_clause'] == f'HCC_ORDERS_{hid}' == first['job_name']
        assert 'MOVE PARTITION P1' in row['original_ddl']
        claims = central.dml_statements("SET operation_status = 'IN_PROGRESS'")
        assert len(claims) == 2
        for sql, binds in claims:
            assert "WHERE history_id = :hid AND database_id = :db AND operation_status = 'QUEUED'" in sql
            assert binds['hid'] == hid and binds['db'] == 1

    def test_claimed_row_is_the_job_row_written_before_create_job(self, dbs):
        central, target = dbs
        hid = central.add()
        seen = {}

        def create_job(database_id, block, **kw):
            seen['status'] = central.status(hid)
            seen['clause'] = central.rows[hid]['compression_clause']
            target.plsql.append(block)
            return True
        with patch.object(TargetConnector, 'execute_plsql', side_effect=create_job):
            res = TargetQueries.submit_queued_job(TargetQueries.get_queued_compression_jobs(1)[0])

        assert res['status'] == 'SUBMITTED'
        assert seen == {'status': 'IN_PROGRESS', 'clause': f'HCC_ORDERS_{hid}'}
        assert f"job_name   => 'HCC_ORDERS_{hid}'" in target.plsql[0]

    def test_before_size_is_the_partition_segment_taken_before_create_job(self, dbs):
        central, target = dbs
        target.sizes = {None: 10_000, 'P1': 1_000}
        hid = central.add(partition_name='P1')
        order = []
        target.query = _record_order(target.query, order, 'size')
        target.execute_plsql = _record_order(target.execute_plsql, order, 'create_job')
        with patch.object(TargetConnector, 'execute_query', target.query), \
                patch.object(TargetConnector, 'execute_plsql', target.execute_plsql):
            TargetQueries.submit_queued_job(TargetQueries.get_queued_compression_jobs(1)[0])

        assert order == ['size', 'create_job']
        assert target.size_queries() == [{'owner': 'APP', 'table_name': 'ORDERS',
                                          'partition_name': 'P1'}]
        assert central.rows[hid]['original_size_bytes'] == 1_000

    def test_subpartition_job_moves_and_sizes_the_subpartition(self, dbs):
        central, target = dbs
        target.sizes = {'SP1': 300}
        hid = central.add(partition_name='P1', subpartition_name='SP1')
        res = TargetQueries.submit_queued_job(TargetQueries.get_queued_compression_jobs(1)[0])
        assert res['status'] == 'SUBMITTED'
        assert 'MOVE SUBPARTITION SP1' in target.plsql[0]
        assert target.size_queries()[0]['partition_name'] == 'SP1'
        assert central.rows[hid]['original_size_bytes'] == 300

    def test_item_blocked_by_running_job_on_same_segment_stays_queued(self, dbs):
        central, target = dbs
        central.add(partition_name='P1', operation_status='IN_PROGRESS',
                    compression_clause='HCC_ORDERS_1')
        hid = central.add(partition_name='P1')
        orig_start = central.rows[hid]['start_time']

        res = TargetQueries.submit_queued_job(TargetQueries.get_queued_compression_jobs(1)[0])

        assert res['status'] == 'BLOCKED'
        assert target.plsql == []
        row = central.rows[hid]
        assert row['operation_status'] == 'QUEUED'
        assert row['compression_clause'] is None
        assert row['start_time'] == orig_start                        # FIFO position kept
        assert 'HCC_ORDERS_1' in row['error_message']

    def test_other_partition_of_a_running_table_is_submitted(self, dbs):
        central, target = dbs
        central.add(partition_name='P1', operation_status='IN_PROGRESS',
                    compression_clause='HCC_ORDERS_1')
        hid = central.add(partition_name='P2')
        res = TargetQueries.submit_queued_job(TargetQueries.get_queued_compression_jobs(1)[0])
        assert res['status'] == 'SUBMITTED'
        assert central.status(hid) == 'IN_PROGRESS'

    def test_table_level_item_waits_for_a_running_partition(self, dbs):
        central, _ = dbs
        central.add(partition_name='P1', operation_status='IN_PROGRESS',
                    compression_clause='HCC_ORDERS_1')
        hid = central.add()
        res = TargetQueries.submit_queued_job(TargetQueries.get_queued_compression_jobs(1)[0])
        assert res['status'] == 'BLOCKED' and central.status(hid) == 'QUEUED'

    def test_create_job_error_marks_the_row_failed(self, dbs):
        central, target = dbs
        target.plsql_error = oracledb.DatabaseError('ORA-27486: insufficient privileges')
        hid = central.add()
        res = TargetQueries.submit_queued_job(TargetQueries.get_queued_compression_jobs(1)[0])
        assert res['status'] == 'FAILED'
        assert central.status(hid) == 'FAILED'
        assert 'ORA-27486' in central.rows[hid]['error_message']

    def test_unreachable_target_requeues(self, dbs):
        central, target = dbs
        target.plsql_error = oracledb.OperationalError('DPY-6005: cannot connect to database')
        hid = central.add()
        res = TargetQueries.submit_queued_job(TargetQueries.get_queued_compression_jobs(1)[0])
        assert res['status'] == 'RETRY'
        assert central.status(hid) == 'QUEUED'
        assert central.rows[hid]['compression_clause'] is None

    def test_existing_job_with_the_rows_name_is_tracked(self, dbs):
        central, target = dbs
        target.plsql_error = oracledb.DatabaseError('ORA-27477: "APP"."HCC_ORDERS_101" already exists')
        hid = central.add()
        res = TargetQueries.submit_queued_job(TargetQueries.get_queued_compression_jobs(1)[0])
        assert res['status'] == 'SUBMITTED' and central.status(hid) == 'IN_PROGRESS'

    def test_invalid_queued_item_fails_instead_of_disappearing(self, dbs):
        central, target = dbs
        hid = central.add(object_name='BAD NAME')
        res = TargetQueries.submit_queued_job(TargetQueries.get_queued_compression_jobs(1)[0])
        assert res['status'] == 'FAILED'
        assert central.status(hid) == 'FAILED'
        assert 'Not submitted' in central.rows[hid]['error_message']
        assert target.plsql == []


def _record_order(fn, order, label):
    def wrapper(*args, **kwargs):
        sql = args[1] if len(args) > 1 else ''
        if label == 'create_job' or 'dba_segments' in _norm(sql):
            order.append(label)
        return fn(*args, **kwargs)
    return wrapper


@pytest.mark.unit
class TestDrain:

    def test_fifo_within_dop_budget_rest_stays_queued(self, dbs):
        central, target = dbs
        ids = [central.add(partition_name=f'P{i}', parallel_degree=2) for i in range(1, 4)]

        stats = TargetQueries.drain_compression_queue(1)             # CPU 8 -> budget 4

        assert stats['submitted'] == 2 and stats['waiting'] == 1
        assert [central.status(h) for h in ids] == ['IN_PROGRESS', 'IN_PROGRESS', 'QUEUED']

    def test_failed_item_is_marked_not_dropped_and_others_continue(self, dbs):
        central, target = dbs
        bad = central.add(object_name='BAD NAME', parallel_degree=1)
        good = central.add(partition_name='P1', parallel_degree=1)
        stats = TargetQueries.drain_compression_queue(1)
        assert stats['failed'] == 1 and stats['submitted'] == 1
        assert central.status(bad) == 'FAILED' and central.status(good) == 'IN_PROGRESS'
        assert len(stats['errors']) == 1

    def test_blocked_item_stays_queued_and_later_items_still_run(self, dbs):
        central, _ = dbs
        central.add(partition_name='P1', operation_status='IN_PROGRESS',
                    compression_clause='HCC_ORDERS_1', parallel_degree=1)
        blocked = central.add(partition_name='P1', parallel_degree=1)
        other = central.add(partition_name='P2', parallel_degree=1)
        stats = TargetQueries.drain_compression_queue(1)
        assert stats['blocked'] == 1 and stats['submitted'] == 1
        assert central.status(blocked) == 'QUEUED' and central.status(other) == 'IN_PROGRESS'

    def test_unreachable_target_leaves_the_rest_of_its_queue(self, dbs):
        central, target = dbs
        target.plsql_error = oracledb.OperationalError('DPY-6005: cannot connect')
        ids = [central.add(partition_name=f'P{i}', parallel_degree=1) for i in range(3)]
        stats = TargetQueries.drain_compression_queue(1)
        assert stats['waiting'] == 3 and stats['skipped_databases'] == [1]
        assert len(target.plsql) == 1                                 # stopped after the first
        assert all(central.status(h) == 'QUEUED' for h in ids)

    def test_queue_read_failure_is_reported(self, dbs):
        central, _ = dbs
        central.fail_on["WHERE operation_status = 'QUEUED'"] = oracledb.DatabaseError('ORA-00942')
        stats = TargetQueries.drain_compression_queue(None)
        assert stats['submitted'] == 0 and 'ORA-00942' in stats['errors'][0]


@pytest.mark.unit
class TestDirectSubmit:

    def test_submits_through_its_own_claimed_queue_row(self, dbs):
        central, target = dbs
        res = TargetQueries.submit_compression_job(1, 'APP', 'ORDERS', 'QUERY HIGH',
                                                   partition_name='P1', parallel_degree=2)
        assert res['success'] is True
        (hid, row), = central.rows.items()
        assert res == {'success': True, 'job_name': f'HCC_ORDERS_{hid}', 'history_id': hid}
        assert row['operation_status'] == 'IN_PROGRESS' and row['executed_by'] == 'alice'
        assert len(target.plsql) == 1

    def test_second_partition_of_running_table_is_accepted(self, dbs):
        central, _ = dbs
        central.add(partition_name='P1', operation_status='IN_PROGRESS',
                    compression_clause='HCC_ORDERS_1')
        res = TargetQueries.submit_compression_job(1, 'APP', 'ORDERS', 'QUERY HIGH',
                                                   partition_name='P2')
        assert res['success'] is True

    def test_same_segment_already_running_is_a_duplicate(self, dbs):
        central, target = dbs
        central.add(partition_name='P1', operation_status='IN_PROGRESS',
                    compression_clause='HCC_ORDERS_1')
        res = TargetQueries.submit_compression_job(1, 'APP', 'ORDERS', 'QUERY HIGH',
                                                   partition_name='P1')
        assert res['success'] is False and res['duplicate'] is True
        assert len(central.rows) == 1 and target.plsql == []

    def test_overlapping_running_job_leaves_it_queued(self, dbs):
        central, _ = dbs
        central.add(partition_name='P1', operation_status='IN_PROGRESS',
                    compression_clause='HCC_ORDERS_1')
        res = TargetQueries.submit_compression_job(1, 'APP', 'ORDERS', 'QUERY HIGH')
        assert res['success'] is False and res['queued'] is True
        assert central.status(res['history_id']) == 'QUEUED'

    def test_invalid_name_returns_an_error_instead_of_raising(self, dbs):
        central, target = dbs
        res = TargetQueries.submit_compression_job(1, 'APP', 'BAD NAME', 'QUERY HIGH')
        assert res['success'] is False and 'Invalid Oracle table name' in res['error']
        assert central.rows == {} and target.plsql == []


# ============================================================================
# One open row per segment (UNQ_HISTORY_OPEN_SEGMENT)
# ============================================================================

_REPO_ROOT = Path(__file__).resolve().parents[3]
_OPEN_INDEX_PATCH = _REPO_ROOT / 'sql' / 'patches' / '20260924-history-unique-open-segment'
_CENTRAL_SCHEMA = _REPO_ROOT / 'sql' / 'central' / '01_central_schema.sql'
_OPEN_ONLY = "CASE WHEN OPERATION_STATUS IN ('QUEUED', 'IN_PROGRESS') THEN"


def _open_index_keys(statement):
    """Normalized key list of the CREATE UNIQUE INDEX UNQ_HISTORY_OPEN_SEGMENT in `statement`."""
    m = re.search(r"CREATE UNIQUE INDEX UNQ_HISTORY_OPEN_SEGMENT ON T_COMPRESSION_HISTORY\s*\((.*)\)",
                  statement, re.S)
    assert m, statement
    return _norm(m.group(1))


def _patch_block():
    (kind, block), = parse_sql_text((_OPEN_INDEX_PATCH / 'patch.sql').read_text())
    assert kind == 'PLSQL'
    return block


@pytest.mark.unit
class TestOpenSegmentIndexSql:

    def test_check_sql_reports_the_index(self):
        (kind, sql), = parse_sql_text((_OPEN_INDEX_PATCH / 'check.sql').read_text())
        assert kind == 'SELECT' and re.search(r'\bas result\b', sql, re.I)
        assert "FROM user_indexes WHERE index_name = 'UNQ_HISTORY_OPEN_SEGMENT'" in sql

    def test_patch_is_one_idempotent_block_that_never_deletes_history(self):
        block = _patch_block()
        assert block.startswith('DECLARE') and block.endswith('END;')
        # Nothing to do once the index exists (re-run safe).
        assert "index_name = 'UNQ_HISTORY_OPEN_SEGMENT'" in block and 'RETURN;' in block
        # Duplicate IN_PROGRESS rows: fail with the list, before any change.
        assert block.index('RAISE_APPLICATION_ERROR') < block.index('UPDATE t_compression_history')
        # Extra QUEUED copies: closed as FAILED with the reason (the UPDATE's
        # SET clause stays on the UPDATE line, as the patch is written).
        assert ("UPDATE t_compression_history SET operation_status = 'FAILED', "
                "end_time = SYSTIMESTAMP,") in block
        assert "AND operation_status = 'QUEUED'" in block
        assert 'Duplicate open row closed by patch 20260924-history-unique-open-segment' in block
        assert 'DELETE' not in block.upper() and 'TRUNCATE' not in block.upper()

    def test_schema_creates_the_same_index_as_the_patch(self):
        stmts = [(k, s) for k, s in parse_sql_file(_CENTRAL_SCHEMA) if 'UNQ_HISTORY_OPEN_SEGMENT' in s]
        (kind, ddl), = stmts
        assert kind == 'DDL' and ddl.startswith('CREATE UNIQUE INDEX UNQ_HISTORY_OPEN_SEGMENT')
        keys = _open_index_keys(ddl)
        assert keys == _open_index_keys(_patch_block())
        # Five keys, each NULL unless the row is open: closed rows are not indexed.
        assert keys.count(_OPEN_ONLY) == 5 and 'ELSE' not in keys
        for column in ('DATABASE_ID END', 'OWNER END', 'OBJECT_NAME END',
                       "NVL(PARTITION_NAME, '~') END", "NVL(SUBPARTITION_NAME, '~') END"):
            assert f"{_OPEN_ONLY} {column}" in keys

    def test_readme_recommends_the_patch(self):
        assert 'recommended' in (_OPEN_INDEX_PATCH / 'readme.md').read_text().lower()

    def test_only_this_index_means_already_queued_or_running(self):
        from oracledb.errors import _Error        # what cursor.getbatcherrors() returns
        dup = 'ORA-00001: unique constraint (HCC.UNQ_HISTORY_OPEN_SEGMENT) violated'
        assert tq._is_open_segment_conflict(oracledb.IntegrityError(dup))
        assert tq._is_open_segment_conflict(_Error(dup, code=1, offset=3))
        assert not tq._is_open_segment_conflict(oracledb.IntegrityError(
            'ORA-00001: unique constraint (HCC.UNQ_HISTORY_EXECUTION) violated'))
        assert not tq._is_open_segment_conflict(oracledb.DatabaseError(
            'ORA-02290: check constraint (HCC.UNQ_HISTORY_OPEN_SEGMENT_X) violated'))


def _other_session_adds(central, after_query, **row):
    """Right after the first central query starting with `after_query`, another
    session commits an open row for a segment: it passed its own "already
    queued?" check at the same instant. Returns [its history_id]."""
    added = []

    def hook(sql, binds):
        if not added and sql.startswith(after_query):
            added.append(central.add(**row))
    central.after_query = hook
    return added


_ENQUEUE_CHECK = 'SELECT owner, object_name, partition_name'
_SEGMENT_CHECK = 'SELECT history_id, operation_status'


@pytest.mark.unit
class TestOneOpenRowPerSegment:

    def test_racing_enqueue_is_a_duplicate_not_an_error(self, dbs):
        central, _ = dbs
        central.unique_open = True
        other = _other_session_adds(central, _ENQUEUE_CHECK, partition_name='P1', executed_by='bob')

        out = TargetQueries.enqueue_compression_jobs([_item(partition_name='P1'),
                                                      _item(partition_name='P2')])

        assert out == {'added': 1, 'duplicates': 1, 'rejected': 0, 'errors': []}
        p1 = [h for h, r in central.rows.items() if r['partition_name'] == 'P1']
        assert p1 == other                                        # the other user's row only
        assert [r['operation_status'] for r in central.rows.values()
                if r['partition_name'] == 'P2'] == ['QUEUED']      # the rest of the call is kept

    def test_without_the_patch_the_race_is_not_caught(self, dbs):
        """Why the patch is recommended: the query check alone lets both in."""
        central, _ = dbs
        _other_session_adds(central, _ENQUEUE_CHECK, partition_name='P1')
        out = TargetQueries.enqueue_compression_jobs([_item(partition_name='P1')])
        assert out['added'] == 1
        assert len([r for r in central.rows.values() if r['partition_name'] == 'P1']) == 2

    def test_any_other_row_error_still_rejects_the_whole_call(self, dbs):
        central, _ = dbs
        central.unique_open = True
        other = _other_session_adds(central, _ENQUEUE_CHECK, partition_name='P1')
        central.insert_errors[('ORDERS', 'P2')] = 'ORA-12899: value too large for column'

        out = TargetQueries.enqueue_compression_jobs([
            _item(partition_name='P1'), _item(partition_name='P2'), _item(partition_name='P3')])

        assert out['added'] == 0 and out['duplicates'] == 0 and out['rejected'] == 3
        assert 'ORA-12899' in out['errors'][0]
        assert list(central.rows) == other                        # P3 was rolled back

    def test_racing_direct_submit_is_a_duplicate_and_creates_no_job(self, dbs):
        central, target = dbs
        central.unique_open = True
        other = _other_session_adds(central, _SEGMENT_CHECK, partition_name='P1',
                                    operation_status='IN_PROGRESS', compression_clause='HCC_ORDERS_1')

        res = TargetQueries.submit_compression_job(1, 'APP', 'ORDERS', 'QUERY HIGH',
                                                   partition_name='P1')

        assert res['success'] is False and res['duplicate'] is True
        assert f"history_id {other[0]}, IN_PROGRESS" in res['error']
        assert list(central.rows) == other and target.plsql == []

    def _execute(self, partition_name='P1'):
        return TargetQueries.execute_compression(1, 'APP', 'ORDERS', 'QUERY HIGH',
                                                 partition_name=partition_name, dry_run=False)

    def test_direct_run_of_a_queued_segment_is_refused_without_the_patch(self, dbs):
        central, target = dbs                                     # unique_open off
        hid = central.add(partition_name='P1')                    # QUEUED

        res = self._execute()

        assert res['success'] is False and res['duplicate'] is True
        assert (f"APP.ORDERS partition P1 is already queued or running (history_id {hid}, QUEUED)"
                in res['error'])
        assert central.dml_statements('SEQ_EXECUTION_ID') == []   # no IN_PROGRESS insert
        assert target.plsql == []                                 # no MOVE
        assert list(central.rows) == [hid]

    def test_direct_run_rejected_by_the_index_runs_no_move(self, dbs):
        central, target = dbs
        central.unique_open = True
        other = _other_session_adds(central, _SEGMENT_CHECK, partition_name='P1', executed_by='bob')

        res = self._execute()

        assert res['success'] is False and res['duplicate'] is True
        assert f"history_id {other[0]}, QUEUED" in res['error']
        assert len(central.dml_statements('SEQ_EXECUTION_ID')) == 1   # the insert was tried,
        assert target.plsql == []                                      # rejected: no MOVE
        assert list(central.rows) == other
        assert central.dml_statements('UPDATE t_compression_history') == []

    def test_direct_run_is_not_run_untracked_when_the_insert_fails(self, dbs):
        central, target = dbs
        central.fail_on['SEQ_EXECUTION_ID'] = oracledb.DatabaseError(
            'ORA-01653: unable to extend table HCC.T_COMPRESSION_HISTORY')

        res = self._execute()

        assert res['success'] is False and 'duplicate' not in res
        assert ('Could not record APP.ORDERS partition P1 in the compression history'
                in res['error'])
        assert target.plsql == [] and central.rows == {}

    def test_direct_run_is_not_run_when_the_history_cannot_be_checked(self, dbs):
        central, target = dbs
        central.fail_on[_SEGMENT_CHECK] = oracledb.DatabaseError('ORA-03113: end-of-file')

        res = self._execute()

        assert res['success'] is False and 'ORA-03113' in res['error']
        assert central.dml_statements('SEQ_EXECUTION_ID') == []
        assert target.plsql == [] and central.rows == {}

    def test_direct_run_closes_its_row_which_frees_the_segment(self, dbs):
        central, target = dbs
        central.unique_open = True
        target.sizes = {'P1': [1000, 400]}

        res = self._execute()

        assert res['success'] is True
        (hid, row), = central.rows.items()
        assert row['operation_status'] == 'SUCCESS' and row['compressed_size_bytes'] == 400
        assert len(target.plsql) == 1 and 'MOVE PARTITION P1' in target.plsql[0]
        assert TargetQueries.enqueue_compression_jobs([_item(partition_name='P1')])['added'] == 1

    def test_claims_and_requeues_keep_the_key_and_closing_frees_it(self, dbs):
        """Claim (QUEUED -> IN_PROGRESS) and requeue update the row's status
        in place, so they never hit the index; SUCCESS takes the row out."""
        central, target = dbs
        central.unique_open = True
        table_job = central.add(operation_status='IN_PROGRESS', compression_clause='HCC_ORDERS_1',
                                parallel_degree=1, age_minutes=120.0)
        assert TargetQueries.enqueue_compression_jobs([_item(partition_name='P1')])['added'] == 1
        # Blocked by the running table-level job: claimed, then put back.
        stats = TargetQueries.drain_compression_queue(1)
        assert stats['blocked'] == 1 and stats['errors'] == []
        # The same segment is still queued exactly once.
        assert TargetQueries.enqueue_compression_jobs([_item(partition_name='P1')])['duplicates'] == 1

        target.runs = {'HCC_ORDERS_1': [{'status': 'SUCCEEDED', 'seconds': 60}]}
        TargetQueries.reconcile_operations(1)
        assert central.status(table_job) == 'SUCCESS'
        assert TargetQueries.drain_compression_queue(1)['submitted'] == 1        # P1 claimed
        # SUCCESS freed the table-level key; P1 is still open (IN_PROGRESS).
        out = TargetQueries.enqueue_compression_jobs([_item(), _item(partition_name='P1')])
        assert (out['added'], out['duplicates'], out['errors']) == (1, 1, [])


# ============================================================================
# Reconcile
# ============================================================================

@pytest.mark.unit
class TestReconcileScheduler:

    def _open(self, central, name, **kw):
        kw.setdefault('operation_status', 'IN_PROGRESS')
        kw.setdefault('age_minutes', 120.0)
        return central.add(compression_clause=name, **kw)

    def test_outcome_mapping(self, dbs):
        central, target = dbs
        target.sizes = {'P2': 250}
        running = self._open(central, 'HCC_ORDERS_1', partition_name='P1')
        ok = self._open(central, 'HCC_ORDERS_2', partition_name='P2', original_size_bytes=1000)
        failed = self._open(central, 'HCC_ORDERS_3', partition_name='P3')
        stopped = self._open(central, 'HCC_ORDERS_4', partition_name='P4')
        missing = self._open(central, 'HCC_ORDERS_5', partition_name='P5')
        young = self._open(central, 'HCC_ORDERS_6', partition_name='P6', age_minutes=2.0)
        scheduled = self._open(central, 'HCC_ORDERS_7', partition_name='P7')
        target.running = {'HCC_ORDERS_1'}
        target.jobs = {'HCC_ORDERS_1': 'RUNNING', 'HCC_ORDERS_7': 'SCHEDULED'}
        target.runs = {
            'HCC_ORDERS_2': [{'status': 'FAILED', 'info': 'earlier try'},
                             {'status': 'SUCCEEDED', 'seconds': 42.0}],
            'HCC_ORDERS_3': [{'status': 'FAILED', 'error': 14257, 'info': 'ORA-14257: cannot move'}],
            'HCC_ORDERS_4': [{'status': 'STOPPED', 'info': 'REASON="Stop job called by user"'}],
        }

        res = TargetQueries.reconcile_operations(1)

        assert res['errors'] == []
        assert central.status(running) == 'IN_PROGRESS'
        assert central.status(young) == 'IN_PROGRESS'
        assert central.status(scheduled) == 'IN_PROGRESS'
        assert (res['running'], res['pending']) == (1, 2)

        row = central.rows[ok]
        assert row['operation_status'] == 'SUCCESS'
        assert row['compressed_size_bytes'] == 250 and row['compression_ratio_achieved'] == 4.0
        assert row['duration_seconds'] == 42.0
        assert central.analysis_updates[0]['p'] == 'P2' and central.analysis_updates[0]['cs'] == 250

        assert central.status(failed) == 'FAILED'
        assert 'ORA-14257' in central.rows[failed]['error_message']
        assert central.rows[failed]['error_code'] == 14257
        assert central.status(stopped) == 'FAILED'
        assert 'STOPPED' in central.rows[stopped]['error_message']
        assert central.status(missing) == 'FAILED'
        assert 'not found' in central.rows[missing]['error_message']

        assert {(u['history_id'], u['status']) for u in res['updated']} == {
            (ok, 'SUCCESS'), (failed, 'FAILED'), (stopped, 'FAILED'), (missing, 'FAILED')}

    def test_no_time_window_on_run_details(self, dbs):
        central, target = dbs
        self._open(central, 'HCC_ORDERS_9', age_minutes=60 * 24 * 10.0)
        target.runs = {'HCC_ORDERS_9': [{'status': 'SUCCEEDED'}]}
        TargetQueries.reconcile_operations(1)
        run_sql = [s for s, _ in target.queries if 'dba_scheduler_job_run_details' in s][0]
        assert 'SYSDATE' not in run_sql and 'actual_start_date >' not in run_sql

    def test_updates_by_history_id_and_database_only(self, dbs):
        central, target = dbs
        hid = self._open(central, 'HCC_ORDERS_2', partition_name='P2')
        central.add(database_id=2, compression_clause='HCC_ORDERS_2',
                    operation_status='IN_PROGRESS', partition_name='P2')    # same job name, other db
        target.runs = {'HCC_ORDERS_2': [{'status': 'SUCCEEDED'}]}

        TargetQueries.reconcile_operations(1)

        (sql, binds), = central.dml_statements("SET operation_status = 'SUCCESS'")
        assert 'WHERE history_id = :hid AND database_id = :db' in sql
        assert 'compression_clause' not in sql.split('WHERE')[1]
        assert (binds['hid'], binds['db']) == (hid, 1)
        assert [r['operation_status'] for r in central.rows.values() if r['database_id'] == 2] \
            == ['IN_PROGRESS']

    def test_only_rows_actually_updated_are_counted(self, dbs):
        central, target = dbs
        a = self._open(central, 'HCC_ORDERS_1')
        b = self._open(central, 'HCC_ORDERS_2')
        target.runs = {'HCC_ORDERS_1': [{'status': 'FAILED'}], 'HCC_ORDERS_2': [{'status': 'FAILED'}]}
        central.lost_updates = {b}          # closed concurrently by someone else
        assert [u['history_id'] for u in TargetQueries.check_completed_jobs(1)] == [a]

    def test_target_lookup_failure_changes_nothing(self, dbs):
        central, target = dbs
        hid = self._open(central, 'HCC_ORDERS_5')
        target.fail_on['dba_scheduler_jobs'] = oracledb.OperationalError('DPY-6005')
        res = TargetQueries.reconcile_operations(1)
        assert central.status(hid) == 'IN_PROGRESS'
        assert res['updated'] == [] and 'DPY-6005' in res['errors'][0]

    def test_subpartition_success_measures_the_subpartition(self, dbs):
        central, target = dbs
        target.sizes = {None: 99_999, 'SP1': 10}
        self._open(central, 'HCC_ORDERS_1', partition_name='P1', subpartition_name='SP1')
        target.runs = {'HCC_ORDERS_1': [{'status': 'SUCCEEDED'}]}
        TargetQueries.reconcile_operations(1)
        assert target.size_queries() == [{'owner': 'APP', 'table_name': 'ORDERS',
                                          'partition_name': 'SP1'}]
        assert central.analysis_updates[0]['sp'] == 'SP1'


@pytest.mark.unit
class TestReconcileSynchronousRows:

    def _sync(self, central, **kw):
        kw.setdefault('operation_status', 'IN_PROGRESS')
        kw.setdefault('compression_clause', 'ALTER TABLE APP.ORDERS MOVE COMPRESS FOR QUERY HIGH')
        return central.add(**kw)

    def test_stale_row_without_session_is_failed_young_row_kept(self, dbs):
        central, target = dbs
        stale = self._sync(central, age_minutes=60 * 30.0)
        young = self._sync(central, age_minutes=60 * 2.0, object_name='LINES')
        res = TargetQueries.reconcile_operations(1)
        assert central.status(stale) == 'FAILED'
        assert 'Outcome unknown' in central.rows[stale]['error_message']
        assert central.status(young) == 'IN_PROGRESS'
        assert [u['history_id'] for u in res['updated']] == [stale]
        (sql, binds), = [(s, p) for s, p in target.queries if 'v$session' in s]
        assert binds['pat'] == r'%ALTER TABLE APP.ORDERS%MOVE%'

    def test_row_with_active_move_session_is_kept(self, dbs):
        central, target = dbs
        target.sessions = 1
        hid = self._sync(central, age_minutes=60 * 30.0)
        TargetQueries.reconcile_operations(1)
        assert central.status(hid) == 'IN_PROGRESS'

    def test_row_owned_by_a_live_thread_of_this_app_is_kept(self, dbs):
        central, target = dbs
        hid = self._sync(central, age_minutes=60 * 48.0)
        tq._set_active(tq._ACTIVE_HISTORY_IDS, hid, True)
        try:
            TargetQueries.reconcile_operations(1)
        finally:
            tq._set_active(tq._ACTIVE_HISTORY_IDS, hid, False)
        assert central.status(hid) == 'IN_PROGRESS'
        assert not [q for q in target.queries if 'v$session' in q[0]]

    def test_session_check_failure_still_closes_with_a_note(self, dbs):
        central, target = dbs
        target.fail_on['v$session'] = oracledb.DatabaseError('ORA-00942: table or view does not exist')
        hid = self._sync(central, age_minutes=60 * 30.0)
        TargetQueries.reconcile_operations(1)
        assert central.status(hid) == 'FAILED'
        assert 'could not be checked' in central.rows[hid]['error_message']


@pytest.mark.unit
class TestReconcileAdvisorRuns:

    def test_stuck_runs_are_failed_except_live_ones(self, dbs):
        central, _ = dbs
        central.advisor_runs = {
            1: {'database_id': 1, 'status': 'RUNNING', 'age_hours': 30},   # stuck
            2: {'database_id': 1, 'status': 'RUNNING', 'age_hours': 2},    # recent
            3: {'database_id': 1, 'status': 'RUNNING', 'age_hours': 50},   # live thread
            4: {'database_id': 2, 'status': 'RUNNING', 'age_hours': 50},   # other database
            5: {'database_id': 1, 'status': 'COMPLETED', 'age_hours': 50},
        }
        tq._set_active(tq._ACTIVE_ADVISOR_RUNS, 3, True)
        try:
            res = TargetQueries.reconcile_operations(1)
        finally:
            tq._set_active(tq._ACTIVE_ADVISOR_RUNS, 3, False)

        assert res['advisor_runs_failed'] == 1
        assert [rid for rid, r in central.advisor_runs.items() if r['status'] == 'FAILED'] == [1]
        assert 'RUNNING' in central.advisor_runs[1]['error']
        (sql, binds), = central.dml_statements('UPDATE t_advisor_run')
        assert "run_status = 'RUNNING'" in sql and 'database_id = :db' in sql
        assert binds['hrs'] == TargetQueries.ADVISOR_RUN_STALE_HOURS

    def test_start_analysis_registers_its_run_while_alive(self, dbs, monkeypatch):
        seen = {}
        monkeypatch.setattr(CentralQueries, 'get_target_database', lambda db: {})
        monkeypatch.setattr(CentralQueries, 'store_advisor_run', lambda db, data: (True, 77))
        monkeypatch.setattr(CentralConnector, 'execute_query', lambda *a, **k: pd.DataFrame())
        monkeypatch.setattr(TargetQueries, '_safe_flush_monitoring_info',
                            lambda db: seen.setdefault('active', tq._active_snapshot(tq._ACTIVE_ADVISOR_RUNS)))
        monkeypatch.setattr(TargetQueries, '_discover_analysis_tables', lambda db, owner: [])
        monkeypatch.setattr(TargetQueries, '_complete_advisor_run', lambda *a: None)

        TargetQueries.start_analysis(1)

        assert 77 in seen['active']
        assert 77 not in tq._active_snapshot(tq._ACTIVE_ADVISOR_RUNS)


# ============================================================================
# Sizes, long DDL, batch execution, index rebuild counting
# ============================================================================

@pytest.mark.unit
class TestSegmentSizeQuery:

    def test_levels(self):
        sql, binds = tq._segment_size_query('APP', 'ORDERS')
        assert 'partition_name' not in sql and binds == {'owner': 'APP', 'table_name': 'ORDERS'}
        sql, binds = tq._segment_size_query('APP', 'ORDERS', 'P1')
        assert 'AND partition_name = :partition_name' in sql and binds['partition_name'] == 'P1'
        sql, binds = tq._segment_size_query('APP', 'ORDERS', 'P1', 'SP1')
        assert binds['partition_name'] == 'SP1'   # a subpartition segment's own name


LONG = 'X' * 120


@pytest.mark.unit
class TestLongDdl:

    def test_history_clause_fits_200_bytes(self):
        assert history_clause('short') == 'short'
        assert history_clause(None) is None
        long = 'ALTER TABLE ' + LONG + '.' + LONG
        fitted = history_clause(long)
        assert len(fitted.encode()) <= 200 and fitted.endswith('...')
        assert len(history_clause('é' * 150).encode()) <= 200

    def test_store_keeps_full_ddl_in_original_ddl(self):
        captured = {}

        def returning(sql, params, out_bind='new_id', commit=True):
            _check_binds(_norm(sql), params, extra=(out_bind,))
            captured.update(params)
            return 9
        long = 'ALTER TABLE ' + LONG + '.' + LONG + '\nMOVE PARTITION ' + LONG
        with patch.object(CentralConnector, 'execute_dml_returning', side_effect=returning):
            assert CentralQueries.store_compression_history(1, {
                'owner': LONG, 'object_name': LONG, 'object_type': 'PARTITION',
                'compression_type_applied': 'QUERY HIGH', 'compression_clause': long}) == 9
        assert len(captured['compression_clause'].encode()) <= 200
        assert captured['original_ddl'] == long

    def test_execute_compression_with_long_names_is_tracked(self):
        store = MagicMock(return_value=9)
        dml = MagicMock(return_value=1)
        with patch.object(CentralQueries, 'store_compression_history', store), \
                patch.object(CentralConnector, 'execute_query', return_value=pd.DataFrame()), \
                patch.object(CentralConnector, 'execute_dml', dml), \
                patch.object(TargetConnector, 'execute_query', return_value=pd.DataFrame()), \
                patch.object(TargetConnector, 'execute_plsql', return_value=True):
            res = TargetQueries.execute_compression(1, 'APP' + 'A' * 100, 'T' * 128, 'QUERY HIGH',
                                                    partition_name='P' * 128, dry_run=False)
        assert res['success'] is True
        record = store.call_args.args[1]
        assert len(record['compression_clause'].encode()) <= 200
        assert record['original_ddl'].startswith('ALTER TABLE') and len(record['original_ddl']) > 300
        binds = dml.call_args_list[0].args[1]
        assert binds['hist_id'] == 9


@pytest.mark.unit
class TestBatchExecute:

    def test_bad_item_is_that_items_failure(self, dbs):
        items = [{'owner': 'APP', 'table_name': 'BAD NAME', 'compression_type': 'QUERY HIGH'},
                 {'owner': 'APP', 'table_name': 'ORDERS', 'compression_type': 'QUERY HIGH'}]
        out = TargetQueries.batch_execute(1, items, dry_run=True, concurrency=2)
        assert (out['success'], out['errors']) == (1, 1)
        bad = next(r for r in out['results'] if r['table_name'] == 'BAD NAME')
        assert 'Invalid Oracle table name' in bad['result']['error']

    def test_worker_exception_does_not_fail_the_batch(self):
        def fake(**kw):
            if kw['table_name'] == 'BOOM':
                raise ValueError('boom')
            return {'success': True}
        items = [{'owner': 'APP', 'table_name': t, 'compression_type': 'OLTP'}
                 for t in ('BOOM', 'OK1', 'OK2')]
        with patch.object(TargetQueries, 'execute_compression', side_effect=fake):
            out = TargetQueries.batch_execute(1, items, dry_run=False, concurrency=3)
        assert (out['total'], out['success'], out['errors']) == (3, 2, 1)
        assert next(r for r in out['results'] if r['table_name'] == 'BOOM')['result'] == \
            {'success': False, 'error': 'boom'}

    def test_acting_user_is_passed_to_worker_threads(self, monkeypatch):
        monkeypatch.setattr(tq, '_acting_user', lambda: 'alice')
        with patch.object(TargetQueries, 'execute_compression', return_value={'success': True}) as ex:
            TargetQueries.batch_execute(1, [{'owner': 'APP', 'table_name': 'T',
                                             'compression_type': 'OLTP'}], dry_run=False)
        assert ex.call_args.kwargs['executed_by'] == 'alice'


@pytest.mark.unit
class TestIndexRebuildCount:

    def test_only_successful_rebuilds_are_counted(self):
        def query(database_id, sql, params=None):
            if 'all_indexes' in sql:
                return pd.DataFrame([{'OWNER': 'APP', 'INDEX_NAME': 'IX1'},
                                     {'OWNER': 'APP', 'INDEX_NAME': 'IX2'}])
            if 'dba_segments' in sql:
                return pd.DataFrame([{'SIZE_BYTES': 100}])
            return pd.DataFrame()

        def plsql(database_id, block):
            return 'IX2' not in block          # the MOVE and IX1 succeed, IX2 fails
        dml = MagicMock(return_value=1)
        with patch.object(CentralQueries, 'store_compression_history', return_value=5), \
                patch.object(CentralConnector, 'execute_query', return_value=pd.DataFrame()), \
                patch.object(CentralConnector, 'execute_dml', dml), \
                patch.object(TargetConnector, 'execute_query', side_effect=query), \
                patch.object(TargetConnector, 'execute_plsql', side_effect=plsql):
            res = TargetQueries.execute_compression(1, 'APP', 'ORDERS', 'OLTP', dry_run=False)

        binds = dml.call_args_list[0].args[1]
        assert binds['idx_cnt'] == 1 and binds['idx_status'] == 'PARTIAL'
        assert '1 index rebuild(s) FAILED' in res['message']


# ============================================================================
# Views: leaf-segment candidates, role-gated drain
# ============================================================================

def _recs(rows):
    cols = ['database_id', 'table_owner', 'table_name', 'object_type', 'partition_name',
            'subpartition_name', 'recommended_strategy', 'execution_status', 'analysis_timestamp']
    return pd.DataFrame([dict(zip(cols, r)) for r in rows], columns=cols).rename(columns=str.upper)


@pytest.mark.unit
class TestLeafCandidates:

    def test_only_leaf_segments_that_are_pending(self):
        from hcc_advisor.views import page_08_quick_scan as p08
        late, early = datetime(2026, 9, 2), datetime(2026, 9, 1)
        recs = _recs([
            (1, 'APP', 'PLAIN', 'TABLE', None, None, 'OLTP', 'Pending', early),
            # partitioned: TABLE row newer than its partitions must still not be moved
            (1, 'APP', 'SALES', 'TABLE', None, None, 'QUERY HIGH', 'Pending', late),
            (1, 'APP', 'SALES', 'PARTITION', 'P1', None, 'QUERY HIGH', 'Pending', early),
            (1, 'APP', 'SALES', 'PARTITION', 'P2', None, 'QUERY HIGH', 'Compressed', early),
            (1, 'APP', 'SALES', 'PARTITION', 'P3', None, 'NONE', 'Pending', early),
            # composite: only subpartitions
            (1, 'APP', 'EVENTS', 'TABLE', None, None, 'QUERY HIGH', 'Pending', early),
            (1, 'APP', 'EVENTS', 'PARTITION', 'Q1', None, 'QUERY HIGH', 'Pending', early),
            (1, 'APP', 'EVENTS', 'SUBPARTITION', 'Q1', 'Q1_A', 'QUERY HIGH', 'Pending', early),
            # every partition already compressed: the TABLE row is still not a leaf
            (1, 'APP', 'DONE', 'TABLE', None, None, 'QUERY HIGH', 'Pending', early),
            (1, 'APP', 'DONE', 'PARTITION', 'D1', None, 'QUERY HIGH', 'Compressed', early),
        ])
        with patch.object(CentralQueries, 'get_recommendations', return_value=recs) as rec:
            items = p08.pending_leaf_candidates('APP', 1, 3)

        kwargs = rec.call_args.kwargs
        assert kwargs['show_executed'] is True and kwargs['include_none'] is True
        got = {(i['table_name'], i['partition_name'], i['subpartition_name']) for i in items}
        assert got == {('PLAIN', None, None), ('SALES', 'P1', None), ('EVENTS', 'Q1', 'Q1_A')}
        assert all(i['dop'] == 3 and i['database_id'] == 1 for i in items)

    def test_bulk_submit_enqueues_then_drains(self, dbs):
        from hcc_advisor.views import page_08_quick_scan as p08
        central, _ = dbs
        central.add(partition_name='P1', operation_status='QUEUED', parallel_degree=2)  # already queued
        out = p08._bulk_submit([_item(partition_name='P1', dop=None),
                                _item(partition_name='P2', dop=None)], 1, 4, 2)
        assert out['duplicates'] == 1
        assert out['submitted'] == 2 and out['queued'] == 0 and out['failed'] == 0
        assert all(r['operation_status'] == 'IN_PROGRESS' for r in central.rows.values())


@pytest.mark.unit
class TestSchedulerPageRefresh:

    def test_drain_only_for_operators_reconcile_for_everyone(self, monkeypatch):
        from hcc_advisor.views import page_12_scheduler as p12
        reconcile = MagicMock(return_value={'errors': [], 'updated': []})
        drain = MagicMock()
        monkeypatch.setattr(TargetQueries, 'reconcile_operations', reconcile)
        monkeypatch.setattr(p12, '_drain_pending_queue', drain)

        monkeypatch.setattr(p12.AuthManager, 'has_role', staticmethod(lambda role: False))
        p12._do_refresh(1)
        reconcile.assert_called_once_with(1)
        drain.assert_not_called()

        monkeypatch.setattr(p12.AuthManager, 'has_role', staticmethod(lambda role: True))
        p12._do_refresh(1)
        drain.assert_called_once_with(1)
