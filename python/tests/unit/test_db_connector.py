"""
Unit tests for the connector helpers the other suites don't reach:
CentralConnector / TargetConnector stored-procedure calls, PL/SQL with OUT
binds, REF CURSOR functions, connection tests and pool lifecycle.

- execute_procedure commits and returns callproc's result; a database error
  is shown with st.error and returns None.
- execute_procedure_with_output converts OUT binds to the requested Python
  type (NULL stays None) and re-raises after reporting an error.
- call_function_cursor wraps the call in a PL/SQL block and returns the REF
  CURSOR rows as a DataFrame (empty on error).
- Pools: initialize_pool is idempotent unless forced; close_pool closes and
  forgets the pool; a target's pool is looked up from the registry when no
  login is given, and an unknown target is a ValueError.

execute_query / execute_dml / execute_plsql error handling is covered by
test_db_error_surfacing, timeouts and pool locking by test_connection_timeouts.
No database: connections come from fake pools.
"""
from unittest.mock import MagicMock

import oracledb
import pandas as pd
import pytest

from hcc_advisor.config import Config
from hcc_advisor.utils import central_connector as cc_module
from hcc_advisor.utils import target_connector as tc_module
from hcc_advisor.utils.central_connector import CentralConnector
from hcc_advisor.utils.central_queries import CentralQueries
from hcc_advisor.utils.target_connector import TargetConnector


class FakeVar:
    """cursor.var(): an OUT bind whose value the fake 'database' sets."""

    def __init__(self, db_type, size=None):
        self.db_type = db_type
        self.size = size
        self.value = None

    def getvalue(self):
        return self.value


class FakeRefCursor:
    def __init__(self, rows, columns):
        self._rows = rows
        self.description = [(c, None, None, None, None, None, None) for c in columns]
        self.closed = False

    def fetchall(self):
        return self._rows

    def close(self):
        self.closed = True


class FakeCursor:
    def __init__(self, db):
        self.db = db
        self.closed = False

    def var(self, db_type, size=None):
        var = FakeVar(db_type, size)
        self.db.vars.append(var)
        return var

    def callproc(self, name, params=None):
        self.db.calls.append(('callproc', name, params))
        if self.db.error:
            raise self.db.error
        return list(params or [])

    def execute(self, sql, params=None):
        self.db.calls.append(('execute', ' '.join(sql.split()), params))
        if self.db.error:
            raise self.db.error
        self.db.on_execute(params or {})

    def fetchone(self):
        return (1,)

    def close(self):
        self.closed = True


class FakeConn:
    def __init__(self, db):
        self.db = db

    def cursor(self):
        return FakeCursor(self.db)

    def commit(self):
        self.db.commits += 1


class FakeDB:
    def __init__(self):
        self.calls = []
        self.vars = []
        self.commits = 0
        self.error = None
        self.on_execute = lambda params: None
        self.pool = MagicMock(name='pool')
        self.pool.acquire.side_effect = lambda: FakeConn(self)
        self.st = MagicMock(name='st')


@pytest.fixture
def central(monkeypatch):
    db = FakeDB()
    monkeypatch.setattr(CentralConnector, '_pool', db.pool)
    monkeypatch.setattr(cc_module, 'st', db.st)
    monkeypatch.setattr(cc_module, 'is_debug_enabled', lambda: False)
    for name in ('log_error', 'log_db_error', 'log_info', 'log_debug'):
        monkeypatch.setattr(cc_module, name, MagicMock())
    return db


@pytest.fixture
def target(monkeypatch):
    db = FakeDB()
    monkeypatch.setattr(TargetConnector, 'get_pool',
                        classmethod(lambda cls, database_id, conn_config: db.pool))
    monkeypatch.setattr(CentralQueries, 'get_target_database',
                        lambda database_id: {'username': 'u'} if database_id == 1 else None)
    monkeypatch.setattr(tc_module, 'st', db.st)
    monkeypatch.setattr(tc_module, 'is_debug_enabled', lambda: False)
    for name in ('log_error', 'log_db_error', 'log_info', 'log_debug'):
        monkeypatch.setattr(tc_module, name, MagicMock())
    return db


# The same behaviour is checked on both connectors: (fixture, call adapter).
def _central_call(method):
    return lambda *args, **kwargs: getattr(CentralConnector, method)(*args, **kwargs)


