"""
Unit tests for version- and platform-aware compression DDL:

- the stored Oracle version banner is parsed into (major, minor), tolerating
  None / garbage (unknown = a modern release);
- MOVE ... ONLINE only where the target's version supports it (partitions and
  subpartitions 12.1+, tables 12.2+); older partition moves get UPDATE INDEXES,
  older table moves a plain MOVE followed by index rebuilds;
- HCC compression types are refused for STANDARD-platform targets on every
  path that creates DDL or a job (generate_ddl, execute_compression,
  batch_execute, rollback, enqueue, direct submit, queue drain, CSV import,
  SQL script export), EXADATA is unchanged;
- the exported SQL script rebuilds dependent indexes only after a MOVE that
  leaves them UNUSABLE, and exports subpartition jobs as MOVE SUBPARTITION.

The central registry and target databases are mocked.
"""
from unittest.mock import MagicMock

import pandas as pd
import pytest

from hcc_advisor.utils import oracle_capabilities as oc
from hcc_advisor.utils import target_queries as tq
from hcc_advisor.utils.central_connector import CentralConnector
from hcc_advisor.utils.central_queries import CentralQueries
from hcc_advisor.utils.oracle_capabilities import (
    HCC_NOT_SUPPORTED, hcc_block_reason, move_modifier, parse_oracle_version,
    supports_online_move,
)
from hcc_advisor.utils.sql_builder import (
    build_compression_script, gather_dependent_indexes, gather_target_info,
)
from hcc_advisor.utils.target_connector import TargetConnector
from hcc_advisor.utils.target_queries import TargetQueries
# The real lookup: tests/unit/conftest.py replaces tq.target_ddl_info per test.
from hcc_advisor.utils.target_queries import target_ddl_info as real_target_ddl_info
from hcc_advisor.views import page_12_scheduler as p12
from tests.unit.test_scheduler_queue import FakeCentral, FakeTarget


V11_2 = "Oracle Database 11g Enterprise Edition Release 11.2.0.4.0 - 64bit Production"
V12_1 = "Oracle Database 12c Enterprise Edition Release 12.1.0.2.0 - 64bit Production"
V12_2 = "Oracle Database 12c Enterprise Edition Release 12.2.0.1.0 - 64bit Production"
V19 = "Oracle Database 19c Enterprise Edition Release 19.0.0.0.0 - Production"
V23 = "Oracle Database 23ai Free Release 23.0.0.0.0 - Develop, Learn, and Run for Free"

HCC_TYPES = ['QUERY LOW', 'QUERY HIGH', 'ARCHIVE LOW', 'ARCHIVE HIGH',
             'QUERY_LOW', 'QUERY_HIGH', 'ARCHIVE_LOW', 'ARCHIVE_HIGH', 'query high']


def _target(monkeypatch, version=V19, platform='EXADATA'):
    """Make every target_ddl_info lookup return this target; returns the call log."""
    calls = []

    def fake(database_id):
        calls.append(database_id)
        return {'oracle_version': version, 'platform_type': platform}
    monkeypatch.setattr(tq, 'target_ddl_info', fake)
    return calls


# ============================================================================
# Version parsing
# ============================================================================

