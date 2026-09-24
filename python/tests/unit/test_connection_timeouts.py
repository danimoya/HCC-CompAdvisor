"""
Unit tests for connection robustness and long operations in the web thread:

- pool kwargs carry the connect timeout and a bounded acquire wait (TIMEDWAIT);
- concurrent callers share one pool per target (and one central pool), and the
  stale-login rebuild still works under the lock;
- the interactive read helpers set call_timeout and reset it before the
  connection goes back to the pool; DDL / PL/SQL and the analysis /
  compression paths (long_operation) run without one;
- timeout errors are explained in the UI message;
- the synchronous batch concurrency is capped below the target pool size;
- Compress Tables / Recommendations: background (DBMS_SCHEDULER) execution
  uses enqueue + drain, the synchronous path stays available, page_02 passes
  its Parallel value through, and live execution needs confirmation.

No database: pools, connections and cursors are fakes.
"""
import inspect
import threading
import time
from unittest.mock import MagicMock, patch

import oracledb
import pandas as pd
import pytest
from streamlit.testing.v1 import AppTest

from hcc_advisor.config import config
from hcc_advisor.utils import central_connector as cc_module
from hcc_advisor.utils import db_timeouts
from hcc_advisor.utils import target_connector as tc_module
from hcc_advisor.utils.central_connector import CentralConnector
from hcc_advisor.utils.central_queries import CentralQueries
from hcc_advisor.utils.db_timeouts import (
    describe_db_error, long_operation, pool_timeout_kwargs, read_call_timeout_ms,
)
from hcc_advisor.utils.target_connector import TargetConnector, max_batch_concurrency
from hcc_advisor.utils.target_queries import TargetQueries, _is_retryable_error


TARGET = {'username': 'APP_ADV', 'password': 'pw', 'host': 'dbhost', 'port': 1521,
          'service': 'FREEPDB1', 'connection_mode': 'NORMAL'}


# ============================================================================
# Fakes
# ============================================================================

class RecordingCursor:
    """Records (sql, call_timeout of its connection at execute time)."""

    def __init__(self, conn):
        self.conn = conn
        self.description = [('X', None, None, None, None, None, None)]
        self.rowcount = 1

    def execute(self, sql, params=None):
        self.conn.log.append((" ".join(sql.split()), self.conn.call_timeout))
        if self.conn.fail_with is not None:
            raise self.conn.fail_with

    def fetchall(self):
        return []

    def fetchone(self):
        return None

    def var(self, *args, **kwargs):
        return MagicMock()

    def close(self):
        pass


class RecordingConn:
    def __init__(self, log, fail_with=None):
        self.log = log
        self.fail_with = fail_with
        self.call_timeout = 0

    def cursor(self):
        return RecordingCursor(self)

    def commit(self):
        pass


class RecordingPool:
    """acquire() hands out RecordingConns sharing one statement log; release()
    records the call_timeout each connection is returned with."""

    def __init__(self, fail_with=None):
        self.log = []
        self.released_with = []
        self.fail_with = fail_with
        self._lock = threading.Lock()

    def acquire(self):
        return RecordingConn(self.log, self.fail_with)

    def release(self, conn):
        with self._lock:
            self.released_with.append(conn.call_timeout)


@pytest.fixture
def clean_pools():
    TargetConnector._pools.clear()
    TargetConnector._pool_configs.clear()
    yield
    TargetConnector._pools.clear()
    TargetConnector._pool_configs.clear()


@pytest.fixture
def target_pool(monkeypatch):
    """Real TargetConnector helpers on a RecordingPool; st/logging mocked."""
    pool = RecordingPool()
    monkeypatch.setattr(TargetConnector, 'get_pool', lambda database_id, conn_config: pool)
    monkeypatch.setattr(CentralQueries, 'get_target_database', lambda database_id: dict(TARGET))
    pool.st = MagicMock()
    monkeypatch.setattr(tc_module, 'st', pool.st)
    monkeypatch.setattr(tc_module, 'is_debug_enabled', lambda: False)
    monkeypatch.setattr(tc_module, 'log_db_error', MagicMock())
    monkeypatch.setattr(tc_module, 'log_error', MagicMock())
    return pool


