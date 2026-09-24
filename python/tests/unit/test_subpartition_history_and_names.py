"""
Unit tests for two follow-ups of subpartition support and duplicate names:

- analysis rows take their execution status, savings, growth and
  permanent-failure exclusion from the T_COMPRESSION_HISTORY rows of exactly
  their own segment (database, owner, table, partition, subpartition), so
  compressing one subpartition no longer marks its siblings "Compressed" or
  hides them (get_recommendations, get_compression_progress,
  get_forecast_data, get_growth_alerts; the Quick Action status overlay and the
  AI advisor context built on them). Legacy rows that recorded a subpartition
  job under its parent partition (no SUBPARTITION_NAME) count for that
  partition's own row only. The History page and the Scheduler monitor show
  the subpartition, so sibling rows can be told apart;
- target pickers other than the sidebar (Wizard, Scheduler export / import)
  key on DATABASE_ID with target_selector_labels, and the migration CLI
  refuses a display name another active target uses.

The history queries run for real on SQLite (window functions, NVL registered
as a function), like test_leaf_segments runs the leaf-segment view.
"""
import argparse
import re
import sqlite3
from contextlib import contextmanager
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest
from streamlit.testing.v1 import AppTest
from streamlit.testing.v1.element_tree import Selectbox

from hcc_advisor.utils import migration
from hcc_advisor.utils.central_connector import CentralConnector
from hcc_advisor.utils.central_queries import CentralQueries
from hcc_advisor.utils.target_queries import TargetQueries
from hcc_advisor.views import page_08_quick_scan, page_12_scheduler, page_13_ai_advisor
from tests.unit.app_harness import _selectbox_index

TIMEOUT = 15  # seconds per AppTest run
MB = 1024 * 1024
T1, T2, T3 = '2026-09-01 10:00:00', '2026-09-02 10:00:00', '2026-09-03 10:00:00'


# ============================================================================
# A central database on SQLite
# ============================================================================

ANALYSIS_COLUMNS = [
    'analysis_id', 'database_id', 'owner', 'object_name', 'object_type', 'partition_name',
    'subpartition_name', 'original_size_bytes', 'size_bytes', 'size_mb', 'row_count',
    'current_compression', 'advisable_compression', 'projected_savings_mb',
    'projected_savings_pct', 'projected_savings_bytes', 'best_ratio', 'basic_ratio',
    'oltp_ratio', 'adv_low_ratio', 'adv_high_ratio', 'hotness_score', 'hotness_category',
    'recommendation_reason', 'analysis_timestamp',
]
HISTORY_COLUMNS = [
    'history_id', 'database_id', 'owner', 'object_name', 'object_type', 'partition_name',
    'subpartition_name', 'operation_status', 'start_time', 'error_message',
    'original_size_bytes', 'compressed_size_bytes', 'original_size_mb', 'compressed_size_mb',
    'duration_seconds',
]
PERMANENT = 'ORA-14808: table does not support ONLINE MOVE'
LEGACY_14257 = 'ORA-14257: cannot move partition other than a Range, List, System, or Hash partition'


