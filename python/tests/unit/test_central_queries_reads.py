"""
Unit tests for the CentralQueries read and bookkeeping functions, driven
against a fake CentralConnector (tests/unit/db_fakes.py):

- binds match the statement's placeholders exactly (python-oracledb rejects an
  unused or a missing bind), checked for every statement a test runs;
- the DATABASE_ID filter is applied when a database is given and left out
  (with its bind) when not;
- result post-processing (Oracle's upper-case columns to dict keys, NULL
  counts to 0, GB conversions, empty results to the documented defaults);
- error paths return the documented fallback (and show a banner where the
  function does), view-missing fallbacks run their direct query;
- strategy / rule CRUD, target-registry helpers and the analysis-result
  ingestion (store_advisor_run, store_analysis_results).

get_recommendations and get_savings_by_strategy are covered elsewhere and
left out here on purpose (their history join is being reworked).
"""
from unittest.mock import MagicMock

import numpy as np
import pandas as pd
import pytest

from hcc_advisor.utils import central_queries as cq_module
from hcc_advisor.utils.central_queries import CentralQueries
from hcc_advisor.utils.target_connector import TargetConnector

from tests.unit.db_fakes import SqlRouter, df, install_central, placeholders


@pytest.fixture
def central(monkeypatch):
    """CentralConnector routed through a SqlRouter; st mocked. Fails the test
    at teardown if any statement's binds did not match its placeholders."""
    router = install_central(monkeypatch, SqlRouter('central'))
    router.st = MagicMock(name='st')
    monkeypatch.setattr(cq_module, 'st', router.st)
    yield router
    assert not router.bind_errors, "\n\n".join(router.bind_errors)


def _errors(router):
    return [c.args[0] for c in router.st.error.call_args_list]


# ============================================================================
# The placeholder helper itself
# ============================================================================

class TestPlaceholderHelper:

    def test_ignores_literals_comments_and_assignments(self):
        sql = """
            SELECT TO_CHAR(d, 'YYYY-MM-DD HH24:MI:SS') AS "A:B", :x  -- :not_a_bind
            FROM t WHERE y = :Y_1 AND z = :x
            BEGIN :out := 1; END;
        """
        assert placeholders(sql) == {'x', 'y_1', 'out'}


# ============================================================================
# DATABASE_ID filter: applied when given, absent (bind and predicate) when not
# ============================================================================

READS = {
    'get_dashboard_summary': lambda d: CentralQueries.get_dashboard_summary(database_id=d),
    'get_scheduler_job_summary': lambda d: CentralQueries.get_scheduler_job_summary(database_id=d),
    'get_scheduler_jobs_for_export': lambda d: CentralQueries.get_scheduler_jobs_for_export(
        database_id=d, status_filter='FAILED'),
    'get_scheduler_job_details': lambda d: CentralQueries.get_scheduler_job_details(database_id=d),
    'get_savings_timeline': lambda d: CentralQueries.get_savings_timeline(database_id=d),
    'get_forecast_data': lambda d: CentralQueries.get_forecast_data(database_id=d),
    'get_growth_alerts': lambda d: CentralQueries.get_growth_alerts(database_id=d),
    'get_compression_progress': lambda d: CentralQueries.get_compression_progress(database_id=d),
    'get_recent_executions': lambda d: CentralQueries.get_recent_executions(database_id=d),
    'get_analysis_runs': lambda d: CentralQueries.get_analysis_runs(database_id=d),
    'get_latest_analysis': lambda d: CentralQueries.get_latest_analysis(database_id=d),
    'get_compression_candidates': lambda d: CentralQueries.get_compression_candidates(database_id=d),
    'get_hot_objects': lambda d: CentralQueries.get_hot_objects(database_id=d),
    'get_cold_objects': lambda d: CentralQueries.get_cold_objects(database_id=d),
    'get_execution_history': lambda d: CentralQueries.get_execution_history(database_id=d),
    'get_compression_effectiveness': lambda d: CentralQueries.get_compression_effectiveness(
        database_id=d),
    'get_index_compression_analysis': lambda d: CentralQueries.get_index_compression_analysis(
        database_id=d),
    'get_lob_compression_analysis': lambda d: CentralQueries.get_lob_compression_analysis(
        database_id=d),
    'get_running_operations': lambda d: CentralQueries.get_running_operations(database_id=d),
    'get_recent_operations': lambda d: CentralQueries.get_recent_operations(database_id=d),
}


@pytest.mark.unit
class TestDatabaseFilter:

    @pytest.mark.parametrize('name', sorted(READS))
    def test_filter_and_bind_when_a_database_is_given(self, central, name):
        READS[name](7)
        assert central.calls, name
        for call in central.calls:
            assert call.params.get('database_id') == 7, call
            assert 'database_id = :database_id' in call.sql, call

    @pytest.mark.parametrize('name', sorted(READS))
    def test_no_filter_and_no_bind_without_a_database(self, central, name):
        READS[name](None)
        assert central.calls, name
        for call in central.calls:
            assert 'database_id' not in call.params, call
            assert ':database_id' not in call.sql, call

    def test_filtered_forecast_duration_query_is_filtered_too(self, central):
        central.on('pending_count', result=df([{'PENDING_COUNT': 1}]))
        CentralQueries.get_forecast_data(database_id=3)
        assert len(central.calls) == 2
        assert all(c.params == {'database_id': 3} for c in central.calls)


