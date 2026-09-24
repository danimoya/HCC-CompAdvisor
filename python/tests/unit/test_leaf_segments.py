"""
Unit tests for the leaf-segment rule (utils/leaf_segments.py): a table analysed
with its partitions must count once — through its partition (or subpartition)
rows, or through its TABLE row when a later table-only analysis refreshed it —
in every total. Covers the in-memory helper, the SQL view (run for real on
SQLite), the SQL each CentralQueries aggregate sends, and the run totals written
by TargetQueries._complete_advisor_run.
"""
import sqlite3
from datetime import datetime

import numpy as np
import pandas as pd
import pytest

from hcc_advisor.utils.central_connector import CentralConnector
from hcc_advisor.utils.central_queries import CentralQueries
from hcc_advisor.utils.leaf_segments import leaf_analysis_sql, leaf_segment_mask, leaf_segments
from hcc_advisor.utils.target_queries import TargetQueries

MB = 1024 * 1024
T1, T2, T3 = datetime(2026, 9, 1, 10), datetime(2026, 9, 2, 10), datetime(2026, 9, 3, 10)


def _row(db, obj, otype, part=None, sub=None, size_mb=0, savings_mb=0, rec='NONE', ts=T1):
    return {
        'DATABASE_ID': db, 'OWNER': 'APP', 'OBJECT_NAME': obj, 'OBJECT_TYPE': otype,
        'PARTITION_NAME': part, 'SUBPARTITION_NAME': sub,
        'SIZE_BYTES': size_mb * MB, 'PROJECTED_SAVINGS_BYTES': savings_mb * MB,
        'ADVISABLE_COMPRESSION': rec, 'ANALYSIS_TIMESTAMP': ts,
    }


# (row, is_leaf) — every shape start_analysis / quick_scan / older scans leave
# in T_COMPRESSION_ANALYSIS (one row per segment, possibly from different runs)
MIXED = [
    (_row(1, 'PLAIN', 'TABLE', size_mb=10), True),                    # not partitioned
    (_row(1, 'RANGE_T', 'TABLE', size_mb=100), False),                # run with partitions
    (_row(1, 'RANGE_T', 'PARTITION', 'P1', size_mb=60), True),
    (_row(1, 'RANGE_T', 'PARTITION', 'P2', size_mb=40), True),
    (_row(1, 'COMP_T', 'TABLE', size_mb=80), False),                  # composite: only
    (_row(1, 'COMP_T', 'SUBPARTITION', 'P1', 'P1_S1', size_mb=50), True),  # subpartition rows
    (_row(1, 'COMP_T', 'SUBPARTITION', 'P1', 'P1_S2', size_mb=30), True),
    (_row(1, 'LEGACY_T', 'TABLE', size_mb=70), False),                # pre-cleanup scans kept
    (_row(1, 'LEGACY_T', 'PARTITION', 'P1', size_mb=50), False),      # the composite
    (_row(1, 'LEGACY_T', 'SUBPARTITION', 'P1', 'P1_S1', size_mb=50), True),  # partition row
    (_row(1, 'LEGACY_T', 'PARTITION', 'P2', size_mb=20), True),
    (_row(2, 'RANGE_T', 'TABLE', size_mb=5), True),                   # same name, other DB
    # Quick Scan with partitions (T1), then Full Analysis without (T2): newer TABLE wins
    (_row(1, 'RERUN_T', 'TABLE', size_mb=90, ts=T2), True),
    (_row(1, 'RERUN_T', 'PARTITION', 'P1', size_mb=45), False),
    (_row(1, 'RERUN_T', 'PARTITION', 'P2', size_mb=45), False),
    # Table-only analysis (T1), then a scan with partitions (T2): partitions win
    (_row(1, 'RESCAN_T', 'TABLE', size_mb=40), False),
    (_row(1, 'RESCAN_T', 'PARTITION', 'P1', size_mb=40, ts=T2), True),
    # Latest run with partitions (T3) failed on P2: P2's older row still counts
    (_row(1, 'PARTIAL_T', 'TABLE', size_mb=30, ts=T3), False),
    (_row(1, 'PARTIAL_T', 'PARTITION', 'P1', size_mb=20, ts=T3), True),
    (_row(1, 'PARTIAL_T', 'PARTITION', 'P2', size_mb=10), True),
    # No timestamps: child rows win
    (_row(1, 'NOTS_T', 'TABLE', size_mb=8, ts=None), False),
    (_row(1, 'NOTS_T', 'PARTITION', 'P1', size_mb=8, ts=None), True),
    # Partition rows without a TABLE row
    (_row(1, 'ORPHAN_T', 'PARTITION', 'P1', size_mb=3), True),
]
LEAF_MB = sum(r['SIZE_BYTES'] for r, leaf in MIXED if leaf) / MB


