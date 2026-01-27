"""
HCC Compression Advisor - Main Streamlit Application
Oracle Hybrid Columnar Compression Analysis and Management Dashboard
"""

import streamlit as st
from streamlit_option_menu import option_menu
from auth import AuthManager, render_logout_button
from config import config
from utils.db_connector import get_db_connector
from utils.db_queries import CompressionQueries
from utils.logger import get_recent_logs, get_error_logs

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

    # Initialize DB connector
    db_connector = get_db_connector()

    # Handle session state navigation (from buttons on other pages)
    default_page_index = 0
    if 'selected_page' in st.session_state and st.session_state.selected_page:
        page_mapping = {
            "Overview": 0, "Run Analysis": 1, "View Recommendations": 2,
            "Compress Tables": 3, "Execution History": 4, "Compression Rules": 5, "DB Connections": 6,
            # Legacy mappings for compatibility
            "Dashboard": 0, "Analysis": 1, "Recommendations": 2,
            "Execution": 3, "History": 4, "Strategies": 5, "Connections": 6
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
                "Compression Rules",
                "DB Connections"
            ],
            icons=[
                "house-door-fill",     # Overview - home/dashboard
                "bar-chart-line-fill", # Run Analysis - analytics
                "stars",               # View Recommendations - suggestions
                "box-arrow-in-down",   # Compress Tables - compression action
                "journal-text",        # Execution History - log/history
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

        # Connection status
        st.markdown("---")
        st.subheader("Connection Status")

        if db_connector.test_connection():
            st.success("Database Connected")
        else:
            st.error("Database Disconnected")

        # Logout button
        render_logout_button()

    # Route to selected page
    if selected == "Overview":
        show_dashboard()
    elif selected == "Run Analysis":
        from views.page_01_analysis import show_analysis_page
        show_analysis_page()
    elif selected == "View Recommendations":
        from views.page_02_recommendations import show_recommendations_page
        show_recommendations_page()
    elif selected == "Compress Tables":
        from views.page_03_execution import show_execution_page
        show_execution_page()
    elif selected == "Execution History":
        from views.page_04_history import show_history_page
        show_history_page()
    elif selected == "Compression Rules":
        from views.page_05_strategies import show_strategies_page
        show_strategies_page()
    elif selected == "DB Connections":
        from views.page_06_connections import show_connections_page
        show_connections_page()


def show_dashboard():
    """Display main dashboard with overview metrics"""

    st.markdown('<div class="main-header">HCC Compression Advisor Dashboard</div>', unsafe_allow_html=True)
    st.markdown("---")

    # Fetch statistics using direct database queries
    stats = CompressionQueries.get_dashboard_summary()

    # Top metrics
    col1, col2, col3, col4 = st.columns(4)

    with col1:
        st.metric(
            label="Total Tables Analyzed",
            value=f"{stats.get('total_tables', 0):,}",
            delta=None
        )

    with col2:
        total_size = stats.get('total_size_gb', 0)
        st.metric(
            label="Total Size (GB)",
            value=f"{total_size:,.2f}",
            delta=None
        )

    with col3:
        potential_savings = stats.get('potential_savings_gb', 0)
        st.metric(
            label="Potential Savings (GB)",
            value=f"{potential_savings:,.2f}",
            delta=None
        )

    with col4:
        savings_pct = stats.get('avg_savings_pct', 0)
        st.metric(
            label="Avg Savings",
            value=f"{savings_pct:.1f}%",
            delta=None
        )

    st.markdown("---")

    # Recent activity and charts
    col1, col2 = st.columns(2)

    with col1:
        st.subheader("Savings by Strategy")

        strategy_df = CompressionQueries.get_savings_by_strategy()

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

        history_df = CompressionQueries.get_recent_executions(limit=5)

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
            if st.button("Refresh Logs", key="refresh_logs_btn"):
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