# ============================================================================
# Dashboard / scheduler summaries
# ============================================================================

@pytest.mark.unit
class TestDashboardSummary:

    def test_row_is_converted_to_gb(self, central):
        central.on('total_tables', result=df([{
            'TOTAL_TABLES': 3, 'TOTAL_SIZE_MB': 2048, 'POTENTIAL_SAVINGS_MB': 1024,
            'AVG_SAVINGS_PCT': 42.5, 'CANDIDATES_COUNT': 2}]))
        assert CentralQueries.get_dashboard_summary() == {
            'total_tables': 3, 'total_size_gb': 2.0, 'potential_savings_gb': 1.0,
            'avg_savings_pct': 42.5, 'candidates_count': 2}

    def test_empty_result_gives_zeros(self, central):
        out = CentralQueries.get_dashboard_summary(database_id=1)
        assert out == {'total_tables': 0, 'total_size_gb': 0, 'potential_savings_gb': 0,
                       'avg_savings_pct': 0, 'candidates_count': 0}

    def test_error_gives_zeros_and_a_banner(self, central):
        central.on('total_tables', result=RuntimeError('boom'))
        assert CentralQueries.get_dashboard_summary()['total_tables'] == 0
        assert _errors(central) == ['Failed to get dashboard summary: boom']

    def test_summary_reads_leaf_segments_not_the_table(self, central):
        CentralQueries.get_dashboard_summary()
        assert 'leaf_n_children' in central.last.sql


@pytest.mark.unit
class TestSchedulerSummaries:

    def test_null_sums_count_as_zero(self, central):
        # SUM over no rows is NULL
        central.on('as queued', result=df([{'QUEUED': None, 'RUNNING': None, 'SUCCEEDED': None,
                                             'FAILED': None, 'TOTAL': 0}]))
        assert CentralQueries.get_scheduler_job_summary() == {
            'queued': 0, 'running': 0, 'succeeded': 0, 'failed': 0, 'total': 0}

    def test_counts(self, central):
        central.on('as queued', result=df([{'QUEUED': 2, 'RUNNING': 1, 'SUCCEEDED': 5,
                                             'FAILED': 1, 'TOTAL': 9}]))
        out = CentralQueries.get_scheduler_job_summary(database_id=4)
        assert out == {'queued': 2, 'running': 1, 'succeeded': 5, 'failed': 1, 'total': 9}

    def test_error_gives_zeros(self, central):
        central.on('as queued', result=RuntimeError('down'))
        assert CentralQueries.get_scheduler_job_summary()['total'] == 0

    def test_window_keeps_queued_and_running_rows_of_any_age(self, central):
        CentralQueries.get_scheduler_job_summary()
        assert "operation_status IN ('QUEUED', 'IN_PROGRESS')" in central.last.sql

    @pytest.mark.parametrize('status, bound', [(None, False), ('All', False), ('QUEUED', True)])
    def test_export_status_filter(self, central, status, bound):
        CentralQueries.get_scheduler_jobs_for_export(status_filter=status)
        call = central.last
        assert ('status' in call.params) is bound
        if bound:
            assert call.params['status'] == 'QUEUED'
        # the export carries the subpartition name (MOVE SUBPARTITION)
        assert 'h.subpartition_name' in call.sql

    def test_export_error_gives_empty_frame(self, central):
        central.on('t_compression_history', result=RuntimeError('x'))
        assert CentralQueries.get_scheduler_jobs_for_export().empty

    def test_details_name_the_database_only_across_databases(self, central):
        CentralQueries.get_scheduler_job_details()
        assert 'join t_target_databases' in central.last.sql.lower()
        CentralQueries.get_scheduler_job_details(database_id=2)
        assert 't_target_databases' not in central.last.sql.lower()

    def test_details_error_gives_empty_frame(self, central):
        central.on('t_compression_history', result=RuntimeError('x'))
        assert CentralQueries.get_scheduler_job_details(database_id=1).empty

    def test_timeline_error_gives_empty_frame(self, central):
        central.on('t_compression_history', result=RuntimeError('x'))
        assert CentralQueries.get_savings_timeline().empty


