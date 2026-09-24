"""
Unit tests for the compression script / manifest builder
(hcc_advisor.utils.sql_builder) beyond the version and platform rules in
test_version_platform_ddl:

- identifier validation and IN-list chunking (ORA-01795) of the index lookup;
- gather_dependent_indexes returns each table's indexes and the partitions of
  its partitioned indexes, and tolerates a failing target;
- build_compression_script comments out anything unsafe or unsupported
  (identifiers, compression types, index / index-partition names), notes a
  failed operation's error and clamps the parallel degree;
- build_compression_manifest emits the re-importable CSV columns.

Target databases are mocked (TargetConnector.execute_query).
"""
import re
from unittest.mock import MagicMock

import pandas as pd
import pytest

from hcc_advisor.utils import sql_builder
from hcc_advisor.utils.sql_builder import (
    MANIFEST_COLUMNS, build_compression_manifest, build_compression_script, chunk_list,
    gather_dependent_indexes, gather_target_info,
)
from hcc_advisor.utils.target_connector import TargetConnector

V11_2 = "Oracle Database 11g Enterprise Edition Release 11.2.0.4.0 - 64bit Production"
V19 = "Oracle Database 19c Enterprise Edition Release 19.0.0.0.0 - Production"
OLD_EXADATA = {1: {'oracle_version': V11_2, 'platform_type': 'EXADATA'}}


def _ops(rows, db_id=1):
    base = {'database_id': db_id, 'database_display': 'PROD', 'database_name': 'PRODDB',
            'owner': 'APP', 'object_name': 'ORDERS', 'partition_name': None,
            'subpartition_name': None, 'compression_type_applied': 'OLTP',
            'parallel_degree': 4, 'operation_status': 'QUEUED', 'error_message': None}
    return pd.DataFrame([{**base, **r} for r in rows])


def _statements(script):
    return [ln for ln in script.splitlines() if ln and not ln.startswith('--')]


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestHelpers:

    @pytest.mark.parametrize('value, valid', [
        ('ORDERS', True), ('a', True), ('SYS_P123$#', True), ('X' * 128, True),
        ('X' * 129, False), ('1ORDERS', False), ('_ORDERS', False), ('ORD ERS', False),
        ('APP.ORDERS', False), ('"Orders"', False), ('ORDERS\n', False), ("O'X", False),
        ('', False), (None, False), (123, False),
    ])
    def test_is_valid_identifier(self, value, valid):
        assert sql_builder._is_valid_identifier(value) is valid

    def test_sql_quote_escapes_quotes(self):
        assert sql_builder._sql_quote("O'BRIEN") == "'O''BRIEN'"
        assert sql_builder._sql_quote(5) == "'5'"

    def test_chunk_list(self):
        assert chunk_list(range(2500)) == [list(range(1000)), list(range(1000, 2000)),
                                           list(range(2000, 2500))]
        assert chunk_list([], 10) == []
        assert chunk_list('abc', 2) == [['a', 'b'], ['c']]

    @pytest.mark.parametrize('value, present', [
        ('P1', True), (0, True), (None, False), (float('nan'), False),
        ('', False), ('  ', False), ('None', False), ('nan', False),
    ])
    def test_present(self, value, present):
        assert sql_builder._present(value) is present

    def test_gather_target_info_ignores_missing_ids(self, monkeypatch):
        from hcc_advisor.utils import target_queries as tq
        lookups = []
        monkeypatch.setattr(tq, 'target_ddl_info',
                            lambda did: lookups.append(did) or {'oracle_version': V19,
                                                                'platform_type': 'EXADATA'})
        df = pd.DataFrame({'DATABASE_ID': [2, 'x', None, 0, 2, 1]})
        assert sorted(gather_target_info(df)) == [1, 2]
        assert lookups == [1, 2]


# ---------------------------------------------------------------------------
# Dependent index discovery
# ---------------------------------------------------------------------------

def _index_rows(*rows):
    return pd.DataFrame(rows, columns=['INDEX_OWNER', 'INDEX_NAME', 'TABLE_OWNER',
                                       'TABLE_NAME', 'PARTITIONED'])


