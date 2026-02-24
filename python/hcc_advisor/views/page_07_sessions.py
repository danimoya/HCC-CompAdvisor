"""
Session Browser Page - HCC Compression Advisor
Monitor active compression sessions and long-running operations
"""

import streamlit as st
import pandas as pd
import plotly.graph_objects as go
from datetime import datetime
from hcc_advisor.utils.target_queries import TargetQueries
from hcc_advisor.config import config


def show_sessions_page():
    """Display session browser page"""

    db_id = st.session_state.get('active_database_id')
    if not db_id:
        st.warning("Select a target database from the sidebar to monitor sessions.")
        st.info("Session monitoring requires a specific target database connection (V$ views are per-database).")
        return

    st.title("Session Browser")
    st.markdown("Monitor active compression sessions and long-running operations")
    st.markdown("---")

    # Auto-refresh toggle
    col1, col2, col3 = st.columns([1, 1, 2])

    with col1:
        auto_refresh = st.checkbox("Auto-refresh", value=False, key="session_auto_refresh")

    with col2:
        if auto_refresh:
            refresh_interval = st.selectbox(
                "Interval",
                options=[5, 10, 30, 60],
                format_func=lambda x: f"{x} seconds",
                key="session_refresh_interval"
            )
        else:
            refresh_interval = 30

    with col3:
        if st.button("🔄 Refresh Now", use_container_width=True):
            st.rerun()

    if auto_refresh:
        st.caption(f"Auto-refreshing every {refresh_interval} seconds...")
        import time
        time.sleep(0.1)  # Small delay to ensure page renders
        st.rerun()

    # Create tabs
    tab1, tab2, tab3 = st.tabs([
        "Long Operations",
        "Active Compression Sessions",
        "All Active Sessions"
    ])

    with tab1:
        show_long_operations()

    with tab2:
        show_compression_sessions()

    with tab3:
        show_all_active_sessions()


def show_long_operations():
    """Display V$SESSION_LONGOPS for compression-related operations"""

    st.subheader("Long-Running Operations")
    st.caption("Operations from V$SESSION_LONGOPS related to compression activities")

    # Filter options
    col1, col2 = st.columns(2)
    with col1:
        filter_compression = st.checkbox(
            "Show only compression-related operations",
            value=True,
            key="longops_filter"
        )

    # Fetch data
    with st.spinner("Loading long operations..."):
        if filter_compression:
            longops_df = TargetQueries.get_session_longops(db_id, filter_compression=True)
        else:
            longops_df = TargetQueries.get_all_active_longops(db_id)

    if longops_df.empty:
        st.success("No long-running operations in progress")
        return

    longops_df.columns = [c.lower() for c in longops_df.columns]

    # Summary metrics
    col1, col2, col3, col4 = st.columns(4)

    with col1:
        st.metric("Active Operations", len(longops_df))

    with col2:
        if 'pct_complete' in longops_df.columns:
            avg_progress = longops_df['pct_complete'].mean()
            st.metric("Avg Progress", f"{avg_progress:.1f}%")

    with col3:
        if 'elapsed_seconds' in longops_df.columns:
            total_elapsed = longops_df['elapsed_seconds'].sum()
            st.metric("Total Elapsed", format_duration(total_elapsed))

    with col4:
        if 'time_remaining_sec' in longops_df.columns:
            max_remaining = longops_df['time_remaining_sec'].max()
            st.metric("Max Remaining", format_duration(max_remaining) if pd.notna(max_remaining) else "N/A")

    st.markdown("---")

    # Display each operation as a card with progress
    for _, op in longops_df.iterrows():
        show_operation_card(op)

    # Also show as table
    with st.expander("View as Table", expanded=False):
        display_cols = ['sid', 'serial_num', 'opname', 'target', 'pct_complete',
                       'sofar', 'totalwork', 'units', 'elapsed_seconds',
                       'time_remaining_sec', 'username', 'message']
        available = [c for c in display_cols if c in longops_df.columns]

        st.dataframe(
            longops_df[available],
            use_container_width=True,
            hide_index=True,
            column_config={
                'sid': 'SID',
                'serial_num': 'Serial#',
                'opname': 'Operation',
                'target': 'Target',
                'pct_complete': st.column_config.ProgressColumn(
                    'Progress',
                    min_value=0,
                    max_value=100,
                    format="%.1f%%"
                ),
                'sofar': 'Done',
                'totalwork': 'Total',
                'units': 'Units',
                'elapsed_seconds': 'Elapsed (s)',
                'time_remaining_sec': 'Remaining (s)',
                'username': 'User',
                'message': 'Message'
            }
        )


