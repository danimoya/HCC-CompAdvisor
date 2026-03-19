"""
HCC Compression Advisor - Main Streamlit Application
Oracle Hybrid Columnar Compression Analysis and Management Dashboard
"""

import streamlit as st

from hcc_advisor.config import config, Config
from hcc_advisor import __version__

# --- Pre-login deployment check (before set_page_config) ---
_needs_setup = config.is_first_run()
_needs_upgrade = False
if not _needs_setup and config.CENTRAL_DB_PASSWORD:
    if not st.session_state.get('setup_complete'):
        _schema_ver = config.get_schema_version()
        _schema_deployed = config.is_schema_deployed()
        _needs_upgrade = (not _schema_deployed) or (_schema_ver is None) or (_schema_ver != __version__)

if (_needs_setup or _needs_upgrade) and not st.session_state.get('setup_complete'):
    from hcc_advisor.views.page_00_setup import show_deployment_page
    show_deployment_page(mode='setup' if _needs_setup else 'upgrade')
    # show_deployment_page calls st.stop()

# --- Normal dashboard ---
from streamlit_option_menu import option_menu
from hcc_advisor.auth import AuthManager, render_logout_button
from hcc_advisor.utils.central_connector import CentralConnector
from hcc_advisor.utils.central_queries import CentralQueries
from hcc_advisor.utils.logger import get_recent_logs, get_error_logs, clear_logs
from hcc_advisor.utils.sql_debug import get_sql_log, clear_sql_log, is_debug_enabled

# Page configuration
st.set_page_config(
    page_title=config.PAGE_TITLE,
    page_icon=config.APP_ICON,
    layout=config.LAYOUT,
    initial_sidebar_state=config.INITIAL_SIDEBAR_STATE
)

# Custom CSS - Full width layout
st.markdown("""
<style>
    /* MAIN CONTENT - FULL WIDTH */
    .block-container {
        max-width: 100% !important;
        width: 100% !important;
        padding: 1rem 2rem !important;
    }

    [data-testid="stAppViewContainer"] > .main {
        max-width: 100% !important;
    }

    .main > div {
        max-width: 100% !important;
        width: 100% !important;
    }

    /* Target all possible block container classes */
    div[class*="block-container"] {
        max-width: 100% !important;
        width: 100% !important;
        padding-left: 2rem !important;
        padding-right: 2rem !important;
    }

    /* SIDEBAR - Fixed width */
    [data-testid="stSidebar"] {
        width: 280px !important;
        min-width: 280px !important;
        max-width: 280px !important;
    }

    [data-testid="stSidebar"] > div:first-child {
        width: 280px !important;
    }

    [data-testid="stSidebarContent"] {
        width: 100% !important;
    }

    /* Header styling */
    .main-header {
        font-size: 2.2rem;
        font-weight: bold;
        color: #1f77b4;
        text-align: center;
        padding: 0.5rem 0;
        margin-bottom: 0.5rem;
    }

    /* Cards */
    .metric-card {
        background-color: #1e2130;
        color: #e0e0e0;
        padding: 1rem;
        border-radius: 0.5rem;
        border-left: 4px solid #1f77b4;
    }

    .metric-card strong {
        color: #ffffff;
    }

    .metric-card small {
        color: #a0a0a0;
    }

    .success-card { background-color: #1a3d2a; border-left-color: #28a745; color: #d4edda; }
    .warning-card { background-color: #3d3a1a; border-left-color: #ffc107; color: #fff3cd; }
    .danger-card { background-color: #3d1a1a; border-left-color: #dc3545; color: #f8d7da; }

    /* Execution card - dark theme */
    .execution-card {
        background-color: #252836;
        color: #e0e0e0;
        padding: 1rem;
        border-radius: 0.5rem;
        border-left: 4px solid #1f77b4;
        margin-bottom: 0.5rem;
    }

    .execution-card strong {
        color: #ffffff;
    }

    .execution-card small {
        color: #888888;
    }

    .execution-card.success { border-left-color: #28a745; }
    .execution-card.failed { border-left-color: #dc3545; }
    .execution-card.running { border-left-color: #ffc107; }

    /* Metrics */
    div[data-testid="stMetricValue"] {
        font-size: 1.8rem;
    }

    /* DataFrames and tables - full width */
    [data-testid="stDataFrame"],
    [data-testid="stTable"],
    .stDataFrame {
        width: 100% !important;
    }

    [data-testid="stDataFrame"] > div {
        width: 100% !important;
    }

    [data-testid="stDataFrame"] iframe {
        width: 100% !important;
    }

    /* Charts full width */
    [data-testid="stPlotlyChart"] {
        width: 100% !important;
    }

    .js-plotly-plot {
        width: 100% !important;
    }

    /* Tabs */
    .stTabs [data-baseweb="tab-list"] {
        gap: 8px;
        width: 100%;
    }

    /* Expanders */
    [data-testid="stExpander"] {
        width: 100% !important;
    }

    /* Log viewer */
    .log-viewer {
        background-color: #1a1a2e;
        color: #00ff00;
        font-family: 'Courier New', monospace;
        font-size: 0.75rem;
        padding: 1rem;
        border-radius: 0.5rem;
        max-height: 400px;
        overflow-y: auto;
        white-space: pre-wrap;
        word-wrap: break-word;
        border: 1px solid #333;
    }

    .log-viewer .error-line {
        color: #ff6b6b;
    }

    .log-viewer .warning-line {
        color: #ffc107;
    }

    .log-viewer .info-line {
        color: #17a2b8;
    }
</style>
""", unsafe_allow_html=True)


