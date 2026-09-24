"""
Scheduler Page - HCC Compression Advisor
Cross-database job queue monitor with auto-refresh and pending queue drain
"""

import streamlit as st
import pandas as pd
from datetime import datetime, timedelta
from hcc_advisor.utils.central_queries import CentralQueries
from hcc_advisor.utils.target_queries import (
    TargetQueries,
    is_supported_compression_type,
    is_protected_schema,
    canonical_compression,
    target_ddl_info,
)
from hcc_advisor.utils.sql_builder import (
    build_compression_script,
    build_compression_manifest,
    gather_dependent_indexes,
    gather_target_info,
)
from hcc_advisor.utils.oracle_capabilities import HCC_NOT_SUPPORTED, hcc_block_reason
from hcc_advisor.utils.logger import log_warning
from hcc_advisor.auth import AuthManager, ROLE_OPERATOR
from hcc_advisor.utils.ui_refresh import schedule_rerun


def show_scheduler_page():
    st.title("Scheduler")
    st.markdown("Monitor compression and rebuild jobs across databases")
    st.markdown("---")

    db_id = st.session_state.get('active_database_id')

    # Initialize session state — auto-refresh OFF on startup, user must start it
    if 'scheduler_auto_refresh' not in st.session_state:
        st.session_state.scheduler_auto_refresh = False
    # The job queue lives in T_COMPRESSION_HISTORY (QUEUED rows); nothing to load.

    # Controls row
    col1, col2, col3, col4 = st.columns([2, 1, 1, 1])
    with col1:
        if db_id:
            st.caption(f"Showing jobs for active database (ID={db_id})")
        else:
            st.caption("Showing jobs across ALL registered databases")
    with col2:
        refresh_clicked = st.button("Refresh Now", key="sched_refresh", use_container_width=True)
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

    # Refresh (Refresh Now, or every render while auto-refresh is on) BEFORE
    # the metrics and job table are read, so they already show the jobs this
    # refresh reconciled or submitted instead of lagging one interval behind.
    if refresh_clicked or st.session_state.scheduler_auto_refresh:
        with st.spinner("Refreshing job status..."):
            _do_refresh(db_id)
        st.session_state['scheduler_last_refresh'] = datetime.now()

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
        ["All", "QUEUED", "IN_PROGRESS", "SUCCESS", "FAILED"],
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

    # Close operations that no job or thread will ever finish
    st.markdown("---")
    with st.expander("Reconcile stale operations"):
        _render_reconcile_section(db_id)

    # Export to SQL / CSV section
    st.markdown("---")
    with st.expander("Export Operations (SQL script or CSV manifest)"):
        _render_export_section(db_id)

    # Import a compression plan from a CSV manifest
    st.markdown("---")
    with st.expander("Import Compression Plan from CSV"):
        _render_import_section(db_id)

    # Recurring Analysis section
    if db_id:
        st.markdown("---")
        with st.expander("Recurring Stats Refresh Jobs"):
            _render_recurring_jobs(db_id)

    # Auto-refresh: _do_refresh ran above, before the metrics; below, wait the
    # chosen interval and rerun in the same session. No browser reload (meta
    # http-equiv refresh): that starts a new Streamlit session, which logs the
    # user out and resets this toggle and the selected page.
    if st.session_state.scheduler_auto_refresh:
        last = st.session_state['scheduler_last_refresh']
        next_at = last + timedelta(minutes=interval)
        st.caption(
            f"Last refresh: **{last.strftime('%H:%M:%S')}** — "
            f"Next at **{next_at.strftime('%H:%M:%S')}** (every {interval} min) — "
            f"click Stop to disable"
        )

    # Last statement of the render. Stop and the other controls still cut the
    # wait short (see schedule_rerun).
    schedule_rerun('scheduler_auto_refresh', interval * 60)


