"""
Compression Wizard - HCC Compression Advisor
Step-by-step guided compression lifecycle
"""

import streamlit as st
import pandas as pd
from hcc_advisor.utils.central_queries import CentralQueries
from hcc_advisor.utils.target_queries import TargetQueries

STEPS = [
    "Select Database",
    "Quick Scan",
    "Review Candidates",
    "Submit Jobs",
    "Monitor",
    "Post-Compression"
]

THROTTLE_PROFILES = {
    'Low': {'divisor': 4, 'label': 'Low — minimal impact (CPU/4)'},
    'Medium': {'divisor': 3, 'label': 'Medium — balanced (CPU/3)'},
    'High': {'divisor': 2, 'label': 'High — maximum throughput (CPU/2)'},
}


def show_wizard_page():
    st.title("Compression Wizard")

    # Initialize wizard state
    if 'wizard_step' not in st.session_state:
        st.session_state.wizard_step = 1

    step = st.session_state.wizard_step

    # Progress bar
    st.progress((step - 1) / (len(STEPS) - 1), text=f"Step {step} of {len(STEPS)}: {STEPS[step - 1]}")
    st.markdown("---")

    # Render current step
    if step == 1:
        _step_select_database()
    elif step == 2:
        _step_quick_scan()
    elif step == 3:
        _step_review_candidates()
    elif step == 4:
        _step_submit()
    elif step == 5:
        _step_monitor()
    elif step == 6:
        _step_post_compression()


def _nav_buttons(can_back=True, can_next=True, next_label="Next", next_disabled=False):
    """Render Back/Next navigation buttons."""
    col1, col2, col3 = st.columns([1, 2, 1])
    with col1:
        if can_back and st.session_state.wizard_step > 1:
            if st.button("Back", key="wiz_back", use_container_width=True):
                st.session_state.wizard_step -= 1
                st.rerun()
    with col3:
        if can_next:
            if st.button(next_label, key="wiz_next", use_container_width=True,
                         type="primary", disabled=next_disabled):
                st.session_state.wizard_step += 1
                st.rerun()


# =========================================================================
# STEP 1: Select Database
# =========================================================================
def _step_select_database():
    st.subheader("Step 1: Select Target Database")

    targets = CentralQueries.get_target_databases()
    if targets.empty:
        st.warning("No target databases registered. Go to DB Connections to add one.")
        return

    targets.columns = [c.lower() for c in targets.columns]
    db_options = {row['display_name'] or row['database_name']: row['database_id']
                  for _, row in targets.iterrows()}

    selected = st.selectbox("Target Database", list(db_options.keys()), key="wiz_db_select")
    db_id = db_options[selected]

    st.session_state.wizard_db_id = db_id

    # Show DB info
    info = CentralQueries.get_target_database(db_id)
    if info:
        col1, col2, col3 = st.columns(3)
        with col1:
            st.metric("Host", info.get('host', info.get('db_host', '?')))
        with col2:
            st.metric("Platform", info.get('platform_type', '?'))
        with col3:
            cpu = TargetQueries.get_cpu_count(db_id)
            st.metric("CPU Count", cpu)

    _nav_buttons(can_back=False, next_disabled=not db_id)


# =========================================================================
# STEP 2: Quick Scan
# =========================================================================
def _step_quick_scan():
    st.subheader("Step 2: Quick Scan")

    db_id = st.session_state.get('wizard_db_id')
    if not db_id:
        st.error("No database selected. Go back to Step 1.")
        return

    schemas = TargetQueries.get_available_schemas(db_id)

    col1, col2 = st.columns(2)
    with col1:
        schema = st.selectbox("Schema", ["All Schemas"] + schemas, key="wiz_schema")
    with col2:
        throttle = st.selectbox("Throttle", list(THROTTLE_PROFILES.keys()), index=1,
                                 key="wiz_throttle",
                                 format_func=lambda k: THROTTLE_PROFILES[k]['label'])

    st.session_state.wizard_schema = None if schema == "All Schemas" else schema
    st.session_state.wizard_throttle = throttle

    if st.button("Scan Now", type="primary", use_container_width=True, key="wiz_scan"):
        with st.spinner("Running quick scan (hotness-only, no DBMS_COMPRESSION)..."):
            results = TargetQueries.quick_scan(db_id, owner=st.session_state.wizard_schema)
            st.session_state.wizard_scan_count = len(results)
            tables = sum(1 for r in results if r['OBJECT_TYPE'] == 'TABLE')
            parts = sum(1 for r in results if r['OBJECT_TYPE'] == 'PARTITION')
            subs = sum(1 for r in results if r['OBJECT_TYPE'] == 'SUBPARTITION')
            st.success(f"Scan complete: {tables} tables, {parts} partitions, {subs} subpartitions")

    scan_count = st.session_state.get('wizard_scan_count', 0)
    if scan_count > 0:
        st.info(f"Last scan: {scan_count} objects analyzed")

    _nav_buttons(next_disabled=scan_count == 0)