@pytest.mark.unit
class TestParseOracleVersion:

    @pytest.mark.parametrize('text, expected', [
        (V11_2, (11, 2)),
        (V12_1, (12, 1)),
        (V12_2, (12, 2)),
        ("Oracle Database 18c Express Edition Release 18.0.0.0.0 - Production", (18, 0)),
        (V19, (19, 0)),
        ("Oracle Database 21c Enterprise Edition Release 21.0.0.0.0 - Production", (21, 0)),
        (V23, (23, 0)),
        ("Oracle Database 23c Free, Release 23.0.0.0.0 - Developer-Release", (23, 0)),
        ("Personal Oracle9i Release 9.2.0.1.0 - Production", (9, 2)),
        (V19 + "\nVersion 19.21.0.0.0", (19, 0)),
        ("Version 19.21.0.0.0", (19, 21)),
        ("11.2.0.4.0", (11, 2)),
        ("  19.3.0.0.0  ", (19, 3)),
        ("19c", (19, 0)),
        ("Oracle Database 23ai", (23, 0)),
        ("Oracle Database 12c", (12, 1)),     # 12c alone: assume 12.1, the first 12c release
        ("Oracle Database 11g", (11, 1)),
    ])
    def test_known_versions(self, text, expected):
        assert parse_oracle_version(text) == expected

    @pytest.mark.parametrize('value', [
        None, float('nan'), '', '   ', 'None', 'nan', 'Unknown', 'garbage',
        'Oracle Database', 'v5.1', 'Release x.y',
    ])
    def test_unknown_is_none(self, value):
        assert parse_oracle_version(value) is None

    def test_unknown_text_is_logged_once(self, monkeypatch):
        logged = []
        monkeypatch.setattr(oc, 'log_warning', logged.append)
        monkeypatch.setattr(oc, '_UNPARSED_LOGGED', set())
        parse_oracle_version('Some Other Database 7')
        parse_oracle_version('Some Other Database 7')
        parse_oracle_version(None)
        assert len(logged) == 1 and 'modern release' in logged[0]

    @pytest.mark.parametrize('version, table, partition', [
        (V11_2, False, False),
        (V12_1, False, True),
        (V12_2, True, True),
        (V19, True, True),
        (V23, True, True),
        ((12, 1), False, True),
        (None, True, True),          # unknown: assume modern
        ('garbage', True, True),
    ])
    def test_supports_online_move(self, version, table, partition):
        assert supports_online_move(version, 'TABLE') is table
        assert supports_online_move(version, 'PARTITION') is partition
        assert supports_online_move(version, 'SUBPARTITION') is partition

    def test_unknown_level_is_rejected(self):
        with pytest.raises(ValueError, match='object level'):
            move_modifier(V19, 'INDEX')


# ============================================================================
# generate_ddl by version and level
# ============================================================================

_SEGMENTS = {
    'TABLE': dict(partition_name=None, subpartition_name=None),
    'PARTITION': dict(partition_name='P1', subpartition_name=None),
    'SUBPARTITION': dict(partition_name='P1', subpartition_name='SP1'),
}
_MOVE_LINE = {'TABLE': 'MOVE COMPRESS FOR OLTP', 'PARTITION': 'MOVE PARTITION P1',
              'SUBPARTITION': 'MOVE SUBPARTITION SP1'}


@pytest.mark.unit
class TestGenerateDdlByVersion:

    @pytest.mark.parametrize('version, level, tail', [
        (V11_2, 'TABLE', 'PARALLEL 4;'),
        (V11_2, 'PARTITION', 'UPDATE INDEXES PARALLEL 4;'),
        (V11_2, 'SUBPARTITION', 'UPDATE INDEXES PARALLEL 4;'),
        (V12_1, 'TABLE', 'PARALLEL 4;'),
        (V12_1, 'PARTITION', 'ONLINE PARALLEL 4;'),
        (V12_1, 'SUBPARTITION', 'ONLINE PARALLEL 4;'),
        (V12_2, 'TABLE', 'ONLINE PARALLEL 4;'),
        (V12_2, 'PARTITION', 'ONLINE PARALLEL 4;'),
        (V12_2, 'SUBPARTITION', 'ONLINE PARALLEL 4;'),
        (V19, 'TABLE', 'ONLINE PARALLEL 4;'),
        (V19, 'PARTITION', 'ONLINE PARALLEL 4;'),
        (V19, 'SUBPARTITION', 'ONLINE PARALLEL 4;'),
        (V23, 'TABLE', 'ONLINE PARALLEL 4;'),
        (V23, 'PARTITION', 'ONLINE PARALLEL 4;'),
        (V23, 'SUBPARTITION', 'ONLINE PARALLEL 4;'),
    ])
    def test_move_tail(self, version, level, tail):
        ddl = TargetQueries.generate_ddl('APP', 'ORDERS', 'OLTP', oracle_version=version,
                                         **_SEGMENTS[level])
        lines = ddl.split('\n')
        assert lines[0] == 'ALTER TABLE APP.ORDERS'
        assert lines[1] == _MOVE_LINE[level]
        assert lines[-1] == tail
        assert ('ONLINE' in ddl) is tail.startswith('ONLINE')

    def test_old_table_move_exact_text(self):
        assert TargetQueries.generate_ddl('APP', 'ORDERS', 'OLTP', oracle_version=V12_1) == \
            "ALTER TABLE APP.ORDERS\nMOVE COMPRESS FOR OLTP\nPARALLEL 4;"
        assert TargetQueries.generate_ddl('APP', 'ORDERS', 'BASIC', 'P1', oracle_version=V11_2,
                                          parallel_degree=8) == \
            "ALTER TABLE APP.ORDERS\nMOVE PARTITION P1\nCOMPRESS BASIC\nUPDATE INDEXES PARALLEL 8;"

    @pytest.mark.parametrize('level', list(_SEGMENTS))
    @pytest.mark.parametrize('version', [V12_2, V19, V23, None, 'Unknown'])
    def test_modern_or_unknown_is_unchanged(self, level, version):
        before = TargetQueries.generate_ddl('APP', 'ORDERS', 'QUERY HIGH', **_SEGMENTS[level])
        assert before.endswith('\nONLINE PARALLEL 4;')
        assert TargetQueries.generate_ddl('APP', 'ORDERS', 'QUERY HIGH', oracle_version=version,
                                          platform_type='EXADATA', **_SEGMENTS[level]) == before


