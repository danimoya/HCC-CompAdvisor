"""
Tablespace Manager - HCC Compression Advisor
Analyze tablespace usage and shrink allocated space after compression
"""

import numbers
from typing import Any, Collection, Dict, Tuple

import streamlit as st
import pandas as pd
import plotly.graph_objects as go
from hcc_advisor.utils.target_queries import TargetQueries
from hcc_advisor.utils.target_connector import TargetConnector


# Resize one datafile. The file name and size are binds concatenated inside the
# PL/SQL block, not text interpolated into the DDL: the name becomes a normal
# quoted literal (embedded quotes doubled), the size a plain number.
_RESIZE_DATAFILE_PLSQL = """
    BEGIN
        EXECUTE IMMEDIATE 'ALTER DATABASE DATAFILE '''
            || REPLACE(:file_name, '''', '''''')
            || ''' RESIZE ' || TO_CHAR(:target_mb) || 'M';
    END;
"""


def show_tablespaces_page():
    st.title("Tablespace Manager")
    st.markdown("Reclaim wasted space from tablespaces after compression")
    st.markdown("---")

    db_id = st.session_state.get('active_database_id')
    if not db_id:
        st.warning("Select a target database from the sidebar.")
        return

    col1, col2 = st.columns([3, 1])
    with col2:
        if st.button("Refresh", key="ts_refresh", use_container_width=True):
            st.rerun()

    with st.spinner("Querying tablespace usage on target..."):
        df = _get_tablespace_usage(db_id)

    if df.empty:
        st.info("No tablespace data returned.")
        return

    # Summary metrics
    total_alloc = df['allocated_mb'].sum()
    total_used = df['used_mb'].sum()
    total_free = df['free_mb'].sum()
    total_shrinkable = df['shrinkable_mb'].sum()

    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric("Allocated", f"{total_alloc / 1024:.2f} GB")
    with col2:
        st.metric("Used", f"{total_used / 1024:.2f} GB")
    with col3:
        st.metric("Free (within files)", f"{total_free / 1024:.2f} GB")
    with col4:
        st.metric("Shrinkable", f"{total_shrinkable / 1024:.2f} GB",
                   delta=f"{total_shrinkable / 1024:.2f} GB reclaimable" if total_shrinkable > 100 else None)

    st.markdown("---")

    # Stacked bar chart — used vs free vs shrinkable
    fig = go.Figure()
    fig.add_trace(go.Bar(
        name='Used', x=df['tablespace_name'], y=df['used_mb'],
        marker_color='#1f77b4', text=df['used_mb'].apply(lambda x: f"{x:.0f}"),
        textposition='auto'
    ))
    fig.add_trace(go.Bar(
        name='Free (in-file)', x=df['tablespace_name'], y=df['free_mb'],
        marker_color='#aec7e8'
    ))
    fig.add_trace(go.Bar(
        name='Shrinkable', x=df['tablespace_name'], y=df['shrinkable_mb'],
        marker_color='#28a745',
        text=df['shrinkable_mb'].apply(lambda x: f"{x:.0f}" if x > 10 else ""),
        textposition='auto'
    ))
    fig.update_layout(
        barmode='stack', height=400, yaxis_title="MB",
        legend=dict(orientation='h', y=-0.15),
        margin=dict(t=20, b=20)
    )
    st.plotly_chart(fig, use_container_width=True)

    st.markdown("---")

    # Detail table with shrink actions
    st.subheader("Tablespace Details")

    show_df = df[['tablespace_name', 'allocated_mb', 'used_mb', 'free_mb',
                   'used_pct', 'shrinkable_mb', 'can_shrink']].copy()
    show_df.insert(0, 'select', False)

    col_config = {
        'select': st.column_config.CheckboxColumn("Shrink", default=False),
        'tablespace_name': st.column_config.TextColumn("Tablespace"),
        'allocated_mb': st.column_config.NumberColumn("Allocated (MB)", format="%.1f"),
        'used_mb': st.column_config.NumberColumn("Used (MB)", format="%.1f"),
        'free_mb': st.column_config.NumberColumn("Free (MB)", format="%.1f"),
        'used_pct': st.column_config.ProgressColumn("Used %", min_value=0, max_value=100, format="%.1f%%"),
        'shrinkable_mb': st.column_config.NumberColumn("Shrinkable (MB)", format="%.1f"),
        'can_shrink': st.column_config.TextColumn("Shrinkable?"),
    }

    edited = st.data_editor(
        show_df, column_config=col_config, use_container_width=True,
        hide_index=True, disabled=[c for c in show_df.columns if c != 'select'],
        key="ts_editor", height=min(35 * len(show_df) + 50, 600)
    )

    # Shrink action
    selected = edited[edited['select'] == True]
    if len(selected) > 0:
        shrinkable = selected[selected['can_shrink'] == 'YES']
        if len(shrinkable) == 0:
            st.warning("Selected tablespaces cannot be shrunk (no reclaimable space or bigfile restrictions).")
        else:
            total_reclaim = shrinkable['shrinkable_mb'].sum()
            ts_names = shrinkable['tablespace_name'].tolist()
            st.info(f"Ready to shrink {len(shrinkable)} tablespace(s): **{', '.join(ts_names)}** — ~{total_reclaim:.0f} MB reclaimable")

            # Store selection in session_state so it survives the confirm checkbox rerun
            st.session_state['ts_shrink_targets'] = ts_names

    # Results of the last Execute Shrink, stashed because the handler reruns the
    # page (to refresh the usage figures), which would otherwise wipe them.
    for ts_name, result in st.session_state.pop('ts_shrink_results', None) or []:
        _show_shrink_result(ts_name, result)

    targets = st.session_state.get('ts_shrink_targets', [])
    if targets:
        col1, col2, col3 = st.columns([1, 1, 1])
        with col1:
            confirm = st.checkbox("Confirm Shrink", key="ts_confirm")
        with col2:
            if st.button("Execute Shrink", disabled=not confirm, type="primary",
                         key="ts_execute", use_container_width=True):
                results = []
                for ts_name in targets:
                    with st.spinner(f"Shrinking {ts_name}..."):
                        results.append((ts_name, _shrink_tablespace(db_id, ts_name)))
                st.session_state['ts_shrink_results'] = results
                st.session_state.pop('ts_shrink_targets', None)
                st.rerun()

    # Datafile details
    st.markdown("---")
    with st.expander("Datafile Details"):
        df_files = _get_datafile_details(db_id)
        if not df_files.empty:
            st.dataframe(df_files, use_container_width=True, hide_index=True)


