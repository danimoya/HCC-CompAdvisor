"""
Smoke tests for the view pages under ``streamlit.testing.v1.AppTest``.

Each page's entry function is rendered for an empty state (no target selected
/ no data) and a populated state, as admin and as viewer (roles through session
state, so the real role gates run), and checked for: no exception, the key
elements of that state, and role-gated controls disabled for viewers. A few
tests click through a representative action (Check Schema Size, the details
of one recommendation, the compression-status refresh, the setup wizard
steps, an AI analysis) to render the parts behind it.

No database: CentralConnector / TargetConnector are routed to empty fakes
(tests/unit/db_fakes.py), so anything a test does not provide comes back
empty through the real query layer, and every statement's binds are checked
against its placeholders. Populated data is provided by patching the
CentralQueries / TargetQueries read functions. st.rerun and the auto-refresh
clock are mocked so buttons and auto-refresh never loop (see
tests/unit/page_harness.py). Page actions (buttons that write) are in
test_page_actions.py.

The Compression Wizard is only rendered at its "no targets" step (its target
picker is being reworked separately).
"""
import json
from types import SimpleNamespace
from unittest.mock import MagicMock

import pandas as pd
import pytest
import requests

from hcc_advisor import __version__
from hcc_advisor.auth import ROLE_ADMIN, ROLE_OPERATOR, ROLE_VIEWER
from hcc_advisor.utils import url_guard
from hcc_advisor.utils.central_queries import CentralQueries
from hcc_advisor.utils.sql_patches import find_patches_dir, list_patch_dirs
from hcc_advisor.utils.target_queries import TargetQueries
from hcc_advisor.views import page_00_setup, page_09_admin, page_13_ai_advisor

from tests.unit.db_fakes import df
from tests.unit.page_harness import (
    ANALYSIS_DETAILS, COLUMN_INFO, EXPORT_JOBS, HISTORY, INDEX_ANALYSIS, INDEXES,
    LOB_ANALYSIS, RECS, ROLES, RULES, SAVINGS_BY_STRATEGY, SCHEDULER_JOBS, STRATEGIES,
    _TS, button, env_fixture, ok, page, patch_scan, schema_state, texts,
)

_FIXTURES = (env_fixture,)  # registered as the `env` fixture


# ============================================================================
# Run Analysis
# ============================================================================

def _analysis_data(env):
    env.returns(TargetQueries, 'get_available_schemas', ['APP', 'HR'])
    env.returns(TargetQueries, 'get_cpu_count', 8)
    env.returns(CentralQueries, 'get_latest_analysis', {
        'analysis_id': 9, 'status': 'COMPLETED', 'tables_analyzed': 40, 'candidates_found': 12,
        'started_at': 's', 'completed_at': 'c', 'duration_seconds': 60, 'min_size_mb': 0,
        'total_current_size_gb': 4.0, 'total_compressed_size_gb': 1.5, 'avg_savings_pct': 62.5})
    env.returns(CentralQueries, 'get_recommendations', RECS)
    env.returns(CentralQueries, 'get_running_operations', df([
        {'OPERATION_ID': 10, 'OPERATION_TYPE': 'ANALYSIS', 'OWNER': 'APP', 'STATUS': 'RUNNING',
         'DURATION_MINUTES': 2.5, 'PROGRESS_PCT': 40.0}]))
    env.returns(CentralQueries, 'get_operation_progress', {
        'OBJECTS_ANALYZED': 5, 'RECOMMEND_OLTP': 2, 'RECOMMEND_ADV_HIGH': 1})
    env.returns(CentralQueries, 'get_analysis_runs', df([
        {'RUN_ID': 9, 'STATUS': 'COMPLETED', 'OWNER_FILTER': None, 'TABLES_ANALYZED': 40,
         'CANDIDATES_FOUND': 12, 'DURATION_SECONDS': 60, 'RUN_DATE': _TS, 'ERROR_MESSAGE': None},
        {'RUN_ID': 8, 'STATUS': 'FAILED', 'OWNER_FILTER': 'HR', 'TABLES_ANALYZED': 0,
         'CANDIDATES_FOUND': 0, 'DURATION_SECONDS': 5, 'RUN_DATE': _TS,
         'ERROR_MESSAGE': 'ORA-01031: insufficient privileges'}]))


@pytest.mark.unit
class TestAnalysisPage:

    @pytest.mark.parametrize('role', ROLES)
    def test_without_a_target(self, env, role):
        at = ok(page('page_01_analysis', 'show_analysis_page', role, db_id=None).run())
        body = texts(at)
        assert 'Compression Analysis' in body
        assert 'Select a target database from the sidebar to run analysis.' in body
        assert 'No analysis results available' in body
        assert 'No analysis runs found' in body

    @pytest.mark.parametrize('role, can_run', [(ROLE_ADMIN, True), (ROLE_VIEWER, False)])
    def test_populated(self, env, role, can_run):
        _analysis_data(env)
        at = ok(page('page_01_analysis', 'show_analysis_page', role).run())
        body = texts(at)
        assert 'Latest Analysis Results' in body and 'Tables Analyzed 40' in body
        assert 'Running Analysis' in body and 'Candidates Found 3' in body
        assert 'ORA-01031' in body                      # failed run's error
        assert at.dataframe                             # candidates + runs tables
        assert button(at, 'Start Analysis').disabled is not can_run

    def test_schema_size(self, env):
        env.target.on('segment_count', result=df([
            {'OWNER': 'APP', 'TOTAL_BYTES': 3 * 1073741824, 'TOTAL_KB': 3145728.0,
             'TOTAL_MB': 3072.0, 'TOTAL_GB': 3.0, 'SEGMENT_COUNT': 40},
            {'OWNER': 'HR', 'TOTAL_BYTES': 1048576, 'TOTAL_KB': 1024.0, 'TOTAL_MB': 1.0,
             'TOTAL_GB': 0.001, 'SEGMENT_COUNT': 3}]))
        at = ok(page('page_01_analysis', 'show_analysis_page').run())
        at = ok(at.button(key='check_schema_size_btn').click().run())
        body = texts(at)
        assert 'Total Size 3.00 GB' in body and 'Schemas 2' in body and 'Segments 43' in body

    def test_schema_size_without_data(self, env):
        at = ok(page('page_01_analysis', 'show_analysis_page').run())
        at = ok(at.button(key='check_schema_size_btn').click().run())
        assert 'No schema data returned.' in texts(at)