def show_operation_card(op):
    """Display a single operation as a styled card"""

    sid = op.get('sid', 'N/A')
    serial = op.get('serial_num', 'N/A')
    opname = op.get('opname', 'Unknown Operation')
    target = op.get('target', 'N/A')
    pct = op.get('pct_complete', 0) or 0
    sofar = op.get('sofar', 0) or 0
    total = op.get('totalwork', 0) or 0
    units = op.get('units', '')
    elapsed = op.get('elapsed_seconds', 0) or 0
    remaining = op.get('time_remaining_sec')
    username = op.get('username', 'N/A')
    message = op.get('message', '')
    sql_id = op.get('sql_id', '')

    # Determine status color
    if pct >= 90:
        status_color = "#28a745"  # Green - almost done
    elif pct >= 50:
        status_color = "#17a2b8"  # Blue - in progress
    elif pct >= 10:
        status_color = "#ffc107"  # Yellow - started
    else:
        status_color = "#6c757d"  # Gray - just started

    with st.container():
        # Header with operation info
        col1, col2, col3 = st.columns([3, 1, 1])

        with col1:
            st.markdown(f"**{opname}**")
            st.caption(f"Target: {target}")

        with col2:
            st.caption(f"SID: {sid}")
            st.caption(f"Serial#: {serial}")

        with col3:
            st.caption(f"User: {username}")
            if sql_id:
                st.caption(f"SQL ID: {sql_id}")

        # Progress bar
        st.progress(min(pct / 100, 1.0), text=f"{pct:.1f}% complete ({sofar:,} / {total:,} {units})")

        # Metrics row
        col1, col2, col3 = st.columns(3)

        with col1:
            st.metric("Elapsed", format_duration(elapsed))

        with col2:
            if remaining and pd.notna(remaining):
                st.metric("Remaining", format_duration(remaining))
            else:
                st.metric("Remaining", "Calculating...")

        with col3:
            if elapsed > 0 and sofar > 0:
                rate = sofar / elapsed
                st.metric("Rate", f"{rate:.1f} {units}/sec")

        # Message
        if message:
            st.caption(f"Status: {message}")

        st.markdown("---")


def show_compression_sessions():
    """Display active sessions running compression operations"""

    st.subheader("Active Compression Sessions")
    st.caption("Sessions currently executing compression-related SQL")

    with st.spinner("Loading compression sessions..."):
        sessions_df = TargetQueries.get_compression_sessions(db_id)

    if sessions_df.empty:
        st.success("No active compression sessions found")
        return

    sessions_df.columns = [c.lower() for c in sessions_df.columns]

    # Summary
    st.metric("Active Compression Sessions", len(sessions_df))

    st.markdown("---")

    # Display sessions
    for _, session in sessions_df.iterrows():
        show_session_card(session)

    # Table view
    with st.expander("View as Table", expanded=False):
        display_cols = ['sid', 'serial_num', 'username', 'status', 'program',
                       'module', 'action', 'seconds_in_wait', 'wait_class',
                       'event', 'sql_id']
        available = [c for c in display_cols if c in sessions_df.columns]

        st.dataframe(
            sessions_df[available],
            use_container_width=True,
            hide_index=True
        )