def main():
    """Main application entry point"""

    # Require authentication
    AuthManager.require_authentication()

    # Initialize Central DB connector
    try:
        CentralConnector.initialize_pool()
    except Exception as e:
        st.error(f"Failed to connect to central database: {e}")

    # Handle session state navigation (from buttons on other pages)
    default_page_index = 0
    if 'selected_page' in st.session_state and st.session_state.selected_page:
        page_mapping = {
            "Overview": 0, "Run Analysis": 1, "View Recommendations": 2,
            "Compress Tables": 3, "Execution History": 4, "Session Browser": 5,
            "Compression Rules": 6, "DB Connections": 7,
            # Legacy mappings for compatibility
            "Dashboard": 0, "Analysis": 1, "Recommendations": 2,
            "Execution": 3, "History": 4, "Sessions": 5, "Strategies": 6, "Connections": 7
        }
        default_page_index = page_mapping.get(st.session_state.selected_page, 0)
        st.session_state.selected_page = None  # Clear after use

    # Sidebar navigation
    with st.sidebar:
        st.markdown(f"### {config.APP_ICON} HCC Advisor")
        st.markdown("---")

        selected = option_menu(
            menu_title=None,  # No title for cleaner look
            options=[
                "Overview",
                "Run Analysis",
                "View Recommendations",
                "Compress Tables",
                "Execution History",
                "Session Browser",
                "Compression Rules",
                "DB Connections"
            ],
            icons=[
                "house-door-fill",     # Overview - home/dashboard
                "bar-chart-line-fill", # Run Analysis - analytics
                "stars",               # View Recommendations - suggestions
                "box-arrow-in-down",   # Compress Tables - compression action
                "journal-text",        # Execution History - log/history
                "binoculars-fill",     # Session Browser - monitoring
                "gear-fill",           # Compression Rules - settings/config
                "plug-fill"            # DB Connections - connectivity
            ],
            menu_icon="list",
            default_index=default_page_index,
            styles={
                "container": {"padding": "0!important", "background-color": "transparent"},
                "icon": {"color": "#1f77b4", "font-size": "1.1rem"},
                "nav-link": {
                    "font-size": "0.95rem",
                    "text-align": "left",
                    "margin": "2px 0",
                    "padding": "0.5rem 0.8rem",
                    "border-radius": "5px",
                },
                "nav-link-selected": {"background-color": "#1f77b4", "color": "white"},
            }
        )

        # Database selector
        st.markdown("---")
        st.subheader("Target Database")

        # Initialize session state
        if 'active_database_id' not in st.session_state:
            st.session_state.active_database_id = None

        # Fetch registered target databases
        target_dbs = CentralQueries.get_target_databases()

        if not target_dbs.empty:
            target_dbs.columns = [c.lower() for c in target_dbs.columns]
            db_options = {"All Databases": None}
            for _, db in target_dbs.iterrows():
                db_options[db.get('display_name', db.get('database_name', 'Unknown'))] = db.get('database_id')

            current_label = "All Databases"
            for label, db_id in db_options.items():
                if db_id == st.session_state.active_database_id:
                    current_label = label
                    break

            selected_db = st.selectbox(
                "Active Database",
                options=list(db_options.keys()),
                index=list(db_options.keys()).index(current_label),
                key="db_selector"
            )
            st.session_state.active_database_id = db_options[selected_db]
        else:
            st.info("No target databases registered")
            st.session_state.active_database_id = None

        # Connection status
        st.markdown("---")
        st.subheader("Connection Status")

        if CentralConnector.test_connection():
            st.success("Central DB Connected")
        else:
            st.error("Central DB Disconnected")

        # SQL Debug toggle
        st.markdown("---")
        st.checkbox("SQL Debug Console", key='sql_debug_enabled', value=False)

        # Logout button
        render_logout_button()

    # Route to selected page
    if selected == "Overview":
        show_dashboard()
    elif selected == "Run Analysis":
        from hcc_advisor.views.page_01_analysis import show_analysis_page
        show_analysis_page()
    elif selected == "View Recommendations":
        from hcc_advisor.views.page_02_recommendations import show_recommendations_page
        show_recommendations_page()
    elif selected == "Compress Tables":
        from hcc_advisor.views.page_03_execution import show_execution_page
        show_execution_page()
    elif selected == "Execution History":
        from hcc_advisor.views.page_04_history import show_history_page
        show_history_page()
    elif selected == "Session Browser":
        from hcc_advisor.views.page_07_sessions import show_sessions_page
        show_sessions_page()
    elif selected == "Compression Rules":
        from hcc_advisor.views.page_05_strategies import show_strategies_page
        show_strategies_page()
    elif selected == "DB Connections":
        from hcc_advisor.views.page_06_connections import show_connections_page
        show_connections_page()

    # SQL Debug Console (visible on all pages when enabled)
    if is_debug_enabled():
        render_sql_debug_console()


