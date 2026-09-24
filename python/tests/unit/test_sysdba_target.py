"""
Unit tests for registering and using a target database as SYS / SYSDBA:
login parsing, connect/pool kwargs, pool invalidation, registry persistence
of CONNECTION_MODE (incl. schema drift), and SYS-specific analysis guards.
"""
import argparse
import re
from unittest.mock import MagicMock, patch

import oracledb
import pandas as pd
import pytest

from hcc_advisor.utils import migration
from hcc_advisor.utils.central_connector import CentralConnector
from hcc_advisor.utils.central_queries import CentralQueries, _cached_target_databases
from hcc_advisor.utils.target_connector import (
    TargetConnector, build_connect_kwargs, parse_target_login,
)
from hcc_advisor.utils.target_queries import TargetQueries, is_protected_schema
from hcc_advisor.views import page_06_connections


SYS_CONFIG = {
    'username': 'SYS', 'password': 'pw', 'host': 'dbhost', 'port': 1521,
    'service': 'FREEPDB1', 'connection_mode': 'SYSDBA',
}


def _binds(sql: str) -> set:
    """Named bind placeholders used in a SQL statement."""
    return set(re.findall(r':(\w+)', sql))


# ============================================================================
# Login parsing / connect kwargs
# ============================================================================

@pytest.mark.unit
class TestParseTargetLogin:

    @pytest.mark.parametrize("username, mode, expected", [
        ('sys as sysdba', None, ('sys', 'SYSDBA')),
        ('SYS AS SYSDBA', 'NORMAL', ('SYS', 'SYSDBA')),
        ('  SYS   as   SysDba  ', 'NORMAL', ('SYS', 'SYSDBA')),
        ('SYS', 'NORMAL', ('SYS', 'SYSDBA')),       # SYS can't log on NORMAL (ORA-28009)
        ('sys', None, ('sys', 'SYSDBA')),
        ('SYS', 'SYSDBA', ('SYS', 'SYSDBA')),
        ('COMPRESSION_MGR', 'NORMAL', ('COMPRESSION_MGR', 'NORMAL')),
        ('COMPRESSION_MGR', None, ('COMPRESSION_MGR', 'NORMAL')),
        ('admin', 'sysdba', ('admin', 'SYSDBA')),
        ('admin as sysdba', 'NORMAL', ('admin', 'SYSDBA')),
        ('MASTER', 'NORMAL', ('MASTER', 'NORMAL')),  # no false "as" match
        ('SYSTEM', 'NORMAL', ('SYSTEM', 'NORMAL')),
    ])
    def test_parse(self, username, mode, expected):
        assert parse_target_login(username, mode) == expected

    def test_non_string_mode_defaults_to_normal(self):
        # pandas can hand back NaN for a NULL CONNECTION_MODE
        assert parse_target_login('SCOTT', float('nan')) == ('SCOTT', 'NORMAL')

    @pytest.mark.parametrize("username, mode", [
        ('sys as sysoper', None),
        ('SYS', 'SYSOPER'),
        ('SCOTT', 'SYSASM'),
    ])
    def test_unsupported_mode_rejected(self, username, mode):
        with pytest.raises(ValueError):
            parse_target_login(username, mode)


