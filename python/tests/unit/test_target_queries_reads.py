"""
Unit tests for the TargetQueries read paths, driven against fake target and
central connectors (tests/unit/db_fakes.py):

- schema discovery, table introspection and session monitoring: binds match
  the placeholders, names are upper-cased, rows post-processed, errors return
  the documented fallback;
- the analysis helpers (table / partition / subpartition discovery, batch
  statistics, hotness sources incl. AWR, DBMS_COMPRESSION ratio with its CTAS
  fallback, compression choice, rationale);
- quick_scan and start_analysis end to end: every statement they run on the
  target and the central database (MERGE of each result row, run bookkeeping)
  is bind-checked;
- pulling results from a target, recurring stats jobs, the CSV-import
  existence check.

Every test fails at teardown if a statement's binds did not match its
placeholders (python-oracledb rejects unused and missing binds). Execution,
rollback and the scheduler queue are covered by their own modules.
"""
from datetime import datetime
from unittest.mock import MagicMock

import pandas as pd
import pytest

from hcc_advisor.utils import target_queries as tq
from hcc_advisor.utils.central_queries import CentralQueries
from hcc_advisor.utils.target_queries import TargetQueries

from tests.unit.db_fakes import SqlRouter, df, install_central, install_target

DB = 5


@pytest.fixture
def dbs(monkeypatch):
    """(target, central) routers; the registry knows target DB (Exadata)."""
    target = install_target(monkeypatch, SqlRouter('target'))
    central = install_central(monkeypatch, SqlRouter('central'))
    target.info = {'database_id': DB, 'username': 'ADVISOR', 'platform_type': 'EXADATA'}
    monkeypatch.setattr(CentralQueries, 'get_target_database',
                        staticmethod(lambda database_id: dict(target.info) if target.info else {}))
    target.st = MagicMock(name='st')
    monkeypatch.setattr(tq, 'st', target.st)
    yield target, central
    errors = target.bind_errors + central.bind_errors
    assert not errors, "\n\n".join(errors)


@pytest.fixture
def target(dbs):
    return dbs[0]


# ============================================================================
# Small reads
# ============================================================================

@pytest.mark.unit
class TestCpuCountAndFlush:

    @pytest.mark.parametrize('result, expected', [
        (df([{'VALUE': '16'}]), 16),
        (pd.DataFrame(), 8),
        (RuntimeError('ORA-00942'), 8),
    ])
    def test_cpu_count(self, target, result, expected):
        target.on('cpu_count', result=result)
        assert TargetQueries.get_cpu_count(DB) == expected

    def test_flush_runs_on_a_pooled_connection(self, target):
        assert TargetQueries._safe_flush_monitoring_info(DB) is True
        assert target.one('flush_database_monitoring_info').kind == 'cursor'
        target.pool.release.assert_called_once()

    @pytest.mark.parametrize('error', ['ORA-20000: insufficient privileges',
                                       'ORA-01031: insufficient privileges',
                                       'ORA-03113: end-of-file on communication channel'])
    def test_flush_failure_is_not_fatal(self, target, error):
        target.on('flush_database_monitoring_info', result=RuntimeError(error))
        assert TargetQueries._safe_flush_monitoring_info(DB) is False

    def test_flush_skipped_for_an_unknown_target(self, target):
        target.info = None
        assert TargetQueries._safe_flush_monitoring_info(DB) is False
        assert target.calls == []


@pytest.mark.unit
class TestSchemaDiscovery:

    def test_available_schemas(self, target):
        # DBA_TABLES, like the scans and "Check Schema Size": ALL_TABLES would
        # hide every schema the advisor account holds no object privilege on
        target.on('from dba_tables', result=df([{'OWNER': 'APP'}, {'OWNER': 'HR'}]))
        assert TargetQueries.get_available_schemas(DB) == ['APP', 'HR']
        sql = target.one('from dba_tables').sql
        assert tq.excluded_schemas_sql('owner') in sql
        assert 'oracle_maintained' not in sql.lower() and not target.find('from all_tables')

    def test_schemas_fall_back_to_all_tables(self, target):
        target.on('from dba_tables', result=RuntimeError('ORA-00942'))
        target.on('from all_tables', result=df([{'OWNER': 'APP'}]))
        assert TargetQueries.get_available_schemas(DB) == ['APP']
        target.st.error.assert_not_called()

    def test_no_schemas(self, target):
        assert TargetQueries.get_available_schemas(DB) == []

    def test_schema_error_banner(self, target):
        target.on('from dba_tables', result=RuntimeError('ORA-00942'))
        target.on('from all_tables', result=RuntimeError('ORA-01017'))
        assert TargetQueries.get_available_schemas(DB) == []
        assert 'ORA-01017' in target.st.error.call_args.args[0]

    def test_exclusions_match_check_schema_size(self, target):
        # Every page leaves out the same schemas, protected ones included
        sql = tq.excluded_schemas_sql('t.owner')
        for owner in tq._PROTECTED_SCHEMAS | {'SYSMAN', 'GSMUSER', 'APEX_040000'}:
            assert f"'{owner}'" in sql
        assert "t.owner NOT LIKE 'APEX_%'" in sql and "t.owner NOT LIKE 'FLOWS_%'" in sql
        assert "'HR'" not in sql and "'ORACLE%'" not in sql

    def test_tables_for_schema(self, target):
        target.on('from all_tables', result=df([{'TABLE_NAME': 'T'}]))
        assert list(TargetQueries.get_tables_for_schema(DB, 'app')['TABLE_NAME']) == ['T']
        assert target.last.params == {'owner': 'APP'}
        target.on('from all_tables', result=RuntimeError('x'))
        assert TargetQueries.get_tables_for_schema(DB, 'app').empty
        target.st.error.assert_called_once()