# ============================================================================
# HCC on STANDARD platforms
# ============================================================================

@pytest.mark.unit
class TestHccPlatformCheck:

    @pytest.mark.parametrize('comp', HCC_TYPES)
    @pytest.mark.parametrize('platform', ['STANDARD', 'standard', ' Standard '])
    def test_generate_ddl_rejects_hcc_on_standard(self, comp, platform):
        with pytest.raises(ValueError, match=HCC_NOT_SUPPORTED) as exc:
            TargetQueries.generate_ddl('APP', 'ORDERS', comp, platform_type=platform)
        assert 'ORA-64307' in str(exc.value) and 'STANDARD' in str(exc.value)

    @pytest.mark.parametrize('comp', HCC_TYPES)
    def test_exadata_and_unknown_platforms_allow_hcc(self, comp):
        for platform in ('EXADATA', 'exadata', None, float('nan'), ''):
            ddl = TargetQueries.generate_ddl('APP', 'ORDERS', comp, platform_type=platform)
            assert 'COMPRESS FOR' in ddl

    @pytest.mark.parametrize('comp', ['NONE', 'BASIC', 'OLTP', 'ADV_LOW', 'ADV_HIGH', None])
    def test_non_hcc_types_allowed_on_standard(self, comp):
        assert hcc_block_reason(comp, 'STANDARD') is None
        TargetQueries.generate_ddl('APP', 'ORDERS', comp, platform_type='STANDARD')

    def test_execute_compression_refuses_before_any_write(self, monkeypatch):
        _target(monkeypatch, V19, 'STANDARD')
        store = MagicMock()
        monkeypatch.setattr(CentralQueries, 'store_compression_history', store)
        plsql = MagicMock()
        monkeypatch.setattr(TargetConnector, 'execute_plsql', plsql)
        for dry_run in (True, False):
            res = TargetQueries.execute_compression(1, 'APP', 'ORDERS', 'QUERY HIGH',
                                                    dry_run=dry_run)
            assert res['success'] is False and HCC_NOT_SUPPORTED in res['error']
        store.assert_not_called()
        plsql.assert_not_called()

    def test_execute_compression_exadata_unchanged(self, monkeypatch):
        _target(monkeypatch, V19, 'EXADATA')
        res = TargetQueries.execute_compression(1, 'APP', 'ORDERS', 'QUERY HIGH', dry_run=True)
        assert res['success'] is True
        assert res['ddl'] == TargetQueries.generate_ddl('APP', 'ORDERS', 'QUERY HIGH')

    def test_batch_execute_looks_up_once_and_rejects_per_item(self, monkeypatch):
        calls = _target(monkeypatch, V19, 'STANDARD')
        items = [{'owner': 'APP', 'table_name': 'T1', 'compression_type': 'QUERY HIGH'},
                 {'owner': 'APP', 'table_name': 'T2', 'compression_type': 'OLTP'},
                 {'owner': 'APP', 'table_name': 'T3', 'compression_type': 'ARCHIVE LOW'}]
        out = TargetQueries.batch_execute(1, items, dry_run=True, concurrency=3)
        assert (out['success'], out['errors']) == (1, 2)
        assert calls == [1]                                  # once for the batch
        for r in out['results']:
            if r['table_name'] != 'T2':
                assert HCC_NOT_SUPPORTED in r['result']['error']


