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
            try:
                TargetConnector.execute_plsql(
                    database_id,
                    "BEGIN DBMS_STATS.FLUSH_DATABASE_MONITORING_INFO; END;",
                    commit=False
                )
            except Exception:
                pass

            # 4. Discover eligible tables on target
            tables = TargetQueries._discover_analysis_tables(database_id, owner)
            if not tables:
                TargetQueries._complete_advisor_run(run_id, 0, 0, [], start_time)
                return {'success': True, 'run_id': run_id, 'message': 'No eligible tables found for analysis'}

            log_info(f"Found {len(tables)} eligible tables on db_id={database_id}")

            # 5. Batch-fetch DML stats for hotness scoring
            dml_stats = TargetQueries._get_batch_dml_stats(database_id, owner)

            # 6. Analyze each table
            results = []
            tables_analyzed = 0
            tables_failed = 0

            for table_info in tables:
                tbl_owner = table_info['owner']
                tbl_name = table_info['table_name']
                try:
                    ratios = TargetQueries._get_compression_ratios(
                        database_id, tbl_owner, tbl_name, platform_type
                    )

                    hotness_key = f"{tbl_owner}.{tbl_name}"
                    dml_info = dml_stats.get(hotness_key, {})
                    hotness_score = dml_info.get('hotness_score', 0) if isinstance(dml_info, dict) else 0

                    current_size_mb = table_info['size_mb']

                    recommended = TargetQueries._evaluate_strategy(
                        strategy_rules, 'TABLE', hotness_score, ratios
                    )

                    # Use the ratio for the recommended compression type for savings
                    rec_ratio_key = TargetQueries._COMP_TYPE_RATIO_KEY.get(recommended)
                    rec_ratio = (ratios.get(rec_ratio_key) if rec_ratio_key else None) or 1

                    # Also compute best ratio across all types for the BEST_RATIO column
                    all_ratios = [v for v in ratios.values() if v and v > 0]
                    best_ratio = max(all_ratios) if all_ratios else 1

                    # Savings based on recommended compression type
                    rec_size = round(current_size_mb / rec_ratio, 2) if rec_ratio > 0 else current_size_mb
                    savings_mb = current_size_mb - rec_size
                    savings_pct = round((savings_mb / current_size_mb) * 100, 2) if current_size_mb > 0 else 0

                    rationale = TargetQueries._generate_rationale(
                        current_size_mb, hotness_score, ratios, recommended
                    )

                    current_comp = table_info.get('compress_for') or table_info.get('compression', 'NONE')
                    if current_comp in ('DISABLED', None, ''):
                        current_comp = 'NONE'

                    basic_ratio = ratios.get('basic') or 1
                    oltp_ratio = ratios.get('oltp') or 1

                    result = {
                        'OWNER': tbl_owner,
                        'OBJECT_NAME': tbl_name,
                        'OBJECT_TYPE': 'TABLE',
                        'PARTITION_NAME': None,
                        'SUBPARTITION_NAME': None,
                        'SIZE_BYTES': table_info['size_bytes'],
                        'ROW_COUNT': table_info.get('num_rows'),
                        'BLOCK_COUNT': table_info.get('blocks'),
                        'AVG_ROW_LENGTH': None,
                        'BASIC_RATIO': basic_ratio,
                        'OLTP_RATIO': oltp_ratio,
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
                        'LAST_ANALYZED': None,
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
                                    try:
                                        part_ratios = TargetQueries._get_compression_ratios(
                                            database_id, tbl_owner, tbl_name, platform_type,
                                            partition_name=part_name
                                        )
                                        part_dml_info = part_dml.get(part_name, {})
                                        part_hotness = part_dml_info.get('hotness_score', 0)
                                        part_recommended = TargetQueries._evaluate_strategy(
                                            strategy_rules, 'TABLE', part_hotness, part_ratios
                                        )
                                        part_ratio_key = TargetQueries._COMP_TYPE_RATIO_KEY.get(part_recommended)
                                        part_rec_ratio = (part_ratios.get(part_ratio_key) if part_ratio_key else None) or 1
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
                                            'SIZE_BYTES': part_info.get('size_bytes', 0),
                                            'ROW_COUNT': part_info.get('num_rows'),
                                            'BLOCK_COUNT': part_info.get('blocks'),
                                            'AVG_ROW_LENGTH': None,
                                            'BASIC_RATIO': part_ratios.get('basic') or 1,
                                            'OLTP_RATIO': part_ratios.get('oltp') or 1,
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

                                        # Subpartition analysis for composite partitions
                                        if part_info.get('composite') == 'YES':
                                            subparts = TargetQueries._discover_subpartitions(
                                                database_id, tbl_owner, tbl_name, part_name
                                            )
                                            for subpart_info in subparts:
                                                sub_name = subpart_info['subpartition_name']
                                                try:
                                                    sub_ratios = TargetQueries._get_compression_ratios(
                                                        database_id, tbl_owner, tbl_name, platform_type,
                                                        partition_name=sub_name
                                                    )
                                                    sub_recommended = TargetQueries._evaluate_strategy(
                                                        strategy_rules, 'TABLE', 0, sub_ratios
                                                    )
                                                    sub_ratio_key = TargetQueries._COMP_TYPE_RATIO_KEY.get(sub_recommended)
                                                    sub_rec_ratio = (sub_ratios.get(sub_ratio_key) if sub_ratio_key else None) or 1
                                                    sub_size_mb = subpart_info.get('size_mb', 0)
                                                    sub_rec_size = round(sub_size_mb / sub_rec_ratio, 2) if sub_rec_ratio > 0 else sub_size_mb
                                                    sub_savings_mb = sub_size_mb - sub_rec_size
                                                    sub_savings_pct = round((sub_savings_mb / sub_size_mb) * 100, 2) if sub_size_mb > 0 else 0
                                                    sub_current_comp = subpart_info.get('compress_for') or subpart_info.get('compression', 'NONE')
                                                    if sub_current_comp in ('DISABLED', None, ''):
                                                        sub_current_comp = 'NONE'

                                                    sub_result = {
                                                        'OWNER': tbl_owner,
                                                        'OBJECT_NAME': tbl_name,
                                                        'OBJECT_TYPE': 'SUBPARTITION',
                                                        'PARTITION_NAME': part_name,
                                                        'SUBPARTITION_NAME': sub_name,
                                                        'SIZE_BYTES': subpart_info.get('size_bytes', 0),
                                                        'ROW_COUNT': subpart_info.get('num_rows'),
                                                        'BLOCK_COUNT': subpart_info.get('blocks'),
                                                        'AVG_ROW_LENGTH': None,
                                                        'BASIC_RATIO': sub_ratios.get('basic') or 1,
                                                        'OLTP_RATIO': sub_ratios.get('oltp') or 1,
                                                        'ADV_LOW_RATIO': sub_ratios.get('query_low'),
                                                        'ADV_HIGH_RATIO': sub_ratios.get('query_high'),
                                                        'BLKCNT_UNCMP_BASIC': None, 'BLKCNT_CMP_BASIC': None,
                                                        'BLKCNT_UNCMP_OLTP': None, 'BLKCNT_CMP_OLTP': None,
                                                        'BLKCNT_UNCMP_ADV_LOW': None, 'BLKCNT_CMP_ADV_LOW': None,
                                                        'BLKCNT_UNCMP_ADV_HIGH': None, 'BLKCNT_CMP_ADV_HIGH': None,
                                                        'INSERT_COUNT': 0, 'UPDATE_COUNT': 0, 'DELETE_COUNT': 0,
                                                        'LOGICAL_READS': None, 'PHYSICAL_READS': None,
                                                        'ACCESS_FREQUENCY': None, 'LAST_ACCESS_DATE': None,
                                                        'HOTNESS_SCORE': 0,
                                                        'READ_RATIO': None, 'WRITE_RATIO': None,
                                                        'DML_24H_RATE': None,
                                                        'LAST_ANALYZED': None, 'DATA_AGE_DAYS': None,
                                                        'CURRENT_COMPRESSION': sub_current_comp,
                                                        'ADVISABLE_COMPRESSION': sub_recommended,
                                                        'RECOMMENDATION_REASON': TargetQueries._generate_rationale(
                                                            sub_size_mb, 0, sub_ratios, sub_recommended
                                                        ),
                                                        'CONFIDENCE_SCORE': None,
                                                        'PROJECTED_SAVINGS_BYTES': int(sub_savings_mb * 1024 * 1024),
                                                        'PROJECTED_SAVINGS_PCT': sub_savings_pct,
                                                        'ANALYSIS_DURATION_SEC': None,
                                                        'SAMPLE_SIZE_ROWS': None,
                                                    }
                                                    results.append(sub_result)
                                                    tables_analyzed += 1
                                                except Exception as sub_e:
                                                    tables_failed += 1
                                                    log_warning(f"Failed to analyze subpartition {tbl_owner}.{tbl_name}.{part_name}.{sub_name}: {sub_e}")

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
                    'num_rows': int(row.get('NUM_ROWS') or 0),
                    'blocks': int(row.get('BLOCKS') or 0),
                    'compression': row.get('COMPRESSION', 'NONE'),
                    'compress_for': row.get('COMPRESS_FOR'),
                    'size_bytes': int(row.get('SIZE_BYTES') or 0),
                    'size_mb': float(row.get('SIZE_MB') or 0),
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
                    'num_rows': int(row.get('NUM_ROWS') or 0),
                    'blocks': int(row.get('BLOCKS') or 0),
                    'size_bytes': int(row.get('SIZE_BYTES') or 0),
                    'size_mb': float(row.get('SIZE_MB') or 0),
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
                    'num_rows': int(row.get('NUM_ROWS') or 0),
                    'blocks': int(row.get('BLOCKS') or 0),
                    'size_bytes': int(row.get('SIZE_BYTES') or 0),
                    'size_mb': float(row.get('SIZE_MB') or 0),
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
    def _get_compression_ratios(
        database_id: int, owner: str, table_name: str,
        platform_type: str = 'STANDARD',
        partition_name: Optional[str] = None
    ) -> Dict[str, Any]:
        """Get compression ratios using DBMS_COMPRESSION.GET_COMPRESSION_RATIO.

        Tests BASIC and OLTP on all platforms. On Exadata, also tests
        QUERY LOW/HIGH and ARCHIVE LOW/HIGH (HCC compression types).

        Falls back to CTAS sampling only if DBMS_COMPRESSION is unavailable
        (e.g., Oracle Free development environments).

        Args:
            database_id: Target database identifier
            owner: Schema owner
            table_name: Table name
            platform_type: 'STANDARD' or 'EXADATA'
            partition_name: Optional partition/subpartition name (None for whole table)

        Returns:
            dict with keys: basic, oltp, query_low, query_high, archive_low, archive_high
            Values are float ratios (>1 = compression effective), None if not tested/available.
        """
        # PL/SQL block using DBMS_COMPRESSION.GET_COMPRESSION_RATIO
        # Tests all 6 compression types; HCC types fail gracefully on non-Exadata
        plsql = """
        DECLARE
            v_tbs VARCHAR2(128);
            v_bc PLS_INTEGER;
            v_bu PLS_INTEGER;
            v_rc PLS_INTEGER;
            v_ru PLS_INTEGER;
            v_ratio NUMBER;
            v_str VARCHAR2(100);
        BEGIN
            SELECT default_tablespace INTO v_tbs FROM dba_users WHERE username = :owner;

            -- BASIC (DBMS_COMPRESSION.COMP_BASIC = 4096)
            BEGIN
                DBMS_COMPRESSION.GET_COMPRESSION_RATIO(
                    v_tbs, :owner, :table_name, :partition_name, 4096,
                    v_bc, v_bu, v_rc, v_ru, v_ratio, v_str);
                :basic_ratio := ROUND(v_ratio, 2);
            EXCEPTION WHEN OTHERS THEN :basic_ratio := -1; END;

            -- OLTP (DBMS_COMPRESSION.COMP_FOR_OLTP = 2)
            BEGIN
                DBMS_COMPRESSION.GET_COMPRESSION_RATIO(
                    v_tbs, :owner, :table_name, :partition_name, 2,
                    v_bc, v_bu, v_rc, v_ru, v_ratio, v_str);
                :oltp_ratio := ROUND(v_ratio, 2);
            EXCEPTION WHEN OTHERS THEN :oltp_ratio := -1; END;

            -- QUERY LOW (DBMS_COMPRESSION.COMP_FOR_QUERY_LOW = 4) - HCC/Exadata
            BEGIN
                DBMS_COMPRESSION.GET_COMPRESSION_RATIO(
                    v_tbs, :owner, :table_name, :partition_name, 4,
                    v_bc, v_bu, v_rc, v_ru, v_ratio, v_str);
                :query_low_ratio := ROUND(v_ratio, 2);
            EXCEPTION WHEN OTHERS THEN :query_low_ratio := NULL; END;

            -- QUERY HIGH (DBMS_COMPRESSION.COMP_FOR_QUERY_HIGH = 8) - HCC/Exadata
            BEGIN
                DBMS_COMPRESSION.GET_COMPRESSION_RATIO(
                    v_tbs, :owner, :table_name, :partition_name, 8,
                    v_bc, v_bu, v_rc, v_ru, v_ratio, v_str);
                :query_high_ratio := ROUND(v_ratio, 2);
            EXCEPTION WHEN OTHERS THEN :query_high_ratio := NULL; END;

            -- ARCHIVE LOW (DBMS_COMPRESSION.COMP_FOR_ARCHIVE_LOW = 16) - HCC/Exadata
            BEGIN
                DBMS_COMPRESSION.GET_COMPRESSION_RATIO(
                    v_tbs, :owner, :table_name, :partition_name, 16,
                    v_bc, v_bu, v_rc, v_ru, v_ratio, v_str);
                :archive_low_ratio := ROUND(v_ratio, 2);
            EXCEPTION WHEN OTHERS THEN :archive_low_ratio := NULL; END;

            -- ARCHIVE HIGH (DBMS_COMPRESSION.COMP_FOR_ARCHIVE_HIGH = 32) - HCC/Exadata
            BEGIN
                DBMS_COMPRESSION.GET_COMPRESSION_RATIO(
                    v_tbs, :owner, :table_name, :partition_name, 32,
                    v_bc, v_bu, v_rc, v_ru, v_ratio, v_str);
                :archive_high_ratio := ROUND(v_ratio, 2);
            EXCEPTION WHEN OTHERS THEN :archive_high_ratio := NULL; END;
        END;
        """

        out_params = {
            'basic_ratio': float,
            'oltp_ratio': float,
            'query_low_ratio': float,
            'query_high_ratio': float,
            'archive_low_ratio': float,
            'archive_high_ratio': float,
        }

        try:
            result = TargetConnector.execute_procedure_with_output(
                database_id, plsql,
                in_params={'owner': owner, 'table_name': table_name, 'partition_name': partition_name},
                out_params=out_params
            )

            ratios = {
                'basic': result.get('basic_ratio'),
                'oltp': result.get('oltp_ratio'),
                'query_low': result.get('query_low_ratio'),
                'query_high': result.get('query_high_ratio'),
                'archive_low': result.get('archive_low_ratio'),
                'archive_high': result.get('archive_high_ratio'),
            }

            # Check if DBMS_COMPRESSION failed for standard types (-1 = error)
            basic_failed = (ratios['basic'] is not None and ratios['basic'] < 0)
            oltp_failed = (ratios['oltp'] is not None and ratios['oltp'] < 0)

            if basic_failed and oltp_failed:
                # DBMS_COMPRESSION unavailable (e.g., Oracle Free SAMPLE BLOCK bug)
                # Fall back to CTAS sampling for BASIC + OLTP only
                log_warning(
                    f"DBMS_COMPRESSION unavailable for {owner}.{table_name}, "
                    f"falling back to CTAS sampling"
                )
                fallback = TargetQueries._get_compression_ratios_ctas(
                    database_id, owner, table_name
                )
                ratios['basic'] = fallback.get('basic', 1)
                ratios['oltp'] = fallback.get('oltp', 1)
            else:
                # Clean up failed individual tests (set -1 to 1)
                for key in ('basic', 'oltp'):
                    if ratios[key] is not None and ratios[key] < 0:
                        ratios[key] = 1

            return ratios

        except Exception as e:
            log_warning(f"Compression ratio test failed for {owner}.{table_name}: {e}")
            return {'basic': 1, 'oltp': 1, 'query_low': None, 'query_high': None,
                    'archive_low': None, 'archive_high': None}

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

    # Map from compression type to ratio dict key
    _COMP_TYPE_RATIO_KEY = {
        'BASIC': 'basic', 'OLTP': 'oltp',
        'QUERY LOW': 'query_low', 'QUERY HIGH': 'query_high',
        'ARCHIVE LOW': 'archive_low', 'ARCHIVE HIGH': 'archive_high',
    }

    @staticmethod
    def _evaluate_strategy(
        rules: List[Dict],
        object_type: str,
        hotness_score: float,
        ratios: Dict[str, Any]
    ) -> str:
        """Evaluate strategy rules to determine compression recommendation.

        Args:
            rules: Strategy rules from central DB
            object_type: 'TABLE', 'INDEX', etc.
            hotness_score: 0-100 DML hotness score
            ratios: dict of compression ratios (basic, oltp, query_low, etc.)

        Returns:
            Compression type: NONE/BASIC/OLTP/QUERY LOW/QUERY HIGH/ARCHIVE LOW/ARCHIVE HIGH
        """
        for rule in rules:
            if rule.get('object_type') == object_type:
                if rule.get('hotness_min', 0) <= hotness_score <= rule.get('hotness_max', 100):
                    comp_type = rule['compression_type']
                    # Check if the recommended type has a valid ratio
                    ratio_key = TargetQueries._COMP_TYPE_RATIO_KEY.get(comp_type)
                    ratio_val = ratios.get(ratio_key) if ratio_key else None
                    if ratio_val and ratio_val > 1:
                        return comp_type
                    # HCC type not available on this platform, try next rule
                    continue

        # Default: pick best available compression based on all ratios
        basic = ratios.get('basic') or 1
        oltp = ratios.get('oltp') or 1
        query_low = ratios.get('query_low') or 0
        query_high = ratios.get('query_high') or 0
        archive_low = ratios.get('archive_low') or 0
        archive_high = ratios.get('archive_high') or 0

        # Prefer HCC if available and significantly better
        best_hcc = max(query_low, query_high, archive_low, archive_high)
        best_std = max(basic, oltp)

        if best_hcc >= 2:
            # HCC available and effective — pick highest ratio HCC type
            hcc_options = [
                ('ARCHIVE HIGH', archive_high), ('ARCHIVE LOW', archive_low),
                ('QUERY HIGH', query_high), ('QUERY LOW', query_low),
            ]
            return max(hcc_options, key=lambda x: x[1])[0]
        elif best_std >= 2:
            return 'OLTP'
        elif best_std >= 1.5:
            return 'BASIC'
        return 'NONE'

    @staticmethod
    def _generate_rationale(
        size_mb: float, hotness_score: float, ratios: Dict[str, Any],
        recommended: str
    ) -> str:
        """Generate human-readable rationale for compression recommendation."""
        parts = [f'Size: {size_mb:.2f} MB']
        if hotness_score > 0:
            label = 'High DML' if hotness_score > 70 else ('Moderate DML' if hotness_score > 30 else 'Low DML')
            parts.append(f'Hotness: {hotness_score}/100 ({label})')

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
        dry_run: bool = True
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

        Returns:
            dict with execution result
        """
        # Handle None/NaN partition name
        if partition_name is not None and pd.isna(partition_name):
            partition_name = None

        if dry_run:
            # Generate DDL only - no database connection needed
            ddl = TargetQueries.generate_ddl(
                owner, table_name, compression_type, partition_name
            )
            return {
                'success': True,
                'dry_run': True,
                'ddl': ddl,
                'message': 'DDL generated successfully (dry run)'
            }

        try:
            # Execute compression via direct ALTER TABLE MOVE DDL
            ddl = TargetQueries.generate_ddl(
                owner, table_name, compression_type, partition_name
            )
            # Strip trailing semicolon — oracledb executes DDL without it
            ddl_exec = ddl.rstrip().rstrip(';')

            success = TargetConnector.execute_plsql(
                database_id,
                f"BEGIN EXECUTE IMMEDIATE q'[{ddl_exec}]'; END;"
            )

            if success:
                # Get the latest history_id after successful execution
                history_query = """
                    SELECT MAX(history_id) as history_id
                    FROM t_compression_history
                    WHERE owner = :owner
                      AND object_name = :table_name
                """
                hist_params = {'owner': owner, 'table_name': table_name}
                if partition_name:
                    history_query = """
                        SELECT MAX(history_id) as history_id
                        FROM t_compression_history
                        WHERE owner = :owner
                          AND object_name = :table_name
                          AND partition_name = :partition_name
                    """
                    hist_params['partition_name'] = partition_name

                hist_df = TargetConnector.execute_query(
                    database_id, history_query, hist_params
                )
                history_id = hist_df.iloc[0]['HISTORY_ID'] if not hist_df.empty else None

                return {
                    'success': True,
                    'execution_id': history_id,
                    'message': f"Compression completed. History ID: {history_id}"
                }

        except Exception as e:
            log_error(e, "TargetQueries.execute_compression", {
                'database_id': database_id,
                'owner': owner,
                'table_name': table_name,
                'compression_type': compression_type,
                'partition_name': partition_name
            })
            return {'error': str(e)}

        return {'error': 'Execution failed'}

    @staticmethod
    def execute_partition_compression(
        database_id: int,
        owner: str,
        table_name: str,
        partition_name: str,
        compression_type: str
    ) -> Dict[str, Any]:
        """
        Execute compression for a specific partition on the target database.

        Args:
            database_id: Target database identifier
            owner: Schema owner
            table_name: Table name
            partition_name: Partition name
            compression_type: Target compression type

        Returns:
            dict with execution result
        """
        try:
            ddl = TargetQueries.generate_ddl(
                owner, table_name, compression_type, partition_name
            )
            ddl_exec = ddl.rstrip().rstrip(';')

            success = TargetConnector.execute_plsql(
                database_id,
                f"BEGIN EXECUTE IMMEDIATE q'[{ddl_exec}]'; END;"
            )

            if success:
                # Get the latest history_id after successful execution
                history_query = """
                    SELECT MAX(history_id) as history_id
                    FROM t_compression_history
                    WHERE owner = :owner
                      AND object_name = :table_name
                      AND partition_name = :partition_name
                """
                hist_df = TargetConnector.execute_query(
                    database_id,
                    history_query,
                    {'owner': owner, 'table_name': table_name, 'partition_name': partition_name}
                )
                history_id = hist_df.iloc[0]['HISTORY_ID'] if not hist_df.empty else None

                return {
                    'success': True,
                    'execution_id': history_id,
                    'message': f"Partition compression completed. History ID: {history_id}"
                }
        except Exception as e:
            log_error(e, "TargetQueries.execute_partition_compression", {
                'database_id': database_id,
                'owner': owner,
                'table_name': table_name,
                'partition_name': partition_name,
                'compression_type': compression_type
            })
            return {'error': str(e)}

        return {'error': 'Partition compression failed'}

    @staticmethod
    def batch_execute(
        database_id: int,
        items: List[Dict],
        dry_run: bool = True
    ) -> Dict[str, Any]:
        """
        Execute compression for multiple items in batch on the target database.

        Args:
            database_id: Target database identifier
            items: List of dicts, each with owner, table_name, compression_type,
                   and optional partition_name
            dry_run: If True, only generate DDL without executing

        Returns:
            dict with batch execution results
        """
        results = []
        success_count = 0
        error_count = 0

        for item in items:
            owner = item.get('owner')
            table_name = item.get('table_name')
            compression_type = item.get('compression_type')
            partition_name = item.get('partition_name')

            result = TargetQueries.execute_compression(
                database_id=database_id,
                owner=owner,
                table_name=table_name,
                compression_type=compression_type,
                partition_name=partition_name,
                dry_run=dry_run
            )

            results.append({
                'owner': owner,
                'table_name': table_name,
                'partition_name': partition_name,
                'compression_type': compression_type,
                'result': result
            })

            if result.get('success'):
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
        subpartition_name: Optional[str] = None
    ) -> str:
        """
        Generate DDL statement for compression. Static utility - no database connection needed.

        Args:
            owner: Schema owner
            table_name: Table name
            compression_type: Target compression type
            partition_name: Optional partition name
            subpartition_name: Optional subpartition name

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
ONLINE PARALLEL 4;"""
        elif partition_name:
            ddl = f"""ALTER TABLE {owner}.{table_name}
MOVE PARTITION {partition_name}
{compression_clause}
ONLINE PARALLEL 4;"""
        else:
            ddl = f"""ALTER TABLE {owner}.{table_name}
MOVE {compression_clause}
ONLINE PARALLEL 4;"""

        return ddl

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
        Get active sessions performing compression operations on the target database.

        Args:
            database_id: Target database identifier

        Returns:
            DataFrame with session data
        """
        query = """
            SELECT
                s.sid,
                s.serial# as serial_num,
                s.username,
                s.status,
                s.schemaname,
                s.osuser,
                s.machine,
                s.program,
                s.module,
                s.action,
                s.sql_id,
                s.prev_sql_id,
                s.logon_time,
                s.last_call_et as seconds_in_wait,
                s.state,
                s.wait_class,
                s.event
            FROM v$session s
            WHERE s.type = 'USER'
              AND s.status = 'ACTIVE'
              AND (
                  UPPER(s.module) LIKE '%HCC%'
                  OR UPPER(s.module) LIKE '%COMPRESS%'
                  OR UPPER(s.action) LIKE '%COMPRESS%'
                  OR UPPER(s.action) LIKE '%MOVE%'
                  OR UPPER(s.program) LIKE '%SQLPLUS%'
                  OR UPPER(s.program) LIKE '%PYTHON%'
              )
            ORDER BY s.logon_time DESC
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


# Create singleton accessor function
@st.cache_resource
def get_target_queries() -> TargetQueries:
    """Get cached TargetQueries instance"""
    return TargetQueries()