def _render_export_section(current_db_id):
    """Export scheduled operations as a SQL script or a portable CSV manifest."""
    st.markdown("Export compression operations as a **SQL script** (runnable "
                "outside HCC Advisor) or as a **CSV manifest** that can be "
                "re-imported into another target database below.")

    # Database filter
    dbs_df = CentralQueries.get_target_databases()
    if not dbs_df.empty:
        dbs_df.columns = [c.lower() for c in dbs_df.columns]
        db_options = {'All Databases': None}
        for _, db in dbs_df.iterrows():
            label = db.get('display_name') or db.get('database_name', f"db_{db.get('database_id')}")
            db_options[label] = int(db.get('database_id'))
    else:
        db_options = {'All Databases': None}

    col1, col2 = st.columns(2)
    with col1:
        default_label = 'All Databases'
        if current_db_id:
            for label, did in db_options.items():
                if did == current_db_id:
                    default_label = label
                    break
        default_idx = list(db_options.keys()).index(default_label)
        selected_db = st.selectbox("Database Filter", list(db_options.keys()),
                                    index=default_idx, key="export_db")
        export_db_id = db_options[selected_db]
    with col2:
        status_map = {
            'All': None,
            'Pending (QUEUED)': 'QUEUED',
            'Running (IN_PROGRESS)': 'IN_PROGRESS',
            'Completed (SUCCESS)': 'SUCCESS',
            'Failed (FAILED)': 'FAILED',
        }
        selected_status_label = st.selectbox("Status Filter", list(status_map.keys()),
                                              key="export_status")
        export_status = status_map[selected_status_label]

    # Preview + generate SQL
    df = CentralQueries.get_scheduler_jobs_for_export(
        database_id=export_db_id, status_filter=export_status
    )

    if df.empty:
        st.info("No operations match the selected filters.")
        return

    df.columns = [c.lower() for c in df.columns]
    st.caption(f"**{len(df)}** operations will be included in the export")

    # Preview first 10
    preview_cols = ['database_display', 'owner', 'object_name', 'partition_name',
                    'subpartition_name', 'compression_type_applied', 'parallel_degree',
                    'operation_status']
    available = [c for c in preview_cols if c in df.columns]
    st.dataframe(df[available].head(10), use_container_width=True, hide_index=True)
    if len(df) > 10:
        st.caption(f"Showing first 10 of {len(df)} rows")

    export_format = st.radio(
        "Export format",
        ["SQL script", "CSV manifest"],
        horizontal=True,
        key="export_format",
        help="SQL = runnable ALTER TABLE MOVE script. "
             "CSV = portable manifest re-importable into another database.",
    )

    base_name = f"hcc_export_{selected_db.replace(' ', '_').lower()}_{export_status or 'all'}"

    if export_format == "SQL script":
        include_indexes = st.checkbox(
            "Include index rebuild statements (queries target for dependent objects)",
            value=True, key="export_include_indexes",
            help="Adds ALTER INDEX ... REBUILD after each MOVE that leaves indexes "
                 "UNUSABLE (a table MOVE before Oracle 12.2). ONLINE moves keep "
                 "indexes usable and get no rebuild."
        )

        # Build SQL script (with index rebuild DDL if requested), each MOVE for
        # its target's Oracle version and platform.
        with st.spinner("Generating SQL script..."):
            targets = gather_target_info(df)
            index_map = gather_dependent_indexes(df, targets) if include_indexes else {}
            sql_script = build_compression_script(df, selected_status_label, selected_db,
                                                  index_map, targets=targets)

        st.download_button(
            label=f"Download SQL Script ({len(df)} operations)",
            data=sql_script,
            file_name=f"{base_name}.sql",
            mime="text/plain",
            type="primary",
            key="export_download"
        )
    else:
        csv_data = build_compression_manifest(df).to_csv(index=False)
        st.caption("The CSV manifest can be re-imported below into any registered "
                   "target database; the importer re-checks each object there.")
        st.download_button(
            label=f"Download CSV Manifest ({len(df)} operations)",
            data=csv_data,
            file_name=f"{base_name}.csv",
            mime="text/csv",
            type="primary",
            key="export_download_csv"
        )