# ============================================================================
# execute_compression / rollback DDL by version
# ============================================================================

@pytest.mark.unit
class TestExecutionByVersion:

    def test_dry_run_ddl_follows_target_version(self, monkeypatch):
        _target(monkeypatch, V11_2, 'STANDARD')
        res = TargetQueries.execute_compression(1, 'APP', 'ORDERS', 'OLTP', 'P1', dry_run=True)
        assert res['ddl'].endswith('\nUPDATE INDEXES PARALLEL 4;')

    @pytest.mark.parametrize('version, mode', [(V12_1, 'OFFLINE'), (V19, 'ONLINE')])
    def test_history_records_execution_mode(self, monkeypatch, version, mode):
        _target(monkeypatch, version, 'STANDARD')
        store = MagicMock(return_value=5)
        monkeypatch.setattr(CentralQueries, 'store_compression_history', store)
        monkeypatch.setattr(CentralConnector, 'execute_dml', MagicMock(return_value=1))
        monkeypatch.setattr(TargetConnector, 'execute_query', MagicMock(return_value=pd.DataFrame()))
        plsql = MagicMock(return_value=True)
        monkeypatch.setattr(TargetConnector, 'execute_plsql', plsql)
        res = TargetQueries.execute_compression(1, 'APP', 'ORDERS', 'OLTP', dry_run=False)
        assert res['success'] is True
        record = store.call_args.args[1]
        assert record['execution_mode'] == mode
        assert ('ONLINE' in plsql.call_args_list[0].args[1]) is (mode == 'ONLINE')

    @pytest.mark.parametrize('version, part, expected', [
        (V11_2, 'P1', 'MOVE PARTITION P1\nNOCOMPRESS\nUPDATE INDEXES PARALLEL 4'),
        (V12_1, None, 'MOVE NOCOMPRESS\nPARALLEL 4'),
        (V19, None, 'MOVE NOCOMPRESS\nONLINE PARALLEL 4'),
    ])
    def test_rollback_ddl_follows_target_version(self, monkeypatch, version, part, expected):
        _target(monkeypatch, version, 'STANDARD')
        plsql = MagicMock(return_value=True)
        monkeypatch.setattr(TargetConnector, 'execute_plsql', plsql)
        monkeypatch.setattr(TargetConnector, 'execute_query', MagicMock(return_value=pd.DataFrame()))
        monkeypatch.setattr(CentralConnector, 'execute_dml', MagicMock(return_value=1))
        res = TargetQueries.rollback_compression(7, 'SCOTT', 'SALES', part)
        assert res['success'] is True
        assert expected in plsql.call_args_list[0].args[1]


# ============================================================================
# Scheduler queue: enqueue, direct submit, drain
# ============================================================================

@pytest.fixture
def queue_dbs(monkeypatch):
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


