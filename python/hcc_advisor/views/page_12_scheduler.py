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
    canonical_compression,
)
from hcc_advisor.utils.sql_builder import (
    build_compression_script,
    build_compression_manifest,
    gather_dependent_indexes,
)
from hcc_advisor.utils.logger import log_warning


def show_scheduler_page():
    st.title("Scheduler")
    st.markdown("Monitor compression and rebuild jobs across databases")
    st.markdown("---")

    db_id = st.session_state.get('active_database_id')

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

    # Auto-refresh logic: runs _do_refresh immediately on the current render
    # and schedules the next page load via an HTML meta-refresh tag — this
    # keeps every control on the page (Stop, interval selector, filters)
    # responsive during the wait, unlike time.sleep which blocks the thread.
    if st.session_state.scheduler_auto_refresh:
        _do_refresh(db_id)
        st.session_state['scheduler_last_refresh'] = datetime.now()

        last = st.session_state['scheduler_last_refresh']
        next_at = last + timedelta(minutes=interval)
        st.caption(
            f"Last refresh: **{last.strftime('%H:%M:%S')}** — "
            f"Next at **{next_at.strftime('%H:%M:%S')}** (every {interval} min) — "
            f"click Stop to disable"
        )

        # Browser-side auto-reload; never blocks Python rendering.
        st.markdown(
            f'<meta http-equiv="refresh" content="{int(interval * 60)}">',
            unsafe_allow_html=True,
        )


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
                    'compression_type_applied', 'parallel_degree', 'operation_status']
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
            help="Adds ALTER INDEX ... REBUILD for all indexes that would become UNUSABLE after MOVE"
        )

        # Build SQL script (with index rebuild DDL if requested)
        with st.spinner("Generating SQL script..."):
            index_map = gather_dependent_indexes(df) if include_indexes else {}
            sql_script = build_compression_script(df, selected_status_label, selected_db, index_map)

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
        rows = []
        verified = []
        for obj, chk in zip(objects, checks):
            planned = obj['compression_type']
            current = chk.get('current_compress_for') or chk.get('current_compression') or 'NONE'
            level = chk['object_level']
            if not chk['exists']:
                state = 'MISSING'
            elif not is_supported_compression_type(planned):
                # Unsupported clause would raise in generate_ddl during drain and
                # crash the page — never queue it.
                state = 'UNSUPPORTED COMPRESSION'
            elif canonical_compression(current) == canonical_compression(planned):
                # Oracle reports OLTP as compress_for='ADVANCED'; normalize both
                # sides so an already-compressed object isn't needlessly re-moved.
                state = 'ALREADY AT TARGET'
            elif level == 'SUBPARTITION':
                # Job submission operates at table/partition granularity only.
                state = 'EXISTS (subpartition — queue manually)'
            else:
                state = 'READY'
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

        verified = st.session_state.get('import_verified_objects', [])
        if verified:
            label = st.session_state.get('import_target_label', target_label)
            if st.button(f"Add {len(verified)} verified object(s) to scheduler queue",
                         key="import_add_queue_btn", type="primary",
                         use_container_width=True):
                # Merge with the full persistent queue across ALL databases so
                # saving doesn't drop QUEUED rows for databases not loaded into
                # this session (the persist step deletes-then-reinserts).
                full_queue = _load_persistent_queue(None)
                seen = {(q['database_id'], q['owner'], q['table_name'], q.get('partition_name'))
                        for q in full_queue}
                added = 0
                for v in verified:
                    k = (v['database_id'], v['owner'], v['table_name'], v.get('partition_name'))
                    if k not in seen:
                        full_queue.append(v)
                        seen.add(k)
                        added += 1
                st.session_state.scheduler_pending_queue = full_queue
                _save_persistent_queue(full_queue)
                st.session_state.pop('import_verify_rows', None)
                st.session_state.pop('import_verified_objects', None)
                st.success(
                    f"Queued {added} verified object(s) for {label}"
                    + (f" ({len(verified) - added} already queued)" if added < len(verified) else "")
                    + ". They appear above as QUEUED and submit as capacity frees up."
                )
                st.rerun()
        else:
            st.info("No objects are in a READY state to queue (all are missing, "
                    "already at the target compression, subpartition-level, or "
                    "carry an unsupported compression type).")


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
        poll_failures = []
        try:
            dbs = CentralQueries.get_target_databases()
            if not dbs.empty:
                dbs.columns = [c.lower() for c in dbs.columns]
                for _, db in dbs.iterrows():
                    did = db.get('database_id')
                    if did:
                        try:
                            TargetQueries.check_completed_jobs(int(did))
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
    # Drain pending queue (handles per-database grouping internally)
    _drain_pending_queue(db_id)