def _show_shrink_result(ts_name: str, result: dict):
    """Render one tablespace's shrink outcome with its per-file results."""
    text = f"{ts_name}: {result['message']}"
    if result['level'] == 'success':
        st.success(text)
    elif result['level'] == 'warning':
        st.warning(text)
    else:
        st.error(text)
    if result.get('files'):
        with st.expander(f"{ts_name}: per-file results", expanded=result['level'] != 'success'):
            st.dataframe(pd.DataFrame(result['files']), use_container_width=True, hide_index=True)


def _get_tablespace_usage(db_id: int) -> pd.DataFrame:
    query = """
        SELECT
            t.tablespace_name,
            ROUND(t.allocated_mb, 1) as allocated_mb,
            ROUND(t.allocated_mb - NVL(f.free_mb, 0), 1) as used_mb,
            ROUND(NVL(f.free_mb, 0), 1) as free_mb,
            ROUND((t.allocated_mb - NVL(f.free_mb, 0)) / NULLIF(t.allocated_mb, 0) * 100, 1) as used_pct,
            ROUND(GREATEST(t.allocated_mb - NVL(hwm.hwm_mb, t.allocated_mb) - 1, 0), 1) as shrinkable_mb,
            CASE WHEN t.allocated_mb - NVL(hwm.hwm_mb, t.allocated_mb) > 1 THEN 'YES' ELSE 'NO' END as can_shrink
        FROM (
            SELECT tablespace_name, SUM(bytes) / 1048576 as allocated_mb
            FROM dba_data_files GROUP BY tablespace_name
        ) t
        LEFT JOIN (
            SELECT tablespace_name, SUM(bytes) / 1048576 as free_mb
            FROM dba_free_space GROUP BY tablespace_name
        ) f ON f.tablespace_name = t.tablespace_name
        LEFT JOIN (
            SELECT e.tablespace_name,
                   SUM((e.max_block + 1) * ts.block_size) / 1048576 as hwm_mb
            FROM (
                SELECT tablespace_name, file_id,
                       MAX(block_id + blocks) as max_block
                FROM dba_extents
                GROUP BY tablespace_name, file_id
            ) e
            JOIN dba_tablespaces ts ON ts.tablespace_name = e.tablespace_name
            GROUP BY e.tablespace_name, ts.block_size
        ) hwm ON hwm.tablespace_name = t.tablespace_name
        ORDER BY t.allocated_mb DESC
    """
    try:
        # Strict mode so a failure here reaches the fallback below instead of
        # returning an empty DataFrame
        df = TargetConnector.execute_query(db_id, query, raise_on_error=True)
        if not df.empty:
            df.columns = [c.lower() for c in df.columns]
        return df
    except Exception:
        # Simpler fallback without HWM
        fallback = """
            SELECT t.tablespace_name,
                   ROUND(t.allocated_mb, 1) as allocated_mb,
                   ROUND(t.allocated_mb - NVL(f.free_mb, 0), 1) as used_mb,
                   ROUND(NVL(f.free_mb, 0), 1) as free_mb,
                   ROUND((t.allocated_mb - NVL(f.free_mb, 0)) / NULLIF(t.allocated_mb, 0) * 100, 1) as used_pct,
                   ROUND(NVL(f.free_mb, 0), 1) as shrinkable_mb,
                   CASE WHEN NVL(f.free_mb, 0) > 10 THEN 'YES' ELSE 'NO' END as can_shrink
            FROM (SELECT tablespace_name, SUM(bytes)/1048576 as allocated_mb
                  FROM dba_data_files GROUP BY tablespace_name) t
            LEFT JOIN (SELECT tablespace_name, SUM(bytes)/1048576 as free_mb
                       FROM dba_free_space GROUP BY tablespace_name) f
                ON f.tablespace_name = t.tablespace_name
            ORDER BY t.allocated_mb DESC
        """
        try:
            df = TargetConnector.execute_query(db_id, fallback)
            if not df.empty:
                df.columns = [c.lower() for c in df.columns]
            return df
        except Exception:
            return pd.DataFrame()