@pytest.mark.unit
class TestBuildConnectKwargs:

    def test_sysdba(self):
        assert build_connect_kwargs(SYS_CONFIG) == {
            'user': 'SYS', 'password': 'pw', 'dsn': 'dbhost:1521/FREEPDB1',
            'mode': oracledb.AUTH_MODE_SYSDBA,
        }

    def test_normal_has_no_mode(self):
        kwargs = build_connect_kwargs({**SYS_CONFIG, 'username': 'COMPRESSION_MGR',
                                       'connection_mode': 'NORMAL'})
        assert 'mode' not in kwargs
        assert kwargs['user'] == 'COMPRESSION_MGR'

    def test_ui_mode_key_and_typed_suffix(self):
        cfg = {k: v for k, v in SYS_CONFIG.items() if k != 'connection_mode'}
        kwargs = build_connect_kwargs({**cfg, 'username': 'sys as sysdba', 'mode': 'NORMAL'})
        assert kwargs['user'] == 'sys'
        assert kwargs['mode'] == oracledb.AUTH_MODE_SYSDBA

    def test_missing_mode_for_sys_still_sysdba(self):
        # Registry rows from a central schema without CONNECTION_MODE
        cfg = {k: v for k, v in SYS_CONFIG.items() if k != 'connection_mode'}
        assert build_connect_kwargs(cfg)['mode'] == oracledb.AUTH_MODE_SYSDBA


# ============================================================================
# TargetConnector pools / direct connections
# ============================================================================

@pytest.fixture
def clean_pools():
    TargetConnector._pools.clear()
    TargetConnector._pool_configs.clear()
    yield
    TargetConnector._pools.clear()
    TargetConnector._pool_configs.clear()


@pytest.mark.unit
class TestTargetConnectorPools:

    def test_pool_created_with_sysdba(self, clean_pools):
        with patch('hcc_advisor.utils.target_connector.oracledb.create_pool') as create_pool:
            pool = TargetConnector.get_pool(7, SYS_CONFIG)
        assert pool is create_pool.return_value
        kwargs = create_pool.call_args.kwargs
        assert kwargs['user'] == 'SYS'
        assert kwargs['mode'] == oracledb.AUTH_MODE_SYSDBA
        assert kwargs['dsn'] == 'dbhost:1521/FREEPDB1'
        assert {'min', 'max', 'increment'} <= kwargs.keys()

    def test_pool_reused_for_same_login(self, clean_pools):
        with patch('hcc_advisor.utils.target_connector.oracledb.create_pool') as create_pool:
            first = TargetConnector.get_pool(7, SYS_CONFIG)
            second = TargetConnector.get_pool(7, dict(SYS_CONFIG))
        assert first is second
        assert create_pool.call_count == 1

    def test_stale_pool_replaced_when_login_changes(self, clean_pools):
        old_pool, new_pool = MagicMock(name='old'), MagicMock(name='new')
        normal = {**SYS_CONFIG, 'username': 'COMPRESSION_MGR', 'connection_mode': 'NORMAL'}
        with patch('hcc_advisor.utils.target_connector.oracledb.create_pool',
                   side_effect=[old_pool, new_pool]) as create_pool:
            assert TargetConnector.get_pool(7, normal) is old_pool
            assert TargetConnector.get_pool(7, SYS_CONFIG) is new_pool
        old_pool.close.assert_called_once()
        assert create_pool.call_args.kwargs['mode'] == oracledb.AUTH_MODE_SYSDBA

    def test_close_pool_forgets_login(self, clean_pools):
        with patch('hcc_advisor.utils.target_connector.oracledb.create_pool'):
            TargetConnector.get_pool(7, SYS_CONFIG)
        TargetConnector.close_pool(7)
        assert 7 not in TargetConnector._pools
        assert 7 not in TargetConnector._pool_configs

    def test_direct_test_uses_sysdba(self):
        with patch('hcc_advisor.utils.target_connector.oracledb.connect') as connect:
            assert TargetConnector.test_connection_direct(SYS_CONFIG) is True
        assert connect.call_args.kwargs['mode'] == oracledb.AUTH_MODE_SYSDBA

    def test_direct_test_rejects_sysoper_without_connecting(self):
        with patch('hcc_advisor.utils.target_connector.oracledb.connect') as connect:
            assert TargetConnector.test_connection_direct(
                {**SYS_CONFIG, 'connection_mode': 'SYSOPER'}) is False
        connect.assert_not_called()


