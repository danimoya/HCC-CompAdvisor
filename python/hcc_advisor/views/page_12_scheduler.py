"""
Scheduler Page - HCC Compression Advisor
Cross-database job queue monitor with auto-refresh and pending queue drain
"""

import streamlit as st
import pandas as pd
import time
from datetime import datetime, timedelta
from hcc_advisor.utils.central_queries import CentralQueries
from hcc_advisor.utils.target_queries import TargetQueries


def show_scheduler_page():
    st.title("Scheduler")
    st.markdown("Monitor compression and rebuild jobs across databases")
    st.markdown("---")

    db_id = st.session_state.get('active_database_id')
    mode = "single" if db_id else "cross"

    # Initialize session state — auto-refresh OFF on startup, user must start it
    if 'scheduler_auto_refresh' not in st.session_state:
        st.session_state.scheduler_auto_refresh = False
    if 'scheduler_pending_queue' not in st.session_state:
        # Reload queued items from central DB (survives app restart)
        st.session_state.scheduler_pending_queue = _load_persistent_queue(db_id)

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
            st.session_state['scheduler_last_refresh'] = datetime.now()
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

    st.markdown("---")

    # Metrics
    summary = CentralQueries.get_scheduler_job_summary(database_id=db_id)
    col1, col2, col3, col4, col5 = st.columns(5)
    with col1:
        st.metric("Total (24h)", summary['total'])
    with col2:
        st.metric("Queued", summary['queued'])
    with col3:
        st.metric("Running", summary['running'])
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

    # Recurring Analysis section
    if db_id:
        st.markdown("---")
        with st.expander("Recurring Stats Refresh Jobs"):
            _render_recurring_jobs(db_id)

    # Auto-refresh logic (at the end so page renders first)
    if st.session_state.scheduler_auto_refresh:
        last = st.session_state.get('scheduler_last_refresh')
        if last:
            elapsed = (datetime.now() - last).total_seconds()
            remaining = max(0, interval * 60 - elapsed)
            rem_min = int(remaining // 60)
            rem_sec = int(remaining % 60)
            st.caption(
                f"Last refresh: **{last.strftime('%H:%M:%S')}** — "
                f"Next in **{rem_min}m {rem_sec}s** (every {interval} min) — "
                f"click Stop to disable"
            )
        else:
            st.caption(f"Auto-refreshing every {interval} minute(s)... (click Stop to disable)")

        _do_refresh(db_id)
        st.session_state['scheduler_last_refresh'] = datetime.now()
        time.sleep(interval * 60)
        st.rerun()


def _render_recurring_jobs(db_id):
    """Show and manage recurring analysis jobs on the target."""
    existing = TargetQueries.get_recurring_scan_jobs(db_id)
    if not existing.empty:
        existing.columns = [c.lower() for c in existing.columns]
        st.dataframe(existing, use_container_width=True, hide_index=True)

        job_to_drop = st.selectbox("Drop job", existing['job_name'].tolist(), key="sched_drop_job")
        if st.button("Drop Selected Job", key="sched_drop_btn"):
            ok = TargetQueries.drop_recurring_scan_job(db_id, job_to_drop)
            if ok:
                st.success(f"Dropped {job_to_drop}")
                st.rerun()
    else:
        st.caption("No recurring jobs configured.")

    st.markdown("---")
    col1, col2 = st.columns(2)
    with col1:
        freq = st.selectbox("Frequency", ["DAILY", "WEEKLY", "MONTHLY"],
                             index=1, key="sched_freq")
    with col2:
        if st.button("Create Recurring Job", key="sched_create_recurring",
                     type="primary", use_container_width=True):
            result = TargetQueries.create_recurring_scan_job(db_id, freq)
            if result.get('success'):
                st.success(f"Created {result['job_name']} ({freq})")
                st.rerun()
            else:
                st.error(result.get('error', 'Failed'))


def _do_refresh(db_id):
    """Poll completed jobs and drain pending queue."""
    if db_id:
        TargetQueries.check_completed_jobs(db_id)
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
    # Drain pending queue (handles per-database grouping internally)
    _drain_pending_queue(db_id)


def _drain_pending_queue(db_id):
    """Submit pending items respecting per-database DOP budget (CPU_COUNT/2).
    Total DOP of running jobs + new job DOP must not exceed the budget."""
    queue = st.session_state.get('scheduler_pending_queue', [])
    if not queue:
        return

    from collections import defaultdict
    by_db = defaultdict(list)
    for item in queue:
        did = item.get('database_id', db_id)
        if did:
            by_db[int(did)].append(item)

    submitted = 0
    remaining = []
    db_dop_remaining = {}

    for did, items in by_db.items():
        if did not in db_dop_remaining:
            try:
                cpu = TargetQueries.get_cpu_count(did)
                budget = max(1, cpu // 2)
                used = TargetQueries.get_running_total_dop(did)
                db_dop_remaining[did] = max(0, budget - used)
            except Exception:
                db_dop_remaining[did] = 0

        for item in items:
            item_dop = int(item.get('dop', 4) or 4)
            if db_dop_remaining.get(did, 0) >= item_dop:
                result = TargetQueries.submit_compression_job(
                    did, item['owner'], item['table_name'],
                    item['compression_type'],
                    partition_name=item.get('partition_name'),
                    parallel_degree=item_dop
                )
                if result.get('success'):
                    submitted += 1
                    db_dop_remaining[did] -= item_dop
                elif 'already has a running job' not in result.get('error', ''):
                    remaining.append(item)
            else:
                remaining.append(item)

    st.session_state.scheduler_pending_queue = remaining
    _save_persistent_queue(remaining)
    if submitted > 0:
        st.toast(f"Drained {submitted} from queue ({len(remaining)} remaining)")


def _load_persistent_queue(db_id) -> list:
    """Load QUEUED items from t_compression_history that haven't been submitted yet."""
    from hcc_advisor.utils.central_connector import CentralConnector
    try:
        db_filter = "AND database_id = :db" if db_id else ""
        params = {'db': db_id} if db_id else {}
        df = CentralConnector.execute_query(f"""
            SELECT database_id, owner, object_name, partition_name,
                   compression_type_applied as compression_type,
                   parallel_degree as dop
            FROM t_compression_history
            WHERE operation_status = 'QUEUED' {db_filter}
            ORDER BY start_time
        """, params if params else None)
        if not df.empty:
            df.columns = [c.lower() for c in df.columns]
            items = []
            for _, r in df.iterrows():
                pn = r.get('partition_name')
                items.append({
                    'database_id': int(r['database_id']),
                    'owner': r['owner'],
                    'table_name': r['object_name'],
                    'compression_type': r['compression_type'],
                    'partition_name': pn if pn and str(pn) != 'None' else None,
                    'dop': int(r.get('dop') or 4),
                })
            return items
    except Exception:
        pass
    return []


def _save_persistent_queue(queue: list):
    """Persist the pending queue to t_compression_history with status QUEUED.
    Replaces all existing QUEUED rows."""
    from hcc_advisor.utils.central_connector import CentralConnector
    try:
        # Delete old QUEUED rows
        CentralConnector.execute_dml(
            "DELETE FROM t_compression_history WHERE operation_status = 'QUEUED'"
        )
        # Insert current queue
        if queue:
            for item in queue:
                CentralConnector.execute_dml("""
                    INSERT INTO t_compression_history (
                        database_id, owner, object_name, object_type,
                        partition_name, compression_type_applied,
                        parallel_degree, operation_status, start_time, executed_by
                    ) VALUES (
                        :db, :owner, :tbl, :otype, :part, :comp,
                        :dop, 'QUEUED', SYSTIMESTAMP, 'HCC_ADVISOR'
                    )
                """, {
                    'db': item['database_id'], 'owner': item['owner'],
                    'tbl': item['table_name'],
                    'otype': 'PARTITION' if item.get('partition_name') else 'TABLE',
                    'part': item.get('partition_name'),
                    'comp': item['compression_type'],
                    'dop': item.get('dop', 4),
                })
    except Exception:
        pass