@pytest.mark.unit
class TestGatherDependentIndexes:

    def test_indexes_and_index_partitions(self, monkeypatch):
        def query(did, sql):
            if 'FROM all_indexes' in sql:
                return _index_rows(('APP', 'ORDERS_PK', 'APP', 'ORDERS', 'NO'),
                                   ('APP', 'ORDERS_LIX', 'APP', 'ORDERS', 'YES'),
                                   ('APP', 'ITEMS_PK', 'APP', 'ITEMS', 'NO'))
            assert "index_name IN ('ORDERS_LIX')" in sql
            return pd.DataFrame({'INDEX_OWNER': ['APP', 'APP'],
                                 'INDEX_NAME': ['ORDERS_LIX', 'ORDERS_LIX'],
                                 'PARTITION_NAME': ['P1', 'P2']})
        monkeypatch.setattr(TargetConnector, 'execute_query', query)
        ops = _ops([{}, {'object_name': 'ITEMS'}, {'database_id': 0, 'object_name': 'SKIPPED'}])

        result = gather_dependent_indexes(ops)

        assert set(result) == {(1, 'APP', 'ORDERS'), (1, 'APP', 'ITEMS')}
        orders = result[(1, 'APP', 'ORDERS')]
        assert [i['name'] for i in orders['indexes']] == ['ORDERS_PK', 'ORDERS_LIX']
        assert orders['ind_partitions'] == {('APP', 'ORDERS_LIX'): ['P1', 'P2']}

    def test_in_lists_are_chunked_under_1000(self, monkeypatch):
        seen = []

        def query(did, sql):
            seen.append(sql)
            return pd.DataFrame()
        monkeypatch.setattr(TargetConnector, 'execute_query', query)
        ops = _ops([{'object_name': f'T{i}'} for i in range(2100)])

        assert gather_dependent_indexes(ops) == {}
        assert len(seen) == 3                   # 1 owner chunk x 3 table chunks
        for sql in seen:
            in_list = re.search(r"table_name IN \(([^)]*)\)", sql).group(1)
            assert 0 < len(in_list.split(',')) <= 1000

    def test_index_partitions_are_chunked(self, monkeypatch):
        calls = []

        def query(did, sql):
            calls.append(sql)
            return pd.DataFrame()
        monkeypatch.setattr(TargetConnector, 'execute_query', query)
        names = [f'IX{i}' for i in range(1500)]
        assert sql_builder._ind_partitions_for(1, ['APP'], names) == {}
        assert len(calls) == 2

    def test_failing_target_is_skipped(self, monkeypatch):
        monkeypatch.setattr(TargetConnector, 'execute_query',
                            MagicMock(side_effect=RuntimeError('ORA-12541: no listener')))
        assert gather_dependent_indexes(_ops([{}])) == {}