# ============================================================================
# Recommendations
# ============================================================================

def _recommendation_data(env):
    env.returns(TargetQueries, 'get_available_schemas', ['APP', 'HR'])
    env.returns(TargetQueries, 'get_cpu_count', 8)
    env.returns(CentralQueries, 'get_recommendations', RECS)
    env.returns(CentralQueries, 'get_analysis_details', ANALYSIS_DETAILS)
    env.returns(CentralQueries, 'get_index_compression_analysis', INDEX_ANALYSIS)
    env.returns(CentralQueries, 'get_lob_compression_analysis', LOB_ANALYSIS)
    env.returns(TargetQueries, 'get_table_column_info', COLUMN_INFO)
    env.returns(TargetQueries, 'get_table_tablespace', 'USERS')


@pytest.mark.unit
class TestRecommendationsPage:

    @pytest.mark.parametrize('role', ROLES)
    def test_empty(self, env, role):
        at = ok(page('page_02_recommendations', 'show_recommendations_page', role).run())
        assert 'No recommendations found' in texts(at)

    @pytest.mark.parametrize('role', ROLES)
    def test_populated(self, env, role):
        _recommendation_data(env)
        at = ok(page('page_02_recommendations', 'show_recommendations_page', role).run())
        body = texts(at)
        assert [t.label for t in at.tabs] == [
            'Overview & Charts', 'Detailed Recommendations', 'Compression Status']
        assert 'Export All Recommendations' in body
        assert 'Click Refresh to query the target database.' in body

    def test_analysis_details_of_one_recommendation(self, env):
        _recommendation_data(env)
        at = ok(page('page_02_recommendations', 'show_recommendations_page').run())
        at = ok(at.selectbox(key='detail_selector').select('101: APP.ORDERS').run())
        body = texts(at)
        assert 'Table APP.ORDERS' in body and 'Recommended QUERY HIGH' in body
        assert 'Best Compression Ratio: 4.00x' in body
        assert 'High Activity Table' in body                    # hotness 80
        assert 'ORDERS_PK' in body and 'Tablespace USERS' in body
        assert 'Consider upgrading to SecureFile' in body

    def test_compression_status_from_the_target(self, env):
        _recommendation_data(env)
        env.target.on('from all_tables t', result=df([
            {'OWNER': 'APP', 'TABLE_NAME': 'ORDERS', 'COMPRESSION': 'ENABLED',
             'COMPRESS_FOR': 'QUERY HIGH', 'NUM_ROWS': 100000, 'SIZE_MB': 128.0}]))
        at = ok(page('page_02_recommendations', 'show_recommendations_page').run())
        at.selectbox(key='comp_status_schema').select('APP')
        at = ok(at.button(key='comp_status_refresh').click().run())
        assert 'No partitions found.' in texts(at) and 'No subpartitions found.' in texts(at)
        tables = env.target.one('from all_tables t')
        assert tables.params == {'schema': 'APP'}


# ============================================================================
# Execution, History, Sessions, Tablespaces, Connections (render only)
# ============================================================================

@pytest.mark.unit
class TestExecutionPage:

    @pytest.mark.parametrize('role', [ROLE_OPERATOR, ROLE_VIEWER])
    def test_empty(self, env, role):
        at = ok(page('page_03_execution', 'show_execution_page', role).run())
        body = texts(at)
        if role == ROLE_VIEWER:
            assert 'Executing compression requires the operator role.' in body
        else:
            assert 'No recommendations available. Run an analysis first.' in body

    @pytest.mark.parametrize('role', [ROLE_OPERATOR, ROLE_VIEWER])
    def test_populated(self, env, role):
        env.returns(CentralQueries, 'get_recommendations', RECS)
        env.returns(TargetQueries, 'get_available_schemas', ['APP'])
        env.returns(TargetQueries, 'get_cpu_count', 8)
        env.returns(CentralQueries, 'get_running_operations', df([
            {'OPERATION_ID': 11, 'OPERATION_TYPE': 'COMPRESSION', 'OWNER': 'APP',
             'TABLE_NAME': 'ORDERS', 'PARTITION_NAME': None, 'STRATEGY': 'QUERY HIGH',
             'STATUS': 'IN_PROGRESS', 'START_TIME': _TS, 'DURATION_MINUTES': 3.0,
             'ORIGINAL_SIZE_MB': 512.0, 'PROGRESS_PCT': None}]))
        env.returns(CentralQueries, 'get_recent_operations', df([
            {'OPERATION_ID': 11, 'OPERATION_TYPE': 'COMPRESSION', 'OWNER': 'APP',
             'NAME': 'ORDERS', 'DETAIL': None, 'STRATEGY': 'QUERY HIGH', 'STATUS': 'SUCCESS',
             'START_TIME': _TS, 'END_TIME': _TS, 'DURATION_MINUTES': 5.0, 'RESULT_PCT': 75.0,
             'ERROR_MESSAGE': None}]))
        at = ok(page('page_03_execution', 'show_execution_page', role).run())
        assert 'Execute Compression' in texts(at)


