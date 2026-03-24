"""
Tablespace Manager - HCC Compression Advisor
Analyze tablespace usage and shrink allocated space after compression
"""

import streamlit as st
import pandas as pd
import plotly.graph_objects as go
from hcc_advisor.utils.target_queries import TargetQueries
from hcc_advisor.utils.target_connector import TargetConnector


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

    targets = st.session_state.get('ts_shrink_targets', [])
    if targets:
        col1, col2, col3 = st.columns([1, 1, 1])
        with col1:
            confirm = st.checkbox("Confirm Shrink", key="ts_confirm")
        with col2:
            if st.button("Execute Shrink", disabled=not confirm, type="primary",
                         key="ts_execute", use_container_width=True):
                for ts_name in targets:
                    with st.spinner(f"Shrinking {ts_name}..."):
                        result = _shrink_tablespace(db_id, ts_name)
                        if result.get('success'):
                            st.success(f"{ts_name}: {result['message']}")
                        else:
                            st.error(f"{ts_name}: {result.get('error', 'Failed')}")
                st.session_state.pop('ts_shrink_targets', None)
                st.rerun()

    # Datafile details
    st.markdown("---")
    with st.expander("Datafile Details"):
        df_files = _get_datafile_details(db_id)
        if not df_files.empty:
            st.dataframe(df_files, use_container_width=True, hide_index=True)


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
        df = TargetConnector.execute_query(db_id, query)
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


def _shrink_tablespace(db_id: int, tablespace_name: str) -> dict:
    """Shrink all datafiles in a tablespace using ALTER TABLESPACE SHRINK SPACE.
    Falls back to per-datafile ALTER DATABASE DATAFILE SHRINK for older Oracle versions."""

    # Get size before shrink
    before_df = TargetConnector.execute_query(db_id,
        "SELECT SUM(bytes)/1048576 as total_mb FROM dba_data_files WHERE tablespace_name = :ts",
        {'ts': tablespace_name})
    before_mb = float(before_df.iloc[0]['TOTAL_MB']) if not before_df.empty else 0

    try:
        # Try ALTER TABLESPACE SHRINK SPACE (Oracle 21c+, simplest)
        ok = TargetConnector.execute_plsql(
            db_id,
            f"BEGIN EXECUTE IMMEDIATE 'ALTER TABLESPACE {tablespace_name} SHRINK SPACE'; END;"
        )
        if ok:
            after_df = TargetConnector.execute_query(db_id,
                "SELECT SUM(bytes)/1048576 as total_mb FROM dba_data_files WHERE tablespace_name = :ts",
                {'ts': tablespace_name})
            after_mb = float(after_df.iloc[0]['TOTAL_MB']) if not after_df.empty else before_mb
            saved = before_mb - after_mb
            return {'success': True, 'message': f'Tablespace shrunk, {saved:.0f} MB reclaimed'}
    except Exception:
        pass

    # Fallback: per-datafile ALTER DATABASE DATAFILE ... SHRINK (Oracle 12c+)
    try:
        files_df = TargetConnector.execute_query(db_id,
            "SELECT file_name FROM dba_data_files WHERE tablespace_name = :ts",
            {'ts': tablespace_name})
        if files_df.empty:
            return {'success': False, 'error': 'No datafiles found'}

        shrunk = 0
        for _, row in files_df.iterrows():
            fname = row['FILE_NAME']
            try:
                TargetConnector.execute_plsql(
                    db_id,
                    f"BEGIN EXECUTE IMMEDIATE 'ALTER DATABASE DATAFILE ''{fname}'' SHRINK'; END;"
                )
                shrunk += 1
            except Exception:
                pass  # Some files may not be shrinkable

        after_df = TargetConnector.execute_query(db_id,
            "SELECT SUM(bytes)/1048576 as total_mb FROM dba_data_files WHERE tablespace_name = :ts",
            {'ts': tablespace_name})
        after_mb = float(after_df.iloc[0]['TOTAL_MB']) if not after_df.empty else before_mb
        saved = before_mb - after_mb

        if shrunk > 0:
            return {'success': True, 'message': f'{shrunk} file(s) shrunk, {saved:.0f} MB reclaimed'}
        return {'success': True, 'message': 'No files could be shrunk'}

    except Exception as e:
        return {'success': False, 'error': str(e)}
