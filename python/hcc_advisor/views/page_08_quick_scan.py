"""
Quick Action Page - HCC Compression Advisor
Lightweight hotness-based analysis with DBMS_SCHEDULER job queue
"""

import streamlit as st
import pandas as pd
from hcc_advisor.utils.central_queries import CentralQueries
from hcc_advisor.utils.target_queries import TargetQueries
from hcc_advisor.config import config

COMP_OPTIONS = ['OLTP', 'QUERY LOW', 'QUERY HIGH', 'ARCHIVE LOW', 'ARCHIVE HIGH']
DOP_OPTIONS = list(range(1, 65))  # will be capped at runtime by CPU_COUNT/2


def show_quick_scan_page():
    st.title("Quick Action")
    st.markdown("Fast hotness-based analysis and DBMS_SCHEDULER compression jobs")
    st.markdown("---")

    db_id = st.session_state.get('active_database_id')
    if not db_id:
        st.warning("Select a target database from the sidebar.")
        return

    # Controls row
    schemas = TargetQueries.get_available_schemas(db_id)
    cpu_count = TargetQueries.get_cpu_count(db_id)
    max_dop = max(1, cpu_count // 2)

    col1, col2, col3, col4 = st.columns([2, 1, 1, 1])
    with col1:
        schema = st.selectbox("Schema", ["All Schemas"] + schemas, key="qs_schema")
    with col2:
        max_queue = st.slider("Max Concurrent Jobs", 1, max(1, cpu_count // 2),
                              min(2, max(1, cpu_count // 2)), key="qs_max_queue",
                              help=f"Max jobs running simultaneously (CPU_COUNT/2 = {cpu_count // 2})")
    with col3:
        show_running = st.checkbox("Running Only", key="qs_running_only")
    with col4:
        st.markdown("<br>", unsafe_allow_html=True)
        refresh = st.button("Refresh", key="qs_refresh", use_container_width=True)

    schema_param = None if schema == "All Schemas" else schema

    # Scan button
    col_scan, col_info = st.columns([1, 3])
    with col_scan:
        if st.button("Scan Now", type="primary", use_container_width=True, key="qs_scan"):
            with st.spinner("Scanning (hotness-only, no DBMS_COMPRESSION)..."):
                results = TargetQueries.quick_scan(db_id, owner=schema_param)
                st.session_state['qs_last_count'] = len(results)
                st.rerun()
    with col_info:
        last = st.session_state.get('qs_last_count')
        if last is not None:
            st.success(f"Last scan: {last} objects analyzed")

    # Check completed jobs on refresh
    if refresh:
        with st.spinner("Checking job status..."):
            updated = TargetQueries.check_completed_jobs(db_id)
            if updated:
                st.toast(f"{len(updated)} jobs updated")

    # Get running jobs for status overlay
    running_jobs = TargetQueries.get_running_compression_jobs(db_id)
    # Also get IN_PROGRESS objects from central history for status overlay
    running_set = set()
    try:
        from hcc_advisor.utils.central_connector import CentralConnector
        in_prog = CentralConnector.execute_query("""
            SELECT owner, object_name FROM t_compression_history
            WHERE operation_status = 'IN_PROGRESS'
              AND database_id = :db
        """, {'db': db_id})
        if not in_prog.empty:
            for _, rj in in_prog.iterrows():
                running_set.add(f"{rj['OWNER']}.{rj['OBJECT_NAME']}")
    except Exception:
        pass

    st.markdown("---")

    # Load recommendations with execution status
    df = CentralQueries.get_recommendations(
        schema=schema_param, limit=500, min_savings_pct=0, min_size_mb=0,
        database_id=db_id, show_executed=True
    )

    if df.empty:
        st.info("No scan data. Click 'Scan Now' to analyze tables.")
        return

    df.columns = [c.lower() for c in df.columns]

    # Add status from running jobs
    df['status'] = df.apply(
        lambda r: 'Running' if f"{r.get('table_owner','')}.{r.get('table_name','')}" in running_set
        else r.get('execution_status', 'Pending'), axis=1
    )

    # Filter running only
    if show_running:
        df = df[df['status'] == 'Running']
        if df.empty:
            st.info("No running compression jobs.")
            return

    # Split into tabs by object_type + Schemas bulk tab
    tab1, tab2, tab3, tab4 = st.tabs(["Tables", "Partitions", "Subpartitions", "Schemas"])

    with tab1:
        _render_scan_tab(df[df['object_type'] == 'TABLE'], 'TABLE', db_id, max_queue, max_dop, running_set)
    with tab2:
        _render_scan_tab(df[df['object_type'] == 'PARTITION'], 'PARTITION', db_id, max_queue, max_dop, running_set)
    with tab3:
        _render_scan_tab(df[df['object_type'] == 'SUBPARTITION'], 'SUBPARTITION', db_id, max_queue, max_dop, running_set)
    with tab4:
        _render_schemas_tab(db_id, max_queue, max_dop)


def _render_scan_tab(df, obj_type, db_id, max_queue, max_dop, running_set):
    """Render a single scan tab with selectable/editable table."""
    if df.empty:
        st.info(f"No {obj_type.lower()} data. Run a scan first.")
        return

    ROWS_PER_PAGE = 100

    # Prepare display DataFrame
    display_cols = ['table_owner', 'table_name']
    if obj_type == 'PARTITION':
        display_cols.append('partition_name')
    elif obj_type == 'SUBPARTITION':
        display_cols.extend(['partition_name', 'subpartition_name'])
    display_cols.extend(['current_size_mb', 'current_compression', 'recommended_strategy',
                         'dop', 'hotness_score', 'status'])

    available_base = [c for c in display_cols if c in df.columns or c == 'dop']
    show_df = df[[c for c in available_base if c in df.columns]].copy()
    show_df.insert(0, 'select', False)
    show_df['dop'] = max_dop

    # Summary (full dataset)
    total_size = show_df['current_size_mb'].sum() if 'current_size_mb' in show_df.columns else 0
    st.caption(f"{len(show_df)} objects, {total_size:.1f} MB total")

    # Pagination
    total_pages = max(1, (len(show_df) + ROWS_PER_PAGE - 1) // ROWS_PER_PAGE)
    page_key = f"qs_page_{obj_type}"
    if total_pages > 1:
        page = st.selectbox(
            f"Page (of {total_pages})", range(1, total_pages + 1), key=page_key,
            format_func=lambda p: f"Page {p}  ({(p-1)*ROWS_PER_PAGE+1}-{min(p*ROWS_PER_PAGE, len(show_df))} of {len(show_df)})"
        )
    else:
        page = 1
    start = (page - 1) * ROWS_PER_PAGE
    page_df = show_df.iloc[start:start + ROWS_PER_PAGE].reset_index(drop=True)

    col_config = {
        'select': st.column_config.CheckboxColumn("Submit", default=False),
        'table_owner': st.column_config.TextColumn("Owner"),
        'table_name': st.column_config.TextColumn("Table"),
        'current_size_mb': st.column_config.NumberColumn("Size (MB)", format="%.1f"),
        'current_compression': st.column_config.TextColumn("Current"),
        'recommended_strategy': st.column_config.SelectboxColumn(
            "Advised", options=COMP_OPTIONS, required=True
        ),
        'dop': st.column_config.NumberColumn(
            "DOP", min_value=1, max_value=max_dop, step=1,
            help=f"Parallel degree per object (1-{max_dop})"
        ),
        'hotness_score': st.column_config.NumberColumn("Hotness", format="%.0f"),
        'status': st.column_config.TextColumn("Status"),
    }
    if 'partition_name' in page_df.columns:
        col_config['partition_name'] = st.column_config.TextColumn("Partition")
    if 'subpartition_name' in page_df.columns:
        col_config['subpartition_name'] = st.column_config.TextColumn("Subpartition")

    edited = st.data_editor(
        page_df, column_config=col_config, use_container_width=True,
        hide_index=True, disabled=['table_owner', 'table_name', 'current_size_mb',
                                    'current_compression', 'hotness_score', 'status',
                                    'partition_name', 'subpartition_name'],
        key=f"qs_editor_{obj_type}_{page}",
        height=min(35 * len(page_df) + 50, 800),
    )

    # Submit selected
    selected = edited[edited['select'] == True]
    if len(selected) > 0:
        n = len(selected)
        running_count = len(running_set)
        slots = max_queue - running_count

        if slots <= 0:
            st.warning(f"Queue full ({running_count}/{max_queue} jobs running). Wait or increase Max Queue.")
        else:
            can_submit = min(n, slots)
            if can_submit < n:
                st.warning(f"Only {can_submit} of {n} can be submitted (queue: {running_count}/{max_queue})")

            if st.button(f"Submit {can_submit} Job(s)", key=f"qs_submit_{obj_type}", type="primary"):
                submitted = 0
                for _, row in selected.head(can_submit).iterrows():
                    owner = row['table_owner']
                    table = row['table_name']
                    comp = row['recommended_strategy']
                    part = row.get('partition_name')
                    if pd.notna(part) and part:
                        pass
                    else:
                        part = None

                    row_dop = int(row.get('dop', max_dop) or max_dop)
                    result = TargetQueries.submit_compression_job(
                        db_id, owner, table, comp,
                        partition_name=part, parallel_degree=row_dop
                    )
                    if result.get('success'):
                        submitted += 1
                        st.toast(f"Submitted: {owner}.{table} → {result.get('job_name')}")
                    else:
                        st.error(f"Failed {owner}.{table}: {result.get('error')}")

                if submitted > 0:
                    st.success(f"{submitted} job(s) submitted to DBMS_SCHEDULER")
                    st.rerun()


def _render_schemas_tab(db_id, max_queue, max_dop):
    """Render the Schemas tab for bulk schema-level compression submission."""
    st.subheader("Bulk Schema Compression")
    st.markdown("Select one or more schemas to queue ALL pending compression candidates at once.")

    schemas = TargetQueries.get_available_schemas(db_id)
    if not schemas:
        st.info("No schemas found. Run a scan first.")
        return

    selected_schemas = st.multiselect(
        "Select Schemas", schemas, key="qs_bulk_schemas"
    )

    col1, col2 = st.columns(2)
    with col1:
        bulk_dop = st.slider("DOP for all jobs", 1, max_dop, min(4, max_dop), key="qs_bulk_dop")

    if not selected_schemas:
        st.caption("Select one or more schemas above.")
        return

    # Count pending candidates across selected schemas
    all_candidates = []
    for s in selected_schemas:
        recs = CentralQueries.get_recommendations(
            schema=s, database_id=db_id, show_executed=False,
            min_savings_pct=0, limit=5000
        )
        if not recs.empty:
            recs.columns = [c.lower() for c in recs.columns]
            for _, r in recs.iterrows():
                pn = r.get('partition_name')
                all_candidates.append({
                    'database_id': db_id,
                    'owner': r['table_owner'],
                    'table_name': r['table_name'],
                    'compression_type': r['recommended_strategy'],
                    'partition_name': pn if pd.notna(pn) else None,
                    'dop': bulk_dop,
                })

    st.info(f"**{len(all_candidates)}** pending candidates across **{len(selected_schemas)}** schema(s)")

    if len(all_candidates) == 0:
        st.caption("No pending candidates. All objects may already be compressed.")
        return

    col1, col2 = st.columns(2)
    with col1:
        confirm = st.checkbox("Confirm Bulk Submission", key="qs_bulk_confirm")
    with col2:
        if st.button(f"Submit All {len(all_candidates)} Candidates",
                     disabled=not confirm, type="primary",
                     key="qs_bulk_submit", use_container_width=True):
            result = _bulk_submit(all_candidates, db_id, max_queue, bulk_dop)
            st.success(
                f"Submitted: {result['submitted']}, "
                f"Queued for later: {result['queued']}, "
                f"Failed: {result['failed']}"
            )
            if result['queued'] > 0:
                st.info("Queued items will be submitted automatically by the Scheduler page.")
            st.session_state.selected_page = "Scheduler"
            st.rerun()


def _bulk_submit(candidates, db_id, max_queue, default_dop):
    """Submit candidates respecting max_queue. Overflow goes to session_state queue."""
    running_df = TargetQueries.get_running_compression_jobs(db_id)
    running_count = len(running_df) if not running_df.empty else 0
    slots = max(0, max_queue - running_count)

    submitted = 0
    failed = 0
    overflow = []

    for i, item in enumerate(candidates):
        if i < slots:
            result = TargetQueries.submit_compression_job(
                item['database_id'], item['owner'], item['table_name'],
                item['compression_type'],
                partition_name=item.get('partition_name'),
                parallel_degree=item.get('dop', default_dop)
            )
            if result.get('success'):
                submitted += 1
            else:
                if 'already has a running job' in result.get('error', ''):
                    pass  # skip duplicates
                else:
                    failed += 1
        else:
            overflow.append(item)

    # Store overflow in session_state for Scheduler to drain
    if 'scheduler_pending_queue' not in st.session_state:
        st.session_state.scheduler_pending_queue = []
    st.session_state.scheduler_pending_queue.extend(overflow)

    return {'submitted': submitted, 'queued': len(overflow), 'failed': failed}


if __name__ == "__main__":
    show_quick_scan_page()
