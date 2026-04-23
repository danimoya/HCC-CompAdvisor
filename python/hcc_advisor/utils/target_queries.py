"""
Target Database Queries Module for HCC Compression Advisor
Data access layer for queries executed on remote target Oracle databases.
Handles analysis execution, compression execution, schema discovery,
table introspection, and session monitoring on target instances.
"""

import pandas as pd
import streamlit as st
from typing import Optional, Dict, Any, List
from hcc_advisor.utils.target_connector import TargetConnector
from hcc_advisor.utils.logger import log_error, log_info, log_debug, log_warning


def _safe_int(val) -> int:
    """Coerce a possibly-NaN/None value to int. NaN and None map to 0."""
    if val is None:
        return 0
    if isinstance(val, float) and pd.isna(val):
        return 0
    return int(val)


def _safe_float(val) -> float:
    """Coerce a possibly-NaN/None value to float. NaN and None map to 0.0."""
    if val is None:
        return 0.0
    if isinstance(val, float) and pd.isna(val):
        return 0.0
    return float(val)


class TargetQueries:
    """Data access layer for operations on remote target Oracle databases"""

    # ============================================================================
    # ANALYSIS EXECUTION (Python-driven, uses DBMS_COMPRESSION on target, HCC-aware)
    # ============================================================================

    # Maximum partitions to analyze per table (safety cap)
    MAX_PARTITIONS_PER_TABLE = 50

    @staticmethod
    def start_analysis(
        database_id: int,
        owner: Optional[str] = None,
        strategy_id: int = 2,
        parallel_degree: int = 4,
        include_partitions: bool = False
    ) -> Dict[str, Any]:
        """
        Run compression analysis on target database using DBMS_COMPRESSION directly.
        No PL/SQL packages required on target. Results stored in central DB.

        Args:
            database_id: Target database identifier
            owner: Schema owner to analyze (None for all schemas)
            strategy_id: Strategy ID (1=Aggressive, 2=Balanced, 3=Conservative)
            parallel_degree: Number of parallel workers
            include_partitions: If True, also analyze individual partitions/subpartitions

        Returns:
            dict with success, run_id, message
        """
        import math
        import time
        from datetime import datetime
        from hcc_advisor.utils.central_queries import CentralQueries
        from hcc_advisor.utils.central_connector import CentralConnector

        start_time = time.time()
        run_id = None

        try:
            # 0. Fetch platform type from central DB for HCC detection
            db_info = CentralQueries.get_target_database(database_id)
            platform_type = (db_info.get('platform_type') or 'STANDARD').upper()

            # 1. Create advisor run in central DB
            run_data = {
                'run_name': f'Analysis {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}',
                'run_type': 'TABLES',
                'schema_filter': owner,
                'strategy_id': strategy_id,
                'parallel_degree': parallel_degree,
                'analysis_mode': 'FULL',
                'include_partitions': 'Y' if include_partitions else 'N'
            }
            ok, run_id = CentralQueries.store_advisor_run(database_id, run_data)
            if not ok or not run_id:
                return {'success': False, 'run_id': None, 'message': 'Failed to create advisor run record'}

            log_info(f"Analysis run created: run_id={run_id}, db_id={database_id}, schema={owner or 'ALL'}")

            # 2. Load strategy rules from central DB
            strategy_rules = []
            try:
                rules_df = CentralConnector.execute_query("""
                    SELECT object_type, compression_type,
                           NVL(hotness_min, 0) as hotness_min,
                           NVL(hotness_max, 100) as hotness_max
                    FROM t_strategy_rules
                    WHERE strategy_id = :sid AND enabled_flag = 'Y'
                    ORDER BY priority DESC
                """, {'sid': strategy_id})
                if not rules_df.empty:
                    for _, r in rules_df.iterrows():
                        strategy_rules.append({
                            'object_type': r['OBJECT_TYPE'],
                            'compression_type': r['COMPRESSION_TYPE'],
                            'hotness_min': float(r['HOTNESS_MIN']),
                            'hotness_max': float(r['HOTNESS_MAX']),
                        })
            except Exception as e:
                log_warning(f"Could not load strategy rules: {e}")

            # 3. Flush monitoring info on target (best effort)
            TargetQueries._safe_flush_monitoring_info(database_id)

            # 4. Discover eligible tables on target
            tables = TargetQueries._discover_analysis_tables(database_id, owner)
            if not tables:
                TargetQueries._complete_advisor_run(run_id, 0, 0, [], start_time)
                return {'success': True, 'run_id': run_id, 'message': 'No eligible tables found for analysis'}

            log_info(f"Found {len(tables)} eligible tables on db_id={database_id}")

            # 5. Batch-fetch DML stats for hotness scoring
            dml_stats = TargetQueries._get_batch_dml_stats(database_id, owner)

            # 5b. Batch-fetch column-level statistics for smarter recommendations
            col_stats = TargetQueries._get_batch_table_stats(database_id, owner)

            # 6. Analyze each table
            results = []
            tables_analyzed = 0
            tables_failed = 0

            for table_info in tables:
                tbl_owner = table_info['owner']
                tbl_name = table_info['table_name']
                try:
                    hotness_key = f"{tbl_owner}.{tbl_name}"
                    dml_info = dml_stats.get(hotness_key, {})
                    hotness_score = dml_info.get('hotness_score', 0) if isinstance(dml_info, dict) else 0

                    current_size_mb = table_info['size_mb']

                    # Build table_stats dict for enhanced recommendation
                    tbl_col_stats = col_stats.get(hotness_key, {})
                    table_stats = {
                        'avg_row_len': table_info.get('avg_row_len', 0),
                        'last_analyzed': table_info.get('last_analyzed'),
                        'num_rows': table_info.get('num_rows', 0),
                        'avg_null_pct': tbl_col_stats.get('avg_null_pct', 0),
                        'avg_distinct': tbl_col_stats.get('avg_distinct', 0),
                        'num_columns': tbl_col_stats.get('num_columns', 0),
                    }

                    # Determine target compression from hotness + stats FIRST
                    recommended = TargetQueries._determine_target_compression(
                        strategy_rules, 'TABLE', hotness_score, table_stats, platform_type
                    )

                    # Only test the single advised ratio (1 call instead of 6)
                    ratios = {k: None for k in ('basic', 'oltp', 'query_low', 'query_high', 'archive_low', 'archive_high')}
                    rec_ratio = 1.0
                    if recommended != 'NONE':
                        rec_ratio = TargetQueries._get_single_compression_ratio(
                            database_id, tbl_owner, tbl_name, recommended
                        )
                        ratio_key = TargetQueries._COMP_TYPE_RATIO_KEY.get(recommended)
                        if ratio_key:
                            ratios[ratio_key] = rec_ratio
                        if rec_ratio <= 1:
                            recommended = 'NONE'

                    best_ratio = rec_ratio if rec_ratio > 1 else 1

                    # Savings based on recommended compression type
                    rec_size = round(current_size_mb / rec_ratio, 2) if rec_ratio > 0 else current_size_mb
                    savings_mb = current_size_mb - rec_size
                    savings_pct = round((savings_mb / current_size_mb) * 100, 2) if current_size_mb > 0 else 0

                    rationale = TargetQueries._generate_rationale(
                        current_size_mb, hotness_score, ratios, recommended, table_stats
                    )

                    current_comp = table_info.get('compress_for') or table_info.get('compression', 'NONE')
                    if current_comp in ('DISABLED', None, ''):
                        current_comp = 'NONE'

                    result = {
                        'OWNER': tbl_owner,
                        'OBJECT_NAME': tbl_name,
                        'OBJECT_TYPE': 'TABLE',
                        'PARTITION_NAME': None,
                        'SUBPARTITION_NAME': None,
                        'ORIGINAL_SIZE_BYTES': table_info['size_bytes'],
                        'SIZE_BYTES': table_info['size_bytes'],
                        'ROW_COUNT': table_info.get('num_rows'),
                        'BLOCK_COUNT': table_info.get('blocks'),
                        'AVG_ROW_LENGTH': table_info.get('avg_row_len'),
                        'BASIC_RATIO': ratios.get('basic'),
                        'OLTP_RATIO': ratios.get('oltp'),
                        'ADV_LOW_RATIO': ratios.get('query_low'),
                        'ADV_HIGH_RATIO': ratios.get('query_high'),
                        'BLKCNT_UNCMP_BASIC': None,
                        'BLKCNT_CMP_BASIC': None,
                        'BLKCNT_UNCMP_OLTP': None,
                        'BLKCNT_CMP_OLTP': None,
                        'BLKCNT_UNCMP_ADV_LOW': None,
                        'BLKCNT_CMP_ADV_LOW': None,
                        'BLKCNT_UNCMP_ADV_HIGH': None,
                        'BLKCNT_CMP_ADV_HIGH': None,
                        'INSERT_COUNT': dml_info.get('inserts', 0) if isinstance(dml_info, dict) else 0,
                        'UPDATE_COUNT': dml_info.get('updates', 0) if isinstance(dml_info, dict) else 0,
                        'DELETE_COUNT': dml_info.get('deletes', 0) if isinstance(dml_info, dict) else 0,
                        'LOGICAL_READS': None,
                        'PHYSICAL_READS': None,
                        'ACCESS_FREQUENCY': None,
                        'LAST_ACCESS_DATE': None,
                        'HOTNESS_SCORE': hotness_score,
                        'READ_RATIO': None,
                        'WRITE_RATIO': None,
                        'DML_24H_RATE': None,
                        'LAST_ANALYZED': table_info.get('last_analyzed'),
                        'DATA_AGE_DAYS': None,
                        'CURRENT_COMPRESSION': current_comp,
                        'ADVISABLE_COMPRESSION': recommended,
                        'RECOMMENDATION_REASON': rationale,
                        'CONFIDENCE_SCORE': None,
                        'PROJECTED_SAVINGS_BYTES': int(savings_mb * 1024 * 1024),
                        'PROJECTED_SAVINGS_PCT': savings_pct,
                        'ANALYSIS_DURATION_SEC': None,
                        'SAMPLE_SIZE_ROWS': None,
                    }
                    results.append(result)
                    tables_analyzed += 1

                    ratio_str = ' '.join(f'{k}={v:.2f}x' for k, v in ratios.items() if v and v > 0)
                    log_debug(f"Analyzed {tbl_owner}.{tbl_name}: {ratio_str} rec={recommended}")

                    # --- Partition-level analysis (opt-in) ---
                    if include_partitions:
                        partitions = TargetQueries._discover_partitions(database_id, tbl_owner, tbl_name)
                        if partitions:
                            if len(partitions) > TargetQueries.MAX_PARTITIONS_PER_TABLE:
                                log_warning(
                                    f"{tbl_owner}.{tbl_name} has {len(partitions)} partitions "
                                    f"(>{TargetQueries.MAX_PARTITIONS_PER_TABLE}), skipping partition-level analysis"
                                )
                            else:
                                log_info(f"Analyzing {len(partitions)} partitions for {tbl_owner}.{tbl_name}")
                                part_dml = TargetQueries._get_batch_partition_dml_stats(
                                    database_id, tbl_owner, tbl_name
                                )

                                for part_info in partitions:
                                    part_name = part_info['partition_name']
                                    is_composite = part_info.get('composite') == 'YES'

                                    # Composite partitions cannot be MOVE'd (ORA-14257)
                                    # Only their subpartitions can — skip the partition-level result
                                    if is_composite:
                                        try:
                                            subparts = TargetQueries._discover_subpartitions(
                                                database_id, tbl_owner, tbl_name, part_name)
                                            for subpart_info in subparts:
                                                sub_name = subpart_info['subpartition_name']
                                                try:
                                                    sub_recommended = TargetQueries._determine_target_compression(
                                                        strategy_rules, 'TABLE', 0, table_stats, platform_type)
                                                    sub_ratios = {k: None for k in ('basic', 'oltp', 'query_low', 'query_high', 'archive_low', 'archive_high')}
                                                    sub_rec_ratio = 1.0
                                                    if sub_recommended != 'NONE':
                                                        sub_rec_ratio = TargetQueries._get_single_compression_ratio(
                                                            database_id, tbl_owner, tbl_name, sub_recommended,
                                                            partition_name=sub_name)
                                                        sk = TargetQueries._COMP_TYPE_RATIO_KEY.get(sub_recommended)
                                                        if sk:
                                                            sub_ratios[sk] = sub_rec_ratio
                                                        if sub_rec_ratio <= 1:
                                                            sub_recommended = 'NONE'
                                                    sub_size_mb = subpart_info.get('size_mb', 0)
                                                    sub_rec_size = round(sub_size_mb / sub_rec_ratio, 2) if sub_rec_ratio > 0 else sub_size_mb
                                                    sub_savings_mb = sub_size_mb - sub_rec_size
                                                    sub_savings_pct = round((sub_savings_mb / sub_size_mb) * 100, 2) if sub_size_mb > 0 else 0
                                                    sub_current_comp = subpart_info.get('compress_for') or subpart_info.get('compression', 'NONE')
                                                    if sub_current_comp in ('DISABLED', None, ''):
                                                        sub_current_comp = 'NONE'
                                                    results.append({
                                                        'OWNER': tbl_owner, 'OBJECT_NAME': tbl_name,
                                                        'OBJECT_TYPE': 'SUBPARTITION',
                                                        'PARTITION_NAME': part_name, 'SUBPARTITION_NAME': sub_name,
                                                        'ORIGINAL_SIZE_BYTES': subpart_info.get('size_bytes', 0),
                                                        'SIZE_BYTES': subpart_info.get('size_bytes', 0),
                                                        'ROW_COUNT': subpart_info.get('num_rows'),
                                                        'BLOCK_COUNT': subpart_info.get('blocks'),
                                                        'AVG_ROW_LENGTH': None,
                                                        'BASIC_RATIO': sub_ratios.get('basic'),
                                                        'OLTP_RATIO': sub_ratios.get('oltp'),
                                                        'ADV_LOW_RATIO': sub_ratios.get('query_low'),
                                                        'ADV_HIGH_RATIO': sub_ratios.get('query_high'),
                                                        'BLKCNT_UNCMP_BASIC': None, 'BLKCNT_CMP_BASIC': None,
                                                        'BLKCNT_UNCMP_OLTP': None, 'BLKCNT_CMP_OLTP': None,
                                                        'BLKCNT_UNCMP_ADV_LOW': None, 'BLKCNT_CMP_ADV_LOW': None,
                                                        'BLKCNT_UNCMP_ADV_HIGH': None, 'BLKCNT_CMP_ADV_HIGH': None,
                                                        'INSERT_COUNT': 0, 'UPDATE_COUNT': 0, 'DELETE_COUNT': 0,
                                                        'LOGICAL_READS': None, 'PHYSICAL_READS': None,
                                                        'ACCESS_FREQUENCY': None, 'LAST_ACCESS_DATE': None,
                                                        'HOTNESS_SCORE': 0, 'READ_RATIO': None, 'WRITE_RATIO': None,
                                                        'DML_24H_RATE': None, 'LAST_ANALYZED': None, 'DATA_AGE_DAYS': None,
                                                        'CURRENT_COMPRESSION': sub_current_comp,
                                                        'ADVISABLE_COMPRESSION': sub_recommended,
                                                        'RECOMMENDATION_REASON': f'Subpartition of composite {part_name}',
                                                        'CONFIDENCE_SCORE': None,
                                                        'PROJECTED_SAVINGS_BYTES': int(sub_savings_mb * 1048576),
                                                        'PROJECTED_SAVINGS_PCT': sub_savings_pct,
                                                        'ANALYSIS_DURATION_SEC': None, 'SAMPLE_SIZE_ROWS': None,
                                                    })
                                                    objects_analyzed += 1
                                                except Exception:
                                                    objects_failed += 1
                                        except Exception:
                                            pass
                                        continue  # Skip to next partition

                                    try:
                                        part_dml_info = part_dml.get(part_name, {})
                                        part_hotness = part_dml_info.get('hotness_score', 0)
                                        part_recommended = TargetQueries._determine_target_compression(
                                            strategy_rules, 'TABLE', part_hotness, table_stats, platform_type
                                        )
                                        part_ratios = {k: None for k in ('basic', 'oltp', 'query_low', 'query_high', 'archive_low', 'archive_high')}
                                        part_rec_ratio = 1.0
                                        if part_recommended != 'NONE':
                                            part_rec_ratio = TargetQueries._get_single_compression_ratio(
                                                database_id, tbl_owner, tbl_name, part_recommended,
                                                partition_name=part_name
                                            )
                                            pk = TargetQueries._COMP_TYPE_RATIO_KEY.get(part_recommended)
                                            if pk:
                                                part_ratios[pk] = part_rec_ratio
                                            if part_rec_ratio <= 1:
                                                part_recommended = 'NONE'

                                        part_size_mb = part_info.get('size_mb', 0)
                                        part_rec_size = round(part_size_mb / part_rec_ratio, 2) if part_rec_ratio > 0 else part_size_mb
                                        part_savings_mb = part_size_mb - part_rec_size
                                        part_savings_pct = round((part_savings_mb / part_size_mb) * 100, 2) if part_size_mb > 0 else 0
                                        part_current_comp = part_info.get('compress_for') or part_info.get('compression', 'NONE')
                                        if part_current_comp in ('DISABLED', None, ''):
                                            part_current_comp = 'NONE'

                                        part_rationale = TargetQueries._generate_rationale(
                                            part_size_mb, part_hotness, part_ratios, part_recommended
                                        )

                                        part_result = {
                                            'OWNER': tbl_owner,
                                            'OBJECT_NAME': tbl_name,
                                            'OBJECT_TYPE': 'PARTITION',
                                            'PARTITION_NAME': part_name,
                                            'SUBPARTITION_NAME': None,
                                            'ORIGINAL_SIZE_BYTES': part_info.get('size_bytes', 0),
                                            'SIZE_BYTES': part_info.get('size_bytes', 0),
                                            'ROW_COUNT': part_info.get('num_rows'),
                                            'BLOCK_COUNT': part_info.get('blocks'),
                                            'AVG_ROW_LENGTH': None,
                                            'BASIC_RATIO': part_ratios.get('basic'),
                                            'OLTP_RATIO': part_ratios.get('oltp'),
                                            'ADV_LOW_RATIO': part_ratios.get('query_low'),
                                            'ADV_HIGH_RATIO': part_ratios.get('query_high'),
                                            'BLKCNT_UNCMP_BASIC': None, 'BLKCNT_CMP_BASIC': None,
                                            'BLKCNT_UNCMP_OLTP': None, 'BLKCNT_CMP_OLTP': None,
                                            'BLKCNT_UNCMP_ADV_LOW': None, 'BLKCNT_CMP_ADV_LOW': None,
                                            'BLKCNT_UNCMP_ADV_HIGH': None, 'BLKCNT_CMP_ADV_HIGH': None,
                                            'INSERT_COUNT': part_dml_info.get('inserts', 0),
                                            'UPDATE_COUNT': part_dml_info.get('updates', 0),
                                            'DELETE_COUNT': part_dml_info.get('deletes', 0),
                                            'LOGICAL_READS': None, 'PHYSICAL_READS': None,
                                            'ACCESS_FREQUENCY': None, 'LAST_ACCESS_DATE': None,
                                            'HOTNESS_SCORE': part_hotness,
                                            'READ_RATIO': None, 'WRITE_RATIO': None,
                                            'DML_24H_RATE': None,
                                            'LAST_ANALYZED': None, 'DATA_AGE_DAYS': None,
                                            'CURRENT_COMPRESSION': part_current_comp,
                                            'ADVISABLE_COMPRESSION': part_recommended,
                                            'RECOMMENDATION_REASON': part_rationale,
                                            'CONFIDENCE_SCORE': None,
                                            'PROJECTED_SAVINGS_BYTES': int(part_savings_mb * 1024 * 1024),
                                            'PROJECTED_SAVINGS_PCT': part_savings_pct,
                                            'ANALYSIS_DURATION_SEC': None,
                                            'SAMPLE_SIZE_ROWS': None,
                                        }
                                        results.append(part_result)
                                        tables_analyzed += 1
                                        log_debug(f"Analyzed partition {tbl_owner}.{tbl_name}.{part_name}: rec={part_recommended}")

                                    except Exception as part_e:
                                        tables_failed += 1
                                        log_warning(f"Failed to analyze partition {tbl_owner}.{tbl_name}.{part_name}: {part_e}")

                except Exception as e:
                    tables_failed += 1
                    log_warning(f"Failed to analyze {tbl_owner}.{tbl_name}: {e}")

            # 7. Store results in central DB
            if results:
                results_df = pd.DataFrame(results)
                CentralQueries.store_analysis_results(database_id, run_id, results_df)

            # 8. Update run record as completed
            TargetQueries._complete_advisor_run(run_id, tables_analyzed, tables_failed, results, start_time)

            msg = f'Analysis completed: {tables_analyzed} tables analyzed'
            candidates = sum(1 for r in results if r.get('ADVISABLE_COMPRESSION', 'NONE') != 'NONE')
            if candidates:
                msg += f', {candidates} compression candidates found'
            log_info(msg)

            return {'success': True, 'run_id': run_id, 'message': msg}

        except Exception as e:
            log_error(e, "TargetQueries.start_analysis", {
                'database_id': database_id, 'owner': owner, 'strategy_id': strategy_id
            })
            if run_id:
                try:
                    from hcc_advisor.utils.central_connector import CentralConnector
                    CentralConnector.execute_dml(
                        "UPDATE t_advisor_run SET run_status = 'FAILED', error_message = :msg, end_time = SYSTIMESTAMP WHERE run_id = :rid",
                        {'rid': run_id, 'msg': str(e)[:4000]}
                    )
                except Exception:
                    pass
            return {'success': False, 'run_id': run_id, 'message': f'Analysis failed: {str(e)}'}

    # ============================================================================
    # ANALYSIS HELPER METHODS (private)
    # ============================================================================

    @staticmethod
    def _discover_analysis_tables(database_id: int, owner: Optional[str] = None) -> List[Dict]:
        """Discover tables eligible for compression analysis on the target"""
        owner_filter = "AND t.owner = :owner" if owner else ""
        params = {'owner': owner.upper()} if owner else {}

        query = f"""
            SELECT t.owner, t.table_name, t.num_rows, t.blocks,
                   t.avg_row_len,
                   t.last_analyzed,
                   t.partitioned,
                   t.compression, t.compress_for,
                   NVL(s.total_bytes, 0) as size_bytes,
                   ROUND(NVL(s.total_bytes, 0) / 1024 / 1024, 2) as size_mb
            FROM all_tables t
            LEFT JOIN (
                SELECT owner, segment_name, SUM(bytes) as total_bytes
                FROM dba_segments WHERE segment_type LIKE 'TABLE%'
                GROUP BY owner, segment_name
            ) s ON s.owner = t.owner AND s.segment_name = t.table_name
            WHERE t.temporary = 'N'
              AND t.iot_type IS NULL
              AND t.cluster_name IS NULL
              AND t.owner NOT IN (
                  'SYS','SYSTEM','AUDSYS','OUTLN','DBSNMP','GSMADMIN_INTERNAL',
                  'XDB','WMSYS','CTXSYS','MDSYS','ORDSYS','ORDDATA','OLAPSYS',
                  'APPQOSSYS','DBSFWUSER','GGSYS','SPATIAL_CSW_ADMIN_USR',
                  'SPATIAL_WFS_ADMIN_USR','ANONYMOUS','APEX_PUBLIC_USER',
                  'DIP','FLOWS_FILES','MDDATA','ORACLE_OCM','XS$NULL',
                  'REMOTE_SCHEDULER_AGENT','APEX_INSTANCE_ADMIN_USER'
              )
              AND t.owner NOT LIKE 'APEX_%'
              AND t.owner NOT LIKE 'ORACLE%'
              AND t.owner NOT LIKE 'FLOWS_%'
              AND NVL(s.total_bytes, 0) > 1048576
              AND NOT EXISTS (
                  SELECT 1 FROM all_tab_columns c
                  WHERE c.owner = t.owner AND c.table_name = t.table_name
                    AND c.data_type IN ('LONG', 'LONG RAW')
              )
              {owner_filter}
            ORDER BY s.total_bytes DESC NULLS LAST
        """

        try:
            df = TargetConnector.execute_query(database_id, query, params if params else None)
            if df.empty:
                return []
            tables = []
            for _, row in df.iterrows():
                tables.append({
                    'owner': row['OWNER'],
                    'table_name': row['TABLE_NAME'],
                    'num_rows': _safe_int(row.get('NUM_ROWS')),
                    'blocks': _safe_int(row.get('BLOCKS')),
                    'avg_row_len': _safe_int(row.get('AVG_ROW_LEN')),
                    'last_analyzed': row.get('LAST_ANALYZED'),
                    'partitioned': row.get('PARTITIONED', 'NO'),
                    'compression': row.get('COMPRESSION', 'NONE'),
                    'compress_for': row.get('COMPRESS_FOR'),
                    'size_bytes': _safe_int(row.get('SIZE_BYTES')),
                    'size_mb': _safe_float(row.get('SIZE_MB')),
                })
            return tables
        except Exception as e:
            log_error(e, "_discover_analysis_tables", {'database_id': database_id, 'owner': owner})
            return []

    @staticmethod
    def _discover_partitions(
        database_id: int, owner: str, table_name: str
    ) -> List[Dict]:
        """Discover partitions for a partitioned table on the target."""
        query = """
            SELECT p.partition_name, p.composite,
                   p.compression, p.compress_for,
                   p.num_rows, p.blocks,
                   NVL(s.bytes, 0) as size_bytes,
                   ROUND(NVL(s.bytes, 0) / 1024 / 1024, 2) as size_mb
            FROM dba_tab_partitions p
            LEFT JOIN dba_segments s
                ON s.owner = p.table_owner
                AND s.segment_name = p.table_name
                AND s.partition_name = p.partition_name
                AND s.segment_type = 'TABLE PARTITION'
            WHERE p.table_owner = :owner
              AND p.table_name = :table_name
            ORDER BY p.partition_position
        """
        try:
            df = TargetConnector.execute_query(database_id, query, {'owner': owner, 'table_name': table_name})
            if df.empty:
                return []
            parts = []
            for _, row in df.iterrows():
                parts.append({
                    'partition_name': row['PARTITION_NAME'],
                    'composite': row.get('COMPOSITE', 'NO'),
                    'compression': row.get('COMPRESSION', 'NONE'),
                    'compress_for': row.get('COMPRESS_FOR'),
                    'num_rows': _safe_int(row.get('NUM_ROWS')),
                    'blocks': _safe_int(row.get('BLOCKS')),
                    'size_bytes': _safe_int(row.get('SIZE_BYTES')),
                    'size_mb': _safe_float(row.get('SIZE_MB')),
                })
            return parts
        except Exception as e:
            log_warning(f"Failed to discover partitions for {owner}.{table_name}: {e}")
            return []

    @staticmethod
    def _discover_subpartitions(
        database_id: int, owner: str, table_name: str, partition_name: str
    ) -> List[Dict]:
        """Discover subpartitions within a partition on the target."""
        query = """
            SELECT sp.subpartition_name,
                   sp.compression, sp.compress_for,
                   sp.num_rows, sp.blocks,
                   NVL(s.bytes, 0) as size_bytes,
                   ROUND(NVL(s.bytes, 0) / 1024 / 1024, 2) as size_mb
            FROM dba_tab_subpartitions sp
            LEFT JOIN dba_segments s
                ON s.owner = sp.table_owner
                AND s.segment_name = sp.table_name
                AND s.partition_name = sp.subpartition_name
                AND s.segment_type = 'TABLE SUBPARTITION'
            WHERE sp.table_owner = :owner
              AND sp.table_name = :table_name
              AND sp.partition_name = :partition_name
            ORDER BY sp.subpartition_position
        """
        try:
            df = TargetConnector.execute_query(
                database_id, query,
                {'owner': owner, 'table_name': table_name, 'partition_name': partition_name}
            )
            if df.empty:
                return []
            subparts = []
            for _, row in df.iterrows():
                subparts.append({
                    'subpartition_name': row['SUBPARTITION_NAME'],
                    'compression': row.get('COMPRESSION', 'NONE'),
                    'compress_for': row.get('COMPRESS_FOR'),
                    'num_rows': _safe_int(row.get('NUM_ROWS')),
                    'blocks': _safe_int(row.get('BLOCKS')),
                    'size_bytes': _safe_int(row.get('SIZE_BYTES')),
                    'size_mb': _safe_float(row.get('SIZE_MB')),
                })
            return subparts
        except Exception as e:
            log_warning(f"Failed to discover subpartitions for {owner}.{table_name}.{partition_name}: {e}")
            return []

    @staticmethod
    def _get_batch_partition_dml_stats(
        database_id: int, owner: str, table_name: str
    ) -> Dict[str, Dict]:
        """Fetch partition-level DML stats. Returns dict keyed by partition_name."""
        import math

        query = """
            SELECT partition_name,
                   NVL(inserts, 0) as inserts,
                   NVL(updates, 0) as updates,
                   NVL(deletes, 0) as deletes
            FROM all_tab_modifications
            WHERE table_owner = :owner
              AND table_name = :table_name
              AND partition_name IS NOT NULL
              AND subpartition_name IS NULL
        """
        try:
            df = TargetConnector.execute_query(
                database_id, query, {'owner': owner, 'table_name': table_name}
            )
            raw = {}
            if not df.empty:
                for _, row in df.iterrows():
                    pname = row['PARTITION_NAME']
                    ins = int(row.get('INSERTS', 0) or 0)
                    upd = int(row.get('UPDATES', 0) or 0)
                    dlt = int(row.get('DELETES', 0) or 0)
                    raw[pname] = {'inserts': ins, 'updates': upd, 'deletes': dlt,
                                  'total_dml': ins + upd + dlt}

            # Log-relative hotness normalization
            max_dml = max((v['total_dml'] for v in raw.values()), default=0)
            log_max = math.log10(max_dml + 1) if max_dml > 0 else 1
            for key, v in raw.items():
                total = v['total_dml']
                if total > 0 and max_dml > 0:
                    v['hotness_score'] = round((math.log10(total + 1) / log_max) * 100, 2)
                else:
                    v['hotness_score'] = 0

            return raw
        except Exception:
            return {}

    @staticmethod
    def _get_compression_ratios_ctas(
        database_id: int, owner: str, table_name: str, sample_rows: int = 5000
    ) -> Dict[str, float]:
        """Fallback: measure BASIC/OLTP compression ratios via CTAS sampling.

        Only used when DBMS_COMPRESSION is unavailable (e.g., Oracle Free).
        Creates small temp tables from a row sample, compares segment sizes.

        Args:
            database_id: Target database identifier
            owner: Schema owner
            table_name: Table name
            sample_rows: Number of rows to sample (default 5000)
        """
        plsql = """
        DECLARE
            v_orig_bytes NUMBER;
            v_basic_bytes NUMBER;
            v_oltp_bytes NUMBER;
            v_fqn VARCHAR2(261) := :owner || '.' || :table_name;
            v_sample NUMBER := :sample_rows;
        BEGIN
            BEGIN EXECUTE IMMEDIATE 'DROP TABLE TMP_CMP_UNC PURGE'; EXCEPTION WHEN OTHERS THEN NULL; END;
            BEGIN EXECUTE IMMEDIATE 'DROP TABLE TMP_CMP_BAS PURGE'; EXCEPTION WHEN OTHERS THEN NULL; END;
            BEGIN EXECUTE IMMEDIATE 'DROP TABLE TMP_CMP_OLT PURGE'; EXCEPTION WHEN OTHERS THEN NULL; END;

            EXECUTE IMMEDIATE 'CREATE TABLE TMP_CMP_UNC NOCOMPRESS AS SELECT * FROM ' || v_fqn || ' WHERE ROWNUM <= ' || v_sample;
            EXECUTE IMMEDIATE 'CREATE TABLE TMP_CMP_BAS COMPRESS BASIC AS SELECT * FROM ' || v_fqn || ' WHERE ROWNUM <= ' || v_sample;
            EXECUTE IMMEDIATE 'CREATE TABLE TMP_CMP_OLT ROW STORE COMPRESS ADVANCED AS SELECT * FROM ' || v_fqn || ' WHERE ROWNUM <= ' || v_sample;

            SELECT bytes INTO v_orig_bytes FROM user_segments WHERE segment_name = 'TMP_CMP_UNC';
            SELECT bytes INTO v_basic_bytes FROM user_segments WHERE segment_name = 'TMP_CMP_BAS';
            SELECT bytes INTO v_oltp_bytes FROM user_segments WHERE segment_name = 'TMP_CMP_OLT';

            :basic_ratio := ROUND(v_orig_bytes / NULLIF(v_basic_bytes, 0), 2);
            :oltp_ratio := ROUND(v_orig_bytes / NULLIF(v_oltp_bytes, 0), 2);

            EXECUTE IMMEDIATE 'DROP TABLE TMP_CMP_UNC PURGE';
            EXECUTE IMMEDIATE 'DROP TABLE TMP_CMP_BAS PURGE';
            EXECUTE IMMEDIATE 'DROP TABLE TMP_CMP_OLT PURGE';
        EXCEPTION
            WHEN OTHERS THEN
                BEGIN EXECUTE IMMEDIATE 'DROP TABLE TMP_CMP_UNC PURGE'; EXCEPTION WHEN OTHERS THEN NULL; END;
                BEGIN EXECUTE IMMEDIATE 'DROP TABLE TMP_CMP_BAS PURGE'; EXCEPTION WHEN OTHERS THEN NULL; END;
                BEGIN EXECUTE IMMEDIATE 'DROP TABLE TMP_CMP_OLT PURGE'; EXCEPTION WHEN OTHERS THEN NULL; END;
                :basic_ratio := 1;
                :oltp_ratio := 1;
        END;
        """

        try:
            result = TargetConnector.execute_procedure_with_output(
                database_id, plsql,
                in_params={'owner': owner, 'table_name': table_name, 'sample_rows': sample_rows},
                out_params={'basic_ratio': float, 'oltp_ratio': float}
            )
            return {
                'basic': result.get('basic_ratio') or 1,
                'oltp': result.get('oltp_ratio') or 1,
            }
        except Exception as e:
            log_warning(f"CTAS compression ratio fallback failed for {owner}.{table_name}: {e}")
            return {'basic': 1, 'oltp': 1}

    @staticmethod
    def _get_batch_dml_stats(database_id: int, owner: Optional[str] = None) -> Dict[str, Dict]:
        """Batch-fetch DML activity for all tables in scope.

        Returns dict keyed by 'OWNER.TABLE_NAME' with values:
            {inserts, updates, deletes, total_dml, hotness_score}

        Hotness is computed as a relative score (0-100) where the table with
        the highest cumulative DML in the batch gets 100 and others scale
        proportionally using log-relative normalization. This ensures tables
        with >1M DML are still differentiated by their relative activity.
        """
        import math

        if owner:
            query = """
                SELECT table_owner, table_name,
                       NVL(inserts, 0) as inserts,
                       NVL(updates, 0) as updates,
                       NVL(deletes, 0) as deletes
                FROM all_tab_modifications
                WHERE table_owner = :owner AND partition_name IS NULL
            """
            params = {'owner': owner.upper()}
        else:
            query = """
                SELECT table_owner, table_name,
                       NVL(inserts, 0) as inserts,
                       NVL(updates, 0) as updates,
                       NVL(deletes, 0) as deletes
                FROM all_tab_modifications
                WHERE partition_name IS NULL
            """
            params = None

        try:
            df = TargetConnector.execute_query(database_id, query, params)
            raw = {}
            if not df.empty:
                for _, row in df.iterrows():
                    key = f"{row['TABLE_OWNER']}.{row['TABLE_NAME']}"
                    ins = int(row.get('INSERTS', 0) or 0)
                    upd = int(row.get('UPDATES', 0) or 0)
                    dlt = int(row.get('DELETES', 0) or 0)
                    raw[key] = {'inserts': ins, 'updates': upd, 'deletes': dlt,
                                'total_dml': ins + upd + dlt}

            # Compute relative hotness: normalize against the max DML in the batch
            max_dml = max((v['total_dml'] for v in raw.values()), default=0)
            log_max = math.log10(max_dml + 1) if max_dml > 0 else 1

            for key, v in raw.items():
                total = v['total_dml']
                if total > 0 and max_dml > 0:
                    # Log-relative: preserves order, spreads values across 0-100
                    v['hotness_score'] = round(
                        (math.log10(total + 1) / log_max) * 100, 2
                    )
                else:
                    v['hotness_score'] = 0

            return raw
        except Exception:
            return {}

    @staticmethod
    def _get_batch_table_stats(database_id: int, owner: Optional[str] = None) -> Dict[str, Dict]:
        """Batch-fetch column-level statistics to enrich compression recommendations.

        Queries dba_tab_col_statistics to compute per-table metrics:
        - avg_null_pct:  average NULL ratio across all columns (high = compresses well)
        - avg_distinct:  average number of distinct values (low = compresses well)
        - num_columns:   total column count

        Returns dict keyed by 'OWNER.TABLE_NAME'.
        """
        owner_filter = "WHERE c.owner = :owner" if owner else ""
        params = {'owner': owner.upper()} if owner else None

        query = f"""
            SELECT c.owner, c.table_name,
                   COUNT(*)                                             AS num_columns,
                   ROUND(AVG(CASE WHEN c.num_nulls IS NOT NULL AND t.num_rows > 0
                                  THEN c.num_nulls / t.num_rows ELSE 0 END), 4)
                                                                        AS avg_null_pct,
                   ROUND(AVG(NVL(c.num_distinct, 0)), 0)               AS avg_distinct
            FROM dba_tab_col_statistics c
            JOIN all_tables t ON t.owner = c.owner AND t.table_name = c.table_name
            {owner_filter}
            GROUP BY c.owner, c.table_name
        """

        try:
            df = TargetConnector.execute_query(database_id, query, params)
            result = {}
            if not df.empty:
                for _, row in df.iterrows():
                    key = f"{row['OWNER']}.{row['TABLE_NAME']}"
                    result[key] = {
                        'num_columns': int(row.get('NUM_COLUMNS') or 0),
                        'avg_null_pct': float(row.get('AVG_NULL_PCT') or 0),
                        'avg_distinct': float(row.get('AVG_DISTINCT') or 0),
                    }
            return result
        except Exception:
            return {}

    # DBMS_COMPRESSION type constants
    _COMP_TYPE_CONST = {
        'BASIC': 4096, 'OLTP': 2,
        'QUERY LOW': 4, 'QUERY HIGH': 8,
        'ARCHIVE LOW': 16, 'ARCHIVE HIGH': 32,
    }

    @staticmethod
    def _determine_target_compression(
        rules: List[Dict],
        object_type: str,
        hotness_score: float,
        table_stats: Optional[Dict[str, Any]] = None,
        platform_type: str = 'STANDARD'
    ) -> str:
        """Determine the target compression type from hotness + table stats BEFORE
        testing the actual compression ratio. This avoids testing all 6 types.

        Hotness bands (never BASIC):
            >85  → NONE (very hot, not a candidate)
            65-85 → OLTP
            45-64 → QUERY LOW
            25-44 → QUERY HIGH
            10-24 → ARCHIVE LOW
            <10  → ARCHIVE HIGH
        """
        stats = table_stats or {}

        # --- Compute effective hotness adjusting for table statistics ---
        effective_hotness = hotness_score

        last_analyzed = stats.get('last_analyzed')
        if last_analyzed:
            from datetime import datetime, date
            try:
                if isinstance(last_analyzed, (datetime, date)):
                    la = last_analyzed if isinstance(last_analyzed, datetime) \
                        else datetime.combine(last_analyzed, datetime.min.time())
                    age_days = (datetime.now() - la).days
                else:
                    age_days = 0
                if age_days > 365:
                    effective_hotness = max(0, effective_hotness - 30)
                elif age_days > 90:
                    effective_hotness = max(0, effective_hotness - 15)
            except Exception:
                pass

        avg_null_pct = stats.get('avg_null_pct', 0) or 0
        if avg_null_pct > 0.5:
            effective_hotness = max(0, effective_hotness - 10)
        elif avg_null_pct > 0.3:
            effective_hotness = max(0, effective_hotness - 5)

        avg_distinct = stats.get('avg_distinct', 0) or 0
        num_rows = stats.get('num_rows', 0) or 0
        if num_rows > 0 and avg_distinct > 0:
            if (avg_distinct / num_rows) < 0.01:
                effective_hotness = max(0, effective_hotness - 10)
            elif (avg_distinct / num_rows) < 0.1:
                effective_hotness = max(0, effective_hotness - 5)

        if (stats.get('avg_row_len', 0) or 0) > 500:
            effective_hotness = max(0, effective_hotness - 5)

        # --- Try strategy rules first (ignore ratio since we don't have one yet) ---
        for rule in rules:
            if rule.get('object_type') == object_type:
                if rule.get('hotness_min', 0) <= effective_hotness <= rule.get('hotness_max', 100):
                    comp_type = rule['compression_type']
                    if comp_type == 'BASIC':
                        comp_type = 'OLTP'  # never BASIC
                    if comp_type != 'NONE':
                        # On non-Exadata, HCC types fall back to OLTP
                        if platform_type != 'EXADATA' and comp_type in ('QUERY LOW', 'QUERY HIGH', 'ARCHIVE LOW', 'ARCHIVE HIGH'):
                            return 'OLTP'
                        return comp_type

        # --- Default hotness bands ---
        if effective_hotness > 85:
            return 'NONE'
        elif effective_hotness >= 65:
            return 'OLTP'
        elif effective_hotness >= 45:
            target = 'QUERY LOW'
        elif effective_hotness >= 25:
            target = 'QUERY HIGH'
        elif effective_hotness >= 10:
            target = 'ARCHIVE LOW'
        else:
            target = 'ARCHIVE HIGH'

        # On non-Exadata, HCC falls back to OLTP
        if platform_type != 'EXADATA' and target in ('QUERY LOW', 'QUERY HIGH', 'ARCHIVE LOW', 'ARCHIVE HIGH'):
            return 'OLTP'
        return target

    @staticmethod
    def _get_single_compression_ratio(
        database_id: int, owner: str, table_name: str,
        compression_type: str,
        partition_name: Optional[str] = None
    ) -> float:
        """Test a single compression type via DBMS_COMPRESSION.GET_COMPRESSION_RATIO.

        Returns the compression ratio (>1 = effective), or 1.0 on failure.
        """
        comp_const = TargetQueries._COMP_TYPE_CONST.get(compression_type)
        if not comp_const:
            return 1.0

        plsql = """
        DECLARE
            v_tbs VARCHAR2(128);
            v_bc PLS_INTEGER; v_bu PLS_INTEGER;
            v_rc PLS_INTEGER; v_ru PLS_INTEGER;
            v_ratio NUMBER; v_str VARCHAR2(100);
        BEGIN
            SELECT default_tablespace INTO v_tbs FROM dba_users WHERE username = :owner;
            DBMS_COMPRESSION.GET_COMPRESSION_RATIO(
                v_tbs, :owner, :table_name, :partition_name, :comp_type,
                v_bc, v_bu, v_rc, v_ru, v_ratio, v_str);
            :out_ratio := ROUND(v_ratio, 2);
        EXCEPTION
            WHEN OTHERS THEN :out_ratio := -1;
        END;
        """

        try:
            result = TargetConnector.execute_procedure_with_output(
                database_id, plsql,
                in_params={
                    'owner': owner, 'table_name': table_name,
                    'partition_name': partition_name, 'comp_type': comp_const
                },
                out_params={'out_ratio': float}
            )
            ratio = result.get('out_ratio', 1.0) or 1.0
            if ratio < 0:
                # DBMS_COMPRESSION failed — try CTAS fallback for OLTP
                if compression_type == 'OLTP':
                    fallback = TargetQueries._get_compression_ratios_ctas(
                        database_id, owner, table_name
                    )
                    return fallback.get('oltp', 1.0)
                return 1.0
            return ratio
        except Exception:
            return 1.0

    # Map from compression type to ratio dict key
    _COMP_TYPE_RATIO_KEY = {
        'BASIC': 'basic', 'OLTP': 'oltp',
        'QUERY LOW': 'query_low', 'QUERY HIGH': 'query_high',
        'ARCHIVE LOW': 'archive_low', 'ARCHIVE HIGH': 'archive_high',
    }

    @staticmethod
    def _generate_rationale(
        size_mb: float, hotness_score: float, ratios: Dict[str, Any],
        recommended: str, table_stats: Optional[Dict[str, Any]] = None
    ) -> str:
        """Generate human-readable rationale for compression recommendation."""
        stats = table_stats or {}
        parts = [f'Size: {size_mb:.2f} MB']
        if hotness_score > 0:
            label = 'High DML' if hotness_score > 70 else ('Moderate DML' if hotness_score > 30 else 'Low DML')
            parts.append(f'Hotness: {hotness_score}/100 ({label})')

        # Table statistics context
        stat_notes = []
        avg_null_pct = stats.get('avg_null_pct', 0)
        if avg_null_pct > 0.3:
            stat_notes.append(f'High NULL density ({avg_null_pct:.0%})')
        avg_row_len = stats.get('avg_row_len', 0)
        if avg_row_len > 500:
            stat_notes.append(f'Wide rows ({avg_row_len}B avg)')
        num_rows = stats.get('num_rows', 0)
        avg_distinct = stats.get('avg_distinct', 0)
        if num_rows > 0 and avg_distinct > 0 and (avg_distinct / num_rows) < 0.01:
            stat_notes.append('Low cardinality (repetitive data)')
        if stat_notes:
            parts.append('Stats: ' + ', '.join(stat_notes))

        # Show all available compression ratios
        ratio_strs = []
        for key, label in [('basic', 'BASIC'), ('oltp', 'OLTP'), ('query_low', 'QUERY LOW'),
                           ('query_high', 'QUERY HIGH'), ('archive_low', 'ARCHIVE LOW'),
                           ('archive_high', 'ARCHIVE HIGH')]:
            val = ratios.get(key)
            if val and val > 0:
                ratio_strs.append(f'{label} {val:.2f}:1')
        if ratio_strs:
            parts.append('Ratios: ' + ', '.join(ratio_strs))

        labels = {
            'NONE': 'No compression recommended (ratio too low or high DML)',
            'BASIC': 'Basic compression (moderate ratio, acceptable overhead)',
            'OLTP': 'OLTP compression (good ratio, optimized for DML)',
            'QUERY LOW': 'HCC Query Low (columnar, optimized for queries)',
            'QUERY HIGH': 'HCC Query High (maximum columnar query compression)',
            'ARCHIVE LOW': 'HCC Archive Low (columnar, optimized for archival)',
            'ARCHIVE HIGH': 'HCC Archive High (maximum compression)',
        }
        parts.append(labels.get(recommended, f'Compression: {recommended}'))
        return '; '.join(parts)

    @staticmethod
    def _complete_advisor_run(
        run_id: int,
        tables_analyzed: int,
        tables_failed: int,
        results: list,
        start_time: float
    ):
        """Update advisor run record as completed in central DB"""
        import time
        from hcc_advisor.utils.central_connector import CentralConnector

        elapsed = time.time() - start_time
        total_size = sum(r.get('SIZE_BYTES', 0) or 0 for r in results) / 1024 / 1024 if results else 0
        total_savings = sum(r.get('PROJECTED_SAVINGS_BYTES', 0) or 0 for r in results) / 1024 / 1024 if results else 0
        savings_pct = round((total_savings / total_size) * 100, 2) if total_size > 0 else 0

        rec_counts = {'NONE': 0, 'BASIC': 0, 'OLTP': 0}
        hcc_low_count = 0  # QUERY LOW + ARCHIVE LOW
        hcc_high_count = 0  # QUERY HIGH + ARCHIVE HIGH
        for r in (results or []):
            rec = r.get('ADVISABLE_COMPRESSION', 'NONE')
            if rec in rec_counts:
                rec_counts[rec] += 1
            elif rec in ('QUERY LOW', 'ARCHIVE LOW'):
                hcc_low_count += 1
            elif rec in ('QUERY HIGH', 'ARCHIVE HIGH'):
                hcc_high_count += 1

        try:
            CentralConnector.execute_dml("""
                UPDATE t_advisor_run SET
                    end_time = SYSTIMESTAMP,
                    duration_minutes = :dur,
                    run_status = 'COMPLETED',
                    objects_analyzed = :analyzed,
                    objects_succeeded = :succeeded,
                    objects_failed = :failed,
                    total_size_mb = :total_size,
                    projected_savings_mb = :savings,
                    projected_savings_pct = :savings_pct,
                    recommend_none = :r_none,
                    recommend_basic = :r_basic,
                    recommend_oltp = :r_oltp,
                    recommend_adv_low = :r_adv_low,
                    recommend_adv_high = :r_adv_high
                WHERE run_id = :run_id
            """, {
                'run_id': run_id,
                'dur': round(elapsed / 60, 2),
                'analyzed': tables_analyzed + tables_failed,
                'succeeded': tables_analyzed,
                'failed': tables_failed,
                'total_size': round(total_size, 2),
                'savings': round(total_savings, 2),
                'savings_pct': savings_pct,
                'r_none': rec_counts.get('NONE', 0),
                'r_basic': rec_counts.get('BASIC', 0),
                'r_oltp': rec_counts.get('OLTP', 0),
                'r_adv_low': hcc_low_count,
                'r_adv_high': hcc_high_count,
            })
        except Exception as e:
            log_error(e, "_complete_advisor_run", {'run_id': run_id})

    @staticmethod
    def pull_analysis_results(
        database_id: int,
        run_id: Optional[int] = None
    ) -> pd.DataFrame:
        """
        Read analysis results from the target's t_compression_analysis table.
        Used to pull results from target for storage in the central DB.

        Args:
            database_id: Target database identifier
            run_id: Specific advisor_run_id to filter (None = latest run)

        Returns:
            DataFrame with analysis results from the target
        """
        if run_id is None:
            # Get latest run_id from target
            latest_query = "SELECT MAX(run_id) as run_id FROM t_advisor_run"
            try:
                latest_df = TargetConnector.execute_query(database_id, latest_query)
                if not latest_df.empty and latest_df.iloc[0]['RUN_ID'] is not None:
                    run_id = int(latest_df.iloc[0]['RUN_ID'])
                else:
                    log_warning(f"No advisor runs found on target db_id={database_id}")
                    return pd.DataFrame()
            except Exception as e:
                log_error(e, "TargetQueries.pull_analysis_results (get latest run_id)", {
                    'database_id': database_id
                })
                return pd.DataFrame()

        query = """
            SELECT
                analysis_id,
                advisor_run_id as run_id,
                owner,
                object_name,
                object_type,
                partition_name,
                subpartition_name,
                size_mb,
                row_count,
                current_compression,
                advisable_compression,
                best_ratio,
                projected_savings_mb,
                projected_savings_pct,
                hotness_score,
                last_analyzed,
                recommendation_reason
            FROM t_compression_analysis
            WHERE advisor_run_id = :run_id
            ORDER BY projected_savings_mb DESC
        """

        try:
            return TargetConnector.execute_query(database_id, query, {'run_id': run_id})
        except Exception as e:
            log_error(e, "TargetQueries.pull_analysis_results", {
                'database_id': database_id,
                'run_id': run_id
            })
            st.error(f"Failed to pull analysis results from target db_id={database_id}: {e}")
            return pd.DataFrame()

    @staticmethod
    def pull_advisor_run(
        database_id: int,
        run_id: Optional[int] = None
    ) -> Dict[str, Any]:
        """
        Read a specific run or the latest run from the target's t_advisor_run.
        Used to pull run metadata for central storage.

        Args:
            database_id: Target database identifier
            run_id: Specific run_id to retrieve (None = latest run)

        Returns:
            Dict with run details
        """
        if run_id is not None:
            where_clause = "WHERE r.run_id = :run_id"
            params = {'run_id': run_id}
        else:
            where_clause = "WHERE r.run_id = (SELECT MAX(run_id) FROM t_advisor_run)"
            params = {}

        query = f"""
            SELECT
                r.run_id,
                r.start_time,
                r.end_time,
                r.run_status as status,
                r.schema_filter as owner_filter,
                r.objects_analyzed as tables_analyzed,
                r.objects_skipped,
                (r.recommend_basic + r.recommend_oltp + r.recommend_adv_low + r.recommend_adv_high) as candidates_found,
                r.recommend_basic,
                r.recommend_oltp,
                r.recommend_adv_low,
                r.recommend_adv_high,
                r.duration_minutes,
                r.total_size_mb,
                r.projected_savings_mb,
                r.projected_savings_pct,
                r.error_message
            FROM t_advisor_run r
            {where_clause}
        """

        try:
            df = TargetConnector.execute_query(database_id, query, params if params else None)
            if not df.empty:
                row = df.iloc[0]
                return {
                    'run_id': row.get('RUN_ID'),
                    'start_time': row.get('START_TIME'),
                    'end_time': row.get('END_TIME'),
                    'status': row.get('STATUS', 'UNKNOWN'),
                    'owner_filter': row.get('OWNER_FILTER'),
                    'tables_analyzed': int(row.get('TABLES_ANALYZED', 0) or 0),
                    'objects_skipped': int(row.get('OBJECTS_SKIPPED', 0) or 0),
                    'candidates_found': int(row.get('CANDIDATES_FOUND', 0) or 0),
                    'recommend_basic': int(row.get('RECOMMEND_BASIC', 0) or 0),
                    'recommend_oltp': int(row.get('RECOMMEND_OLTP', 0) or 0),
                    'recommend_adv_low': int(row.get('RECOMMEND_ADV_LOW', 0) or 0),
                    'recommend_adv_high': int(row.get('RECOMMEND_ADV_HIGH', 0) or 0),
                    'duration_minutes': float(row.get('DURATION_MINUTES', 0) or 0),
                    'total_size_mb': float(row.get('TOTAL_SIZE_MB', 0) or 0),
                    'projected_savings_mb': float(row.get('PROJECTED_SAVINGS_MB', 0) or 0),
                    'projected_savings_pct': float(row.get('PROJECTED_SAVINGS_PCT', 0) or 0),
                    'error_message': row.get('ERROR_MESSAGE')
                }
        except Exception as e:
            log_error(e, "TargetQueries.pull_advisor_run", {
                'database_id': database_id,
                'run_id': run_id
            })
            st.error(f"Failed to pull advisor run from target db_id={database_id}: {e}")

        return {}

    # ============================================================================
    # COMPRESSION EXECUTION (runs PL/SQL on target)
    # ============================================================================

    @staticmethod
    def execute_compression(
        database_id: int,
        owner: str,
        table_name: str,
        compression_type: str,
        partition_name: Optional[str] = None,
        dry_run: bool = True,
        parallel_degree: int = 4
    ) -> Dict[str, Any]:
        """
        Execute compression for a specific table or partition on the target database.

        Args:
            database_id: Target database identifier
            owner: Schema owner
            table_name: Table name
            compression_type: Target compression type
            partition_name: Optional partition name
            dry_run: If True, only generate DDL without executing
            parallel_degree: Parallel execution degree

        Returns:
            dict with execution result
        """
        # Handle None/NaN partition name
        if partition_name is not None and pd.isna(partition_name):
            partition_name = None

        if dry_run:
            ddl = TargetQueries.generate_ddl(
                owner, table_name, compression_type, partition_name,
                parallel_degree=parallel_degree
            )
            return {
                'success': True,
                'dry_run': True,
                'ddl': ddl,
                'message': 'DDL generated successfully (dry run)'
            }

        import time as _time
        from datetime import datetime
        from hcc_advisor.utils.central_queries import CentralQueries
        from hcc_advisor.utils.central_connector import CentralConnector

        ddl = TargetQueries.generate_ddl(
            owner, table_name, compression_type, partition_name,
            parallel_degree=parallel_degree
        )
        ddl_exec = ddl.rstrip().rstrip(';')

        # Pre-compression validation: check for LOB columns
        try:
            lob_q = """
                SELECT COUNT(*) as lob_count FROM all_tab_columns
                WHERE owner = :owner AND table_name = :table_name
                  AND data_type IN ('BLOB', 'CLOB', 'NCLOB', 'LONG')
            """
            lob_df = TargetConnector.execute_query(database_id, lob_q,
                                                   {'owner': owner, 'table_name': table_name})
            if not lob_df.empty and int(lob_df.iloc[0]['LOB_COUNT'] or 0) > 0:
                log_warning(f"{owner}.{table_name} has LOB columns — MOVE may need LOB storage clause")
        except Exception:
            pass

        # Get original size from target before compression
        orig_size = 0
        try:
            seg_q = """
                SELECT NVL(SUM(bytes), 0) as size_bytes
                FROM dba_segments WHERE owner = :owner AND segment_name = :table_name
            """
            seg_params = {'owner': owner, 'table_name': table_name}
            if partition_name:
                seg_q = """
                    SELECT NVL(SUM(bytes), 0) as size_bytes
                    FROM dba_segments WHERE owner = :owner AND segment_name = :table_name
                    AND partition_name = :partition_name
                """
                seg_params['partition_name'] = partition_name
            seg_df = TargetConnector.execute_query(database_id, seg_q, seg_params)
            if not seg_df.empty:
                orig_size = int(seg_df.iloc[0]['SIZE_BYTES'] or 0)
        except Exception:
            pass

        # Insert IN_PROGRESS history record
        start_dt = datetime.now()
        history_record = {
            'owner': owner,
            'object_name': table_name,
            'object_type': 'PARTITION' if partition_name else 'TABLE',
            'partition_name': partition_name,
            'compression_type_applied': compression_type,
            'compression_clause': ddl_exec,
            'execution_mode': 'ONLINE',
            'parallel_degree': parallel_degree,
            'original_size_bytes': orig_size,
            'operation_status': 'IN_PROGRESS',
            'start_time': start_dt,
            'executed_by': 'HCC_ADVISOR',
        }
        CentralQueries.store_compression_history(database_id, history_record)

        try:
            t0 = _time.perf_counter()
            success = TargetConnector.execute_plsql(
                database_id,
                f"BEGIN EXECUTE IMMEDIATE q'[{ddl_exec}]'; END;"
            )
            elapsed = _time.perf_counter() - t0

            if success:
                # Rebuild unusable indexes after ALTER TABLE MOVE
                idx_rebuilt = 0
                idx_time = 0
                try:
                    idx_q = """
                        SELECT owner, index_name FROM all_indexes
                        WHERE table_owner = :owner AND table_name = :table_name
                          AND status = 'UNUSABLE'
                    """
                    idx_params = {'owner': owner, 'table_name': table_name}
                    idx_df = TargetConnector.execute_query(database_id, idx_q, idx_params)
                    if not idx_df.empty:
                        it0 = _time.perf_counter()
                        for _, idx_row in idx_df.iterrows():
                            idx_owner = idx_row['OWNER']
                            idx_name = idx_row['INDEX_NAME']
                            try:
                                TargetConnector.execute_plsql(
                                    database_id,
                                    f"BEGIN EXECUTE IMMEDIATE 'ALTER INDEX {idx_owner}.{idx_name} REBUILD ONLINE PARALLEL {parallel_degree}'; END;"
                                )
                                idx_rebuilt += 1
                            except Exception:
                                log_warning(f"Failed to rebuild index {idx_owner}.{idx_name}")
                        idx_time = round(_time.perf_counter() - it0, 1)
                except Exception:
                    pass

                # Get compressed size
                comp_size = 0
                try:
                    seg_df2 = TargetConnector.execute_query(database_id, seg_q, seg_params)
                    if not seg_df2.empty:
                        comp_size = int(seg_df2.iloc[0]['SIZE_BYTES'] or 0)
                except Exception:
                    pass

                ratio = round(orig_size / comp_size, 2) if comp_size > 0 else None
                total_elapsed = round(elapsed + idx_time, 1)

                # Update history to SUCCESS
                CentralConnector.execute_dml("""
                    UPDATE t_compression_history
                    SET operation_status = 'SUCCESS',
                        end_time = SYSTIMESTAMP,
                        duration_seconds = :dur,
                        compressed_size_bytes = :comp_size,
                        compression_ratio_achieved = :ratio,
                        indexes_rebuilt_count = :idx_cnt,
                        index_rebuild_time_sec = :idx_time
                    WHERE owner = :owner AND object_name = :tbl
                      AND operation_status = 'IN_PROGRESS'
                      AND ROWNUM = 1
                """, {
                    'dur': total_elapsed, 'comp_size': comp_size,
                    'ratio': ratio, 'owner': owner, 'tbl': table_name,
                    'idx_cnt': idx_rebuilt, 'idx_time': idx_time
                })

                # Update analysis row to reflect new compression state
                try:
                    CentralConnector.execute_dml("""
                        UPDATE t_compression_analysis
                        SET current_compression = :comp_type,
                            size_bytes = :comp_size
                        WHERE database_id = :db_id AND owner = :owner
                          AND object_name = :tbl
                          AND NVL(partition_name, '~') = NVL(:part, '~')
                    """, {
                        'comp_type': compression_type, 'comp_size': comp_size,
                        'db_id': database_id, 'owner': owner,
                        'tbl': table_name, 'part': partition_name
                    })
                except Exception:
                    pass

                saved_mb = round((orig_size - comp_size) / 1048576, 2)
                idx_msg = f", {idx_rebuilt} indexes rebuilt" if idx_rebuilt else ""
                return {
                    'success': True,
                    'message': f"Compression completed in {total_elapsed:.0f}s, saved {saved_mb} MB{idx_msg}"
                }

            # DDL returned False — unknown failure
            CentralConnector.execute_dml("""
                UPDATE t_compression_history
                SET operation_status = 'FAILED', end_time = SYSTIMESTAMP,
                    duration_seconds = :dur, error_message = 'DDL execution returned failure'
                WHERE owner = :owner AND object_name = :tbl
                  AND operation_status = 'IN_PROGRESS' AND ROWNUM = 1
            """, {'dur': round(elapsed, 1), 'owner': owner, 'tbl': table_name})

        except Exception as e:
            # Update history to FAILED
            try:
                CentralConnector.execute_dml("""
                    UPDATE t_compression_history
                    SET operation_status = 'FAILED', end_time = SYSTIMESTAMP,
                        error_message = :err
                    WHERE owner = :owner AND object_name = :tbl
                      AND operation_status = 'IN_PROGRESS' AND ROWNUM = 1
                """, {'err': str(e)[:4000], 'owner': owner, 'tbl': table_name})
            except Exception:
                pass
            log_error(e, "TargetQueries.execute_compression", {
                'database_id': database_id, 'owner': owner,
                'table_name': table_name, 'compression_type': compression_type
            })
            return {'error': str(e)}

        return {'error': 'Execution failed'}

    @staticmethod
    def batch_execute(
        database_id: int,
        items: List[Dict],
        dry_run: bool = True,
        parallel_degree: int = 4,
        concurrency: int = 1
    ) -> Dict[str, Any]:
        """
        Execute compression for multiple items in batch on the target database.
        Uses ThreadPoolExecutor for concurrent table compression.

        Args:
            database_id: Target database identifier
            items: List of dicts, each with owner, table_name, compression_type,
                   and optional partition_name
            dry_run: If True, only generate DDL without executing
            parallel_degree: Parallel execution degree per table (PARALLEL N in DDL)
            concurrency: Number of tables to compress simultaneously

        Returns:
            dict with batch execution results
        """
        from concurrent.futures import ThreadPoolExecutor, as_completed

        def _compress_one(item):
            res = TargetQueries.execute_compression(
                database_id=database_id,
                owner=item.get('owner'),
                table_name=item.get('table_name'),
                compression_type=item.get('compression_type'),
                partition_name=item.get('partition_name'),
                dry_run=dry_run,
                parallel_degree=parallel_degree
            )
            return {
                'owner': item.get('owner'),
                'table_name': item.get('table_name'),
                'partition_name': item.get('partition_name'),
                'compression_type': item.get('compression_type'),
                'result': res
            }

        results = []
        success_count = 0
        error_count = 0

        max_workers = max(1, min(concurrency, len(items)))

        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {executor.submit(_compress_one, item): item for item in items}
            for future in as_completed(futures):
                entry = future.result()
                results.append(entry)
                if entry['result'].get('success'):
                    success_count += 1
                else:
                    error_count += 1

        return {
            'total': len(items),
            'success': success_count,
            'errors': error_count,
            'results': results,
            'message': f"Batch completed: {success_count} success, {error_count} errors"
        }

    @staticmethod
    def generate_ddl(
        owner: str,
        table_name: str,
        compression_type: str,
        partition_name: Optional[str] = None,
        subpartition_name: Optional[str] = None,
        parallel_degree: int = 4
    ) -> str:
        """
        Generate DDL statement for compression. Static utility - no database connection needed.

        Args:
            owner: Schema owner
            table_name: Table name
            compression_type: Target compression type
            partition_name: Optional partition name
            subpartition_name: Optional subpartition name
            parallel_degree: Parallel execution degree

        Returns:
            DDL statement string
        """
        # Map compression type to DDL clause
        compression_clause_map = {
            'NONE': 'NOCOMPRESS',
            'BASIC': 'COMPRESS BASIC',
            'OLTP': 'COMPRESS FOR OLTP',
            'ADV_LOW': 'COMPRESS FOR OLTP',  # Oracle 23c Free equivalent
            'ADV_HIGH': 'COMPRESS FOR OLTP',  # Oracle 23c Free equivalent
            'QUERY LOW': 'COMPRESS FOR QUERY LOW',
            'QUERY HIGH': 'COMPRESS FOR QUERY HIGH',
            'ARCHIVE LOW': 'COMPRESS FOR ARCHIVE LOW',
            'ARCHIVE HIGH': 'COMPRESS FOR ARCHIVE HIGH',
            # Alternate naming conventions
            'QUERY_LOW': 'COMPRESS FOR QUERY LOW',
            'QUERY_HIGH': 'COMPRESS FOR QUERY HIGH',
            'ARCHIVE_LOW': 'COMPRESS FOR ARCHIVE LOW',
            'ARCHIVE_HIGH': 'COMPRESS FOR ARCHIVE HIGH',
        }

        compression_clause = compression_clause_map.get(
            compression_type.upper() if compression_type else 'BASIC',
            f'COMPRESS FOR {compression_type}'
        )

        if subpartition_name:
            ddl = f"""ALTER TABLE {owner}.{table_name}
MOVE SUBPARTITION {subpartition_name}
{compression_clause}
ONLINE PARALLEL {parallel_degree};"""
        elif partition_name:
            ddl = f"""ALTER TABLE {owner}.{table_name}
MOVE PARTITION {partition_name}
{compression_clause}
ONLINE PARALLEL {parallel_degree};"""
        else:
            ddl = f"""ALTER TABLE {owner}.{table_name}
MOVE {compression_clause}
ONLINE PARALLEL {parallel_degree};"""

        return ddl

    # ============================================================================
    # TARGET DATABASE METADATA
    # ============================================================================

    @staticmethod
    def get_cpu_count(database_id: int) -> int:
        """Query CPU_COUNT from target database v$parameter."""
        try:
            df = TargetConnector.execute_query(
                database_id,
                "SELECT value FROM v$parameter WHERE name = 'cpu_count'"
            )
            if not df.empty:
                return int(df.iloc[0]['VALUE'])
        except Exception:
            pass
        return 8  # safe default

    @staticmethod
    def _safe_flush_monitoring_info(database_id: int) -> bool:
        """Call DBMS_STATS.FLUSH_DATABASE_MONITORING_INFO, silently skipping
        ORA-20000 (insufficient privileges). This flush only updates the DML
        counters in DBA_TAB_MODIFICATIONS — it does NOT affect column statistics
        or any data in dba_tab_col_statistics. Requires ANALYZE ANY privilege.

        Bypasses TargetConnector.get_connection because that wrapper logs every
        oracledb.Error before re-raising, which would drown the log in noisy
        tracebacks for the benign ORA-20000 case.
        """
        from hcc_advisor.utils.central_queries import CentralQueries
        db_info = CentralQueries.get_target_database(database_id)
        if not db_info:
            return False

        connection = None
        try:
            pool = TargetConnector.get_pool(database_id, db_info)
            connection = pool.acquire()
            cursor = connection.cursor()
            try:
                cursor.execute("BEGIN DBMS_STATS.FLUSH_DATABASE_MONITORING_INFO; END;")
                log_info(f"[Target db_id={database_id}] Flushed monitoring info")
                return True
            finally:
                cursor.close()
        except Exception as e:
            # ORA-20000 (insufficient privileges) is expected when user lacks
            # ANALYZE ANY; silently continue without flushing — DML counts will
            # still be read from DBA_TAB_MODIFICATIONS (just slightly stale).
            err_str = str(e)
            if 'ORA-20000' in err_str or 'ORA-01031' in err_str:
                log_debug(f"[Target db_id={database_id}] FLUSH_DATABASE_MONITORING_INFO "
                          "skipped (missing ANALYZE ANY privilege); using cached DML counts")
            else:
                log_warning(f"[Target db_id={database_id}] Flush monitoring info failed: {err_str[:200]}")
            return False
        finally:
            if connection is not None:
                try:
                    pool.release(connection)
                except Exception:
                    pass

    # ============================================================================
    # SCHEMA DISCOVERY (queries target data dictionary)
    # ============================================================================

    @staticmethod
    def get_available_schemas(database_id: int) -> List[str]:
        """
        Get list of schemas with tables that can be analyzed on the target database.

        Args:
            database_id: Target database identifier

        Returns:
            List of schema names
        """
        query = """
            SELECT DISTINCT owner
            FROM all_tables
            WHERE owner NOT IN (
                'SYS', 'SYSTEM', 'OUTLN', 'DIP', 'ORACLE_OCM',
                'DBSNMP', 'APPQOSSYS', 'WMSYS', 'EXFSYS', 'CTXSYS',
                'XDB', 'ANONYMOUS', 'MDSYS', 'ORDDATA', 'ORDPLUGINS',
                'SI_INFORMTN_SCHEMA', 'OLAPSYS', 'MDDATA', 'SPATIAL_WFS_ADMIN_USR',
                'SPATIAL_CSW_ADMIN_USR', 'ORDSYS', 'LBACSYS', 'XS$NULL'
            )
            ORDER BY owner
        """

        try:
            df = TargetConnector.execute_query(database_id, query)
            if not df.empty:
                return df['OWNER'].tolist()
        except Exception as e:
            log_error(e, "TargetQueries.get_available_schemas", {'database_id': database_id})
            st.error(f"Failed to get schemas from target db_id={database_id}: {e}")

        return []

    @staticmethod
    def get_tables_for_schema(database_id: int, owner: str) -> pd.DataFrame:
        """
        Get tables for a specific schema on the target database.

        Args:
            database_id: Target database identifier
            owner: Schema owner

        Returns:
            DataFrame with table information
        """
        query = """
            SELECT
                table_name,
                num_rows,
                blocks,
                ROUND(blocks * 8192 / 1024 / 1024, 2) as size_mb,
                compression,
                compress_for,
                last_analyzed
            FROM all_tables
            WHERE owner = :owner
            ORDER BY size_mb DESC NULLS LAST
        """

        try:
            return TargetConnector.execute_query(database_id, query, {'owner': owner.upper()})
        except Exception as e:
            log_error(e, "TargetQueries.get_tables_for_schema", {
                'database_id': database_id,
                'owner': owner
            })
            st.error(f"Failed to get tables from target db_id={database_id}: {e}")
            return pd.DataFrame()

    # ============================================================================
    # TABLE INTROSPECTION (queries target data dictionary)
    # ============================================================================

    @staticmethod
    def get_column_statistics(database_id: int, owner: str, table_name: str) -> pd.DataFrame:
        """
        Get column statistics from all_tab_col_statistics on the target database.

        Args:
            database_id: Target database identifier
            owner: Schema owner
            table_name: Table name

        Returns:
            DataFrame with column statistics
        """
        query = """
            SELECT
                column_name,
                num_distinct,
                low_value,
                high_value,
                density,
                num_nulls,
                num_buckets,
                sample_size,
                last_analyzed,
                avg_col_len,
                histogram,
                notes
            FROM all_tab_col_statistics
            WHERE owner = :owner
              AND table_name = :table_name
            ORDER BY column_id NULLS LAST, column_name
        """

        try:
            return TargetConnector.execute_query(database_id, query, {
                'owner': owner.upper(),
                'table_name': table_name.upper()
            })
        except Exception as e:
            log_error(e, "TargetQueries.get_column_statistics", {
                'database_id': database_id,
                'owner': owner,
                'table_name': table_name
            })
            st.error(f"Failed to get column statistics from target db_id={database_id}: {e}")
            return pd.DataFrame()

    @staticmethod
    def get_table_column_info(database_id: int, owner: str, table_name: str) -> pd.DataFrame:
        """
        Get table column information with data types and sizes from the target database.

        Args:
            database_id: Target database identifier
            owner: Schema owner
            table_name: Table name

        Returns:
            DataFrame with column info
        """
        query = """
            SELECT
                c.column_name,
                c.data_type,
                c.data_length,
                c.data_precision,
                c.data_scale,
                c.nullable,
                c.column_id,
                s.num_distinct,
                s.num_nulls,
                s.avg_col_len,
                s.histogram,
                CASE
                    WHEN c.data_type IN ('CLOB', 'BLOB', 'LONG', 'LONG RAW') THEN 'LOB - High compression potential'
                    WHEN c.data_type IN ('VARCHAR2', 'CHAR', 'NVARCHAR2', 'NCHAR') AND c.data_length > 100 THEN 'Text - Good for HCC'
                    WHEN c.data_type IN ('NUMBER', 'FLOAT', 'BINARY_FLOAT', 'BINARY_DOUBLE') THEN 'Numeric - Moderate compression'
                    WHEN c.data_type IN ('DATE', 'TIMESTAMP') THEN 'Temporal - Good compression'
                    ELSE 'Standard compression'
                END as compression_hint
            FROM all_tab_columns c
            LEFT JOIN all_tab_col_statistics s
                ON c.owner = s.owner
                AND c.table_name = s.table_name
                AND c.column_name = s.column_name
            WHERE c.owner = :owner
              AND c.table_name = :table_name
            ORDER BY c.column_id
        """

        try:
            return TargetConnector.execute_query(database_id, query, {
                'owner': owner.upper(),
                'table_name': table_name.upper()
            })
        except Exception as e:
            log_error(e, "TargetQueries.get_table_column_info", {
                'database_id': database_id,
                'owner': owner,
                'table_name': table_name
            })
            st.error(f"Failed to get column info from target db_id={database_id}: {e}")
            return pd.DataFrame()

    @staticmethod
    def get_table_tablespace(database_id: int, owner: str, table_name: str) -> Optional[str]:
        """
        Get tablespace name for a table on the target database.

        Args:
            database_id: Target database identifier
            owner: Schema owner
            table_name: Table name

        Returns:
            Tablespace name or None
        """
        query = """
            SELECT tablespace_name
            FROM all_tables
            WHERE owner = :owner
              AND table_name = :table_name
        """

        try:
            df = TargetConnector.execute_query(database_id, query, {
                'owner': owner.upper(),
                'table_name': table_name.upper()
            })
            if not df.empty:
                return df.iloc[0].get('TABLESPACE_NAME', None)
        except Exception as e:
            log_debug(f"Could not get tablespace from target db_id={database_id}: {e}")

        return None

    @staticmethod
    def get_segment_info(database_id: int, owner: str, segment_name: str) -> Dict[str, Any]:
        """
        Get segment storage information from dba_segments on the target database.

        Args:
            database_id: Target database identifier
            owner: Schema owner
            segment_name: Segment/table name

        Returns:
            dict with segment storage details
        """
        query = """
            SELECT
                segment_name,
                segment_type,
                tablespace_name,
                bytes,
                ROUND(bytes / 1024 / 1024, 2) as size_mb,
                ROUND(bytes / 1024 / 1024 / 1024, 4) as size_gb,
                blocks,
                extents,
                initial_extent,
                next_extent,
                pct_increase,
                buffer_pool
            FROM dba_segments
            WHERE owner = :owner
              AND segment_name = :segment_name
        """

        try:
            df = TargetConnector.execute_query(database_id, query, {
                'owner': owner.upper(),
                'segment_name': segment_name.upper()
            })
            if not df.empty:
                return df.iloc[0].to_dict()
        except Exception as e:
            log_error(e, "TargetQueries.get_segment_info", {
                'database_id': database_id,
                'owner': owner,
                'segment_name': segment_name
            })
            st.warning(f"Could not get segment info from target db_id={database_id}: {e}")

        return {}

    @staticmethod
    def get_table_activity(database_id: int, owner: str, table_name: str) -> Dict[str, Any]:
        """
        Get table modification/activity information from all_tab_modifications
        on the target database.

        Args:
            database_id: Target database identifier
            owner: Schema owner
            table_name: Table name

        Returns:
            dict with table activity metrics
        """
        query = """
            SELECT
                table_owner as owner,
                table_name,
                inserts,
                updates,
                deletes,
                timestamp as last_modified,
                truncated,
                drop_segments
            FROM all_tab_modifications
            WHERE table_owner = :owner
              AND table_name = :table_name
        """

        try:
            df = TargetConnector.execute_query(database_id, query, {
                'owner': owner.upper(),
                'table_name': table_name.upper()
            })
            if not df.empty:
                return df.iloc[0].to_dict()
        except Exception as e:
            # Table may not have pending modifications tracked
            log_debug(f"Could not get table activity from target db_id={database_id}: {e}")

        return {}

    @staticmethod
    def compare_strategies(database_id: int, owner: str, table_name: str) -> pd.DataFrame:
        """
        Compare all compression strategies for a specific table on the target database.
        Queries t_compression_analysis on target, with fallback to estimated table stats.

        Args:
            database_id: Target database identifier
            owner: Schema owner
            table_name: Table name

        Returns:
            DataFrame with strategy comparison
        """
        # Try to get actual analysis data from target
        try:
            query = """
                SELECT
                    advisable_compression as strategy,
                    size_mb as current_size_mb,
                    row_count,
                    size_mb - projected_savings_mb as estimated_size_mb,
                    projected_savings_pct as savings_pct,
                    best_ratio as compression_ratio,
                    size_mb / NULLIF(size_mb - projected_savings_mb, 0) as estimated_blocks
                FROM t_compression_analysis
                WHERE owner = :owner
                  AND object_name = :table_name
                  AND advisable_compression IS NOT NULL
            """

            df = TargetConnector.execute_query(database_id, query, {
                'owner': owner.upper(),
                'table_name': table_name.upper()
            })

            if not df.empty:
                return df
        except Exception:
            pass

        # Fallback: Get table info from target data dictionary and estimate
        try:
            table_query = """
                SELECT
                    num_rows,
                    blocks,
                    ROUND(blocks * 8192 / 1024 / 1024, 2) as size_mb
                FROM all_tables
                WHERE owner = :owner
                  AND table_name = :table_name
            """
            table_df = TargetConnector.execute_query(database_id, table_query, {
                'owner': owner.upper(),
                'table_name': table_name.upper()
            })

            if table_df.empty:
                return pd.DataFrame()

            row = table_df.iloc[0]
            current_size_mb = float(row.get('SIZE_MB', 0) or 0)
            row_count = int(row.get('NUM_ROWS', 0) or 0)
        except Exception as e:
            log_error(e, "TargetQueries.compare_strategies (fallback)", {
                'database_id': database_id,
                'owner': owner,
                'table_name': table_name
            })
            return pd.DataFrame()

        # Estimate savings for each strategy
        strategies = [
            ('QUERY LOW', 0.4, 4.0),
            ('QUERY HIGH', 0.6, 6.0),
            ('ARCHIVE LOW', 0.75, 8.0),
            ('ARCHIVE HIGH', 0.85, 12.0)
        ]

        results = []
        for strategy, savings_factor, ratio in strategies:
            estimated_size = current_size_mb * (1 - savings_factor)
            results.append({
                'strategy': strategy,
                'current_size_mb': current_size_mb,
                'row_count': row_count,
                'estimated_size_mb': estimated_size,
                'savings_pct': savings_factor * 100,
                'compression_ratio': ratio,
                'estimated_blocks': current_size_mb / max(estimated_size, 0.01)
            })

        return pd.DataFrame(results)

    # ============================================================================
    # SESSION MONITORING (queries target V$ views)
    # ============================================================================

    @staticmethod
    def get_session_longops(database_id: int, filter_compression: bool = True) -> pd.DataFrame:
        """
        Get long-running operations from v$session_longops on the target database.

        Args:
            database_id: Target database identifier
            filter_compression: Only show compression-related operations

        Returns:
            DataFrame with long ops data
        """
        if filter_compression:
            where_clause = """
                WHERE (
                    UPPER(opname) LIKE '%COMPRESS%'
                    OR UPPER(opname) LIKE '%ALTER%TABLE%'
                    OR UPPER(opname) LIKE '%MOVE%'
                    OR UPPER(opname) LIKE '%REBUILD%'
                    OR UPPER(message) LIKE '%COMPRESS%'
                )
                AND sofar < totalwork
            """
        else:
            where_clause = "WHERE sofar < totalwork"

        query = f"""
            SELECT
                sid,
                serial# as serial_num,
                opname,
                target,
                target_desc,
                sofar,
                totalwork,
                ROUND(sofar / NULLIF(totalwork, 0) * 100, 1) as pct_complete,
                units,
                start_time,
                last_update_time,
                elapsed_seconds,
                ROUND(elapsed_seconds / NULLIF(sofar / NULLIF(totalwork, 0), 0) * (1 - sofar / NULLIF(totalwork, 0)), 0) as time_remaining_sec,
                message,
                username,
                sql_id
            FROM v$session_longops
            {where_clause}
            ORDER BY start_time DESC
        """

        try:
            return TargetConnector.execute_query(database_id, query)
        except Exception as e:
            log_error(e, "TargetQueries.get_session_longops", {
                'database_id': database_id,
                'filter_compression': filter_compression
            })
            return pd.DataFrame()

    @staticmethod
    def get_compression_sessions(database_id: int) -> pd.DataFrame:
        """
        Get active sessions performing compression or MOVE operations on the target.
        Joins v$session with v$sql for SQL text and v$session_longops for progress.
        """
        query = """
            SELECT
                s.sid,
                s.serial# as serial_num,
                s.username,
                s.status,
                s.schemaname,
                s.osuser,
                s.program,
                s.module,
                s.action,
                s.sql_id,
                s.last_call_et as elapsed_seconds,
                s.wait_class,
                s.event,
                SUBSTR(sq.sql_text, 1, 300) as sql_text,
                lo.opname,
                lo.target as longops_target,
                ROUND(lo.sofar / NULLIF(lo.totalwork, 0) * 100, 1) as pct_complete,
                CASE WHEN lo.sofar > 0 AND lo.totalwork > 0 THEN
                    ROUND((lo.elapsed_seconds / (lo.sofar / lo.totalwork)
                           * (1 - lo.sofar / lo.totalwork)) / 60, 1)
                ELSE NULL END as remaining_minutes
            FROM v$session s
            LEFT JOIN v$sql sq ON sq.sql_id = s.sql_id AND sq.child_number = 0
            LEFT JOIN v$session_longops lo ON lo.sid = s.sid AND lo.serial# = s.serial#
                AND lo.sofar < lo.totalwork
            WHERE s.type = 'USER'
              AND s.status = 'ACTIVE'
              AND (
                  UPPER(NVL(sq.sql_text, '')) LIKE '%ALTER%TABLE%MOVE%'
                  OR UPPER(NVL(sq.sql_text, '')) LIKE '%COMPRESS%'
                  OR UPPER(NVL(sq.sql_text, '')) LIKE '%REBUILD%INDEX%'
                  OR UPPER(NVL(s.action, '')) LIKE '%COMPRESS%'
                  OR UPPER(NVL(s.action, '')) LIKE '%MOVE%'
                  OR UPPER(NVL(s.module, '')) LIKE '%DBMS_SCHEDULER%'
                  AND UPPER(NVL(sq.sql_text, '')) LIKE '%HCC%'
              )
            ORDER BY s.last_call_et DESC
        """

        try:
            return TargetConnector.execute_query(database_id, query)
        except Exception as e:
            log_error(e, "TargetQueries.get_compression_sessions", {'database_id': database_id})
            return pd.DataFrame()

    @staticmethod
    def get_all_active_longops(database_id: int) -> pd.DataFrame:
        """
        Get all active long operations on the target database (not just compression).

        Args:
            database_id: Target database identifier

        Returns:
            DataFrame with all active long ops
        """
        query = """
            SELECT
                sid,
                serial# as serial_num,
                opname,
                target,
                target_desc,
                sofar,
                totalwork,
                ROUND(sofar / NULLIF(totalwork, 0) * 100, 1) as pct_complete,
                units,
                start_time,
                last_update_time,
                elapsed_seconds,
                CASE
                    WHEN sofar > 0 AND totalwork > 0 THEN
                        ROUND(elapsed_seconds / (sofar / totalwork) * (1 - sofar / totalwork), 0)
                    ELSE NULL
                END as time_remaining_sec,
                message,
                username,
                sql_id
            FROM v$session_longops
            WHERE sofar < totalwork
              OR (sofar = totalwork AND last_update_time > SYSDATE - INTERVAL '5' MINUTE)
            ORDER BY start_time DESC
        """

        try:
            return TargetConnector.execute_query(database_id, query)
        except Exception as e:
            log_error(e, "TargetQueries.get_all_active_longops", {'database_id': database_id})
            return pd.DataFrame()

    @staticmethod
    def get_session_sql(database_id: int, sql_id: str) -> str:
        """
        Get SQL text for a given SQL ID from the target database.

        Args:
            database_id: Target database identifier
            sql_id: SQL identifier

        Returns:
            SQL text or empty string
        """
        query = """
            SELECT sql_fulltext
            FROM v$sql
            WHERE sql_id = :sql_id
            AND ROWNUM = 1
        """

        try:
            df = TargetConnector.execute_query(database_id, query, {'sql_id': sql_id})
            if not df.empty:
                return str(df.iloc[0].get('SQL_FULLTEXT', ''))
        except Exception as e:
            log_debug(f"Could not get SQL text from target db_id={database_id}: {e}")

        return ""

    @staticmethod
    def get_long_operations(database_id: int) -> pd.DataFrame:
        """
        Get long-running operations from v$session_longops on the target database
        (requires DBA privileges).

        Args:
            database_id: Target database identifier

        Returns:
            DataFrame with long operations progress
        """
        query = """
            SELECT
                sid,
                serial#,
                opname,
                target,
                target_desc,
                sofar,
                totalwork,
                units,
                ROUND(sofar / NULLIF(totalwork, 0) * 100, 1) as pct_complete,
                elapsed_seconds,
                time_remaining as seconds_remaining,
                message
            FROM v$session_longops
            WHERE sofar < totalwork
              AND opname NOT LIKE '%Gather%'
            ORDER BY start_time DESC
        """

        try:
            return TargetConnector.execute_query(database_id, query)
        except Exception as e:
            # May not have privileges to access V$SESSION_LONGOPS
            log_debug(f"Could not get long operations from target db_id={database_id}: {e}")
            return pd.DataFrame()


    # ============================================================================
    # COMPRESSION ROLLBACK
    # ============================================================================

    @staticmethod
    def rollback_compression(
        database_id: int, owner: str, table_name: str,
        partition_name: Optional[str] = None, parallel_degree: int = 4
    ) -> Dict[str, Any]:
        """Rollback compression by moving table to NOCOMPRESS."""
        from hcc_advisor.utils.central_connector import CentralConnector

        ddl = f"ALTER TABLE {owner}.{table_name}"
        if partition_name:
            ddl += f" MOVE PARTITION {partition_name} NOCOMPRESS ONLINE PARALLEL {parallel_degree}"
        else:
            ddl += f" MOVE NOCOMPRESS ONLINE PARALLEL {parallel_degree}"

        try:
            ok = TargetConnector.execute_plsql(
                database_id, f"BEGIN EXECUTE IMMEDIATE q'[{ddl}]'; END;"
            )
            if ok:
                # Rebuild unusable indexes
                idx_q = """
                    SELECT owner, index_name FROM all_indexes
                    WHERE table_owner = :o AND table_name = :t AND status = 'UNUSABLE'
                """
                idx_df = TargetConnector.execute_query(database_id, idx_q,
                                                       {'o': owner, 't': table_name})
                idx_count = 0
                if not idx_df.empty:
                    for _, r in idx_df.iterrows():
                        try:
                            TargetConnector.execute_plsql(database_id,
                                f"BEGIN EXECUTE IMMEDIATE 'ALTER INDEX {r['OWNER']}.{r['INDEX_NAME']} REBUILD ONLINE PARALLEL {parallel_degree}'; END;")
                            idx_count += 1
                        except Exception:
                            pass

                # Update history
                try:
                    CentralConnector.execute_dml("""
                        UPDATE t_compression_history
                        SET rollback_status = 'ROLLED_BACK'
                        WHERE database_id = :db AND owner = :o AND object_name = :t
                          AND operation_status = 'SUCCESS'
                          AND NVL(partition_name, '~') = NVL(:p, '~')
                          AND rollback_status IS NULL
                          AND ROWNUM = 1
                    """, {'db': database_id, 'o': owner, 't': table_name, 'p': partition_name})

                    CentralConnector.execute_dml("""
                        UPDATE t_compression_analysis
                        SET current_compression = 'NONE'
                        WHERE database_id = :db AND owner = :o AND object_name = :t
                          AND NVL(partition_name, '~') = NVL(:p, '~')
                    """, {'db': database_id, 'o': owner, 't': table_name, 'p': partition_name})
                except Exception:
                    pass

                msg = f"Rolled back to NOCOMPRESS"
                if idx_count:
                    msg += f", {idx_count} indexes rebuilt"
                return {'success': True, 'message': msg}
            return {'success': False, 'error': 'DDL execution failed'}
        except Exception as e:
            return {'success': False, 'error': str(e)}

    # ============================================================================
    # AWR/ASH INTEGRATION FOR HOTNESS (requires Diagnostics Pack license)
    # ============================================================================

    @staticmethod
    def get_awr_segment_stats(database_id: int, owner: Optional[str] = None) -> Dict[str, float]:
        """Query DBA_HIST_SEG_STAT for physical reads per segment.
        Returns dict keyed by 'OWNER.TABLE_NAME' with read_score 0-100.
        WARNING: Requires Oracle Diagnostics Pack license."""
        owner_filter = "AND s.obj#owner = :owner" if owner else ""
        params = {'owner': owner} if owner else {}

        query = f"""
            SELECT o.owner, o.object_name,
                   SUM(s.physical_reads_delta) as total_reads
            FROM dba_hist_seg_stat s
            JOIN dba_objects o ON o.object_id = s.obj#
            WHERE o.object_type = 'TABLE'
              AND s.snap_id > (SELECT MAX(snap_id) - 48 FROM dba_hist_snapshot)
              {owner_filter}
            GROUP BY o.owner, o.object_name
            HAVING SUM(s.physical_reads_delta) > 0
        """
        try:
            df = TargetConnector.execute_query(database_id, query, params if params else None)
            if df.empty:
                return {}
            import math
            max_reads = df['TOTAL_READS'].max()
            result = {}
            for _, r in df.iterrows():
                reads = float(r['TOTAL_READS'])
                score = (math.log10(reads + 1) / math.log10(max_reads + 1)) * 100 if max_reads > 0 else 0
                result[f"{r['OWNER']}.{r['OBJECT_NAME']}"] = round(score, 1)
            return result
        except Exception:
            return {}

    # ============================================================================
    # SCHEDULED RECURRING ANALYSIS
    # ============================================================================

    @staticmethod
    def create_recurring_scan_job(
        database_id: int, frequency: str = 'WEEKLY',
        owner: Optional[str] = None
    ) -> Dict[str, Any]:
        """Create a DBMS_SCHEDULER repeating job for periodic quick scan.
        frequency: DAILY, WEEKLY, MONTHLY"""
        import random
        from datetime import datetime

        repeat_map = {
            'DAILY': 'FREQ=DAILY;BYHOUR=2;BYMINUTE=0',
            'WEEKLY': 'FREQ=WEEKLY;BYDAY=SUN;BYHOUR=2;BYMINUTE=0',
            'MONTHLY': 'FREQ=MONTHLY;BYMONTHDAY=1;BYHOUR=2;BYMINUTE=0',
        }
        repeat_interval = repeat_map.get(frequency, repeat_map['WEEKLY'])
        job_name = f"HCC_RECURRING_SCAN_{random.randint(100,999)}"

        # The recurring job flushes monitoring + gathers fresh stats
        action = """
            BEGIN
                DBMS_STATS.FLUSH_DATABASE_MONITORING_INFO;
                DBMS_STATS.GATHER_DATABASE_STATS(options => 'GATHER STALE');
            END;
        """

        plsql = f"""
            BEGIN
                DBMS_SCHEDULER.CREATE_JOB(
                    job_name        => '{job_name}',
                    job_type        => 'PLSQL_BLOCK',
                    job_action      => q'[{action}]',
                    repeat_interval => '{repeat_interval}',
                    enabled         => TRUE,
                    auto_drop       => FALSE,
                    comments        => 'HCC Advisor: recurring stats refresh ({frequency})'
                );
            END;
        """
        try:
            ok = TargetConnector.execute_plsql(database_id, plsql)
            if ok:
                return {'success': True, 'job_name': job_name, 'frequency': frequency}
            return {'success': False, 'error': 'Job creation failed'}
        except Exception as e:
            return {'success': False, 'error': str(e)}

    @staticmethod
    def get_recurring_scan_jobs(database_id: int) -> pd.DataFrame:
        """List HCC recurring scan jobs on the target."""
        query = """
            SELECT job_name, enabled, state, comments,
                   repeat_interval,
                   TO_CHAR(last_start_date, 'YYYY-MM-DD HH24:MI') as last_run,
                   TO_CHAR(next_run_date, 'YYYY-MM-DD HH24:MI') as next_run
            FROM dba_scheduler_jobs
            WHERE job_name LIKE 'HCC_RECURRING%'
            ORDER BY job_name
        """
        try:
            return TargetConnector.execute_query(database_id, query)
        except Exception:
            return pd.DataFrame()

    @staticmethod
    def drop_recurring_scan_job(database_id: int, job_name: str) -> bool:
        """Drop a recurring scan job."""
        try:
            return TargetConnector.execute_plsql(
                database_id,
                f"BEGIN DBMS_SCHEDULER.DROP_JOB('{job_name}', force => TRUE); END;"
            )
        except Exception:
            return False

    # ============================================================================
    # QUICK SCAN — Hotness-only analysis (no DBMS_COMPRESSION)
    # ============================================================================

    @staticmethod
    def quick_scan(
        database_id: int,
        owner: Optional[str] = None,
        strategy_id: int = 2,
        include_partitions: bool = True
    ) -> List[Dict]:
        """Fast analysis using hotness + table stats only (no DBMS_COMPRESSION).
        Returns list of result dicts and MERGE-es them into t_compression_analysis."""
        import math
        from hcc_advisor.utils.central_queries import CentralQueries
        from hcc_advisor.utils.central_connector import CentralConnector

        db_info = CentralQueries.get_target_database(database_id)
        platform_type = (db_info.get('platform_type') or 'STANDARD').upper()

        # Load strategy rules
        strategy_rules = []
        try:
            rules_df = CentralConnector.execute_query("""
                SELECT object_type, compression_type,
                       NVL(hotness_min, 0) as hotness_min, NVL(hotness_max, 100) as hotness_max
                FROM t_strategy_rules WHERE strategy_id = :sid AND enabled_flag = 'Y'
                ORDER BY priority DESC
            """, {'sid': strategy_id})
            if not rules_df.empty:
                for _, r in rules_df.iterrows():
                    strategy_rules.append({
                        'object_type': r['OBJECT_TYPE'], 'compression_type': r['COMPRESSION_TYPE'],
                        'hotness_min': float(r['HOTNESS_MIN']), 'hotness_max': float(r['HOTNESS_MAX']),
                    })
        except Exception:
            pass

        # Flush monitoring info
        TargetQueries._safe_flush_monitoring_info(database_id)

        tables = TargetQueries._discover_analysis_tables(database_id, owner)
        if not tables:
            return []

        dml_stats = TargetQueries._get_batch_dml_stats(database_id, owner)
        col_stats = TargetQueries._get_batch_table_stats(database_id, owner)

        results = []
        for t in tables:
            tbl_owner, tbl_name = t['owner'], t['table_name']
            hkey = f"{tbl_owner}.{tbl_name}"
            dml = dml_stats.get(hkey, {})
            hotness = dml.get('hotness_score', 0) if isinstance(dml, dict) else 0
            cs = col_stats.get(hkey, {})
            ts = {
                'avg_row_len': t.get('avg_row_len', 0), 'last_analyzed': t.get('last_analyzed'),
                'num_rows': t.get('num_rows', 0), 'avg_null_pct': cs.get('avg_null_pct', 0),
                'avg_distinct': cs.get('avg_distinct', 0), 'num_columns': cs.get('num_columns', 0),
            }
            advised = TargetQueries._determine_target_compression(
                strategy_rules, 'TABLE', hotness, ts, platform_type)

            current_comp = t.get('compress_for') or t.get('compression', 'NONE')
            if current_comp in ('DISABLED', None, ''):
                current_comp = 'NONE'

            results.append({
                'OWNER': tbl_owner, 'OBJECT_NAME': tbl_name, 'OBJECT_TYPE': 'TABLE',
                'PARTITION_NAME': None, 'SUBPARTITION_NAME': None,
                'ORIGINAL_SIZE_BYTES': t['size_bytes'],
                'SIZE_BYTES': t['size_bytes'], 'ROW_COUNT': t.get('num_rows'),
                'BLOCK_COUNT': t.get('blocks'), 'AVG_ROW_LENGTH': t.get('avg_row_len'),
                'BASIC_RATIO': None, 'OLTP_RATIO': None, 'ADV_LOW_RATIO': None, 'ADV_HIGH_RATIO': None,
                'BLKCNT_UNCMP_BASIC': None, 'BLKCNT_CMP_BASIC': None,
                'BLKCNT_UNCMP_OLTP': None, 'BLKCNT_CMP_OLTP': None,
                'BLKCNT_UNCMP_ADV_LOW': None, 'BLKCNT_CMP_ADV_LOW': None,
                'BLKCNT_UNCMP_ADV_HIGH': None, 'BLKCNT_CMP_ADV_HIGH': None,
                'INSERT_COUNT': dml.get('inserts', 0) if isinstance(dml, dict) else 0,
                'UPDATE_COUNT': dml.get('updates', 0) if isinstance(dml, dict) else 0,
                'DELETE_COUNT': dml.get('deletes', 0) if isinstance(dml, dict) else 0,
                'LOGICAL_READS': None, 'PHYSICAL_READS': None,
                'ACCESS_FREQUENCY': None, 'LAST_ACCESS_DATE': None,
                'HOTNESS_SCORE': hotness, 'READ_RATIO': None, 'WRITE_RATIO': None,
                'DML_24H_RATE': None, 'LAST_ANALYZED': t.get('last_analyzed'),
                'DATA_AGE_DAYS': None, 'CURRENT_COMPRESSION': current_comp,
                'ADVISABLE_COMPRESSION': advised,
                'RECOMMENDATION_REASON': f'Quick scan: hotness={hotness:.0f}',
                'CONFIDENCE_SCORE': None,
                'PROJECTED_SAVINGS_BYTES': 0, 'PROJECTED_SAVINGS_PCT': 0,
                'ANALYSIS_DURATION_SEC': None, 'SAMPLE_SIZE_ROWS': None,
            })

            # Partition analysis
            if include_partitions and t.get('partitioned') == 'YES':
                parts = TargetQueries._discover_partitions(database_id, tbl_owner, tbl_name)
                part_dml = TargetQueries._get_batch_partition_dml_stats(database_id, tbl_owner, tbl_name)
                for p in parts:
                    is_composite = p.get('composite') == 'YES'

                    if is_composite:
                        # Composite partitions can't be MOVE'd (ORA-14257)
                        # List only their subpartitions
                        subs = TargetQueries._discover_subpartitions(
                            database_id, tbl_owner, tbl_name, p['partition_name'])
                        for sp in subs:
                            sa = TargetQueries._determine_target_compression(
                                strategy_rules, 'TABLE', 0, ts, platform_type)
                            sc = sp.get('compress_for') or sp.get('compression', 'NONE')
                            if sc in ('DISABLED', None, ''):
                                sc = 'NONE'
                            results.append({
                                'OWNER': tbl_owner, 'OBJECT_NAME': tbl_name,
                                'OBJECT_TYPE': 'SUBPARTITION',
                                'PARTITION_NAME': p['partition_name'],
                                'SUBPARTITION_NAME': sp['subpartition_name'],
                                'ORIGINAL_SIZE_BYTES': sp.get('size_bytes', 0),
                                'SIZE_BYTES': sp.get('size_bytes', 0), 'ROW_COUNT': sp.get('num_rows'),
                                'BLOCK_COUNT': sp.get('blocks'), 'AVG_ROW_LENGTH': None,
                                'BASIC_RATIO': None, 'OLTP_RATIO': None,
                                'ADV_LOW_RATIO': None, 'ADV_HIGH_RATIO': None,
                                'BLKCNT_UNCMP_BASIC': None, 'BLKCNT_CMP_BASIC': None,
                                'BLKCNT_UNCMP_OLTP': None, 'BLKCNT_CMP_OLTP': None,
                                'BLKCNT_UNCMP_ADV_LOW': None, 'BLKCNT_CMP_ADV_LOW': None,
                                'BLKCNT_UNCMP_ADV_HIGH': None, 'BLKCNT_CMP_ADV_HIGH': None,
                                'INSERT_COUNT': 0, 'UPDATE_COUNT': 0, 'DELETE_COUNT': 0,
                                'LOGICAL_READS': None, 'PHYSICAL_READS': None,
                                'ACCESS_FREQUENCY': None, 'LAST_ACCESS_DATE': None,
                                'HOTNESS_SCORE': 0, 'READ_RATIO': None, 'WRITE_RATIO': None,
                                'DML_24H_RATE': None, 'LAST_ANALYZED': None, 'DATA_AGE_DAYS': None,
                                'CURRENT_COMPRESSION': sc, 'ADVISABLE_COMPRESSION': sa,
                                'RECOMMENDATION_REASON': f'Quick scan subpartition of {p["partition_name"]}',
                                'CONFIDENCE_SCORE': None,
                                'PROJECTED_SAVINGS_BYTES': 0, 'PROJECTED_SAVINGS_PCT': 0,
                                'ANALYSIS_DURATION_SEC': None, 'SAMPLE_SIZE_ROWS': None,
                            })
                        continue  # Skip to next partition

                    # Non-composite partition — can be MOVE'd directly
                    ph = part_dml.get(p['partition_name'], {}).get('hotness_score', 0)
                    pa = TargetQueries._determine_target_compression(
                        strategy_rules, 'TABLE', ph, ts, platform_type)
                    pc = p.get('compress_for') or p.get('compression', 'NONE')
                    if pc in ('DISABLED', None, ''):
                        pc = 'NONE'
                    results.append({
                        'OWNER': tbl_owner, 'OBJECT_NAME': tbl_name, 'OBJECT_TYPE': 'PARTITION',
                        'PARTITION_NAME': p['partition_name'], 'SUBPARTITION_NAME': None,
                        'ORIGINAL_SIZE_BYTES': p.get('size_bytes', 0),
                        'SIZE_BYTES': p.get('size_bytes', 0), 'ROW_COUNT': p.get('num_rows'),
                        'BLOCK_COUNT': p.get('blocks'), 'AVG_ROW_LENGTH': None,
                        'BASIC_RATIO': None, 'OLTP_RATIO': None, 'ADV_LOW_RATIO': None, 'ADV_HIGH_RATIO': None,
                        'BLKCNT_UNCMP_BASIC': None, 'BLKCNT_CMP_BASIC': None,
                        'BLKCNT_UNCMP_OLTP': None, 'BLKCNT_CMP_OLTP': None,
                        'BLKCNT_UNCMP_ADV_LOW': None, 'BLKCNT_CMP_ADV_LOW': None,
                        'BLKCNT_UNCMP_ADV_HIGH': None, 'BLKCNT_CMP_ADV_HIGH': None,
                        'INSERT_COUNT': 0, 'UPDATE_COUNT': 0, 'DELETE_COUNT': 0,
                        'LOGICAL_READS': None, 'PHYSICAL_READS': None,
                        'ACCESS_FREQUENCY': None, 'LAST_ACCESS_DATE': None,
                        'HOTNESS_SCORE': ph, 'READ_RATIO': None, 'WRITE_RATIO': None,
                        'DML_24H_RATE': None, 'LAST_ANALYZED': None, 'DATA_AGE_DAYS': None,
                        'CURRENT_COMPRESSION': pc, 'ADVISABLE_COMPRESSION': pa,
                        'RECOMMENDATION_REASON': f'Quick scan partition: hotness={ph:.0f}',
                        'CONFIDENCE_SCORE': None,
                        'PROJECTED_SAVINGS_BYTES': 0, 'PROJECTED_SAVINGS_PCT': 0,
                        'ANALYSIS_DURATION_SEC': None, 'SAMPLE_SIZE_ROWS': None,
                    })

        # Create a lightweight run record for the quick scan
        if results:
            from datetime import datetime
            run_data = {
                'run_name': f'Quick Scan {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}',
                'run_type': 'TABLES',
                'schema_filter': owner,
                'strategy_id': strategy_id,
                'parallel_degree': 1,
                'analysis_mode': 'QUICK',
                'include_partitions': 'Y' if include_partitions else 'N'
            }
            ok, run_id = CentralQueries.store_advisor_run(database_id, run_data)
            if not ok or not run_id:
                run_id = None

            results_df = pd.DataFrame(results)
            CentralQueries.store_analysis_results(database_id, run_id, results_df)

        return results

    # ============================================================================
    # DBMS_SCHEDULER JOB SUBMISSION
    # ============================================================================

    @staticmethod
    def submit_compression_job(
        database_id: int, owner: str, table_name: str,
        compression_type: str, partition_name: Optional[str] = None,
        parallel_degree: int = 4
    ) -> Dict[str, Any]:
        """Submit ALTER TABLE MOVE as a DBMS_SCHEDULER job on the target database."""
        from datetime import datetime
        from hcc_advisor.utils.central_queries import CentralQueries
        from hcc_advisor.utils.central_connector import CentralConnector

        import random
        ts = datetime.now().strftime('%m%d%H%M%S') + f"{random.randint(0,999):03d}"
        obj_short = table_name[:30]
        job_name = f"HCC_{obj_short}_{ts}"

        # Check queue — prevent overload
        running_df = TargetQueries.get_running_compression_jobs(database_id)
        running_count = len(running_df) if not running_df.empty else 0

        # Check double-submission via central history (IN_PROGRESS means job is active)
        from hcc_advisor.utils.central_connector import CentralConnector
        dup_df = CentralConnector.execute_query("""
            SELECT 1 FROM t_compression_history
            WHERE database_id = :db AND owner = :o AND object_name = :t
              AND operation_status = 'IN_PROGRESS'
              AND ROWNUM = 1
        """, {'db': database_id, 'o': owner, 't': table_name})
        if not dup_df.empty:
            return {'success': False, 'error': f'{owner}.{table_name} already has a running job'}

        ddl = TargetQueries.generate_ddl(
            owner, table_name, compression_type, partition_name,
            parallel_degree=parallel_degree
        ).rstrip().rstrip(';')

        # Build PL/SQL action with index rebuild
        part_filter = f"AND table_name = ''{table_name}''" if not partition_name else \
                      f"AND table_name = ''{table_name}''"
        action = f"""
            DECLARE v_n NUMBER := 0;
            BEGIN
                EXECUTE IMMEDIATE '{ddl.replace("'", "''")}';
                FOR idx IN (SELECT owner, index_name FROM all_indexes
                            WHERE table_owner = '{owner}' AND table_name = '{table_name}'
                              AND status = 'UNUSABLE')
                LOOP
                    EXECUTE IMMEDIATE 'ALTER INDEX ' || idx.owner || '.' || idx.index_name
                                      || ' REBUILD ONLINE PARALLEL {parallel_degree}';
                    v_n := v_n + 1;
                END LOOP;
            END;
        """

        create_job_plsql = f"""
            BEGIN
                DBMS_SCHEDULER.CREATE_JOB(
                    job_name   => '{job_name}',
                    job_type   => 'PLSQL_BLOCK',
                    job_action => q'§{action}§',
                    enabled    => TRUE,
                    auto_drop  => TRUE,
                    comments   => 'HCC Advisor: {compression_type} on {owner}.{table_name}'
                );
            END;
        """

        try:
            success = TargetConnector.execute_plsql(database_id, create_job_plsql)
            if not success:
                return {'success': False, 'error': 'Failed to create scheduler job'}

            # Get original size
            orig_size = 0
            try:
                sq = "SELECT NVL(SUM(bytes),0) as sz FROM dba_segments WHERE owner=:o AND segment_name=:t"
                sp = {'o': owner, 't': table_name}
                sdf = TargetConnector.execute_query(database_id, sq, sp)
                if not sdf.empty:
                    orig_size = int(sdf.iloc[0]['SZ'] or 0)
            except Exception:
                pass

            # Record IN_PROGRESS in history
            CentralQueries.store_compression_history(database_id, {
                'owner': owner, 'object_name': table_name,
                'object_type': 'PARTITION' if partition_name else 'TABLE',
                'partition_name': partition_name,
                'compression_type_applied': compression_type,
                'compression_clause': job_name,
                'execution_mode': 'ONLINE', 'parallel_degree': parallel_degree,
                'original_size_bytes': orig_size,
                'operation_status': 'IN_PROGRESS',
                'start_time': datetime.now(), 'executed_by': 'HCC_ADVISOR',
            })

            return {'success': True, 'job_name': job_name}

        except Exception as e:
            log_error(e, "submit_compression_job")
            return {'success': False, 'error': str(e)}

    @staticmethod
    def get_running_compression_jobs(database_id: int) -> pd.DataFrame:
        """Query DBA_SCHEDULER_RUNNING_JOBS for HCC_% jobs."""
        query = """
            SELECT r.job_name, r.owner as job_owner,
                   EXTRACT(HOUR FROM r.elapsed_time)*3600 +
                   EXTRACT(MINUTE FROM r.elapsed_time)*60 +
                   EXTRACT(SECOND FROM r.elapsed_time) as elapsed_seconds,
                   r.session_id
            FROM dba_scheduler_running_jobs r
            WHERE r.job_name LIKE 'HCC_%'
            ORDER BY r.job_name DESC
        """
        try:
            return TargetConnector.execute_query(database_id, query)
        except Exception:
            return pd.DataFrame()

    @staticmethod
    def get_running_total_dop(database_id: int) -> int:
        """Get total DOP consumed by running HCC jobs from central history."""
        from hcc_advisor.utils.central_connector import CentralConnector
        try:
            df = CentralConnector.execute_query("""
                SELECT NVL(SUM(NVL(parallel_degree, 1)), 0) as total_dop
                FROM t_compression_history
                WHERE database_id = :db AND operation_status = 'IN_PROGRESS'
            """, {'db': database_id})
            if not df.empty:
                return int(df.iloc[0]['TOTAL_DOP'] or 0)
        except Exception:
            pass
        return 0

    @staticmethod
    def check_completed_jobs(database_id: int) -> List[Dict]:
        """Check DBA_SCHEDULER_JOB_RUN_DETAILS for recently completed HCC_% jobs.
        Updates t_compression_history from IN_PROGRESS to SUCCESS/FAILED."""
        from hcc_advisor.utils.central_connector import CentralConnector

        query = """
            SELECT job_name, status,
                   TO_CHAR(actual_start_date, 'YYYY-MM-DD HH24:MI:SS') as start_time,
                   TO_CHAR(run_duration) as run_duration,
                   error# as error_num,
                   SUBSTR(additional_info, 1, 2000) as additional_info
            FROM dba_scheduler_job_run_details
            WHERE job_name LIKE 'HCC_%'
              AND actual_start_date > SYSDATE - 1
            ORDER BY actual_start_date DESC
        """
        try:
            df = TargetConnector.execute_query(database_id, query)
        except Exception:
            return []

        if df.empty:
            return []

        df.columns = [c.lower() for c in df.columns]
        updated = []

        for _, row in df.iterrows():
            job_name = row.get('job_name', '')
            job_status = row.get('status', '')

            if job_status == 'SUCCEEDED':
                # Update history to SUCCESS, get new size
                try:
                    # Find the matching history row
                    hist = CentralConnector.execute_query("""
                        SELECT history_id, owner, object_name, partition_name
                        FROM t_compression_history
                        WHERE compression_clause = :jn AND operation_status = 'IN_PROGRESS'
                          AND ROWNUM = 1
                    """, {'jn': job_name})
                    if not hist.empty:
                        h = hist.iloc[0]
                        o, t = h['OWNER'], h['OBJECT_NAME']
                        # Get new size
                        comp_size = 0
                        try:
                            sdf = TargetConnector.execute_query(database_id,
                                "SELECT NVL(SUM(bytes),0) as sz FROM dba_segments WHERE owner=:o AND segment_name=:t",
                                {'o': o, 't': t})
                            if not sdf.empty:
                                comp_size = int(sdf.iloc[0]['SZ'] or 0)
                        except Exception:
                            pass

                        CentralConnector.execute_dml("""
                            UPDATE t_compression_history
                            SET operation_status = 'SUCCESS', end_time = SYSTIMESTAMP,
                                compressed_size_bytes = :cs
                            WHERE compression_clause = :jn AND operation_status = 'IN_PROGRESS'
                              AND ROWNUM = 1
                        """, {'cs': comp_size, 'jn': job_name})

                        # Update analysis row
                        CentralConnector.execute_dml("""
                            UPDATE t_compression_analysis
                            SET size_bytes = :cs
                            WHERE database_id = :db AND owner = :o AND object_name = :t
                              AND NVL(partition_name, '~') = NVL(:p, '~')
                        """, {'cs': comp_size, 'db': database_id, 'o': o, 't': t,
                              'p': h.get('PARTITION_NAME')})

                        updated.append({'job_name': job_name, 'status': 'SUCCESS'})
                except Exception:
                    pass

            elif job_status == 'FAILED':
                err = row.get('additional_info', '')
                try:
                    CentralConnector.execute_dml("""
                        UPDATE t_compression_history
                        SET operation_status = 'FAILED', end_time = SYSTIMESTAMP,
                            error_message = :err
                        WHERE compression_clause = :jn AND operation_status = 'IN_PROGRESS'
                          AND ROWNUM = 1
                    """, {'err': str(err)[:4000], 'jn': job_name})
                    updated.append({'job_name': job_name, 'status': 'FAILED'})
                except Exception:
                    pass

        return updated


# Create singleton accessor function
@st.cache_resource
def get_target_queries() -> TargetQueries:
    """Get cached TargetQueries instance"""
    return TargetQueries()