@pytest.mark.unit
class TestForecastAndProgress:

    def test_forecast_uses_the_average_duration(self, central):
        central.on('pending_count', result=df([{
            'PENDING_COUNT': 4, 'PENDING_CURRENT_MB': 100.0, 'PENDING_PROJECTED_MB': 40.0,
            'PENDING_SAVINGS_MB': 60.0}]))
        central.on('avg_sec', result=df([{'AVG_SEC': 120}]))
        assert CentralQueries.get_forecast_data() == {
            'pending_count': 4, 'pending_current_mb': 100.0, 'pending_projected_mb': 40.0,
            'pending_savings_mb': 60.0, 'avg_duration_sec': 120}

    def test_forecast_without_history_defaults_to_five_minutes(self, central):
        central.on('pending_count', result=df([{
            'PENDING_COUNT': 0, 'PENDING_CURRENT_MB': None, 'PENDING_PROJECTED_MB': None,
            'PENDING_SAVINGS_MB': None}]))
        central.on('avg_sec', result=df([{'AVG_SEC': None}]))
        out = CentralQueries.get_forecast_data()
        assert out['avg_duration_sec'] == 300
        assert out['pending_current_mb'] == 0.0

    def test_forecast_error_gives_defaults(self, central):
        central.on('pending_count', result=RuntimeError('x'))
        assert CentralQueries.get_forecast_data() == {
            'pending_count': 0, 'pending_current_mb': 0, 'pending_projected_mb': 0,
            'pending_savings_mb': 0, 'avg_duration_sec': 300}

    def test_growth_alert_threshold_is_bound(self, central):
        CentralQueries.get_growth_alerts(threshold_pct=35.0)
        assert central.last.params == {'threshold': 35.0}

    def test_growth_alert_error_gives_empty_frame(self, central):
        central.on('compressed_size_bytes', result=RuntimeError('x'))
        assert CentralQueries.get_growth_alerts().empty

    def test_progress_row(self, central):
        central.on('as skipped', result=df([{
            'TOTAL': 10, 'SKIPPED': 2, 'COMPRESSED': 3, 'PENDING': 5, 'SAVED_MB': 12.5,
            'PENDING_SAVINGS_MB': 40.0, 'COMPRESSED_ORIGINAL_MB': 30.0, 'UNCOMPRESSED_MB': 80.0}]))
        assert CentralQueries.get_compression_progress(database_id=1) == {
            'total': 10, 'compressed': 3, 'pending': 5, 'skipped': 2, 'saved_mb': 12.5,
            'pending_savings_mb': 40.0, 'compressed_original_mb': 30.0, 'uncompressed_mb': 80.0}

    @pytest.mark.parametrize('result', [pd.DataFrame(), RuntimeError('x')])
    def test_progress_empty_or_error_gives_zeros(self, central, result):
        central.on('as skipped', result=result)
        out = CentralQueries.get_compression_progress()
        assert out['total'] == 0 and out['saved_mb'] == 0 and len(out) == 8


# ============================================================================
# Executions, analysis runs and results
# ============================================================================

@pytest.mark.unit
class TestRunsAndResults:

    def test_recent_executions_limit(self, central):
        CentralQueries.get_recent_executions(limit=3)
        assert central.last.params == {'limit': 3}

    def test_analysis_runs_limit(self, central):
        CentralQueries.get_analysis_runs(limit=12, database_id=2)
        assert central.last.params == {'limit': 12, 'database_id': 2}

    @pytest.mark.parametrize('fn', [CentralQueries.get_recent_executions,
                                    CentralQueries.get_analysis_runs])
    def test_list_error_gives_empty_frame_and_banner(self, central, fn):
        central.on('select', result=RuntimeError('ORA-00942'))
        assert fn().empty
        assert _errors(central) and 'ORA-00942' in _errors(central)[0]

    def test_latest_analysis_row(self, central):
        central.on('as analysis_id', result=df([{
            'ANALYSIS_ID': 9, 'DATABASE_ID': 1, 'STARTED_AT': 's', 'COMPLETED_AT': None,
            'STATUS': 'COMPLETED', 'TABLES_ANALYZED': None, 'CANDIDATES_FOUND': 4,
            'DURATION_SECONDS': 90.0, 'TOTAL_CURRENT_SIZE_GB': 2.5,
            'TOTAL_COMPRESSED_SIZE_GB': None, 'AVG_SAVINGS_PCT': 33.3}]))
        out = CentralQueries.get_latest_analysis(database_id=1)
        assert out['analysis_id'] == 9 and out['status'] == 'COMPLETED'
        assert out['tables_analyzed'] == 0          # NULL count
        assert out['candidates_found'] == 4 and out['duration_seconds'] == 90
        assert out['total_compressed_size_gb'] == 0.0 and out['min_size_mb'] == 0

    def test_latest_analysis_picks_the_filtered_max_run(self, central):
        CentralQueries.get_latest_analysis(database_id=5)
        # both the outer query and the MAX(run_id) subquery are scoped
        assert central.last.sql.count('database_id = :database_id') == 2

    def test_latest_analysis_empty_or_error(self, central):
        assert CentralQueries.get_latest_analysis() == {}
        central.on('as analysis_id', result=RuntimeError('x'))
        assert CentralQueries.get_latest_analysis() == {}
        assert _errors(central) == ['Failed to get latest analysis: x']

    def test_analysis_results_by_run(self, central):
        central.on('advisor_run_id = :run_id', result=df([{'ANALYSIS_ID': 1}]))
        assert len(CentralQueries.get_analysis_results(42)) == 1
        assert central.last.params == {'run_id': 42}

    def test_analysis_results_error(self, central):
        central.on('advisor_run_id = :run_id', result=RuntimeError('x'))
        assert CentralQueries.get_analysis_results(42).empty
        assert _errors(central)

    def test_analysis_details(self, central):
        central.on('analysis_id = :analysis_id', result=df([{'ANALYSIS_ID': 5, 'OWNER': 'APP'}]))
        assert CentralQueries.get_analysis_details(5) == {'ANALYSIS_ID': 5, 'OWNER': 'APP'}
        central.on('analysis_id = :analysis_id', result=pd.DataFrame())
        assert CentralQueries.get_analysis_details(6) == {}
        central.on('analysis_id = :analysis_id', result=RuntimeError('x'))
        assert CentralQueries.get_analysis_details(7) == {}

    def test_execution_history_binds_every_filter(self, central):
        CentralQueries.get_execution_history(start_date='2026-01-01', end_date='2026-02-01',
                                             status='FAILED', limit=5, database_id=3)
        assert central.last.params == {'start_date': '2026-01-01', 'end_date': '2026-02-01',
                                       'status': 'FAILED', 'limit': 5, 'database_id': 3}
        assert 'subpartition_name' in central.last.sql

    def test_execution_history_error(self, central):
        central.on('t_compression_history', result=RuntimeError('x'))
        assert CentralQueries.get_execution_history().empty
        assert _errors(central) == ['Failed to get execution history: x']

    def test_execution_status(self, central):
        central.on('history_id = :history_id', result=df([{'EXECUTION_ID': 3, 'STATUS': 'SUCCESS'}]))
        assert CentralQueries.get_execution_status(3) == {'EXECUTION_ID': 3, 'STATUS': 'SUCCESS'}
        central.on('history_id = :history_id', result=pd.DataFrame())
        assert CentralQueries.get_execution_status(4) == {}
        central.on('history_id = :history_id', result=RuntimeError('x'))
        assert CentralQueries.get_execution_status(5) == {}