@pytest.mark.unit
class TestConnectionsPageTest:

    def _fake_conn(self):
        conn = MagicMock()
        conn.cursor.return_value.fetchone.return_value = ('Oracle Database 23ai',)
        return conn

    def test_typed_sys_as_sysdba(self):
        details = {'host': 'dbhost', 'port': 1521, 'service': 'FREEPDB1',
                   'username': 'SYS AS SYSDBA', 'password': 'pw', 'mode': 'NORMAL'}
        with patch.object(page_06_connections.oracledb, 'connect',
                          return_value=self._fake_conn()) as connect:
            ok, _msg, version = page_06_connections.test_target_connection(details)
        assert ok and version == 'Oracle Database 23ai'
        assert connect.call_args.kwargs['user'] == 'SYS'
        assert connect.call_args.kwargs['mode'] == oracledb.AUTH_MODE_SYSDBA

    def test_sysoper_rejected(self):
        details = {'host': 'h', 'port': 1521, 'service': 's',
                   'username': 'sys as sysoper', 'password': 'pw'}
        with patch.object(page_06_connections.oracledb, 'connect') as connect:
            ok, msg, version = page_06_connections.test_target_connection(details)
        assert not ok and version is None and 'SYSOPER' in msg
        connect.assert_not_called()


# ============================================================================
# Central registry (CentralQueries)
# ============================================================================

@pytest.fixture
def central(monkeypatch):
    """Mock CentralConnector; `state` controls the fake dictionary/registry."""
    state = {'has_column': True, 'can_add_column': True, 'existing': None}
    calls = {'query': [], 'dml': [], 'plsql': []}

    def execute_query(sql, params=None, raise_on_error=False):
        calls['query'].append((sql, params))
        if 'user_tab_columns' in sql:
            return pd.DataFrame([{'COLUMN_COUNT': 1 if state['has_column'] else 0}])
        if 'is_active FROM t_target_databases' in sql:
            if state['existing'] is None:
                return pd.DataFrame()
            return pd.DataFrame([state['existing']])
        if 'SELECT database_id' in sql:
            return pd.DataFrame([{'DATABASE_ID': 42}])
        return pd.DataFrame()

    def execute_plsql(sql, params=None, commit=True, raise_on_error=False):
        calls['plsql'].append(sql)
        if state['can_add_column']:
            state['has_column'] = True
        return state['can_add_column']

    def execute_dml(sql, params=None, commit=True, raise_on_error=False):
        # Mirror python-oracledb: every bind must match a placeholder (DPY-4008/4010)
        assert set(params) == _binds(sql), (set(params), _binds(sql))
        calls['dml'].append((sql, params))
        return 1

    monkeypatch.setattr(CentralConnector, 'execute_query', execute_query)
    monkeypatch.setattr(CentralConnector, 'execute_plsql', execute_plsql)
    monkeypatch.setattr(CentralConnector, 'execute_dml', execute_dml)
    monkeypatch.setattr(CentralQueries, '_connection_mode_column_ok', False)
    close_pool = MagicMock()
    monkeypatch.setattr(TargetConnector, 'close_pool', close_pool)
    return state, calls, close_pool


def _new_target(**overrides):
    data = {
        'database_name': 'PROD', 'display_name': 'Prod', 'db_host': 'dbhost',
        'port': 1521, 'service_name': 'FREEPDB1', 'username': 'SYS AS SYSDBA',
        'password_encrypted': 'enc', 'description': '', 'environment': 'PRODUCTION',
        'platform_type': 'STANDARD', 'connection_mode': 'NORMAL',
        'oracle_version': 'Oracle Database 23ai',
    }
    data.update(overrides)
    return data


