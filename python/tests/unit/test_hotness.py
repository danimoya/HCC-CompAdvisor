"""
Unit tests for the hotness scoring model (hcc_advisor.utils.hotness) and its
wiring into TargetQueries (start_analysis / quick_scan inputs).

Run with:
    cd python && python -m pytest tests/unit/test_hotness.py -o addopts="" -q
"""
import itertools
import math
from datetime import datetime, timedelta
from unittest.mock import patch

import pandas as pd
import pytest

from hcc_advisor.utils.hotness import (
    compute_hotness, hotness_category, index_dml_rows, index_segment_rows,
    lookup_dml, lookup_segment, read_intensity, write_intensity,
    SOURCE_AWR, SOURCE_DML, SOURCE_SEGSTATS,
)

NOW = datetime(2026, 9, 24, 12, 0, 0)


def _seg(window_days=30.0, logical_reads=0, physical_reads=0, block_changes=0):
    return {'window_days': window_days, 'logical_reads': logical_reads,
            'physical_reads': physical_reads, 'block_changes': block_changes}


# ============================================================================
# The regressions reported by users
# ============================================================================

@pytest.mark.unit
class TestActiveTablesAreNotZero:

    def test_busy_table_analyzed_last_night_without_modifications_row(self):
        """Nightly auto-stats removed the DBA_TAB_MODIFICATIONS row; segment
        statistics still show the table is busy."""
        r = compute_hotness(
            {},  # modifications view readable, but no row for this table
            num_rows=2_000_000,
            last_analyzed=NOW - timedelta(hours=1),
            now=NOW,
            segment_stats=_seg(window_days=20, logical_reads=400_000_000,
                               physical_reads=2_000_000, block_changes=3_000_000),
        )
        assert r['hotness_score'] > 50
        assert r['hotness_category'] in ('WARM', 'HOT')
        assert r['dml_per_day'] == pytest.approx(150_000)

    def test_recently_analyzed_table_with_little_dml_since_is_rated_per_day(self):
        """300 DML in the 2 hours since the stats gather is 3,600 DML/day, not
        '300 DML total' (which the old count-based model ranked as cold)."""
        r = compute_hotness({'inserts': 200, 'updates': 100}, num_rows=500_000,
                            last_analyzed=NOW - timedelta(hours=2), now=NOW)
        assert r['dml_per_day'] == pytest.approx(3600)
        assert r['hotness_score'] > 40

    def test_read_heavy_table_without_dml_is_not_zero(self):
        r = compute_hotness({}, num_rows=1_000_000, dml_window_days=3,
                            segment_stats=_seg(window_days=10, logical_reads=500_000_000))
        assert r['total_dml'] == 0
        assert r['hotness_score'] >= 25
        assert r['hotness_category'] in ('COOL', 'WARM')
        assert r['read_ratio'] == 1.0

    def test_reads_alone_never_reach_hot(self):
        r = compute_hotness({}, segment_stats=_seg(window_days=1, logical_reads=10 ** 13))
        assert r['hotness_score'] == pytest.approx(60.0)
        assert r['hotness_category'] == 'WARM'

    def test_modifications_view_unreadable_still_scores_from_segments(self):
        r = compute_hotness(None, segment_stats=_seg(window_days=5, block_changes=500_000))
        assert r['hotness_score'] > 50
        assert r['sources'] == (SOURCE_SEGSTATS,)

    def test_score_is_absolute_not_relative_to_the_batch(self):
        """The old model gave the busiest table of the batch 100. A near-idle
        table must stay near-idle even if it is the busiest one scanned."""
        near_idle = compute_hotness({'updates': 3}, dml_window_days=30)
        assert near_idle['hotness_score'] < 10
        # and a busy table keeps its score regardless of what else exists
        busy = compute_hotness({'updates': 1_000_000}, dml_window_days=1)
        assert busy['hotness_score'] == 100.0


