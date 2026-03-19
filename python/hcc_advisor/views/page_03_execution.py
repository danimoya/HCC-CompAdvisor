"""
Execution Page - HCC Compression Advisor
Execute compression recommendations
"""

import streamlit as st
import pandas as pd
import time
from hcc_advisor.utils.central_queries import CentralQueries
from hcc_advisor.utils.target_queries import TargetQueries
from hcc_advisor.config import config


def show_execution_page():
    """Display execution page"""

    st.title("Execute Compression")
    st.markdown("Execute compression for selected recommendations")
    st.markdown("---")

    # Execution mode selector
    tab1, tab2, tab3 = st.tabs(["Single Table", "Batch Execution", "Monitor Progress"])

    with tab1:
        show_single_execution()

    with tab2:
        show_batch_execution()

    with tab3:
        show_execution_monitor()


def show_single_execution():
    """Show single table execution interface"""

    st.subheader("Execute Single Table Compression")

    db_id = st.session_state.get('active_database_id')

    # Fetch recommendations using central database query
    df = CentralQueries.get_recommendations(limit=100, min_savings_pct=10.0, database_id=db_id)

    if df.empty:
        st.warning("No recommendations available. Run an analysis first.")
        return

    # Normalize column names to lowercase
    df.columns = [col.lower() for col in df.columns]

    # Table selector
    col1, col2 = st.columns([2, 1])

    with col1:
        selected_index = st.selectbox(
            "Select Table",
            options=range(len(df)),
            format_func=lambda x: f"{df.iloc[x]['table_owner']}.{df.iloc[x]['table_name']} - {df.iloc[x]['savings_pct']:.1f}% savings"
        )

    with col2:
        st.info(f"""
        **Selected Table:**
        {df.iloc[selected_index]['table_owner']}.{df.iloc[selected_index]['table_name']}
        """)

    # Execution parameters
    st.markdown("---")
    st.subheader("Execution Parameters")

    # Query CPU_COUNT from target for max parallel degree
    max_parallel = 16
    if db_id:
        cpu_count = TargetQueries.get_cpu_count(db_id)
        max_parallel = max(1, cpu_count // 2)

    col1, col2 = st.columns(2)

    with col1:
        parallel_degree = st.slider(
            "Parallel Degree",
            min_value=1,
            max_value=max_parallel,
            value=min(4, max_parallel),
            help=f"Number of parallel processes (max CPU_COUNT/2 = {max_parallel})"
        )

    with col2:
        confirm_execution = st.checkbox(
            "Confirm Execution",
            value=False,
            help="Confirm you want to execute this compression"
        )

    # Display details
    selected_row = df.iloc[selected_index]

    col1, col2 = st.columns(2)

    current_size = selected_row.get('current_size_mb', 0) or 0
    estimated_rows = selected_row.get('estimated_rows', 0) or 0
    current_compression = selected_row.get('current_compression', 'NONE')
    recommended_strategy = selected_row.get('recommended_strategy', 'N/A')
    estimated_size = selected_row.get('estimated_size_mb', 0) or 0
    savings_pct = selected_row.get('savings_pct', 0) or 0
    compression_ratio = selected_row.get('compression_ratio', 1) or 1

    with col1:
        st.markdown(f"""
        <div class="metric-card">
            <h4>Current State</h4>
            <strong>Size:</strong> {current_size:.2f} MB<br>
            <strong>Rows:</strong> {int(estimated_rows):,}<br>
            <strong>Compression:</strong> {current_compression}
        </div>
        """, unsafe_allow_html=True)

    with col2:
        st.markdown(f"""
        <div class="metric-card success-card">
            <h4>After Compression</h4>
            <strong>Strategy:</strong> {recommended_strategy}<br>
            <strong>Estimated Size:</strong> {estimated_size:.2f} MB<br>
            <strong>Savings:</strong> {savings_pct:.1f}% ({compression_ratio:.2f}x)
        </div>
        """, unsafe_allow_html=True)

    # DDL Preview section
    st.markdown("---")
    st.subheader("DDL Preview")

    owner = selected_row['table_owner']
    table_name = selected_row['table_name']
    partition_name = selected_row.get('partition_name')

    ddl = TargetQueries.generate_ddl(
        owner, table_name, recommended_strategy, partition_name,
        parallel_degree=parallel_degree
    )
    st.code(ddl, language="sql")

    # Execute button
    st.markdown("---")

    if not confirm_execution:
        st.warning("Check 'Confirm Execution' to enable the button")

    col1, col2, col3 = st.columns([1, 1, 1])

    with col2:
        execute_button = st.button(
            "Execute Compression",
            disabled=not confirm_execution,
            use_container_width=True
        )

    if execute_button:
        if not db_id:
            st.error("Select a target database from the sidebar first.")
        else:
            with st.spinner("Executing compression..."):
                result = TargetQueries.execute_compression(
                    db_id,
                    owner=owner,
                    table_name=table_name,
                    compression_type=recommended_strategy,
                    partition_name=partition_name,
                    dry_run=False,
                    parallel_degree=parallel_degree
                )

                if result.get('error'):
                    st.error(f"Execution failed: {result['error']}")
                elif result.get('success'):
                    st.success(result.get('message', 'Compression completed'))
                else:
                    st.warning("Execution completed with unknown result")


def show_batch_execution():
    """Show batch execution interface"""

    st.subheader("Batch Compression Execution")

    db_id = st.session_state.get('active_database_id')

    # Schema filter for batch
    schemas = TargetQueries.get_available_schemas(db_id) if db_id else []
    schema_filter = st.selectbox("Filter by Schema", ["All Schemas"] + schemas, key="batch_schema")

    # Fetch recommendations using central database query
    schema_val = None if schema_filter == "All Schemas" else schema_filter
    df = CentralQueries.get_recommendations(
        limit=200, min_savings_pct=5.0, database_id=db_id, schema=schema_val
    )

    if df.empty:
        st.warning("No recommendations available. Run an analysis first.")
        return

    # Normalize column names to lowercase
    df.columns = [col.lower() for col in df.columns]

    # Show schema summary with totals
    if schema_val:
        total_current = df['current_size_mb'].sum() if 'current_size_mb' in df.columns else 0
        total_est = df['estimated_size_mb'].sum() if 'estimated_size_mb' in df.columns else 0
        c1, c2, c3 = st.columns(3)
        with c1:
            st.metric("Tables", len(df))
        with c2:
            st.metric("Current Total", f"{total_current:.1f} MB")
        with c3:
            st.metric("Estimated After", f"{total_est:.1f} MB")

        st.dataframe(
            df[['table_owner', 'table_name', 'current_size_mb', 'recommended_strategy',
                'estimated_size_mb', 'savings_pct']].rename(columns={
                'table_owner': 'Owner', 'table_name': 'Table',
                'current_size_mb': 'Current (MB)', 'recommended_strategy': 'Advised',
                'estimated_size_mb': 'Est. Size (MB)', 'savings_pct': 'Savings %'
            }),
            use_container_width=True, hide_index=True
        )

    st.markdown("---")
    st.markdown("Select tables for batch execution:")

    selected_tables = st.multiselect(
        "Tables",
        options=df['recommendation_id'].tolist(),
        format_func=lambda x: f"{df[df['recommendation_id']==x].iloc[0]['table_owner']}.{df[df['recommendation_id']==x].iloc[0]['table_name']}"
    )

    if selected_tables:
        # Show summary
        selected_df = df[df['recommendation_id'].isin(selected_tables)]

        col1, col2, col3 = st.columns(3)

        with col1:
            st.metric("Selected Tables", len(selected_tables))

        with col2:
            total_size = selected_df['current_size_mb'].sum() if 'current_size_mb' in selected_df.columns else 0
            st.metric("Total Size", f"{total_size:.2f} MB")

        with col3:
            avg_savings = selected_df['savings_pct'].mean() if 'savings_pct' in selected_df.columns else 0
            st.metric("Avg Savings", f"{avg_savings:.1f}%")

        # Execution parameters
        st.markdown("---")

        max_parallel_batch = 16
        if db_id:
            cpu_count_batch = TargetQueries.get_cpu_count(db_id)
            max_parallel_batch = max(1, cpu_count_batch // 2)

        col1, col2, col3 = st.columns(3)

        with col1:
            batch_parallel = st.slider(
                "Parallel Degree",
                min_value=1,
                max_value=max_parallel_batch,
                value=min(4, max_parallel_batch),
                key="batch_parallel",
                help=f"Per-table parallelism (max CPU_COUNT/2 = {max_parallel_batch})"
            )

        with col2:
            batch_concurrency = st.slider(
                "Concurrent Tables",
                min_value=1,
                max_value=max_parallel_batch,
                value=1,
                key="batch_concurrency",
                help=f"How many tables to compress simultaneously (max CPU_COUNT/2 = {max_parallel_batch})"
            )

        with col3:
            batch_confirm = st.checkbox(
                "Confirm Batch Execution",
                value=False,
                key="batch_confirm"
            )

        # Execute batch
        col1, col2, col3 = st.columns([1, 1, 1])

        with col2:
            if st.button("Execute Batch", use_container_width=True, disabled=not batch_confirm):
                if not db_id:
                    st.error("Select a target database from the sidebar first.")
                else:
                    # Build proper items list from selected recommendation IDs
                    items = []
                    for rec_id in selected_tables:
                        match = df[df['recommendation_id'] == rec_id]
                        if not match.empty:
                            row = match.iloc[0]
                            pn = row.get('partition_name')
                            items.append({
                                'owner': row['table_owner'],
                                'table_name': row['table_name'],
                                'compression_type': row['recommended_strategy'],
                                'partition_name': pn if pd.notna(pn) else None
                            })

                    with st.spinner(f"Executing {len(items)} compressions..."):
                        result = TargetQueries.batch_execute(
                            db_id, items,
                            dry_run=False,
                            parallel_degree=batch_parallel,
                            concurrency=batch_concurrency
                        )

                        if result.get('errors', 0) > 0:
                            st.warning(f"Batch completed with {result.get('errors')} errors")
                        st.success(f"Batch execution: {result.get('success', 0)} success, {result.get('errors', 0)} errors")


def show_execution_monitor():
    """Show execution monitoring interface with auto-refresh"""

    st.subheader("Operation Monitor")

    db_id = st.session_state.get('active_database_id')

    # Auto-refresh toggle
    col1, col2, col3 = st.columns([1, 1, 2])
    with col1:
        auto_refresh = st.checkbox("Auto-refresh", value=False, key="auto_refresh")
    with col2:
        if st.button("Refresh Now", use_container_width=True):
            st.rerun()
    with col3:
        refresh_interval = st.slider("Refresh interval (seconds)", 5, 60, 10, key="refresh_interval")

    # Auto-refresh logic
    if auto_refresh:
        import time
        time.sleep(refresh_interval)
        st.rerun()

    st.markdown("---")

    # Running Operations Section
    st.markdown("### 🔄 Running Operations")

    running_ops = CentralQueries.get_running_operations(database_id=db_id)

    if not running_ops.empty:
        running_ops.columns = [c.lower() for c in running_ops.columns]

        for _, row in running_ops.iterrows():
            op_type = row.get('operation_type', 'UNKNOWN')
            op_id = row.get('operation_id', 'N/A')
            status = row.get('status', 'UNKNOWN')
            owner = row.get('owner', '')
            table_name = row.get('table_name', '')
            duration = row.get('duration_minutes', 0) or 0
            progress = row.get('progress_pct', 0) or 0

            icon = "📊" if op_type == 'ANALYSIS' else "📦"
            title = f"{icon} {op_type}: {owner}.{table_name}" if owner else f"{icon} {op_type}"

            with st.expander(f"{title} - {status}", expanded=True):
                col1, col2, col3 = st.columns(3)

                with col1:
                    st.metric("Operation ID", op_id)
                with col2:
                    st.metric("Duration", f"{duration:.1f} min")
                with col3:
                    st.metric("Status", status)

                if progress > 0:
                    st.progress(progress / 100, text=f"Progress: {progress:.1f}%")
                else:
                    st.progress(0, text="Progress: Calculating...")

                # Get more details
                if st.button(f"View Details", key=f"detail_{op_type}_{op_id}"):
                    details = CentralQueries.get_operation_progress(op_type, int(op_id))
                    if details:
                        st.json(details)
    else:
        st.info("No operations currently running")

    # Long Operations from V$SESSION_LONGOPS
    st.markdown("---")
    st.markdown("### ⏳ Long-Running Database Operations")

    long_ops = TargetQueries.get_long_operations(db_id) if db_id else pd.DataFrame()

    if not long_ops.empty:
        long_ops.columns = [c.lower() for c in long_ops.columns]

        for _, row in long_ops.iterrows():
            opname = row.get('opname', 'Unknown')
            target = row.get('target', '')
            pct_complete = row.get('pct_complete', 0) or 0
            elapsed = row.get('elapsed_seconds', 0) or 0
            remaining = row.get('seconds_remaining', 0) or 0
            message = row.get('message', '')

            with st.container():
                col1, col2, col3 = st.columns([2, 1, 1])
                with col1:
                    st.markdown(f"**{opname}** - {target}")
                with col2:
                    st.metric("Elapsed", f"{elapsed:.0f}s")
                with col3:
                    st.metric("Remaining", f"{remaining:.0f}s")

                st.progress(pct_complete / 100, text=f"{pct_complete:.1f}% complete")
                if message:
                    st.caption(message)
                st.markdown("---")
    else:
        st.info("No long-running operations detected (requires DBA privileges)")

    # Recent Operations Section
    st.markdown("### 📋 Recent Operations")

    recent_ops = CentralQueries.get_recent_operations(limit=15, database_id=db_id)

    if not recent_ops.empty:
        recent_ops.columns = [c.lower() for c in recent_ops.columns]

        # Color-coded status display
        def get_status_color(status):
            if status in ('SUCCESS', 'COMPLETED'):
                return '🟢'
            elif status in ('IN_PROGRESS', 'RUNNING'):
                return '🟡'
            elif status in ('FAILED', 'ERROR'):
                return '🔴'
            else:
                return '⚪'

        display_data = []
        for _, row in recent_ops.iterrows():
            status = row.get('status', 'UNKNOWN')
            display_data.append({
                'Status': f"{get_status_color(status)} {status}",
                'Type': row.get('operation_type', ''),
                'Owner': row.get('owner', ''),
                'Name': row.get('name', ''),
                'Strategy': row.get('strategy', ''),
                'Duration': f"{row.get('duration_minutes', 0):.1f} min",
                'Result': f"{row.get('result_pct', 0):.1f}%" if row.get('result_pct') else 'N/A',
                'Started': str(row.get('start_time', ''))[:19]
            })

        display_df = pd.DataFrame(display_data)
        st.dataframe(display_df, use_container_width=True, hide_index=True)

        # Error details
        errors = recent_ops[recent_ops['status'].isin(['FAILED', 'ERROR'])]
        if not errors.empty:
            with st.expander("⚠️ View Error Details"):
                for _, err in errors.iterrows():
                    if err.get('error_message'):
                        st.error(f"**{err.get('name', 'Unknown')}**: {err.get('error_message')}")
    else:
        st.info("No recent operations found")

    # History link
    st.markdown("---")
    col1, col2, col3 = st.columns([1, 1, 1])
    with col2:
        if st.button("View Full Execution History", use_container_width=True):
            st.session_state.selected_page = "Execution History"
            st.rerun()


if __name__ == "__main__":
    show_execution_page()