def _mixed_df():
    return pd.DataFrame([r for r, _ in MIXED])


def _expected():
    return [leaf for _, leaf in MIXED]


# ============================================================================
# In-memory helper
# ============================================================================

@pytest.mark.unit
class TestLeafSegmentMask:

    def test_picks_leaves_from_mixed_table_partition_subpartition_rows(self):
        df = _mixed_df()
        assert leaf_segment_mask(df).tolist() == _expected()
        assert leaf_segments(df)['SIZE_BYTES'].sum() / MB == LEAF_MB
        assert df['SIZE_BYTES'].sum() / MB > LEAF_MB  # the old double-counted total

    def test_keeps_index_and_all_columns(self):
        df = _mixed_df()
        df.index = [f"r{i}" for i in range(len(df))]
        out = leaf_segments(df)
        assert list(out.columns) == list(df.columns)
        assert list(out.index) == [i for i, leaf in zip(df.index, _expected()) if leaf]

    def test_accepts_recommendation_columns_lowercase(self):
        df = _mixed_df().rename(columns={'OWNER': 'TABLE_OWNER', 'OBJECT_NAME': 'TABLE_NAME'})
        df.columns = [c.lower() for c in df.columns]
        df['analysis_timestamp'] = pd.to_datetime(df['analysis_timestamp'])  # NaT for None
        assert leaf_segment_mask(df).tolist() == _expected()

    def test_without_timestamps_child_rows_win(self):
        df = _mixed_df().drop(columns=['ANALYSIS_TIMESTAMP'])
        mask = dict(zip(zip(df['OBJECT_NAME'], df['PARTITION_NAME']), leaf_segment_mask(df)))
        assert not mask[('RERUN_T', None)]
        assert mask[('RERUN_T', 'P1')] and mask[('RERUN_T', 'P2')]

    def test_nan_and_empty_partition_names_mean_no_partition(self):
        df = pd.DataFrame([
            {'OWNER': 'A', 'OBJECT_NAME': 'T', 'PARTITION_NAME': np.nan, 'SUBPARTITION_NAME': np.nan},
            {'OWNER': 'A', 'OBJECT_NAME': 'U', 'PARTITION_NAME': '', 'SUBPARTITION_NAME': None},
            {'OWNER': 'A', 'OBJECT_NAME': 'V', 'PARTITION_NAME': 'P1', 'SUBPARTITION_NAME': np.nan},
        ])
        assert leaf_segment_mask(df).tolist() == [True, True, True]

    def test_siblings_are_only_looked_up_within_the_rows_given(self):
        # A filtered list that kept the TABLE row but none of its partitions
        # still counts the table once.
        df = pd.DataFrame([_row(1, 'RANGE_T', 'TABLE', size_mb=100)])
        assert leaf_segment_mask(df).tolist() == [True]

    def test_list_of_dicts_in_list_out(self):
        rows = [r for r, _ in MIXED]
        out = leaf_segments(rows)
        assert isinstance(out, list)
        assert out == [r for r, leaf in MIXED if leaf]

    def test_empty_inputs(self):
        assert leaf_segments([]) == []
        assert leaf_segments(None) == []
        assert leaf_segments(pd.DataFrame()).empty
        assert leaf_segment_mask(pd.DataFrame(columns=['OWNER', 'OBJECT_NAME'])).tolist() == []

    def test_without_owner_object_columns_every_row_counts(self):
        df = pd.DataFrame({'current_size_mb': [1.0, 2.0], 'partition_name': [None, 'P1']})
        assert leaf_segment_mask(df).tolist() == [True, True]


# ============================================================================
# SQL view
# ============================================================================

@pytest.mark.unit
class TestLeafAnalysisSql:

    def test_groups_siblings_by_object_not_run(self):
        sql = " ".join(leaf_analysis_sql().split())
        assert sql.startswith("( SELECT * FROM ( SELECT ca.*,")
        assert sql.count("PARTITION BY ca.database_id, ca.owner, ca.object_name") == 4
        assert 'advisor_run_id' not in sql

    def test_sql_and_python_rules_agree(self):
        """Run the view for real (SQLite speaks this subset of Oracle SQL)."""
        con = sqlite3.connect(':memory:')
        con.execute("""CREATE TABLE t_compression_analysis (
            analysis_id INTEGER, database_id INTEGER, owner TEXT, object_name TEXT,
            partition_name TEXT, subpartition_name TEXT, size_bytes INTEGER,
            analysis_timestamp TEXT)""")
        con.executemany(
            "INSERT INTO t_compression_analysis VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            [(i, r['DATABASE_ID'], r['OWNER'], r['OBJECT_NAME'], r['PARTITION_NAME'],
              r['SUBPARTITION_NAME'], r['SIZE_BYTES'],
              r['ANALYSIS_TIMESTAMP'].isoformat() if r['ANALYSIS_TIMESTAMP'] else None)
             for i, (r, _) in enumerate(MIXED)])

        got = {row[0] for row in con.execute(
            f"SELECT a.analysis_id FROM {leaf_analysis_sql()} a")}
        assert got == {i for i, (_, leaf) in enumerate(MIXED) if leaf}

        # An outer filter on database_id works the way the aggregates use it
        total = con.execute(
            f"SELECT SUM(size_bytes) FROM {leaf_analysis_sql()} a "
            f"WHERE 1=1 AND database_id = :database_id", {'database_id': 1}).fetchone()[0]
        assert total / MB == LEAF_MB - 5


