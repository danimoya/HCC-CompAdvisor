"""
Index Manager - HCC Compression Advisor
Monitor invalid/unusable indexes and rebuild them via DBMS_SCHEDULER jobs
"""

import streamlit as st
import pandas as pd
import random
from datetime import datetime
from hcc_advisor.utils.target_queries import TargetQueries
from hcc_advisor.utils.target_connector import TargetConnector
from hcc_advisor.utils.central_connector import CentralConnector
from hcc_advisor.utils.logger import log_error


def show_indexes_page():
    st.title("Index Manager")
    st.markdown("Monitor and rebuild unusable/invalid indexes on the target database")
    st.markdown("---")

    db_id = st.session_state.get('active_database_id')
    if not db_id:
        st.warning("Select a target database from the sidebar.")
        return

    cpu_count = TargetQueries.get_cpu_count(db_id)
    max_dop = max(1, cpu_count // 2)

    col1, col2, col3, col4 = st.columns([2, 1, 1, 1])
    with col1:
        schemas = TargetQueries.get_available_schemas(db_id)
        schema = st.selectbox("Schema", ["All Schemas"] + schemas, key="idx_schema")
    with col2:
        show_valid = st.checkbox("Show valid indexes too", key="idx_show_valid")
    with col3:
        show_rebuilding = st.checkbox("Rebuilding only", key="idx_show_rebuilding")
    with col4:
        st.markdown("<br>", unsafe_allow_html=True)
        if st.button("Refresh", key="idx_refresh", use_container_width=True):
            _check_rebuild_jobs(db_id)
            st.session_state.pop('idx_submitted', None)
            st.rerun()

    schema_param = None if schema == "All Schemas" else schema

    # Get running IDXR_% jobs to mark rebuilding indexes
    rebuilding_set = set()
    running_jobs = _get_running_rebuild_jobs(db_id)
    if not running_jobs.empty:
        for _, rj in running_jobs.iterrows():
            # Extract index name from job_name: IDXR_<index_name>_<timestamp>
            jname = str(rj.get('job_name', ''))
            if jname.startswith('IDXR_'):
                parts = jname[5:].rsplit('_', 1)
                if parts:
                    rebuilding_set.add(parts[0])
    # Also check session_state for just-submitted jobs
    for idx_key in st.session_state.get('idx_submitted', []):
        rebuilding_set.add(idx_key)

    with st.spinner("Querying indexes on target..."):
        df = _get_indexes(db_id, schema_param, include_valid=show_valid)

    if df.empty:
        if show_valid:
            st.info("No indexes found for the selected schema.")
        else:
            st.success("No unusable or invalid indexes found.")
        return

    # Add rebuild_status column
    df['rebuild_status'] = df['index_name'].apply(
        lambda n: 'Rebuilding' if n in rebuilding_set else ''
    )

    # Filter to rebuilding only
    if show_rebuilding:
        df = df[df['rebuild_status'] == 'Rebuilding']
        if df.empty:
            st.info("No indexes currently rebuilding.")
            return

    # Summary
    total = len(df)
    unusable = len(df[df['status'] == 'UNUSABLE'])
    invalid = len(df[df['status'].isin(['INVALID', 'N/A'])])
    valid = len(df[df['status'] == 'VALID'])

    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric("Total Indexes", total)
    with col2:
        st.metric("Unusable", unusable, delta=f"-{unusable}" if unusable > 0 else None,
                   delta_color="inverse")
    with col3:
        st.metric("Invalid", invalid, delta=f"-{invalid}" if invalid > 0 else None,
                   delta_color="inverse")
    with col4:
        st.metric("Valid", valid)

    st.markdown("---")

    # Pagination
    ROWS_PER_PAGE = 100
    total_pages = max(1, (len(df) + ROWS_PER_PAGE - 1) // ROWS_PER_PAGE)
    if total_pages > 1:
        page = st.selectbox(
            f"Page (of {total_pages})", range(1, total_pages + 1), key="idx_page",
            format_func=lambda p: f"Page {p}  ({(p-1)*ROWS_PER_PAGE+1}-{min(p*ROWS_PER_PAGE, len(df))} of {len(df)})"
        )
    else:
        page = 1
    start = (page - 1) * ROWS_PER_PAGE
    page_df = df.iloc[start:start + ROWS_PER_PAGE].reset_index(drop=True)

    # Editable table
    show_df = page_df.copy()
    show_df.insert(0, 'select', False)
    show_df['dop'] = max_dop

    col_config = {
        'select': st.column_config.CheckboxColumn("Rebuild", default=False),
        'index_owner': st.column_config.TextColumn("Owner"),
        'index_name': st.column_config.TextColumn("Index"),
        'table_owner': st.column_config.TextColumn("Table Owner"),
        'table_name': st.column_config.TextColumn("Table"),
        'index_type': st.column_config.TextColumn("Type"),
        'status': st.column_config.TextColumn("Status"),
        'rebuild_status': st.column_config.TextColumn("Rebuild"),
        'size_mb': st.column_config.NumberColumn("Size (MB)", format="%.1f"),
        'partitioned': st.column_config.TextColumn("Partitioned"),
        'dop': st.column_config.NumberColumn("DOP", min_value=1, max_value=max_dop, step=1,
                                              help=f"Parallel degree (1-{max_dop})"),
    }

    edited = st.data_editor(
        show_df, column_config=col_config, use_container_width=True,
        hide_index=True,
        disabled=['index_owner', 'index_name', 'table_owner', 'table_name',
                  'index_type', 'status', 'rebuild_status', 'size_mb', 'partitioned'],
        key=f"idx_editor_{page}",
        height=min(35 * len(show_df) + 50, 800)
    )

    # Submit selected for rebuild
    selected = edited[edited['select'] == True]
    if len(selected) > 0:
        n = len(selected)
        st.info(f"{n} index(es) selected for rebuild")

        col1, col2, col3 = st.columns([1, 1, 2])
        with col1:
            confirm = st.checkbox("Confirm Rebuild", key="idx_confirm")
        with col2:
            if st.button(f"Submit {n} Rebuild Job(s)", disabled=not confirm,
                         type="primary", key="idx_submit", use_container_width=True):
                submitted = 0
                for _, row in selected.iterrows():
                    idx_owner = row['index_owner']
                    idx_name = row['index_name']
                    row_dop = int(row.get('dop', max_dop) or max_dop)

                    idx_partitioned = row.get('partitioned', 'NO')
                    result = _submit_rebuild_job(db_id, idx_owner, idx_name, row_dop,
                                                 partitioned=idx_partitioned)
                    if result.get('success'):
                        submitted += 1
                        # Track in session_state for immediate UI feedback
                        if 'idx_submitted' not in st.session_state:
                            st.session_state['idx_submitted'] = []
                        st.session_state['idx_submitted'].append(idx_name)
                        st.toast(f"Submitted: {idx_owner}.{idx_name} -> {result.get('job_name')}")
                    else:
                        st.error(f"Failed {idx_owner}.{idx_name}: {result.get('error')}")

                if submitted > 0:
                    st.success(f"{submitted} rebuild job(s) submitted to DBMS_SCHEDULER")
                    st.rerun()

    # Running rebuild jobs — always visible
    st.markdown("---")
    st.subheader("Rebuild Jobs")
    if not running_jobs.empty:
        st.dataframe(running_jobs, use_container_width=True, hide_index=True)
    else:
        submitted_list = st.session_state.get('idx_submitted', [])
        if submitted_list:
            st.info(f"Recently submitted: {', '.join(submitted_list)} — click Refresh to check status")
        else:
            st.caption("No rebuild jobs currently running.")


def _get_indexes(db_id: int, schema: str = None, include_valid: bool = False) -> pd.DataFrame:
    schema_filter = "AND i.owner = :schema" if schema else ""
    status_filter = "" if include_valid else "AND i.status != 'VALID'"
    params = {'schema': schema} if schema else {}

    query = f"""
        SELECT
            i.owner as index_owner,
            i.index_name,
            i.table_owner,
            i.table_name,
            i.index_type,
            i.status,
            ROUND(NVL(s.bytes, 0) / 1048576, 1) as size_mb,
            i.partitioned
        FROM all_indexes i
        LEFT JOIN dba_segments s
            ON s.owner = i.owner AND s.segment_name = i.index_name
            AND s.segment_type LIKE 'INDEX%'
        WHERE i.owner NOT IN (
            'SYS','SYSTEM','AUDSYS','OUTLN','DBSNMP','GSMADMIN_INTERNAL',
            'XDB','WMSYS','CTXSYS','MDSYS','ORDSYS','ORDDATA','OLAPSYS',
            'APPQOSSYS','DBSFWUSER','GGSYS','ANONYMOUS','APEX_PUBLIC_USER',
            'DIP','FLOWS_FILES','MDDATA','ORACLE_OCM'
        )
        AND i.owner NOT LIKE 'APEX_%'
        AND i.owner NOT LIKE 'ORACLE%'
        {schema_filter}
        {status_filter}
        ORDER BY DECODE(i.status, 'UNUSABLE', 1, 'INVALID', 2, 'N/A', 3, 4),
                 NVL(s.bytes, 0) DESC
    """
    try:
        df = TargetConnector.execute_query(db_id, query, params if params else None)
        if not df.empty:
            df.columns = [c.lower() for c in df.columns]
        return df
    except Exception as e:
        log_error(e, "_get_indexes")
        return pd.DataFrame()


def _submit_rebuild_job(db_id: int, index_owner: str, index_name: str,
                        dop: int = 4, partitioned: str = 'NO') -> dict:
    ts = datetime.now().strftime('%m%d%H%M%S') + f"{random.randint(0,999):03d}"
    job_name = f"IDXR_{index_name[:25]}_{ts}"

    if partitioned == 'YES':
        # Partitioned index: must rebuild each partition individually (ORA-14086)
        action = f"""
            BEGIN
                FOR p IN (SELECT partition_name FROM all_ind_partitions
                          WHERE index_owner = '{index_owner}' AND index_name = '{index_name}'
                            AND status = 'UNUSABLE')
                LOOP
                    EXECUTE IMMEDIATE 'ALTER INDEX {index_owner}.{index_name} REBUILD PARTITION '
                                      || p.partition_name || ' ONLINE PARALLEL {dop}';
                END LOOP;
                FOR sp IN (SELECT partition_name, subpartition_name FROM all_ind_subpartitions
                           WHERE index_owner = '{index_owner}' AND index_name = '{index_name}'
                             AND status = 'UNUSABLE')
                LOOP
                    EXECUTE IMMEDIATE 'ALTER INDEX {index_owner}.{index_name} REBUILD SUBPARTITION '
                                      || sp.subpartition_name || ' ONLINE PARALLEL {dop}';
                END LOOP;
                EXECUTE IMMEDIATE 'ALTER INDEX {index_owner}.{index_name} NOPARALLEL';
            END;
        """
    else:
        action = f"""
            BEGIN
                EXECUTE IMMEDIATE 'ALTER INDEX {index_owner}.{index_name} REBUILD ONLINE PARALLEL {dop}';
                EXECUTE IMMEDIATE 'ALTER INDEX {index_owner}.{index_name} NOPARALLEL';
            END;
        """

    create_job = f"""
        BEGIN
            DBMS_SCHEDULER.CREATE_JOB(
                job_name   => '{job_name}',
                job_type   => 'PLSQL_BLOCK',
                job_action => q'[{action}]',
                enabled    => TRUE,
                auto_drop  => TRUE,
                comments   => 'HCC Advisor: rebuild {index_owner}.{index_name}'
            );
        END;
    """

    try:
        ok = TargetConnector.execute_plsql(db_id, create_job)
        if ok:
            return {'success': True, 'job_name': job_name}
        return {'success': False, 'error': 'DBMS_SCHEDULER.CREATE_JOB returned failure'}
    except Exception as e:
        log_error(e, "_submit_rebuild_job")
        return {'success': False, 'error': str(e)}


def _get_running_rebuild_jobs(db_id: int) -> pd.DataFrame:
    query = """
        SELECT r.job_name,
               EXTRACT(HOUR FROM r.elapsed_time)*3600 +
               EXTRACT(MINUTE FROM r.elapsed_time)*60 +
               EXTRACT(SECOND FROM r.elapsed_time) as elapsed_seconds,
               r.session_id
        FROM dba_scheduler_running_jobs r
        WHERE r.job_name LIKE 'IDXR_%'
        ORDER BY r.job_name DESC
    """
    try:
        df = TargetConnector.execute_query(db_id, query)
        if not df.empty:
            df.columns = [c.lower() for c in df.columns]
        return df
    except Exception:
        return pd.DataFrame()


def _check_rebuild_jobs(db_id: int):
    """Check for completed IDXR_% jobs in scheduler history."""
    query = """
        SELECT job_name, status,
               TO_CHAR(actual_start_date, 'YYYY-MM-DD HH24:MI:SS') as start_time,
               SUBSTR(additional_info, 1, 500) as info
        FROM dba_scheduler_job_run_details
        WHERE job_name LIKE 'IDXR_%'
          AND actual_start_date > SYSDATE - 1
        ORDER BY actual_start_date DESC
        FETCH FIRST 20 ROWS ONLY
    """
    try:
        df = TargetConnector.execute_query(db_id, query)
        if not df.empty:
            df.columns = [c.lower() for c in df.columns]
            succeeded = len(df[df['status'] == 'SUCCEEDED'])
            failed = len(df[df['status'] == 'FAILED'])
            if succeeded > 0 or failed > 0:
                st.toast(f"Rebuild jobs: {succeeded} succeeded, {failed} failed (last 24h)")
    except Exception:
        pass