# ============================================================================
# View-backed reads fall back to a direct query when the view is missing
# ============================================================================

@pytest.mark.unit
class TestViewFallbacks:

    def test_candidates_fall_back_to_recommendations(self, central, monkeypatch):
        recs = MagicMock(return_value=df([{'TABLE_NAME': 'T'}]))
        monkeypatch.setattr(CentralQueries, 'get_recommendations', recs)
        central.on('v_compression_candidates', result=RuntimeError('ORA-00942'))
        out = CentralQueries.get_compression_candidates(database_id=4)
        recs.assert_called_once_with(database_id=4)
        assert list(out['TABLE_NAME']) == ['T']

    @pytest.mark.parametrize('fn, view, predicate', [
        (CentralQueries.get_hot_objects, 'v_hot_objects', 'hotness_score >= 50'),
        (CentralQueries.get_cold_objects, 'v_cold_objects', 'hotness_score < 50'),
        (CentralQueries.get_compression_effectiveness, 'v_compression_effectiveness',
         "operation_status = 'SUCCESS'"),
    ])
    @pytest.mark.parametrize('database_id', [None, 8])
    def test_missing_view_runs_the_direct_query(self, central, fn, view, predicate, database_id):
        central.on(view, result=RuntimeError('ORA-00942'))
        central.on(predicate, result=df([{'OWNER': 'APP'}]))
        out = fn(database_id=database_id)
        assert list(out['OWNER']) == ['APP']
        fallback = central.last
        assert view not in fallback.sql and predicate in fallback.sql
        assert ('database_id' in fallback.params) is (database_id is not None)

    @pytest.mark.parametrize('fn, view', [
        (CentralQueries.get_hot_objects, 'v_hot_objects'),
        (CentralQueries.get_cold_objects, 'v_cold_objects'),
        (CentralQueries.get_compression_effectiveness, 'v_compression_effectiveness'),
        (CentralQueries.get_compression_candidates, 'v_compression_candidates'),
    ])
    def test_a_missing_view_as_the_database_reports_it_falls_back(self, central, monkeypatch,
                                                                  fn, view):
        # The central schema has none of these views: the connector reports
        # ORA-00942 as an oracledb error, which a non-strict query turns into
        # an empty frame (and a red banner) instead of reaching the fallback.
        import oracledb
        monkeypatch.setattr(CentralQueries, 'get_recommendations',
                            MagicMock(return_value=df([{'OWNER': 'APP'}])))
        central.on(view, result=oracledb.DatabaseError('ORA-00942: table or view does not exist'))
        central.on('from t_compression', result=df([{'OWNER': 'APP'}]))
        assert list(fn()['OWNER']) == ['APP']
        assert central.swallowed == []

    def test_view_result_is_returned_as_is(self, central):
        central.on('v_hot_objects', result=df([{'OWNER': 'X', 'HOTNESS_SCORE': 90}]))
        assert CentralQueries.get_hot_objects().iloc[0]['OWNER'] == 'X'
        assert len(central.calls) == 1


# ============================================================================
# Strategies and rules
# ============================================================================

