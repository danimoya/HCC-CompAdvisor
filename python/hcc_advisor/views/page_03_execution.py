"""
Execution Page - HCC Compression Advisor
Execute compression recommendations
"""

import html
import streamlit as st
import pandas as pd
import time
from hcc_advisor.utils.central_queries import CentralQueries
from hcc_advisor.utils.target_queries import TargetQueries
from hcc_advisor.utils.target_connector import max_batch_concurrency
from hcc_advisor.utils.leaf_segments import leaf_segments
from hcc_advisor.utils.ui_refresh import schedule_rerun
from hcc_advisor.utils.sql_builder import (
    build_compression_script,
    gather_dependent_indexes,
)
from hcc_advisor.config import config
from hcc_advisor.auth import AuthManager, ROLE_OPERATOR
from hcc_advisor.views.page_08_quick_scan import _bulk_submit

BACKGROUND_LABEL = "Run as background jobs (DBMS_SCHEDULER) — recommended"
BACKGROUND_HELP = (
    "Queue each table as a DBMS_SCHEDULER job on the target and return at once: the "
    "ALTER TABLE ... MOVE runs inside the database, not in this browser session, "
    "throttled by the target's DOP budget (CPU_COUNT/2). Follow it on the Scheduler page. "
    "Untick to run the MOVE synchronously here; the page then stays busy until it "
    "finishes (fine for a single small table)."
)


def _db_label_for(db_id):
    """Resolve a friendly display label for a target database."""
    if not db_id:
        return "unknown"
    try:
        dbs = CentralQueries.get_target_databases()
        if not dbs.empty:
            dbs.columns = [c.lower() for c in dbs.columns]
            row = dbs[dbs['database_id'] == db_id]
            if not row.empty:
                return (row.iloc[0].get('display_name')
                        or row.iloc[0].get('database_name')
                        or f"db_{db_id}")
    except Exception:
        pass
    return f"db_{db_id}"


def _render_dry_run(operations_df: pd.DataFrame, db_label: str,
                    include_indexes: bool, download_key: str,
                    status_label: str = "Dry Run"):
    """Render the preview DDL script from a sql_builder-shaped DataFrame."""
    with st.spinner("Generating DDL preview..."):
        index_map = gather_dependent_indexes(operations_df) if include_indexes else {}
        sql_script = build_compression_script(
            operations_df, status_label, db_label, index_map
        )
    st.code(sql_script, language="sql")
    st.download_button(
        label=f"Download Preview ({len(operations_df)} operation(s))",
        data=sql_script,
        file_name=f"hcc_dryrun_{db_label.replace(' ', '_').lower()}.sql",
        mime="text/plain",
        key=download_key,
    )


def submit_background_compression(items, db_id, parallel_degree):
    """Queue items as DBMS_SCHEDULER jobs and show the outcome.

    Every item becomes a QUEUED history row (segments already queued or
    running are skipped as duplicates); the target's queue is then drained in
    FIFO order within its DOP budget, and whatever does not fit stays QUEUED
    for the Scheduler page. Returns once the jobs are queued / created: the
    MOVEs run inside the target database, not in this script thread.

    Args:
        items: dicts with owner, table_name, compression_type and optional
            partition_name / subpartition_name
        db_id: target database id
        parallel_degree: DOP of each job
    """
    items = [{**item, 'database_id': db_id, 'dop': parallel_degree} for item in items]
    with st.spinner(f"Queueing {len(items)} compression job(s)..."):
        result = _bulk_submit(items, db_id, None, parallel_degree)

    summary = (f"Queued: {result.get('added', 0)} · "
               f"Submitted to DBMS_SCHEDULER: {result['submitted']} · "
               f"Waiting in queue: {result['queued']} · "
               f"Already queued/running: {result['duplicates']} · "
               f"Failed: {result['failed']}")
    if result['failed']:
        st.warning(summary)
    else:
        st.success(summary)
    errors = result.get('errors') or []
    if errors:
        with st.expander(f"Details ({len(errors)})", expanded=bool(result['failed'])):
            for err in errors:
                st.text(err)
    st.info(
        "The jobs run on the target database, independent of this page. Track them on "
        "the **Scheduler** page (sidebar); items still waiting are submitted there as "
        "DOP budget frees up. Submitted/waiting counts cover this target's whole queue."
    )
    return result