@pytest.mark.unit
class TestTableIntrospection:

    @pytest.mark.parametrize('fn, needle', [
        (TargetQueries.get_column_statistics, 'all_tab_col_statistics'),
        (TargetQueries.get_table_column_info, 'all_tab_columns'),
    ])
    def test_column_reads(self, target, fn, needle):
        target.on(needle, result=df([{'COLUMN_NAME': 'ID'}]))
        assert list(fn(DB, 'app', 'orders')['COLUMN_NAME']) == ['ID']
        assert target.last.params == {'owner': 'APP', 'table_name': 'ORDERS'}
        target.on(needle, result=RuntimeError('x'))
        assert fn(DB, 'app', 'orders').empty
        target.st.error.assert_called_once()

    def test_column_statistics_orders_by_columns_of_the_view(self, target):
        # ALL_TAB_COL_STATISTICS has no COLUMN_ID (ORA-00904 on every call)
        TargetQueries.get_column_statistics(DB, 'APP', 'ORDERS')
        assert 'column_id' not in target.last.sql.lower()

    def test_table_tablespace(self, target):
        target.on('tablespace_name', result=df([{'TABLESPACE_NAME': 'USERS'}]))
        assert TargetQueries.get_table_tablespace(DB, 'app', 't') == 'USERS'
        target.on('tablespace_name', result=pd.DataFrame())
        assert TargetQueries.get_table_tablespace(DB, 'app', 't') is None
        target.on('tablespace_name', result=RuntimeError('x'))
        assert TargetQueries.get_table_tablespace(DB, 'app', 't') is None

    def test_segment_info(self, target):
        target.on('from dba_segments', result=df([{'SEGMENT_NAME': 'T', 'BYTES': 8192}]))
        assert TargetQueries.get_segment_info(DB, 'app', 't') == {'SEGMENT_NAME': 'T', 'BYTES': 8192}
        assert target.last.params == {'owner': 'APP', 'segment_name': 'T'}
        target.on('from dba_segments', result=pd.DataFrame())
        assert TargetQueries.get_segment_info(DB, 'app', 't') == {}
        target.on('from dba_segments', result=RuntimeError('x'))
        assert TargetQueries.get_segment_info(DB, 'app', 't') == {}
        target.st.warning.assert_called_once()

    def test_table_activity(self, target):
        target.on('all_tab_modifications', result=df([{'INSERTS': 3}]))
        assert TargetQueries.get_table_activity(DB, 'app', 't') == {'INSERTS': 3}
        target.on('all_tab_modifications', result=RuntimeError('x'))
        assert TargetQueries.get_table_activity(DB, 'app', 't') == {}

    def test_compare_strategies_uses_stored_analysis(self, target):
        target.on('t_compression_analysis', result=df([{'STRATEGY': 'OLTP'}]))
        assert list(TargetQueries.compare_strategies(DB, 'app', 't')['STRATEGY']) == ['OLTP']
        assert not target.find('from all_tables')

    def test_compare_strategies_estimates_from_table_size(self, target):
        target.on('from all_tables', result=df([{'NUM_ROWS': 1000, 'BLOCKS': 128, 'SIZE_MB': 100.0}]))
        out = TargetQueries.compare_strategies(DB, 'app', 't')
        assert list(out['strategy']) == ['QUERY LOW', 'QUERY HIGH', 'ARCHIVE LOW', 'ARCHIVE HIGH']
        assert out.iloc[1]['estimated_size_mb'] == pytest.approx(40.0)
        assert set(out['row_count']) == {1000}

    def test_compare_strategies_missing_analysis_table_falls_back_quietly(self, target):
        import oracledb
        target.on('t_compression_analysis',
                  result=oracledb.DatabaseError('ORA-00942: table or view does not exist'))
        target.on('from all_tables', result=df([{'NUM_ROWS': 10, 'BLOCKS': 8, 'SIZE_MB': 1.0}]))
        assert len(TargetQueries.compare_strategies(DB, 'app', 't')) == 4
        assert target.swallowed == []       # no "query error" banner before the estimate

    def test_compare_strategies_nothing_known(self, target):
        target.on('t_compression_analysis', result=RuntimeError('ORA-00942'))
        assert TargetQueries.compare_strategies(DB, 'app', 't').empty
        target.on('from all_tables', result=RuntimeError('x'))
        assert TargetQueries.compare_strategies(DB, 'app', 't').empty