def _page_strategy(**overrides):
    """The dict page_05_strategies passes to save_strategy."""
    data = {
        'strategy_id': None, 'strategy_name': 'Nightly', 'description': 'd',
        'category': 'BALANCED', 'hotness_threshold_hot': 75, 'hotness_threshold_warm': 50,
        'hotness_threshold_cool': 25, 'dml_threshold_high': 10000,
        'dml_threshold_medium': 1000, 'dml_threshold_low': 100,
        'size_threshold_large_gb': 50.0, 'size_threshold_medium_gb': 10.0,
        'size_threshold_small_gb': 1.0, 'age_threshold_recent_days': 30,
        'age_threshold_old_days': 90, 'age_threshold_archive_days': 180,
        'min_compression_ratio': 1.5, 'min_space_savings_mb': 100,
        'active_flag': 'Y', 'priority': 50,
    }
    data.update(overrides)
    return data


def _page_rule(**overrides):
    """The dict page_05_strategies passes to save_strategy_rule."""
    data = {
        'rule_id': None, 'strategy_id': 2, 'object_type': 'TABLE', 'hotness_min': 0,
        'hotness_max': 100, 'dml_ratio_threshold': 0.5, 'compression_type': 'OLTP',
        'priority': 50, 'enabled_flag': 'Y', 'rule_description': 'r',
    }
    data.update(overrides)
    return data


@pytest.mark.unit
class TestStrategies:

    def test_active_strategies(self, central):
        central.on('t_compression_strategies', result=df([{'STRATEGY_ID': 1}]))
        assert len(CentralQueries.get_strategies()) == 1
        assert central.last.params == {}

    def test_strategies_error_warns(self, central):
        central.on('t_compression_strategies', result=RuntimeError('ORA-00942'))
        assert CentralQueries.get_strategies().empty
        central.st.warning.assert_called_once()

    @pytest.mark.parametrize('include, flag', [(True, 'Y'), (False, 'N')])
    def test_all_strategies_inactive_flag(self, central, include, flag):
        CentralQueries.get_all_strategies(include_inactive=include)
        assert central.last.params == {'include_inactive': flag}

    @pytest.mark.parametrize('fn', [CentralQueries.get_strategy_rules,
                                    CentralQueries.get_all_strategy_rules])
    @pytest.mark.parametrize('strategy_id', [None, 3])
    def test_rules_bind_the_optional_strategy(self, central, fn, strategy_id):
        fn(strategy_id)
        assert central.last.params == {'strategy_id': strategy_id}

    @pytest.mark.parametrize('fn', [CentralQueries.get_strategy_rules,
                                    CentralQueries.get_all_strategy_rules,
                                    CentralQueries.get_all_strategies])
    def test_list_errors_give_empty_frames(self, central, fn):
        central.on('select', result=RuntimeError('x'))
        assert fn().empty

    def test_strategy_by_id(self, central):
        central.on('strategy_id = :strategy_id', result=df([{'STRATEGY_ID': 2, 'IS_DEFAULT': 'Y'}]))
        assert CentralQueries.get_strategy_by_id(2)['IS_DEFAULT'] == 'Y'
        central.on('strategy_id = :strategy_id', result=RuntimeError('x'))
        assert CentralQueries.get_strategy_by_id(2) == {}

    def test_create_strategy_binds_only_the_insert_placeholders(self, central):
        # The page sends strategy_id=None for a new strategy; the INSERT has no
        # :strategy_id placeholder (python-oracledb: DPY-4008 on the extra bind).
        ok, msg = CentralQueries.save_strategy(_page_strategy())
        assert (ok, msg) == (True, "Strategy created successfully")
        call = central.one('insert into t_compression_strategies')
        assert 'strategy_id' not in call.params and call.params['strategy_name'] == 'Nightly'

    def test_update_strategy(self, central):
        ok, msg = CentralQueries.save_strategy(_page_strategy(strategy_id=4))
        assert (ok, msg) == (True, "Strategy updated successfully")
        assert central.one('update t_compression_strategies').params['strategy_id'] == 4

    def test_save_strategy_no_rows_or_error(self, central):
        central.default_dml = 0
        assert CentralQueries.save_strategy(_page_strategy(strategy_id=4)) == (
            False, "Failed to save strategy")
        central.on('update t_compression_strategies', result=RuntimeError('ORA-00001'))
        assert CentralQueries.save_strategy(_page_strategy(strategy_id=4)) == (False, 'ORA-00001')

    def test_default_strategy_cannot_be_deleted(self, central):
        central.on('select is_default', result=df([{'IS_DEFAULT': 'Y'}]))
        assert CentralQueries.delete_strategy(1) == (False, "Cannot delete the default strategy")
        assert not central.find('update')

    def test_delete_strategy_deactivates(self, central):
        central.on('select is_default', result=df([{'IS_DEFAULT': None}]))
        assert CentralQueries.delete_strategy(3) == (True, "Strategy deactivated successfully")
        call = central.one("set active_flag = 'N'")
        assert call.params == {'strategy_id': 3}
        central.default_dml = 0
        assert CentralQueries.delete_strategy(3) == (False, "Failed to delete strategy")

    def test_set_default_clears_then_sets(self, central):
        assert CentralQueries.set_default_strategy(5) == (True, "Default strategy updated successfully")
        clear, set_ = central.find('update t_compression_strategies')
        assert "is_default = null" in clear.sql.lower() and clear.params == {}
        assert set_.params == {'strategy_id': 5}

    def test_set_default_stops_when_the_clear_fails(self, central):
        central.on('set is_default = null', result=RuntimeError('ORA-00054'))
        assert CentralQueries.set_default_strategy(5) == (False, 'ORA-00054')
        assert len(central.find('update')) == 1

    def test_set_default_unknown_strategy(self, central):
        central.on("set is_default = 'y'", result=0)
        assert CentralQueries.set_default_strategy(99) == (False, "Failed to set default strategy")

    def test_create_rule_binds_only_the_insert_placeholders(self, central):
        # Same as strategies: the page sends rule_id=None for a new rule.
        assert CentralQueries.save_strategy_rule(_page_rule()) == (True, "Rule created successfully")
        assert 'rule_id' not in central.one('insert into t_strategy_rules').params

    def test_update_rule(self, central):
        assert CentralQueries.save_strategy_rule(_page_rule(rule_id=8)) == (
            True, "Rule updated successfully")
        assert central.one('update t_strategy_rules').params['rule_id'] == 8

    def test_save_rule_failures(self, central):
        central.default_dml = 0
        assert CentralQueries.save_strategy_rule(_page_rule(rule_id=8)) == (False, "Failed to save rule")
        central.on('t_strategy_rules', result=RuntimeError('ORA-02291'))
        assert CentralQueries.save_strategy_rule(_page_rule()) == (False, 'ORA-02291')

    def test_delete_rule(self, central):
        assert CentralQueries.delete_strategy_rule(4) == (True, "Rule deleted successfully")
        assert central.last.params == {'rule_id': 4}
        central.default_dml = 0
        assert CentralQueries.delete_strategy_rule(4) == (False, "Failed to delete rule")
        central.on('delete from t_strategy_rules', result=RuntimeError('x'))
        assert CentralQueries.delete_strategy_rule(4) == (False, 'x')