# =========================================================================
# STEP 3: Review Candidates
# =========================================================================
def _step_review_candidates():
    st.subheader("Step 3: Review Compression Candidates")

    db_id = st.session_state.get('wizard_db_id')
    schema = st.session_state.get('wizard_schema')

    recs = CentralQueries.get_recommendations(
        schema=schema, database_id=db_id, show_executed=False,
        min_savings_pct=0, limit=500
    )

    if recs.empty:
        st.warning("No pending candidates found. Run a scan first or adjust filters.")
        _nav_buttons(can_next=False)
        return

    recs.columns = [c.lower() for c in recs.columns]

    # Summary
    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric("Candidates", len(recs))
    with col2:
        total_mb = recs['current_size_mb'].sum() if 'current_size_mb' in recs.columns else 0
        st.metric("Total Size", f"{total_mb / 1024:.2f} GB")
    with col3:
        if 'savings_pct' in recs.columns:
            avg_sav = recs['savings_pct'].mean()
            st.metric("Avg Savings", f"{avg_sav:.1f}%")

    # Optional AI analysis
    col1, col2 = st.columns([1, 3])
    with col1:
        if st.button("Get AI Analysis", key="wiz_ai"):
            st.session_state.selected_page = "AI Advisor"
            st.rerun()

    # Display candidates table
    display_cols = ['table_owner', 'table_name', 'object_type', 'current_size_mb',
                    'recommended_strategy', 'hotness_score', 'execution_status']
    available = [c for c in display_cols if c in recs.columns]
    st.dataframe(recs[available], use_container_width=True, hide_index=True,
                 height=min(35 * len(recs) + 50, 500))

    # Store for next step
    st.session_state.wizard_candidate_count = len(recs)

    _nav_buttons()