class SqliteCentral:
    """CentralConnector.execute_query on an in-memory SQLite database holding
    T_COMPRESSION_ANALYSIS and T_COMPRESSION_HISTORY. Column names come back
    upper-case like Oracle's; SQL errors are recorded and re-raised."""

    def __init__(self):
        self.con = sqlite3.connect(':memory:', check_same_thread=False)
        self.con.create_function('NVL', 2, lambda value, default: default if value is None else value)
        self.con.execute(f"CREATE TABLE t_compression_analysis ({', '.join(ANALYSIS_COLUMNS)})")
        self.con.execute(f"CREATE TABLE t_compression_history ({', '.join(HISTORY_COLUMNS)})")
        self.statements, self.errors = [], []

    def analysis(self, obj, otype, part=None, sub=None, size_mb=100.0, db=1, rec='OLTP'):
        n = self.con.execute("SELECT COUNT(*) FROM t_compression_analysis").fetchone()[0] + 1
        row = dict(analysis_id=n, database_id=db, owner='APP', object_name=obj,
                   object_type=otype, partition_name=part, subpartition_name=sub,
                   original_size_bytes=size_mb * MB, size_bytes=size_mb * MB, size_mb=size_mb,
                   row_count=1000, current_compression='NONE', advisable_compression=rec,
                   projected_savings_mb=size_mb / 2, projected_savings_pct=50.0,
                   projected_savings_bytes=size_mb / 2 * MB, best_ratio=2.0, basic_ratio=1.5,
                   oltp_ratio=2.0, adv_low_ratio=None, adv_high_ratio=None, hotness_score=10.0,
                   hotness_category='COLD', recommendation_reason='test', analysis_timestamp=T1)
        self._insert('t_compression_analysis', ANALYSIS_COLUMNS, row)

    def history(self, obj, status, part=None, sub=None, start=T1, error=None,
                compressed_mb=None, db=1, otype=None, original_mb=100.0):
        n = self.con.execute("SELECT COUNT(*) FROM t_compression_history").fetchone()[0] + 1
        otype = otype or ('SUBPARTITION' if sub else 'PARTITION' if part else 'TABLE')
        row = dict(history_id=n, database_id=db, owner='APP', object_name=obj, object_type=otype,
                   partition_name=part, subpartition_name=sub, operation_status=status,
                   start_time=start, error_message=error, original_size_bytes=original_mb * MB,
                   compressed_size_bytes=compressed_mb * MB if compressed_mb else None,
                   original_size_mb=original_mb, compressed_size_mb=compressed_mb,
                   duration_seconds=60)
        self._insert('t_compression_history', HISTORY_COLUMNS, row)
        return n

    def _insert(self, table, columns, row):
        self.con.execute(f"INSERT INTO {table} VALUES ({', '.join('?' * len(columns))})",
                         [row[c] for c in columns])

    def query(self, sql, params=None, raise_on_error=False, **kw):
        self.statements.append((sql, params))
        try:
            cur = self.con.execute(sql, params or {})
        except sqlite3.Error as e:
            self.errors.append((str(e), sql))
            raise
        return pd.DataFrame(cur.fetchall(), columns=[d[0].upper() for d in cur.description])


def _estate(central):
    """Every shape of history an analysed segment can meet (database 1)."""
    a, h = central.analysis, central.history
    # Composite table, analysed per subpartition. P1_S1 compressed (T2); its
    # sibling P1_S2 failed earlier (T1) with a retryable error; P2_S1 failed
    # permanently; P2_S2 has no history.
    a('COMP_T', 'TABLE', size_mb=400.0)
    a('COMP_T', 'SUBPARTITION', 'P1', 'P1_S1')
    a('COMP_T', 'SUBPARTITION', 'P1', 'P1_S2')
    a('COMP_T', 'SUBPARTITION', 'P2', 'P2_S1')
    a('COMP_T', 'SUBPARTITION', 'P2', 'P2_S2')
    h('COMP_T', 'SUCCESS', 'P1', 'P1_S1', start=T2, compressed_mb=50.0)
    h('COMP_T', 'FAILED', 'P1', 'P1_S2', start=T1, error='ORA-01652: unable to extend temp segment')
    h('COMP_T', 'FAILED', 'P2', 'P2_S1', error=PERMANENT)
    # Range-partitioned table: P1 compressed; the TABLE row has no history of its own
    a('RANGE_T', 'TABLE', size_mb=200.0)
    a('RANGE_T', 'PARTITION', 'P1')
    a('RANGE_T', 'PARTITION', 'P2')
    h('RANGE_T', 'SUCCESS', 'P1', compressed_mb=100.0)
    # Not partitioned: table-level history
    a('PLAIN_T', 'TABLE', size_mb=50.0)
    h('PLAIN_T', 'SUCCESS', compressed_mb=50.0, original_mb=50.0)
    # Table-level history does not mark the table's partitions compressed
    a('MIXED_T', 'TABLE')
    a('MIXED_T', 'PARTITION', 'P1')
    h('MIXED_T', 'SUCCESS')
    # Legacy rows: a subpartition job recorded under its parent partition (no
    # SUBPARTITION_NAME) that ran MOVE PARTITION on the composite parent
    a('LEGACY_T', 'PARTITION', 'P1')                  # pre-cleanup partition row
    a('LEGACY_T', 'SUBPARTITION', 'P1', 'P1_S1')
    a('LEGACY_T', 'SUBPARTITION', 'P1', 'P1_S2')
    h('LEGACY_T', 'FAILED', 'P1', error=LEGACY_14257)
    a('LEGACY_OK_T', 'SUBPARTITION', 'P1', 'P1_S1')
    a('LEGACY_OK_T', 'SUBPARTITION', 'P1', 'P1_S2')
    h('LEGACY_OK_T', 'SUCCESS', 'P1', compressed_mb=10.0)
    # Database 2: same table, its sibling compressed there
    a('COMP_T', 'SUBPARTITION', 'P1', 'P1_S2', db=2)
    h('COMP_T', 'SUCCESS', 'P1', 'P1_S2', start=T3, compressed_mb=50.0, db=2)