@pytest.mark.unit
class TestHistoryPage:

    @pytest.mark.parametrize('role', ROLES)
    def test_empty(self, env, role):
        at = ok(page('page_04_history', 'show_history_page', role).run())
        assert 'No execution history found' in texts(at)

    @pytest.mark.parametrize('role', ROLES)
    def test_populated(self, env, role):
        env.returns(CentralQueries, 'get_execution_history', HISTORY)
        at = ok(page('page_04_history', 'show_history_page', role).run())
        body = texts(at)
        assert 'Total Executions 2' in body and 'Tables Processed 2' in body


@pytest.mark.unit
class TestSessionsPage:

    @pytest.mark.parametrize('role', ROLES)
    def test_without_a_target(self, env, role):
        ok(page('page_07_sessions', 'show_sessions_page', role, db_id=None).run())

    @pytest.mark.parametrize('role', ROLES)
    def test_populated(self, env, role):
        longops = df([{'SID': 12, 'SERIAL_NUM': 3, 'OPNAME': 'Table Scan', 'TARGET': 'APP.ORDERS',
                       'TARGET_DESC': None, 'SOFAR': 50, 'TOTALWORK': 100, 'PCT_COMPLETE': 50.0,
                       'UNITS': 'Blocks', 'START_TIME': _TS, 'LAST_UPDATE_TIME': _TS,
                       'ELAPSED_SECONDS': 30, 'TIME_REMAINING_SEC': 30, 'MESSAGE': 'm',
                       'USERNAME': 'HCC', 'SQL_ID': 'abc'}])
        env.returns(TargetQueries, 'get_session_longops', longops)
        env.returns(TargetQueries, 'get_all_active_longops', longops)
        env.returns(TargetQueries, 'get_compression_sessions', df([
            {'SID': 12, 'SERIAL_NUM': 3, 'USERNAME': 'HCC', 'STATUS': 'ACTIVE',
             'SCHEMANAME': 'APP', 'OSUSER': 'oracle', 'PROGRAM': 'p', 'MODULE': 'm',
             'ACTION': 'a', 'SQL_ID': 'abc', 'ELAPSED_SECONDS': 30, 'WAIT_CLASS': 'User I/O',
             'EVENT': 'db file scattered read', 'SQL_TEXT': 'ALTER TABLE APP.ORDERS MOVE',
             'OPNAME': 'Table Scan', 'LONGOPS_TARGET': 'APP.ORDERS', 'PCT_COMPLETE': 50.0,
             'REMAINING_MINUTES': 0.5}]))
        ok(page('page_07_sessions', 'show_sessions_page', role).run())


@pytest.mark.unit
class TestTablespacesPage:

    @pytest.mark.parametrize('role', ROLES)
    def test_without_a_target(self, env, role):
        ok(page('page_10_tablespaces', 'show_tablespaces_page', role, db_id=None).run())

    @pytest.mark.parametrize('role', ROLES)
    def test_empty_target(self, env, role):
        ok(page('page_10_tablespaces', 'show_tablespaces_page', role).run())


@pytest.mark.unit
class TestConnectionsPage:

    def test_viewer_is_refused(self, env):
        at = ok(page('page_06_connections', 'show_connections_page', ROLE_VIEWER).run())
        assert 'requires the admin role' in texts(at)

    def test_no_targets(self, env):
        env.targets = pd.DataFrame()
        at = ok(page('page_06_connections', 'show_connections_page').run())
        assert 'No target databases registered' in texts(at)

    def test_registered_target(self, env):
        at = ok(page('page_06_connections', 'show_connections_page').run())
        body = texts(at)
        assert 'ACTIVE TARGET DATABASE' in body and '`db1`' in body


# ============================================================================
# Strategies
# ============================================================================