@pytest.mark.unit
class TestSessionMonitoring:

    def test_longops_compression_filter(self, target):
        TargetQueries.get_session_longops(DB)
        assert '%COMPRESS%' in target.last.sql
        TargetQueries.get_session_longops(DB, filter_compression=False)
        assert '%COMPRESS%' not in target.last.sql and 'sofar < totalwork' in target.last.sql

    @pytest.mark.parametrize('fn', [
        lambda: TargetQueries.get_session_longops(DB),
        lambda: TargetQueries.get_compression_sessions(DB),
        lambda: TargetQueries.get_all_active_longops(DB),
        lambda: TargetQueries.get_long_operations(DB),
        lambda: TargetQueries.get_running_compression_jobs(DB),
        lambda: TargetQueries.get_recurring_scan_jobs(DB),
    ])
    def test_monitor_reads_pass_rows_and_swallow_errors(self, target, fn):
        target.on('select', result=df([{'SID': 1}]))
        assert list(fn()['SID']) == [1]
        target.on('select', result=RuntimeError('ORA-00942'))
        assert fn().empty

    def test_session_sql(self, target):
        target.on('sql_fulltext', result=df([{'SQL_FULLTEXT': 'ALTER TABLE ...'}]))
        assert TargetQueries.get_session_sql(DB, 'abc') == 'ALTER TABLE ...'
        assert target.last.params == {'sql_id': 'abc'}
        target.on('sql_fulltext', result=RuntimeError('x'))
        assert TargetQueries.get_session_sql(DB, 'abc') == ''

    def test_running_total_dop(self, dbs):
        _, central = dbs
        central.on('total_dop', result=df([{'TOTAL_DOP': 12}]))
        assert TargetQueries.get_running_total_dop(DB) == 12
        assert central.last.params == {'db': DB}
        central.on('total_dop', result=RuntimeError('x'))
        assert TargetQueries.get_running_total_dop(DB) == 0


# ============================================================================
# Pulling results from a target that runs the advisor package itself
# ============================================================================

@pytest.mark.unit
class TestPullFromTarget:

    def test_results_of_the_latest_run(self, target):
        target.on('max(run_id)', result=df([{'RUN_ID': 12}]))
        target.on('advisor_run_id = :run_id', result=df([{'ANALYSIS_ID': 1}]))
        assert len(TargetQueries.pull_analysis_results(DB)) == 1
        assert target.last.params == {'run_id': 12}

    def test_no_runs_on_the_target(self, target):
        target.on('max(run_id)', result=df([{'RUN_ID': None}]))
        assert TargetQueries.pull_analysis_results(DB).empty
        target.on('max(run_id)', result=RuntimeError('ORA-00942'))
        assert TargetQueries.pull_analysis_results(DB).empty
        assert not target.find('advisor_run_id = :run_id')

    def test_results_of_a_given_run(self, target):
        TargetQueries.pull_analysis_results(DB, run_id=3)
        assert [c.params for c in target.calls] == [{'run_id': 3}]
        target.on('advisor_run_id = :run_id', result=RuntimeError('x'))
        assert TargetQueries.pull_analysis_results(DB, run_id=3).empty
        target.st.error.assert_called_once()

    def test_advisor_run(self, target):
        target.on('from t_advisor_run r', result=df([{
            'RUN_ID': 3, 'STATUS': 'COMPLETED', 'TABLES_ANALYZED': 7, 'OBJECTS_SKIPPED': None,
            'CANDIDATES_FOUND': 2, 'DURATION_MINUTES': 1.5, 'TOTAL_SIZE_MB': None}]))
        out = TargetQueries.pull_advisor_run(DB, run_id=3)
        assert target.last.params == {'run_id': 3}
        assert out['run_id'] == 3 and out['tables_analyzed'] == 7
        assert out['objects_skipped'] == 0 and out['total_size_mb'] == 0.0
        assert out['duration_minutes'] == 1.5

    def test_latest_advisor_run_has_no_binds(self, target):
        assert TargetQueries.pull_advisor_run(DB) == {}
        assert target.last.params == {} and 'max(run_id)' in target.last.sql.lower()
        target.on('from t_advisor_run r', result=RuntimeError('x'))
        assert TargetQueries.pull_advisor_run(DB) == {}


# ============================================================================
# Analysis helpers
# ============================================================================

def _table_row(owner='APP', name='ORDERS', partitioned='NO', size_mb=64.0, **kw):
    row = {'OWNER': owner, 'TABLE_NAME': name, 'NUM_ROWS': 1000, 'BLOCKS': 800,
           'AVG_ROW_LEN': 120, 'LAST_ANALYZED': datetime(2026, 9, 1), 'STATS_AGE_DAYS': 20.0,
           'PARTITIONED': partitioned, 'COMPRESSION': 'DISABLED', 'COMPRESS_FOR': None,
           'SIZE_BYTES': int(size_mb * 1048576), 'SIZE_MB': size_mb}
    row.update(kw)
    return row


def _partition_row(name, composite='NO', stats_age=None):
    return {'PARTITION_NAME': name, 'COMPOSITE': composite, 'COMPRESSION': 'DISABLED',
            'COMPRESS_FOR': None, 'NUM_ROWS': 500, 'BLOCKS': 400,
            'LAST_ANALYZED': None if stats_age is None else datetime(2026, 9, 10),
            'STATS_AGE_DAYS': stats_age, 'SIZE_BYTES': 32 * 1048576, 'SIZE_MB': 32.0}