# ============================================================================
# SQL sent by the CentralQueries aggregates
# ============================================================================

def _norm(sql):
    return " ".join(sql.split())


LEAF_VIEW = _norm(leaf_analysis_sql())


@pytest.fixture
def captured(monkeypatch):
    """Replace CentralConnector.execute_query; record (sql, params) per call."""
    calls = []

    def fake_execute_query(query, params=None):
        calls.append((_norm(query), params))
        return pd.DataFrame([{
            'TOTAL_TABLES': 3, 'TOTAL_SIZE_MB': 1.0, 'POTENTIAL_SAVINGS_MB': 0.5,
            'AVG_SAVINGS_PCT': 10.0, 'CANDIDATES_COUNT': 1, 'TOTAL': 3, 'COMPRESSED': 1,
            'PENDING': 1, 'SKIPPED': 1, 'SAVED_MB': 0.0,
            'COMPRESSED_ORIGINAL_MB': 0.0, 'UNCOMPRESSED_MB': 0.0, 'PENDING_COUNT': 2,
            'PENDING_CURRENT_MB': 1.0, 'PENDING_PROJECTED_MB': 0.5, 'PENDING_SAVINGS_MB': 0.5,
            'AVG_SEC': 60,
        }])

    monkeypatch.setattr(CentralConnector, 'execute_query', fake_execute_query)
    return calls


AGGREGATES = [
    ('get_dashboard_summary', {'database_id': 7}),
    ('get_compression_progress', {'database_id': 7}),
    ('get_forecast_data', {'database_id': 7}),
    ('get_savings_by_strategy', {'database_id': 7}),
    ('get_dashboard_summary', {}),
    ('get_compression_progress', {}),
    ('get_forecast_data', {}),
    ('get_savings_by_strategy', {}),
    ('get_savings_by_database', {}),
    ('compare_databases', {}),
]


@pytest.mark.unit
class TestAggregateSql:

    @pytest.mark.parametrize('method,kwargs', AGGREGATES)
    def test_aggregate_reads_leaf_segments_only(self, captured, method, kwargs):
        getattr(CentralQueries, method)(**kwargs)
        sql, params = captured[0]
        assert f"FROM {LEAF_VIEW} a" in sql
        assert 'FROM t_compression_analysis ca' in sql
        # the base table is only read through the view
        assert sql.count('t_compression_analysis') == 1
        if kwargs:
            assert 'database_id = :database_id' in sql
            assert params == {'database_id': 7}

    def test_forecast_duration_query_unchanged(self, captured):
        result = CentralQueries.get_forecast_data(database_id=7)
        dur_sql, dur_params = captured[1]
        assert 'FROM t_compression_history' in dur_sql
        assert dur_sql.endswith('AND duration_seconds > 0 AND database_id = :database_id')
        assert dur_params == {'database_id': 7}
        assert result['pending_count'] == 2 and result['avg_duration_sec'] == 60

    def test_dashboard_summary_values_pass_through(self, captured):
        s = CentralQueries.get_dashboard_summary(database_id=7)
        assert s['total_tables'] == 3 and s['candidates_count'] == 1

    def test_object_level_recommendations_list_keeps_every_row(self, captured):
        CentralQueries.get_recommendations(database_id=7)
        sql, _ = captured[0]
        assert 'FROM t_compression_analysis a' in sql
        assert 'leaf_n_children' not in sql
        assert 'a.analysis_timestamp' in sql  # lets page totals apply the rule in memory


# ============================================================================
# Run totals
# ============================================================================