# ---------------------------------------------------------------------------
# SQL script
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestBuildCompressionScript:

    def test_header_and_basic_move(self):
        script = build_compression_script(_ops([{}]), 'QUEUED', 'PROD',
                                          targets={1: {'oracle_version': V19,
                                                       'platform_type': 'EXADATA'}})
        assert '-- Database Filter: PROD' in script
        assert '-- Status Filter: QUEUED' in script
        assert '-- Total Operations: 1' in script
        assert '-- Index rebuild statements: NOT INCLUDED' in script
        assert '-- Database: PROD' in script
        assert '-- Oracle version: 19.0, platform: EXADATA' in script
        assert _statements(script) == [
            'SET SERVEROUTPUT ON;', 'SET TIMING ON;',
            'ALTER TABLE APP.ORDERS MOVE COMPRESS FOR OLTP ONLINE PARALLEL 4;',
        ]
        assert script.endswith('-- End of generated script')

    @pytest.mark.parametrize('comp, clause', [
        ('BASIC', 'COMPRESS BASIC'), ('NONE', 'NOCOMPRESS'), ('ADVANCED', 'COMPRESS FOR OLTP'),
        ('query_high', 'COMPRESS FOR QUERY HIGH'), (None, 'COMPRESS FOR OLTP'),
    ])
    def test_compression_clauses(self, comp, clause):
        script = build_compression_script(_ops([{'compression_type_applied': comp}]), 'All', 'PROD',
                                          targets={1: {'oracle_version': V19,
                                                       'platform_type': 'EXADATA'}})
        assert f'ALTER TABLE APP.ORDERS MOVE {clause} ONLINE PARALLEL 4;' in script

    def test_unsupported_compression_is_skipped(self):
        script = build_compression_script(
            _ops([{'compression_type_applied': "OLTP; DROP TABLE X"}]), 'All', 'PROD', targets={})
        assert "-- SKIPPED (unsupported compression type 'OLTP; DROP TABLE X'): APP.ORDERS" in script
        assert not [s for s in _statements(script) if s.startswith('ALTER')]

    @pytest.mark.parametrize('row', [
        {'owner': 'APP; DROP USER SYS'},
        {'object_name': 'ORDERS MOVE TABLESPACE X'},
        {'partition_name': "P1'"},
    ])
    def test_invalid_identifiers_are_skipped(self, row):
        script = build_compression_script(_ops([row]), 'All', 'PROD', targets={})
        assert '-- SKIPPED (invalid identifier)' in script
        assert not [s for s in _statements(script) if s.startswith('ALTER')]

    @pytest.mark.parametrize('dop, expected', [(0, 4), (1, 1), (500, 128), (8.0, 8)])
    def test_parallel_degree_is_clamped(self, dop, expected):
        # 0 / None fall back to the default of 4 before clamping.
        script = build_compression_script(_ops([{'parallel_degree': dop}]), 'All', 'PROD',
                                          targets={})
        assert f'ONLINE PARALLEL {expected};' in script

    def test_failed_operation_notes_its_error(self):
        script = build_compression_script(
            _ops([{'operation_status': 'FAILED', 'error_message': 'ORA-01652: ' + 'x' * 200}]),
            'FAILED', 'PROD', targets={})
        marker = next(ln for ln in script.splitlines() if ln.startswith('-- APP.ORDERS [FAILED]'))
        assert marker == '-- APP.ORDERS [FAILED] -- error: ' + ('ORA-01652: ' + 'x' * 200)[:100]

    def test_bad_database_id_is_treated_as_unknown(self):
        script = build_compression_script(_ops([{'database_id': 'n/a'}]), 'All', 'PROD', targets={})
        assert '-- Oracle version: unknown (assuming 12.2+), platform: unknown' in script
        assert 'ALTER TABLE APP.ORDERS MOVE COMPRESS FOR OLTP ONLINE PARALLEL 4;' in script

    def test_database_label_falls_back(self):
        ops = _ops([{'database_display': None}, {'database_display': None, 'database_name': None}])
        script = build_compression_script(ops, 'All', 'ALL', targets={})
        assert '-- Database: PRODDB' in script
        assert '-- Database: db_1' in script

    def test_unsafe_index_names_are_not_rebuilt(self):
        index_map = {(1, 'APP', 'ORDERS'): {
            'indexes': [
                {'owner': 'APP', 'name': 'ORDERS_PK', 'partitioned': 'NO'},
                {'owner': 'APP', 'name': 'BAD INDEX', 'partitioned': 'NO'},
                {'owner': 'APP', 'name': 'ORDERS_LIX', 'partitioned': 'YES'},
                {'owner': 'APP', 'name': 'ORDERS_GIX', 'partitioned': 'YES'},
            ],
            'ind_partitions': {('APP', 'ORDERS_LIX'): ['P1', 'P2; DROP TABLE X']},
        }}
        script = build_compression_script(_ops([{}]), 'All', 'PROD', index_map,
                                          targets=OLD_EXADATA)
        assert '-- Rebuild 4 dependent index(es) for APP.ORDERS' in script
        assert [s for s in _statements(script) if s.startswith('ALTER INDEX')] == [
            'ALTER INDEX APP.ORDERS_PK REBUILD ONLINE PARALLEL 4;',
            'ALTER INDEX APP.ORDERS_LIX REBUILD PARTITION P1 ONLINE PARALLEL 4;',
        ]
        assert '-- SKIPPED index rebuild (invalid identifier): APP.BAD INDEX' in script
        assert ('-- SKIPPED partition rebuild (invalid identifier): '
                'APP.ORDERS_LIX.P2; DROP TABLE X') in script
        assert ('-- WARNING: could not enumerate partitions for APP.ORDERS_GIX; '
                'rebuild manually') in script

    def test_table_without_indexes_in_the_map(self):
        index_map = {(1, 'APP', 'OTHER'): {'indexes': [], 'ind_partitions': {}}}
        script = build_compression_script(_ops([{}]), 'All', 'PROD', index_map,
                                          targets=OLD_EXADATA)
        assert 'ALTER TABLE APP.ORDERS MOVE COMPRESS FOR OLTP PARALLEL 4;' in script
        assert '-- No dependent indexes found for APP.ORDERS (or index info unavailable)' in script


# ---------------------------------------------------------------------------
# CSV manifest
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestBuildCompressionManifest:

    def test_columns_and_values(self):
        ops = _ops([{'partition_name': 'P1', 'compression_type_applied': 'QUERY HIGH'}])
        ops['object_type'] = 'TABLE PARTITION'
        ops.columns = [c.upper() for c in ops.columns]   # queries return upper case

        manifest = build_compression_manifest(ops)

        assert list(manifest.columns) == MANIFEST_COLUMNS
        row = manifest.iloc[0]
        assert row['database_name'] == 'PROD'            # display name preferred
        assert row['owner'] == 'APP' and row['object_name'] == 'ORDERS'
        assert row['partition_name'] == 'P1'
        assert row['compression_type'] == 'QUERY HIGH'
        assert row['object_type'] == 'TABLE PARTITION'
        assert row['operation_status'] == 'QUEUED'

    def test_missing_columns_are_empty(self):
        ops = pd.DataFrame({'owner': ['APP'], 'object_name': ['ORDERS'],
                            'database_name': ['PRODDB']})
        manifest = build_compression_manifest(ops)
        assert list(manifest.columns) == MANIFEST_COLUMNS
        assert manifest.iloc[0]['database_name'] == 'PRODDB'
        assert manifest[['database_id', 'object_type', 'compression_type']].isna().all().all()

    def test_input_frame_is_not_modified(self):
        ops = _ops([{}])
        ops.columns = [c.upper() for c in ops.columns]
        before = list(ops.columns)
        build_compression_manifest(ops)
        assert list(ops.columns) == before