@pytest.fixture
def central_pool(monkeypatch):
    pool = RecordingPool()
    monkeypatch.setattr(CentralConnector, '_pool', pool)
    pool.st = MagicMock()
    monkeypatch.setattr(cc_module, 'st', pool.st)
    monkeypatch.setattr(cc_module, 'is_debug_enabled', lambda: False)
    monkeypatch.setattr(cc_module, 'log_db_error', MagicMock())
    monkeypatch.setattr(cc_module, 'log_error', MagicMock())
    return pool


# ============================================================================
# Pool kwargs
# ============================================================================

@pytest.mark.unit
class TestPoolTimeoutKwargs:

    def test_target_pool_gets_timeouts(self, clean_pools, monkeypatch):
        monkeypatch.setattr(config, 'TARGET_CONNECT_TIMEOUT', 7)
        monkeypatch.setattr(config, 'POOL_WAIT_TIMEOUT', 30)
        with patch.object(tc_module.oracledb, 'create_pool') as create_pool:
            TargetConnector.get_pool(7, TARGET)
        kwargs = create_pool.call_args.kwargs
        assert kwargs['tcp_connect_timeout'] == 7
        assert kwargs['getmode'] == oracledb.POOL_GETMODE_TIMEDWAIT
        assert kwargs['wait_timeout'] == 30000           # milliseconds
        assert kwargs['max'] == config.TARGET_POOL_MAX

    def test_central_pool_gets_timeouts(self, monkeypatch):
        monkeypatch.setattr(CentralConnector, '_pool', None)
        monkeypatch.setattr(config, 'CENTRAL_CONNECT_TIMEOUT', 9)
        monkeypatch.setattr(config, 'POOL_WAIT_TIMEOUT', 15)
        with patch.object(cc_module.oracledb, 'create_pool') as create_pool:
            CentralConnector.initialize_pool()
        kwargs = create_pool.call_args.kwargs
        assert kwargs['tcp_connect_timeout'] == 9
        assert kwargs['getmode'] == oracledb.POOL_GETMODE_TIMEDWAIT
        assert kwargs['wait_timeout'] == 15000

    def test_zero_wait_keeps_driver_wait_mode(self, monkeypatch):
        monkeypatch.setattr(config, 'POOL_WAIT_TIMEOUT', 0)
        assert pool_timeout_kwargs(10) == {'tcp_connect_timeout': 10.0}
        assert pool_timeout_kwargs(0) == {}

    def test_kwargs_are_create_pool_parameters(self):
        # Parameter names checked against the installed python-oracledb.
        inspect.signature(oracledb.create_pool).bind(
            user='u', password='p', dsn='h:1521/s', min=1, max=5, increment=1,
            **pool_timeout_kwargs(10))

    def test_direct_connection_test_has_connect_timeout(self, monkeypatch):
        monkeypatch.setattr(config, 'TARGET_CONNECT_TIMEOUT', 4)
        with patch.object(tc_module.oracledb, 'connect') as connect:
            assert TargetConnector.test_connection_direct(TARGET) is True
        assert connect.call_args.kwargs['tcp_connect_timeout'] == 4


# ============================================================================
# One pool per target / one central pool under concurrency
# ============================================================================

def _run_concurrently(fn, n=8):
    barrier = threading.Barrier(n)
    results, errors = [], []

    def worker():
        barrier.wait()
        try:
            results.append(fn())
        except Exception as e:  # pragma: no cover - surfaced by the assert below
            errors.append(e)

    threads = [threading.Thread(target=worker) for _ in range(n)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=10)
    assert not errors
    return results


def _slow_create_pool(created):
    def create_pool(**kwargs):
        time.sleep(0.2)          # widen the race window
        pool = MagicMock(name=f"pool{len(created)}")
        pool.login = kwargs.get('user')
        created.append(pool)
        return pool
    return create_pool