# (object, partition, subpartition) -> execution_status in database 1; rows
# missing from the dict are excluded from the list (permanent failure).
EXPECTED_STATUS = {
    ('COMP_T', None, None): 'Pending',
    ('COMP_T', 'P1', 'P1_S1'): 'Compressed',
    ('COMP_T', 'P1', 'P1_S2'): 'FAILED',      # its own latest row, not its sibling's SUCCESS
    ('COMP_T', 'P2', 'P2_S2'): 'Pending',     # its sibling's permanent failure does not hide it
    ('RANGE_T', None, None): 'Pending',       # the TABLE row is not matched by partition history
    ('RANGE_T', 'P1', None): 'Compressed',
    ('RANGE_T', 'P2', None): 'Pending',
    ('PLAIN_T', None, None): 'Compressed',
    ('MIXED_T', None, None): 'Compressed',
    ('MIXED_T', 'P1', None): 'Pending',       # nor a partition row by table history
    ('LEGACY_T', 'P1', 'P1_S1'): 'Pending',   # the legacy ORA-14257 hides the partition row only
    ('LEGACY_T', 'P1', 'P1_S2'): 'Pending',
    ('LEGACY_OK_T', 'P1', 'P1_S1'): 'Pending',  # a legacy partition row is not theirs
    ('LEGACY_OK_T', 'P1', 'P1_S2'): 'Pending',
}


@pytest.fixture
def central(monkeypatch):
    db = SqliteCentral()
    _estate(db)
    monkeypatch.setattr(CentralConnector, 'execute_query', db.query)
    return db


def _none(value):
    return None if value is None or (isinstance(value, float) and pd.isna(value)) else value


def _statuses(df, database_id=1):
    return {(r['TABLE_NAME'], _none(r['PARTITION_NAME']), _none(r['SUBPARTITION_NAME'])):
            r['EXECUTION_STATUS'] for _, r in df.iterrows() if r['DATABASE_ID'] == database_id}


def _recommendations(**kwargs):
    args = dict(database_id=1, limit=None, min_savings_pct=0, show_executed=True)
    args.update(kwargs)
    return CentralQueries.get_recommendations(**args)


# ============================================================================
# 1. The queries, run on SQLite
# ============================================================================