def show_execution_page():
    """Display execution page"""

    st.title("Execute Compression")
    st.markdown("Execute compression for selected recommendations")
    st.markdown("---")

    # Execution mode selector
    tab1, tab2, tab3 = st.tabs(["Single Table", "Batch Execution", "Monitor Progress"])

    # Running compression DDL on a target requires the operator role (or admin);
    # viewers may still watch progress on the Monitor tab.
    can_execute = AuthManager.has_role(ROLE_OPERATOR)

    with tab1:
        if can_execute:
            show_single_execution()
        else:
            st.error("Executing compression requires the operator role.")

    with tab2:
        if can_execute:
            show_batch_execution()
        else:
            st.error("Executing compression requires the operator role.")

    with tab3:
        show_execution_monitor()

    # Auto-refresh (Monitor Progress tab): every tab is rendered by now, so
    # wait the chosen interval and rerun in the same session.
    schedule_rerun("auto_refresh", st.session_state.get("refresh_interval", 10))


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
        dry_run = st.checkbox(
            "Dry run (preview DDL only)",
            value=True,
            key="single_dry_run",
            help="When enabled, shows the ALTER TABLE MOVE + dependent index "
                 "REBUILD script without executing anything on the target."
        )
        confirm_execution = st.checkbox(
            "Confirm Execution",
            value=False,
            disabled=dry_run,
            help="Required to run the real DDL. Ignored in dry-run mode."
        )
        single_background = st.checkbox(
            BACKGROUND_LABEL,
            value=True,
            key="single_background",
            disabled=dry_run,
            help=BACKGROUND_HELP
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
            <strong>Compression:</strong> {html.escape(str(current_compression))}
        </div>
        """, unsafe_allow_html=True)

    with col2:
        st.markdown(f"""
        <div class="metric-card success-card">
            <h4>After Compression</h4>
            <strong>Strategy:</strong> {html.escape(str(recommended_strategy))}<br>
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

    if not dry_run and not confirm_execution:
        st.warning("Check 'Confirm Execution' to enable the button (or leave Dry run enabled).")

    col1, col2, col3 = st.columns([1, 1, 1])

    with col2:
        button_label = ("Preview DDL" if dry_run
                        else "Submit Background Job" if single_background
                        else "Execute Compression")
        execute_button = st.button(
            button_label,
            disabled=(not dry_run) and (not confirm_execution),
            use_container_width=True,
            type="primary" if not dry_run else "secondary",
        )

    if execute_button:
        if not db_id:
            st.error("Select a target database from the sidebar first.")
        elif dry_run:
            db_label = _db_label_for(db_id)
            op_df = pd.DataFrame([{
                'database_id': db_id,
                'database_display': db_label,
                'database_name': db_label,
                'owner': str(owner).upper(),
                'object_name': str(table_name).upper(),
                'partition_name': partition_name if partition_name and pd.notna(partition_name) else None,
                'compression_type_applied': recommended_strategy,
                'parallel_degree': int(parallel_degree),
                'operation_status': 'DRY_RUN',
                'error_message': '',
            }])
            _render_dry_run(op_df, db_label, include_indexes=True,
                            download_key="single_dry_run_download",
                            status_label="Dry Run (single table)")
        elif not confirm_execution:
            st.error("Check 'Confirm Execution' to run the compression.")
        elif single_background:
            submit_background_compression([{
                'owner': owner,
                'table_name': table_name,
                'compression_type': recommended_strategy,
                'partition_name': partition_name if partition_name and pd.notna(partition_name) else None,
            }], db_id, parallel_degree)
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

    # Show schema summary with totals (each segment once — see leaf_segments)
    if schema_val:
        leaves = leaf_segments(df)
        total_current = leaves['current_size_mb'].sum() if 'current_size_mb' in df.columns else 0
        total_est = leaves['estimated_size_mb'].sum() if 'estimated_size_mb' in df.columns else 0
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
        # A synchronous batch holds one pooled target connection per concurrent
        # table: cap it so TARGET_POOL_UI_HEADROOM connections stay free for the
        # page queries of this and other sessions (see max_batch_concurrency).
        max_concurrency = max(1, min(max_parallel_batch, max_batch_concurrency()))

        batch_background = st.checkbox(
            BACKGROUND_LABEL,
            value=True,
            key="batch_background",
            help=BACKGROUND_HELP
        )

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
                max_value=max_concurrency,
                value=1,
                key="batch_concurrency",
                disabled=batch_background,
                help=(f"How many tables to compress simultaneously in this page "
                      f"(max {max_concurrency}: CPU_COUNT/2, and the target pool's "
                      f"{config.TARGET_POOL_MAX} connections minus "
                      f"{config.TARGET_POOL_UI_HEADROOM} kept for page queries). "
                      f"Background jobs are throttled by the Scheduler's DOP budget instead.")
            )

        with col3:
            batch_dry_run = st.checkbox(
                "Dry run (preview DDL only)",
                value=True,
                key="batch_dry_run",
                help="When enabled, previews DDL for every selected table without executing."
            )
            batch_confirm = st.checkbox(
                "Confirm Batch Execution",
                value=False,
                key="batch_confirm",
                disabled=batch_dry_run,
                help="Required to run the real DDL. Ignored in dry-run mode."
            )

        # Execute batch
        col1, col2, col3 = st.columns([1, 1, 1])

        with col2:
            batch_button_label = ("Preview DDL" if batch_dry_run
                                  else "Queue Background Jobs" if batch_background
                                  else "Execute Batch")
            batch_go = st.button(
                batch_button_label,
                use_container_width=True,
                disabled=(not batch_dry_run) and (not batch_confirm),
                type="primary" if not batch_dry_run else "secondary",
            )

        if batch_go:
            if not db_id:
                st.error("Select a target database from the sidebar first.")
            elif batch_dry_run:
                db_label = _db_label_for(db_id)
                rows = []
                for rec_id in selected_tables:
                    match = df[df['recommendation_id'] == rec_id]
                    if not match.empty:
                        r = match.iloc[0]
                        pn = r.get('partition_name')
                        rows.append({
                            'database_id': db_id,
                            'database_display': db_label,
                            'database_name': db_label,
                            'owner': str(r['table_owner']).upper(),
                            'object_name': str(r['table_name']).upper(),
                            'partition_name': pn if pd.notna(pn) else None,
                            'compression_type_applied': r['recommended_strategy'],
                            'parallel_degree': int(batch_parallel),
                            'operation_status': 'DRY_RUN',
                            'error_message': '',
                        })
                op_df = pd.DataFrame(rows)
                _render_dry_run(op_df, db_label, include_indexes=True,
                                download_key="batch_dry_run_download",
                                status_label="Dry Run (batch)")
            elif not batch_confirm:
                st.error("Check 'Confirm Batch Execution' to run the compressions.")
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

                if batch_background:
                    submit_background_compression(items, db_id, batch_parallel)
                else:
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
        st.checkbox("Auto-refresh", value=False, key="auto_refresh")
    with col2:
        if st.button("Refresh Now", use_container_width=True):
            st.rerun()
    with col3:
        st.slider("Refresh interval (seconds)", 5, 60, 10, key="refresh_interval")

    # Auto-refresh ("auto_refresh"): the wait and rerun happen at the end of
    # show_execution_page(), once this monitor has been rendered.

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
