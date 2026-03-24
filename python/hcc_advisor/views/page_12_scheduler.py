"""
Scheduler Page - HCC Compression Advisor
Cross-database job queue monitor with auto-refresh and pending queue drain
"""

import streamlit as st
import pandas as pd
import time
from hcc_advisor.utils.central_queries import CentralQueries
from hcc_advisor.utils.target_queries import TargetQueries


def show_scheduler_page():
    st.title("Scheduler")
    st.markdown("Monitor compression and rebuild jobs across databases")
    st.markdown("---")

    db_id = st.session_state.get('active_database_id')
    mode = "single" if db_id else "cross"

    # Initialize session state
    if 'scheduler_auto_refresh' not in st.session_state:
        st.session_state.scheduler_auto_refresh = True
    if 'scheduler_pending_queue' not in st.session_state:
        st.session_state.scheduler_pending_queue = []

    # Controls row
    col1, col2, col3, col4 = st.columns([2, 1, 1, 1])
    with col1:
        if db_id:
            st.caption(f"Showing jobs for active database (ID={db_id})")
        else:
            st.caption("Showing jobs across ALL registered databases")
    with col2:
        if st.button("Refresh Now", key="sched_refresh", use_container_width=True):
            _do_refresh(db_id)
            st.rerun()
    with col3:
        interval = st.selectbox("Interval", [1, 2, 5, 10], index=2,
                                format_func=lambda x: f"{x} min",
                                key="sched_interval")
    with col4:
        if st.session_state.scheduler_auto_refresh:
            if st.button("Stop Auto-refresh", key="sched_stop", use_container_width=True):
                st.session_state.scheduler_auto_refresh = False
                st.rerun()
        else:
            if st.button("Start Auto-refresh", key="sched_start",
                         use_container_width=True, type="primary"):
                st.session_state.scheduler_auto_refresh = True
                st.rerun()

    # Show pending local queue
    pending = st.session_state.get('scheduler_pending_queue', [])
    if pending:
        st.warning(f"Local queue: **{len(pending)}** items waiting to be submitted as slots free up")

    st.markdown("---")

    # Metrics
    summary = CentralQueries.get_scheduler_job_summary(database_id=db_id)
    col1, col2, col3, col4, col5 = st.columns(5)
    with col1:
        st.metric("Total (24h)", summary['total'])
    with col2:
        st.metric("Running", summary['running'])
    with col3:
        st.metric("Queued", len(pending))
    with col4:
        st.metric("Succeeded", summary['succeeded'])
    with col5:
        st.metric("Failed", summary['failed'])

    st.markdown("---")

    # Status filter
    status_filter = st.selectbox(
        "Filter by Status",
        ["All", "IN_PROGRESS", "SUCCESS", "FAILED"],
        key="sched_status_filter"
    )

    # Job details table
    details = CentralQueries.get_scheduler_job_details(database_id=db_id)

    if not details.empty:
        details.columns = [c.lower() for c in details.columns]

        if status_filter != "All":
            details = details[details['status'] == status_filter]

        if not details.empty:
            st.dataframe(
                details, use_container_width=True, hide_index=True,
                height=min(35 * len(details) + 50, 700)
            )
        else:
            st.info(f"No jobs with status '{status_filter}' in the last 24 hours.")
    else:
        st.info("No compression jobs recorded in the last 24 hours.")

    # Auto-refresh logic (at the end so page renders first)
    if st.session_state.scheduler_auto_refresh:
        st.caption(f"Auto-refreshing every {interval} minute(s)... (click Stop to disable)")
        _do_refresh(db_id)
        time.sleep(interval * 60)
        st.rerun()


def _do_refresh(db_id):
    """Poll completed jobs and drain pending queue."""
    if db_id:
        TargetQueries.check_completed_jobs(db_id)
        _drain_pending_queue(db_id)
    else:
        # Cross-database: poll all registered databases
        try:
            dbs = CentralQueries.get_target_databases()
            if not dbs.empty:
                dbs.columns = [c.lower() for c in dbs.columns]
                for _, db in dbs.iterrows():
                    did = db.get('database_id')
                    if did:
                        try:
                            TargetQueries.check_completed_jobs(int(did))
                        except Exception:
                            pass
        except Exception:
            pass
        _drain_pending_queue(None)


def _drain_pending_queue(db_id):
    """Submit pending items from local queue as slots free up."""
    queue = st.session_state.get('scheduler_pending_queue', [])
    if not queue:
        return

    # Determine max_queue from first item's database
    first_db = queue[0].get('database_id', db_id)
    if first_db:
        cpu = TargetQueries.get_cpu_count(first_db)
        max_queue = max(1, cpu // 2)

        running_df = TargetQueries.get_running_compression_jobs(first_db)
        running_count = len(running_df) if not running_df.empty else 0
        slots = max_queue - running_count
    else:
        return

    submitted = 0
    remaining = []
    for item in queue:
        if slots <= 0:
            remaining.append(item)
            continue
        result = TargetQueries.submit_compression_job(
            item['database_id'], item['owner'], item['table_name'],
            item['compression_type'],
            partition_name=item.get('partition_name'),
            parallel_degree=item.get('dop', 4)
        )
        if result.get('success'):
            submitted += 1
            slots -= 1
        elif 'already has a running job' not in result.get('error', ''):
            remaining.append(item)

    st.session_state.scheduler_pending_queue = remaining
    if submitted > 0:
        st.toast(f"Drained {submitted} from queue ({len(remaining)} remaining)")