@pytest.mark.unit
class TestPoolCreationLock:

    def test_concurrent_get_pool_creates_one_pool(self, clean_pools):
        created = []
        with patch.object(tc_module.oracledb, 'create_pool', side_effect=_slow_create_pool(created)):
            results = _run_concurrently(lambda: TargetConnector.get_pool(7, TARGET))
        assert len(created) == 1
        assert len(results) == 8 and all(r is created[0] for r in results)

    def test_other_targets_are_not_serialized(self, clean_pools):
        db7_creating, release_db7 = threading.Event(), threading.Event()

        def create_pool(**kwargs):
            if kwargs['dsn'].startswith('slow'):
                db7_creating.set()
                assert release_db7.wait(timeout=5)
            return MagicMock()

        with patch.object(tc_module.oracledb, 'create_pool', side_effect=create_pool):
            slow = threading.Thread(target=TargetConnector.get_pool,
                                    args=(7, {**TARGET, 'host': 'slow'}))
            slow.start()
            assert db7_creating.wait(timeout=5)       # db 7's lock is held now
            t0 = time.perf_counter()
            TargetConnector.get_pool(8, TARGET)       # must not wait for db 7
            elapsed = time.perf_counter() - t0
            release_db7.set()
            slow.join(timeout=5)
        assert elapsed < 1
        assert set(TargetConnector._pools) == {7, 8}

    def test_concurrent_stale_login_rebuilds_once(self, clean_pools):
        created = []
        old_login = {**TARGET, 'username': 'OLD_USER'}
        with patch.object(tc_module.oracledb, 'create_pool', side_effect=_slow_create_pool(created)):
            old_pool = TargetConnector.get_pool(7, old_login)
            results = _run_concurrently(lambda: TargetConnector.get_pool(7, TARGET))
        assert len(created) == 2
        new_pool = created[1]
        assert new_pool.login == 'APP_ADV'
        assert all(r is new_pool for r in results)
        old_pool.close.assert_called_once()

    def test_concurrent_central_initialize_creates_one_pool(self, monkeypatch):
        monkeypatch.setattr(CentralConnector, '_pool', None)
        created = []
        with patch.object(cc_module.oracledb, 'create_pool', side_effect=_slow_create_pool(created)):
            _run_concurrently(CentralConnector.initialize_pool)
        assert len(created) == 1
        assert CentralConnector._pool is created[0]


# ============================================================================
# call_timeout: interactive reads only
# ============================================================================