def _import_row_state(obj, chk, platform_type) -> str:
    """Verification state of one imported manifest row; only READY rows are
    queued. platform_type is the import target's (target_ddl_info)."""
    planned = obj['compression_type']
    current = chk.get('current_compress_for') or chk.get('current_compression') or 'NONE'
    if not chk['exists']:
        return 'MISSING'
    if is_protected_schema(obj['owner']):
        # Oracle-maintained schema (SYS, AUDSYS, ...): visible and alterable
        # when the target is registered AS SYSDBA — never queue it.
        return 'PROTECTED SCHEMA'
    if not is_supported_compression_type(planned):
        # Unsupported clause would raise in generate_ddl during drain and
        # crash the page — never queue it.
        return 'UNSUPPORTED COMPRESSION'
    if hcc_block_reason(planned, platform_type):
        # HCC on a non-Exadata target fails at run time with ORA-64307 (the
        # same check generate_ddl applies on enqueue and submit).
        return HCC_NOT_SUPPORTED
    if canonical_compression(current) == canonical_compression(planned):
        # Oracle reports OLTP as compress_for='ADVANCED'; normalize both
        # sides so an already-compressed object isn't needlessly re-moved.
        return 'ALREADY AT TARGET'
    return 'READY'


def _render_import_section(current_db_id):
    """Import a compression plan from a CSV manifest.

    Workflow: pick a target database, upload a CSV (as exported above), verify
    each row against that database (does the object exist? what is its current
    compress_for?), then queue the verified objects so they appear in the
    Scheduler against the selected target.
    """
    st.markdown(
        "Upload a **CSV manifest** (exported above) to load a compression plan "
        "into a target database. Every row is checked against the selected "
        "database for existence and current compression before it can be queued."
    )

    dbs_df = CentralQueries.get_target_databases()
    if dbs_df.empty:
        st.info("No target databases registered. Add one in DB Connections first.")
        return
    dbs_df.columns = [c.lower() for c in dbs_df.columns]
    db_options = {}
    for _, db in dbs_df.iterrows():
        label = db.get('display_name') or db.get('database_name', f"db_{db.get('database_id')}")
        db_options[label] = int(db.get('database_id'))

    labels = list(db_options.keys())
    default_idx = 0
    if current_db_id:
        for i, did in enumerate(db_options.values()):
            if did == current_db_id:
                default_idx = i
                break
    target_label = st.selectbox("Target Database for Import", labels,
                                index=default_idx, key="import_target_db")
    target_db_id = db_options[target_label]

    uploaded = st.file_uploader("CSV manifest", type=['csv'], key="import_csv_file")
    if uploaded is None:
        return

    try:
        raw = pd.read_csv(uploaded)
    except Exception as e:
        st.error(f"Could not read CSV: {e}")
        return
    if raw.empty:
        st.warning("The uploaded CSV has no rows.")
        return

    raw.columns = [str(c).strip().lower() for c in raw.columns]

    def _col(row, *names, default=None):
        for n in names:
            if n in row and pd.notna(row[n]):
                return row[n]
        return default

    objects = []
    for _, r in raw.iterrows():
        owner = _col(r, 'owner', 'table_owner')
        name = _col(r, 'object_name', 'table_name', 'table')
        if owner is None or name is None:
            continue
        comp = _col(r, 'compression_type', 'compression_type_applied',
                    'recommended_strategy', 'advised', 'strategy', default='QUERY HIGH')
        dop_raw = _col(r, 'parallel_degree', 'dop', default=4)
        try:
            dop = int(float(dop_raw))
        except (TypeError, ValueError):
            dop = 4
        part = _col(r, 'partition_name')
        sub = _col(r, 'subpartition_name')
        objects.append({
            'owner': str(owner).strip().upper(),
            'object_name': str(name).strip().upper(),
            'partition_name': str(part).strip() if part is not None else None,
            'subpartition_name': str(sub).strip() if sub is not None else None,
            'compression_type': str(comp).strip().upper(),
            'dop': max(1, dop),
        })

    if not objects:
        st.error("No usable rows found. The CSV needs at least 'owner' and "
                 "'object_name' columns.")
        return

    st.caption(f"Parsed **{len(objects)}** object(s) from the manifest.")

    if st.button(f"Verify against {target_label}", key="import_verify_btn",
                 type="primary", use_container_width=True):
        with st.spinner(f"Checking {len(objects)} object(s) on {target_label}..."):
            checks = TargetQueries.check_objects_existence(target_db_id, objects)
            platform_type = target_ddl_info(target_db_id).get('platform_type')
        rows = []
        verified = []
        for obj, chk in zip(objects, checks):
            planned = obj['compression_type']
            current = chk.get('current_compress_for') or chk.get('current_compression') or 'NONE'
            level = chk['object_level']
            state = _import_row_state(obj, chk, platform_type)
            rows.append({
                'Owner': obj['owner'],
                'Object': obj['object_name'],
                'Partition': obj['partition_name'] or obj['subpartition_name'] or '',
                'Level': level,
                'Planned': planned,
                'Current': current,
                'Exists': 'Yes' if chk['exists'] else 'No',
                'State': state,
            })
            if state == 'READY':
                verified.append({
                    'database_id': target_db_id,
                    'owner': obj['owner'],
                    'table_name': obj['object_name'],
                    'compression_type': planned,
                    'partition_name': obj['partition_name'],
                    'subpartition_name': obj['subpartition_name'],
                    'dop': obj['dop'],
                })
        st.session_state['import_verify_rows'] = rows
        st.session_state['import_verified_objects'] = verified
        st.session_state['import_target_label'] = target_label

    rows = st.session_state.get('import_verify_rows')
    if rows:
        st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True,
                     height=min(35 * len(rows) + 50, 500))
        n_ready = sum(1 for r in rows if r['State'] == 'READY')
        n_already = sum(1 for r in rows if r['State'] == 'ALREADY AT TARGET')
        n_missing = sum(1 for r in rows if r['State'] == 'MISSING')
        c1, c2, c3 = st.columns(3)
        c1.metric("Ready to queue", n_ready)
        c2.metric("Already compressed", n_already)
        c3.metric("Missing", n_missing)
        n_hcc = sum(1 for r in rows if r['State'] == HCC_NOT_SUPPORTED)
        if n_hcc:
            st.warning(f"{n_hcc} row(s) plan Hybrid Columnar Compression (QUERY/ARCHIVE), "
                       f"which needs an EXADATA target; this target is not one, so they "
                       f"are not queued (the MOVE would fail with ORA-64307). Re-plan them "
                       f"as OLTP or BASIC, or import them into an Exadata target.")

        verified = st.session_state.get('import_verified_objects', [])
        if verified:
            label = st.session_state.get('import_target_label', target_label)
            # Queued objects are compressed by the drain: operator role or above.
            can_queue, queue_help = AuthManager.role_gate(ROLE_OPERATOR)
            if queue_help:
                st.caption("View only: queueing objects requires the operator role.")
            if st.button(f"Add {len(verified)} verified object(s) to scheduler queue",
                         key="import_add_queue_btn", type="primary",
                         use_container_width=True, disabled=not can_queue,
                         help=queue_help) and AuthManager.require_role(ROLE_OPERATOR):
                # New QUEUED rows only; rows already in the queue are untouched.
                res = TargetQueries.enqueue_compression_jobs(verified)
                st.session_state.pop('import_verify_rows', None)
                st.session_state.pop('import_verified_objects', None)
                msg = f"Queued {res['added']} verified object(s) for {label}"
                if res['duplicates']:
                    msg += f" ({res['duplicates']} already queued or running)"
                msg += ". They appear above as QUEUED and submit as capacity frees up."
                if res['errors']:
                    st.warning(msg)
                    st.error(f"{res['rejected']} object(s) not queued:\n\n- "
                             + "\n- ".join(res['errors'][:20]))
                else:
                    st.success(msg)
                    st.rerun()
        else:
            st.info("No objects are in a READY state to queue (all are missing, "
                    "already at the target compression, or carry an "
                    "unsupported compression type, e.g. HCC on a non-Exadata target).")