def _subpartition_row(name):
    return {'SUBPARTITION_NAME': name, 'COMPRESSION': 'ENABLED', 'COMPRESS_FOR': 'ADVANCED',
            'NUM_ROWS': 100, 'BLOCKS': 80, 'LAST_ANALYZED': datetime(2026, 9, 12),
            'STATS_AGE_DAYS': 8.0, 'SIZE_BYTES': 8 * 1048576, 'SIZE_MB': 8.0}


@pytest.mark.unit
class TestDiscovery:

    def test_tables_with_and_without_owner(self, target):
        target.on('avg_row_len', result=df([_table_row(NUM_ROWS=None)]))
        tables = TargetQueries._discover_analysis_tables(DB, 'app')
        assert target.last.params == {'owner': 'APP'}
        assert tables[0]['owner'] == 'APP' and tables[0]['num_rows'] == 0   # NULL -> 0
        assert tables[0]['size_bytes'] == 64 * 1048576 and tables[0]['partitioned'] == 'NO'
        TargetQueries._discover_analysis_tables(DB)
        assert target.last.params == {}

    def test_tables_read_from_dba_views(self, target):
        target.on('avg_row_len', result=df([_table_row()]))
        TargetQueries._discover_analysis_tables(DB, 'app')
        sql = target.one('avg_row_len').sql.lower()
        assert 'from dba_tables t' in sql and 'from dba_tab_columns c' in sql
        assert 'all_tables' not in sql and 'all_tab_columns' not in sql
        assert tq.excluded_schemas_sql('t.owner').lower() in sql
        assert "nvl(t.dropped, 'no') = 'no'" in sql
        assert f'>= {tq.MIN_ANALYSIS_TABLE_BYTES}' in sql

    def test_tables_fall_back_to_all_views(self, target):
        target.on('avg_row_len', 'from dba_tables', result=RuntimeError('ORA-00942'))
        target.on('avg_row_len', 'from all_tables', result=df([_table_row()]))
        tables = TargetQueries._discover_analysis_tables(DB, 'app')
        assert [t['table_name'] for t in tables] == [_table_row()['TABLE_NAME']]
        assert 'from all_tab_columns c' in target.last.sql.lower()
        assert target.last.params == {'owner': 'APP'}

    @pytest.mark.parametrize('result', [pd.DataFrame(), RuntimeError('x')])
    def test_no_tables(self, target, result):
        target.on('avg_row_len', result=result)
        assert TargetQueries._discover_analysis_tables(DB) == []

    def test_partitions(self, target):
        target.on('from dba_tab_partitions p', result=df([_partition_row('P1'),
                                                          _partition_row('P2', 'YES', 3.0)]))
        parts = TargetQueries._discover_partitions(DB, 'APP', 'ORDERS')
        assert target.last.params == {'owner': 'APP', 'table_name': 'ORDERS'}
        assert [p['partition_name'] for p in parts] == ['P1', 'P2']
        assert parts[1]['composite'] == 'YES' and parts[0]['size_bytes'] == 32 * 1048576

    def test_subpartitions(self, target):
        target.on('from dba_tab_subpartitions sp', result=df([_subpartition_row('SP1')]))
        subs = TargetQueries._discover_subpartitions(DB, 'APP', 'ORDERS', 'P2')
        assert target.last.params == {'owner': 'APP', 'table_name': 'ORDERS', 'partition_name': 'P2'}
        assert subs[0]['subpartition_name'] == 'SP1' and subs[0]['compress_for'] == 'ADVANCED'

    @pytest.mark.parametrize('result', [pd.DataFrame(), RuntimeError('x')])
    def test_no_partitions(self, target, result):
        target.on('dba_tab_partitions', result=result)
        target.on('dba_tab_subpartitions', result=result)
        assert TargetQueries._discover_partitions(DB, 'A', 'T') == []
        assert TargetQueries._discover_subpartitions(DB, 'A', 'T', 'P') == []