@pytest.mark.unit
class TestCallTimeout:

    def test_target_read_sets_and_resets_call_timeout(self, target_pool, monkeypatch):
        monkeypatch.setattr(config, 'DB_CALL_TIMEOUT', 45)
        TargetConnector.execute_query(1, "SELECT 1 FROM dual")
        assert target_pool.log == [("SELECT 1 FROM dual", 45000)]
        assert target_pool.released_with == [0]      # back in the pool without it

    def test_central_read_sets_and_resets_call_timeout(self, central_pool, monkeypatch):
        monkeypatch.setattr(config, 'DB_CALL_TIMEOUT', 20)
        CentralConnector.execute_query("SELECT 1 FROM dual")
        assert central_pool.log == [("SELECT 1 FROM dual", 20000)]
        assert central_pool.released_with == [0]

    def test_ddl_and_dml_paths_have_no_call_timeout(self, target_pool, central_pool):
        TargetConnector.execute_plsql(1, "BEGIN EXECUTE IMMEDIATE 'ALTER TABLE APP.T MOVE'; END;")
        TargetConnector.execute_dml(1, "UPDATE t SET x = 1")
        CentralConnector.execute_dml("UPDATE t SET x = 1")
        CentralConnector.execute_plsql("BEGIN NULL; END;")
        assert [t for _, t in target_pool.log + central_pool.log] == [0, 0, 0, 0]

    def test_per_call_override(self, target_pool, monkeypatch):
        monkeypatch.setattr(config, 'DB_CALL_TIMEOUT', 45)
        TargetConnector.execute_query(1, "SELECT 1 FROM dual", call_timeout=5)
        TargetConnector.execute_query(1, "SELECT 2 FROM dual", call_timeout=0)
        assert [t for _, t in target_pool.log] == [5000, 0]

    def test_long_operation_disables_the_read_timeout(self, target_pool, monkeypatch):
        monkeypatch.setattr(config, 'DB_CALL_TIMEOUT', 45)
        with long_operation():
            TargetConnector.execute_query(1, "SELECT 1 FROM dual")
        TargetConnector.execute_query(1, "SELECT 2 FROM dual")
        assert [t for _, t in target_pool.log] == [0, 45000]

    def test_disabled_by_config(self, monkeypatch):
        monkeypatch.setattr(config, 'DB_CALL_TIMEOUT', 0)
        assert read_call_timeout_ms() == 0

    def test_reset_after_failed_read(self, target_pool, monkeypatch):
        monkeypatch.setattr(config, 'DB_CALL_TIMEOUT', 45)
        target_pool.fail_with = oracledb.DatabaseError("DPY-4024: call timeout of 45000 ms exceeded")
        df = TargetConnector.execute_query(1, "SELECT slow FROM big")
        assert df.empty
        assert target_pool.released_with == [0]
        message = target_pool.st.error.call_args.args[0]
        assert 'DPY-4024' in message and 'DB_CALL_TIMEOUT=45s' in message

    def _compression_mocks(self, monkeypatch):
        from hcc_advisor.utils import target_queries as tq
        monkeypatch.setattr(CentralQueries, 'store_compression_history', lambda db, rec: 101)
        monkeypatch.setattr(CentralConnector, 'execute_dml', MagicMock(return_value=1))
        monkeypatch.setattr(tq, '_acting_user', lambda: 'alice')
        # No other open (QUEUED/IN_PROGRESS) row for the segment, so the run
        # is allowed (see TargetQueries._open_segment_row).
        monkeypatch.setattr(TargetQueries, '_open_segment_row',
                            staticmethod(lambda *a, **k: None))

    def test_compression_runs_without_call_timeout(self, target_pool, monkeypatch):
        monkeypatch.setattr(config, 'DB_CALL_TIMEOUT', 45)
        self._compression_mocks(monkeypatch)
        out = TargetQueries.execute_compression(1, 'APP', 'ORDERS', 'QUERY HIGH', dry_run=False)
        assert out.get('success'), out
        sqls = [s for s, _ in target_pool.log]
        assert any(s.startswith('SELECT') for s in sqls)            # its reads ...
        assert any('ALTER TABLE APP.ORDERS' in s for s in sqls)     # ... and the MOVE
        assert all(t == 0 for _, t in target_pool.log)
        # the scope ends with the call: a later UI read is limited again
        TargetConnector.execute_query(1, "SELECT 1 FROM dual")
        assert target_pool.log[-1][1] == 45000

    def test_batch_worker_threads_run_without_call_timeout(self, target_pool, monkeypatch):
        monkeypatch.setattr(config, 'DB_CALL_TIMEOUT', 45)
        self._compression_mocks(monkeypatch)
        items = [{'owner': 'APP', 'table_name': t, 'compression_type': 'OLTP'}
                 for t in ('T1', 'T2', 'T3')]
        out = TargetQueries.batch_execute(1, items, dry_run=False, concurrency=3)
        assert out['success'] == 3
        assert target_pool.log and all(t == 0 for _, t in target_pool.log)

    def test_analysis_scan_and_rollback_run_as_long_operations(self, monkeypatch):
        """Their first database call already sees the long-operation scope."""
        seen = []

        class Stop(Exception):
            pass

        def probe(*args, **kwargs):
            seen.append(db_timeouts.in_long_operation())
            raise Stop()

        monkeypatch.setattr(CentralQueries, 'get_target_database', probe)
        monkeypatch.setattr(CentralConnector, 'execute_query', probe)
        for call in (lambda: TargetQueries.start_analysis(1, owner='APP'),
                     lambda: TargetQueries.quick_scan(1, owner='APP'),
                     lambda: TargetQueries.rollback_compression(1, 'APP', 'ORDERS', history_id=5)):
            try:
                call()
            except Stop:
                pass
        assert seen == [True, True, True]
        assert not db_timeouts.in_long_operation()


# ============================================================================
# Readable timeout errors
# ============================================================================