@pytest.mark.unit
class TestQueuePlatformAndVersion:

    def test_enqueue_rejects_hcc_on_standard_with_reason(self, monkeypatch, queue_dbs):
        central, _ = queue_dbs
        calls = _target(monkeypatch, V19, 'STANDARD')
        out = TargetQueries.enqueue_compression_jobs([
            _item(partition_name='P1'), _item(partition_name='P2', compression_type='OLTP'),
            _item(partition_name='P3', compression_type='ARCHIVE_HIGH'),
        ])
        assert (out['added'], out['rejected']) == (1, 2)
        assert all(HCC_NOT_SUPPORTED in e for e in out['errors'])
        assert 'APP.ORDERS partition P1' in out['errors'][0]
        assert [r['partition_name'] for r in central.rows.values()] == ['P2']
        assert calls == [1]                                  # once per database, not per row

    def test_enqueue_exadata_unchanged(self, monkeypatch, queue_dbs):
        _target(monkeypatch, V19, 'EXADATA')
        out = TargetQueries.enqueue_compression_jobs([_item(), _item(partition_name='P1')])
        assert out == {'added': 2, 'duplicates': 0, 'rejected': 0, 'errors': []}

    def test_direct_submit_refuses_hcc_on_standard(self, monkeypatch, queue_dbs):
        central, target = queue_dbs
        _target(monkeypatch, V19, 'STANDARD')
        res = TargetQueries.submit_compression_job(1, 'APP', 'ORDERS', 'QUERY HIGH',
                                                   partition_name='P1')
        assert res['success'] is False and HCC_NOT_SUPPORTED in res['error']
        assert central.rows == {} and target.plsql == []

    def test_direct_submit_job_action_follows_version(self, monkeypatch, queue_dbs):
        central, target = queue_dbs
        calls = _target(monkeypatch, V11_2, 'EXADATA')
        res = TargetQueries.submit_compression_job(1, 'APP', 'ORDERS', 'QUERY HIGH',
                                                   partition_name='P1', parallel_degree=2)
        assert res['success'] is True
        (row,) = central.rows.values()
        assert row['original_ddl'].endswith('UPDATE INDEXES PARALLEL 2')
        assert 'ONLINE PARALLEL 2' not in row['original_ddl']
        assert 'UPDATE INDEXES PARALLEL 2' in target.plsql[0]
        assert calls == [1]                                  # validation and submit share it

    def test_queued_hcc_row_for_standard_fails_at_drain(self, monkeypatch, queue_dbs):
        central, target = queue_dbs
        # queued before this check existed (or before the target was re-registered)
        bad = central.add(partition_name='P1', compression_type_applied='QUERY HIGH',
                          parallel_degree=1)
        good = central.add(partition_name='P2', compression_type_applied='OLTP',
                           parallel_degree=1)
        calls = _target(monkeypatch, V19, 'STANDARD')
        stats = TargetQueries.drain_compression_queue(1)
        assert stats['failed'] == 1 and stats['submitted'] == 1
        assert central.status(bad) == 'FAILED'
        assert HCC_NOT_SUPPORTED in central.rows[bad]['error_message']
        assert central.status(good) == 'IN_PROGRESS'
        assert len(target.plsql) == 1
        assert calls == [1]                                  # once per database per drain


# ============================================================================
# Scheduler CSV import
# ============================================================================

def _obj(comp='QUERY HIGH', owner='APP'):
    return {'owner': owner, 'object_name': 'ORDERS', 'partition_name': None,
            'subpartition_name': None, 'compression_type': comp, 'dop': 4}


def _chk(exists=True, current='NONE'):
    return {'exists': exists, 'object_level': 'TABLE', 'current_compression': None,
            'current_compress_for': current}


@pytest.mark.unit
class TestCsvImportState:

    @pytest.mark.parametrize('comp', ['QUERY HIGH', 'ARCHIVE LOW', 'QUERY_LOW'])
    def test_hcc_on_standard_is_not_ready(self, comp):
        assert p12._import_row_state(_obj(comp), _chk(), 'STANDARD') == 'HCC NOT SUPPORTED'

    def test_exadata_and_non_hcc_are_ready(self):
        assert p12._import_row_state(_obj('QUERY HIGH'), _chk(), 'EXADATA') == 'READY'
        assert p12._import_row_state(_obj('OLTP'), _chk(), 'STANDARD') == 'READY'
        assert p12._import_row_state(_obj('QUERY HIGH'), _chk(), None) == 'READY'

    def test_other_states_unchanged(self):
        assert p12._import_row_state(_obj(), _chk(exists=False), 'STANDARD') == 'MISSING'
        assert p12._import_row_state(_obj(owner='SYS'), _chk(), 'STANDARD') == 'PROTECTED SCHEMA'
        assert p12._import_row_state(_obj('SUPER'), _chk(), 'STANDARD') == 'UNSUPPORTED COMPRESSION'
        assert p12._import_row_state(_obj('OLTP'), _chk(current='ADVANCED'), 'STANDARD') == \
            'ALREADY AT TARGET'