def _render_recurring_jobs(db_id):
    """Show and manage recurring analysis jobs on the target."""
    # Creating/dropping DBMS_SCHEDULER jobs on the target: operator role or above.
    can_manage, manage_help = AuthManager.role_gate(ROLE_OPERATOR)
    if manage_help:
        st.caption("View only: managing recurring jobs requires the operator role.")
    existing = TargetQueries.get_recurring_scan_jobs(db_id)
    if not existing.empty:
        existing.columns = [c.lower() for c in existing.columns]
        st.dataframe(existing, use_container_width=True, hide_index=True)

        job_to_drop = st.selectbox("Drop job", existing['job_name'].tolist(), key="sched_drop_job")
        if st.button("Drop Selected Job", key="sched_drop_btn", disabled=not can_manage,
                     help=manage_help) and AuthManager.require_role(ROLE_OPERATOR):
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
                     type="primary", use_container_width=True, disabled=not can_manage,
                     help=manage_help) and AuthManager.require_role(ROLE_OPERATOR):
            result = TargetQueries.create_recurring_scan_job(db_id, freq)
            if result.get('success'):
                st.success(f"Created {result['job_name']} ({freq})")
                st.rerun()
            else:
                st.error(result.get('error', 'Failed'))


def _do_refresh(db_id):
    """Reconcile open operations (finished / lost jobs, stale rows) and drain
    the pending queue."""
    if db_id:
        res = TargetQueries.reconcile_operations(db_id)
        if res['errors']:
            st.toast(f"Status poll of db_id={db_id} incomplete: {res['errors'][0]}", icon="⚠️")
    else:
        # Cross-database: poll all registered databases
        poll_failures = []
        try:
            dbs = CentralQueries.get_target_databases()
            if not dbs.empty:
                dbs.columns = [c.lower() for c in dbs.columns]
                for _, db in dbs.iterrows():
                    did = db.get('database_id')
                    if did:
                        try:
                            res = TargetQueries.reconcile_operations(int(did))
                            if res['errors']:
                                log_warning(f"Scheduler: polling db_id={did} incomplete: "
                                            f"{res['errors']}")
                                poll_failures.append(int(did))
                        except Exception as e:
                            log_warning(f"Scheduler: polling db_id={did} failed: {e}")
                            poll_failures.append(int(did))
        except Exception as e:
            log_warning(f"Scheduler: cross-DB poll setup failed: {e}")
            st.toast(f"Cross-DB poll failed: {e}", icon="⚠️")
        if poll_failures:
            st.toast(
                f"Polling failed for {len(poll_failures)} database(s): "
                f"{', '.join(str(d) for d in poll_failures)}",
                icon="⚠️",
            )
    # Drain pending queue (handles per-database grouping internally). Draining
    # submits compression jobs, so only operator sessions drain; a viewer's
    # refresh just polls job status.
    if AuthManager.has_role(ROLE_OPERATOR):
        _drain_pending_queue(db_id)