def _target_call(method):
    return lambda *args, **kwargs: getattr(TargetConnector, method)(1, *args, **kwargs)


CONNECTORS = [('central', _central_call), ('target', _target_call)]


@pytest.fixture(params=CONNECTORS, ids=[c[0] for c in CONNECTORS])
def conn(request):
    fixture_name, adapter = request.param
    return request.getfixturevalue(fixture_name), adapter


def _errors(db) -> str:
    return ' | '.join(c.args[0] for c in db.st.error.call_args_list)


# ---------------------------------------------------------------------------
# Stored procedures
# ---------------------------------------------------------------------------

@pytest.mark.unit
@pytest.mark.database
class TestExecuteProcedure:

    def test_calls_commits_and_returns_result(self, conn):
        db, call = conn
        assert call('execute_procedure')('pkg.run', ['HR', 5]) == ['HR', 5]
        assert db.calls == [('callproc', 'pkg.run', ['HR', 5])]
        assert db.commits == 1

    def test_without_parameters(self, conn):
        db, call = conn
        call('execute_procedure')('pkg.refresh')
        assert db.calls == [('callproc', 'pkg.refresh', None)]

    def test_error_is_reported_and_returns_none(self, conn):
        db, call = conn
        db.error = oracledb.DatabaseError('ORA-06550: line 1, column 7')
        assert call('execute_procedure')('pkg.run') is None
        assert 'procedure execution error' in _errors(db)
        assert 'ORA-06550' in _errors(db)
        assert db.commits == 0


# ---------------------------------------------------------------------------
# PL/SQL with OUT binds
# ---------------------------------------------------------------------------

@pytest.mark.unit
@pytest.mark.database
class TestProcedureWithOutput:

    def test_out_binds_are_converted(self, conn):
        db, call = conn

        def fill(params):
            params['n'].value = 42.0
            params['ratio'].value = 2.5
            params['msg'].value = 'done'
            params['other'].value = 'raw'
        db.on_execute = fill

        result = call('execute_procedure_with_output')(
            'BEGIN pkg.run(:owner, :n, :ratio, :msg, :other); END;',
            in_params={'owner': 'HR'},
            out_params={'n': int, 'ratio': float, 'msg': str, 'other': bytes})

        assert result == {'n': 42, 'ratio': 2.5, 'msg': 'done', 'other': 'raw'}
        assert isinstance(result['n'], int)
        _, _, binds = db.calls[0]
        assert binds['owner'] == 'HR'
        assert {v.db_type for v in db.vars} == {oracledb.NUMBER, oracledb.STRING}
        assert db.commits == 1

    def test_null_out_binds_stay_none(self, conn):
        _, call = conn
        result = call('execute_procedure_with_output')(
            'BEGIN :n := NULL; :r := NULL; END;', out_params={'n': int, 'r': float})
        assert result == {'n': None, 'r': None}

    def test_error_is_reported_and_raised(self, conn):
        db, call = conn
        db.error = oracledb.DatabaseError('ORA-20001: boom')
        with pytest.raises(oracledb.DatabaseError):
            call('execute_procedure_with_output')('BEGIN x; END;', out_params={'n': int})
        assert 'PL/SQL execution error' in _errors(db)


# ---------------------------------------------------------------------------
# REF CURSOR functions
# ---------------------------------------------------------------------------

@pytest.mark.unit
@pytest.mark.database
class TestFunctionCursor:

    def test_rows_become_a_dataframe(self, conn):
        db, call = conn
        ref = FakeRefCursor([('HR', 'EMP'), ('HR', 'DEPT')], ['OWNER', 'TABLE_NAME'])

        def fill(params):
            params['result_cursor'].value = ref
        db.on_execute = fill

        df = call('call_function_cursor')('pkg.tables(:owner)', {'owner': 'HR'})

        assert list(df.columns) == ['OWNER', 'TABLE_NAME']
        assert df['TABLE_NAME'].tolist() == ['EMP', 'DEPT']
        _, sql, binds = db.calls[0]
        assert sql == 'BEGIN :result_cursor := pkg.tables(:owner); END;'
        assert binds['owner'] == 'HR'
        assert db.vars[0].db_type is oracledb.CURSOR
        assert ref.closed

    def test_error_returns_empty_frame(self, conn):
        db, call = conn
        db.error = oracledb.DatabaseError('ORA-00904: invalid identifier')
        df = call('call_function_cursor')('pkg.tables(:owner)', {'owner': 'HR'})
        assert isinstance(df, pd.DataFrame) and df.empty
        assert 'function cursor execution error' in _errors(db)