def show_session_card(session):
    """Display a single session as a styled card"""

    sid = session.get('sid', 'N/A')
    serial = session.get('serial_num', 'N/A')
    username = session.get('username', 'N/A')
    status = session.get('status', 'N/A')
    program = session.get('program', 'N/A')
    module = session.get('module', 'N/A')
    action = session.get('action', 'N/A')
    wait_class = session.get('wait_class', 'N/A')
    event = session.get('event', 'N/A')
    seconds_in_wait = session.get('seconds_in_wait', 0) or 0
    sql_id = session.get('sql_id', '')

    with st.container():
        col1, col2, col3 = st.columns([2, 1, 1])

        with col1:
            st.markdown(f"**Session {sid},{serial}** - {username}")
            st.caption(f"Program: {program}")

        with col2:
            status_icon = "🟢" if status == 'ACTIVE' else "🟡"
            st.markdown(f"{status_icon} {status}")
            st.caption(f"Wait: {wait_class}")

        with col3:
            st.caption(f"Module: {module}")
            st.caption(f"Action: {action}")

        # SQL ID info
        if sql_id:
            st.caption(f"SQL ID: {sql_id}")

        # Wait info
        if seconds_in_wait > 0:
            st.caption(f"Waiting for {format_duration(seconds_in_wait)} on: {event}")

        st.markdown("---")


def show_all_active_sessions():
    """Display all active long operations (not just compression)"""

    st.subheader("All Active Long Operations")
    st.caption("All operations from V$SESSION_LONGOPS regardless of type")

    with st.spinner("Loading all operations..."):
        longops_df = TargetQueries.get_all_active_longops(db_id)

    if longops_df.empty:
        st.success("No active long operations")
        return

    longops_df.columns = [c.lower() for c in longops_df.columns]

    # Group by operation type
    if 'opname' in longops_df.columns:
        op_counts = longops_df['opname'].value_counts()

        col1, col2 = st.columns([1, 2])

        with col1:
            st.markdown("**Operations by Type:**")
            for op, count in op_counts.items():
                st.markdown(f"- {op}: {count}")

        with col2:
            # Pie chart of operation types
            fig = go.Figure(data=[go.Pie(
                labels=op_counts.index.tolist(),
                values=op_counts.values.tolist(),
                hole=0.4
            )])
            fig.update_layout(
                height=300,
                margin=dict(l=20, r=20, t=20, b=20),
                showlegend=True
            )
            st.plotly_chart(fig, use_container_width=True)

    st.markdown("---")

    # Display all operations
    display_cols = ['sid', 'serial_num', 'opname', 'target', 'pct_complete',
                   'sofar', 'totalwork', 'units', 'elapsed_seconds',
                   'time_remaining_sec', 'username', 'start_time']
    available = [c for c in display_cols if c in longops_df.columns]

    st.dataframe(
        longops_df[available],
        use_container_width=True,
        hide_index=True,
        column_config={
            'sid': 'SID',
            'serial_num': 'Serial#',
            'opname': 'Operation',
            'target': 'Target',
            'pct_complete': st.column_config.ProgressColumn(
                'Progress',
                min_value=0,
                max_value=100,
                format="%.1f%%"
            ),
            'sofar': 'Done',
            'totalwork': 'Total',
            'units': 'Units',
            'elapsed_seconds': 'Elapsed (s)',
            'time_remaining_sec': 'Remaining (s)',
            'username': 'User',
            'start_time': 'Started'
        }
    )


def format_duration(seconds):
    """Format seconds into human-readable duration"""

    if seconds is None or pd.isna(seconds):
        return "N/A"

    seconds = int(seconds)

    if seconds < 60:
        return f"{seconds}s"
    elif seconds < 3600:
        mins = seconds // 60
        secs = seconds % 60
        return f"{mins}m {secs}s"
    else:
        hours = seconds // 3600
        mins = (seconds % 3600) // 60
        return f"{hours}h {mins}m"


if __name__ == "__main__":
    show_sessions_page()
