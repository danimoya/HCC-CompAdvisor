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
    # ANALYSIS EXECUTION (runs PL/SQL on target)
    # ============================================================================

    @staticmethod
    def start_analysis(
        database_id: int,
        owner: Optional[str] = None,
        strategy_id: int = 2,
        parallel_degree: int = 4
    ) -> Dict[str, Any]:
        """
        Start a new compression analysis by calling PKG_COMPRESSION_ADVISOR.run_analysis
        on the target database.

        Args:
            database_id: Target database identifier
            owner: Schema owner to analyze (None for all schemas)
            strategy_id: Strategy ID (1=Aggressive, 2=Balanced, 3=Conservative)
            parallel_degree: Number of parallel workers

        Returns:
            dict with success, run_id, message
        """
        plsql_block = """
        BEGIN
            PKG_COMPRESSION_ADVISOR.run_analysis(
                p_owner => :owner,
                p_strategy_id => :strategy_id,
                p_parallel_degree => :parallel_degree
            );
        END;
        """

        try:
            success = TargetConnector.execute_plsql(
                database_id,
                plsql_block,
                params={
                    'owner': owner,
                    'strategy_id': strategy_id,
                    'parallel_degree': parallel_degree
                }
            )

            if success:
                # Get the latest run_id after successful execution
                query = "SELECT MAX(run_id) as run_id FROM t_advisor_run"
                df = TargetConnector.execute_query(database_id, query)
                run_id = df.iloc[0]['RUN_ID'] if not df.empty else None

                return {
                    'success': True,
                    'run_id': run_id,
                    'message': f"Analysis completed successfully. Run ID: {run_id}"
                }
        except Exception as e:
            log_error(e, "TargetQueries.start_analysis", {
                'database_id': database_id,
                'owner': owner,
                'strategy_id': strategy_id
            })
            st.warning(f"Analysis procedure call failed on target db_id={database_id}: {e}")

        return {
            'success': False,
            'run_id': None,
            'message': 'Analysis procedure not available or failed'
        }

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
            # Execute compression via procedure on target
            if partition_name:
                # Use compress_partition for partitioned objects
                plsql_block = """
                BEGIN
                    PKG_COMPRESSION_EXECUTOR.compress_partition(
                        p_owner => :owner,
                        p_table_name => :table_name,
                        p_partition_name => :partition_name,
                        p_compression_type => :compression_type,
                        p_online => TRUE
                    );
                END;
                """
                success = TargetConnector.execute_plsql(
                    database_id,
                    plsql_block,
                    params={
                        'owner': owner,
                        'table_name': table_name,
                        'partition_name': partition_name,
                        'compression_type': compression_type
                    }
                )
            else:
                # Use compress_table for regular tables
                plsql_block = """
                BEGIN
                    PKG_COMPRESSION_EXECUTOR.compress_table(
                        p_owner => :owner,
                        p_table_name => :table_name,
                        p_compression_type => :compression_type,
                        p_online => TRUE,
                        p_dry_run => FALSE
                    );
                END;
                """
                success = TargetConnector.execute_plsql(
                    database_id,
                    plsql_block,
                    params={
                        'owner': owner,
                        'table_name': table_name,
                        'compression_type': compression_type
                    }
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
        plsql_block = """
        BEGIN
            PKG_COMPRESSION_EXECUTOR.compress_partition(
                p_owner => :owner,
                p_table_name => :table_name,
                p_partition_name => :partition_name,
                p_compression_type => :compression_type,
                p_online => TRUE
            );
        END;
        """

        try:
            success = TargetConnector.execute_plsql(
                database_id,
                plsql_block,
                params={
                    'owner': owner,
                    'table_name': table_name,
                    'partition_name': partition_name,
                    'compression_type': compression_type
                }
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
        partition_name: Optional[str] = None
    ) -> str:
        """
        Generate DDL statement for compression. Static utility - no database connection needed.

        Args:
            owner: Schema owner
            table_name: Table name
            compression_type: Target compression type
            partition_name: Optional partition name

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

        if partition_name:
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