@pytest.mark.unit
class TestStrategiesPage:

    @pytest.mark.parametrize('role', ROLES)
    def test_empty(self, env, role):
        at = ok(page('page_05_strategies', 'show_strategies_page', role, db_id=None).run())
        body = texts(at)
        assert 'No strategies found' in body
        assert 'No active strategies found. Create a strategy first.' in body

    @pytest.mark.parametrize('role, can_edit', [(ROLE_ADMIN, True), (ROLE_VIEWER, False)])
    def test_populated(self, env, role, can_edit):
        env.returns(CentralQueries, 'get_all_strategies', STRATEGIES)
        env.returns(CentralQueries, 'get_all_strategy_rules', RULES)
        env.returns(CentralQueries, 'get_savings_by_strategy', SAVINGS_BY_STRATEGY)
        env.returns(TargetQueries, 'get_available_schemas', ['APP'])
        at = ok(page('page_05_strategies', 'show_strategies_page', role).run())
        body = texts(at)
        assert 'Strategy Performance Statistics' in body and 'Delete Rule' in body
        assert ('View only: editing strategies requires the admin role.' in body) is not can_edit
        assert button(at, '🗑️ Delete Rule').disabled is not can_edit

    def test_admin_creates_a_strategy(self, env):
        env.returns(CentralQueries, 'get_all_strategies', STRATEGIES)
        at = ok(page('page_05_strategies', 'show_strategies_page').run())
        # the editor opens on "Create New Strategy"
        name, = [w for w in at.text_input if w.label == 'Strategy Name *']
        name.input('Nightly')
        at = ok(button(at, '💾 Save Strategy').click().run())
        insert = env.central.one('insert into t_compression_strategies')
        assert insert.params['strategy_name'] == 'Nightly'
        env.rerun.assert_called()

    def test_compare_strategies(self, env):
        env.returns(TargetQueries, 'get_available_schemas', ['APP'])
        env.returns(TargetQueries, 'compare_strategies', pd.DataFrame([
            {'strategy': 'QUERY LOW', 'current_size_mb': 100.0, 'row_count': 1000,
             'estimated_size_mb': 60.0, 'savings_pct': 40.0, 'compression_ratio': 4.0,
             'estimated_blocks': 1.7},
            {'strategy': 'QUERY HIGH', 'current_size_mb': 100.0, 'row_count': 1000,
             'estimated_size_mb': 40.0, 'savings_pct': 60.0, 'compression_ratio': 6.0,
             'estimated_blocks': 2.5}]))
        at = ok(page('page_05_strategies', 'show_strategies_page').run())
        at = ok(button(at, 'Compare').click().run())
        assert 'Recommended Strategy:** QUERY HIGH (60.0% savings)' in texts(at)


# ============================================================================
# Quick Action
# ============================================================================

@pytest.mark.unit
class TestQuickScanPage:

    @pytest.mark.parametrize('role', ROLES)
    def test_without_a_target(self, env, role):
        at = ok(page('page_08_quick_scan', 'show_quick_scan_page', role, db_id=None).run())
        assert 'Select a target database from the sidebar.' in texts(at)

    @pytest.mark.parametrize('role, can_scan', [(ROLE_ADMIN, True), (ROLE_VIEWER, False)])
    def test_no_scan_data(self, env, role, can_scan):
        at = ok(page('page_08_quick_scan', 'show_quick_scan_page', role).run())
        assert "No scan data. Click 'Scan Now' to analyze tables." in texts(at)
        assert at.button(key='qs_scan').disabled is not can_scan

    @pytest.mark.parametrize('role', ROLES)
    def test_populated(self, env, role):
        env.returns(TargetQueries, 'get_available_schemas', ['APP', 'HR'])
        env.returns(TargetQueries, 'get_cpu_count', 16)
        env.returns(CentralQueries, 'get_recommendations', RECS)
        env.central.on("operation_status = 'in_progress'", result=df([
            {'OWNER': 'APP', 'OBJECT_NAME': 'ORDERS', 'PARTITION_NAME': None,
             'SUBPARTITION_NAME': None}]))
        at = ok(page('page_08_quick_scan', 'show_quick_scan_page', role).run())
        body = texts(at)
        assert [t.label for t in at.tabs] == ['Tables', 'Partitions', 'Subpartitions', 'Schemas']
        assert 'CPU_COUNT=16' in body
        assert '2 objects' in body                          # the Tables tab
        assert 'operations will be included in the export' in body

    def test_bulk_schema_tab_counts_pending_leaf_candidates(self, env):
        env.returns(TargetQueries, 'get_available_schemas', ['APP', 'HR'])
        env.returns(TargetQueries, 'get_cpu_count', 16)
        env.returns(CentralQueries, 'get_recommendations', RECS)
        at = ok(page('page_08_quick_scan', 'show_quick_scan_page').run())
        at = ok(at.multiselect(key='qs_bulk_schemas').select('APP').run())
        # ORDERS (pending) and SALES.SP1 (failed, retryable); SALES.P1 is compressed
        assert '**2** pending candidates across **1** schema(s)' in texts(at)


# ============================================================================
# Administration
# ============================================================================