@pytest.mark.unit
class TestRecommendationStatus:

    def test_each_row_has_the_status_of_its_own_segment(self, central):
        df = _recommendations()
        assert not central.errors
        assert _statuses(df) == EXPECTED_STATUS

    def test_hide_executed_hides_only_the_compressed_segments(self, central):
        df = _recommendations(show_executed=False)
        assert not central.errors
        assert _statuses(df) == {k: v for k, v in EXPECTED_STATUS.items() if v != 'Compressed'}
        assert ('COMP_T', 'P1', 'P1_S2') in _statuses(df)

    def test_other_database_history_does_not_match(self, central):
        df = _recommendations(database_id=None)
        assert not central.errors
        assert _statuses(df, 1) == EXPECTED_STATUS
        assert _statuses(df, 2) == {('COMP_T', 'P1', 'P1_S2'): 'Compressed'}

    def test_quick_action_candidates_skip_only_compressed_segments(self, central):
        items = page_08_quick_scan.pending_leaf_candidates(None, 1, 4)
        assert not central.errors
        got = {(i['table_name'], i['partition_name'], i['subpartition_name']) for i in items}
        assert got == {
            ('COMP_T', 'P1', 'P1_S2'), ('COMP_T', 'P2', 'P2_S2'),
            ('RANGE_T', 'P2', None), ('MIXED_T', 'P1', None),
            ('LEGACY_T', 'P1', 'P1_S1'), ('LEGACY_T', 'P1', 'P1_S2'),
            ('LEGACY_OK_T', 'P1', 'P1_S1'), ('LEGACY_OK_T', 'P1', 'P1_S2'),
        }


@pytest.mark.unit
class TestAggregatesPerSegment:
    """Leaf segments of database 1: COMP_T's 4 subpartitions, RANGE_T's 2
    partitions, PLAIN_T, MIXED_T's partition, 2 + 2 legacy subpartitions."""

    def test_progress_counts_each_leaf_by_its_own_history(self, central):
        p = CentralQueries.get_compression_progress(database_id=1)
        assert not central.errors
        # compressed: COMP_T P1_S1, RANGE_T P1, PLAIN_T (a partition-level
        # match counted P1_S2 and both LEGACY_OK_T subpartitions as well)
        assert (p['total'], p['compressed'], p['pending'], p['skipped']) == (12, 3, 9, 0)
        # saved: P1_S1's own row (100 -> 50 MB) once; RANGE_T/PLAIN_T saved nothing
        assert p['saved_mb'] == pytest.approx(50.0)

    def test_forecast_pending_are_the_not_compressed_leaves(self, central):
        f = CentralQueries.get_forecast_data(database_id=1)
        assert not central.errors
        assert f['pending_count'] == 9
        assert f['pending_current_mb'] == pytest.approx(900.0)

    def test_growth_alert_only_for_the_compressed_subpartition(self, central):
        df = CentralQueries.get_growth_alerts(database_id=1)
        assert not central.errors
        rows = [(r['OBJECT_NAME'], r['PARTITION_NAME'], r['SUBPARTITION_NAME'], r['GROWTH_PCT'])
                for _, r in df.iterrows()]
        # P1_S1 is back at 100 MB after compressing to 50 MB; P1_S2 and the
        # LEGACY_OK_T subpartitions have no compression of their own
        assert rows == [('COMP_T', 'P1', 'P1_S1', 100.0)]


# ============================================================================
# 2. The SQL each query sends
# ============================================================================

def _norm(sql):
    return " ".join(sql.split())


SEGMENT_WINDOW = re.compile(
    r"PARTITION BY (h2\.)?database_id, (h2\.)?owner, (h2\.)?object_name, "
    r"NVL\((h2\.)?partition_name, '~'\), NVL\((h2\.)?subpartition_name, '~'\)")
SEGMENT_JOIN = re.compile(
    r"= NVL\(a\.partition_name, '~'\) AND h\.(h_)?sn = NVL\(a\.subpartition_name, '~'\)"
    r" AND h\.rn = 1")


@pytest.fixture
def captured(monkeypatch):
    calls = []

    def fake(query, params=None, **kw):
        calls.append(_norm(query))
        return pd.DataFrame()

    monkeypatch.setattr(CentralConnector, 'execute_query', fake)
    return calls


