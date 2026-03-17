"""
Analysis Page - HCC Compression Advisor
Trigger and monitor compression analysis
"""

import streamlit as st
import pandas as pd
import plotly.graph_objects as go
import threading
from datetime import datetime
from hcc_advisor.utils.central_queries import CentralQueries
from hcc_advisor.utils.target_queries import TargetQueries
from hcc_advisor.config import config


def show_analysis_page():
    """Display analysis page"""

    st.title("Compression Analysis")
    st.markdown("Analyze tables for compression opportunities")
    st.markdown("---")

    # Tabs for Analysis, Monitor, and Schema Size
    tab1, tab2, tab3 = st.tabs(["Run Analysis", "Monitor Progress", "Check Schema Size"])

    with tab1:
        show_analysis_config()

    with tab2:
        show_analysis_monitor()

    with tab3:
        show_schema_size()


def show_analysis_config():
    """Show analysis configuration and results"""

    # Analysis configuration
    db_id = st.session_state.get('active_database_id')
    if not db_id:
        st.warning("Select a target database from the sidebar to run analysis.")
        schemas = []
    else:
        schemas = TargetQueries.get_available_schemas(db_id)

    col1, col2 = st.columns([2, 1])

    with col1:
        st.subheader("Start New Analysis")

        with st.form("analysis_form"):
            # Schema selector
            schema_options = ["All Schemas"] + schemas
            selected_schema = st.selectbox(
                "Target Schema",
                options=schema_options,
                index=0,
                help="Select a specific schema or analyze all schemas"
            )

            # Strategy selector
            strategy_options = {
                1: "Aggressive (Maximum compression)",
                2: "Balanced (Default - recommended)",
                3: "Conservative (Minimal risk)"
            }
            selected_strategy = st.selectbox(
                "Analysis Strategy",
                options=list(strategy_options.keys()),
                format_func=lambda x: strategy_options[x],
                index=1,
                help="Select the analysis strategy"
            )

            parallel_degree = st.slider(
                "Parallel Degree",
                min_value=1,
                max_value=16,
                value=4,
                help="Number of parallel workers for analysis"
            )

            include_partitions = st.checkbox(
                "Include Partition Analysis",
                value=False,
                help="Analyze individual partitions and subpartitions (slower for highly partitioned tables)"
            )

            col_a, col_b = st.columns(2)

            with col_a:
                submit_button = st.form_submit_button(
                    "Start Analysis",
                    use_container_width=True
                )

            with col_b:
                refresh_button = st.form_submit_button(
                    "Refresh Status",
                    use_container_width=True
                )

            if submit_button:
                if not db_id:
                    st.error("Select a target database from the sidebar first.")
                else:
                    owner = None if selected_schema == "All Schemas" else selected_schema

                    # Launch analysis in background thread so UI stays responsive
                    def _run_analysis():
                        TargetQueries.start_analysis(
                            db_id,
                            owner=owner,
                            strategy_id=selected_strategy,
                            parallel_degree=parallel_degree,
                            include_partitions=include_partitions
                        )

                    thread = threading.Thread(target=_run_analysis, daemon=True)
                    thread.start()
                    st.success(
                        "Analysis started in background. "
                        "Switch to the **Monitor Progress** tab to track status."
                    )

    with col2:
        st.subheader("Analysis Parameters")
        st.info(f"""
        **Strategy Options:**
        - **Aggressive**: Maximum compression, higher risk
        - **Balanced**: Recommended default
        - **Conservative**: Minimal changes, lower risk
        """)

    st.markdown("---")

    # Latest analysis results
    st.subheader("Latest Analysis Results")

    analysis_data = CentralQueries.get_latest_analysis(database_id=db_id)

    if not analysis_data:
        st.warning("No analysis results available. Start a new analysis above.")
        return

    # Display analysis summary
    col1, col2, col3, col4 = st.columns(4)

    with col1:
        st.metric(
            label="Analysis ID",
            value=f"#{analysis_data.get('analysis_id', 'N/A')}"
        )

    with col2:
        st.metric(
            label="Tables Analyzed",
            value=f"{analysis_data.get('tables_analyzed', 0):,}"
        )

    with col3:
        st.metric(
            label="Candidates Found",
            value=f"{analysis_data.get('candidates_found', 0):,}"
        )

    with col4:
        status = analysis_data.get('status', 'UNKNOWN')
        status_indicator = "complete" if status == "COMPLETED" else "hourglass"
        st.metric(
            label="Status",
            value=f"{status}"
        )

    # Analysis details
    st.markdown("---")

    col1, col2 = st.columns(2)

    with col1:
        st.subheader("Analysis Details")

        st.markdown(f"""
        <div class="metric-card">
            <strong>Started:</strong> {analysis_data.get('started_at', 'N/A')}<br>
            <strong>Completed:</strong> {analysis_data.get('completed_at', 'N/A')}<br>
            <strong>Duration:</strong> {analysis_data.get('duration_seconds', 0)} seconds<br>
            <strong>Min Size:</strong> {analysis_data.get('min_size_mb', 0)} MB
        </div>
        """, unsafe_allow_html=True)

    with col2:
        st.subheader("Potential Savings")

        total_size = analysis_data.get('total_current_size_gb', 0) or 0
        potential_size = analysis_data.get('total_compressed_size_gb', 0) or 0
        savings = total_size - potential_size

        st.markdown(f"""
        <div class="metric-card success-card">
            <strong>Current Size:</strong> {total_size:.2f} GB<br>
            <strong>Compressed Size:</strong> {potential_size:.2f} GB<br>
            <strong>Potential Savings:</strong> {savings:.2f} GB ({analysis_data.get('avg_savings_pct', 0):.1f}%)
        </div>
        """, unsafe_allow_html=True)

    # Visualization
    if total_size > 0 and potential_size > 0:
        st.markdown("---")
        st.subheader("Size Comparison")

        fig = go.Figure()

        fig.add_trace(go.Bar(
            x=['Current Size', 'After Compression'],
            y=[total_size, potential_size],
            marker_color=[config.CHART_COLORS['danger'], config.CHART_COLORS['success']],
            text=[f"{total_size:.2f} GB", f"{potential_size:.2f} GB"],
            textposition='auto',
        ))

        fig.update_layout(
            yaxis_title="Size (GB)",
            height=400,
            showlegend=False
        )

        st.plotly_chart(fig, use_container_width=True)

    # Top candidates preview
    st.markdown("---")
    st.subheader("Top Compression Candidates")

    recommendations_df = CentralQueries.get_recommendations(limit=10, min_savings_pct=10.0, database_id=db_id)

    if not recommendations_df.empty:
        # Normalize column names to lowercase
        recommendations_df.columns = [col.lower() for col in recommendations_df.columns]

        # Select and format columns
        column_mapping = {
            'table_owner': 'Owner',
            'table_name': 'Table',
            'current_size_mb': 'Current (MB)',
            'recommended_strategy': 'Strategy',
            'estimated_size_mb': 'Compressed (MB)',
            'savings_pct': 'Savings %'
        }

        available_cols = [c for c in column_mapping.keys() if c in recommendations_df.columns]
        display_df = recommendations_df[available_cols].copy()
        display_df.columns = [column_mapping[c] for c in available_cols]

        # Format numbers
        if 'Current (MB)' in display_df.columns:
            display_df['Current (MB)'] = display_df['Current (MB)'].round(2)
        if 'Compressed (MB)' in display_df.columns:
            display_df['Compressed (MB)'] = display_df['Compressed (MB)'].round(2)
        if 'Savings %' in display_df.columns:
            display_df['Savings %'] = display_df['Savings %'].round(1)

        st.dataframe(
            display_df,
            use_container_width=True,
            hide_index=True
        )

        # Quick action
        if st.button("View All Recommendations", use_container_width=True):
            st.session_state.selected_page = "Recommendations"
            st.rerun()
    else:
        st.info("No recommendations available. Run an analysis first.")