@pytest.mark.unit
class TestAdminPage:

    def test_viewer_is_refused(self, env):
        at = ok(page('page_09_admin', 'show_admin_page', ROLE_VIEWER).run())
        assert 'Administration is restricted to the admin role.' in texts(at)
        assert not at.tabs

    def test_admin_with_an_unreachable_central_state(self, env):
        env.patch(page_09_admin, 'find_patches_dir', lambda: None)
        at = ok(page('page_09_admin', 'show_admin_page').run())
        body = texts(at)
        assert len(at.tabs) == 6
        assert 'Patches directory not found' in body
        assert 'AWR-enhanced hotness scoring is **disabled**.' in body
        assert 'Could not read current row counts' in body       # purge preview unavailable

    def test_admin_populated(self, env):
        patches_dir = find_patches_dir()
        assert patches_dir is not None
        dirs = list_patch_dirs(patches_dir)
        env.patch(page_09_admin, 'patches_dir_problem', lambda d: None)
        env.patch(page_09_admin, 'scan_patches', lambda pd_: patch_scan(dirs))
        env.central.on("key in ('ollama_url', 'ollama_model')", result=df([
            {'KEY': 'ollama_url', 'VALUE': 'http://ollama.example:11434'},
            {'KEY': 'ollama_model', 'VALUE': 'mistral'}]))
        env.central.on("key = 'webhook_url'", result=df([{'VALUE': 'https://hooks.example/x'}]))
        env.central.on("key = 'awr_acknowledged'", result=df([{'VALUE': 'Y'}]))
        env.central.on("key = 'schema_version'", result=df([{'VALUE': __version__}]))
        env.central.on("'analysis results' as item", result=df([
            {'ITEM': 'Analysis Results', 'CNT': 1200}, {'ITEM': 'Execution History', 'CNT': 30}]))
        env.returns(CentralQueries, 'get_history_purge_preview', {
            'counts': {t: 5 for t in CentralQueries.PURGE_HISTORY_TABLES},
            'targets_to_reset': 1,
            'active': {'queued': 1, 'in_progress': 0, 'running_runs': 0}})
        at = ok(page('page_09_admin', 'show_admin_page').run())
        body = texts(at)
        assert f'Total Patches {len(dirs)}' in body and 'Applied 2' in body
        assert 'AWR feature acknowledged and enabled' in body
        assert f'Schema Version {__version__}' in body and 'Analysis Results 1,200' in body
        assert 'Operations in flight for this scope' in body
        assert at.text_input(key='admin_ollama_model').value == 'mistral'
        assert at.text_input(key='webhook_url_input').value == 'https://hooks.example/x'
        # purge is blocked while an operation is queued
        assert at.button(key='admin_purge_btn_all').disabled


# ============================================================================
# Index Manager
# ============================================================================

@pytest.mark.unit
class TestIndexesPage:

    @pytest.mark.parametrize('role', ROLES)
    def test_without_a_target(self, env, role):
        at = ok(page('page_11_indexes', 'show_indexes_page', role, db_id=None).run())
        assert 'Select a target database from the sidebar.' in texts(at)

    @pytest.mark.parametrize('role', ROLES)
    def test_no_broken_indexes(self, env, role):
        at = ok(page('page_11_indexes', 'show_indexes_page', role).run())
        assert 'No unusable or invalid indexes found.' in texts(at)

    @pytest.mark.parametrize('role', ROLES)
    def test_populated(self, env, role):
        env.returns(TargetQueries, 'get_available_schemas', ['APP'])
        env.target.on('from all_indexes i', result=INDEXES)
        env.target.on("like 'idxr_%'", result=df([
            {'JOB_NAME': 'IDXR_SALES_IX_0924101010123', 'ELAPSED_SECONDS': 12.0,
             'SESSION_ID': 77}]))
        at = ok(page('page_11_indexes', 'show_indexes_page', role).run())
        body = texts(at)
        assert 'Total Indexes 2' in body and 'Unusable 1' in body and 'Invalid 1' in body
        assert 'Rebuild Jobs' in body

    def test_schema_filter_and_valid_indexes_are_bound(self, env):
        env.returns(TargetQueries, 'get_available_schemas', ['APP'])
        at = ok(page('page_11_indexes', 'show_indexes_page').run())
        at.selectbox(key='idx_schema').select('APP')
        at = ok(at.checkbox(key='idx_show_valid').check().run())
        query = env.target.find('from all_indexes i')[-1]
        assert query.params == {'schema': 'APP'} and "status != 'valid'" not in query.sql.lower()
        assert 'No indexes found for the selected schema.' in texts(at)

    def test_refresh_checks_finished_rebuild_jobs(self, env):
        env.target.on('dba_scheduler_job_run_details', result=df([
            {'JOB_NAME': 'IDXR_A_1', 'STATUS': 'SUCCEEDED', 'START_TIME': 's', 'INFO': None},
            {'JOB_NAME': 'IDXR_B_2', 'STATUS': 'FAILED', 'START_TIME': 's', 'INFO': 'ORA-1'}]))
        at = ok(page('page_11_indexes', 'show_indexes_page').run())
        at = ok(at.button(key='idx_refresh').click().run())
        assert env.target.find('dba_scheduler_job_run_details')
        env.rerun.assert_called()


# ============================================================================
# Scheduler
# ============================================================================

@pytest.mark.unit
class TestSchedulerPage:

    @pytest.mark.parametrize('role', ROLES)
    def test_empty(self, env, role):
        at = ok(page('page_12_scheduler', 'show_scheduler_page', role).run())
        body = texts(at)
        assert 'No compression jobs recorded in the last 24 hours.' in body
        assert 'No operations match the selected filters.' in body
        assert 'Total (24h) 0' in body

    def test_all_databases_without_targets(self, env):
        env.targets = pd.DataFrame()
        at = ok(page('page_12_scheduler', 'show_scheduler_page', db_id=None).run())
        body = texts(at)
        assert 'Showing jobs across ALL registered databases' in body
        assert 'No target databases registered.' in body

    @pytest.mark.parametrize('role', ROLES)
    def test_populated(self, env, role):
        env.returns(CentralQueries, 'get_scheduler_job_summary',
                    {'queued': 1, 'running': 1, 'succeeded': 3, 'failed': 1, 'total': 6})
        env.returns(CentralQueries, 'get_scheduler_job_details', SCHEDULER_JOBS)
        env.returns(CentralQueries, 'get_scheduler_jobs_for_export', EXPORT_JOBS)
        at = ok(page('page_12_scheduler', 'show_scheduler_page', role).run())
        body = texts(at)
        assert 'Total (24h) 6' in body and 'Failed 1' in body
        assert '**2** operations will be included in the export' in body
        assert at.dataframe

    def test_status_filter_and_csv_export(self, env):
        env.returns(CentralQueries, 'get_scheduler_job_details', SCHEDULER_JOBS)
        env.returns(CentralQueries, 'get_scheduler_jobs_for_export', EXPORT_JOBS)
        at = ok(page('page_12_scheduler', 'show_scheduler_page').run())
        at.selectbox(key='sched_status_filter').select('SUCCESS')
        at = ok(at.radio(key='export_format').set_value('CSV manifest').run())
        body = texts(at)
        assert "No jobs with status 'SUCCESS' in the last 24 hours." in body
        assert 'The CSV manifest can be re-imported below' in body


