"""
HCC Compression Advisor - Main Streamlit Application
Oracle Hybrid Columnar Compression Analysis and Management Dashboard
"""

import streamlit as st
from streamlit_option_menu import option_menu
from auth import AuthManager, render_logout_button
from config import config
from utils.api_client import get_api_client
from utils.db_connector import get_db_connector

# Page configuration
st.set_page_config(
    page_title=config.PAGE_TITLE,
    page_icon=config.APP_ICON,
    layout=config.LAYOUT,
    initial_sidebar_state=config.INITIAL_SIDEBAR_STATE
)

# Custom CSS
st.markdown("""
<style>
    .main-header {
        font-size: 2.5rem;
        font-weight: bold;
        color: #1f77b4;
        text-align: center;
        padding: 1rem 0;
    }
    .metric-card {
        background-color: #f0f2f6;
        padding: 1rem;
        border-radius: 0.5rem;
        border-left: 4px solid #1f77b4;
    }
    .success-card {
        background-color: #d4edda;
        border-left-color: #28a745;
    }
    .warning-card {
        background-color: #fff3cd;
        border-left-color: #ffc107;
    }
    .danger-card {
        background-color: #f8d7da;
        border-left-color: #dc3545;
    }
    .stButton>button {
        width: 100%;
    }
    div[data-testid="stMetricValue"] {
        font-size: 1.8rem;
    }
</style>
""", unsafe_allow_html=True)


def main():
    """Main application entry point"""

    # Require authentication
    AuthManager.require_authentication()

    # Initialize API client and DB connector
    api_client = get_api_client()
    db_connector = get_db_connector()

    # Sidebar navigation
    with st.sidebar:
        st.markdown(f"# {config.APP_ICON} {config.APP_TITLE}")
        st.markdown("---")

        selected = option_menu(
            menu_title="Navigation",
            options=[
                "Dashboard",
                "Analysis",
                "Recommendations",
                "Execution",
                "History",
                "Strategies"
            ],
            icons=[
                "speedometer2",
                "search",
                "lightbulb",
                "play-circle",
                "clock-history",
                "diagram-3"
            ],
            menu_icon="cast",
            default_index=0,
            styles={
                "container": {"padding": "0!important"},
                "icon": {"color": "#1f77b4", "font-size": "1.2rem"},
                "nav-link": {
                    "font-size": "1rem",
                    "text-align": "left",
                    "margin": "0px",
                    "padding": "0.5rem 1rem",
                },
                "nav-link-selected": {"background-color": "#1f77b4"},
            }
        )

        # Connection status
        st.markdown("---")
        st.subheader("Connection Status")

        col1, col2 = st.columns(2)
        with col1:
            if api_client.health_check():
                st.success("✓ API")
            else:
                st.error("✗ API")

        with col2:
            if db_connector.test_connection():
                st.success("✓ Database")
            else:
                st.error("✗ Database")

        # Logout button
        render_logout_button()

    # Route to selected page
    if selected == "Dashboard":
        show_dashboard()
    elif selected == "Analysis":
        from pages.page_01_analysis import show_analysis_page
        show_analysis_page()
    elif selected == "Recommendations":
        from pages.page_02_recommendations import show_recommendations_page
        show_recommendations_page()
    elif selected == "Execution":
        from pages.page_03_execution import show_execution_page
        show_execution_page()
    elif selected == "History":
        from pages.page_04_history import show_history_page
        show_history_page()
    elif selected == "Strategies":
        from pages.page_05_strategies import show_strategies_page
        show_strategies_page()


def show_dashboard():
    """Display main dashboard with overview metrics"""

    st.markdown('<div class="main-header">📊 HCC Compression Advisor Dashboard</div>', unsafe_allow_html=True)
    st.markdown("---")

    # Get API client
    api_client = get_api_client()

    # Fetch statistics
    stats = api_client.get_compression_statistics()

    if "error" in stats:
        st.error("Failed to load statistics. Please check your connection.")
        return

    # Top metrics
    col1, col2, col3, col4 = st.columns(4)

    items = stats.get("items", [])
    if items:
        data = items[0]

        with col1:
            st.metric(
                label="Total Tables Analyzed",
                value=f"{data.get('total_tables', 0):,}",
                delta=None
            )

        with col2:
            total_size = data.get('total_size_gb', 0)
            st.metric(
                label="Total Size (GB)",
                value=f"{total_size:,.2f}",
                delta=None
            )

        with col3:
            compressed_size = data.get('compressed_size_gb', 0)
            st.metric(
                label="Compressed Size (GB)",
                value=f"{compressed_size:,.2f}",
                delta=None
            )

        with col4:
            savings_pct = data.get('avg_savings_pct', 0)
            st.metric(
                label="Avg Savings",
                value=f"{savings_pct:.1f}%",
                delta=None
            )

    st.markdown("---")

    # Recent activity and charts
    col1, col2 = st.columns(2)

    with col1:
        st.subheader("📈 Savings by Strategy")

        strategy_stats = api_client.get_savings_by_strategy()

        if "items" in strategy_stats and strategy_stats["items"]:
            import plotly.graph_objects as go

            strategies = [item.get('strategy', '') for item in strategy_stats["items"]]
            savings = [item.get('avg_savings_pct', 0) for item in strategy_stats["items"]]

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
            st.info("No strategy statistics available")

    with col2:
        st.subheader("🕐 Recent Executions")

        history = api_client.get_execution_history(limit=5)

        if "items" in history and history["items"]:
            import pandas as pd

            df = pd.DataFrame(history["items"])

            # Display recent executions
            for _, row in df.iterrows():
                status_icon = "✓" if row.get('status') == 'COMPLETED' else "⏳"
                st.markdown(f"""
                <div class="metric-card">
                    <strong>{status_icon} {row.get('table_name', 'N/A')}</strong><br>
                    Strategy: {row.get('strategy', 'N/A')}<br>
                    Savings: {row.get('savings_pct', 0):.1f}%<br>
                    <small>{row.get('executed_at', 'N/A')}</small>
                </div>
                """, unsafe_allow_html=True)
                st.markdown("<br>", unsafe_allow_html=True)
        else:
            st.info("No recent executions")

    # Quick actions
    st.markdown("---")
    st.subheader("⚡ Quick Actions")

    col1, col2, col3, col4 = st.columns(4)

    with col1:
        if st.button("🔍 Start New Analysis", use_container_width=True):
            st.session_state.selected_page = "Analysis"
            st.rerun()

    with col2:
        if st.button("💡 View Recommendations", use_container_width=True):
            st.session_state.selected_page = "Recommendations"
            st.rerun()

    with col3:
        if st.button("▶️ Execute Compression", use_container_width=True):
            st.session_state.selected_page = "Execution"
            st.rerun()

    with col4:
        if st.button("📊 View Strategies", use_container_width=True):
            st.session_state.selected_page = "Strategies"
            st.rerun()


if __name__ == "__main__":
    main()