@pytest.mark.unit
class TestStatsAndHotnessSources:

    def test_batch_table_stats(self, target):
        target.on('dba_tab_col_statistics', result=df([
            {'OWNER': 'APP', 'TABLE_NAME': 'T', 'NUM_COLUMNS': 4, 'AVG_NULL_PCT': 0.25,
             'AVG_DISTINCT': None}]))
        assert TargetQueries._get_batch_table_stats(DB, 'app') == {
            'APP.T': {'num_columns': 4, 'avg_null_pct': 0.25, 'avg_distinct': 0.0}}
        assert target.last.params == {'owner': 'APP'}
        assert 'join dba_tables t' in target.last.sql.lower()
        target.on('dba_tab_col_statistics', result=RuntimeError('x'))
        target.on('all_tab_col_statistics', result=RuntimeError('x'))
        assert TargetQueries._get_batch_table_stats(DB) == {}

    def test_dml_counters_fall_back_to_all_tab_modifications(self, target):
        target.on('from dba_tab_modifications', result=RuntimeError('ORA-00942'))
        target.on('from all_tab_modifications', result=df([
            {'TABLE_OWNER': 'APP', 'TABLE_NAME': 'T', 'PARTITION_NAME': None,
             'SUBPARTITION_NAME': None, 'INSERTS': 5, 'UPDATES': 0, 'DELETES': 1}]))
        index = TargetQueries._get_batch_dml_stats(DB, 'app')
        assert index is not None and len(index) == 1
        assert [c.sql.split('FROM ')[1].split()[0] for c in target.calls] == [
            'dba_tab_modifications', 'all_tab_modifications']

    def test_no_dml_source(self, target):
        target.on('tab_modifications', result=RuntimeError('ORA-01031'))
        assert TargetQueries._get_batch_dml_stats(DB) is None

    def test_segment_statistics(self, target):
        target.on('v$instance', result=df([{'UPTIME_DAYS': 4.0}]))
        target.on('v$segment_statistics', result=df([
            {'OWNER': 'APP', 'OBJECT_NAME': 'T', 'SUBOBJECT_NAME': None, 'LOGICAL_READS': 100,
             'PHYSICAL_READS': 1, 'BLOCK_CHANGES': 7}]))
        out = TargetQueries._get_segment_activity(DB, 'app')
        assert out['window_days'] == 4.0 and out['objects']
        assert target.last.params == {'owner': 'APP'}

    def test_segment_statistics_not_readable(self, target):
        target.on('v$instance', result=RuntimeError('ORA-00942'))
        assert TargetQueries._get_segment_activity(DB) is None

    def test_quiet_query_needs_a_registered_target(self, target):
        target.info = None
        with pytest.raises(ValueError, match='not found'):
            TargetQueries._query_target_quiet(DB, 'SELECT 1 FROM dual')

    def test_awr_window_and_segments(self, target):
        target.on('dba_hist_snapshot', result=df([{'WINDOW_DAYS': 6.5}]))
        target.on('dba_hist_seg_stat', result=df([
            {'OWNER': 'APP', 'OBJECT_NAME': 'T', 'SUBOBJECT_NAME': 'P1', 'LOGICAL_READS': 10,
             'PHYSICAL_READS': 2, 'BLOCK_CHANGES': 3}]))
        out = TargetQueries.get_awr_segment_stats(DB, owner='app', lookback_days=7)
        assert out['window_days'] == 6.5 and out['objects']
        window, segs = target.calls
        assert window.params == {'days': 7}
        assert segs.params == {'days': 7, 'owner': 'APP'}

    @pytest.mark.parametrize('window', [df([{'WINDOW_DAYS': None}]), pd.DataFrame(),
                                        RuntimeError('ORA-13516')])
    def test_awr_unusable(self, target, window):
        target.on('dba_hist_snapshot', result=window)
        assert TargetQueries.get_awr_segment_stats(DB) is None
        assert not target.find('dba_hist_seg_stat s')

    def test_awr_used_only_when_acknowledged(self, dbs, monkeypatch):
        target, central = dbs
        awr = MagicMock(return_value=None)
        monkeypatch.setattr(TargetQueries, 'get_awr_segment_stats', awr)
        TargetQueries._collect_hotness_inputs(DB)
        awr.assert_not_called()
        central.on('awr_acknowledged', result=df([{'VALUE': 'y'}]))
        inputs = TargetQueries._collect_hotness_inputs(DB, 'APP')
        awr.assert_called_once_with(DB, 'APP')
        assert set(inputs) == {'dml', 'segments', 'awr'}

    def test_awr_flag_read_error_means_off(self, dbs):
        _, central = dbs
        central.on('awr_acknowledged', result=RuntimeError('x'))
        assert TargetQueries._awr_acknowledged() is False