# ============================================================================
# AI Advisor (Ollama mocked)
# ============================================================================

class FakeResponse:
    """requests.Response stand-in (JSON body or streamed lines)."""

    def __init__(self, payload=None, lines=()):
        self.payload = payload or {}
        self.lines = list(lines)
        self.status_code = 200

    def raise_for_status(self):
        pass

    def json(self):
        return self.payload

    def iter_lines(self, decode_unicode=False):
        return iter(self.lines)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _fake_ollama(answer='## Priority Recommendations\nCompress APP.ORDERS first.'):
    """A `requests` stand-in for Ollama: /api/tags, /api/show, /api/generate
    (plain, and streamed word by word with a blank and a non-JSON line)."""
    words = answer.split(' ')
    chunks = [json.dumps({'response': w + ' ', 'done': False}) for w in words[:-1]]
    chunks += ['', 'not json', json.dumps({'response': words[-1], 'done': True})]

    def get(url, **kwargs):
        return FakeResponse({'models': [{'name': 'llama3:latest'}]})

    def post(url, stream=False, **kwargs):
        if url.endswith('/api/show'):
            return FakeResponse({'details': {'format': 'gguf', 'family': 'llama',
                                             'parameter_size': '8B'}})
        if stream:
            return FakeResponse(lines=chunks)
        return FakeResponse({'response': 'Hi there friend', 'load_duration': 2e9,
                             'eval_count': 4, 'eval_duration': 1e9})

    return SimpleNamespace(get=MagicMock(side_effect=get), post=MagicMock(side_effect=post),
                           exceptions=requests.exceptions)


@pytest.mark.unit
class TestAiAdvisorPage:

    @pytest.mark.parametrize('role', ROLES)
    def test_not_configured(self, env, role):
        at = ok(page('page_13_ai_advisor', 'show_ai_advisor_page', role).run())
        assert 'Configure Ollama URL in **Admin → AI / Ollama** tab first.' in texts(at)

    def test_url_rejected_by_the_ssrf_guard(self, env):
        def reject(url, kind):
            raise url_guard.UrlNotAllowed('loopback address')
        env.patch(url_guard, 'validate_outbound_url', reject)
        at = ok(page('page_13_ai_advisor', 'show_ai_advisor_page',
                     ollama_url='http://127.0.0.1:11434').run())
        assert 'Ollama URL rejected by SSRF guard: loopback address' in texts(at)
        assert not at.button

    def _configured(self, env):
        env.patch(url_guard, 'validate_outbound_url', lambda url, kind: url)
        fake = env.patch(page_13_ai_advisor, 'requests', _fake_ollama())
        env.returns(CentralQueries, 'get_recommendations', RECS)
        env.returns(CentralQueries, 'get_execution_history', HISTORY)
        env.returns(CentralQueries, 'get_growth_alerts', df([
            {'OWNER': 'APP', 'OBJECT_NAME': 'ORDERS', 'OBJECT_TYPE': 'TABLE',
             'COMPRESSED_MB': 128.0, 'CURRENT_MB': 200.0, 'GROWTH_PCT': 56.3}]))
        env.central.on("key = :k", result=lambda sql, params: df([
            {'VALUE': {'ollama_url': 'http://ollama.example:11434',
                       'ollama_model': 'llama3'}[params['k']]}]))
        return fake

    def test_analysis_and_follow_up(self, env):
        fake = self._configured(env)
        at = ok(page('page_13_ai_advisor', 'show_ai_advisor_page').run())
        at = ok(at.button(key='ai_analyze').click().run())
        body = texts(at)
        assert 'Compress APP.ORDERS first.' in body and 'AI Analysis' in body
        prompt = at.session_state['ai_last_prompt']
        assert '| APP | ORDERS | - |' in prompt and '| APP | SALES | P2.SP1 |' in prompt
        assert 'ORA-01652' in prompt and 'GROWTH ALERTS' in prompt
        assert fake.post.call_args_list[0].kwargs['json']['prompt'] == ''   # warm-up

        at = ok(at.text_input(key='ai_followup').input('Which table first?').run())
        at = ok(at.button(key='ai_ask').click().run())
        assert len(at.session_state['ai_chat_history']) == 4
        assert 'User: Which table first?' in at.session_state['ai_last_followup_prompt']

    def test_single_table_scope(self, env):
        self._configured(env)
        at = ok(page('page_13_ai_advisor', 'show_ai_advisor_page').run())
        at = ok(at.selectbox(key='ai_scope').select('Single Table').run())
        at.text_input(key='ai_table').input('APP.SALES')
        at = ok(at.button(key='ai_analyze').click().run())
        prompt = at.session_state['ai_last_prompt']
        assert 'SALES' in prompt and '| APP | ORDERS |' not in prompt

    def test_diagnostic(self, env):
        self._configured(env)
        at = ok(page('page_13_ai_advisor', 'show_ai_advisor_page').run())
        at = ok(at.button(key='ai_test_generate').click().run())
        assert 'Ollama is reachable and generating correctly.' in texts(at)

    def test_unreachable_ollama(self, env):
        fake = self._configured(env)
        fake.get.side_effect = requests.exceptions.ConnectionError('refused')
        fake.post.side_effect = requests.exceptions.Timeout('read timed out')
        at = ok(page('page_13_ai_advisor', 'show_ai_advisor_page').run())
        at = ok(at.button(key='ai_test_generate').click().run())
        assert '[FAIL] /api/tags unreachable: refused' in texts(at)
        at = ok(at.button(key='ai_analyze').click().run())
        assert 'Ollama request timed out: read timed out' in texts(at)