# =========================================================================
# STEP 4: Submit Jobs
# =========================================================================
def _step_submit():
    st.subheader("Step 4: Submit Compression Jobs")

    db_id = st.session_state.get('wizard_db_id')
    schema = st.session_state.get('wizard_schema')
    throttle = st.session_state.get('wizard_throttle', 'Medium')
    profile = THROTTLE_PROFILES.get(throttle, THROTTLE_PROFILES['Medium'])

    cpu = TargetQueries.get_cpu_count(db_id) if db_id else 8
    dop = max(1, cpu // profile['divisor'])
    max_queue = max(1, cpu // profile['divisor'])

    # Get pending candidates
    recs = CentralQueries.get_recommendations(
        schema=schema, database_id=db_id, show_executed=False,
        min_savings_pct=0, limit=5000
    )

    if recs.empty:
        st.info("No pending candidates to submit.")
        _nav_buttons(can_next=True, next_label="Skip to Monitor")
        return

    recs.columns = [c.lower() for c in recs.columns]

    # Summary
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric("Objects", len(recs))
    with col2:
        st.metric("Throttle", throttle)
    with col3:
        st.metric("DOP per job", dop)
    with col4:
        forecast = CentralQueries.get_forecast_data(database_id=db_id)
        est_hrs = (forecast['pending_count'] * forecast['avg_duration_sec']) / 3600
        st.metric("Est. Time", f"{est_hrs:.1f} hrs" if est_hrs < 24 else f"{est_hrs / 24:.1f} days")

    st.markdown("---")

    confirm = st.checkbox("I confirm I want to submit all pending candidates for compression",
                           key="wiz_confirm_submit")

    if st.button("Submit All to Scheduler", disabled=not confirm, type="primary",
                 use_container_width=True, key="wiz_submit_btn"):
        # Build candidate list
        candidates = []
        for _, r in recs.iterrows():
            pn = r.get('partition_name')
            candidates.append({
                'database_id': db_id,
                'owner': r['table_owner'],
                'table_name': r['table_name'],
                'compression_type': r['recommended_strategy'],
                'partition_name': pn if pd.notna(pn) else None,
                'dop': dop,
            })

        from hcc_advisor.views.page_08_quick_scan import _bulk_submit
        result = _bulk_submit(candidates, db_id, max_queue, dop)
        st.success(
            f"Submitted: {result['submitted']}, "
            f"Queued: {result['queued']}, "
            f"Failed: {result['failed']}"
        )
        st.session_state.wizard_step = 5
        st.rerun()

    _nav_buttons(next_label="Skip to Monitor")


# =========================================================================
# STEP 5: Monitor
# =========================================================================
def _step_monitor():
    st.subheader("Step 5: Monitor Progress")

    db_id = st.session_state.get('wizard_db_id')

    # Embedded scheduler metrics
    summary = CentralQueries.get_scheduler_job_summary(database_id=db_id)
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric("Queued", summary.get('queued', 0))
    with col2:
        st.metric("Running", summary.get('running', 0))
    with col3:
        st.metric("Succeeded", summary.get('succeeded', 0))
    with col4:
        st.metric("Failed", summary.get('failed', 0))

    # Job details
    details = CentralQueries.get_scheduler_job_details(database_id=db_id)
    if not details.empty:
        details.columns = [c.lower() for c in details.columns]
        st.dataframe(details, use_container_width=True, hide_index=True,
                     height=min(35 * len(details) + 50, 400))

    col1, col2 = st.columns(2)
    with col1:
        if st.button("Refresh Status", key="wiz_monitor_refresh", use_container_width=True):
            if db_id:
                TargetQueries.check_completed_jobs(db_id)
            st.rerun()
    with col2:
        if st.button("Open Full Scheduler", key="wiz_goto_sched", use_container_width=True):
            st.session_state.selected_page = "Scheduler"
            st.rerun()

    all_done = summary.get('queued', 0) == 0 and summary.get('running', 0) == 0
    if all_done and summary.get('succeeded', 0) > 0:
        st.success("All jobs completed!")

    _nav_buttons(next_label="Finish" if all_done else "Next (Post-Compression)")


# =========================================================================
# STEP 6: Post-Compression
# =========================================================================
def _step_post_compression():
    st.subheader("Step 6: Post-Compression Tasks")
    st.markdown("Compression jobs are done. Complete these follow-up tasks:")

    db_id = st.session_state.get('wizard_db_id')

    # Show savings summary
    progress = CentralQueries.get_compression_progress(database_id=db_id)
    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric("Compressed", progress.get('compressed', 0))
    with col2:
        st.metric("Total Saved", f"{progress.get('saved_mb', 0) / 1024:.2f} GB")
    with col3:
        orig = progress.get('compressed_original_mb', 0) + progress.get('uncompressed_mb', 0)
        pct = round(progress.get('compressed_original_mb', 0) / orig * 100, 1) if orig > 0 else 0
        st.metric("Progress", f"{pct}%")

    st.markdown("---")
    st.markdown("### Recommended Next Steps")

    col1, col2, col3 = st.columns(3)
    with col1:
        st.markdown("#### Shrink Tablespaces")
        st.caption("Reclaim freed disk space from compressed datafiles")
        if st.button("Open Tablespace Manager", use_container_width=True, key="wiz_ts"):
            st.session_state.selected_page = "Tablespaces"
            st.rerun()

    with col2:
        st.markdown("#### Rebuild Indexes")
        st.caption("Check for and rebuild any unusable indexes")
        if st.button("Open Index Manager", use_container_width=True, key="wiz_idx"):
            st.session_state.selected_page = "Index Manager"
            st.rerun()

    with col3:
        st.markdown("#### View Dashboard")
        st.caption("See overall compression effectiveness and savings")
        if st.button("Open Dashboard", use_container_width=True, key="wiz_dash"):
            st.session_state.selected_page = "Overview"
            st.rerun()

    st.markdown("---")
    if st.button("Start New Wizard", type="primary", use_container_width=True, key="wiz_restart"):
        for k in list(st.session_state.keys()):
            if k.startswith('wizard_') or k.startswith('wiz_'):
                del st.session_state[k]
        st.session_state.wizard_step = 1
        st.rerun()


if __name__ == "__main__":
    show_wizard_page()