@pytest.mark.unit
class TestHistoryJoinSql:

    @pytest.mark.parametrize('method,kwargs', [
        ('get_recommendations', {'database_id': 1}),
        ('get_recommendations', {}),
        ('get_compression_progress', {'database_id': 1}),
        ('get_forecast_data', {}),
        ('get_growth_alerts', {'database_id': 1}),
    ])
    def test_latest_history_row_per_exact_segment(self, captured, method, kwargs):
        getattr(CentralQueries, method)(**kwargs)
        sql = captured[0]
        assert 'FROM t_compression_history' in sql
        assert SEGMENT_WINDOW.search(sql), sql
        assert SEGMENT_JOIN.search(sql), sql

    def test_permanent_failures_match_the_exact_segment(self, captured):
        CentralQueries.get_recommendations(database_id=1)
        sql = captured[0]
        assert ("NVL(pf.partition_name, '~') = NVL(a.partition_name, '~') "
                "AND NVL(pf.subpartition_name, '~') = NVL(a.subpartition_name, '~')") in sql

    def test_growth_alerts_name_the_segment(self, captured):
        CentralQueries.get_growth_alerts()
        assert 'SELECT a.owner, a.object_name, a.object_type, a.partition_name, ' \
               'a.subpartition_name,' in captured[0]

    def test_scheduler_monitor_rows_name_the_subpartition(self, captured):
        CentralQueries.get_scheduler_job_details(database_id=1)
        assert 'h.object_type, h.partition_name, h.subpartition_name,' in captured[0]


# ============================================================================
# 3. Pages built on the history status
# ============================================================================

def _quick_scan_page():
    from hcc_advisor.views.page_08_quick_scan import show_quick_scan_page
    show_quick_scan_page()


@pytest.mark.unit
class TestQuickActionOverlay:

    def test_running_subpartition_does_not_mark_its_sibling(self, central):
        central.history('LEGACY_OK_T', 'IN_PROGRESS', 'P1', 'P1_S1', start=T3)
        scan_tab = MagicMock()
        with patch.object(TargetQueries, 'get_available_schemas', return_value=[]), \
                patch.object(TargetQueries, 'get_cpu_count', return_value=8), \
                patch.object(TargetQueries, 'get_running_compression_jobs',
                             return_value=pd.DataFrame()), \
                patch.object(page_08_quick_scan, '_render_scan_tab', scan_tab), \
                patch.object(page_08_quick_scan, '_render_export_section', MagicMock()), \
                patch.object(page_08_quick_scan, '_render_schemas_tab', MagicMock()):
            at = AppTest.from_function(_quick_scan_page, default_timeout=TIMEOUT)
            at.session_state['authenticated'] = True
            at.session_state['role'] = 'operator'
            at.session_state['active_database_id'] = 1
            at.run()
        assert not at.exception and not central.errors
        subs = next(c.args[0] for c in scan_tab.call_args_list if c.args[1] == 'SUBPARTITION')
        status = {(r['table_name'], r['subpartition_name']): r['status'] for _, r in subs.iterrows()}
        assert status[('LEGACY_OK_T', 'P1_S1')] == 'Running'
        assert status[('LEGACY_OK_T', 'P1_S2')] == 'Pending'
        assert status[('COMP_T', 'P1_S1')] == 'Compressed'
        assert status[('COMP_T', 'P1_S2')] == 'FAILED'


def _history_page():
    from hcc_advisor.views.page_04_history import show_history_page
    show_history_page()