def _get_datafile_details(db_id: int) -> pd.DataFrame:
    query = """
        SELECT f.tablespace_name,
               f.file_name,
               ROUND(f.bytes / 1048576, 1) as size_mb,
               f.autoextensible as auto_ext,
               ROUND(NVL(fr.free_mb, 0), 1) as free_mb
        FROM dba_data_files f
        LEFT JOIN (
            SELECT file_id, SUM(bytes) / 1048576 as free_mb
            FROM dba_free_space GROUP BY file_id
        ) fr ON fr.file_id = f.file_id
        ORDER BY f.tablespace_name, f.file_name
    """
    try:
        df = TargetConnector.execute_query(db_id, query)
        if not df.empty:
            df.columns = [c.lower() for c in df.columns]
        return df
    except Exception:
        return pd.DataFrame()


def _build_datafile_resize(file_name: Any, target_mb: Any,
                           known_files: Collection[str]) -> Tuple[str, Dict[str, Any]]:
    """
    Validate one datafile resize and return (plsql_block, binds) for execute_plsql.

    Args:
        file_name: Datafile to resize; must be one of known_files
        target_mb: New size in MB; must be a positive whole number
        known_files: FILE_NAME values just read from DBA_DATA_FILES

    Raises:
        ValueError: if file_name or target_mb is not acceptable
    """
    if not isinstance(file_name, str) or file_name not in known_files:
        raise ValueError(f"{file_name!r} is not a datafile of this tablespace")
    if isinstance(target_mb, bool) or not isinstance(target_mb, numbers.Integral) or target_mb <= 0:
        raise ValueError(f"invalid resize target {target_mb!r} MB")
    return _RESIZE_DATAFILE_PLSQL, {'file_name': file_name, 'target_mb': int(target_mb)}


