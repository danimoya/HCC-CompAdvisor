"""
Database Queries Module for HCC Compression Advisor
Central data access layer with all SQL queries and procedure calls
Replaces ORDS REST API with direct database queries
"""

import pandas as pd
import streamlit as st
from typing import Optional, Dict, Any, List, Tuple
from datetime import datetime, timedelta
from utils.db_connector import DatabaseConnector
from utils.logger import log_error, log_info, log_debug, log_warning


class CompressionQueries:
    """Data access layer for compression analysis operations"""

    # ============================================================================
    # DASHBOARD METHODS
    # ============================================================================

    @staticmethod
    def get_dashboard_summary() -> Dict[str, Any]:
        """
        Get dashboard summary statistics from T_COMPRESSION_ANALYSIS or V_ADVISOR_SUMMARY

        Returns:
            dict: Summary with total_tables, total_size_mb, potential_savings_mb, avg_savings_pct
        """
        query = """
            SELECT
                COUNT(*) as total_tables,
                COALESCE(SUM(size_mb), 0) as total_size_mb,
                COALESCE(SUM(projected_savings_mb), 0) as potential_savings_mb,
                COALESCE(AVG(projected_savings_pct), 0) as avg_savings_pct,
                COUNT(CASE WHEN advisable_compression IS NOT NULL
                          AND advisable_compression != 'NONE' THEN 1 END) as candidates_count
            FROM t_compression_analysis
        """

        try:
            df = DatabaseConnector.execute_query(query)
            if not df.empty:
                row = df.iloc[0]
                return {
                    'total_tables': int(row.get('TOTAL_TABLES', 0)),
                    'total_size_gb': float(row.get('TOTAL_SIZE_MB', 0)) / 1024,
                    'potential_savings_gb': float(row.get('POTENTIAL_SAVINGS_MB', 0)) / 1024,
                    'avg_savings_pct': float(row.get('AVG_SAVINGS_PCT', 0)),
                    'candidates_count': int(row.get('CANDIDATES_COUNT', 0))
                }
        except Exception as e:
            log_error(e, "get_dashboard_summary", {"query": query[:200]})
            st.error(f"Failed to get dashboard summary: {e}")

        return {
            'total_tables': 0,
            'total_size_gb': 0,
            'potential_savings_gb': 0,
            'avg_savings_pct': 0,
            'candidates_count': 0
        }

    @staticmethod
    def get_savings_by_strategy() -> pd.DataFrame:
        """
        Get savings breakdown grouped by compression strategy

        Returns:
            DataFrame with strategy, count, avg_savings_pct, total_size_mb, total_savings_mb
        """
        query = """
            SELECT
                advisable_compression as strategy,
                COUNT(*) as table_count,
                COALESCE(AVG(projected_savings_pct), 0) as avg_savings_pct,
                COALESCE(AVG(best_ratio), 0) as avg_compression_ratio,
                COALESCE(SUM(size_mb), 0) / 1024 as total_size_gb,
                COALESCE(SUM(projected_savings_mb), 0) / 1024 as total_savings_gb
            FROM t_compression_analysis
            WHERE advisable_compression IS NOT NULL
              AND advisable_compression != 'NONE'
            GROUP BY advisable_compression
            ORDER BY total_savings_gb DESC
        """

        try:
            return DatabaseConnector.execute_query(query)
        except Exception as e:
            st.error(f"Failed to get savings by strategy: {e}")
            return pd.DataFrame()

    @staticmethod
    def get_recent_executions(limit: int = 5) -> pd.DataFrame:
        """
        Get recent compression executions from T_COMPRESSION_HISTORY

        Args:
            limit: Maximum number of records to return

        Returns:
            DataFrame with recent execution history
        """
        query = """
            SELECT
                history_id,
                owner as table_owner,
                object_name as table_name,
                object_type,
                partition_name,
                compression_type_applied as strategy,
                original_size_mb,
                compressed_size_mb as final_size_mb,
                space_saved_mb as savings_mb,
                space_saved_pct as savings_pct,
                operation_status as status,
                start_time,
                end_time,
                error_message
            FROM t_compression_history
            ORDER BY start_time DESC
            FETCH FIRST :limit ROWS ONLY
        """

        try:
            return DatabaseConnector.execute_query(query, {'limit': limit})
        except Exception as e:
            st.error(f"Failed to get recent executions: {e}")
            return pd.DataFrame()

    # ============================================================================
    # ANALYSIS METHODS
    # ============================================================================

    @staticmethod
    def start_analysis(
        owner: Optional[str] = None,
        strategy_id: int = 2,
        parallel_degree: int = 4
    ) -> Dict[str, Any]:
        """
        Start a new compression analysis by calling PKG_COMPRESSION_ADVISOR.run_analysis

        Args:
            owner: Schema owner to analyze (None for all schemas)
            strategy_id: Strategy ID (1=Aggressive, 2=Balanced, 3=Conservative)
            parallel_degree: Number of parallel workers

        Returns:
            dict with run_id and status
        """
        # Call the procedure - it doesn't return a run_id, so we query for latest after
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
            success = DatabaseConnector.execute_plsql(
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
                df = DatabaseConnector.execute_query(query)
                run_id = df.iloc[0]['RUN_ID'] if not df.empty else None

                return {
                    'success': True,
                    'run_id': run_id,
                    'message': f"Analysis completed successfully. Run ID: {run_id}"
                }
        except Exception as e:
            st.warning(f"Analysis procedure call failed: {e}")

        return {
            'success': False,
            'run_id': None,
            'message': 'Analysis procedure not available or failed'
        }

    @staticmethod
    def get_analysis_runs(limit: int = 10) -> pd.DataFrame:
        """
        Get list of analysis runs from T_ADVISOR_RUN

        Args:
            limit: Maximum number of runs to return

        Returns:
            DataFrame with analysis run history
        """
        query = """
            SELECT
                run_id,
                start_time as run_date,
                schema_filter as owner_filter,
                run_status as status,
                objects_analyzed as tables_analyzed,
                (recommend_basic + recommend_oltp + recommend_adv_low + recommend_adv_high) as candidates_found,
                duration_minutes * 60 as duration_seconds,
                error_message
            FROM t_advisor_run
            ORDER BY start_time DESC
            FETCH FIRST :limit ROWS ONLY
        """

        try:
            return DatabaseConnector.execute_query(query, {'limit': limit})
        except Exception as e:
            st.error(f"Failed to get analysis runs: {e}")
            return pd.DataFrame()

    @staticmethod
    def get_latest_analysis() -> Dict[str, Any]:
        """
        Get the latest analysis run and its summary

        Returns:
            dict with analysis summary
        """
        query = """
            SELECT
                r.run_id as analysis_id,
                r.start_time as started_at,
                r.end_time as completed_at,
                r.run_status as status,
                r.schema_filter as owner_filter,
                r.objects_analyzed as tables_analyzed,
                (r.recommend_basic + r.recommend_oltp + r.recommend_adv_low + r.recommend_adv_high) as candidates_found,
                r.duration_minutes * 60 as duration_seconds,
                COALESCE(r.total_size_mb, 0) / 1024 as total_current_size_gb,
                COALESCE(r.total_size_mb - r.projected_savings_mb, 0) / 1024 as total_compressed_size_gb,
                COALESCE(r.projected_savings_pct, 0) as avg_savings_pct
            FROM t_advisor_run r
            WHERE r.run_id = (SELECT MAX(run_id) FROM t_advisor_run)
        """

        try:
            df = DatabaseConnector.execute_query(query)
            if not df.empty:
                row = df.iloc[0]
                return {
                    'analysis_id': row.get('ANALYSIS_ID'),
                    'started_at': row.get('STARTED_AT'),
                    'completed_at': row.get('COMPLETED_AT'),
                    'status': row.get('STATUS', 'UNKNOWN'),
                    'tables_analyzed': int(row.get('TABLES_ANALYZED', 0) or 0),
                    'candidates_found': int(row.get('CANDIDATES_FOUND', 0) or 0),
                    'duration_seconds': int(row.get('DURATION_SECONDS', 0) or 0),
                    'min_size_mb': 0,
                    'total_current_size_gb': float(row.get('TOTAL_CURRENT_SIZE_GB', 0) or 0),
                    'total_compressed_size_gb': float(row.get('TOTAL_COMPRESSED_SIZE_GB', 0) or 0),
                    'avg_savings_pct': float(row.get('AVG_SAVINGS_PCT', 0) or 0)
                }
        except Exception as e:
            st.error(f"Failed to get latest analysis: {e}")

        return {}

    @staticmethod
    def get_analysis_results(run_id: int) -> pd.DataFrame:
        """
        Get analysis results for a specific run

        Args:
            run_id: Analysis run ID

        Returns:
            DataFrame with analysis results
        """
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
            return DatabaseConnector.execute_query(query, {'run_id': run_id})
        except Exception as e:
            st.error(f"Failed to get analysis results: {e}")
            return pd.DataFrame()

    # ============================================================================
    # RECOMMENDATIONS METHODS
    # ============================================================================

    @staticmethod
    def get_recommendations(
        schema: Optional[str] = None,
        strategy: Optional[str] = None,
        min_savings_pct: float = 10.0,
        min_size_mb: float = 0.0,
        limit: int = 100
    ) -> pd.DataFrame:
        """
        Get compression recommendations from T_COMPRESSION_ANALYSIS

        Args:
            schema: Filter by schema/owner (None for all)
            strategy: Filter by compression strategy (None for all)
            min_savings_pct: Minimum savings percentage
            min_size_mb: Minimum table size in MB
            limit: Maximum number of results

        Returns:
            DataFrame with recommendations
        """
        query = """
            SELECT
                analysis_id as recommendation_id,
                owner as table_owner,
                object_name as table_name,
                object_type,
                partition_name,
                size_mb as current_size_mb,
                row_count as estimated_rows,
                current_compression,
                advisable_compression as recommended_strategy,
                size_mb - projected_savings_mb as estimated_size_mb,
                projected_savings_pct as savings_pct,
                best_ratio as compression_ratio,
                hotness_score,
                recommendation_reason
            FROM t_compression_analysis
            WHERE advisable_compression IS NOT NULL
              AND advisable_compression != 'NONE'
              AND projected_savings_pct >= :min_savings_pct
              AND size_mb >= :min_size_mb
              AND (:schema IS NULL OR owner = :schema)
              AND (:strategy IS NULL OR advisable_compression = :strategy)
            ORDER BY projected_savings_mb DESC
            FETCH FIRST :limit ROWS ONLY
        """

        try:
            return DatabaseConnector.execute_query(query, {
                'schema': schema,
                'strategy': strategy,
                'min_savings_pct': min_savings_pct,
                'min_size_mb': min_size_mb,
                'limit': limit
            })
        except Exception as e:
            st.error(f"Failed to get recommendations: {e}")
            return pd.DataFrame()

    @staticmethod
    def get_compression_candidates() -> pd.DataFrame:
        """
        Get compression candidates from V_COMPRESSION_CANDIDATES view

        Returns:
            DataFrame with compression candidates
        """
        query = """
            SELECT * FROM v_compression_candidates
            ORDER BY projected_savings_mb DESC
        """

        try:
            return DatabaseConnector.execute_query(query)
        except Exception as e:
            # Fallback to direct query if view doesn't exist
            return CompressionQueries.get_recommendations()

    @staticmethod
    def get_hot_objects() -> pd.DataFrame:
        """
        Get hot objects from V_HOT_OBJECTS view (frequently accessed)

        Returns:
            DataFrame with hot objects
        """
        query = """
            SELECT * FROM v_hot_objects
            ORDER BY hotness_score DESC
        """

        try:
            return DatabaseConnector.execute_query(query)
        except Exception as e:
            # Fallback query
            fallback_query = """
                SELECT
                    owner, object_name, object_type,
                    size_mb, hotness_score, advisable_compression
                FROM t_compression_analysis
                WHERE hotness_score >= 50
                ORDER BY hotness_score DESC
            """
            return DatabaseConnector.execute_query(fallback_query)

    @staticmethod
    def get_cold_objects() -> pd.DataFrame:
        """
        Get cold objects from V_COLD_OBJECTS view (rarely accessed)

        Returns:
            DataFrame with cold objects
        """
        query = """
            SELECT * FROM v_cold_objects
            ORDER BY size_mb DESC
        """

        try:
            return DatabaseConnector.execute_query(query)
        except Exception as e:
            # Fallback query
            fallback_query = """
                SELECT
                    owner, object_name, object_type,
                    size_mb, hotness_score, advisable_compression
                FROM t_compression_analysis
                WHERE hotness_score < 50
                ORDER BY size_mb DESC
            """
            return DatabaseConnector.execute_query(fallback_query)

    # ============================================================================
    # EXECUTION METHODS
    # ============================================================================

    @staticmethod
    def execute_compression(
        analysis_id: int,
        dry_run: bool = True,
        parallel_degree: int = 4
    ) -> Dict[str, Any]:
        """
        Execute compression for a specific analysis recommendation

        Args:
            analysis_id: Analysis ID to execute compression for
            dry_run: If True, only generate DDL without executing
            parallel_degree: Degree of parallelism (not used by procedure, kept for API compatibility)

        Returns:
            dict with execution result
        """
        # First get the recommendation details
        query = """
            SELECT owner, object_name, object_type, partition_name,
                   advisable_compression, size_mb
            FROM t_compression_analysis
            WHERE analysis_id = :analysis_id
        """

        try:
            df = DatabaseConnector.execute_query(query, {'analysis_id': analysis_id})
            if df.empty:
                return {'error': 'Recommendation not found'}

            row = df.iloc[0]
            owner = row['OWNER']
            table_name = row['OBJECT_NAME']
            object_type = row.get('OBJECT_TYPE', 'TABLE')
            compression_type = row['ADVISABLE_COMPRESSION']
            partition_name = row.get('PARTITION_NAME')

            # Handle None/NaN partition name
            if pd.isna(partition_name):
                partition_name = None

            if dry_run:
                # Generate DDL only
                ddl = CompressionQueries.generate_ddl(
                    owner, table_name, compression_type, partition_name
                )
                return {
                    'success': True,
                    'dry_run': True,
                    'ddl': ddl,
                    'message': 'DDL generated successfully (dry run)'
                }

            # Execute compression via procedure
            # Note: Oracle PL/SQL BOOLEAN cannot be bound from Python, use literals
            if partition_name:
                # Use compress_partition for partitioned objects
                plsql_block = f"""
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
                success = DatabaseConnector.execute_plsql(
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
                plsql_block = f"""
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
                success = DatabaseConnector.execute_plsql(
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
                hist_df = DatabaseConnector.execute_query(
                    history_query,
                    {'owner': owner, 'table_name': table_name}
                )
                history_id = hist_df.iloc[0]['HISTORY_ID'] if not hist_df.empty else None

                return {
                    'success': True,
                    'execution_id': history_id,
                    'message': f"Compression completed. History ID: {history_id}"
                }

        except Exception as e:
            return {'error': str(e)}

        return {'error': 'Execution failed'}

    @staticmethod
    def execute_partition_compression(
        owner: str,
        table_name: str,
        partition_name: str,
        compression_type: str,
        parallel_degree: int = 4
    ) -> Dict[str, Any]:
        """
        Execute compression for a specific partition

        Args:
            owner: Schema owner
            table_name: Table name
            partition_name: Partition name
            compression_type: Target compression type
            parallel_degree: Degree of parallelism (not used by procedure, kept for API compatibility)

        Returns:
            dict with execution result
        """
        # Note: Oracle PL/SQL BOOLEAN cannot be bound from Python, use literals
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
            success = DatabaseConnector.execute_plsql(
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
                hist_df = DatabaseConnector.execute_query(
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
            return {'error': str(e)}

        return {'error': 'Partition compression failed'}

    @staticmethod
    def batch_execute(
        analysis_ids: List[int],
        dry_run: bool = True,
        parallel_degree: int = 4
    ) -> Dict[str, Any]:
        """
        Execute compression for multiple recommendations in batch

        Args:
            analysis_ids: List of analysis IDs to process
            dry_run: If True, only generate DDL without executing
            parallel_degree: Degree of parallelism

        Returns:
            dict with batch execution results
        """
        results = []
        success_count = 0
        error_count = 0

        for analysis_id in analysis_ids:
            result = CompressionQueries.execute_compression(
                analysis_id, dry_run, parallel_degree
            )
            results.append({
                'analysis_id': analysis_id,
                'result': result
            })

            if result.get('success'):
                success_count += 1
            else:
                error_count += 1

        return {
            'total': len(analysis_ids),
            'success': success_count,
            'errors': error_count,
            'results': results,
            'message': f"Batch completed: {success_count} success, {error_count} errors"
        }

    @staticmethod
    def get_execution_status(history_id: int) -> Dict[str, Any]:
        """
        Get execution status from T_COMPRESSION_HISTORY

        Args:
            history_id: History ID to check

        Returns:
            dict with execution status
        """
        query = """
            SELECT
                history_id as execution_id,
                owner as table_owner,
                object_name as table_name,
                object_type,
                partition_name,
                compression_type_applied as strategy,
                original_size_mb,
                compressed_size_mb as final_size_mb,
                space_saved_mb as savings_mb,
                space_saved_pct as savings_pct,
                operation_status as status,
                start_time,
                end_time,
                error_message
            FROM t_compression_history
            WHERE history_id = :history_id
        """

        try:
            df = DatabaseConnector.execute_query(query, {'history_id': history_id})
            if not df.empty:
                return df.iloc[0].to_dict()
        except Exception as e:
            st.error(f"Failed to get execution status: {e}")

        return {}

    @staticmethod
    def generate_ddl(
        owner: str,
        table_name: str,
        compression_type: str,
        partition_name: Optional[str] = None,
        analysis_id: Optional[int] = None
    ) -> str:
        """
        Generate DDL statement for compression

        Args:
            owner: Schema owner
            table_name: Table name
            compression_type: Target compression type
            partition_name: Optional partition name
            analysis_id: Optional analysis ID (to use package function)

        Returns:
            DDL statement string
        """
        # If we have an analysis_id, try using the package function
        if analysis_id:
            try:
                # The package function returns a cursor with DDL statements
                query = """
                    SELECT ddl_statement
                    FROM TABLE(
                        CAST(PKG_COMPRESSION_ADVISOR.generate_ddl(:analysis_id) AS SYS_REFCURSOR)
                    )
                    WHERE ROWNUM = 1
                """
                df = DatabaseConnector.execute_query(query, {'analysis_id': analysis_id})
                if not df.empty and df.iloc[0].get('DDL_STATEMENT'):
                    return df.iloc[0]['DDL_STATEMENT']
            except Exception:
                # Package function may not work as expected, use fallback
                pass

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
    # HISTORY METHODS
    # ============================================================================

    @staticmethod
    def get_execution_history(
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        status: Optional[str] = None,
        limit: int = 100
    ) -> pd.DataFrame:
        """
        Get execution history from T_COMPRESSION_HISTORY with filters

        Args:
            start_date: Start date filter (ISO format)
            end_date: End date filter (ISO format)
            status: Status filter
            limit: Maximum results

        Returns:
            DataFrame with execution history
        """
        query = """
            SELECT
                history_id as execution_id,
                owner as table_owner,
                object_name as table_name,
                object_type,
                partition_name,
                compression_type_applied as strategy,
                original_size_mb,
                compressed_size_mb as final_size_mb,
                space_saved_mb as savings_mb,
                space_saved_pct as savings_pct,
                operation_status as status,
                start_time as executed_at,
                end_time,
                error_message
            FROM t_compression_history
            WHERE (:start_date IS NULL OR start_time >= TO_DATE(:start_date, 'YYYY-MM-DD'))
              AND (:end_date IS NULL OR start_time <= TO_DATE(:end_date, 'YYYY-MM-DD') + 1)
              AND (:status IS NULL OR operation_status = :status)
            ORDER BY start_time DESC
            FETCH FIRST :limit ROWS ONLY
        """

        try:
            return DatabaseConnector.execute_query(query, {
                'start_date': start_date,
                'end_date': end_date,
                'status': status,
                'limit': limit
            })
        except Exception as e:
            st.error(f"Failed to get execution history: {e}")
            return pd.DataFrame()

    @staticmethod
    def get_compression_effectiveness() -> pd.DataFrame:
        """
        Get compression effectiveness statistics from V_COMPRESSION_EFFECTIVENESS

        Returns:
            DataFrame with effectiveness metrics
        """
        query = """
            SELECT * FROM v_compression_effectiveness
        """

        try:
            return DatabaseConnector.execute_query(query)
        except Exception as e:
            # Fallback to aggregated query
            fallback_query = """
                SELECT
                    compression_type_applied as strategy,
                    COUNT(*) as execution_count,
                    AVG(space_saved_pct) as avg_savings_pct,
                    SUM(space_saved_mb) as total_savings_mb,
                    COUNT(CASE WHEN operation_status = 'SUCCESS' THEN 1 END) as success_count
                FROM t_compression_history
                WHERE operation_status = 'SUCCESS'
                GROUP BY compression_type_applied
                ORDER BY total_savings_mb DESC
            """
            return DatabaseConnector.execute_query(fallback_query)

    # ============================================================================
    # STRATEGY METHODS
    # ============================================================================

    @staticmethod
    def get_strategies() -> pd.DataFrame:
        """
        Get compression strategies from T_COMPRESSION_STRATEGIES

        Returns:
            DataFrame with strategy information (empty if table doesn't exist)
        """
        query = """
            SELECT
                strategy_id,
                strategy_name,
                description,
                category as compression_level,
                category as best_for,
                min_compression_ratio as avg_compression_ratio,
                100 - (100 / NULLIF(min_compression_ratio, 0)) as avg_savings_pct,
                CASE
                    WHEN category = 'PERFORMANCE' THEN 'Low'
                    WHEN category = 'BALANCED' THEN 'Medium'
                    WHEN category = 'SPACE' THEN 'High'
                    ELSE 'Medium'
                END as performance_impact,
                active_flag
            FROM t_compression_strategies
            WHERE active_flag = 'Y'
            ORDER BY priority DESC, strategy_id
        """

        try:
            return DatabaseConnector.execute_query(query)
        except Exception as e:
            st.warning(f"Could not load strategies from database: {e}")
            return pd.DataFrame()

    @staticmethod
    def get_strategy_rules(strategy_id: Optional[int] = None) -> pd.DataFrame:
        """
        Get strategy rules from T_STRATEGY_RULES

        Args:
            strategy_id: Optional strategy ID to filter

        Returns:
            DataFrame with strategy rules
        """
        query = """
            SELECT
                rule_id,
                strategy_id,
                rule_description as rule_name,
                object_type as condition_type,
                compression_type as condition_value,
                priority,
                enabled_flag as is_active
            FROM t_strategy_rules
            WHERE (:strategy_id IS NULL OR strategy_id = :strategy_id)
              AND enabled_flag = 'Y'
            ORDER BY strategy_id, priority
        """

        try:
            return DatabaseConnector.execute_query(query, {'strategy_id': strategy_id})
        except Exception as e:
            return pd.DataFrame()

    @staticmethod
    def compare_strategies(owner: str, table_name: str) -> pd.DataFrame:
        """
        Compare all compression strategies for a specific table

        Args:
            owner: Schema owner
            table_name: Table name

        Returns:
            DataFrame with strategy comparison
        """
        # Try to call the analysis procedure for comparison
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

            df = DatabaseConnector.execute_query(query, {
                'owner': owner.upper(),
                'table_name': table_name.upper()
            })

            if not df.empty:
                return df
        except Exception:
            pass

        # Fallback: Get table info and estimate
        table_info = DatabaseConnector.get_table_statistics(owner, table_name)

        if not table_info:
            return pd.DataFrame()

        current_size_mb = table_info.get('SIZE_MB', 0) or 0
        row_count = table_info.get('NUM_ROWS', 0) or 0

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
    # SCHEMA/OWNER METHODS
    # ============================================================================

    @staticmethod
    def get_available_schemas() -> List[str]:
        """
        Get list of schemas with tables that can be analyzed

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
            df = DatabaseConnector.execute_query(query)
            if not df.empty:
                return df['OWNER'].tolist()
        except Exception as e:
            st.error(f"Failed to get schemas: {e}")

        return []

    @staticmethod
    def get_tables_for_schema(owner: str) -> pd.DataFrame:
        """
        Get tables for a specific schema

        Args:
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
            return DatabaseConnector.execute_query(query, {'owner': owner.upper()})
        except Exception as e:
            st.error(f"Failed to get tables: {e}")
            return pd.DataFrame()


    # ============================================================================
    # DETAILED ANALYSIS METHODS (for justification display)
    # ============================================================================

    @staticmethod
    def get_analysis_details(analysis_id: int) -> Dict[str, Any]:
        """
        Get detailed analysis information for a specific recommendation

        Args:
            analysis_id: Analysis ID

        Returns:
            dict with detailed analysis data including compression ratios, activity metrics
        """
        # Use SELECT * to get all available columns dynamically
        query = """
            SELECT *
            FROM t_compression_analysis
            WHERE analysis_id = :analysis_id
        """

        try:
            df = DatabaseConnector.execute_query(query, {'analysis_id': analysis_id})
            if not df.empty:
                row = df.iloc[0]
                return row.to_dict()
        except Exception as e:
            st.error(f"Failed to get analysis details: {e}")

        return {}

    @staticmethod
    def get_column_statistics(owner: str, table_name: str) -> pd.DataFrame:
        """
        Get column statistics from DBA_TAB_COL_STATISTICS

        Args:
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
            return DatabaseConnector.execute_query(query, {
                'owner': owner.upper(),
                'table_name': table_name.upper()
            })
        except Exception as e:
            st.error(f"Failed to get column statistics: {e}")
            return pd.DataFrame()

    @staticmethod
    def get_table_column_info(owner: str, table_name: str) -> pd.DataFrame:
        """
        Get table column information with data types and sizes

        Args:
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
            return DatabaseConnector.execute_query(query, {
                'owner': owner.upper(),
                'table_name': table_name.upper()
            })
        except Exception as e:
            st.error(f"Failed to get column info: {e}")
            return pd.DataFrame()

    @staticmethod
    def get_table_tablespace(owner: str, table_name: str) -> Optional[str]:
        """
        Get tablespace name for a table

        Args:
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
            df = DatabaseConnector.execute_query(query, {
                'owner': owner.upper(),
                'table_name': table_name.upper()
            })
            if not df.empty:
                return df.iloc[0].get('TABLESPACE_NAME', None)
        except Exception as e:
            log_debug(f"Could not get tablespace: {e}")

        return None

    @staticmethod
    def get_segment_info(owner: str, segment_name: str) -> Dict[str, Any]:
        """
        Get segment storage information

        Args:
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
            df = DatabaseConnector.execute_query(query, {
                'owner': owner.upper(),
                'segment_name': segment_name.upper()
            })
            if not df.empty:
                return df.iloc[0].to_dict()
        except Exception as e:
            st.warning(f"Could not get segment info: {e}")

        return {}

    @staticmethod
    def get_table_activity(owner: str, table_name: str) -> Dict[str, Any]:
        """
        Get table modification/activity information

        Args:
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
            df = DatabaseConnector.execute_query(query, {
                'owner': owner.upper(),
                'table_name': table_name.upper()
            })
            if not df.empty:
                return df.iloc[0].to_dict()
        except Exception as e:
            pass  # Table may not have pending modifications tracked

        return {}

    @staticmethod
    def build_recommendation_justification(analysis_id: int) -> Dict[str, Any]:
        """
        Build comprehensive recommendation justification for display

        Args:
            analysis_id: Analysis ID

        Returns:
            dict with comprehensive justification data
        """
        details = CompressionQueries.get_analysis_details(analysis_id)

        if not details:
            return {'error': 'Analysis not found'}

        owner = details.get('OWNER', '')
        table_name = details.get('OBJECT_NAME', '')

        # Build justification structure
        justification = {
            'summary': {
                'table': f"{owner}.{table_name}",
                'current_size_mb': details.get('SIZE_MB', 0),
                'row_count': details.get('ROW_COUNT', 0),
                'current_compression': details.get('CURRENT_COMPRESSION', 'NONE'),
                'recommended': details.get('ADVISABLE_COMPRESSION', 'N/A'),
                'projected_savings_pct': details.get('PROJECTED_SAVINGS_PCT', 0),
                'confidence_score': details.get('CONFIDENCE_SCORE', 0),
                'reason': details.get('RECOMMENDATION_REASON', '')
            },
            'compression_analysis': {
                'basic': {
                    'ratio': details.get('BASIC_RATIO', 0),
                    'uncompressed_blocks': details.get('BLKCNT_UNCMP_BASIC', 0),
                    'compressed_blocks': details.get('BLKCNT_CMP_BASIC', 0)
                },
                'oltp': {
                    'ratio': details.get('OLTP_RATIO', 0),
                    'uncompressed_blocks': details.get('BLKCNT_UNCMP_OLTP', 0),
                    'compressed_blocks': details.get('BLKCNT_CMP_OLTP', 0)
                },
                'adv_low': {
                    'ratio': details.get('ADV_LOW_RATIO', 0),
                    'uncompressed_blocks': details.get('BLKCNT_UNCMP_ADV_LOW', 0),
                    'compressed_blocks': details.get('BLKCNT_CMP_ADV_LOW', 0)
                },
                'adv_high': {
                    'ratio': details.get('ADV_HIGH_RATIO', 0),
                    'uncompressed_blocks': details.get('BLKCNT_UNCMP_ADV_HIGH', 0),
                    'compressed_blocks': details.get('BLKCNT_CMP_ADV_HIGH', 0)
                },
                'best_ratio': details.get('BEST_RATIO', 0)
            },
            'activity_metrics': {
                'inserts': details.get('INSERT_COUNT', 0) or 0,
                'updates': details.get('UPDATE_COUNT', 0) or 0,
                'deletes': details.get('DELETE_COUNT', 0) or 0,
                'total_dml': details.get('TOTAL_DML', 0) or 0,
                'logical_reads': details.get('LOGICAL_READS', 0) or 0,
                'physical_reads': details.get('PHYSICAL_READS', 0) or 0,
                'hotness_score': details.get('HOTNESS_SCORE', 0) or 0,
                'hotness_category': details.get('HOTNESS_CATEGORY', 'UNKNOWN'),
                'read_ratio': details.get('READ_RATIO', 0) or 0,
                'write_ratio': details.get('WRITE_RATIO', 0) or 0
            },
            'storage': {
                'tablespace': details.get('TABLESPACE_NAME', ''),
                'block_count': details.get('BLOCK_COUNT', 0) or details.get('BLOCKS', 0),
                'avg_row_length': details.get('AVG_ROW_LENGTH', 0) or details.get('AVG_ROW_LEN', 0),
                'size_bytes': details.get('SIZE_BYTES', 0) or (details.get('SIZE_MB', 0) or 0) * 1024 * 1024
            },
            'analysis_info': {
                'last_analyzed': details.get('LAST_ANALYZED'),
                'analysis_timestamp': details.get('ANALYSIS_TIMESTAMP')
            }
        }

        # Fetch tablespace from dba_tables if not in analysis table
        if not justification['storage']['tablespace'] and owner and table_name:
            try:
                tablespace = CompressionQueries.get_table_tablespace(owner, table_name)
                if tablespace:
                    justification['storage']['tablespace'] = tablespace
            except Exception:
                pass

        # Fetch segment info for additional storage details if missing
        if (not justification['storage']['block_count'] or not justification['storage']['size_bytes']) and owner and table_name:
            try:
                segment_info = CompressionQueries.get_segment_info(owner, table_name)
                if segment_info:
                    if not justification['storage']['tablespace']:
                        justification['storage']['tablespace'] = segment_info.get('TABLESPACE_NAME', '')
                    if not justification['storage']['block_count']:
                        justification['storage']['block_count'] = segment_info.get('BLOCKS', 0)
                    if not justification['storage']['size_bytes']:
                        justification['storage']['size_bytes'] = segment_info.get('BYTES', 0)
            except Exception:
                pass

        return justification

    # ============================================================================
    # MONITORING METHODS (for operation progress tracking)
    # ============================================================================

    @staticmethod
    def get_running_operations() -> pd.DataFrame:
        """
        Get currently running compression or analysis operations

        Returns:
            DataFrame with running operations
        """
        query = """
            SELECT
                history_id as operation_id,
                'COMPRESSION' as operation_type,
                owner,
                object_name as table_name,
                partition_name,
                compression_type_applied as strategy,
                operation_status as status,
                start_time,
                ROUND((SYSDATE - start_time) * 24 * 60, 1) as duration_minutes,
                original_size_mb,
                NULL as progress_pct
            FROM t_compression_history
            WHERE operation_status = 'IN_PROGRESS'
            UNION ALL
            SELECT
                run_id as operation_id,
                'ANALYSIS' as operation_type,
                schema_filter as owner,
                'All Tables' as table_name,
                NULL as partition_name,
                'Balanced' as strategy,
                run_status as status,
                start_time,
                ROUND((SYSDATE - start_time) * 24 * 60, 1) as duration_minutes,
                total_size_mb as original_size_mb,
                NULL as progress_pct
            FROM t_advisor_run
            WHERE run_status = 'RUNNING'
            ORDER BY start_time DESC
        """

        try:
            return DatabaseConnector.execute_query(query)
        except Exception as e:
            st.error(f"Failed to get running operations: {e}")
            return pd.DataFrame()

    @staticmethod
    def get_operation_progress(operation_type: str, operation_id: int) -> Dict[str, Any]:
        """
        Get progress for a specific operation

        Args:
            operation_type: 'COMPRESSION' or 'ANALYSIS'
            operation_id: Operation ID (history_id or run_id)

        Returns:
            dict with progress information
        """
        if operation_type == 'COMPRESSION':
            query = """
                SELECT
                    history_id as operation_id,
                    owner,
                    object_name as table_name,
                    partition_name,
                    compression_type_applied as strategy,
                    operation_status as status,
                    start_time,
                    end_time,
                    ROUND((NVL(end_time, SYSDATE) - start_time) * 24 * 60, 1) as duration_minutes,
                    original_size_mb,
                    compressed_size_mb,
                    space_saved_mb,
                    space_saved_pct,
                    error_message
                FROM t_compression_history
                WHERE history_id = :operation_id
            """
        else:  # ANALYSIS
            query = """
                SELECT
                    run_id as operation_id,
                    schema_filter as owner,
                    run_status as status,
                    start_time,
                    end_time,
                    ROUND((NVL(end_time, SYSDATE) - start_time) * 24 * 60, 1) as duration_minutes,
                    objects_analyzed,
                    objects_skipped,
                    NULL as progress_pct,
                    recommend_basic,
                    recommend_oltp,
                    recommend_adv_low,
                    recommend_adv_high,
                    total_size_mb,
                    projected_savings_mb,
                    projected_savings_pct,
                    error_message
                FROM t_advisor_run
                WHERE run_id = :operation_id
            """

        try:
            df = DatabaseConnector.execute_query(query, {'operation_id': operation_id})
            if not df.empty:
                return df.iloc[0].to_dict()
        except Exception as e:
            st.error(f"Failed to get operation progress: {e}")

        return {}

    @staticmethod
    def get_long_operations() -> pd.DataFrame:
        """
        Get long-running operations from V$SESSION_LONGOPS (requires DBA privileges)

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
            return DatabaseConnector.execute_query(query)
        except Exception as e:
            # May not have privileges to access V$SESSION_LONGOPS
            return pd.DataFrame()

    @staticmethod
    def get_recent_operations(limit: int = 10) -> pd.DataFrame:
        """
        Get recent operations (both analysis and compression)

        Args:
            limit: Maximum number of operations

        Returns:
            DataFrame with recent operations
        """
        query = """
            SELECT * FROM (
                SELECT
                    history_id as operation_id,
                    'COMPRESSION' as operation_type,
                    owner,
                    object_name as name,
                    partition_name as detail,
                    compression_type_applied as strategy,
                    operation_status as status,
                    start_time,
                    end_time,
                    ROUND((NVL(end_time, SYSDATE) - start_time) * 24 * 60, 1) as duration_minutes,
                    space_saved_pct as result_pct,
                    error_message
                FROM t_compression_history
                UNION ALL
                SELECT
                    run_id as operation_id,
                    'ANALYSIS' as operation_type,
                    schema_filter as owner,
                    'Schema Analysis' as name,
                    objects_analyzed || ' objects' as detail,
                    'Balanced' as strategy,
                    run_status as status,
                    start_time,
                    end_time,
                    ROUND((NVL(end_time, SYSDATE) - start_time) * 24 * 60, 1) as duration_minutes,
                    projected_savings_pct as result_pct,
                    error_message
                FROM t_advisor_run
            )
            ORDER BY start_time DESC
            FETCH FIRST :limit ROWS ONLY
        """

        try:
            return DatabaseConnector.execute_query(query, {'limit': limit})
        except Exception as e:
            st.error(f"Failed to get recent operations: {e}")
            return pd.DataFrame()


# Create singleton accessor function
@st.cache_resource
def get_compression_queries() -> CompressionQueries:
    """Get cached CompressionQueries instance"""
    return CompressionQueries()