# ---------------------------------------------------------------------------
# Connection tests
# ---------------------------------------------------------------------------

@pytest.mark.unit
@pytest.mark.database
class TestConnectionTest:

    def test_central_success(self, central):
        assert CentralConnector.test_connection() is True
        assert central.calls == [('execute', 'SELECT 1 FROM DUAL', None)]

    def test_central_failure(self, central):
        central.pool.acquire.side_effect = oracledb.OperationalError('DPY-6005: cannot connect')
        assert CentralConnector.test_connection() is False
        assert 'connection test failed' in _errors(central)

    def test_target_success(self, target):
        assert TargetConnector.test_connection_by_id(1) is True

    def test_unregistered_target_fails_cleanly(self, target):
        assert TargetConnector.test_connection_by_id(99) is False
        assert 'not found in central registry' in _errors(target)


# ---------------------------------------------------------------------------
# Pool lifecycle
# ---------------------------------------------------------------------------

@pytest.mark.unit
@pytest.mark.database
class TestPoolLifecycle:

    @pytest.fixture
    def create_pool(self, monkeypatch):
        pools = []

        def create(**kwargs):
            pool = MagicMock(name=f'pool{len(pools)}')
            pools.append((pool, kwargs))
            return pool
        monkeypatch.setattr(oracledb, 'create_pool', create)
        monkeypatch.setattr(CentralConnector, '_pool', None)
        for name in ('log_error', 'log_info'):
            monkeypatch.setattr(cc_module, name, MagicMock())
        monkeypatch.setattr(cc_module, 'st', MagicMock())
        return pools

    def test_initialize_is_idempotent_unless_forced(self, create_pool):
        CentralConnector.initialize_pool()
        CentralConnector.initialize_pool()
        assert len(create_pool) == 1
        first = create_pool[0][0]

        CentralConnector.initialize_pool(force_reinit=True)
        assert len(create_pool) == 2
        first.close.assert_called_once()
        assert CentralConnector._pool is create_pool[1][0]

    def test_pool_uses_the_central_settings(self, create_pool, monkeypatch):
        monkeypatch.setattr(Config, 'CENTRAL_DB_USER', 'COMPRESSION_MGR')
        CentralConnector.initialize_pool()
        kwargs = create_pool[0][1]
        assert kwargs['user'] == 'COMPRESSION_MGR'
        assert kwargs['dsn'] == Config.get_central_db_dsn()
        assert kwargs['min'] == Config.CENTRAL_POOL_MIN
        assert kwargs['max'] == Config.CENTRAL_POOL_MAX

    def test_failed_creation_is_reported_and_raised(self, monkeypatch, create_pool):
        monkeypatch.setattr(oracledb, 'create_pool',
                            MagicMock(side_effect=oracledb.DatabaseError('ORA-01017')))
        with pytest.raises(oracledb.DatabaseError):
            CentralConnector.initialize_pool()
        assert CentralConnector._pool is None
        assert 'Failed to create central DB connection pool' in \
            cc_module.st.error.call_args.args[0]

    def test_close_pool(self, create_pool):
        CentralConnector.initialize_pool()
        pool = CentralConnector._pool
        CentralConnector.close_pool()
        pool.close.assert_called_once()
        assert CentralConnector._pool is None
        CentralConnector.close_pool()  # already closed: no-op

    def test_close_pool_survives_a_driver_error(self, create_pool):
        CentralConnector.initialize_pool()
        CentralConnector._pool.close.side_effect = oracledb.DatabaseError('DPY-1002')
        CentralConnector.close_pool()
        assert CentralConnector._pool is None

    def test_target_close_all_pools(self, monkeypatch):
        pools = {7: MagicMock(name='p7'), 8: MagicMock(name='p8')}
        monkeypatch.setattr(TargetConnector, '_pools', dict(pools))
        monkeypatch.setattr(TargetConnector, '_pool_configs', {7: {}, 8: {}})
        monkeypatch.setattr(tc_module, 'log_info', MagicMock())
        TargetConnector.close_all_pools()
        assert TargetConnector._pools == {}
        assert TargetConnector._pool_configs == {}
        for pool in pools.values():
            pool.close.assert_called_once()