# ============================================================================
# Deployment / setup
# ============================================================================

@pytest.mark.unit
class TestSetupWizard:

    def _run(self, step, role=ROLE_ADMIN, **conn):
        conn = {'host': 'db', 'port': 1521, 'service': 'PDB', 'username': 'HCC',
                'password': 'pw', **conn}
        return page('page_00_setup', 'show_deployment_page', role, db_id=None,
                    args="mode='setup'", setup_step=step, setup_conn=conn).run()

    def test_viewer_cannot_run_the_wizard(self, env):
        at = ok(self._run(0, role=ROLE_VIEWER))
        assert 'Initial setup requires the admin role' in texts(at)

    def test_welcome_then_connection(self, env):
        at = ok(page('page_00_setup', 'show_deployment_page', db_id=None,
                     args="mode='setup'").run())
        assert 'Welcome to HCC Compression Advisor' in texts(at)
        at = ok(button(at, 'Begin Setup').click().run())
        assert at.session_state['setup_step'] == 1

    def test_connection_form_moves_to_verify(self, env):
        at = ok(self._run(1))
        assert 'Central Database Connection' in texts(at)
        password, = [w for w in at.text_input if w.label == 'Password']
        password.input('secret')
        at = ok(button(at, 'Test Connection').click().run())
        assert at.session_state['setup_step'] == 2
        assert at.session_state['setup_conn']['password'] == 'secret'

    def test_connection_form_requires_every_field(self, env):
        at = ok(self._run(1, password=''))
        at = ok(button(at, 'Test Connection').click().run())
        assert 'All fields are required.' in texts(at)

    def test_verify_with_an_existing_schema(self, env):
        env.patch(page_00_setup, '_test_connection', lambda *a: (True, 'Oracle 23ai'))
        env.patch(page_00_setup, '_check_privileges',
                  lambda *a: (False, [('CREATE TABLE', True), ('CREATE VIEW', False)]))
        env.patch(page_00_setup, '_get_schema_state', lambda *a: schema_state())
        at = ok(self._run(2))
        body = texts(at)
        assert 'Connection successful: Oracle 23ai' in body
        assert '❌ CREATE VIEW' in body and 'Some privileges are missing' in body
        assert f'Existing schema detected: v{__version__}' in body

    def test_verify_connection_failure(self, env):
        env.patch(page_00_setup, '_test_connection', lambda *a: (False, 'ORA-12541: no listener'))
        at = ok(self._run(2))
        assert 'Connection failed: ORA-12541: no listener' in texts(at)

    def test_deploy_over_an_existing_schema_offers_skip(self, env):
        at = ok(self._run(3, schema_state=schema_state()))
        assert f'Existing schema v{__version__} detected' in texts(at)
        assert button(at, 'Drop existing and re-install').disabled
        at = ok(button(at, 'Skip (keep existing schema)').click().run())
        assert at.session_state['setup_step'] == 4

    def test_deploy_installs_the_schema(self, env):
        install = env.patch(page_00_setup, '_run_schema_install',
                            MagicMock(return_value=(120, 0, ['[OK] done'])))
        at = ok(self._run(3))
        assert '- Schema: `found`' in texts(at)
        at = ok(button(at, 'Install Schema').click().run())
        install.assert_called_once()
        assert at.session_state['setup_step'] == 4

    def test_deploy_reports_statement_errors(self, env):
        env.patch(page_00_setup, '_run_schema_install',
                  MagicMock(return_value=(100, 2, ['[ERROR] ORA-00955'])))
        at = ok(self._run(3))
        at = ok(button(at, 'Install Schema').click().run())
        assert 'Completed with 2 errors (100 successful)' in texts(at)

    def test_security_step(self, env):
        at = ok(self._run(4))
        assert 'Security Configuration' in texts(at)
        at = ok(button(at, 'Save Configuration').click().run())
        assert at.session_state['setup_step'] == 4           # empty password refused
        assert at.error

    def test_finish_summary_masks_secrets(self, env):
        at = ok(self._run(5, dashboard_password='Str0ng-Passw0rd!', encryption_key='k'))
        body = texts(at)
        assert '`CENTRAL_DB_PASSWORD` = `***`' in body and '`CENTRAL_DB_HOST` = `db`' in body

    def test_finish_without_a_password_goes_back(self, env):
        at = ok(self._run(5))
        at = ok(at.button(key='setup_finish_back_security').click().run())
        assert at.session_state['setup_step'] == 4


