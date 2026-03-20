"""
Central Database Queries Module for HCC Compression Advisor
Data access layer for the centralized Oracle metadata database.
Handles all queries against central tables: analysis results, strategies,
history, target database registration, and cross-database reporting.

Split from the monolithic db_queries.py - this module covers central DB operations.
Target database queries (v$session, dba_segments, etc.) are in target_queries.py.
"""

import pandas as pd
import streamlit as st
from typing import Optional, Dict, Any, List, Tuple
from datetime import datetime, timedelta
from hcc_advisor.utils.central_connector import CentralConnector
from hcc_advisor.utils.logger import log_error, log_info, log_debug, log_warning


class CentralQueries:
    """Data access layer for centralized compression analysis operations"""

    # ============================================================================
    # DASHBOARD METHODS
    # ============================================================================

    @staticmethod
    def get_dashboard_summary(database_id: Optional[int] = None) -> Dict[str, Any]:
        """
        Get dashboard summary statistics from T_COMPRESSION_ANALYSIS

        Args:
            database_id: Optional target database ID to filter results

        Returns:
            dict: Summary with total_tables, total_size_mb, potential_savings_mb, avg_savings_pct
        """
        db_filter = "AND database_id = :database_id" if database_id else ""
        query = f"""
            SELECT
                COUNT(*) as total_tables,
                COALESCE(SUM(size_mb), 0) as total_size_mb,
                COALESCE(SUM(projected_savings_mb), 0) as potential_savings_mb,
                COALESCE(AVG(projected_savings_pct), 0) as avg_savings_pct,
                COUNT(CASE WHEN advisable_compression IS NOT NULL
                          AND advisable_compression != 'NONE' THEN 1 END) as candidates_count
            FROM t_compression_analysis
            WHERE 1=1
            {db_filter}
        """

        params = {}
        if database_id:
            params['database_id'] = database_id

        try:
            df = CentralConnector.execute_query(query, params if params else None)
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
    def get_compression_progress(database_id: Optional[int] = None) -> Dict[str, Any]:
        """Get compressed/pending/skipped breakdown for the dashboard."""
        db_filter = "AND a.database_id = :database_id" if database_id else ""
        hist_db_filter = "AND database_id = :database_id" if database_id else ""
        query = f"""
            SELECT
                COUNT(*) as total,
                COUNT(CASE WHEN a.advisable_compression IS NULL
                           OR a.advisable_compression = 'NONE' THEN 1 END) as skipped,
                COUNT(CASE WHEN a.advisable_compression IS NOT NULL
                           AND a.advisable_compression != 'NONE'
                           AND h.operation_status = 'SUCCESS' THEN 1 END) as compressed,
                COUNT(CASE WHEN a.advisable_compression IS NOT NULL
                           AND a.advisable_compression != 'NONE'
                           AND (h.operation_status IS NULL OR h.operation_status != 'SUCCESS')
                           THEN 1 END) as pending,
                COALESCE(SUM(CASE WHEN h.operation_status = 'SUCCESS'
                           THEN (a.size_mb - NVL(h.compressed_size_mb, a.size_mb))
                           ELSE 0 END), 0) as saved_mb,
                COALESCE(SUM(CASE WHEN a.advisable_compression IS NOT NULL
                           AND a.advisable_compression != 'NONE'
                           AND (h.operation_status IS NULL OR h.operation_status != 'SUCCESS')
                           THEN a.projected_savings_mb ELSE 0 END), 0) as pending_savings_mb
            FROM t_compression_analysis a
            LEFT JOIN (
                SELECT database_id, owner, object_name,
                       NVL(partition_name, '~') as pn,
                       operation_status, compressed_size_mb,
                       ROW_NUMBER() OVER (
                           PARTITION BY database_id, owner, object_name, NVL(partition_name, '~')
                           ORDER BY start_time DESC
                       ) as rn
                FROM t_compression_history
                WHERE 1=1 {hist_db_filter}
            ) h ON h.database_id = a.database_id
               AND h.owner = a.owner AND h.object_name = a.object_name
               AND h.pn = NVL(a.partition_name, '~') AND h.rn = 1
            WHERE 1=1 {db_filter}
        """
        params = {}
        if database_id:
            params['database_id'] = database_id

        try:
            df = CentralConnector.execute_query(query, params if params else None)
            if not df.empty:
                row = df.iloc[0]
                return {
                    'total': int(row.get('TOTAL', 0)),
                    'compressed': int(row.get('COMPRESSED', 0)),
                    'pending': int(row.get('PENDING', 0)),
                    'skipped': int(row.get('SKIPPED', 0)),
                    'saved_mb': float(row.get('SAVED_MB', 0)),
                    'pending_savings_mb': float(row.get('PENDING_SAVINGS_MB', 0)),
                }
        except Exception as e:
            log_error(e, "get_compression_progress")
        return {'total': 0, 'compressed': 0, 'pending': 0, 'skipped': 0,
                'saved_mb': 0, 'pending_savings_mb': 0}

    @staticmethod
    def get_savings_by_strategy(database_id: Optional[int] = None) -> pd.DataFrame:
        """
        Get savings breakdown grouped by compression strategy

        Args:
            database_id: Optional target database ID to filter results

        Returns:
            DataFrame with strategy, count, avg_savings_pct, total_size_mb, total_savings_mb
        """
        db_filter = "AND database_id = :database_id" if database_id else ""
        query = f"""
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
              {db_filter}
            GROUP BY advisable_compression
            ORDER BY total_savings_gb DESC
        """

        params = {}
        if database_id:
            params['database_id'] = database_id

        try:
            return CentralConnector.execute_query(query, params if params else None)
        except Exception as e:
            log_error(e, "get_savings_by_strategy")
            st.error(f"Failed to get savings by strategy: {e}")
            return pd.DataFrame()

    @staticmethod
    def get_recent_executions(limit: int = 5, database_id: Optional[int] = None) -> pd.DataFrame:
        """
        Get recent compression executions from T_COMPRESSION_HISTORY

        Args:
            limit: Maximum number of records to return
            database_id: Optional target database ID to filter results

        Returns:
            DataFrame with recent execution history
        """
        db_filter = "AND database_id = :database_id" if database_id else ""
        query = f"""
            SELECT
                history_id,
                database_id,
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
            WHERE 1=1
            {db_filter}
            ORDER BY start_time DESC
            FETCH FIRST :limit ROWS ONLY
        """

        params = {'limit': limit}
        if database_id:
            params['database_id'] = database_id

        try:
            return CentralConnector.execute_query(query, params)
        except Exception as e:
            log_error(e, "get_recent_executions")
            st.error(f"Failed to get recent executions: {e}")
            return pd.DataFrame()

    # ============================================================================
    # ANALYSIS RESULT METHODS
    # ============================================================================

    @staticmethod
    def get_analysis_runs(limit: int = 10, database_id: Optional[int] = None) -> pd.DataFrame:
        """
        Get list of analysis runs from T_ADVISOR_RUN

        Args:
            limit: Maximum number of runs to return
            database_id: Optional target database ID to filter results

        Returns:
            DataFrame with analysis run history
        """
        db_filter = "AND database_id = :database_id" if database_id else ""
        query = f"""
            SELECT
                run_id,
                database_id,
                start_time as run_date,
                schema_filter as owner_filter,
                run_status as status,
                objects_analyzed as tables_analyzed,
                (recommend_basic + recommend_oltp + recommend_adv_low + recommend_adv_high) as candidates_found,
                duration_minutes * 60 as duration_seconds,
                error_message
            FROM t_advisor_run
            WHERE 1=1
            {db_filter}
            ORDER BY start_time DESC
            FETCH FIRST :limit ROWS ONLY
        """

        params = {'limit': limit}
        if database_id:
            params['database_id'] = database_id

        try:
            return CentralConnector.execute_query(query, params)
        except Exception as e:
            log_error(e, "get_analysis_runs")
            st.error(f"Failed to get analysis runs: {e}")
            return pd.DataFrame()

    @staticmethod
    def get_latest_analysis(database_id: Optional[int] = None) -> Dict[str, Any]:
        """
        Get the latest analysis run and its summary

        Args:
            database_id: Optional target database ID to filter results

        Returns:
            dict with analysis summary
        """
        db_filter = "AND database_id = :database_id" if database_id else ""
        inner_db_filter = "AND database_id = :database_id" if database_id else ""
        query = f"""
            SELECT
                r.run_id as analysis_id,
                r.database_id,
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
            WHERE r.run_id = (
                SELECT MAX(run_id) FROM t_advisor_run WHERE 1=1 {inner_db_filter}
            )
            {db_filter}
        """

        params = {}
        if database_id:
            params['database_id'] = database_id

        try:
            df = CentralConnector.execute_query(query, params if params else None)
            if not df.empty:
                row = df.iloc[0]
                return {
                    'analysis_id': row.get('ANALYSIS_ID'),
                    'database_id': row.get('DATABASE_ID'),
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
            log_error(e, "get_latest_analysis")
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
                database_id,
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
            return CentralConnector.execute_query(query, {'run_id': run_id})
        except Exception as e:
            log_error(e, "get_analysis_results", {'run_id': run_id})
            st.error(f"Failed to get analysis results: {e}")
            return pd.DataFrame()

    @staticmethod
    def get_analysis_details(analysis_id: int) -> Dict[str, Any]:
        """
        Get detailed analysis information for a specific recommendation

        Args:
            analysis_id: Analysis ID

        Returns:
            dict with detailed analysis data including compression ratios, activity metrics
        """
        query = """
            SELECT *
            FROM t_compression_analysis
            WHERE analysis_id = :analysis_id
        """

        try:
            df = CentralConnector.execute_query(query, {'analysis_id': analysis_id})
            if not df.empty:
                row = df.iloc[0]
                return row.to_dict()
        except Exception as e:
            log_error(e, "get_analysis_details", {'analysis_id': analysis_id})
            st.error(f"Failed to get analysis details: {e}")

        return {}

    # ============================================================================
    # RECOMMENDATION METHODS
    # ============================================================================

    @staticmethod
    def get_recommendations(
        schema: Optional[str] = None,
        strategy: Optional[str] = None,
        min_savings_pct: float = 10.0,
        min_size_mb: float = 0.0,
        limit: int = 100,
        database_id: Optional[int] = None,
        show_executed: bool = True
    ) -> pd.DataFrame:
        """
        Get compression recommendations from T_COMPRESSION_ANALYSIS with execution status.

        Args:
            schema: Filter by schema/owner (None for all)
            strategy: Filter by compression strategy (None for all)
            min_savings_pct: Minimum savings percentage
            min_size_mb: Minimum table size in MB
            limit: Maximum number of results
            database_id: Optional target database ID to filter results
            show_executed: If False, hide objects already compressed successfully

        Returns:
            DataFrame with recommendations including execution_status column
        """
        db_filter = "AND a.database_id = :database_id" if database_id else ""
        hist_db_filter = "AND database_id = :database_id" if database_id else ""
        executed_filter = "" if show_executed else "AND (h.operation_status IS NULL OR h.operation_status != 'SUCCESS')"
        query = f"""
            SELECT
                a.analysis_id as recommendation_id,
                a.database_id,
                a.owner as table_owner,
                a.object_name as table_name,
                a.object_type,
                a.partition_name,
                a.subpartition_name,
                a.size_mb as current_size_mb,
                a.row_count as estimated_rows,
                a.current_compression,
                a.advisable_compression as recommended_strategy,
                a.size_mb - a.projected_savings_mb as estimated_size_mb,
                a.projected_savings_pct as savings_pct,
                a.best_ratio as compression_ratio,
                a.basic_ratio,
                a.oltp_ratio,
                a.adv_low_ratio as query_low_ratio,
                a.adv_high_ratio as query_high_ratio,
                a.hotness_score,
                a.hotness_category,
                a.recommendation_reason,
                CASE WHEN h.operation_status = 'SUCCESS' THEN 'Compressed'
                     WHEN h.operation_status IS NOT NULL THEN h.operation_status
                     ELSE 'Pending' END as execution_status
            FROM t_compression_analysis a
            LEFT JOIN (
                SELECT owner, object_name,
                       NVL(partition_name, '~') as pn,
                       database_id, operation_status,
                       ROW_NUMBER() OVER (
                           PARTITION BY database_id, owner, object_name, NVL(partition_name, '~')
                           ORDER BY start_time DESC
                       ) as rn
                FROM t_compression_history
                WHERE 1=1 {hist_db_filter}
            ) h ON h.database_id = a.database_id
               AND h.owner = a.owner AND h.object_name = a.object_name
               AND h.pn = NVL(a.partition_name, '~') AND h.rn = 1
            WHERE a.advisable_compression IS NOT NULL
              AND a.advisable_compression != 'NONE'
              AND a.projected_savings_pct >= :min_savings_pct
              AND a.size_mb >= :min_size_mb
              AND (:schema IS NULL OR a.owner = :schema)
              AND (:strategy IS NULL OR a.advisable_compression = :strategy)
              {db_filter}
              {executed_filter}
            ORDER BY a.projected_savings_mb DESC
            FETCH FIRST :limit ROWS ONLY
        """

        params = {
            'schema': schema,
            'strategy': strategy,
            'min_savings_pct': min_savings_pct,
            'min_size_mb': min_size_mb,
            'limit': limit
        }
        if database_id:
            params['database_id'] = database_id

        try:
            return CentralConnector.execute_query(query, params)
        except Exception as e:
            log_error(e, "get_recommendations")
            st.error(f"Failed to get recommendations: {e}")
            return pd.DataFrame()

    @staticmethod
    def get_compression_candidates(database_id: Optional[int] = None) -> pd.DataFrame:
        """
        Get compression candidates from V_COMPRESSION_CANDIDATES view

        Args:
            database_id: Optional target database ID to filter results

        Returns:
            DataFrame with compression candidates
        """
        db_filter = "WHERE database_id = :database_id" if database_id else ""
        query = f"""
            SELECT * FROM v_compression_candidates
            {db_filter}
            ORDER BY projected_savings_mb DESC
        """

        params = {}
        if database_id:
            params['database_id'] = database_id

        try:
            return CentralConnector.execute_query(query, params if params else None)
        except Exception as e:
            # Fallback to direct query if view doesn't exist
            log_debug(f"v_compression_candidates view not available, using fallback: {e}")
            return CentralQueries.get_recommendations(database_id=database_id)

    @staticmethod
    def get_hot_objects(database_id: Optional[int] = None) -> pd.DataFrame:
        """
        Get hot objects from V_HOT_OBJECTS view (frequently accessed)

        Args:
            database_id: Optional target database ID to filter results

        Returns:
            DataFrame with hot objects
        """
        db_filter = "WHERE database_id = :database_id" if database_id else ""
        query = f"""
            SELECT * FROM v_hot_objects
            {db_filter}
            ORDER BY hotness_score DESC
        """

        params = {}
        if database_id:
            params['database_id'] = database_id

        try:
            return CentralConnector.execute_query(query, params if params else None)
        except Exception as e:
            # Fallback query
            log_debug(f"v_hot_objects view not available, using fallback: {e}")
            db_filter_fb = "AND database_id = :database_id" if database_id else ""
            fallback_query = f"""
                SELECT
                    owner, object_name, object_type, database_id,
                    size_mb, hotness_score, advisable_compression
                FROM t_compression_analysis
                WHERE hotness_score >= 50
                {db_filter_fb}
                ORDER BY hotness_score DESC
            """
            return CentralConnector.execute_query(fallback_query, params if params else None)

    @staticmethod
    def get_cold_objects(database_id: Optional[int] = None) -> pd.DataFrame:
        """
        Get cold objects from V_COLD_OBJECTS view (rarely accessed)

        Args:
            database_id: Optional target database ID to filter results

        Returns:
            DataFrame with cold objects
        """
        db_filter = "WHERE database_id = :database_id" if database_id else ""
        query = f"""
            SELECT * FROM v_cold_objects
            {db_filter}
            ORDER BY size_mb DESC
        """

        params = {}
        if database_id:
            params['database_id'] = database_id

        try:
            return CentralConnector.execute_query(query, params if params else None)
        except Exception as e:
            # Fallback query
            log_debug(f"v_cold_objects view not available, using fallback: {e}")
            db_filter_fb = "AND database_id = :database_id" if database_id else ""
            fallback_query = f"""
                SELECT
                    owner, object_name, object_type, database_id,
                    size_mb, hotness_score, advisable_compression
                FROM t_compression_analysis
                WHERE hotness_score < 50
                {db_filter_fb}
                ORDER BY size_mb DESC
            """
            return CentralConnector.execute_query(fallback_query, params if params else None)

    # ============================================================================
    # HISTORY METHODS
    # ============================================================================

    @staticmethod
    def get_execution_history(
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        status: Optional[str] = None,
        limit: int = 100,
        database_id: Optional[int] = None
    ) -> pd.DataFrame:
        """
        Get execution history from T_COMPRESSION_HISTORY with filters

        Args:
            start_date: Start date filter (ISO format)
            end_date: End date filter (ISO format)
            status: Status filter
            limit: Maximum results
            database_id: Optional target database ID to filter results

        Returns:
            DataFrame with execution history
        """
        db_filter = "AND database_id = :database_id" if database_id else ""
        query = f"""
            SELECT
                history_id as execution_id,
                database_id,
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
              {db_filter}
            ORDER BY start_time DESC
            FETCH FIRST :limit ROWS ONLY
        """

        params = {
            'start_date': start_date,
            'end_date': end_date,
            'status': status,
            'limit': limit
        }
        if database_id:
            params['database_id'] = database_id

        try:
            return CentralConnector.execute_query(query, params)
        except Exception as e:
            log_error(e, "get_execution_history")
            st.error(f"Failed to get execution history: {e}")
            return pd.DataFrame()

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
                database_id,
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
            df = CentralConnector.execute_query(query, {'history_id': history_id})
            if not df.empty:
                return df.iloc[0].to_dict()
        except Exception as e:
            log_error(e, "get_execution_status", {'history_id': history_id})
            st.error(f"Failed to get execution status: {e}")

        return {}

    @staticmethod
    def get_compression_effectiveness(database_id: Optional[int] = None) -> pd.DataFrame:
        """
        Get compression effectiveness statistics

        Args:
            database_id: Optional target database ID to filter results

        Returns:
            DataFrame with effectiveness metrics
        """
        db_filter = "WHERE database_id = :database_id" if database_id else ""
        query = f"""
            SELECT * FROM v_compression_effectiveness
            {db_filter}
        """

        params = {}
        if database_id:
            params['database_id'] = database_id

        try:
            return CentralConnector.execute_query(query, params if params else None)
        except Exception as e:
            # Fallback to aggregated query
            log_debug(f"v_compression_effectiveness view not available, using fallback: {e}")
            db_filter_fb = "AND database_id = :database_id" if database_id else ""
            fallback_query = f"""
                SELECT
                    compression_type_applied as strategy,
                    COUNT(*) as execution_count,
                    AVG(space_saved_pct) as avg_savings_pct,
                    SUM(space_saved_mb) as total_savings_mb,
                    COUNT(CASE WHEN operation_status = 'SUCCESS' THEN 1 END) as success_count
                FROM t_compression_history
                WHERE operation_status = 'SUCCESS'
                {db_filter_fb}
                GROUP BY compression_type_applied
                ORDER BY total_savings_mb DESC
            """
            return CentralConnector.execute_query(fallback_query, params if params else None)

    # ============================================================================
    # STRATEGY METHODS (Global - NO database_id filter)
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
            return CentralConnector.execute_query(query)
        except Exception as e:
            log_warning(f"Could not load strategies from database: {e}")
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
            return CentralConnector.execute_query(query, {'strategy_id': strategy_id})
        except Exception as e:
            log_error(e, "get_strategy_rules", {'strategy_id': strategy_id})
            return pd.DataFrame()

    @staticmethod
    def get_all_strategies(include_inactive: bool = True) -> pd.DataFrame:
        """
        Get all compression strategies with full details for management

        Args:
            include_inactive: Include inactive strategies

        Returns:
            DataFrame with all strategy columns
        """
        query = """
            SELECT
                strategy_id,
                strategy_name,
                description,
                category,
                hotness_threshold_hot,
                hotness_threshold_warm,
                hotness_threshold_cool,
                dml_threshold_high,
                dml_threshold_medium,
                dml_threshold_low,
                size_threshold_large_gb,
                size_threshold_medium_gb,
                size_threshold_small_gb,
                age_threshold_recent_days,
                age_threshold_old_days,
                age_threshold_archive_days,
                min_compression_ratio,
                min_space_savings_mb,
                active_flag,
                is_default,
                priority,
                created_date,
                created_by,
                modified_date,
                modified_by
            FROM t_compression_strategies
            WHERE (:include_inactive = 'Y' OR active_flag = 'Y')
            ORDER BY is_default DESC NULLS LAST, priority DESC, strategy_name
        """

        try:
            return CentralConnector.execute_query(query, {
                'include_inactive': 'Y' if include_inactive else 'N'
            })
        except Exception as e:
            log_error(e, "get_all_strategies")
            return pd.DataFrame()

    @staticmethod
    def get_strategy_by_id(strategy_id: int) -> Dict[str, Any]:
        """
        Get a single strategy by ID with all details

        Args:
            strategy_id: Strategy ID

        Returns:
            dict with strategy details
        """
        query = """
            SELECT *
            FROM t_compression_strategies
            WHERE strategy_id = :strategy_id
        """

        try:
            df = CentralConnector.execute_query(query, {'strategy_id': strategy_id})
            if not df.empty:
                return df.iloc[0].to_dict()
        except Exception as e:
            log_error(e, "get_strategy_by_id", {'strategy_id': strategy_id})

        return {}

    @staticmethod
    def save_strategy(strategy_data: Dict[str, Any]) -> Tuple[bool, str]:
        """
        Create or update a compression strategy

        Args:
            strategy_data: Dictionary with strategy fields

        Returns:
            Tuple of (success, message)
        """
        strategy_id = strategy_data.get('strategy_id')

        if strategy_id:
            # Update existing strategy
            query = """
                UPDATE t_compression_strategies SET
                    strategy_name = :strategy_name,
                    description = :description,
                    category = :category,
                    hotness_threshold_hot = :hotness_threshold_hot,
                    hotness_threshold_warm = :hotness_threshold_warm,
                    hotness_threshold_cool = :hotness_threshold_cool,
                    dml_threshold_high = :dml_threshold_high,
                    dml_threshold_medium = :dml_threshold_medium,
                    dml_threshold_low = :dml_threshold_low,
                    size_threshold_large_gb = :size_threshold_large_gb,
                    size_threshold_medium_gb = :size_threshold_medium_gb,
                    size_threshold_small_gb = :size_threshold_small_gb,
                    age_threshold_recent_days = :age_threshold_recent_days,
                    age_threshold_old_days = :age_threshold_old_days,
                    age_threshold_archive_days = :age_threshold_archive_days,
                    min_compression_ratio = :min_compression_ratio,
                    min_space_savings_mb = :min_space_savings_mb,
                    active_flag = :active_flag,
                    priority = :priority,
                    modified_date = SYSDATE,
                    modified_by = USER
                WHERE strategy_id = :strategy_id
            """
        else:
            # Insert new strategy
            query = """
                INSERT INTO t_compression_strategies (
                    strategy_name, description, category,
                    hotness_threshold_hot, hotness_threshold_warm, hotness_threshold_cool,
                    dml_threshold_high, dml_threshold_medium, dml_threshold_low,
                    size_threshold_large_gb, size_threshold_medium_gb, size_threshold_small_gb,
                    age_threshold_recent_days, age_threshold_old_days, age_threshold_archive_days,
                    min_compression_ratio, min_space_savings_mb, active_flag, priority,
                    created_date, created_by
                ) VALUES (
                    :strategy_name, :description, :category,
                    :hotness_threshold_hot, :hotness_threshold_warm, :hotness_threshold_cool,
                    :dml_threshold_high, :dml_threshold_medium, :dml_threshold_low,
                    :size_threshold_large_gb, :size_threshold_medium_gb, :size_threshold_small_gb,
                    :age_threshold_recent_days, :age_threshold_old_days, :age_threshold_archive_days,
                    :min_compression_ratio, :min_space_savings_mb, :active_flag, :priority,
                    SYSDATE, USER
                )
            """

        try:
            rows_affected = CentralConnector.execute_dml(query, strategy_data)
            if rows_affected:
                action = "updated" if strategy_id else "created"
                return True, f"Strategy {action} successfully"
            return False, "Failed to save strategy"
        except Exception as e:
            log_error(e, "save_strategy", strategy_data)
            return False, str(e)

    @staticmethod
    def delete_strategy(strategy_id: int) -> Tuple[bool, str]:
        """
        Delete a compression strategy (soft delete by setting inactive)

        Args:
            strategy_id: Strategy ID to delete

        Returns:
            Tuple of (success, message)
        """
        # First check if it's the default strategy
        check_query = "SELECT is_default FROM t_compression_strategies WHERE strategy_id = :strategy_id"
        try:
            df = CentralConnector.execute_query(check_query, {'strategy_id': strategy_id})
            if not df.empty and df.iloc[0].get('IS_DEFAULT') == 'Y':
                return False, "Cannot delete the default strategy"

            # Soft delete by setting active_flag to 'N'
            query = """
                UPDATE t_compression_strategies
                SET active_flag = 'N', modified_date = SYSDATE, modified_by = USER
                WHERE strategy_id = :strategy_id
            """
            rows_affected = CentralConnector.execute_dml(query, {'strategy_id': strategy_id})
            if rows_affected:
                return True, "Strategy deactivated successfully"
            return False, "Failed to delete strategy"
        except Exception as e:
            log_error(e, "delete_strategy", {'strategy_id': strategy_id})
            return False, str(e)

    @staticmethod
    def set_default_strategy(strategy_id: int) -> Tuple[bool, str]:
        """
        Set a strategy as the default

        Args:
            strategy_id: Strategy ID to set as default

        Returns:
            Tuple of (success, message)
        """
        try:
            # Clear existing default
            clear_query = "UPDATE t_compression_strategies SET is_default = NULL WHERE is_default = 'Y'"
            CentralConnector.execute_dml(clear_query)

            # Set new default
            set_query = """
                UPDATE t_compression_strategies
                SET is_default = 'Y', modified_date = SYSDATE, modified_by = USER
                WHERE strategy_id = :strategy_id
            """
            rows_affected = CentralConnector.execute_dml(set_query, {'strategy_id': strategy_id})
            if rows_affected:
                return True, "Default strategy updated successfully"
            return False, "Failed to set default strategy"
        except Exception as e:
            log_error(e, "set_default_strategy", {'strategy_id': strategy_id})
            return False, str(e)

    @staticmethod
    def get_all_strategy_rules(strategy_id: Optional[int] = None) -> pd.DataFrame:
        """
        Get all strategy rules with full details for editing

        Args:
            strategy_id: Optional strategy ID to filter

        Returns:
            DataFrame with all rule columns
        """
        query = """
            SELECT
                r.rule_id,
                r.strategy_id,
                s.strategy_name,
                r.object_type,
                r.hotness_min,
                r.hotness_max,
                r.dml_ratio_threshold,
                r.compression_type,
                r.priority,
                r.enabled_flag,
                r.rule_description
            FROM t_strategy_rules r
            JOIN t_compression_strategies s ON r.strategy_id = s.strategy_id
            WHERE (:strategy_id IS NULL OR r.strategy_id = :strategy_id)
            ORDER BY r.strategy_id, r.priority
        """

        try:
            return CentralConnector.execute_query(query, {'strategy_id': strategy_id})
        except Exception as e:
            log_error(e, "get_all_strategy_rules")
            return pd.DataFrame()

    @staticmethod
    def save_strategy_rule(rule_data: Dict[str, Any]) -> Tuple[bool, str]:
        """
        Create or update a strategy rule

        Args:
            rule_data: Dictionary with rule fields

        Returns:
            Tuple of (success, message)
        """
        rule_id = rule_data.get('rule_id')

        if rule_id:
            query = """
                UPDATE t_strategy_rules SET
                    strategy_id = :strategy_id,
                    object_type = :object_type,
                    hotness_min = :hotness_min,
                    hotness_max = :hotness_max,
                    dml_ratio_threshold = :dml_ratio_threshold,
                    compression_type = :compression_type,
                    priority = :priority,
                    enabled_flag = :enabled_flag,
                    rule_description = :rule_description
                WHERE rule_id = :rule_id
            """
        else:
            query = """
                INSERT INTO t_strategy_rules (
                    strategy_id, object_type, hotness_min, hotness_max,
                    dml_ratio_threshold, compression_type, priority,
                    enabled_flag, rule_description
                ) VALUES (
                    :strategy_id, :object_type, :hotness_min, :hotness_max,
                    :dml_ratio_threshold, :compression_type, :priority,
                    :enabled_flag, :rule_description
                )
            """

        try:
            rows_affected = CentralConnector.execute_dml(query, rule_data)
            if rows_affected:
                action = "updated" if rule_id else "created"
                return True, f"Rule {action} successfully"
            return False, "Failed to save rule"
        except Exception as e:
            log_error(e, "save_strategy_rule", rule_data)
            return False, str(e)

    @staticmethod
    def delete_strategy_rule(rule_id: int) -> Tuple[bool, str]:
        """
        Delete a strategy rule

        Args:
            rule_id: Rule ID to delete

        Returns:
            Tuple of (success, message)
        """
        try:
            query = "DELETE FROM t_strategy_rules WHERE rule_id = :rule_id"
            rows_affected = CentralConnector.execute_dml(query, {'rule_id': rule_id})
            if rows_affected:
                return True, "Rule deleted successfully"
            return False, "Failed to delete rule"
        except Exception as e:
            log_error(e, "delete_strategy_rule", {'rule_id': rule_id})
            return False, str(e)

    # ============================================================================
    # INDEX & LOB ANALYSIS METHODS
    # ============================================================================

    @staticmethod
    def get_index_compression_analysis(
        owner: Optional[str] = None,
        table_name: Optional[str] = None,
        database_id: Optional[int] = None
    ) -> pd.DataFrame:
        """
        Get index compression analysis from T_INDEX_COMPRESSION_ANALYSIS

        Args:
            owner: Optional schema filter
            table_name: Optional table filter
            database_id: Optional target database ID to filter results

        Returns:
            DataFrame with index compression analysis
        """
        db_filter = "AND database_id = :database_id" if database_id else ""
        query = f"""
            SELECT
                index_analysis_id,
                database_id,
                index_owner,
                index_name,
                table_owner,
                table_name,
                index_type,
                uniqueness,
                partition_name,
                index_size_mb,
                leaf_blocks,
                distinct_keys,
                clustering_factor,
                prefix_compression_ratio,
                advanced_low_ratio,
                advanced_high_ratio,
                blkcnt_uncmp_prefix,
                blkcnt_cmp_prefix,
                blkcnt_uncmp_adv_low,
                blkcnt_cmp_adv_low,
                blkcnt_uncmp_adv_high,
                blkcnt_cmp_adv_high,
                current_compression,
                current_prefix_length,
                scan_count,
                lookup_count,
                access_frequency,
                advisable_compression,
                recommended_prefix_length,
                recommendation_reason,
                projected_savings_mb,
                analysis_date
            FROM t_index_compression_analysis
            WHERE (:owner IS NULL OR table_owner = :owner)
              AND (:table_name IS NULL OR table_name = :table_name)
              {db_filter}
            ORDER BY projected_savings_mb DESC NULLS LAST
        """

        params = {
            'owner': owner.upper() if owner else None,
            'table_name': table_name.upper() if table_name else None
        }
        if database_id:
            params['database_id'] = database_id

        try:
            return CentralConnector.execute_query(query, params)
        except Exception as e:
            log_error(e, "get_index_compression_analysis")
            return pd.DataFrame()

    @staticmethod
    def get_lob_compression_analysis(
        owner: Optional[str] = None,
        table_name: Optional[str] = None,
        database_id: Optional[int] = None
    ) -> pd.DataFrame:
        """
        Get LOB compression analysis from T_LOB_COMPRESSION_ANALYSIS

        Args:
            owner: Optional schema filter
            table_name: Optional table filter
            database_id: Optional target database ID to filter results

        Returns:
            DataFrame with LOB compression analysis
        """
        db_filter = "AND database_id = :database_id" if database_id else ""
        query = f"""
            SELECT
                lob_analysis_id,
                database_id,
                table_owner,
                table_name,
                column_name,
                lob_name,
                data_type,
                securefile,
                partition_name,
                lob_size_mb,
                num_lobs,
                avg_lob_size_kb,
                current_compression,
                current_deduplication,
                current_encryption,
                chunk_size,
                low_compression_ratio,
                medium_compression_ratio,
                high_compression_ratio,
                dedup_savings_pct,
                blkcnt_uncmp_low,
                blkcnt_cmp_low,
                blkcnt_uncmp_medium,
                blkcnt_cmp_medium,
                blkcnt_uncmp_high,
                blkcnt_cmp_high,
                read_frequency,
                write_frequency,
                read_write_ratio,
                advisable_compression,
                advisable_dedup,
                recommendation_reason,
                projected_savings_mb,
                recommend_securefile,
                analysis_date
            FROM t_lob_compression_analysis
            WHERE (:owner IS NULL OR table_owner = :owner)
              AND (:table_name IS NULL OR table_name = :table_name)
              {db_filter}
            ORDER BY projected_savings_mb DESC NULLS LAST
        """

        params = {
            'owner': owner.upper() if owner else None,
            'table_name': table_name.upper() if table_name else None
        }
        if database_id:
            params['database_id'] = database_id

        try:
            return CentralConnector.execute_query(query, params)
        except Exception as e:
            log_error(e, "get_lob_compression_analysis")
            return pd.DataFrame()

    # ============================================================================
    # JUSTIFICATION METHOD
    # ============================================================================

    @staticmethod
    def build_recommendation_justification(analysis_id: int) -> Dict[str, Any]:
        """
        Build comprehensive recommendation justification for display.
        Reads all data from central T_COMPRESSION_ANALYSIS table.
        Does NOT call target DB methods (get_segment_info, get_table_tablespace)
        -- those are in target_queries.py.

        Args:
            analysis_id: Analysis ID

        Returns:
            dict with comprehensive justification data
        """
        details = CentralQueries.get_analysis_details(analysis_id)

        if not details:
            return {'error': 'Analysis not found'}

        owner = details.get('OWNER', '')
        table_name = details.get('OBJECT_NAME', '')

        # Build justification structure from central analysis data
        justification = {
            'summary': {
                'table': f"{owner}.{table_name}",
                'database_id': details.get('DATABASE_ID'),
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

        return justification

    # ============================================================================
    # MONITORING METHODS (read from central result tables)
    # ============================================================================

    @staticmethod
    def get_running_operations(database_id: Optional[int] = None) -> pd.DataFrame:
        """
        Get currently running compression or analysis operations

        Args:
            database_id: Optional target database ID to filter results

        Returns:
            DataFrame with running operations
        """
        db_filter = "AND database_id = :database_id" if database_id else ""
        query = f"""
            SELECT
                history_id as operation_id,
                'COMPRESSION' as operation_type,
                database_id,
                owner,
                object_name as table_name,
                partition_name,
                compression_type_applied as strategy,
                operation_status as status,
                start_time,
                ROUND((CAST(SYSDATE AS DATE) - CAST(start_time AS DATE)) * 24 * 60, 1) as duration_minutes,
                original_size_mb,
                NULL as progress_pct
            FROM t_compression_history
            WHERE operation_status = 'IN_PROGRESS'
            {db_filter}
            UNION ALL
            SELECT
                run_id as operation_id,
                'ANALYSIS' as operation_type,
                database_id,
                schema_filter as owner,
                'All Tables' as table_name,
                NULL as partition_name,
                'Balanced' as strategy,
                run_status as status,
                start_time,
                ROUND((CAST(SYSDATE AS DATE) - CAST(start_time AS DATE)) * 24 * 60, 1) as duration_minutes,
                total_size_mb as original_size_mb,
                NULL as progress_pct
            FROM t_advisor_run
            WHERE run_status = 'RUNNING'
            {db_filter}
            ORDER BY start_time DESC
        """

        params = {}
        if database_id:
            params['database_id'] = database_id

        try:
            return CentralConnector.execute_query(query, params if params else None)
        except Exception as e:
            log_error(e, "get_running_operations")
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
                    database_id,
                    owner,
                    object_name as table_name,
                    partition_name,
                    compression_type_applied as strategy,
                    operation_status as status,
                    start_time,
                    end_time,
                    ROUND((CAST(NVL(end_time, SYSTIMESTAMP) AS DATE) - CAST(start_time AS DATE)) * 24 * 60, 1) as duration_minutes,
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
                    database_id,
                    schema_filter as owner,
                    run_status as status,
                    start_time,
                    end_time,
                    ROUND((CAST(NVL(end_time, SYSTIMESTAMP) AS DATE) - CAST(start_time AS DATE)) * 24 * 60, 1) as duration_minutes,
                    objects_analyzed,
                    objects_failed,
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
            df = CentralConnector.execute_query(query, {'operation_id': operation_id})
            if not df.empty:
                return df.iloc[0].to_dict()
        except Exception as e:
            log_error(e, "get_operation_progress", {
                'operation_type': operation_type,
                'operation_id': operation_id
            })
            st.error(f"Failed to get operation progress: {e}")

        return {}

    @staticmethod
    def get_recent_operations(limit: int = 10, database_id: Optional[int] = None) -> pd.DataFrame:
        """
        Get recent operations (both analysis and compression)

        Args:
            limit: Maximum number of operations
            database_id: Optional target database ID to filter results

        Returns:
            DataFrame with recent operations
        """
        db_filter = "AND database_id = :database_id" if database_id else ""
        query = f"""
            SELECT * FROM (
                SELECT
                    history_id as operation_id,
                    'COMPRESSION' as operation_type,
                    database_id,
                    owner,
                    object_name as name,
                    partition_name as detail,
                    compression_type_applied as strategy,
                    operation_status as status,
                    start_time,
                    end_time,
                    ROUND((CAST(NVL(end_time, SYSDATE) AS DATE) - CAST(start_time AS DATE)) * 24 * 60, 1) as duration_minutes,
                    space_saved_pct as result_pct,
                    error_message
                FROM t_compression_history
                WHERE 1=1
                {db_filter}
                UNION ALL
                SELECT
                    run_id as operation_id,
                    'ANALYSIS' as operation_type,
                    database_id,
                    schema_filter as owner,
                    'Schema Analysis' as name,
                    TO_CHAR(objects_analyzed) || ' objects' as detail,
                    'Balanced' as strategy,
                    run_status as status,
                    start_time,
                    end_time,
                    ROUND((CAST(NVL(end_time, SYSDATE) AS DATE) - CAST(start_time AS DATE)) * 24 * 60, 1) as duration_minutes,
                    projected_savings_pct as result_pct,
                    error_message
                FROM t_advisor_run
                WHERE 1=1
                {db_filter}
            )
            ORDER BY start_time DESC
            FETCH FIRST :limit ROWS ONLY
        """

        params = {'limit': limit}
        if database_id:
            params['database_id'] = database_id

        try:
            return CentralConnector.execute_query(query, params)
        except Exception as e:
            log_error(e, "get_recent_operations")
            st.error(f"Failed to get recent operations: {e}")
            return pd.DataFrame()

    # ============================================================================
    # TARGET DATABASE MANAGEMENT METHODS
    # ============================================================================

    @staticmethod
    def get_target_databases() -> pd.DataFrame:
        """
        Get all active target databases

        Returns:
            DataFrame with target database information
        """
        query = """
            SELECT
                database_id,
                database_name,
                display_name,
                db_host,
                port,
                service_name,
                username,
                password_encrypted,
                description,
                environment,
                platform_type,
                is_active,
                last_connected,
                last_analysis_date,
                oracle_version,
                created_date,
                created_by
            FROM t_target_databases
            WHERE is_active = 'Y'
            ORDER BY display_name
        """

        try:
            return CentralConnector.execute_query(query)
        except Exception as e:
            log_error(e, "get_target_databases")
            st.error(f"Failed to get target databases: {e}")
            return pd.DataFrame()

    @staticmethod
    def get_target_database(database_id: int) -> Dict[str, Any]:
        """
        Get a single target database by ID

        Args:
            database_id: Target database ID

        Returns:
            dict with target database details
        """
        query = """
            SELECT *
            FROM t_target_databases
            WHERE database_id = :database_id
        """

        try:
            df = CentralConnector.execute_query(query, {'database_id': database_id})
            if not df.empty:
                row = {k.lower(): v for k, v in df.iloc[0].to_dict().items()}
                # Map column names for connector compatibility
                if 'db_host' in row:
                    row['host'] = row['db_host']
                if 'service_name' in row:
                    row['service'] = row['service_name']
                # Decrypt password for target connector
                if 'password_encrypted' in row and row['password_encrypted']:
                    try:
                        from hcc_advisor.views.page_06_connections import decrypt_password
                        row['password'] = decrypt_password(row['password_encrypted'])
                    except Exception:
                        row['password'] = row['password_encrypted']
                return row
        except Exception as e:
            log_error(e, "get_target_database", {'database_id': database_id})

        return {}

    @staticmethod
    def add_target_database(db_data: Dict[str, Any]) -> Tuple[bool, str, Optional[int]]:
        """
        Register a new target database

        Args:
            db_data: Dictionary with database connection details:
                - database_name, display_name, db_host, port, service_name,
                  username, password_encrypted, description, environment,
                  platform_type

        Returns:
            Tuple of (success, message, new_database_id)
        """
        insert_query = """
            INSERT INTO t_target_databases (
                database_name, display_name, db_host, port, service_name,
                username, password_encrypted, description, environment,
                platform_type, oracle_version, is_active, created_date, created_by
            ) VALUES (
                :database_name, :display_name, :db_host, :port, :service_name,
                :username, :password_encrypted, :description, :environment,
                :platform_type, :oracle_version, 'Y', SYSDATE, USER
            )
        """

        try:
            rows_affected = CentralConnector.execute_dml(insert_query, db_data)
            if rows_affected:
                # Retrieve the new database_id
                id_query = """
                    SELECT database_id
                    FROM t_target_databases
                    WHERE database_name = :database_name
                """
                df = CentralConnector.execute_query(id_query, {
                    'database_name': db_data.get('database_name')
                })
                new_id = int(df.iloc[0]['DATABASE_ID']) if not df.empty else None
                log_info(f"Target database registered: {db_data.get('database_name')} (ID: {new_id})")
                return True, "Target database registered successfully", new_id
            return False, "Failed to register target database", None
        except Exception as e:
            log_error(e, "add_target_database", db_data)
            return False, str(e), None

    @staticmethod
    def update_target_database(database_id: int, db_data: Dict[str, Any]) -> Tuple[bool, str]:
        """
        Update a target database registration

        Args:
            database_id: Target database ID
            db_data: Dictionary with fields to update

        Returns:
            Tuple of (success, message)
        """
        query = """
            UPDATE t_target_databases SET
                display_name = :display_name,
                db_host = :db_host,
                port = :port,
                service_name = :service_name,
                username = :username,
                description = :description,
                environment = :environment,
                platform_type = :platform_type,
                modified_date = SYSDATE,
                modified_by = USER
            WHERE database_id = :database_id
        """

        params = dict(db_data)
        params['database_id'] = database_id

        # If password_encrypted is provided, update it separately
        if 'password_encrypted' in db_data and db_data['password_encrypted']:
            password_query = """
                UPDATE t_target_databases
                SET password_encrypted = :password_encrypted,
                    modified_date = SYSDATE,
                    modified_by = USER
                WHERE database_id = :database_id
            """
            try:
                CentralConnector.execute_dml(password_query, {
                    'password_encrypted': db_data['password_encrypted'],
                    'database_id': database_id
                })
            except Exception as e:
                log_error(e, "update_target_database (password)", {'database_id': database_id})
                return False, f"Failed to update password: {e}"

        try:
            rows_affected = CentralConnector.execute_dml(query, params)
            if rows_affected:
                log_info(f"Target database updated: ID {database_id}")
                return True, "Target database updated successfully"
            return False, "Failed to update target database"
        except Exception as e:
            log_error(e, "update_target_database", {'database_id': database_id})
            return False, str(e)

    @staticmethod
    def delete_target_database(database_id: int) -> Tuple[bool, str]:
        """
        Soft-delete a target database (set is_active='N')

        Args:
            database_id: Target database ID

        Returns:
            Tuple of (success, message)
        """
        query = """
            UPDATE t_target_databases
            SET is_active = 'N', modified_date = SYSDATE, modified_by = USER
            WHERE database_id = :database_id
        """

        try:
            rows_affected = CentralConnector.execute_dml(query, {'database_id': database_id})
            if rows_affected:
                log_info(f"Target database deactivated: ID {database_id}")
                return True, "Target database deactivated successfully"
            return False, "Failed to deactivate target database"
        except Exception as e:
            log_error(e, "delete_target_database", {'database_id': database_id})
            return False, str(e)

    @staticmethod
    def update_target_last_connected(database_id: int) -> bool:
        """
        Update the last_connected timestamp for a target database

        Args:
            database_id: Target database ID

        Returns:
            bool: True if successful
        """
        query = """
            UPDATE t_target_databases
            SET last_connected = SYSTIMESTAMP
            WHERE database_id = :database_id
        """

        try:
            rows_affected = CentralConnector.execute_dml(query, {'database_id': database_id})
            return rows_affected > 0
        except Exception as e:
            log_error(e, "update_target_last_connected", {'database_id': database_id})
            return False

    @staticmethod
    def update_target_metadata(database_id: int, oracle_version: str, platform_type: str) -> bool:
        """
        Update Oracle version and platform type for a target database

        Args:
            database_id: Target database ID
            oracle_version: Oracle version string
            platform_type: Platform type ('STANDARD' or 'EXADATA')

        Returns:
            bool: True if successful
        """
        query = """
            UPDATE t_target_databases
            SET oracle_version = :oracle_version,
                platform_type = :platform_type,
                modified_date = SYSDATE,
                modified_by = USER
            WHERE database_id = :database_id
        """

        try:
            rows_affected = CentralConnector.execute_dml(query, {
                'database_id': database_id,
                'oracle_version': oracle_version,
                'platform_type': platform_type
            })
            if rows_affected:
                log_info(f"Target database metadata updated: ID {database_id}, "
                         f"version={oracle_version}, platform={platform_type}")
            return rows_affected > 0
        except Exception as e:
            log_error(e, "update_target_metadata", {
                'database_id': database_id,
                'oracle_version': oracle_version,
                'platform_type': platform_type
            })
            return False

    # ============================================================================
    # DATA INGESTION METHODS (store results from target into central)
    # ============================================================================

    @staticmethod
    def store_advisor_run(database_id: int, run_data: Dict[str, Any]) -> Tuple[bool, Optional[int]]:
        """
        Store a new advisor run record in the central database

        Args:
            database_id: Target database ID
            run_data: Dictionary with run details:
                - run_name, run_type, run_description, schema_filter,
                  object_type_filter, object_name_pattern, include_partitions,
                  strategy_id, strategy_name, sample_size, parallel_degree,
                  analysis_mode

        Returns:
            Tuple of (success, new_run_id)
        """
        insert_query = """
            INSERT INTO t_advisor_run (
                database_id, run_name, run_type, run_description,
                schema_filter, object_type_filter, object_name_pattern,
                include_partitions, strategy_id, strategy_name,
                sample_size, parallel_degree, analysis_mode,
                start_time, run_status, initiated_by
            ) VALUES (
                :database_id, :run_name, :run_type, :run_description,
                :schema_filter, :object_type_filter, :object_name_pattern,
                :include_partitions, :strategy_id, :strategy_name,
                :sample_size, :parallel_degree, :analysis_mode,
                SYSTIMESTAMP, 'RUNNING', USER
            )
        """

        params = dict(run_data)
        params['database_id'] = database_id

        # Set defaults for optional fields
        params.setdefault('run_name', None)
        params.setdefault('run_type', 'ALL')
        params.setdefault('run_description', None)
        params.setdefault('schema_filter', None)
        params.setdefault('object_type_filter', None)
        params.setdefault('object_name_pattern', None)
        params.setdefault('include_partitions', 'N')
        params.setdefault('strategy_id', None)
        params.setdefault('strategy_name', None)
        params.setdefault('sample_size', 1000000)
        params.setdefault('parallel_degree', 4)
        params.setdefault('analysis_mode', 'FULL')

        try:
            rows_affected = CentralConnector.execute_dml(insert_query, params)
            if rows_affected:
                # Get the newly created run_id
                id_query = """
                    SELECT MAX(run_id) as run_id
                    FROM t_advisor_run
                    WHERE database_id = :database_id
                """
                df = CentralConnector.execute_query(id_query, {'database_id': database_id})
                new_run_id = int(df.iloc[0]['RUN_ID']) if not df.empty else None
                log_info(f"Advisor run stored: database_id={database_id}, run_id={new_run_id}")
                return True, new_run_id
            return False, None
        except Exception as e:
            log_error(e, "store_advisor_run", {
                'database_id': database_id,
                'run_data_keys': list(run_data.keys())
            })
            return False, None

    @staticmethod
    def store_analysis_results(database_id: int, run_id: int, results_df: pd.DataFrame) -> bool:
        """
        Batch store analysis results into T_COMPRESSION_ANALYSIS.
        Uses executemany for performance on large result sets.

        Args:
            database_id: Target database ID
            run_id: Advisor run ID
            results_df: DataFrame with analysis results. Expected columns:
                owner, object_name, object_type, partition_name, subpartition_name,
                size_bytes, row_count, block_count, avg_row_length,
                basic_ratio, oltp_ratio, adv_low_ratio, adv_high_ratio,
                blkcnt_uncmp_basic, blkcnt_cmp_basic, blkcnt_uncmp_oltp, blkcnt_cmp_oltp,
                blkcnt_uncmp_adv_low, blkcnt_cmp_adv_low, blkcnt_uncmp_adv_high, blkcnt_cmp_adv_high,
                insert_count, update_count, delete_count,
                logical_reads, physical_reads, access_frequency, last_access_date,
                hotness_score, read_ratio, write_ratio, dml_24h_rate,
                last_analyzed, data_age_days,
                current_compression, advisable_compression, recommendation_reason,
                confidence_score, projected_savings_bytes, projected_savings_pct,
                analysis_duration_sec, sample_size_rows

        Returns:
            bool: True if successful
        """
        if results_df.empty:
            log_warning("store_analysis_results called with empty DataFrame")
            return True

        merge_query = """
            MERGE INTO t_compression_analysis tgt
            USING (SELECT :database_id AS database_id, :owner AS owner,
                          :object_name AS object_name,
                          :partition_name AS partition_name,
                          :subpartition_name AS subpartition_name
                   FROM DUAL) src
            ON (    tgt.database_id = src.database_id
                AND tgt.owner = src.owner
                AND tgt.object_name = src.object_name
                AND NVL(tgt.partition_name, '~') = NVL(src.partition_name, '~')
                AND NVL(tgt.subpartition_name, '~') = NVL(src.subpartition_name, '~'))
            WHEN MATCHED THEN UPDATE SET
                advisor_run_id = NVL(:advisor_run_id, tgt.advisor_run_id),
                object_type = :object_type,
                size_bytes = :size_bytes, row_count = :row_count,
                block_count = :block_count, avg_row_length = :avg_row_length,
                basic_ratio = :basic_ratio, oltp_ratio = :oltp_ratio,
                adv_low_ratio = :adv_low_ratio, adv_high_ratio = :adv_high_ratio,
                blkcnt_uncmp_basic = :blkcnt_uncmp_basic, blkcnt_cmp_basic = :blkcnt_cmp_basic,
                blkcnt_uncmp_oltp = :blkcnt_uncmp_oltp, blkcnt_cmp_oltp = :blkcnt_cmp_oltp,
                blkcnt_uncmp_adv_low = :blkcnt_uncmp_adv_low, blkcnt_cmp_adv_low = :blkcnt_cmp_adv_low,
                blkcnt_uncmp_adv_high = :blkcnt_uncmp_adv_high, blkcnt_cmp_adv_high = :blkcnt_cmp_adv_high,
                insert_count = :insert_count, update_count = :update_count, delete_count = :delete_count,
                logical_reads = :logical_reads, physical_reads = :physical_reads,
                access_frequency = :access_frequency, last_access_date = :last_access_date,
                hotness_score = :hotness_score, read_ratio = :read_ratio,
                write_ratio = :write_ratio, dml_24h_rate = :dml_24h_rate,
                last_analyzed = :last_analyzed, data_age_days = :data_age_days,
                current_compression = :current_compression,
                advisable_compression = :advisable_compression,
                recommendation_reason = :recommendation_reason,
                confidence_score = :confidence_score,
                projected_savings_bytes = :projected_savings_bytes,
                projected_savings_pct = :projected_savings_pct,
                analysis_duration_sec = :analysis_duration_sec,
                sample_size_rows = :sample_size_rows,
                analysis_date = SYSDATE, analysis_timestamp = SYSTIMESTAMP
            WHEN NOT MATCHED THEN INSERT (
                database_id, advisor_run_id,
                owner, object_name, object_type, partition_name, subpartition_name,
                size_bytes, row_count, block_count, avg_row_length,
                basic_ratio, oltp_ratio, adv_low_ratio, adv_high_ratio,
                blkcnt_uncmp_basic, blkcnt_cmp_basic,
                blkcnt_uncmp_oltp, blkcnt_cmp_oltp,
                blkcnt_uncmp_adv_low, blkcnt_cmp_adv_low,
                blkcnt_uncmp_adv_high, blkcnt_cmp_adv_high,
                insert_count, update_count, delete_count,
                logical_reads, physical_reads, access_frequency, last_access_date,
                hotness_score, read_ratio, write_ratio, dml_24h_rate,
                last_analyzed, data_age_days,
                current_compression, advisable_compression, recommendation_reason,
                confidence_score, projected_savings_bytes, projected_savings_pct,
                analysis_duration_sec, sample_size_rows,
                analysis_date, analysis_timestamp
            ) VALUES (
                :database_id, :advisor_run_id,
                :owner, :object_name, :object_type, :partition_name, :subpartition_name,
                :size_bytes, :row_count, :block_count, :avg_row_length,
                :basic_ratio, :oltp_ratio, :adv_low_ratio, :adv_high_ratio,
                :blkcnt_uncmp_basic, :blkcnt_cmp_basic,
                :blkcnt_uncmp_oltp, :blkcnt_cmp_oltp,
                :blkcnt_uncmp_adv_low, :blkcnt_cmp_adv_low,
                :blkcnt_uncmp_adv_high, :blkcnt_cmp_adv_high,
                :insert_count, :update_count, :delete_count,
                :logical_reads, :physical_reads, :access_frequency, :last_access_date,
                :hotness_score, :read_ratio, :write_ratio, :dml_24h_rate,
                :last_analyzed, :data_age_days,
                :current_compression, :advisable_compression, :recommendation_reason,
                :confidence_score, :projected_savings_bytes, :projected_savings_pct,
                :analysis_duration_sec, :sample_size_rows,
                SYSDATE, SYSTIMESTAMP
            )
        """

        try:
            # Normalize column names to uppercase for consistency
            df = results_df.copy()
            df.columns = [c.upper() for c in df.columns]

            # Build list of parameter dicts for executemany
            rows = []
            for _, row in df.iterrows():
                params = {
                    'database_id': database_id,
                    'advisor_run_id': run_id,
                    'owner': row.get('OWNER'),
                    'object_name': row.get('OBJECT_NAME'),
                    'object_type': row.get('OBJECT_TYPE', 'TABLE'),
                    'partition_name': row.get('PARTITION_NAME'),
                    'subpartition_name': row.get('SUBPARTITION_NAME'),
                    'size_bytes': row.get('SIZE_BYTES'),
                    'row_count': row.get('ROW_COUNT'),
                    'block_count': row.get('BLOCK_COUNT'),
                    'avg_row_length': row.get('AVG_ROW_LENGTH'),
                    'basic_ratio': row.get('BASIC_RATIO'),
                    'oltp_ratio': row.get('OLTP_RATIO'),
                    'adv_low_ratio': row.get('ADV_LOW_RATIO'),
                    'adv_high_ratio': row.get('ADV_HIGH_RATIO'),
                    'blkcnt_uncmp_basic': row.get('BLKCNT_UNCMP_BASIC'),
                    'blkcnt_cmp_basic': row.get('BLKCNT_CMP_BASIC'),
                    'blkcnt_uncmp_oltp': row.get('BLKCNT_UNCMP_OLTP'),
                    'blkcnt_cmp_oltp': row.get('BLKCNT_CMP_OLTP'),
                    'blkcnt_uncmp_adv_low': row.get('BLKCNT_UNCMP_ADV_LOW'),
                    'blkcnt_cmp_adv_low': row.get('BLKCNT_CMP_ADV_LOW'),
                    'blkcnt_uncmp_adv_high': row.get('BLKCNT_UNCMP_ADV_HIGH'),
                    'blkcnt_cmp_adv_high': row.get('BLKCNT_CMP_ADV_HIGH'),
                    'insert_count': row.get('INSERT_COUNT', 0),
                    'update_count': row.get('UPDATE_COUNT', 0),
                    'delete_count': row.get('DELETE_COUNT', 0),
                    'logical_reads': row.get('LOGICAL_READS'),
                    'physical_reads': row.get('PHYSICAL_READS'),
                    'access_frequency': row.get('ACCESS_FREQUENCY'),
                    'last_access_date': row.get('LAST_ACCESS_DATE'),
                    'hotness_score': row.get('HOTNESS_SCORE'),
                    'read_ratio': row.get('READ_RATIO'),
                    'write_ratio': row.get('WRITE_RATIO'),
                    'dml_24h_rate': row.get('DML_24H_RATE'),
                    'last_analyzed': row.get('LAST_ANALYZED'),
                    'data_age_days': row.get('DATA_AGE_DAYS'),
                    'current_compression': row.get('CURRENT_COMPRESSION'),
                    'advisable_compression': row.get('ADVISABLE_COMPRESSION'),
                    'recommendation_reason': row.get('RECOMMENDATION_REASON'),
                    'confidence_score': row.get('CONFIDENCE_SCORE'),
                    'projected_savings_bytes': row.get('PROJECTED_SAVINGS_BYTES'),
                    'projected_savings_pct': row.get('PROJECTED_SAVINGS_PCT'),
                    'analysis_duration_sec': row.get('ANALYSIS_DURATION_SEC'),
                    'sample_size_rows': row.get('SAMPLE_SIZE_ROWS'),
                }
                # Convert NaN to None for Oracle
                for k, v in params.items():
                    if pd.isna(v) if not isinstance(v, (str, type(None))) else False:
                        params[k] = None
                rows.append(params)

            # Use executemany MERGE for upsert (insert or update existing)
            with CentralConnector.get_connection() as conn:
                cursor = conn.cursor()
                cursor.executemany(merge_query, rows)
                conn.commit()
                merged = cursor.rowcount
                cursor.close()

            log_info(f"Merged {merged} analysis results: database_id={database_id}, run_id={run_id}")
            return True

        except Exception as e:
            log_error(e, "store_analysis_results", {
                'database_id': database_id,
                'run_id': run_id,
                'result_count': len(results_df)
            })
            st.error(f"Failed to store analysis results: {e}")
            return False

    @staticmethod
    def store_compression_history(database_id: int, record: Dict[str, Any]) -> bool:
        """
        Store a compression history record in the central database

        Args:
            database_id: Target database ID
            record: Dictionary with history record fields:
                - owner, object_name, object_type, partition_name, subpartition_name,
                  compression_type_applied, compression_clause, execution_mode,
                  parallel_degree, original_size_bytes, original_blocks,
                  original_row_count, compressed_size_bytes, compressed_blocks,
                  compressed_row_count, compression_ratio_achieved, predicted_ratio,
                  start_time, end_time, duration_seconds, operation_status,
                  error_code, error_message, analysis_id, executed_by

        Returns:
            bool: True if successful
        """
        insert_query = """
            INSERT INTO t_compression_history (
                database_id, execution_id,
                owner, object_name, object_type, partition_name, subpartition_name,
                compression_type_applied, compression_clause, execution_mode,
                parallel_degree,
                original_size_bytes, original_blocks, original_row_count,
                compressed_size_bytes, compressed_blocks, compressed_row_count,
                compression_ratio_achieved, predicted_ratio,
                start_time, end_time, duration_seconds,
                operation_status, error_code, error_message,
                analysis_id, executed_by
            ) VALUES (
                :database_id, SEQ_EXECUTION_ID.NEXTVAL,
                :owner, :object_name, :object_type, :partition_name, :subpartition_name,
                :compression_type_applied, :compression_clause, :execution_mode,
                :parallel_degree,
                :original_size_bytes, :original_blocks, :original_row_count,
                :compressed_size_bytes, :compressed_blocks, :compressed_row_count,
                :compression_ratio_achieved, :predicted_ratio,
                :start_time, :end_time, :duration_seconds,
                :operation_status, :error_code, :error_message,
                :analysis_id, :executed_by
            )
        """

        params = dict(record)
        params['database_id'] = database_id

        # Set defaults for optional fields
        params.setdefault('partition_name', None)
        params.setdefault('subpartition_name', None)
        params.setdefault('compression_clause', None)
        params.setdefault('execution_mode', None)
        params.setdefault('parallel_degree', None)
        params.setdefault('original_size_bytes', None)
        params.setdefault('original_blocks', None)
        params.setdefault('original_row_count', None)
        params.setdefault('compressed_size_bytes', None)
        params.setdefault('compressed_blocks', None)
        params.setdefault('compressed_row_count', None)
        params.setdefault('compression_ratio_achieved', None)
        params.setdefault('predicted_ratio', None)
        params.setdefault('start_time', None)
        params.setdefault('end_time', None)
        params.setdefault('duration_seconds', None)
        params.setdefault('operation_status', 'IN_PROGRESS')
        params.setdefault('error_code', None)
        params.setdefault('error_message', None)
        params.setdefault('analysis_id', None)
        params.setdefault('executed_by', None)

        try:
            rows_affected = CentralConnector.execute_dml(insert_query, params)
            if rows_affected:
                log_info(f"Compression history stored: database_id={database_id}, "
                         f"object={params.get('owner')}.{params.get('object_name')}")
                return True
            return False
        except Exception as e:
            log_error(e, "store_compression_history", {
                'database_id': database_id,
                'object': f"{params.get('owner')}.{params.get('object_name')}"
            })
            st.error(f"Failed to store compression history: {e}")
            return False

    # ============================================================================
    # CROSS-DATABASE METHODS
    # ============================================================================

    @staticmethod
    def get_savings_by_database() -> pd.DataFrame:
        """
        Get savings breakdown grouped by target database

        Returns:
            DataFrame with per-database savings summary
        """
        query = """
            SELECT
                a.database_id,
                t.display_name as database_name,
                t.environment,
                t.platform_type,
                COUNT(*) as total_tables,
                COALESCE(SUM(a.size_mb), 0) / 1024 as total_size_gb,
                COALESCE(SUM(a.projected_savings_mb), 0) / 1024 as potential_savings_gb,
                COALESCE(AVG(a.projected_savings_pct), 0) as avg_savings_pct,
                COUNT(CASE WHEN a.advisable_compression IS NOT NULL
                          AND a.advisable_compression != 'NONE' THEN 1 END) as candidates_count
            FROM t_compression_analysis a
            JOIN t_target_databases t ON a.database_id = t.database_id
            WHERE t.is_active = 'Y'
            GROUP BY a.database_id, t.display_name, t.environment, t.platform_type
            ORDER BY potential_savings_gb DESC
        """

        try:
            return CentralConnector.execute_query(query)
        except Exception as e:
            log_error(e, "get_savings_by_database")
            st.error(f"Failed to get savings by database: {e}")
            return pd.DataFrame()

    @staticmethod
    def compare_databases() -> pd.DataFrame:
        """
        Get aggregated comparison stats across all databases

        Returns:
            DataFrame with per-database comparison: total_tables, total_size,
            potential_savings, avg_savings_pct
        """
        query = """
            SELECT
                t.database_id,
                t.display_name as database_name,
                t.environment,
                t.platform_type,
                t.oracle_version,
                t.last_connected,
                t.last_analysis_date,
                COALESCE(stats.total_tables, 0) as total_tables,
                COALESCE(stats.total_size_gb, 0) as total_size_gb,
                COALESCE(stats.potential_savings_gb, 0) as potential_savings_gb,
                COALESCE(stats.avg_savings_pct, 0) as avg_savings_pct,
                COALESCE(stats.candidates_count, 0) as candidates_count,
                COALESCE(hist.total_executions, 0) as total_executions,
                COALESCE(hist.successful_executions, 0) as successful_executions,
                COALESCE(hist.total_space_saved_gb, 0) as total_space_saved_gb
            FROM t_target_databases t
            LEFT JOIN (
                SELECT
                    database_id,
                    COUNT(*) as total_tables,
                    COALESCE(SUM(size_mb), 0) / 1024 as total_size_gb,
                    COALESCE(SUM(projected_savings_mb), 0) / 1024 as potential_savings_gb,
                    COALESCE(AVG(projected_savings_pct), 0) as avg_savings_pct,
                    COUNT(CASE WHEN advisable_compression IS NOT NULL
                              AND advisable_compression != 'NONE' THEN 1 END) as candidates_count
                FROM t_compression_analysis
                GROUP BY database_id
            ) stats ON t.database_id = stats.database_id
            LEFT JOIN (
                SELECT
                    database_id,
                    COUNT(*) as total_executions,
                    COUNT(CASE WHEN operation_status = 'SUCCESS' THEN 1 END) as successful_executions,
                    COALESCE(SUM(space_saved_mb), 0) / 1024 as total_space_saved_gb
                FROM t_compression_history
                GROUP BY database_id
            ) hist ON t.database_id = hist.database_id
            WHERE t.is_active = 'Y'
            ORDER BY t.display_name
        """

        try:
            return CentralConnector.execute_query(query)
        except Exception as e:
            log_error(e, "compare_databases")
            st.error(f"Failed to compare databases: {e}")
            return pd.DataFrame()


# Create singleton accessor function
@st.cache_resource
def get_central_queries() -> CentralQueries:
    """Get cached CentralQueries instance"""
    return CentralQueries()