def _drain_pending_queue(db_id):
    """Submit pending items respecting per-database DOP budget (CPU_COUNT/2).
    Total DOP of running jobs + new job DOP must not exceed the budget.

    Operates on the FULL cross-database queue (reloaded from the central DB)
    rather than the per-session subset. _save_persistent_queue rewrites ALL
    QUEUED rows, so draining a partial (single-DB) view here would silently
    delete other databases' queued work. Reloading the complete set keeps the
    delete-then-reinsert persistence faithful regardless of the active DB.
    """
    queue = _load_persistent_queue(None)
    if not queue:
        st.session_state.scheduler_pending_queue = []
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
            except Exception as e:
                log_warning(
                    f"Scheduler: DOP-budget lookup for db_id={did} failed, "
                    f"queue drain will skip this database: {e}"
                )
                st.toast(
                    f"Queue drain skipped db_id={did} (budget lookup failed)",
                    icon="⚠️",
                )
                db_dop_remaining[did] = 0

        for item in items:
            item_dop = int(item.get('dop', 4) or 4)
            if db_dop_remaining.get(did, 0) >= item_dop:
                # Guard against a single bad queue item (e.g. an unsupported
                # compression_type raising in generate_ddl) crashing the whole
                # page render and aborting the save below.
                try:
                    result = TargetQueries.submit_compression_job(
                        did, item['owner'], item['table_name'],
                        item['compression_type'],
                        partition_name=item.get('partition_name'),
                        parallel_degree=item_dop
                    )
                except Exception as e:
                    log_warning(
                        f"Scheduler: submit failed for "
                        f"{item.get('owner')}.{item.get('table_name')}: {e}"
                    )
                    st.toast(
                        f"Skipped {item.get('owner')}.{item.get('table_name')}: {e}",
                        icon="⚠️",
                    )
                    result = {'success': False, 'error': str(e)}
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
    """Load QUEUED items from t_compression_history that haven't been submitted yet.

    Called at page init; stays silent on failure because the table may not
    yet exist on a fresh deployment (schema not deployed). Errors here are
    expected in that case, not drain-time bugs.
    """
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

    Replaces all existing QUEUED rows atomically: the DELETE and every INSERT
    run on a single connection inside one transaction, committed once at the
    end (rolled back on error). The previous per-statement auto-commit could
    durably delete the queue and then fail mid-reinsert, losing it entirely.
    Callers must pass the COMPLETE cross-database queue (the DELETE is global).
    """
    from hcc_advisor.utils.central_connector import CentralConnector
    rows = [{
        'db': item['database_id'], 'owner': item['owner'],
        'tbl': item['table_name'],
        'otype': 'PARTITION' if item.get('partition_name') else 'TABLE',
        'part': item.get('partition_name'),
        'comp': item['compression_type'],
        'dop': item.get('dop', 4),
    } for item in queue]
    try:
        with CentralConnector.get_connection() as conn:
            cur = conn.cursor()
            try:
                cur.execute(
                    "DELETE FROM t_compression_history WHERE operation_status = 'QUEUED'"
                )
                if rows:
                    cur.executemany("""
                        INSERT INTO t_compression_history (
                            database_id, owner, object_name, object_type,
                            partition_name, compression_type_applied,
                            parallel_degree, operation_status, start_time, executed_by
                        ) VALUES (
                            :db, :owner, :tbl, :otype, :part, :comp,
                            :dop, 'QUEUED', SYSTIMESTAMP, 'HCC_ADVISOR'
                        )
                    """, rows)
                conn.commit()
            except Exception:
                conn.rollback()
                raise
            finally:
                cur.close()
    except Exception as e:
        log_warning(f"Scheduler: persisting pending queue failed, items may be lost on restart: {e}")
        st.toast(
            "Queue persistence failed — items may be lost on restart. Check logs.",
            icon="⚠️",
        )