@pytest.mark.unit
class TestIdleTables:

    def test_no_activity_observed_scores_zero(self):
        r = compute_hotness({}, num_rows=10_000_000, dml_window_days=40,
                            segment_stats=_seg(window_days=40))
        assert r['hotness_score'] == 0
        assert r['hotness_category'] == 'COLD'
        assert r['basis'].startswith('no DML or reads observed')

    def test_trickle_of_activity_scores_low(self):
        r = compute_hotness({'inserts': 12}, num_rows=50_000_000, dml_window_days=365,
                            segment_stats=_seg(window_days=90, logical_reads=900))
        assert 0 < r['hotness_score'] < 10
        assert r['hotness_category'] == 'COLD'

    def test_no_source_readable_is_reported_as_unavailable(self):
        r = compute_hotness(None)
        assert r['hotness_score'] == 0
        assert r['sources'] == ()
        assert r['basis'] == 'activity data unavailable'
        assert r['dml_per_day'] is None and r['reads_per_day'] is None


# ============================================================================
# Model properties
# ============================================================================

@pytest.mark.unit
class TestMonotonicity:

    LEVELS = [0, 1, 10, 1_000, 100_000, 10_000_000, 10 ** 9]

    @pytest.mark.parametrize('field', ['inserts', 'updates', 'deletes'])
    def test_non_decreasing_in_dml(self, field):
        scores = [compute_hotness({field: n}, num_rows=1_000_000, dml_window_days=2,
                                  segment_stats=_seg(logical_reads=10_000))['hotness_score']
                  for n in self.LEVELS]
        assert scores == sorted(scores)
        assert scores[-1] > scores[0]

    @pytest.mark.parametrize('field', ['logical_reads', 'physical_reads', 'block_changes'])
    def test_non_decreasing_in_segment_stats(self, field):
        scores = [compute_hotness({'updates': 50}, dml_window_days=1,
                                  segment_stats=_seg(**{field: n}))['hotness_score']
                  for n in self.LEVELS]
        assert scores == sorted(scores)
        assert scores[-1] > scores[0]

    def test_non_decreasing_in_awr_stats(self):
        scores = [compute_hotness({}, awr_stats=_seg(window_days=7, logical_reads=n,
                                                     block_changes=n // 10))['hotness_score']
                  for n in self.LEVELS]
        assert scores == sorted(scores)

    def test_same_dml_over_a_longer_window_is_cooler(self):
        scores = [compute_hotness({'updates': 50_000}, num_rows=1_000_000,
                                  dml_window_days=d)['hotness_score']
                  for d in (0.1, 1, 7, 30, 365)]
        assert scores == sorted(scores, reverse=True)
        assert scores[0] > scores[-1]

    def test_grid_of_reads_and_writes(self):
        rates = [0, 10, 1_000, 100_000, 10_000_000]
        grid = {(w, r): compute_hotness({'updates': w}, dml_window_days=1,
                                        segment_stats=_seg(window_days=1, logical_reads=r))['hotness_score']
                for w, r in itertools.product(rates, rates)}
        for (w, r), score in grid.items():
            assert 0 <= score <= 100
            for w2 in rates:
                if w2 > w:
                    assert grid[(w2, r)] >= score
            for r2 in rates:
                if r2 > r:
                    assert grid[(w, r2)] >= score


@pytest.mark.unit
class TestCalibration:

    @pytest.mark.parametrize('dml_per_day,expected', [
        (1_000, 50.0), (10_000, 66.7), (100_000, 83.3), (1_000_000, 100.0), (10 ** 8, 100.0),
    ])
    def test_write_anchors_without_num_rows(self, dml_per_day, expected):
        r = compute_hotness({'updates': dml_per_day}, dml_window_days=1)
        assert r['hotness_score'] == pytest.approx(expected, abs=0.1)

    def test_churn_makes_small_busy_tables_hotter_than_huge_ones(self):
        small = compute_hotness({'updates': 20_000}, num_rows=50_000, dml_window_days=1)
        huge = compute_hotness({'updates': 20_000}, num_rows=1_000_000_000, dml_window_days=1)
        assert small['hotness_score'] > huge['hotness_score'] > 0
        assert small['hotness_category'] == 'HOT'

    def test_unknown_num_rows_uses_absolute_rate_only(self):
        a = compute_hotness({'updates': 5_000}, num_rows=None, dml_window_days=1)
        b = compute_hotness({'updates': 5_000}, num_rows=0, dml_window_days=1)
        assert a['hotness_score'] == b['hotness_score']
        assert a['write_intensity'] == pytest.approx(math.log10(5001) / math.log10(1_000_001), abs=1e-4)

    def test_intensities_are_bounded(self):
        assert write_intensity(10 ** 15, 1) == 1.0
        assert read_intensity(10 ** 15) == 1.0
        assert write_intensity(0, 100) == 0.0
        assert read_intensity(None) == 0.0

    def test_highest_source_wins(self):
        seg_only = compute_hotness(None, segment_stats=_seg(window_days=100, block_changes=1_000))
        with_awr = compute_hotness(None, segment_stats=_seg(window_days=100, block_changes=1_000),
                                   awr_stats=_seg(window_days=7, block_changes=700_000))
        assert with_awr['dml_per_day'] == pytest.approx(100_000)
        assert with_awr['hotness_score'] > seg_only['hotness_score']
        assert with_awr['sources'] == (SOURCE_SEGSTATS, SOURCE_AWR)


@pytest.mark.unit
class TestWindowsAndInputs:

    def test_last_analyzed_and_explicit_window_agree(self):
        a = compute_hotness({'updates': 5_000}, last_analyzed=NOW - timedelta(days=2), now=NOW)
        b = compute_hotness({'updates': 5_000}, dml_window_days=2)
        assert a['hotness_score'] == b['hotness_score']

    def test_explicit_window_wins_over_last_analyzed(self):
        r = compute_hotness({'updates': 1_000}, dml_window_days=10,
                            last_analyzed=NOW - timedelta(days=1), now=NOW)
        assert r['dml_per_day'] == pytest.approx(100)

    def test_tiny_or_negative_windows_clamp_to_one_hour(self):
        just_now = compute_hotness({'updates': 10}, dml_window_days=0)
        skewed = compute_hotness({'updates': 10}, last_analyzed=NOW + timedelta(hours=3), now=NOW)
        assert just_now['dml_per_day'] == pytest.approx(240)
        assert skewed['dml_per_day'] == pytest.approx(240)

    def test_never_analyzed_defaults_to_one_day(self):
        r = compute_hotness({'inserts': 500}, last_analyzed=None, dml_window_days=None)
        assert r['dml_per_day'] == pytest.approx(500)

    def test_pandas_nan_nat_and_none_are_tolerated(self):
        r = compute_hotness({'inserts': float('nan'), 'updates': None, 'deletes': 7},
                            num_rows=float('nan'), last_analyzed=pd.NaT,
                            dml_window_days=float('nan'),
                            segment_stats={'window_days': None, 'logical_reads': float('nan')})
        assert r['total_dml'] == 7
        assert 0 < r['hotness_score'] <= 100

    def test_date_and_timestamp_last_analyzed(self):
        ts = compute_hotness({'updates': 100}, last_analyzed=pd.Timestamp(NOW - timedelta(days=4)), now=NOW)
        d = compute_hotness({'updates': 100}, last_analyzed=(NOW - timedelta(days=4)).date(), now=NOW)
        assert ts['dml_per_day'] == pytest.approx(25)
        assert d['dml_per_day'] == pytest.approx(100 / 4.5, abs=0.01)  # date = midnight, NOW is noon

    def test_result_fits_hotness_score_column(self):
        r = compute_hotness({'updates': 123_457}, num_rows=987_654, dml_window_days=1.2345,
                            segment_stats=_seg(logical_reads=98_765_432))
        assert r['hotness_score'] == round(r['hotness_score'], 2)
        assert 0 <= r['hotness_score'] <= 100
        assert r['read_ratio'] + r['write_ratio'] == pytest.approx(1.0, abs=0.011)

    def test_basis_mentions_rates_and_sources(self):
        r = compute_hotness({'updates': 2_000}, dml_window_days=1,
                            segment_stats=_seg(window_days=1, logical_reads=3_000_000))
        assert '2.0K writes/day' in r['basis']
        assert '3.0M block reads/day' in r['basis']
        assert SOURCE_DML in r['basis'] and SOURCE_SEGSTATS in r['basis']


@pytest.mark.unit
class TestCategory:

    @pytest.mark.parametrize('score,expected', [
        (100, 'HOT'), (75, 'HOT'), (74.99, 'WARM'), (50, 'WARM'), (49.99, 'COOL'),
        (25, 'COOL'), (24.99, 'COLD'), (0, 'COLD'), (None, 'COLD'), (float('nan'), 'COLD'),
    ])
    def test_thresholds_match_central_virtual_column(self, score, expected):
        assert hotness_category(score) == expected

    def test_category_matches_score(self):
        for n in (0, 5, 50, 500, 5_000, 50_000, 500_000):
            r = compute_hotness({'updates': n}, dml_window_days=1)
            assert r['hotness_category'] == hotness_category(r['hotness_score'])


# ============================================================================
# Dictionary row indexing (partitioned tables)
# ============================================================================

def _mod(owner, table, part=None, sub=None, ins=0, upd=0, dlt=0):
    return {'table_owner': owner, 'table_name': table, 'partition_name': part,
            'subpartition_name': sub, 'inserts': ins, 'updates': upd, 'deletes': dlt}


@pytest.mark.unit
class TestDmlIndex:

    def test_partitioned_table_without_table_level_row_sums_partitions(self):
        idx = index_dml_rows([
            _mod('APP', 'SALES', 'P1', ins=100),
            _mod('APP', 'SALES', 'P2', ins=50, upd=5),
        ])
        assert lookup_dml(idx, 'APP', 'SALES') == {'inserts': 150, 'updates': 5, 'deletes': 0}
        assert lookup_dml(idx, 'APP', 'SALES', 'P2') == {'inserts': 50, 'updates': 5, 'deletes': 0}

    def test_lagging_table_row_is_raised_to_partition_sum(self):
        idx = index_dml_rows([
            _mod('APP', 'SALES', ins=10, dlt=40),
            _mod('APP', 'SALES', 'P1', ins=100),
            _mod('APP', 'SALES', 'P2', ins=50),
        ])
        assert lookup_dml(idx, 'APP', 'SALES') == {'inserts': 150, 'updates': 0, 'deletes': 40}

    def test_composite_partition_and_subpartitions(self):
        idx = index_dml_rows([
            _mod('APP', 'EVT', 'P1', 'P1_S1', upd=7),
            _mod('APP', 'EVT', 'P1', 'P1_S2', upd=3),
            _mod('APP', 'EVT', 'P2', 'P2_S1', dlt=4),
        ])
        assert lookup_dml(idx, 'APP', 'EVT', 'P1', 'P1_S2') == {'inserts': 0, 'updates': 3, 'deletes': 0}
        assert lookup_dml(idx, 'APP', 'EVT', 'P1') == {'inserts': 0, 'updates': 10, 'deletes': 0}
        assert lookup_dml(idx, 'APP', 'EVT') == {'inserts': 0, 'updates': 10, 'deletes': 4}

    def test_unknown_objects_get_zeros(self):
        idx = index_dml_rows([_mod('APP', 'T1', ins=1)])
        assert lookup_dml(idx, 'APP', 'OTHER') == {'inserts': 0, 'updates': 0, 'deletes': 0}
        assert lookup_dml(idx, 'APP', 'T1', 'NOPE') == {'inserts': 0, 'updates': 0, 'deletes': 0}

    def test_nan_partition_names_from_pandas_are_table_level(self):
        idx = index_dml_rows([_mod('APP', 'T1', part=float('nan'), sub=float('nan'), ins=9)])
        assert lookup_dml(idx, 'APP', 'T1')['inserts'] == 9


@pytest.mark.unit
class TestSegmentIndex:

    def test_table_level_sums_all_segments_and_partitions_by_name(self):
        src = {'window_days': 12.5, 'objects': index_segment_rows([
            {'owner': 'APP', 'object_name': 'SALES', 'subobject_name': 'P1',
             'logical_reads': 100, 'physical_reads': 10, 'block_changes': 5},
            {'owner': 'APP', 'object_name': 'SALES', 'subobject_name': 'P2',
             'logical_reads': 300, 'physical_reads': 0, 'block_changes': 1},
        ])}
        table = lookup_segment(src, 'APP', 'SALES')
        assert table == {'logical_reads': 400, 'physical_reads': 10, 'block_changes': 6, 'window_days': 12.5}
        assert lookup_segment(src, 'APP', 'SALES', 'P2')['logical_reads'] == 300

    def test_segment_not_touched_since_startup_is_zero_activity(self):
        src = {'window_days': 3.0, 'objects': {}}
        seg = lookup_segment(src, 'APP', 'COLD_TABLE')
        assert seg == {'logical_reads': 0, 'physical_reads': 0, 'block_changes': 0, 'window_days': 3.0}
        assert compute_hotness({}, segment_stats=seg)['hotness_score'] == 0


# ============================================================================
# TargetQueries wiring (no database: every target/central call is mocked)
# ============================================================================

from hcc_advisor.utils.target_queries import TargetQueries  # noqa: E402

_V_SEGSTAT_ROWS = pd.DataFrame([
    # busy non-partitioned table whose stats were just gathered
    ('APP', 'ORDERS', None, 900_000_000, 3_000_000, 6_000_000),
    # partitioned table: only the current partition is active
    ('APP', 'EVENTS', 'P_OLD', 0, 0, 0),
    ('APP', 'EVENTS', 'P_CUR', 50_000_000, 100_000, 800_000),
], columns=['OWNER', 'OBJECT_NAME', 'SUBOBJECT_NAME', 'LOGICAL_READS', 'PHYSICAL_READS', 'BLOCK_CHANGES'])


def _fake_quiet(fail_views=()):
    def run(database_id, query, params=None):
        q = query.lower()
        for view in fail_views:
            if view in q:
                raise RuntimeError(f'ORA-00942: table or view does not exist ({view})')
        if 'v$instance' in q:
            return pd.DataFrame([(20.0,)], columns=['UPTIME_DAYS'])
        if 'v$segment_statistics' in q:
            return _V_SEGSTAT_ROWS.copy()
        if 'tab_modifications' in q:
            # ORDERS has no row: its stats were gathered 1 hour ago
            return pd.DataFrame([('APP', 'EVENTS', 'P_CUR', None, 4_000, 0, 0)],
                                columns=['TABLE_OWNER', 'TABLE_NAME', 'PARTITION_NAME',
                                         'SUBPARTITION_NAME', 'INSERTS', 'UPDATES', 'DELETES'])
        raise AssertionError(f'unexpected query: {query}')
    return run


@pytest.mark.unit
class TestTargetQueriesWiring:

    def test_dml_stats_fall_back_to_all_view(self):
        with patch.object(TargetQueries, '_query_target_quiet',
                          side_effect=_fake_quiet(fail_views=('dba_tab_modifications',))) as q:
            idx = TargetQueries._get_batch_dml_stats(1, 'app')
        assert lookup_dml(idx, 'APP', 'EVENTS')['inserts'] == 4_000
        assert 'all_tab_modifications' in q.call_args_list[-1].args[1]
        assert q.call_args_list[-1].args[2] == {'owner': 'APP'}

    def test_unreadable_sources_are_logged_not_swallowed(self):
        with patch.object(TargetQueries, '_query_target_quiet',
                          side_effect=_fake_quiet(fail_views=('tab_modifications', 'v$segment_statistics'))), \
                patch.object(TargetQueries, '_awr_acknowledged', return_value=False), \
                patch('hcc_advisor.utils.target_queries.log_warning') as warn:
            inputs = TargetQueries._collect_hotness_inputs(1)
        assert inputs == {'dml': None, 'segments': None, 'awr': None}
        messages = ' '.join(str(c.args[0]) for c in warn.call_args_list)
        assert 'TAB_MODIFICATIONS' in messages
        assert 'V$SEGMENT_STATISTICS' in messages
        assert 'no activity source could be read' in messages

    def test_awr_only_queried_when_acknowledged(self):
        with patch.object(TargetQueries, '_query_target_quiet', side_effect=_fake_quiet()), \
                patch.object(TargetQueries, 'get_awr_segment_stats', return_value=None) as awr:
            with patch.object(TargetQueries, '_awr_acknowledged', return_value=False):
                TargetQueries._collect_hotness_inputs(1)
            awr.assert_not_called()
            with patch.object(TargetQueries, '_awr_acknowledged', return_value=True):
                TargetQueries._collect_hotness_inputs(1, 'APP')
            awr.assert_called_once_with(1, 'APP')

    def test_quick_scan_scores_recently_analyzed_active_tables(self):
        from hcc_advisor.utils.central_queries import CentralQueries
        from hcc_advisor.utils.central_connector import CentralConnector

        tables = [
            {'owner': 'APP', 'table_name': 'ORDERS', 'num_rows': 5_000_000, 'blocks': 100_000,
             'avg_row_len': 120, 'last_analyzed': NOW - timedelta(hours=1), 'stats_age_days': 1 / 24,
             'partitioned': 'NO', 'compression': 'DISABLED', 'compress_for': None,
             'size_bytes': 800 * 1048576, 'size_mb': 800.0},
            {'owner': 'APP', 'table_name': 'EVENTS', 'num_rows': 9_000_000, 'blocks': 200_000,
             'avg_row_len': 90, 'last_analyzed': NOW - timedelta(days=3), 'stats_age_days': 3.0,
             'partitioned': 'YES', 'compression': 'DISABLED', 'compress_for': None,
             'size_bytes': 1600 * 1048576, 'size_mb': 1600.0},
        ]
        partitions = [
            {'partition_name': 'P_OLD', 'composite': 'NO', 'compression': 'DISABLED', 'compress_for': None,
             'num_rows': 8_000_000, 'blocks': 150_000, 'last_analyzed': NOW - timedelta(days=200),
             'stats_age_days': 200.0, 'size_bytes': 1200 * 1048576, 'size_mb': 1200.0},
            {'partition_name': 'P_CUR', 'composite': 'NO', 'compression': 'DISABLED', 'compress_for': None,
             'num_rows': 1_000_000, 'blocks': 50_000, 'last_analyzed': None,
             'stats_age_days': float('nan'), 'size_bytes': 400 * 1048576, 'size_mb': 400.0},
        ]
        stored = {}

        def _store(database_id, run_id, df):
            stored['df'] = df
            return True

        with patch.object(CentralQueries, 'get_target_database', return_value={'platform_type': 'EXADATA'}), \
                patch.object(CentralConnector, 'execute_query', return_value=pd.DataFrame()), \
                patch.object(CentralQueries, 'store_advisor_run', return_value=(True, 42)), \
                patch.object(CentralQueries, 'store_analysis_results', side_effect=_store), \
                patch.object(TargetQueries, '_safe_flush_monitoring_info', return_value=True), \
                patch.object(TargetQueries, '_discover_analysis_tables', return_value=tables), \
                patch.object(TargetQueries, '_get_batch_table_stats', return_value={}), \
                patch.object(TargetQueries, '_discover_partitions', return_value=partitions), \
                patch.object(TargetQueries, '_query_target_quiet', side_effect=_fake_quiet()):
            results = TargetQueries.quick_scan(1, owner='APP')

        by_name = {(r['OBJECT_NAME'], r['PARTITION_NAME']): r for r in results}
        orders = by_name[('ORDERS', None)]
        assert orders['HOTNESS_SCORE'] >= 75          # was 0: no TAB_MODIFICATIONS row
        assert orders['ADVISABLE_COMPRESSION'] in ('NONE', 'OLTP')
        assert orders['LOGICAL_READS'] == 900_000_000
        assert orders['DML_24H_RATE'] == pytest.approx(300_000)
        assert 'HOT' in orders['RECOMMENDATION_REASON']

        events = by_name[('EVENTS', None)]
        assert events['INSERT_COUNT'] == 4_000        # rebuilt from the partition row
        assert events['HOTNESS_SCORE'] > 0

        p_cur = by_name[('EVENTS', 'P_CUR')]
        p_old = by_name[('EVENTS', 'P_OLD')]
        assert p_cur['HOTNESS_SCORE'] > 50
        assert p_old['HOTNESS_SCORE'] == 0
        assert p_old['ADVISABLE_COMPRESSION'] == 'ARCHIVE HIGH'
        assert 'no DML or reads observed' in p_old['RECOMMENDATION_REASON']

        assert list(stored['df']['HOTNESS_SCORE']) == [r['HOTNESS_SCORE'] for r in results]

    def test_start_analysis_scores_subpartitions_and_keeps_all_of_them(self):
        """Subpartitions used to be hard-coded to hotness 0, and a NameError
        (undefined objects_analyzed) silently dropped every subpartition after
        the first one."""
        from hcc_advisor.utils.central_queries import CentralQueries
        from hcc_advisor.utils.central_connector import CentralConnector

        table = {'owner': 'APP', 'table_name': 'EVENTS', 'num_rows': 9_000_000, 'blocks': 200_000,
                 'avg_row_len': 90, 'last_analyzed': NOW - timedelta(days=1), 'stats_age_days': 1.0,
                 'partitioned': 'YES', 'compression': 'DISABLED', 'compress_for': None,
                 'size_bytes': 1600 * 1048576, 'size_mb': 1600.0}
        part = {'partition_name': 'P1', 'composite': 'YES', 'compression': 'NONE', 'compress_for': None,
                'num_rows': 9_000_000, 'blocks': 200_000, 'last_analyzed': None,
                'stats_age_days': None, 'size_bytes': 0, 'size_mb': 0.0}
        subs = [
            {'subpartition_name': 'P1_S1', 'compression': 'DISABLED', 'compress_for': None,
             'num_rows': 4_000_000, 'blocks': 90_000, 'last_analyzed': NOW - timedelta(hours=2),
             'stats_age_days': 2 / 24, 'size_bytes': 700 * 1048576, 'size_mb': 700.0},
            {'subpartition_name': 'P1_S2', 'compression': 'DISABLED', 'compress_for': None,
             'num_rows': 5_000_000, 'blocks': 110_000, 'last_analyzed': NOW - timedelta(days=90),
             'stats_age_days': 90.0, 'size_bytes': 900 * 1048576, 'size_mb': 900.0},
        ]
        segstats = pd.DataFrame([
            ('APP', 'EVENTS', 'P1_S1', 80_000_000, 50_000, 2_000_000),
        ], columns=['OWNER', 'OBJECT_NAME', 'SUBOBJECT_NAME', 'LOGICAL_READS', 'PHYSICAL_READS',
                    'BLOCK_CHANGES'])
        mods = pd.DataFrame([('APP', 'EVENTS', 'P1', 'P1_S1', 1_000, 500, 0)],
                            columns=['TABLE_OWNER', 'TABLE_NAME', 'PARTITION_NAME',
                                     'SUBPARTITION_NAME', 'INSERTS', 'UPDATES', 'DELETES'])

        def quiet(database_id, query, params=None):
            q = query.lower()
            if 'v$instance' in q:
                return pd.DataFrame([(10.0,)], columns=['UPTIME_DAYS'])
            if 'v$segment_statistics' in q:
                return segstats.copy()
            if 'tab_modifications' in q:
                return mods.copy()
            raise AssertionError(query)

        stored = {}
        with patch.object(CentralQueries, 'get_target_database', return_value={'platform_type': 'EXADATA'}), \
                patch.object(CentralConnector, 'execute_query', return_value=pd.DataFrame()), \
                patch.object(CentralQueries, 'store_advisor_run', return_value=(True, 7)), \
                patch.object(CentralQueries, 'store_analysis_results',
                             side_effect=lambda db, run, df: stored.setdefault('df', df)), \
                patch.object(TargetQueries, '_complete_advisor_run'), \
                patch.object(TargetQueries, '_safe_flush_monitoring_info', return_value=True), \
                patch.object(TargetQueries, '_discover_analysis_tables', return_value=[table]), \
                patch.object(TargetQueries, '_get_batch_table_stats', return_value={}), \
                patch.object(TargetQueries, '_get_single_compression_ratio', return_value=3.0), \
                patch.object(TargetQueries, '_discover_partitions', return_value=[part]), \
                patch.object(TargetQueries, '_discover_subpartitions', return_value=subs), \
                patch.object(TargetQueries, '_query_target_quiet', side_effect=quiet):
            out = TargetQueries.start_analysis(1, owner='APP', include_partitions=True)

        assert out['success'], out
        rows = {(r['OBJECT_TYPE'], r['SUBPARTITION_NAME']): r for r in stored['df'].to_dict('records')}
        assert set(rows) == {('TABLE', None), ('SUBPARTITION', 'P1_S1'), ('SUBPARTITION', 'P1_S2')}
        assert rows[('TABLE', None)]['HOTNESS_SCORE'] > 50
        assert rows[('TABLE', None)]['INSERT_COUNT'] == 1_000   # rebuilt from the subpartition row
        assert rows[('SUBPARTITION', 'P1_S1')]['HOTNESS_SCORE'] >= 75
        assert rows[('SUBPARTITION', 'P1_S2')]['HOTNESS_SCORE'] == 0
        assert rows[('SUBPARTITION', 'P1_S1')]['ADVISABLE_COMPRESSION'] != \
            rows[('SUBPARTITION', 'P1_S2')]['ADVISABLE_COMPRESSION']
        assert 'Hotness:' in rows[('TABLE', None)]['RECOMMENDATION_REASON']

    def test_old_statistics_no_longer_cool_a_hot_table(self):
        stats = {'last_analyzed': NOW - timedelta(days=400), 'num_rows': 1_000_000}
        assert TargetQueries._determine_target_compression([], 'TABLE', 80, stats, 'EXADATA') == 'OLTP'

    def test_rationale_distinguishes_idle_from_unavailable(self):
        idle = compute_hotness({}, segment_stats=_seg())
        unknown = compute_hotness(None)
        r1 = TargetQueries._generate_rationale(10.0, 0, {}, 'ARCHIVE HIGH', hotness=idle)
        r2 = TargetQueries._generate_rationale(10.0, 0, {}, 'ARCHIVE HIGH', hotness=unknown)
        assert 'Hotness: 0/100 (COLD; no DML or reads observed' in r1
        assert 'Hotness: 0/100 (COLD; activity data unavailable)' in r2