@pytest.mark.unit
class TestHistoryPageSegments:

    def test_sibling_subpartition_rows_are_told_apart(self):
        history = pd.DataFrame([{
            'EXECUTION_ID': n, 'DATABASE_ID': 1, 'TABLE_OWNER': 'APP', 'TABLE_NAME': 'COMP_T',
            'PARTITION_NAME': 'P1', 'SUBPARTITION_NAME': sub, 'OBJECT_TYPE': 'SUBPARTITION',
            'STRATEGY': 'OLTP', 'STATUS': status, 'ROLLBACK_STATUS': None, 'SAVINGS_PCT': 50.0,
            'ERROR_MESSAGE': None, 'EXECUTED_AT': pd.Timestamp('2026-09-01'),
        } for n, sub, status in ((1, 'P1_S1', 'SUCCESS'), (2, 'P1_S2', 'FAILED'))])
        with patch.object(Selectbox, 'index', property(_selectbox_index)), \
                patch.object(CentralQueries, 'get_execution_history',
                             side_effect=lambda **k: history.copy()):
            at = AppTest.from_function(_history_page, default_timeout=TIMEOUT)
            at.session_state['authenticated'] = True
            at.session_state['role'] = 'operator'
            at.session_state['active_database_id'] = 1
            at.run()
        assert not at.exception
        details = next(d.value for d in at.dataframe if 'Subpartition' in d.value.columns)
        assert list(zip(details['Partition'], details['Subpartition'], details['Status'])) == \
            [('P1', 'P1_S1', 'SUCCESS'), ('P1', 'P1_S2', 'FAILED')]


@pytest.mark.unit
class TestAiAdvisorSegments:

    def test_failures_and_growth_name_the_segment(self):
        context = {
            'failures': [
                {'table_owner': 'APP', 'table_name': 'COMP_T', 'partition_name': 'P1',
                 'subpartition_name': 'P1_S2', 'error_message': 'ORA-01652'},
                {'table_owner': 'APP', 'table_name': 'PLAIN_T', 'partition_name': None,
                 'subpartition_name': float('nan'), 'error_message': 'ORA-00054'},
            ],
            'growth_alerts': [
                {'owner': 'APP', 'object_name': 'COMP_T', 'partition_name': 'P1',
                 'subpartition_name': 'P1_S1', 'compressed_mb': 50.0, 'current_mb': 100.0,
                 'growth_pct': 100.0},
            ],
        }
        prompt = page_13_ai_advisor._build_prompt(context, 'Full Estate')
        assert '- APP.COMP_T [P1.P1_S2]: ORA-01652' in prompt
        assert '- APP.PLAIN_T: ORA-00054' in prompt
        assert '- APP.COMP_T [P1.P1_S1]: was 50.0 MB, now 100.0 MB (+100.0%)' in prompt


# ============================================================================
# 4. Target pickers keyed on DATABASE_ID
# ============================================================================

DUP_TARGETS = pd.DataFrame(
    [(1, 'prod-01', 'Prod', 'h1', 'S1'), (2, 'prod-02', 'prod', 'h2', 'S2'),
     (3, 'dev-01', 'Dev', 'h3', 'S3')],
    columns=['DATABASE_ID', 'DATABASE_NAME', 'DISPLAY_NAME', 'DB_HOST', 'SERVICE_NAME'])
LABELS = ['Prod (h1/S1)', 'prod (h2/S2)', 'Dev']


@contextmanager
def _picker_app(func, **state):
    """AppTest of func with DUP_TARGETS registered. Selectbox.index is patched:
    AppTest 1.31 can't send an untouched format_func'd selectbox back (see
    app_harness._selectbox_index)."""
    with patch.object(Selectbox, 'index', property(_selectbox_index)), \
            patch.object(CentralQueries, 'get_target_databases',
                         side_effect=lambda: DUP_TARGETS.copy()):
        at = AppTest.from_function(func, default_timeout=TIMEOUT)
        at.session_state['authenticated'] = True
        at.session_state['role'] = 'operator'
        for key, value in state.items():
            at.session_state[key] = value
        yield at


def _wizard_step1():
    from hcc_advisor.views.page_14_wizard import _step_select_database
    _step_select_database()


@contextmanager
def _wizard(**state):
    info = MagicMock(side_effect=lambda did: {'db_host': f'h{did}', 'platform_type': 'STANDARD'})
    with _picker_app(_wizard_step1, **state) as at, \
            patch.object(CentralQueries, 'get_target_database', info), \
            patch.object(TargetQueries, 'get_cpu_count', return_value=8):
        yield at.run(), info