@pytest.mark.unit
class TestCompressionChoice:

    def test_single_ratio(self, target):
        target.on('get_compression_ratio', result={'out_ratio': 3.25})
        assert TargetQueries._get_single_compression_ratio(DB, 'APP', 'T', 'QUERY HIGH', 'P1') == 3.25
        assert target.last.params == {'owner': 'APP', 'table_name': 'T', 'partition_name': 'P1',
                                      'comp_type': 8}

    def test_unknown_type_is_not_tested(self, target):
        assert TargetQueries._get_single_compression_ratio(DB, 'APP', 'T', 'NONE') == 1.0
        assert target.calls == []

    def test_failed_oltp_ratio_uses_the_ctas_sample(self, target):
        target.on('get_compression_ratio', result={'out_ratio': -1})
        target.on('tmp_cmp_unc', result={'basic_ratio': 1.8, 'oltp_ratio': 2.4})
        assert TargetQueries._get_single_compression_ratio(DB, 'APP', 'T', 'OLTP') == 2.4
        assert target.last.params == {'owner': 'APP', 'table_name': 'T', 'sample_rows': 5000}

    def test_failed_hcc_ratio_or_error_is_one(self, target):
        target.on('get_compression_ratio', result={'out_ratio': -1})
        assert TargetQueries._get_single_compression_ratio(DB, 'APP', 'T', 'ARCHIVE HIGH') == 1.0
        target.on('get_compression_ratio', result=RuntimeError('x'))
        assert TargetQueries._get_single_compression_ratio(DB, 'APP', 'T', 'OLTP') == 1.0

    @pytest.mark.parametrize('result, expected', [
        ({'basic_ratio': -1, 'oltp_ratio': -1}, {'basic': 1, 'oltp': 1}),   # connected as SYS
        ({'basic_ratio': None, 'oltp_ratio': None}, {'basic': 1, 'oltp': 1}),
        (RuntimeError('x'), {'basic': 1, 'oltp': 1}),
    ])
    def test_ctas_edge_cases(self, target, result, expected):
        target.on('tmp_cmp_unc', result=result)
        assert TargetQueries._get_compression_ratios_ctas(DB, 'APP', 'T') == expected

    @pytest.mark.parametrize('hotness, platform, expected', [
        (90, 'EXADATA', 'NONE'),
        (70, 'EXADATA', 'OLTP'),
        (50, 'EXADATA', 'QUERY LOW'),
        (30, 'EXADATA', 'QUERY HIGH'),
        (15, 'EXADATA', 'ARCHIVE LOW'),
        (5, 'EXADATA', 'ARCHIVE HIGH'),
        (5, 'STANDARD', 'OLTP'),      # HCC needs Exadata
    ])
    def test_hotness_bands(self, hotness, platform, expected):
        assert TargetQueries._determine_target_compression([], 'TABLE', hotness, {}, platform) == expected

    def test_stats_make_a_table_look_colder(self):
        stats = {'avg_null_pct': 0.6, 'avg_distinct': 5, 'num_rows': 10000, 'avg_row_len': 900}
        # 70 - 10 (NULLs) - 10 (low cardinality) - 5 (wide rows) = 45 -> QUERY LOW
        assert TargetQueries._determine_target_compression([], 'TABLE', 70, stats, 'EXADATA') == 'QUERY LOW'
        stats = {'avg_null_pct': 0.4, 'avg_distinct': 500, 'num_rows': 10000}
        # 70 - 5 - 5 = 60 -> QUERY LOW
        assert TargetQueries._determine_target_compression([], 'TABLE', 70, stats, 'EXADATA') == 'QUERY LOW'

    def test_rules_win_but_never_basic_and_no_hcc_off_exadata(self):
        rules = [{'object_type': 'TABLE', 'hotness_min': 0, 'hotness_max': 40,
                  'compression_type': 'BASIC'},
                 {'object_type': 'TABLE', 'hotness_min': 41, 'hotness_max': 100,
                  'compression_type': 'ARCHIVE HIGH'}]
        assert TargetQueries._determine_target_compression(rules, 'TABLE', 20, {}, 'EXADATA') == 'OLTP'
        assert TargetQueries._determine_target_compression(rules, 'TABLE', 60, {}, 'EXADATA') == 'ARCHIVE HIGH'
        assert TargetQueries._determine_target_compression(rules, 'TABLE', 60, {}, 'STANDARD') == 'OLTP'
        # a NONE rule falls through to the bands
        none_rule = [{'object_type': 'TABLE', 'hotness_min': 0, 'hotness_max': 100,
                      'compression_type': 'NONE'}]
        assert TargetQueries._determine_target_compression(none_rule, 'TABLE', 70, {}, 'EXADATA') == 'OLTP'

    def test_rationale_mentions_stats_ratios_and_choice(self):
        text = TargetQueries._generate_rationale(
            12.0, 80, {'oltp': 2.5, 'query_high': None}, 'OLTP',
            {'avg_null_pct': 0.4, 'avg_row_len': 600, 'num_rows': 1000, 'avg_distinct': 2})
        assert text.startswith('Size: 12.00 MB; Hotness: 80/100 (High DML)')
        assert 'High NULL density (40%)' in text and 'Wide rows (600B avg)' in text
        assert 'Low cardinality' in text and 'OLTP 2.50:1' in text
        assert text.endswith('OLTP compression (good ratio, optimized for DML)')
        assert TargetQueries._generate_rationale(1.0, 10, {}, 'X').endswith('Compression: X')


# ============================================================================
# Quick scan / full analysis end to end
# ============================================================================

def _scan_target(target):
    """One non-partitioned and one partitioned table (plain partition P1, composite
    partition P2 with subpartition SP1), every hotness source readable."""
    target.on('avg_row_len', result=df([
        _table_row('APP', 'CUSTOMERS'),
        _table_row('APP', 'ORDERS', partitioned='YES', COMPRESS_FOR='ADVANCED')]))
    parts = df([_partition_row('P1', stats_age=None), _partition_row('P2', 'YES', 2.0)])
    target.on('from dba_tab_partitions p', result=lambda sql, params: (
        parts if params['table_name'] == 'ORDERS' else pd.DataFrame()))
    target.on('from dba_tab_subpartitions sp', result=df([_subpartition_row('SP1')]))
    target.on('from dba_tab_modifications', result=df([
        {'TABLE_OWNER': 'APP', 'TABLE_NAME': 'ORDERS', 'PARTITION_NAME': 'P1',
         'SUBPARTITION_NAME': None, 'INSERTS': 50000, 'UPDATES': 20000, 'DELETES': 0}]))
    target.on('v$instance', result=df([{'UPTIME_DAYS': 10.0}]))
    target.on('v$segment_statistics', result=df([
        {'OWNER': 'APP', 'OBJECT_NAME': 'CUSTOMERS', 'SUBOBJECT_NAME': None,
         'LOGICAL_READS': 1000, 'PHYSICAL_READS': 10, 'BLOCK_CHANGES': 5}]))
    target.on('dba_tab_col_statistics', result=df([
        {'OWNER': 'APP', 'TABLE_NAME': 'CUSTOMERS', 'NUM_COLUMNS': 5, 'AVG_NULL_PCT': 0.1,
         'AVG_DISTINCT': 900}]))
    target.on('get_compression_ratio', result={'out_ratio': 4.0})