@pytest.mark.unit
class TestTargetRegistry:

    def test_cached_listing_returns_connection_mode(self, central):
        _state, calls, _ = central
        _cached_target_databases.clear()
        _cached_target_databases()
        sql = calls['query'][-1][0].lower()
        assert 'select *' in sql or 'connection_mode' in sql

    def test_add_stores_clean_username_and_sysdba(self, central):
        _state, calls, _ = central
        ok, _msg, new_id = CentralQueries.add_target_database(_new_target())
        assert ok and new_id == 42
        insert_sql, params = calls['dml'][-1]
        assert 'INSERT INTO t_target_databases' in insert_sql
        assert params['username'] == 'SYS'
        assert params['connection_mode'] == 'SYSDBA'
        assert calls['plsql'] == []

    def test_add_self_heals_missing_column(self, central):
        state, calls, _ = central
        state['has_column'] = False
        ok, _msg, _id = CentralQueries.add_target_database(_new_target())
        assert ok
        assert len(calls['plsql']) == 1 and 'ADD (connection_mode' in calls['plsql'][0]

    def test_add_actionable_error_when_column_cannot_be_added(self, central):
        state, calls, _ = central
        state['has_column'] = False
        state['can_add_column'] = False
        ok, msg, new_id = CentralQueries.add_target_database(_new_target())
        assert not ok and new_id is None
        assert '20260331-connection-mode-column' in msg
        assert calls['dml'] == []

    def test_add_sysoper_rejected(self, central):
        _state, calls, _ = central
        ok, msg, _id = CentralQueries.add_target_database(_new_target(username='sys as sysoper'))
        assert not ok and 'SYSOPER' in msg
        assert calls['dml'] == []

    def test_add_reactivates_removed_target(self, central):
        state, calls, close_pool = central
        state['existing'] = {'DATABASE_ID': 5, 'IS_ACTIVE': 'N'}
        ok, _msg, db_id = CentralQueries.add_target_database(_new_target())
        assert ok and db_id == 5
        update_sql, params = calls['dml'][-1]
        assert "is_active = 'Y'" in update_sql
        assert params['username'] == 'SYS' and params['connection_mode'] == 'SYSDBA'
        assert params['database_id'] == 5
        assert any('password_encrypted' in p for _s, p in calls['dml'])
        close_pool.assert_called_with(5)

    def test_add_active_duplicate_still_rejected(self, central):
        state, calls, _ = central
        state['existing'] = {'DATABASE_ID': 5, 'IS_ACTIVE': 'Y'}
        ok, msg, db_id = CentralQueries.add_target_database(_new_target())
        assert not ok and db_id == 5 and 'already exists' in msg
        assert calls['dml'] == []

    def test_update_persists_mode_and_binds_only_placeholders(self, central):
        _state, calls, close_pool = central
        ok, _msg = CentralQueries.update_target_database(3, _new_target(username='SYS'))
        assert ok
        update_sql, params = calls['dml'][-1]
        assert 'connection_mode = :connection_mode' in update_sql
        assert "is_active = 'Y'" not in update_sql
        assert params['connection_mode'] == 'SYSDBA'
        close_pool.assert_called_with(3)

    def test_update_missing_field(self, central):
        _state, calls, _ = central
        data = _new_target()
        del data['db_host']
        ok, msg = CentralQueries.update_target_database(3, data)
        assert not ok and 'db_host' in msg
        assert calls['dml'] == []

    def test_delete_closes_pool(self, central):
        _state, _calls, close_pool = central
        ok, _msg = CentralQueries.delete_target_database(9)
        assert ok
        close_pool.assert_called_with(9)


# ============================================================================
# SYS-specific analysis / execution guards (TargetQueries)
# ============================================================================