# ============================================================================
# Index / LOB analysis and the recommendation justification
# ============================================================================

@pytest.mark.unit
class TestIndexLobAndJustification:

    @pytest.mark.parametrize('fn', [CentralQueries.get_index_compression_analysis,
                                    CentralQueries.get_lob_compression_analysis])
    def test_names_are_upper_cased(self, central, fn):
        fn('app', 'orders')
        assert central.last.params == {'owner': 'APP', 'table_name': 'ORDERS'}
        fn()
        assert central.last.params == {'owner': None, 'table_name': None}

    @pytest.mark.parametrize('fn', [CentralQueries.get_index_compression_analysis,
                                    CentralQueries.get_lob_compression_analysis])
    def test_errors_give_empty_frames(self, central, fn):
        central.on('select', result=RuntimeError('x'))
        assert fn('APP', 'T').empty

    def test_justification_of_a_missing_analysis(self, central):
        assert CentralQueries.build_recommendation_justification(1) == {
            'error': 'Analysis not found'}

    def test_justification_structure(self, central):
        central.on('analysis_id = :analysis_id', result=df([{
            'OWNER': 'APP', 'OBJECT_NAME': 'ORDERS', 'DATABASE_ID': 1, 'SIZE_MB': 2.0,
            'SIZE_BYTES': None, 'ROW_COUNT': 10, 'ADVISABLE_COMPRESSION': 'OLTP',
            'BASIC_RATIO': 1.5, 'OLTP_RATIO': 2.5, 'BEST_RATIO': 2.5, 'INSERT_COUNT': None,
            'HOTNESS_SCORE': 12.0, 'HOTNESS_CATEGORY': 'COLD', 'TABLESPACE_NAME': 'USERS',
            'BLOCK_COUNT': None, 'BLOCKS': 64}]))
        out = CentralQueries.build_recommendation_justification(11)
        assert out['summary']['table'] == 'APP.ORDERS'
        assert out['summary']['recommended'] == 'OLTP'
        assert out['compression_analysis']['oltp']['ratio'] == 2.5
        assert out['compression_analysis']['best_ratio'] == 2.5
        assert out['activity_metrics']['inserts'] == 0      # NULL -> 0
        assert out['activity_metrics']['hotness_category'] == 'COLD'
        assert out['storage']['tablespace'] == 'USERS'
        assert out['storage']['block_count'] == 64          # BLOCKS when BLOCK_COUNT is NULL
        assert out['storage']['size_bytes'] == 2.0 * 1024 * 1024


# ============================================================================
# Monitoring
# ============================================================================

