"""
Strategies Page - HCC Compression Advisor
View and compare compression strategies
"""

import streamlit as st
import pandas as pd
import plotly.graph_objects as go
import plotly.express as px
from utils.api_client import get_api_client
from config import config


def show_strategies_page():
    """Display strategies page"""

    st.title("📊 Compression Strategies")
    st.markdown("View and compare HCC compression strategies")
    st.markdown("---")

    api_client = get_api_client()

    # Strategy overview
    st.subheader("🎯 Available Strategies")

    strategies = api_client.get_strategies()

    if "error" in strategies:
        st.error("Failed to load strategies")
        return

    if "items" not in strategies or not strategies["items"]:
        st.info("No strategy information available")
        return

    # Display strategy cards
    for strategy_data in strategies["items"]:
        strategy_name = strategy_data.get('strategy_name', 'Unknown')

        with st.expander(f"📌 {strategy_name}", expanded=False):
            col1, col2 = st.columns(2)

            with col1:
                st.markdown(f"""
                **Description:** {strategy_data.get('description', 'N/A')}

                **Best For:**
                - {strategy_data.get('best_for', 'General purpose')}

                **Compression Level:** {strategy_data.get('compression_level', 'N/A')}
                """)

            with col2:
                st.markdown(f"""
                **Typical Compression Ratio:** {strategy_data.get('avg_compression_ratio', 0):.2f}x

                **Average Savings:** {strategy_data.get('avg_savings_pct', 0):.1f}%

                **Performance Impact:** {strategy_data.get('performance_impact', 'N/A')}
                """)

    st.markdown("---")

    # Strategy comparison
    st.subheader("📊 Strategy Performance Comparison")

    # Fetch savings by strategy
    strategy_stats = api_client.get_savings_by_strategy()

    if "items" in strategy_stats and strategy_stats["items"]:
        df = pd.DataFrame(strategy_stats["items"])

        # Create comparison chart
        fig = go.Figure()

        fig.add_trace(go.Bar(
            name='Average Savings %',
            x=df['strategy'],
            y=df['avg_savings_pct'],
            marker_color=config.CHART_COLORS['primary'],
            yaxis='y',
            offsetgroup=1
        ))

        fig.add_trace(go.Bar(
            name='Compression Ratio',
            x=df['strategy'],
            y=df['avg_compression_ratio'],
            marker_color=config.CHART_COLORS['success'],
            yaxis='y2',
            offsetgroup=2
        ))

        fig.update_layout(
            xaxis_title="Strategy",
            yaxis_title="Average Savings (%)",
            yaxis2=dict(
                title="Compression Ratio",
                overlaying='y',
                side='right'
            ),
            height=400,
            barmode='group'
        )

        st.plotly_chart(fig, use_container_width=True)

        # Display statistics table
        st.markdown("---")
        st.subheader("📈 Strategy Statistics")

        display_df = df[[
            'strategy', 'table_count', 'avg_savings_pct',
            'avg_compression_ratio', 'total_size_gb', 'total_savings_gb'
        ]].copy()

        display_df.columns = [
            'Strategy', 'Tables', 'Avg Savings %',
            'Avg Ratio', 'Total Size (GB)', 'Total Savings (GB)'
        ]

        # Format numbers
        display_df['Avg Savings %'] = display_df['Avg Savings %'].round(1)
        display_df['Avg Ratio'] = display_df['Avg Ratio'].round(2)
        display_df['Total Size (GB)'] = display_df['Total Size (GB)'].round(2)
        display_df['Total Savings (GB)'] = display_df['Total Savings (GB)'].round(2)

        st.dataframe(display_df, use_container_width=True, hide_index=True)

    st.markdown("---")

    # Table-specific comparison
    st.subheader("🔍 Compare Strategies for Specific Table")

    col1, col2 = st.columns([2, 1])

    with col1:
        owner = st.text_input("Schema Owner", value="HR")
        table_name = st.text_input("Table Name", value="EMPLOYEES")

    with col2:
        st.markdown("<br>", unsafe_allow_html=True)
        compare_button = st.button("🔍 Compare Strategies", use_container_width=True)

    if compare_button and owner and table_name:
        with st.spinner(f"Comparing strategies for {owner}.{table_name}..."):
            comparison = api_client.compare_strategies(owner, table_name)

            if "error" in comparison:
                st.error(f"Comparison failed: {comparison['error']}")
            elif "items" in comparison and comparison["items"]:
                comp_df = pd.DataFrame(comparison["items"])

                # Show current table info
                if not comp_df.empty:
                    st.markdown(f"""
                    <div class="metric-card">
                        <h4>Table Information</h4>
                        <strong>Owner:</strong> {owner}<br>
                        <strong>Table:</strong> {table_name}<br>
                        <strong>Current Size:</strong> {comp_df.iloc[0].get('current_size_mb', 0):.2f} MB<br>
                        <strong>Row Count:</strong> {comp_df.iloc[0].get('row_count', 0):,}
                    </div>
                    """, unsafe_allow_html=True)

                st.markdown("---")

                # Strategy comparison chart
                fig = go.Figure()

                fig.add_trace(go.Bar(
                    x=comp_df['strategy'],
                    y=comp_df['estimated_size_mb'],
                    name='Estimated Size (MB)',
                    marker_color=config.CHART_COLORS['primary'],
                    text=comp_df['estimated_size_mb'].round(2),
                    textposition='auto'
                ))

                # Add current size line
                current_size = comp_df.iloc[0].get('current_size_mb', 0)
                fig.add_hline(
                    y=current_size,
                    line_dash="dash",
                    line_color=config.CHART_COLORS['danger'],
                    annotation_text=f"Current: {current_size:.2f} MB"
                )

                fig.update_layout(
                    xaxis_title="Strategy",
                    yaxis_title="Size (MB)",
                    height=400,
                    showlegend=False
                )

                st.plotly_chart(fig, use_container_width=True)

                # Comparison table
                st.markdown("---")
                st.subheader("📊 Detailed Comparison")

                display_df = comp_df[[
                    'strategy', 'estimated_size_mb', 'savings_pct',
                    'compression_ratio', 'estimated_blocks'
                ]].copy()

                display_df.columns = [
                    'Strategy', 'Size (MB)', 'Savings %',
                    'Ratio', 'Blocks'
                ]

                # Format numbers
                display_df['Size (MB)'] = display_df['Size (MB)'].round(2)
                display_df['Savings %'] = display_df['Savings %'].round(1)
                display_df['Ratio'] = display_df['Ratio'].round(2)

                # Highlight best strategy
                best_idx = display_df['Savings %'].idxmax()

                st.dataframe(
                    display_df.style.highlight_max(
                        subset=['Savings %'],
                        color='lightgreen'
                    ),
                    use_container_width=True,
                    hide_index=True
                )

                # Recommendation
                best_strategy = display_df.iloc[best_idx]['Strategy']
                best_savings = display_df.iloc[best_idx]['Savings %']

                st.success(f"💡 **Recommended Strategy:** {best_strategy} ({best_savings:.1f}% savings)")

            else:
                st.warning("No comparison data available for this table")

    st.markdown("---")

    # Strategy selection guide
    st.subheader("📚 Strategy Selection Guide")

    col1, col2 = st.columns(2)

    with col1:
        st.markdown("""
        <div class="metric-card">
            <h4>QUERY LOW</h4>
            <strong>Best for:</strong> Tables with frequent queries and moderate data changes<br>
            <strong>Compression:</strong> Moderate (3-5x)<br>
            <strong>Performance:</strong> Minimal query impact<br>
            <strong>Use case:</strong> Active transactional tables
        </div>
        <br>
        <div class="metric-card">
            <h4>ARCHIVE LOW</h4>
            <strong>Best for:</strong> Historical data with occasional queries<br>
            <strong>Compression:</strong> High (5-10x)<br>
            <strong>Performance:</strong> Some query overhead<br>
            <strong>Use case:</strong> Archive and reporting tables
        </div>
        """, unsafe_allow_html=True)

    with col2:
        st.markdown("""
        <div class="metric-card">
            <h4>QUERY HIGH</h4>
            <strong>Best for:</strong> Read-heavy tables with minimal changes<br>
            <strong>Compression:</strong> High (5-8x)<br>
            <strong>Performance:</strong> Slight query impact<br>
            <strong>Use case:</strong> Data warehouse fact tables
        </div>
        <br>
        <div class="metric-card">
            <h4>ARCHIVE HIGH</h4>
            <strong>Best for:</strong> Cold data rarely accessed<br>
            <strong>Compression:</strong> Maximum (10-15x)<br>
            <strong>Performance:</strong> Higher query overhead<br>
            <strong>Use case:</strong> Long-term archival data
        </div>
        """, unsafe_allow_html=True)


if __name__ == "__main__":
    show_strategies_page()