@pytest.mark.unit
class TestSysGuards:

    @pytest.mark.parametrize("owner", ['SYS', 'sys', 'SYSTEM', 'AUDSYS', 'XDB'])
    def test_protected_schemas(self, owner):
        assert is_protected_schema(owner)
        with pytest.raises(ValueError):
            TargetQueries.generate_ddl(owner.upper(), 'SOME_TABLE', 'OLTP')

    def test_application_schema_allowed(self):
        assert not is_protected_schema('HR')
        assert not is_protected_schema(None)
        assert 'ALTER TABLE HR.EMPLOYEES' in TargetQueries.generate_ddl('HR', 'EMPLOYEES', 'OLTP')

    def test_ctas_fallback_guards_sys_schema(self):
        with patch('hcc_advisor.utils.target_queries.TargetConnector.execute_procedure_with_output',
                   return_value={'basic_ratio': -1.0, 'oltp_ratio': -1.0}) as proc:
            ratios = TargetQueries._get_compression_ratios_ctas(1, 'HR', 'EMPLOYEES')
        assert ratios == {'basic': 1, 'oltp': 1}
        plsql = proc.call_args.args[1]
        guard = plsql.index("SYS_CONTEXT('USERENV', 'CURRENT_SCHEMA') = 'SYS'")
        assert guard < plsql.index('CREATE TABLE TMP_CMP_UNC')

    def test_ctas_fallback_normal_ratios_pass_through(self):
        with patch('hcc_advisor.utils.target_queries.TargetConnector.execute_procedure_with_output',
                   return_value={'basic_ratio': 2.5, 'oltp_ratio': 2.1}):
            assert TargetQueries._get_compression_ratios_ctas(1, 'HR', 'EMPLOYEES') == \
                {'basic': 2.5, 'oltp': 2.1}

    def test_schema_picker_hides_oracle_maintained(self):
        with patch('hcc_advisor.utils.target_queries.TargetConnector.execute_query',
                   return_value=pd.DataFrame({'OWNER': ['HR']})) as query:
            assert TargetQueries.get_available_schemas(1) == ['HR']
        assert "oracle_maintained = 'Y'" in query.call_args.args[1]


# ============================================================================
# Migration CLI registration
# ============================================================================

@pytest.mark.unit
class TestMigrationSysdba:

    @pytest.fixture(autouse=True)
    def _key(self, monkeypatch):
        from cryptography.fernet import Fernet
        monkeypatch.setattr(migration.config, 'ENCRYPTION_KEY', Fernet.generate_key().decode())

    def _args(self, **overrides):
        values = dict(host='dbhost', port=1521, service='FREEPDB1', username='sys as sysdba',
                      password='pw', name='Prod DB', description=None,
                      environment='PRODUCTION', platform='STANDARD', mode='NORMAL')
        values.update(overrides)
        return argparse.Namespace(**values)

    def _central(self, has_column):
        central = MagicMock()
        cur = central.cursor.return_value
        cur.fetchone.side_effect = [(1 if has_column else 0,), (11,)]
        return central, cur

    def test_register_with_connection_mode(self):
        central, cur = self._central(has_column=True)
        assert migration.register_target_database(central, self._args(), dry_run=False) == 11
        insert_sql, params = cur.execute.call_args_list[1].args
        assert 'connection_mode' in insert_sql
        assert params['username'] == 'sys' and params['connection_mode'] == 'SYSDBA'
        assert set(params) == _binds(insert_sql)

    def test_register_sysdba_without_column_fails_clearly(self):
        central, _cur = self._central(has_column=False)
        with pytest.raises(RuntimeError, match='20260331-connection-mode-column'):
            migration.register_target_database(central, self._args(), dry_run=False)

    def test_register_normal_without_column_uses_legacy_insert(self):
        central, cur = self._central(has_column=False)
        args = self._args(username='COMPRESSION_MGR')
        assert migration.register_target_database(central, args, dry_run=False) == 11
        insert_sql, params = cur.execute.call_args_list[1].args
        assert 'connection_mode' not in insert_sql and 'connection_mode' not in params
        assert set(params) == _binds(insert_sql)

    def test_target_connection_uses_sysdba(self):
        with patch.object(migration.oracledb, 'connect') as connect:
            migration.get_target_connection(self._args())
        assert connect.call_args.kwargs['user'] == 'sys'
        assert connect.call_args.kwargs['mode'] == oracledb.AUTH_MODE_SYSDBA