@pytest.mark.unit
class TestCompleteAdvisorRun:

    def _run(self, monkeypatch, results, analyzed, failed):
        dml = []
        monkeypatch.setattr(CentralConnector, 'execute_dml',
                            lambda statement, params=None, commit=True: dml.append(params) or 1)
        TargetQueries._complete_advisor_run(42, analyzed, failed, results, 0.0)
        assert len(dml) == 1
        return dml[0]

    def test_totals_cover_leaf_segments_only(self, monkeypatch):
        results = [
            _row(1, 'PLAIN', 'TABLE', size_mb=10, savings_mb=5, rec='BASIC'),
            _row(1, 'RANGE_T', 'TABLE', size_mb=100, savings_mb=50, rec='OLTP'),
            _row(1, 'RANGE_T', 'PARTITION', 'P1', size_mb=60, savings_mb=30, rec='QUERY HIGH'),
            _row(1, 'RANGE_T', 'PARTITION', 'P2', size_mb=40, savings_mb=0, rec='NONE'),
            _row(1, 'COMP_T', 'TABLE', size_mb=80, savings_mb=40, rec='OLTP'),
            _row(1, 'COMP_T', 'SUBPARTITION', 'P1', 'P1_S1', size_mb=50, savings_mb=25,
                 rec='ARCHIVE LOW'),
            _row(1, 'COMP_T', 'SUBPARTITION', 'P1', 'P1_S2', size_mb=30, savings_mb=0, rec='NONE'),
        ]
        for r in results:            # start_analysis rows carry neither column
            del r['DATABASE_ID'], r['ANALYSIS_TIMESTAMP']
        p = self._run(monkeypatch, results, analyzed=7, failed=1)

        assert p['run_id'] == 42
        assert p['total_size'] == 10 + 60 + 40 + 50 + 30
        assert p['savings'] == 5 + 30 + 0 + 25 + 0
        assert p['savings_pct'] == round(60 / 190 * 100, 2)
        assert (p['r_none'], p['r_basic'], p['r_oltp'], p['r_adv_low'], p['r_adv_high']) == \
            (2, 1, 0, 1, 1)
        # Work counters are the analyses performed, passed through unchanged
        assert (p['analyzed'], p['succeeded'], p['failed']) == (8, 7, 1)

    def test_non_partitioned_run_unchanged(self, monkeypatch):
        results = [_row(1, 'A', 'TABLE', size_mb=10, savings_mb=4, rec='OLTP'),
                   _row(1, 'B', 'TABLE', size_mb=30, savings_mb=0, rec='NONE')]
        p = self._run(monkeypatch, results, analyzed=2, failed=0)
        assert (p['total_size'], p['savings'], p['savings_pct']) == (40, 4, 10.0)
        assert (p['r_none'], p['r_oltp']) == (1, 1)

    def test_empty_run(self, monkeypatch):
        p = self._run(monkeypatch, [], analyzed=0, failed=0)
        assert (p['total_size'], p['savings'], p['savings_pct']) == (0, 0, 0)


# ============================================================================
# AI Advisor prompt
# ============================================================================

@pytest.mark.unit
class TestAiAdvisorPrompt:

    def test_candidates_are_leaf_segments_labelled_by_partition(self, monkeypatch):
        from hcc_advisor.views import page_13_ai_advisor as ai

        recs = pd.DataFrame([
            {'TABLE_OWNER': 'APP', 'TABLE_NAME': 'SALES', 'PARTITION_NAME': None,
             'SUBPARTITION_NAME': None, 'CURRENT_SIZE_MB': 100.0},
            {'TABLE_OWNER': 'APP', 'TABLE_NAME': 'SALES', 'PARTITION_NAME': 'P1',
             'SUBPARTITION_NAME': None, 'CURRENT_SIZE_MB': 60.0},
            {'TABLE_OWNER': 'APP', 'TABLE_NAME': 'SALES', 'PARTITION_NAME': 'P2',
             'SUBPARTITION_NAME': None, 'CURRENT_SIZE_MB': 40.0},
            {'TABLE_OWNER': 'APP', 'TABLE_NAME': 'EVENTS', 'PARTITION_NAME': 'Q1',
             'SUBPARTITION_NAME': 'Q1_S1', 'CURRENT_SIZE_MB': 5.0},
        ])
        monkeypatch.setattr(CentralQueries, 'get_compression_progress', lambda database_id: {})
        monkeypatch.setattr(CentralQueries, 'get_forecast_data', lambda database_id: {})
        monkeypatch.setattr(CentralQueries, 'get_recommendations', lambda **kw: recs.copy())
        monkeypatch.setattr(CentralQueries, 'get_execution_history', lambda **kw: pd.DataFrame())
        monkeypatch.setattr(CentralQueries, 'get_growth_alerts', lambda database_id: pd.DataFrame())

        context = ai._gather_context(7)
        assert [(c['table_name'], c['partition_name']) for c in context['candidates']] == \
            [('SALES', 'P1'), ('SALES', 'P2'), ('EVENTS', 'Q1')]
        assert sum(c['current_size_mb'] for c in context['candidates']) == 105.0

        prompt = ai._build_prompt(context, 'Full Estate')
        assert '| Owner | Table | Partition | Size MB |' in prompt
        assert '| APP | SALES | P1 | 60 |' in prompt
        assert '| APP | EVENTS | Q1.Q1_S1 | 5 |' in prompt
        assert '| APP | SALES | - |' not in prompt