def _shrink_tablespace(db_id: int, tablespace_name: str) -> dict:
    """Shrink datafiles in a permanent tablespace by resizing each file
    down to its high-water mark + a small buffer.

    For permanent tablespaces ALTER TABLESPACE SHRINK SPACE is not supported
    (ORA-12916). The correct approach is per-datafile ALTER DATABASE DATAFILE RESIZE.

    Returns:
        dict: {'level': 'success' | 'warning' | 'error', 'message': str,
               'files': [{'File', 'Result', 'Detail'}, ...]}
    """

    # Get datafiles with their HWM
    query = """
        SELECT f.file_id, f.file_name,
               f.bytes as current_bytes,
               NVL(hwm.hwm_bytes, 0) as hwm_bytes
        FROM dba_data_files f
        LEFT JOIN (
            SELECT e.file_id,
                   (MAX(e.block_id + e.blocks)) * ts.block_size as hwm_bytes
            FROM dba_extents e
            JOIN dba_tablespaces ts ON ts.tablespace_name = e.tablespace_name
            WHERE e.tablespace_name = :ts
            GROUP BY e.file_id, ts.block_size
        ) hwm ON hwm.file_id = f.file_id
        WHERE f.tablespace_name = :ts
    """
    try:
        df = TargetConnector.execute_query(db_id, query, {'ts': tablespace_name}, raise_on_error=True)
    except Exception as e:
        return {'level': 'error', 'message': f'Failed to query datafiles: {e}', 'files': []}

    if df.empty:
        return {'level': 'error', 'message': 'No datafiles found', 'files': []}

    # Only files this query just read from DBA_DATA_FILES may be resized
    known_files = set(df['FILE_NAME'])
    files = []
    resized = skipped = failed = 0
    total_saved = 0

    for _, row in df.iterrows():
        current = int(row['CURRENT_BYTES'])
        hwm = int(row['HWM_BYTES'])
        # Target = HWM + 10MB buffer, rounded up to next MB
        target = hwm + 10 * 1048576
        if target >= current - 1048576:
            continue  # Not enough to reclaim

        file_name = row['FILE_NAME']
        target_mb = (target // 1048576) + 1

        try:
            plsql, binds = _build_datafile_resize(file_name, target_mb, known_files)
        except ValueError as e:
            failed += 1
            files.append({'File': str(file_name), 'Result': 'Failed', 'Detail': f'Rejected: {e}'})
            continue

        try:
            # Strict mode: a failed RESIZE raises instead of returning False,
            # so it is never counted as shrunk.
            TargetConnector.execute_plsql(db_id, plsql, binds, raise_on_error=True)
        except Exception as e:
            err_str = str(e)
            if 'ORA-03297' in err_str:
                # Expected when used extents sit above the computed target size
                skipped += 1
                files.append({'File': file_name, 'Result': 'Skipped',
                              'Detail': f'Used data beyond {target_mb} MB (ORA-03297)'})
            else:
                failed += 1
                files.append({'File': file_name, 'Result': 'Failed', 'Detail': err_str[:300]})
            continue

        saved = max((current - target_mb * 1048576) // 1048576, 0)
        total_saved += saved
        resized += 1
        files.append({'File': file_name, 'Result': 'Resized',
                      'Detail': f'{current // 1048576} MB -> {target_mb} MB (~{saved} MB reclaimed)'})

    if not files:
        return {'level': 'success', 'message': 'No files needed resizing', 'files': []}

    parts = [f'{resized} file(s) resized, ~{total_saved} MB reclaimed']
    if skipped:
        parts.append(f'{skipped} skipped (used data beyond the target size)')
    if failed:
        parts.append(f'{failed} failed')
        level = 'warning' if resized else 'error'
    else:
        level = 'success' if resized else 'warning'
    return {'level': level, 'message': '; '.join(parts), 'files': files}