@pytest.mark.unit
class TestDescribeDbError:

    def test_pool_wait(self, monkeypatch):
        monkeypatch.setattr(config, 'POOL_WAIT_TIMEOUT', 30)
        msg = describe_db_error(oracledb.DatabaseError(
            "DPY-4005: timed out waiting for the connection pool to return a connection"))
        assert msg.startswith("DPY-4005")
        assert 'POOL_WAIT_TIMEOUT=30s' in msg and 'TARGET_POOL_MAX' in msg

    def test_connect_timeout(self):
        msg = describe_db_error(oracledb.OperationalError(
            "DPY-6005: cannot connect to database (CONNECTION_ID=x).\ntimed out"))
        assert 'TARGET_CONNECT_TIMEOUT' in msg

    def test_other_errors_unchanged(self):
        for text in ("ORA-00942: table or view does not exist", "DPY-6005: cannot connect"):
            assert describe_db_error(oracledb.DatabaseError(text)) == text

    def test_busy_target_pool_is_explained_in_the_ui(self, monkeypatch):
        pool = MagicMock()
        pool.acquire.side_effect = oracledb.DatabaseError(
            "DPY-4005: timed out waiting for the connection pool to return a connection")
        monkeypatch.setattr(TargetConnector, 'get_pool', lambda database_id, conn_config: pool)
        st_mock = MagicMock()
        monkeypatch.setattr(tc_module, 'st', st_mock)
        monkeypatch.setattr(tc_module, 'log_db_error', MagicMock())
        monkeypatch.setattr(tc_module, 'log_error', MagicMock())
        assert TargetConnector.execute_query(3, "SELECT 1 FROM dual", conn_config=TARGET).empty
        assert 'POOL_WAIT_TIMEOUT' in st_mock.error.call_args.args[0]

    def test_busy_pool_is_retryable_for_the_scheduler(self):
        assert _is_retryable_error(oracledb.DatabaseError(
            "DPY-4005: timed out waiting for the connection pool to return a connection"))


# ============================================================================
# Synchronous batch concurrency cap
# ============================================================================

@pytest.mark.unit
class TestBatchConcurrencyCap:

    @pytest.mark.parametrize('pool_max, expected', [(5, 3), (10, 8), (3, 1), (2, 1), (1, 1)])
    def test_cap_leaves_headroom(self, monkeypatch, pool_max, expected):
        monkeypatch.setattr(config, 'TARGET_POOL_MAX', pool_max)
        monkeypatch.setattr(config, 'TARGET_POOL_UI_HEADROOM', 2)
        assert max_batch_concurrency() == expected

    def test_batch_execute_never_exceeds_the_cap(self, monkeypatch):
        monkeypatch.setattr(config, 'TARGET_POOL_MAX', 5)
        monkeypatch.setattr(config, 'TARGET_POOL_UI_HEADROOM', 2)
        state = {'active': 0, 'peak': 0}
        lock = threading.Lock()

        def fake(**kw):
            with lock:
                state['active'] += 1
                state['peak'] = max(state['peak'], state['active'])
            time.sleep(0.05)
            with lock:
                state['active'] -= 1
            return {'success': True}

        items = [{'owner': 'APP', 'table_name': f'T{i}', 'compression_type': 'OLTP'}
                 for i in range(8)]
        with patch.object(TargetQueries, 'execute_compression', side_effect=fake):
            out = TargetQueries.batch_execute(1, items, dry_run=False, concurrency=8)
        assert out['success'] == 8
        assert state['peak'] <= 3


# ============================================================================
# Compress Tables (page_03)
# ============================================================================

RECS = pd.DataFrame({
    'recommendation_id': [11, 12],
    'table_owner': ['APP', 'APP'],
    'table_name': ['ORDERS', 'EVENTS'],
    'partition_name': [None, 'P1'],
    'current_size_mb': [100.0, 50.0],
    'estimated_size_mb': [20.0, 10.0],
    'recommended_strategy': ['QUERY HIGH', 'OLTP'],
    'savings_pct': [80.0, 80.0],
})

ENQ_OK = {'added': 2, 'duplicates': 0, 'rejected': 0, 'errors': []}
DRAIN_OK = {'submitted': 1, 'blocked': 0, 'failed': 0, 'not_claimed': 0, 'waiting': 1,
            'skipped_databases': [], 'errors': []}


def _batch_page():
    from hcc_advisor.views.page_03_execution import show_batch_execution
    show_batch_execution()


@pytest.fixture
def page03_mocks():
    with patch.object(CentralQueries, 'get_recommendations', return_value=RECS.copy()), \
            patch.object(TargetQueries, 'get_available_schemas', return_value=[]), \
            patch.object(TargetQueries, 'get_cpu_count', return_value=64), \
            patch.object(TargetQueries, 'enqueue_compression_jobs', return_value=ENQ_OK) as enqueue, \
            patch.object(TargetQueries, 'drain_compression_queue', return_value=DRAIN_OK) as drain, \
            patch.object(TargetQueries, 'batch_execute',
                         return_value={'success': 2, 'errors': 0}) as batch, \
            patch.object(TargetQueries, 'execute_compression') as execute:
        yield {'enqueue': enqueue, 'drain': drain, 'batch': batch, 'execute': execute}