# ============================================================================
# Registry lookup
# ============================================================================

@pytest.mark.unit
class TestTargetDdlInfo:

    def _registry(self, monkeypatch, rows, by_id=None):
        monkeypatch.setattr(CentralQueries, 'get_target_databases',
                            staticmethod(lambda: pd.DataFrame(rows)))
        by_id_mock = MagicMock(return_value=by_id or {})
        monkeypatch.setattr(CentralQueries, 'get_target_database', by_id_mock)
        return by_id_mock

    def test_reads_the_cached_registry(self, monkeypatch):
        by_id = self._registry(monkeypatch, [
            {'DATABASE_ID': 1, 'ORACLE_VERSION': V11_2, 'PLATFORM_TYPE': 'EXADATA'},
            {'DATABASE_ID': 2, 'ORACLE_VERSION': V19, 'PLATFORM_TYPE': 'STANDARD'},
        ])
        assert real_target_ddl_info(1) == {'oracle_version': V11_2, 'platform_type': 'EXADATA'}
        assert real_target_ddl_info('2') == {'oracle_version': V19, 'platform_type': 'STANDARD'}
        by_id.assert_not_called()

    def test_null_platform_is_standard(self, monkeypatch):
        self._registry(monkeypatch, [
            {'DATABASE_ID': 1, 'ORACLE_VERSION': None, 'PLATFORM_TYPE': None}])
        assert real_target_ddl_info(1) == {'oracle_version': None, 'platform_type': 'STANDARD'}

    def test_inactive_target_is_read_by_id(self, monkeypatch):
        by_id = self._registry(monkeypatch, [], by_id={
            'database_id': 9, 'oracle_version': V12_1, 'platform_type': 'exadata'})
        assert real_target_ddl_info(9) == {'oracle_version': V12_1, 'platform_type': 'EXADATA'}
        by_id.assert_called_once_with(9)

    def test_unknown_target_is_all_none(self, monkeypatch):
        self._registry(monkeypatch, [])
        assert real_target_ddl_info(9) == {'oracle_version': None, 'platform_type': None}
        assert real_target_ddl_info(None) == {'oracle_version': None, 'platform_type': None}

    def test_registry_failure_is_all_none(self, monkeypatch):
        def boom():
            raise RuntimeError('ORA-12541')
        monkeypatch.setattr(CentralQueries, 'get_target_databases', staticmethod(boom))
        monkeypatch.setattr(CentralQueries, 'get_target_database', staticmethod(lambda did: {}))
        assert real_target_ddl_info(1) == {'oracle_version': None, 'platform_type': None}


# ============================================================================
# SQL script export
# ============================================================================

def _ops(rows, db_id=1):
    base = {'database_id': db_id, 'database_display': 'PROD', 'database_name': 'PROD',
            'owner': 'APP', 'object_name': 'ORDERS', 'partition_name': None,
            'subpartition_name': None, 'compression_type_applied': 'OLTP',
            'parallel_degree': 4, 'operation_status': 'QUEUED', 'error_message': None}
    return pd.DataFrame([{**base, **r} for r in rows])


_INDEX_MAP = {(1, 'APP', 'ORDERS'): {
    'indexes': [{'owner': 'APP', 'name': 'ORDERS_PK', 'partitioned': 'NO'},
                {'owner': 'APP', 'name': 'ORDERS_GPIX', 'partitioned': 'YES'}],
    'ind_partitions': {('APP', 'ORDERS_GPIX'): ['GP1', 'GP2']},
}}