@pytest.mark.unit
class TestWizardTargetPicker:

    def test_every_target_is_an_option_keyed_by_id(self):
        with _wizard() as (at, info):
            assert not at.exception
            sel = at.selectbox(key='wiz_db_select')
            assert sel.options == LABELS
            assert sel.value == 1
            assert at.session_state['wizard_db_id'] == 1
            info.assert_called_with(1)

    def test_selecting_a_duplicate_name_picks_its_own_target(self):
        with _wizard() as (at, info):
            at.selectbox(key='wiz_db_select').select_index(1).run()
            assert not at.exception
            assert at.session_state['wizard_db_id'] == 2
            info.assert_called_with(2)
            at.run()                                   # and it sticks
            assert at.session_state['wizard_db_id'] == 2

    def test_back_to_step_one_keeps_the_chosen_target(self):
        with _wizard(wizard_db_id=2) as (at, _info):
            assert at.selectbox(key='wiz_db_select').value == 2
            assert at.session_state['wizard_db_id'] == 2

    def test_no_targets(self):
        with patch.object(CentralQueries, 'get_target_databases', return_value=pd.DataFrame()):
            at = AppTest.from_function(_wizard_step1, default_timeout=TIMEOUT).run()
        assert not at.exception
        assert 'No target databases registered' in at.warning[0].value


def _export_section():
    import streamlit as st
    from hcc_advisor.views.page_12_scheduler import _render_export_section
    _render_export_section(st.session_state.get('active_database_id'))


def _import_section():
    import streamlit as st
    from hcc_advisor.views.page_12_scheduler import _render_import_section
    _render_import_section(st.session_state.get('active_database_id'))


EXPORT_ROWS = pd.DataFrame([{
    'DATABASE_ID': 2, 'OWNER': 'APP', 'OBJECT_NAME': 'COMP_T', 'OBJECT_TYPE': 'SUBPARTITION',
    'PARTITION_NAME': 'P1', 'SUBPARTITION_NAME': 'P1_S1', 'COMPRESSION_TYPE_APPLIED': 'OLTP',
    'PARALLEL_DEGREE': 4, 'OPERATION_STATUS': 'QUEUED'}])


@pytest.mark.unit
class TestSchedulerTargetPickers:

    def test_export_filter_keyed_by_id(self):
        jobs = MagicMock(return_value=EXPORT_ROWS.copy())
        script = MagicMock(return_value='-- script')
        download = MagicMock()
        with _picker_app(_export_section, active_database_id=2) as at, \
                patch.object(CentralQueries, 'get_scheduler_jobs_for_export', jobs), \
                patch.object(page_12_scheduler, 'gather_target_info', MagicMock(return_value={})), \
                patch.object(page_12_scheduler, 'gather_dependent_indexes',
                             MagicMock(return_value={})), \
                patch.object(page_12_scheduler, 'build_compression_script', script), \
                patch.object(page_12_scheduler.st, 'download_button', download):
            at.run()
            assert not at.exception
            sel = at.selectbox(key='export_db')
            assert sel.options == ['All Databases'] + LABELS
            assert sel.value == 2                      # the active target, not its namesake
            assert jobs.call_args.kwargs['database_id'] == 2
            assert script.call_args.args[2] == 'prod (h2/S2)'
            assert download.call_args.kwargs['file_name'] == 'hcc_export_prod_h2_s2_all.sql'

            sel.select_index(1).run()
            assert jobs.call_args.kwargs['database_id'] == 1
            at.selectbox(key='export_db').select_index(0).run()
            assert jobs.call_args.kwargs['database_id'] is None
            assert download.call_args.kwargs['file_name'] == 'hcc_export_all_databases_all.sql'

    def test_import_target_keyed_by_id(self):
        with _picker_app(_import_section, active_database_id=2) as at:
            at.run()
            assert not at.exception
            sel = at.selectbox(key='import_target_db')
            assert sel.options == LABELS
            assert sel.value == 2
            sel.select_index(0).run()
            assert not at.exception
            assert at.selectbox(key='import_target_db').value == 1

    def test_import_without_targets(self):
        with patch.object(CentralQueries, 'get_target_databases', return_value=pd.DataFrame()):
            at = AppTest.from_function(_import_section, default_timeout=TIMEOUT).run()
        assert not at.exception
        assert 'No target databases registered' in at.info[0].value