def _batch_app_selected(**state):
    at = AppTest.from_function(_batch_page, default_timeout=10)
    at.session_state['authenticated'] = True
    at.session_state['role'] = 'operator'
    at.session_state['active_database_id'] = 1
    for key, value in state.items():
        at.session_state[key] = value
    at.run()
    return _rerun(at)


def _rerun(at):
    """Run with both tables selected. The multiselect uses a format_func, which
    AppTest (1.31) can only send back by displayed label, so it is re-pinned
    before every run."""
    at.multiselect[0].set_value(['APP.ORDERS', 'APP.EVENTS'])
    return at.run()


def _go_live(at, background=True, confirm=True):
    at.checkbox(key='batch_dry_run').uncheck()
    if not background:
        at.checkbox(key='batch_background').uncheck()
    if confirm:
        at.checkbox(key='batch_confirm').check()
    return _rerun(at)


@pytest.mark.unit
class TestCompressTablesPage:

    def test_concurrency_slider_is_capped_by_the_pool(self, page03_mocks, monkeypatch):
        monkeypatch.setattr(config, 'TARGET_POOL_MAX', 5)
        at = _batch_app_selected()
        slider = at.slider(key='batch_concurrency')
        assert slider.max == 3                      # not CPU_COUNT/2 = 32
        assert slider.disabled                      # background mode: not used

    def test_background_is_the_default_and_queues(self, page03_mocks):
        at = _go_live(_batch_app_selected())
        assert at.checkbox(key='batch_background').value is True
        at.button[0].click()
        _rerun(at)
        page03_mocks['enqueue'].assert_called_once()
        items = page03_mocks['enqueue'].call_args.args[0]
        assert {(i['table_name'], i['partition_name']) for i in items} == \
            {('ORDERS', None), ('EVENTS', 'P1')}
        assert all(i['database_id'] == 1 and i['dop'] == at.slider(key='batch_parallel').value
                   for i in items)
        page03_mocks['drain'].assert_called_once_with(1)
        page03_mocks['batch'].assert_not_called()
        page03_mocks['execute'].assert_not_called()
        text = " ".join(s.value for s in at.success) + " ".join(i.value for i in at.info)
        assert 'Queued: 2' in text and 'Submitted to DBMS_SCHEDULER: 1' in text
        assert 'Scheduler' in text

    def test_synchronous_path_when_unticked(self, page03_mocks):
        at = _go_live(_batch_app_selected(), background=False)
        at.slider(key='batch_concurrency').set_value(3)
        _rerun(at)
        at.button[0].click()
        _rerun(at)
        page03_mocks['batch'].assert_called_once()
        assert page03_mocks['batch'].call_args.kwargs['concurrency'] == 3
        page03_mocks['enqueue'].assert_not_called()

    def test_confirm_required(self, page03_mocks):
        at = _go_live(_batch_app_selected(), confirm=False)
        assert at.button[0].disabled
        at.button[0].click()                        # forced click on the disabled button
        _rerun(at)
        page03_mocks['enqueue'].assert_not_called()
        page03_mocks['batch'].assert_not_called()
        assert 'Confirm' in " ".join(e.value for e in at.error)


# ============================================================================
# Recommendations (page_02)
# ============================================================================

def _rec_app():
    import pandas as pd
    import streamlit as st
    from hcc_advisor.views.page_02_recommendations import execute_batch_compression
    sel = pd.DataFrame({'ID': [7, 8], 'Table': ['T1', 'T2'], 'Owner': ['APP', 'APP'],
                        'Advised': ['QUERY HIGH', 'OLTP'], 'Partition': [None, 'P2']})
    execute_batch_compression(sel, sel, st.session_state['t_dry_run'], st.session_state['t_dop'],
                              background=st.session_state['t_background'],
                              confirmed=st.session_state['t_confirmed'])


def _run_rec(dry_run=False, dop=6, background=True, confirmed=True):
    at = AppTest.from_function(_rec_app, default_timeout=10)
    for key, value in {'authenticated': True, 'role': 'operator', 'active_database_id': 1,
                       't_dry_run': dry_run, 't_dop': dop, 't_background': background,
                       't_confirmed': confirmed}.items():
        at.session_state[key] = value
    return at.run()