def _targets(version, platform='EXADATA'):
    return {1: {'oracle_version': version, 'platform_type': platform}}


def _statements(script):
    """Executable lines of a script (comments dropped)."""
    return [ln for ln in script.split('\n') if ln.strip() and not ln.startswith('--')]


def _rebuilds(script):
    return [ln for ln in _statements(script) if ln.startswith('ALTER INDEX')]


@pytest.mark.unit
class TestExportScript:

    @pytest.mark.parametrize('version', [V12_2, V19, V23, None])
    def test_online_moves_omit_index_rebuilds(self, version):
        script = build_compression_script(
            _ops([{}, {'partition_name': 'P1'}, {'partition_name': 'P1', 'subpartition_name': 'SP1'}]),
            'All', 'PROD', _INDEX_MAP, targets=_targets(version))
        assert 'ALTER TABLE APP.ORDERS MOVE COMPRESS FOR OLTP ONLINE PARALLEL 4;' in script
        assert 'ALTER TABLE APP.ORDERS MOVE PARTITION P1 COMPRESS FOR OLTP ONLINE PARALLEL 4;' in script
        assert 'ALTER TABLE APP.ORDERS MOVE SUBPARTITION SP1 COMPRESS FOR OLTP ONLINE PARALLEL 4;' in script
        assert _rebuilds(script) == []
        assert script.count('-- No index rebuild: the ONLINE move keeps the indexes usable') == 3
        assert 'keep every index usable, so no ALTER INDEX' in script    # header explains why

    def test_non_online_table_move_rebuilds_indexes(self):
        script = build_compression_script(_ops([{}]), 'All', 'PROD', _INDEX_MAP,
                                          targets=_targets(V12_1))
        assert 'ALTER TABLE APP.ORDERS MOVE COMPRESS FOR OLTP PARALLEL 4;' in script
        assert 'ALTER INDEX APP.ORDERS_PK REBUILD ONLINE PARALLEL 4;' in script
        assert 'ALTER INDEX APP.ORDERS_GPIX REBUILD PARTITION GP1 ONLINE PARALLEL 4;' in script
        assert 'ALTER INDEX APP.ORDERS_GPIX REBUILD PARTITION GP2 ONLINE PARALLEL 4;' in script
        assert '-- Oracle version: 12.1, platform: EXADATA' in script

    def test_non_online_table_move_without_index_info_warns(self):
        script = build_compression_script(_ops([{}]), 'All', 'PROD', {}, targets=_targets(V11_2))
        assert _rebuilds(script) == []
        assert 'leaves the indexes of APP.ORDERS UNUSABLE' in script

    def test_old_partition_moves_use_update_indexes_not_rebuilds(self):
        script = build_compression_script(
            _ops([{'partition_name': 'P1'}, {'partition_name': 'P1', 'subpartition_name': 'SP1'}]),
            'All', 'PROD', _INDEX_MAP, targets=_targets(V11_2))
        assert 'ALTER TABLE APP.ORDERS MOVE PARTITION P1 COMPRESS FOR OLTP UPDATE INDEXES PARALLEL 4;' in script
        assert ('ALTER TABLE APP.ORDERS MOVE SUBPARTITION SP1 COMPRESS FOR OLTP '
                'UPDATE INDEXES PARALLEL 4;') in script
        assert _rebuilds(script) == []
        assert not [ln for ln in _statements(script) if 'ONLINE' in ln]

    def test_hcc_rows_skipped_for_standard_target(self):
        ops = _ops([{'compression_type_applied': 'QUERY HIGH'}, {'partition_name': 'P2'}])
        script = build_compression_script(ops, 'All', 'PROD', {}, targets=_targets(V19, 'STANDARD'))
        assert f'-- SKIPPED APP.ORDERS: {HCC_NOT_SUPPORTED}' in script
        assert 'QUERY HIGH ONLINE' not in script
        assert 'MOVE PARTITION P2 COMPRESS FOR OLTP ONLINE PARALLEL 4;' in script
        exa = build_compression_script(ops, 'All', 'PROD', {}, targets=_targets(V19, 'EXADATA'))
        assert 'ALTER TABLE APP.ORDERS MOVE COMPRESS FOR QUERY HIGH ONLINE PARALLEL 4;' in exa

    def test_invalid_subpartition_name_is_skipped(self):
        script = build_compression_script(
            _ops([{'partition_name': 'P1', 'subpartition_name': "SP1; DROP TABLE X"}]),
            'All', 'PROD', {}, targets=_targets(V19))
        assert '-- SKIPPED (invalid identifier)' in script and 'DROP TABLE X;' not in script

    def test_targets_resolved_from_registry_when_not_given(self, monkeypatch):
        calls = _target(monkeypatch, V12_1, 'EXADATA')
        script = build_compression_script(_ops([{}, {}, {'partition_name': 'P1'}]),
                                          'All', 'PROD', {})
        assert 'MOVE COMPRESS FOR OLTP PARALLEL 4;' in script
        assert calls == [1]                                  # once per database

    def test_gather_indexes_skips_online_moves(self, monkeypatch):
        query = MagicMock(return_value=pd.DataFrame())
        monkeypatch.setattr(TargetConnector, 'execute_query', query)
        ops = _ops([{}, {'partition_name': 'P1'}])
        assert gather_dependent_indexes(ops.copy(), _targets(V19)) == {}
        query.assert_not_called()
        gather_dependent_indexes(ops.copy(), _targets(V12_1))       # table move needs them
        sql = query.call_args_list[0].args[1]
        assert "IN ('ORDERS')" in sql
        query.reset_mock()
        gather_dependent_indexes(_ops([{'partition_name': 'P1'}]), _targets(V11_2))
        query.assert_not_called()                                  # UPDATE INDEXES

    def test_gather_target_info_one_lookup_per_database(self, monkeypatch):
        calls = _target(monkeypatch, V19, 'EXADATA')
        ops = pd.concat([_ops([{}, {}], db_id=1), _ops([{}], db_id=2)], ignore_index=True)
        info = gather_target_info(ops)
        assert set(info) == {1, 2} and sorted(calls) == [1, 2]


