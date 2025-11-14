"""
Recommendations Page - HCC Compression Advisor
View and filter compression recommendations
"""

import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from utils.api_client import get_api_client
from config import config


def show_recommendations_page():
    """Display recommendations page"""

    st.title("💡 Compression Recommendations")
    st.markdown("View and filter compression candidates")
    st.markdown("---")

    api_client = get_api_client()

    # Filters
    st.subheader("🔍 Filters")

    col1, col2, col3, col4 = st.columns(4)

    with col1:
        strategy_filter = st.selectbox(
            "Strategy",
            options=["All"] + config.COMPRESSION_STRATEGIES,
            index=0
        )

    with col2:
        min_savings = st.slider(
            "Min Savings %",
            min_value=0,
            max_value=100,
            value=10,
            step=5
        )

    with col3:
        min_size = st.number_input(
            "Min Size (MB)",
            min_value=0,
            max_value=10000,
            value=0,
            step=100
        )

    with col4:
        limit = st.number_input(
            "Max Results",
            min_value=10,
            max_value=1000,
            value=100,
            step=10
        )

    # Fetch recommendations
    strategy_param = None if strategy_filter == "All" else strategy_filter

    with st.spinner("Loading recommendations..."):
        recommendations = api_client.get_recommendations(
            strategy=strategy_param,
            min_savings_pct=min_savings,
            limit=limit
        )

    if "error" in recommendations:
        st.error("Failed to load recommendations")
        return

    if "items" not in recommendations or not recommendations["items"]:
        st.warning("No recommendations found. Try adjusting your filters or run a new analysis.")
        return

    # Convert to DataFrame
    df = pd.DataFrame(recommendations["items"])

    # Apply additional filters
    if min_size > 0:
        df = df[df['current_size_mb'] >= min_size]

    # Summary metrics
    col1, col2, col3, col4 = st.columns(4)

    with col1:
        st.metric(
            label="Total Candidates",
            value=f"{len(df):,}"
        )

    with col2:
        total_current = df['current_size_mb'].sum() / 1024
        st.metric(
            label="Total Current Size",
            value=f"{total_current:.2f} GB"
        )

    with col3:
        total_compressed = df['estimated_size_mb'].sum() / 1024
        st.metric(
            label="Total After Compression",
            value=f"{total_compressed:.2f} GB"
        )

    with col4:
        total_savings = ((total_current - total_compressed) / total_current * 100) if total_current > 0 else 0
        st.metric(
            label="Overall Savings",
            value=f"{total_savings:.1f}%",
            delta=f"{(total_current - total_compressed):.2f} GB"
        )

    st.markdown("---")

    # Visualizations
    col1, col2 = st.columns(2)

    with col1:
        st.subheader("📊 Recommendations by Strategy")

        strategy_counts = df['recommended_strategy'].value_counts()

        fig = px.pie(
            values=strategy_counts.values,
            names=strategy_counts.index,
            color_discrete_sequence=px.colors.qualitative.Set3
        )

        fig.update_layout(height=400)
        st.plotly_chart(fig, use_container_width=True)

    with col2:
        st.subheader("📈 Savings Distribution")

        fig = px.histogram(
            df,
            x='savings_pct',
            nbins=20,
            color_discrete_sequence=[config.CHART_COLORS['primary']]
        )

        fig.update_layout(
            xaxis_title="Savings (%)",
            yaxis_title="Number of Tables",
            height=400
        )

        st.plotly_chart(fig, use_container_width=True)

    st.markdown("---")

    # Top recommendations
    st.subheader("🎯 Top Recommendations by Savings")

    top_n = st.slider("Show top N tables", min_value=5, max_value=50, value=10, step=5)

    top_df = df.nlargest(top_n, 'savings_pct')

    fig = go.Figure()

    fig.add_trace(go.Bar(
        x=top_df['table_name'],
        y=top_df['savings_pct'],
        marker_color=config.CHART_COLORS['success'],
        text=top_df['savings_pct'].round(1),
        textposition='auto',
        hovertemplate='<b>%{x}</b><br>Savings: %{y:.1f}%<extra></extra>'
    ))

    fig.update_layout(
        xaxis_title="Table Name",
        yaxis_title="Savings (%)",
        height=400,
        showlegend=False
    )

    st.plotly_chart(fig, use_container_width=True)

    st.markdown("---")

    # Detailed table
    st.subheader("📋 Detailed Recommendations")

    # Prepare display DataFrame
    display_df = df[[
        'recommendation_id',
        'table_owner',
        'table_name',
        'current_size_mb',
        'recommended_strategy',
        'estimated_size_mb',
        'savings_pct',
        'compression_ratio',
        'estimated_rows'
    ]].copy()

    display_df.columns = [
        'ID', 'Owner', 'Table', 'Current (MB)',
        'Strategy', 'Compressed (MB)', 'Savings %',
        'Ratio', 'Rows'
    ]

    # Format numbers
    display_df['Current (MB)'] = display_df['Current (MB)'].round(2)
    display_df['Compressed (MB)'] = display_df['Compressed (MB)'].round(2)
    display_df['Savings %'] = display_df['Savings %'].round(1)
    display_df['Ratio'] = display_df['Ratio'].round(2)

    # Display with selection
    st.dataframe(
        display_df,
        use_container_width=True,
        hide_index=True
    )

    # Export options
    st.markdown("---")
    st.subheader("📥 Export Options")

    col1, col2, col3 = st.columns(3)

    with col1:
        # CSV export
        csv_data = display_df.to_csv(index=False)
        st.download_button(
            label="📄 Download CSV",
            data=csv_data,
            file_name=f"hcc_recommendations_{pd.Timestamp.now().strftime('%Y%m%d_%H%M%S')}.csv",
            mime="text/csv",
            use_container_width=True
        )

    with col2:
        # Excel export
        import io
        buffer = io.BytesIO()
        with pd.ExcelWriter(buffer, engine='xlsxwriter') as writer:
            display_df.to_excel(writer, sheet_name='Recommendations', index=False)

        st.download_button(
            label="📊 Download Excel",
            data=buffer.getvalue(),
            file_name=f"hcc_recommendations_{pd.Timestamp.now().strftime('%Y%m%d_%H%M%S')}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            use_container_width=True
        )

    with col3:
        if st.button("▶️ Execute Selected", use_container_width=True):
            st.session_state.selected_page = "Execution"
            st.rerun()


if __name__ == "__main__":
    show_recommendations_page()