def _scan_central(central, run_id=77):
    central.on('from t_strategy_rules', result=df([
        {'OBJECT_TYPE': 'TABLE', 'COMPRESSION_TYPE': 'QUERY HIGH', 'HOTNESS_MIN': 0,
         'HOTNESS_MAX': 30}]))
    central.on('insert into t_advisor_run', result=run_id)


@pytest.mark.unit
class TestQuickScan:

    def test_scan_lists_leaf_segments_and_stores_them(self, dbs):
        target, central = dbs
        _scan_target(target)
        _scan_central(central)
        results = TargetQueries.quick_scan(DB, owner='APP')

        levels = [(r['OBJECT_NAME'], r['OBJECT_TYPE'], r['PARTITION_NAME'], r['SUBPARTITION_NAME'])
                  for r in results]
        assert levels == [('CUSTOMERS', 'TABLE', None, None), ('ORDERS', 'TABLE', None, None),
                          ('ORDERS', 'PARTITION', 'P1', None),
                          ('ORDERS', 'SUBPARTITION', 'P2', 'SP1')]
        by_name = {(r['OBJECT_NAME'], r['PARTITION_NAME']): r for r in results}
        assert by_name[('ORDERS', None)]['CURRENT_COMPRESSION'] == 'ADVANCED'
        assert by_name[('CUSTOMERS', None)]['CURRENT_COMPRESSION'] == 'NONE'
        assert all(r['PROJECTED_SAVINGS_BYTES'] == 0 for r in results)  # no DBMS_COMPRESSION
        assert not target.find('get_compression_ratio')

        # run record, one MERGE per result row, run closed as COMPLETED
        assert central.one('insert into t_advisor_run').params['analysis_mode'] == 'QUICK'
        merges = central.find('merge into t_compression_analysis', kind='executemany')
        assert len(merges) == 4 and {m.params['advisor_run_id'] for m in merges} == {77}
        close = central.one("run_status = 'COMPLETED'")
        assert close.params['run_id'] == 77 and close.params['analyzed'] == 4

    def test_scan_without_partitions(self, dbs):
        target, central = dbs
        _scan_target(target)
        _scan_central(central)
        results = TargetQueries.quick_scan(DB, include_partitions=False)
        assert [r['OBJECT_TYPE'] for r in results] == ['TABLE', 'TABLE']
        assert not target.find('dba_tab_partitions')
        assert central.one('insert into t_advisor_run').params['include_partitions'] == 'N'

    def test_nothing_to_scan(self, dbs):
        target, central = dbs
        assert TargetQueries.quick_scan(DB) == []
        assert not central.find('insert')

    def test_results_are_stored_even_without_a_run_record(self, dbs):
        target, central = dbs
        _scan_target(target)
        _scan_central(central, run_id=None)
        assert len(TargetQueries.quick_scan(DB, include_partitions=False)) == 2
        assert len(central.find('merge', kind='executemany')) == 2
        assert not central.find("run_status = 'COMPLETED'")


@pytest.mark.unit
class TestStartAnalysis:

    def test_full_analysis_with_partitions(self, dbs):
        target, central = dbs
        _scan_target(target)
        _scan_central(central)
        out = TargetQueries.start_analysis(DB, owner='APP', include_partitions=True)
        assert out['success'] is True and out['run_id'] == 77

        merges = [m.params for m in central.find('merge', kind='executemany')]
        assert [(m['object_name'], m['object_type']) for m in merges] == [
            ('CUSTOMERS', 'TABLE'), ('ORDERS', 'TABLE'), ('ORDERS', 'PARTITION'),
            ('ORDERS', 'SUBPARTITION')]
        # one DBMS_COMPRESSION call per advised segment, with the (sub)partition name
        ratio_calls = target.find('get_compression_ratio')
        assert [c.params['partition_name'] for c in ratio_calls] == [None, None, 'P1', 'SP1']
        customers = merges[0]
        assert customers['projected_savings_pct'] == 75.0      # ratio 4 -> 75% saved
        close = central.one("run_status = 'COMPLETED'")
        assert close.params['succeeded'] == 4 and close.params['failed'] == 0

    def test_too_many_partitions_are_skipped(self, dbs, monkeypatch):
        target, central = dbs
        _scan_target(target)
        _scan_central(central)
        monkeypatch.setattr(TargetQueries, 'MAX_PARTITIONS_PER_TABLE', 1)
        TargetQueries.start_analysis(DB, include_partitions=True)
        types = [m.params['object_type'] for m in central.find('merge', kind='executemany')]
        assert types == ['TABLE', 'TABLE']

    def test_ratio_of_one_means_no_compression(self, dbs):
        target, central = dbs
        _scan_target(target)
        _scan_central(central)
        target.on('get_compression_ratio', result={'out_ratio': 1.0})
        TargetQueries.start_analysis(DB)
        advised = {m.params['advisable_compression'] for m in central.find('merge', kind='executemany')}
        assert advised == {'NONE'}

    def test_no_eligible_tables_closes_the_run(self, dbs):
        target, central = dbs
        _scan_central(central)
        out = TargetQueries.start_analysis(DB)
        assert out == {'success': True, 'run_id': 77,
                       'message': 'No eligible tables found for analysis'}
        assert central.one("run_status = 'COMPLETED'").params['analyzed'] == 0

    def test_run_record_failure(self, dbs):
        _, central = dbs
        central.on('insert into t_advisor_run', result=None)
        assert TargetQueries.start_analysis(DB) == {
            'success': False, 'run_id': None, 'message': 'Failed to create advisor run record'}