@pytest.mark.unit
class TestExistingInstallation:

    @pytest.fixture(autouse=True)
    def _installed(self, env):
        env.patch(page_00_setup.config, 'CENTRAL_DB_PASSWORD', 'central-secret')

    def _run(self, role=ROLE_ADMIN, **state):
        return page('page_00_setup', 'show_deployment_page', role, db_id=None,
                    args="mode='upgrade'", **state).run()

    def test_viewer_may_only_continue(self, env):
        at = ok(self._run(ROLE_VIEWER))
        assert 'Ask an administrator to upgrade the schema.' in texts(at)
        at = ok(at.button(key='setup_continue_non_admin').click().run())
        assert at.session_state['setup_complete'] is True

    @pytest.mark.parametrize('state, message', [
        (schema_state(), 'Schema is up to date.'),
        (schema_state(deployed=False, version=None, tables_found=0),
         'No HCC schema tables found.'),
        (schema_state(deployed=False, version=None, tables_found=3),
         'predate schema 2.0.0'),
    ])
    def test_status(self, env, state, message):
        env.patch(page_00_setup, '_get_schema_state', lambda *a: state)
        at = ok(self._run())
        assert message in texts(at)

    def test_unreachable_central_database(self, env):
        env.patch(page_00_setup, '_get_schema_state', lambda *a: schema_state(connected=False))
        at = ok(self._run())
        assert 'Central DB: connection failed' in texts(at)

    def test_upgrade_applies_pending_patches(self, env):
        env.patch(page_00_setup, '_get_schema_state', lambda *a: schema_state(version='2.0.0'))
        env.patch(page_00_setup, '_get_pending_patches', lambda *a: (['20260924-x'], None))
        result = SimpleNamespace(name='20260924-x', status=page_00_setup.sql_patches.PATCH_APPLIED,
                                 statements=3, error=None)
        upgrade = env.patch(page_00_setup, '_run_upgrade', MagicMock(
            return_value=(SimpleNamespace(results=[result], failed=None), True)))
        at = ok(self._run())
        at = ok(button(at, 'Upgrade (keeps data)').click().run())
        assert '**1 pending patch(es):** `20260924-x`' in texts(at)
        at = ok(button(at, 'Apply Upgrade').click().run())
        upgrade.assert_called_once()
        body = texts(at)
        assert '[OK] 20260924-x (3 statements)' in body
        assert 'Upgrade complete: 1 patch(es) applied' in body

    def test_upgrade_stops_at_a_failed_patch(self, env):
        env.patch(page_00_setup, '_get_schema_state', lambda *a: schema_state(version='2.0.0'))
        env.patch(page_00_setup, '_get_pending_patches', lambda *a: ([], None))
        failed = SimpleNamespace(name='p1', status='FAILED', statements=0, error='ORA-00942')
        env.patch(page_00_setup, '_run_upgrade', MagicMock(
            return_value=(SimpleNamespace(results=[failed], failed=failed), False)))
        at = ok(self._run(setup_action='upgrade'))
        assert 'No pending patches' in texts(at)
        at = ok(button(at, 'Apply Upgrade').click().run())
        body = texts(at)
        assert '[FAILED] p1: ORA-00942' in body and 'Patch `p1` failed.' in body

    def test_upgrade_cannot_read_the_patches(self, env):
        env.patch(page_00_setup, '_get_schema_state', lambda *a: schema_state(version='2.0.0'))
        env.patch(page_00_setup, '_get_pending_patches', lambda *a: (None, 'no patches dir'))
        at = ok(self._run(setup_action='upgrade'))
        assert 'Cannot upgrade: no patches dir' in texts(at)

    @pytest.mark.parametrize('action, label', [('reinstall', 'Confirm Re-install'),
                                               ('cleanup', 'Confirm Cleanup')])
    def test_destructive_actions_wait_for_the_phrase(self, env, action, label):
        drop = env.patch(page_00_setup, '_drop_all_hcc_objects', MagicMock(return_value=[]))
        env.patch(page_00_setup, '_get_schema_state', lambda *a: schema_state())
        at = ok(self._run(setup_action=action))
        assert button(at, label).disabled
        drop.assert_not_called()

    def test_reinstall_after_the_phrase(self, env):
        env.patch(page_00_setup, '_get_schema_state', lambda *a: schema_state())
        drop = env.patch(page_00_setup, '_drop_all_hcc_objects',
                         MagicMock(return_value=['Dropped table T_COMPRESSION_HISTORY']))
        install = env.patch(page_00_setup, '_run_schema_install',
                            MagicMock(return_value=(50, 0, ['[OK] created'])))
        at = ok(self._run(setup_action='reinstall'))
        at.text_input(key='setup_reinstall_confirm').input('REINSTALL')
        at = ok(button(at, 'Confirm Re-install').click().run())
        drop.assert_called_once()
        install.assert_called_once()
        assert 'Schema re-installed successfully (50 statements executed)' in texts(at)


# ============================================================================
# Compression Wizard: "no targets" step only
# ============================================================================

@pytest.mark.unit
class TestWizardPage:

    @pytest.mark.parametrize('role', ROLES)
    def test_no_targets(self, env, role):
        env.targets = pd.DataFrame()
        at = ok(page('page_14_wizard', 'show_wizard_page', role, db_id=None).run())
        assert 'Compression Wizard' in texts(at)
