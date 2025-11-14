"""
Analysis Page - HCC Compression Advisor
Trigger and monitor compression analysis
"""

import streamlit as st
import pandas as pd
import plotly.graph_objects as go
from datetime import datetime
from utils.api_client import get_api_client
from config import config


def show_analysis_page():
    """Display analysis page"""

    st.title("🔍 Compression Analysis")
    st.markdown("Analyze tables for compression opportunities")
    st.markdown("---")

    api_client = get_api_client()

    # Analysis configuration
    col1, col2 = st.columns([2, 1])

    with col1:
        st.subheader("Start New Analysis")

        with st.form("analysis_form"):
            min_size_mb = st.number_input(
                "Minimum Table Size (MB)",
                min_value=1.0,
                max_value=10000.0,
                value=100.0,
                step=10.0,
                help="Only analyze tables larger than this size"
            )

            col_a, col_b = st.columns(2)

            with col_a:
                submit_button = st.form_submit_button(
                    "▶️ Start Analysis",
                    use_container_width=True
                )

            with col_b:
                refresh_button = st.form_submit_button(
                    "🔄 Refresh Status",
                    use_container_width=True
                )

            if submit_button:
                with st.spinner("Starting analysis..."):
                    result = api_client.start_analysis(min_size_mb=min_size_mb)

                    if "error" in result:
                        st.error(f"Analysis failed: {result['error']}")
                    elif "items" in result and result["items"]:
                        analysis_data = result["items"][0]
                        st.success(f"Analysis started! ID: {analysis_data.get('analysis_id')}")
                        st.session_state.current_analysis_id = analysis_data.get('analysis_id')
                    else:
                        st.success("Analysis started successfully!")

    with col2:
        st.subheader("Analysis Parameters")
        st.info(f"""
        **Current Settings:**
        - Min Size: {min_size_mb} MB
        - Target: All schemas
        - Strategies: All 4
        """)

    st.markdown("---")

    # Latest analysis results
    st.subheader("📊 Latest Analysis Results")

    latest_analysis = api_client.get_latest_analysis()

    if "error" in latest_analysis:
        st.warning("No analysis results available. Start a new analysis above.")
        return

    if "items" not in latest_analysis or not latest_analysis["items"]:
        st.info("No analysis data available")
        return

    analysis_data = latest_analysis["items"][0]

    # Display analysis summary
    col1, col2, col3, col4 = st.columns(4)

    with col1:
        st.metric(
            label="Analysis ID",
            value=f"#{analysis_data.get('analysis_id', 'N/A')}"
        )

    with col2:
        st.metric(
            label="Tables Analyzed",
            value=f"{analysis_data.get('tables_analyzed', 0):,}"
        )

    with col3:
        st.metric(
            label="Candidates Found",
            value=f"{analysis_data.get('candidates_found', 0):,}"
        )

    with col4:
        status = analysis_data.get('status', 'UNKNOWN')
        status_color = "🟢" if status == "COMPLETED" else "🟡"
        st.metric(
            label="Status",
            value=f"{status_color} {status}"
        )

    # Analysis details
    st.markdown("---")

    col1, col2 = st.columns(2)

    with col1:
        st.subheader("Analysis Details")

        st.markdown(f"""
        <div class="metric-card">
            <strong>Started:</strong> {analysis_data.get('started_at', 'N/A')}<br>
            <strong>Completed:</strong> {analysis_data.get('completed_at', 'N/A')}<br>
            <strong>Duration:</strong> {analysis_data.get('duration_seconds', 0)} seconds<br>
            <strong>Min Size:</strong> {analysis_data.get('min_size_mb', 0)} MB
        </div>
        """, unsafe_allow_html=True)

    with col2:
        st.subheader("Potential Savings")

        total_size = analysis_data.get('total_current_size_gb', 0)
        potential_size = analysis_data.get('total_compressed_size_gb', 0)
        savings = total_size - potential_size

        st.markdown(f"""
        <div class="metric-card success-card">
            <strong>Current Size:</strong> {total_size:.2f} GB<br>
            <strong>Compressed Size:</strong> {potential_size:.2f} GB<br>
            <strong>Potential Savings:</strong> {savings:.2f} GB ({analysis_data.get('avg_savings_pct', 0):.1f}%)
        </div>
        """, unsafe_allow_html=True)

    # Visualization
    if total_size > 0 and potential_size > 0:
        st.markdown("---")
        st.subheader("📈 Size Comparison")

        fig = go.Figure()

        fig.add_trace(go.Bar(
            x=['Current Size', 'After Compression'],
            y=[total_size, potential_size],
            marker_color=[config.CHART_COLORS['danger'], config.CHART_COLORS['success']],
            text=[f"{total_size:.2f} GB", f"{potential_size:.2f} GB"],
            textposition='auto',
        ))

        fig.update_layout(
            yaxis_title="Size (GB)",
            height=400,
            showlegend=False
        )

        st.plotly_chart(fig, use_container_width=True)

    # Top candidates preview
    st.markdown("---")
    st.subheader("🎯 Top Compression Candidates")

    recommendations = api_client.get_recommendations(limit=10, min_savings_pct=10.0)

    if "items" in recommendations and recommendations["items"]:
        df = pd.DataFrame(recommendations["items"])

        # Format DataFrame
        display_df = df[[
            'table_owner', 'table_name', 'current_size_mb',
            'recommended_strategy', 'estimated_size_mb', 'savings_pct'
        ]].copy()

        display_df.columns = [
            'Owner', 'Table', 'Current (MB)',
            'Strategy', 'Compressed (MB)', 'Savings %'
        ]

        # Format numbers
        display_df['Current (MB)'] = display_df['Current (MB)'].round(2)
        display_df['Compressed (MB)'] = display_df['Compressed (MB)'].round(2)
        display_df['Savings %'] = display_df['Savings %'].round(1)

        st.dataframe(
            display_df,
            use_container_width=True,
            hide_index=True
        )

        # Quick action
        if st.button("📋 View All Recommendations", use_container_width=True):
            st.session_state.selected_page = "Recommendations"
            st.rerun()
    else:
        st.info("No recommendations available. Run an analysis first.")


if __name__ == "__main__":
    show_analysis_page()