# ============================================================================
# Recurring stats jobs and the CSV-import existence check
# ============================================================================

@pytest.mark.unit
class TestRecurringJobs:

    @pytest.mark.parametrize('frequency, interval', [
        ('DAILY', 'FREQ=DAILY;'), ('MONTHLY', 'FREQ=MONTHLY;'), ('BOGUS', 'FREQ=WEEKLY;')])
    def test_create(self, target, frequency, interval):
        out = TargetQueries.create_recurring_scan_job(DB, frequency)
        assert out['success'] is True and out['job_name'].startswith('HCC_RECURRING_SCAN_')
        call = target.one('dbms_scheduler.create_job')
        assert interval in call.sql and out['job_name'] in call.sql

    @pytest.mark.parametrize('result, error', [(False, 'Job creation failed'),
                                               (RuntimeError('ORA-27477'), 'ORA-27477')])
    def test_create_failure(self, target, result, error):
        target.on('create_job', result=result)
        assert TargetQueries.create_recurring_scan_job(DB) == {'success': False, 'error': error}

    def test_drop(self, target):
        assert TargetQueries.drop_recurring_scan_job(DB, 'HCC_RECURRING_SCAN_123') is True
        assert "DROP_JOB('HCC_RECURRING_SCAN_123'" in target.last.sql
        target.on('drop_job', result=RuntimeError('x'))
        assert TargetQueries.drop_recurring_scan_job(DB, 'HCC_RECURRING_SCAN_123') is False


@pytest.mark.unit
class TestObjectsExistence:

    def test_each_level_is_looked_up_and_results_stay_aligned(self, target):
        target.on('from all_tables', result=df([
            {'OWNER': 'APP', 'TABLE_NAME': 'ORDERS', 'COMPRESSION': 'ENABLED',
             'COMPRESS_FOR': 'ADVANCED'}]))
        target.on('from dba_tab_partitions', result=df([
            {'TABLE_OWNER': 'APP', 'TABLE_NAME': 'SALES', 'PARTITION_NAME': 'P1',
             'COMPRESSION': 'DISABLED', 'COMPRESS_FOR': None}]))
        target.on('from dba_tab_subpartitions', result=df([
            {'TABLE_OWNER': 'APP', 'TABLE_NAME': 'SALES', 'SUBPARTITION_NAME': 'SP1',
             'COMPRESSION': 'ENABLED', 'COMPRESS_FOR': 'QUERY HIGH'}]))
        objects = [
            {'owner': 'APP', 'object_name': 'ORDERS'},
            {'owner': 'APP', 'table_name': 'SALES', 'partition_name': 'P1'},
            {'owner': 'APP', 'object_name': 'SALES', 'partition_name': 'P1',
             'subpartition_name': 'SP1'},
            {'owner': 'APP', 'object_name': 'GONE', 'partition_name': 'nan'},
            {'owner': "APP'; DROP", 'object_name': 'X'},       # invalid identifier
            {'owner': None, 'object_name': 'ORDERS'},
        ]
        out = TargetQueries.check_objects_existence(DB, objects)
        assert [(r['object_level'], r['exists']) for r in out] == [
            ('TABLE', True), ('PARTITION', True), ('SUBPARTITION', True), ('TABLE', False),
            ('TABLE', False), ('TABLE', False)]
        assert out[0]['current_compress_for'] == 'ADVANCED'
        assert out[2]['current_compress_for'] == 'QUERY HIGH'
        # identifiers are quoted literals, never binds; the invalid one is not sent
        assert all(c.params == {} for c in target.calls)
        assert not any('DROP' in c.sql for c in target.calls)

    def test_nothing_valid_runs_no_query(self, target):
        out = TargetQueries.check_objects_existence(DB, [{'owner': '', 'object_name': 'T'}])
        assert out == [{'exists': False, 'object_level': 'TABLE', 'current_compression': None,
                        'current_compress_for': None}]
        assert target.calls == []