@pytest.mark.unit
class TestSchedulerExportSubpartitions:

    def test_export_query_selects_subpartition_name(self, monkeypatch):
        seen = []
        monkeypatch.setattr(CentralConnector, 'execute_query',
                            lambda sql, params=None, **k: seen.append(sql) or pd.DataFrame())
        CentralQueries.get_scheduler_jobs_for_export(database_id=1, status_filter='QUEUED')
        assert 'h.subpartition_name' in seen[0]

    def test_subpartition_job_exports_as_move_subpartition(self):
        # shaped like get_scheduler_jobs_for_export (upper-case columns, lower-cased by the page)
        df = pd.DataFrame([{
            'DATABASE_NAME': 'PROD', 'DATABASE_DISPLAY': 'Prod', 'DATABASE_ID': 1,
            'OWNER': 'APP', 'OBJECT_NAME': 'ORDERS', 'OBJECT_TYPE': 'SUBPARTITION',
            'PARTITION_NAME': 'P2024', 'SUBPARTITION_NAME': 'P2024_SP1',
            'COMPRESSION_TYPE_APPLIED': 'QUERY HIGH', 'PARALLEL_DEGREE': 4,
            'OPERATION_STATUS': 'QUEUED', 'START_TIME': '2026-09-01 08:00:00',
            'ERROR_MESSAGE': None,
        }])
        df.columns = [c.lower() for c in df.columns]
        script = build_compression_script(df, 'All', 'Prod', {}, targets=_targets(V19))
        assert ('ALTER TABLE APP.ORDERS MOVE SUBPARTITION P2024_SP1 COMPRESS FOR QUERY HIGH '
                'ONLINE PARALLEL 4;') in script
        assert 'MOVE PARTITION' not in script
        assert '-- APP.ORDERS.P2024.P2024_SP1 [QUEUED]' in script