def show_schema_size():
    """Show schema size breakdown from target database"""

    st.subheader("Schema Size Overview")
    st.markdown("Query `DBA_SEGMENTS` on the target database to see storage usage per schema.")

    db_id = st.session_state.get('active_database_id')
    if not db_id:
        st.warning("Select a target database from the sidebar first.")
        return

    if st.button("Check Schema Size", use_container_width=True, type="primary", key="check_schema_size_btn"):
        from hcc_advisor.utils.target_connector import TargetConnector

        query = """
            SELECT
                owner,
                SUM(bytes)                          AS total_bytes,
                ROUND(SUM(bytes) / 1024, 2)         AS total_kb,
                ROUND(SUM(bytes) / 1048576, 2)      AS total_mb,
                ROUND(SUM(bytes) / 1073741824, 4)   AS total_gb,
                COUNT(*)                            AS segment_count
            FROM
                dba_segments
            WHERE
                owner NOT IN (
                    'SYS', 'SYSTEM', 'OUTLN', 'DBSNMP', 'APPQOSSYS',
                    'DBSFWUSER', 'GGSYS', 'ANONYMOUS', 'CTXSYS', 'DVSYS',
                    'DVF', 'GSMADMIN_INTERNAL', 'MDSYS', 'OLAPSYS', 'ORDSYS',
                    'ORDPLUGINS', 'ORDDATA', 'SI_INFORMTN_SCHEMA', 'XDB',
                    'WMSYS', 'LBACSYS', 'OJVMSYS', 'AUDSYS', 'APEX_030200',
                    'APEX_040000', 'FLOWS_FILES', 'APEX_PUBLIC_USER',
                    'XS$NULL', 'SPATIAL_CSW_ADMIN_USR', 'SPATIAL_WFS_ADMIN_USR',
                    'MDDATA', 'SYSBACKUP', 'SYSDG', 'SYSKM', 'SYSRAC',
                    'REMOTE_SCHEDULER_AGENT', 'GSMUSER', 'GSMROOTUSER',
                    'DIP', 'ORACLE_OCM', 'SYSMAN', 'MGMT_VIEW',
                    'EXFSYS', 'TSMSYS', 'DMSYS'
                )
                AND owner NOT LIKE 'APEX_%'
                AND owner NOT LIKE 'FLOWS_%'
            GROUP BY
                owner
            ORDER BY
                total_bytes DESC
        """

        with st.spinner("Querying DBA_SEGMENTS..."):
            df = TargetConnector.execute_query(db_id, query)

        if df.empty:
            st.info("No schema data returned.")
            return

        df.columns = [c.lower() for c in df.columns]

        # Summary metrics
        total_gb = df['total_gb'].sum()
        total_mb = df['total_mb'].sum()
        total_segments = df['segment_count'].sum()

        col1, col2, col3 = st.columns(3)
        with col1:
            st.metric("Total Size", f"{total_gb:.2f} GB" if total_gb >= 1 else f"{total_mb:.1f} MB")
        with col2:
            st.metric("Schemas", len(df))
        with col3:
            st.metric("Segments", f"{int(total_segments):,}")

        st.markdown("---")

        # Chart
        fig = go.Figure(data=[
            go.Bar(
                x=df['owner'],
                y=df['total_mb'],
                marker_color=config.CHART_COLORS['primary'],
                text=df['total_mb'].apply(lambda x: f"{x:.1f} MB"),
                textposition='auto'
            )
        ])
        fig.update_layout(
            xaxis_title="Schema",
            yaxis_title="Size (MB)",
            height=400
        )
        st.plotly_chart(fig, use_container_width=True)

        # Data table
        display_df = df[['owner', 'total_mb', 'total_gb', 'segment_count']].copy()
        display_df.columns = ['Schema', 'Size (MB)', 'Size (GB)', 'Segments']

        st.dataframe(display_df, use_container_width=True, hide_index=True)