@pytest.mark.unit
class TestMonitoring:

    def test_running_operations_cover_both_tables(self, central):
        CentralQueries.get_running_operations(database_id=2)
        sql = central.last.sql
        assert 't_compression_history' in sql and 't_advisor_run' in sql
        assert sql.count('database_id = :database_id') == 2

    @pytest.mark.parametrize('kind, table', [('COMPRESSION', 't_compression_history'),
                                             ('ANALYSIS', 't_advisor_run')])
    def test_operation_progress(self, central, kind, table):
        central.on(table, result=df([{'OPERATION_ID': 6, 'STATUS': 'RUNNING'}]))
        assert CentralQueries.get_operation_progress(kind, 6) == {'OPERATION_ID': 6,
                                                                   'STATUS': 'RUNNING'}
        assert central.last.params == {'operation_id': 6}

    def test_operation_progress_missing_or_error(self, central):
        assert CentralQueries.get_operation_progress('ANALYSIS', 1) == {}
        central.on('t_advisor_run', result=RuntimeError('x'))
        assert CentralQueries.get_operation_progress('ANALYSIS', 1) == {}
        assert _errors(central) == ['Failed to get operation progress: x']

    def test_recent_operations(self, central):
        CentralQueries.get_recent_operations(limit=4, database_id=1)
        assert central.last.params == {'limit': 4, 'database_id': 1}

    @pytest.mark.parametrize('fn', [CentralQueries.get_running_operations,
                                    CentralQueries.get_recent_operations])
    def test_monitor_errors_give_empty_frames(self, central, fn):
        central.on('select', result=RuntimeError('x'))
        assert fn().empty
        assert _errors(central)


# ============================================================================
# Target registry helpers
# ============================================================================

@pytest.mark.unit
class TestTargetRegistry:

    def test_target_databases_returns_a_copy_of_the_cache(self, central, monkeypatch):
        cached = df([{'DATABASE_ID': 1, 'DISPLAY_NAME': 'A'}])
        monkeypatch.setattr(cq_module, '_cached_target_databases', MagicMock(return_value=cached))
        out = CentralQueries.get_target_databases()
        out.columns = [c.lower() for c in out.columns]
        assert list(cached.columns) == ['DATABASE_ID', 'DISPLAY_NAME']

    def test_target_databases_none_or_error(self, central, monkeypatch):
        monkeypatch.setattr(cq_module, '_cached_target_databases', MagicMock(return_value=None))
        assert CentralQueries.get_target_databases().empty
        monkeypatch.setattr(cq_module, '_cached_target_databases',
                            MagicMock(side_effect=RuntimeError('down')))
        assert CentralQueries.get_target_databases().empty
        assert _errors(central) == ['Failed to get target databases: down']

    def test_cached_read_selects_active_targets(self, central):
        cq_module._cached_target_databases.clear()
        try:
            cq_module._cached_target_databases()
        finally:
            cq_module._cached_target_databases.clear()
        assert "is_active = 'y'" in central.last.sql.lower()

    def test_invalidate_clears_the_cache(self, monkeypatch):
        cache = MagicMock()
        monkeypatch.setattr(cq_module, '_cached_target_databases', cache)
        CentralQueries.invalidate_target_databases_cache()
        cache.clear.assert_called_once_with()
        cache.clear.side_effect = RuntimeError('no runtime')
        CentralQueries.invalidate_target_databases_cache()   # swallowed

    def test_target_database_row_for_the_connector(self, central, monkeypatch):
        from hcc_advisor.views import page_06_connections
        monkeypatch.setattr(page_06_connections, 'decrypt_password', lambda token: 'plain')
        central.on('from t_target_databases', result=df([{
            'DATABASE_ID': 3, 'DB_HOST': 'h', 'SERVICE_NAME': 's', 'PASSWORD_ENCRYPTED': 'tok'}]))
        row = CentralQueries.get_target_database(3)
        assert central.last.params == {'database_id': 3}
        assert row['database_id'] == 3
        assert (row['host'], row['service'], row['password']) == ('h', 's', 'plain')

    def test_target_database_fails_closed_on_a_bad_key(self, central, monkeypatch):
        from hcc_advisor.views import page_06_connections

        def boom(token):
            raise ValueError('InvalidToken')
        monkeypatch.setattr(page_06_connections, 'decrypt_password', boom)
        central.on('from t_target_databases', result=df([{
            'DATABASE_ID': 3, 'PASSWORD_ENCRYPTED': 'tok'}]))
        assert CentralQueries.get_target_database(3)['password'] is None

    def test_target_database_missing_or_error(self, central):
        assert CentralQueries.get_target_database(3) == {}
        central.on('from t_target_databases', result=RuntimeError('x'))
        assert CentralQueries.get_target_database(3) == {}

    def test_delete_target_invalidates_cache_and_closes_its_pool(self, central, monkeypatch):
        cache, close = MagicMock(), MagicMock()
        monkeypatch.setattr(cq_module, '_cached_target_databases', cache)
        monkeypatch.setattr(TargetConnector, 'close_pool', close)
        assert CentralQueries.delete_target_database(4) == (
            True, "Target database deactivated successfully")
        assert "set is_active = 'n'" in central.last.sql.lower()
        cache.clear.assert_called_once()
        close.assert_called_once_with(4)

    def test_delete_target_not_found_or_error(self, central, monkeypatch):
        monkeypatch.setattr(TargetConnector, 'close_pool', MagicMock())
        central.default_dml = 0
        assert CentralQueries.delete_target_database(4) == (
            False, "Failed to deactivate target database")
        central.on('update t_target_databases', result=RuntimeError('x'))
        assert CentralQueries.delete_target_database(4) == (False, 'x')

    def test_pool_close_failure_is_only_logged(self, central, monkeypatch):
        monkeypatch.setattr(TargetConnector, 'close_pool', MagicMock(side_effect=RuntimeError('x')))
        assert CentralQueries.delete_target_database(4)[0] is True

    def test_last_connected(self, central):
        assert CentralQueries.update_target_last_connected(2) is True
        assert central.last.params == {'database_id': 2}
        central.default_dml = 0
        assert CentralQueries.update_target_last_connected(2) is False
        central.on('last_connected', result=RuntimeError('x'))
        assert CentralQueries.update_target_last_connected(2) is False

    def test_metadata(self, central):
        assert CentralQueries.update_target_metadata(2, '19.0.0', 'EXADATA') is True
        assert central.last.params == {'database_id': 2, 'oracle_version': '19.0.0',
                                       'platform_type': 'EXADATA'}
        central.on('oracle_version', result=RuntimeError('x'))
        assert CentralQueries.update_target_metadata(2, '19.0.0', 'EXADATA') is False