def render_sql_debug_console():
    """Render the SQL debug console panel at the bottom of any page."""
    st.markdown("---")
    st.subheader("SQL Debug Console")

    col1, col2, col3 = st.columns([1, 1, 2])
    with col1:
        filter_db = st.selectbox("Database", ["All", "central", "target"],
                                 key="sql_debug_filter_db")
    with col2:
        filter_op = st.selectbox("Operation",
                                 ["All", "SELECT", "DML", "PLSQL", "PROCEDURE", "FUNCTION"],
                                 key="sql_debug_filter_op")
    with col3:
        btn1, btn2 = st.columns(2)
        with btn1:
            if st.button("Refresh", key="sql_debug_refresh"):
                st.rerun()
        with btn2:
            if st.button("Clear", key="sql_debug_clear"):
                clear_sql_log()
                st.rerun()

    entries = get_sql_log()

    if filter_db != "All":
        entries = [e for e in entries if filter_db in e['database']]
    if filter_op != "All":
        entries = [e for e in entries if e['operation'] == filter_op]

    if entries:
        st.caption(f"{len(entries)} queries captured")
        for i, entry in enumerate(entries):
            status_icon = "🔴" if entry['status'] == 'ERROR' else "🟢"
            duration = f"{entry['duration_ms']:.0f}ms" if entry['duration_ms'] else "?"
            rows = f"{entry['rows']} rows" if entry['rows'] is not None else ""
            header = (f"{status_icon} `{entry['timestamp']}` **{entry['operation']}** "
                      f"on `{entry['database']}` — {duration} {rows}")
            with st.expander(header, expanded=False):
                st.code(entry['sql'], language='sql')
                if entry['params']:
                    st.json(entry['params'])
                if entry['error']:
                    st.error(entry['error'])
    else:
        st.info("No SQL queries captured yet. Interact with the dashboard to see queries here.")