def show_analysis_monitor():
    """Show analysis monitoring interface"""

    st.subheader("Analysis Progress Monitor")

    db_id = st.session_state.get('active_database_id')

    # Auto-refresh controls
    col1, col2, col3 = st.columns([1, 1, 2])
    with col1:
        auto_refresh = st.checkbox("Auto-refresh", value=False, key="analysis_auto_refresh")
    with col2:
        if st.button("Refresh Now", use_container_width=True, key="analysis_refresh"):
            st.rerun()
    with col3:
        refresh_interval = st.slider("Refresh interval (seconds)", 5, 60, 10, key="analysis_refresh_interval")

    # Auto-refresh logic
    if auto_refresh:
        import time
        time.sleep(refresh_interval)
        st.rerun()

    st.markdown("---")

    # Check for running analysis
    running_ops = CentralQueries.get_running_operations(database_id=db_id)

    if not running_ops.empty:
        running_ops.columns = [c.lower() for c in running_ops.columns]
        analysis_ops = running_ops[running_ops['operation_type'] == 'ANALYSIS']

        if not analysis_ops.empty:
            st.markdown("### 🔄 Running Analysis")

            for _, row in analysis_ops.iterrows():
                run_id = row.get('operation_id', 'N/A')
                owner = row.get('owner', 'All Schemas')
                status = row.get('status', 'UNKNOWN')
                duration = row.get('duration_minutes', 0) or 0
                progress = row.get('progress_pct', 0) or 0

                with st.container():
                    col1, col2, col3, col4 = st.columns(4)
                    with col1:
                        st.metric("Run ID", f"#{run_id}")
                    with col2:
                        st.metric("Schema", owner or "All")
                    with col3:
                        st.metric("Duration", f"{duration:.1f} min")
                    with col4:
                        st.metric("Status", status)

                    if progress > 0:
                        st.progress(progress / 100, text=f"Progress: {progress:.1f}%")
                    else:
                        st.progress(0, text="Analyzing tables...")

                    # Get detailed progress
                    details = CentralQueries.get_operation_progress('ANALYSIS', int(run_id))
                    if details:
                        col1, col2, col3 = st.columns(3)
                        with col1:
                            st.metric("Objects Analyzed", details.get('OBJECTS_ANALYZED') or 0)
                        with col2:
                            st.metric("Objects Skipped", details.get('OBJECTS_SKIPPED') or 0)
                        with col3:
                            candidates = (
                                (details.get('RECOMMEND_BASIC') or 0) +
                                (details.get('RECOMMEND_OLTP') or 0) +
                                (details.get('RECOMMEND_ADV_LOW') or 0) +
                                (details.get('RECOMMEND_ADV_HIGH') or 0)
                            )
                            st.metric("Candidates Found", candidates)

                    st.markdown("---")
        else:
            st.info("No analysis currently running")
    else:
        st.info("No analysis currently running")

    # Recent Analysis Runs
    st.markdown("### 📋 Recent Analysis Runs")

    analysis_runs = CentralQueries.get_analysis_runs(limit=10, database_id=db_id)

    if not analysis_runs.empty:
        analysis_runs.columns = [c.lower() for c in analysis_runs.columns]

        def get_status_icon(status):
            if status in ('COMPLETED', 'SUCCESS'):
                return '🟢'
            elif status == 'RUNNING':
                return '🟡'
            elif status in ('FAILED', 'ERROR'):
                return '🔴'
            return '⚪'

        display_data = []
        for _, row in analysis_runs.iterrows():
            status = row.get('status', 'UNKNOWN')
            display_data.append({
                'Status': f"{get_status_icon(status)} {status}",
                'Run ID': row.get('run_id', 'N/A'),
                'Schema': row.get('owner_filter', 'All') or 'All',
                'Tables Analyzed': row.get('tables_analyzed', 0),
                'Candidates': row.get('candidates_found', 0),
                'Duration': f"{(row.get('duration_seconds', 0) or 0) / 60:.1f} min",
                'Run Date': str(row.get('run_date', ''))[:19]
            })

        st.dataframe(pd.DataFrame(display_data), use_container_width=True, hide_index=True)

        # Error details for failed runs
        failed_runs = analysis_runs[analysis_runs['status'].isin(['FAILED', 'ERROR'])]
        if not failed_runs.empty:
            with st.expander("⚠️ View Error Details"):
                for _, err in failed_runs.iterrows():
                    err_msg = err.get('error_message')
                    if err_msg:
                        st.error(f"**Run #{err.get('run_id', 'N/A')}**: {err_msg}")
    else:
        st.info("No analysis runs found. Start a new analysis from the 'Run Analysis' tab.")

    # Link to view recommendations
    st.markdown("---")
    col1, col2, col3 = st.columns([1, 1, 1])
    with col2:
        if st.button("View All Recommendations", use_container_width=True, key="view_recs_from_monitor"):
            st.session_state.selected_page = "View Recommendations"
            st.rerun()


if __name__ == "__main__":
    show_analysis_page()