def _drain_pending_queue(db_id):
    """Submit QUEUED items respecting each database's DOP budget (CPU_COUNT/2).

    Drains every database's queue, as before. Each item is claimed atomically
    (QUEUED -> IN_PROGRESS on its own row), so two tabs or admins draining at
    once can't submit the same item. Items that don't fit, or overlap a running
    job on the same segment, stay QUEUED in FIFO order; an item that can't be
    submitted ends FAILED with the reason on its row — nothing is dropped.
    """
    stats = TargetQueries.drain_compression_queue(None)
    for did in dict.fromkeys(stats['skipped_databases']):
        st.toast(f"Queue drain skipped db_id={did} (target unreachable or "
                 f"budget lookup failed); its items stay queued", icon="⚠️")
    if stats['failed']:
        st.toast(f"{stats['failed']} queued item(s) could not be submitted and were "
                 f"marked FAILED (see error_message)", icon="⚠️")
    if stats['submitted'] > 0:
        st.toast(f"Drained {stats['submitted']} from queue ({stats['waiting']} remaining)")
    for err in stats['errors']:
        log_warning(f"Scheduler drain: {err}")


def _render_reconcile_section(db_id):
    """Operator action: close IN_PROGRESS / RUNNING operations that no job or
    thread will ever finish (see TargetQueries.reconcile_operations)."""
    st.markdown(
        "Closes operations stuck in **IN_PROGRESS** / **RUNNING** that nothing "
        "will ever finish:\n"
        "- **Scheduler jobs** are looked up on the target: a finished job gets its "
        "real outcome (SUCCEEDED → SUCCESS, FAILED / STOPPED → FAILED, however old); "
        "a job the target no longer knows (dropped, or its log purged) is marked "
        f"FAILED once it is {TargetQueries.JOB_NOT_FOUND_GRACE_MINUTES} min old.\n"
        "- **Direct compressions** still open after "
        f"{TargetQueries.SYNC_STALE_HOURS} h, with no target session running the "
        "MOVE, are marked FAILED with *outcome unknown* (the app was restarted "
        "mid-MOVE) — check the segment before retrying.\n"
        "- **Analysis runs** still RUNNING after "
        f"{TargetQueries.ADVISOR_RUN_STALE_HOURS} h are marked FAILED.\n\n"
        "Operations this app is still running are never touched, and nothing is "
        "changed for a target that can't be reached. The same checks run on every "
        "refresh; this button runs them now and shows what changed."
    )
    allowed = AuthManager.has_role(ROLE_OPERATOR)
    scope = f"database ID={db_id}" if db_id else "all registered databases"
    clicked = st.button(f"Reconcile stale operations ({scope})", key="sched_reconcile_btn",
                        disabled=not allowed,
                        help=None if allowed else "Requires the operator role.")
    if clicked and AuthManager.require_role(ROLE_OPERATOR):
        if db_id:
            targets = [int(db_id)]
        else:
            dbs = CentralQueries.get_target_databases()
            targets = []
            if not dbs.empty:
                dbs.columns = [c.lower() for c in dbs.columns]
                targets = [int(d) for d in dbs['database_id'].dropna()]
        results = []
        with st.spinner(f"Reconciling {len(targets)} database(s)..."):
            for did in targets:
                try:
                    results.append(TargetQueries.reconcile_operations(did))
                except Exception as e:
                    log_warning(f"Scheduler: reconcile of db_id={did} failed: {e}")
                    results.append({'database_id': did, 'updated': [], 'running': 0,
                                    'pending': 0, 'advisor_runs_failed': 0,
                                    'errors': [str(e)]})
        st.session_state['sched_reconcile_result'] = {
            'at': datetime.now(), 'results': results,
        }
        st.rerun()  # refresh the metrics and job table above

    last = st.session_state.get('sched_reconcile_result')
    if not last:
        return
    results = last['results']
    updated = [dict(u, database_id=r['database_id']) for r in results for u in r['updated']]
    st.caption(f"Last reconcile: {last['at'].strftime('%H:%M:%S')} — "
               f"{len(results)} database(s)")
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Rows closed", len(updated))
    c2.metric("Still running", sum(r['running'] for r in results))
    c3.metric("Pending / waiting", sum(r['pending'] for r in results))
    c4.metric("Analysis runs failed", sum(r['advisor_runs_failed'] for r in results))
    if updated:
        st.dataframe(pd.DataFrame(updated)[
            ['database_id', 'history_id', 'object', 'job_name', 'status', 'reason']],
            use_container_width=True, hide_index=True)
    for r in results:
        for err in r['errors']:
            st.warning(f"db_id={r['database_id']}: {err}")