# ============================================================================
# 5. Migration CLI: display names
# ============================================================================

@pytest.mark.unit
class TestMigrationDisplayName:

    @pytest.fixture(autouse=True)
    def _key(self, monkeypatch):
        from cryptography.fernet import Fernet
        monkeypatch.setattr(migration.config, 'ENCRYPTION_KEY', Fernet.generate_key().decode())

    @staticmethod
    def _args(**overrides):
        values = dict(host='dbhost', port=1521, service='FREEPDB1', username='HCC',
                      password='pw', name='Prod DB', description=None,
                      environment='PRODUCTION', platform='STANDARD', mode='NORMAL',
                      dry_run=False)
        values.update(overrides)
        return argparse.Namespace(**values)

    @staticmethod
    def _central(registry):
        central = MagicMock()
        cur = central.cursor.return_value
        cur.fetchall.return_value = registry
        cur.fetchone.side_effect = [(1,), (11,)]      # CONNECTION_MODE exists; new id
        return central, cur

    @staticmethod
    def _sql(cur):
        return [c.args[0] for c in cur.execute.call_args_list]

    @pytest.mark.parametrize('dry_run', [False, True])
    @pytest.mark.parametrize('name', ['Prod DB', 'prod db', ' PROD DB '])
    def test_name_in_use_is_refused_before_any_write(self, name, dry_run):
        central, cur = self._central([(5, 'PROD_01', 'Prod DB'), (6, 'DEV_01', 'Dev')])
        with pytest.raises(RuntimeError) as err:
            migration.register_target_database(central, self._args(name=name), dry_run=dry_run)
        msg = str(err.value)
        assert "already used by target 'Prod DB' (PROD_01, ID 5)" in msg
        assert '--name' in msg
        sql = self._sql(cur)
        assert len(sql) == 1 and "is_active = 'Y'" in sql[0]    # only the registry read
        assert 'display_name' in sql[0]

    def test_shared_rule(self):
        from hcc_advisor.utils.target_names import display_name_conflict
        registry = pd.DataFrame([(5, 'PROD_01', 'Prod DB'), (None, None, 'Dev')],
                                columns=['database_id', 'database_name', 'display_name'])
        assert display_name_conflict('  ', registry) is None
        assert display_name_conflict('PROD DB', registry, exclude_database_id=5) is None
        assert "'Dev' (ID None)" in display_name_conflict('dev', registry)

    def test_new_name_is_registered(self):
        central, cur = self._central([(5, 'PROD_01', 'Prod DB')])
        assert migration.register_target_database(central, self._args(name='QA'),
                                                  dry_run=False) == 11
        insert = next(s for s in self._sql(cur) if 'INSERT INTO t_target_databases' in s)
        params = next(c.args[1] for c in cur.execute.call_args_list if c.args[0] == insert)
        assert params['display_name'] == 'QA'

    def test_cli_fails_with_the_message_and_writes_nothing(self, monkeypatch, capsys):
        central, cur = self._central([(5, 'PROD_01', 'Prod DB')])
        target = MagicMock()
        monkeypatch.setattr(migration, 'get_central_connection', lambda: central)
        monkeypatch.setattr(migration, 'get_target_connection', lambda args: target)
        monkeypatch.setattr(migration, 'test_connection', lambda conn, label: True)
        monkeypatch.setattr('sys.argv', ['migration', '--host', 'dbhost', '--service', 'S',
                                         '--username', 'HCC', '--password', 'pw',
                                         '--name', 'PROD DB'])
        assert migration.main() == 1
        out = capsys.readouterr().out
        assert "[FATAL] Registration failed: The display name 'PROD DB' is already used by " \
               "target 'Prod DB' (PROD_01, ID 5)." in out
        assert not any('INSERT' in s for s in self._sql(cur))
        central.rollback.assert_called_once()
        central.commit.assert_not_called()