def _detailed_tab_app():
    from unittest.mock import patch
    import pandas as pd
    import streamlit as st
    from hcc_advisor.utils.target_queries import TargetQueries
    from hcc_advisor.views import page_02_recommendations as p02
    recs = pd.DataFrame({'recommendation_id': [7, 8], 'table_owner': ['APP', 'APP'],
                         'table_name': ['T1', 'T2'], 'partition_name': [None, 'P2'],
                         'recommended_strategy': ['QUERY HIGH', 'OLTP'],
                         'current_size_mb': [10.0, 20.0], 'savings_pct': [50.0, 60.0]})

    def all_selected(df, **kwargs):     # AppTest cannot tick data_editor cells
        df = df.copy()
        df['Select'] = True
        return df
    with patch.object(st, 'data_editor', side_effect=all_selected), \
            patch.object(p02, 'show_analysis_details'), \
            patch.object(TargetQueries, 'get_cpu_count', return_value=16):
        p02.show_detailed_tab(recs)


@pytest.fixture
def rec_mocks():
    with patch.object(TargetQueries, 'enqueue_compression_jobs', return_value=ENQ_OK) as enqueue, \
            patch.object(TargetQueries, 'drain_compression_queue', return_value=DRAIN_OK) as drain, \
            patch.object(TargetQueries, 'execute_compression',
                         return_value={'success': True, 'message': 'done'}) as execute:
        yield {'enqueue': enqueue, 'drain': drain, 'execute': execute}


@pytest.mark.unit
class TestRecommendationsExecution:

    def test_background_queues_with_the_parallel_degree(self, rec_mocks):
        _run_rec(dop=6, background=True)
        items = rec_mocks['enqueue'].call_args.args[0]
        assert [(i['table_name'], i['partition_name'], i['dop']) for i in items] == \
            [('T1', None, 6), ('T2', 'P2', 6)]
        rec_mocks['drain'].assert_called_once_with(1)
        rec_mocks['execute'].assert_not_called()

    @pytest.mark.parametrize('dry_run', [False, True])
    def test_synchronous_path_passes_the_parallel_degree(self, rec_mocks, dry_run):
        _run_rec(dry_run=dry_run, dop=6, background=False)
        assert rec_mocks['execute'].call_count == 2
        assert all(c.kwargs['parallel_degree'] == 6 for c in rec_mocks['execute'].call_args_list)
        rec_mocks['enqueue'].assert_not_called()

    def test_live_execution_requires_confirmation(self, rec_mocks):
        for background in (True, False):
            at = _run_rec(background=background, confirmed=False)
            assert 'Confirm Execution' in " ".join(e.value for e in at.error)
        rec_mocks['enqueue'].assert_not_called()
        rec_mocks['execute'].assert_not_called()

    def test_dry_run_needs_no_confirmation(self, rec_mocks):
        _run_rec(dry_run=True, background=True, confirmed=False)
        assert rec_mocks['execute'].call_count == 2       # DDL preview only
        assert all(c.kwargs['dry_run'] is True for c in rec_mocks['execute'].call_args_list)
        rec_mocks['enqueue'].assert_not_called()

    def test_page_button_needs_confirmation_and_passes_parallel(self, rec_mocks):
        at = AppTest.from_function(_detailed_tab_app, default_timeout=10)
        at.session_state['authenticated'] = True
        at.session_state['role'] = 'operator'
        at.session_state['active_database_id'] = 1
        at.run()
        at.checkbox(key='batch_dry_run').uncheck().run()
        assert at.checkbox(key='rec_background').value is True     # recommended default
        assert at.button[0].disabled                                # not confirmed yet
        at.button[0].click().run()                                  # forced click
        rec_mocks['enqueue'].assert_not_called()
        rec_mocks['execute'].assert_not_called()

        at.checkbox(key='rec_confirm_execution').check().run()
        assert not at.button[0].disabled
        assert at.slider(key='batch_parallel').max == 8             # CPU_COUNT/2
        at.slider(key='batch_parallel').set_value(8)
        at.button[0].click().run()
        items = rec_mocks['enqueue'].call_args.args[0]
        assert [(i['table_name'], i['dop']) for i in items] == [('T1', 8), ('T2', 8)]
        rec_mocks['execute'].assert_not_called()