def show_dashboard():
    """Display main dashboard with overview metrics"""

    st.markdown('<div class="main-header">HCC Compression Advisor Dashboard</div>', unsafe_allow_html=True)
    st.markdown("---")

    # Fetch statistics
    db_id = st.session_state.get('active_database_id')
    stats = CentralQueries.get_dashboard_summary(database_id=db_id)
    progress = CentralQueries.get_compression_progress(database_id=db_id)

    # Row 1 — Estate Summary
    col1, col2, col3, col4, col5 = st.columns(5)

    with col1:
        st.metric("Objects Analyzed", f"{stats.get('total_tables', 0):,}")
    with col2:
        st.metric("Total Size (GB)", f"{stats.get('total_size_gb', 0):,.2f}")
    with col3:
        st.metric("Compressed", f"{progress.get('compressed', 0):,}",
                   delta=f"{progress.get('saved_mb', 0) / 1024:.2f} GB saved" if progress.get('saved_mb', 0) > 0 else None)
    with col4:
        st.metric("Pending", f"{progress.get('pending', 0):,}",
                   delta=f"{progress.get('pending_savings_mb', 0) / 1024:.2f} GB potential" if progress.get('pending', 0) > 0 else None)
    with col5:
        st.metric("Avg Savings", f"{stats.get('avg_savings_pct', 0):.1f}%")

    st.markdown("---")

    # Row 2 — Compression Progress
    col1, col2 = st.columns(2)

    with col1:
        st.subheader("Compression Progress")
        compressed = progress.get('compressed', 0)
        pending = progress.get('pending', 0)
        skipped = progress.get('skipped', 0)

        if compressed + pending + skipped > 0:
            import plotly.graph_objects as go
            fig = go.Figure(data=[go.Pie(
                labels=['Compressed', 'Pending', 'Not Recommended'],
                values=[compressed, pending, skipped],
                marker_colors=['#28a745', '#ffc107', '#6c757d'],
                hole=0.5,
                textinfo='label+value'
            )])
            fig.update_layout(height=300, margin=dict(t=20, b=20, l=20, r=20),
                              showlegend=True, legend=dict(orientation='h', y=-0.1))
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("No analysis data yet. Run an analysis first.")

    with col2:
        st.subheader("Savings Overview")
        total_size = stats.get('total_size_gb', 0)
        saved = progress.get('saved_mb', 0) / 1024
        pending_save = progress.get('pending_savings_mb', 0) / 1024
        remaining = max(0, total_size - saved - pending_save)

        if total_size > 0:
            import plotly.graph_objects as go
            fig = go.Figure(data=[
                go.Bar(name='Already Saved', x=['Storage'], y=[saved],
                       marker_color='#28a745', text=f"{saved:.2f} GB", textposition='auto'),
                go.Bar(name='Pending Savings', x=['Storage'], y=[pending_save],
                       marker_color='#ffc107', text=f"{pending_save:.2f} GB", textposition='auto'),
                go.Bar(name='Remaining', x=['Storage'], y=[remaining],
                       marker_color='#6c757d', text=f"{remaining:.2f} GB", textposition='auto'),
            ])
            fig.update_layout(barmode='stack', height=300, yaxis_title="GB",
                              margin=dict(t=20, b=20), showlegend=True,
                              legend=dict(orientation='h', y=-0.15))
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("No size data available.")

    st.markdown("---")

    # Row 3 — Existing charts
    col1, col2 = st.columns(2)

    with col1:
        st.subheader("Savings by Strategy")

        strategy_df = CentralQueries.get_savings_by_strategy(database_id=st.session_state.get('active_database_id'))

        if not strategy_df.empty:
            import plotly.graph_objects as go

            # Handle column name case (Oracle returns uppercase)
            strategy_col = 'STRATEGY' if 'STRATEGY' in strategy_df.columns else 'strategy'
            savings_col = 'AVG_SAVINGS_PCT' if 'AVG_SAVINGS_PCT' in strategy_df.columns else 'avg_savings_pct'

            strategies = strategy_df[strategy_col].tolist()
            savings = strategy_df[savings_col].tolist()

            fig = go.Figure(data=[
                go.Bar(
                    x=strategies,
                    y=savings,
                    marker_color=config.CHART_COLORS['primary']
                )
            ])

            fig.update_layout(
                xaxis_title="Strategy",
                yaxis_title="Average Savings (%)",
                height=400
            )

            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("No strategy statistics available. Run an analysis first.")

    with col2:
        st.subheader("Recent Executions")

        history_df = CentralQueries.get_recent_executions(limit=5, database_id=st.session_state.get('active_database_id'))

        if not history_df.empty:
            # Handle column name case
            for _, row in history_df.iterrows():
                table_name = row.get('TABLE_NAME', row.get('table_name', 'N/A'))
                status = row.get('STATUS', row.get('status', 'UNKNOWN'))
                strategy = row.get('STRATEGY', row.get('strategy', 'N/A'))
                savings_pct = row.get('SAVINGS_PCT', row.get('savings_pct', 0)) or 0
                start_time = row.get('START_TIME', row.get('start_time', 'N/A'))

                # Determine status class and icon
                if status == 'SUCCESS':
                    status_class = 'success'
                    status_icon = '✓'
                elif status == 'FAILED':
                    status_class = 'failed'
                    status_icon = '✗'
                elif status == 'IN_PROGRESS':
                    status_class = 'running'
                    status_icon = '⏳'
                else:
                    status_class = ''
                    status_icon = '•'

                st.markdown(f"""
                <div class="execution-card {status_class}">
                    <strong>{status_icon} {table_name}</strong><br>
                    Strategy: {strategy}<br>
                    Savings: {savings_pct:.1f}%<br>
                    <small>{start_time}</small>
                </div>
                """, unsafe_allow_html=True)
        else:
            st.info("No recent executions")

    # Quick actions
    st.markdown("---")
    st.subheader("Quick Actions")

    col1, col2, col3, col4 = st.columns(4)

    with col1:
        if st.button("Run New Analysis", use_container_width=True, type="primary"):
            st.session_state.selected_page = "Run Analysis"
            st.rerun()

    with col2:
        if st.button("View Recommendations", use_container_width=True):
            st.session_state.selected_page = "View Recommendations"
            st.rerun()

    with col3:
        if st.button("Compress Tables", use_container_width=True):
            st.session_state.selected_page = "Compress Tables"
            st.rerun()

    with col4:
        if st.button("Compression Rules", use_container_width=True):
            st.session_state.selected_page = "Compression Rules"
            st.rerun()

    # Debug logs section
    st.markdown("---")
    st.markdown("<h3 style='text-align: center;'>Debug Logs</h3>", unsafe_allow_html=True)
    with st.expander("View Application Logs", expanded=False):
        col1, col2, col3 = st.columns([1, 1, 2])
        with col1:
            log_type = st.selectbox(
                "Log Type",
                options=["Error Logs", "All Logs"],
                key="log_type_select"
            )
        with col2:
            log_lines = st.number_input(
                "Lines to Show",
                min_value=10,
                max_value=500,
                value=50,
                step=10,
                key="log_lines_input"
            )
        with col3:
            btn_col1, btn_col2 = st.columns(2)
            with btn_col1:
                if st.button("Refresh Logs", key="refresh_logs_btn", use_container_width=True):
                    st.rerun()
            with btn_col2:
                if st.button("Clear Logs", key="clear_logs_btn", use_container_width=True, type="secondary"):
                    result = clear_logs()
                    st.toast(result)
                    st.rerun()

        # Fetch and display logs
        if log_type == "Error Logs":
            logs_content = get_error_logs(lines=log_lines)
        else:
            logs_content = get_recent_logs(lines=log_lines)

        if logs_content and logs_content != "No logs available" and logs_content != "No error logs available":
            # Color-code log lines
            lines = logs_content.split('\n')
            formatted_lines = []
            for line in lines:
                if '| ERROR' in line or '| CRITICAL' in line:
                    formatted_lines.append(f'<span class="error-line">{line}</span>')
                elif '| WARNING' in line:
                    formatted_lines.append(f'<span class="warning-line">{line}</span>')
                elif '| INFO' in line:
                    formatted_lines.append(f'<span class="info-line">{line}</span>')
                else:
                    formatted_lines.append(line)

            st.markdown(
                f'<div class="log-viewer">{chr(10).join(formatted_lines)}</div>',
                unsafe_allow_html=True
            )
        else:
            st.info("No logs available yet. Logs will appear here when errors occur.")


if __name__ == "__main__":
    main()