# ============================================================================
# Ingestion: advisor runs and analysis results
# ============================================================================

def _analysis_frame():
    """Two analysed rows as the analysis code builds them (mixed case, NaN)."""
    return pd.DataFrame([
        {'owner': 'APP', 'object_name': 'ORDERS', 'object_type': 'TABLE',
         'size_bytes': 2 * 1048576, 'row_count': 10,
         'hotness_score': np.nan, 'advisable_compression': 'OLTP', 'insert_count': 3,
         'last_analyzed': pd.Timestamp('2026-09-01')},
        {'owner': 'APP', 'object_name': 'ORDERS', 'partition_name': 'P1', 'object_type': 'PARTITION',
         'size_bytes': 1048576, 'row_count': np.nan, 'hotness_score': 5.0,
         'advisable_compression': 'QUERY HIGH', 'last_analyzed': pd.NaT},
    ])


@pytest.mark.unit
class TestIngestion:

    def test_advisor_run_defaults_fill_every_placeholder(self, central):
        central.on('insert into t_advisor_run', result=41)
        assert CentralQueries.store_advisor_run(1, {'run_name': 'x', 'schema_filter': 'APP'}) == (True, 41)
        params = central.last.params
        assert params['database_id'] == 1 and params['run_type'] == 'ALL'
        assert params['include_partitions'] == 'N' and params['analysis_mode'] == 'FULL'

    def test_advisor_run_without_id_or_on_error(self, central):
        central.on('insert into t_advisor_run', result=None)
        assert CentralQueries.store_advisor_run(1, {}) == (False, None)
        central.on('insert into t_advisor_run', result=RuntimeError('x'))
        assert CentralQueries.store_advisor_run(1, {}) == (False, None)

    def test_empty_results_store_nothing(self, central):
        assert CentralQueries.store_analysis_results(1, 2, pd.DataFrame()) is True
        assert central.calls == []

    def test_results_merge_one_bound_row_each(self, central):
        assert CentralQueries.store_analysis_results(1, 2, _analysis_frame()) is True
        rows = central.find('merge into t_compression_analysis', kind='executemany')
        assert len(rows) == 2
        table, part = (r.params for r in rows)
        assert table['database_id'] == 1 and table['advisor_run_id'] == 2
        assert table['object_type'] == 'TABLE'
        assert table['partition_name'] is None and table['hotness_score'] is None   # NaN -> None
        assert table['insert_count'] == 3 and part['insert_count'] is None
        assert part['object_type'] == 'PARTITION' and part['row_count'] is None
        assert part['last_analyzed'] is None               # NaT -> None

    def test_object_type_defaults_to_table(self, central):
        frame = pd.DataFrame([{'OWNER': 'APP', 'OBJECT_NAME': 'T', 'SIZE_BYTES': 1}])
        assert CentralQueries.store_analysis_results(1, None, frame) is True
        params = central.one('merge', kind='executemany').params
        assert params['object_type'] == 'TABLE' and params['advisor_run_id'] is None
        assert params['insert_count'] == 0              # activity counters default to 0

    def test_results_error_reports_failure(self, central):
        central.on('merge into t_compression_analysis', result=RuntimeError('ORA-01400'))
        assert CentralQueries.store_analysis_results(1, 2, _analysis_frame()) is False
        assert _errors(central) == ['Failed to store analysis results: ORA-01400']


# ============================================================================
# Cross-database reports
# ============================================================================

@pytest.mark.unit
class TestCrossDatabase:

    @pytest.mark.parametrize('fn', [CentralQueries.get_savings_by_database,
                                    CentralQueries.compare_databases])
    def test_active_targets_only_without_binds(self, central, fn):
        central.on('t_target_databases', result=df([{'DATABASE_ID': 1}]))
        assert len(fn()) == 1
        assert central.last.params == {}
        assert "is_active = 'y'" in central.last.sql.lower()

    @pytest.mark.parametrize('fn, message', [
        (CentralQueries.get_savings_by_database, 'Failed to get savings by database: x'),
        (CentralQueries.compare_databases, 'Failed to compare databases: x'),
    ])
    def test_errors_give_empty_frames_and_a_banner(self, central, fn, message):
        central.on('t_target_databases', result=RuntimeError('x'))
        assert fn().empty
        assert _errors(central) == [message]
