"""
Strategies Page - HCC Compression Advisor
View and compare compression strategies
"""

import streamlit as st
import pandas as pd
import plotly.graph_objects as go
import plotly.express as px
from utils.db_queries import CompressionQueries
from config import config


def show_strategies_page():
    """Display strategies page"""

    st.title("Compression Strategies")
    st.markdown("View and compare HCC compression strategies")
    st.markdown("---")

    # Strategy overview
    st.subheader("Available Strategies")

    strategies_df = CompressionQueries.get_strategies()

    if strategies_df.empty:
        st.info("No strategy information available")
        return

    # Display strategy cards
    for _, strategy_data in strategies_df.iterrows():
        # Handle column case (Oracle returns uppercase)
        strategy_name = strategy_data.get('STRATEGY_NAME', strategy_data.get('strategy_name', 'Unknown'))

        with st.expander(f"{strategy_name}", expanded=False):
            col1, col2 = st.columns(2)

            with col1:
                description = strategy_data.get('DESCRIPTION', strategy_data.get('description', 'N/A'))
                best_for = strategy_data.get('BEST_FOR', strategy_data.get('best_for', 'General purpose'))
                compression_level = strategy_data.get('COMPRESSION_LEVEL', strategy_data.get('compression_level', 'N/A'))

                st.markdown(f"""
                **Description:** {description}

                **Best For:**
                - {best_for}

                **Compression Level:** {compression_level}
                """)

            with col2:
                avg_ratio = strategy_data.get('AVG_COMPRESSION_RATIO', strategy_data.get('avg_compression_ratio', 0)) or 0
                avg_savings = strategy_data.get('AVG_SAVINGS_PCT', strategy_data.get('avg_savings_pct', 0)) or 0
                perf_impact = strategy_data.get('PERFORMANCE_IMPACT', strategy_data.get('performance_impact', 'N/A'))

                st.markdown(f"""
                **Typical Compression Ratio:** {avg_ratio:.2f}x

                **Average Savings:** {avg_savings:.1f}%

                **Performance Impact:** {perf_impact}
                """)

    st.markdown("---")

    # Strategy comparison
    st.subheader("Strategy Performance Comparison")

    # Fetch savings by strategy
    strategy_stats_df = CompressionQueries.get_savings_by_strategy()

    if not strategy_stats_df.empty:
        # Handle column name case
        strategy_col = 'STRATEGY' if 'STRATEGY' in strategy_stats_df.columns else 'strategy'
        savings_col = 'AVG_SAVINGS_PCT' if 'AVG_SAVINGS_PCT' in strategy_stats_df.columns else 'avg_savings_pct'
        ratio_col = 'AVG_COMPRESSION_RATIO' if 'AVG_COMPRESSION_RATIO' in strategy_stats_df.columns else 'avg_compression_ratio'
        count_col = 'TABLE_COUNT' if 'TABLE_COUNT' in strategy_stats_df.columns else 'table_count'
        size_col = 'TOTAL_SIZE_GB' if 'TOTAL_SIZE_GB' in strategy_stats_df.columns else 'total_size_gb'
        total_savings_col = 'TOTAL_SAVINGS_GB' if 'TOTAL_SAVINGS_GB' in strategy_stats_df.columns else 'total_savings_gb'

        # Create comparison chart
        fig = go.Figure()

        fig.add_trace(go.Bar(
            name='Average Savings %',
            x=strategy_stats_df[strategy_col],
            y=strategy_stats_df[savings_col],
            marker_color=config.CHART_COLORS['primary'],
            yaxis='y',
            offsetgroup=1
        ))

        fig.add_trace(go.Bar(
            name='Compression Ratio',
            x=strategy_stats_df[strategy_col],
            y=strategy_stats_df[ratio_col],
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
        st.subheader("Strategy Statistics")

        # Rename columns for display
        display_df = strategy_stats_df.copy()
        display_df.columns = [col.lower() for col in display_df.columns]

        # Select and rename columns
        col_mapping = {
            'strategy': 'Strategy',
            'table_count': 'Tables',
            'avg_savings_pct': 'Avg Savings %',
            'avg_compression_ratio': 'Avg Ratio',
            'total_size_gb': 'Total Size (GB)',
            'total_savings_gb': 'Total Savings (GB)'
        }

        available_cols = [c for c in col_mapping.keys() if c in display_df.columns]
        display_df = display_df[available_cols].copy()
        display_df.columns = [col_mapping[c] for c in available_cols]

        # Format numbers
        if 'Avg Savings %' in display_df.columns:
            display_df['Avg Savings %'] = display_df['Avg Savings %'].round(1)
        if 'Avg Ratio' in display_df.columns:
            display_df['Avg Ratio'] = display_df['Avg Ratio'].round(2)
        if 'Total Size (GB)' in display_df.columns:
            display_df['Total Size (GB)'] = display_df['Total Size (GB)'].round(2)
        if 'Total Savings (GB)' in display_df.columns:
            display_df['Total Savings (GB)'] = display_df['Total Savings (GB)'].round(2)

        st.dataframe(display_df, use_container_width=True, hide_index=True)

    st.markdown("---")

    # Table-specific comparison
    st.subheader("Compare Strategies for Specific Table")

    # Get available schemas
    schemas = CompressionQueries.get_available_schemas()

    col1, col2 = st.columns([2, 1])

    with col1:
        if schemas:
            owner = st.selectbox("Schema Owner", options=schemas, index=0)
        else:
            owner = st.text_input("Schema Owner", value="HR")
        table_name = st.text_input("Table Name", value="EMPLOYEES")

    with col2:
        st.markdown("<br>", unsafe_allow_html=True)
        compare_button = st.button("Compare Strategies", use_container_width=True)

    if compare_button and owner and table_name:
        with st.spinner(f"Comparing strategies for {owner}.{table_name}..."):
            comp_df = CompressionQueries.compare_strategies(owner, table_name)

            if comp_df.empty:
                st.warning("No comparison data available for this table")
            else:
                # Normalize column names to lowercase
                comp_df.columns = [col.lower() for col in comp_df.columns]

                # Show current table info
                current_size = comp_df.iloc[0].get('current_size_mb', 0) or 0
                row_count = comp_df.iloc[0].get('row_count', 0) or 0

                st.markdown(f"""
                <div class="metric-card">
                    <h4>Table Information</h4>
                    <strong>Owner:</strong> {owner}<br>
                    <strong>Table:</strong> {table_name}<br>
                    <strong>Current Size:</strong> {current_size:.2f} MB<br>
                    <strong>Row Count:</strong> {int(row_count):,}
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
                st.subheader("Detailed Comparison")

                display_cols = ['strategy', 'estimated_size_mb', 'savings_pct', 'compression_ratio']
                if 'estimated_blocks' in comp_df.columns:
                    display_cols.append('estimated_blocks')

                display_df = comp_df[display_cols].copy()

                col_names = ['Strategy', 'Size (MB)', 'Savings %', 'Ratio']
                if 'estimated_blocks' in display_cols:
                    col_names.append('Blocks')
                display_df.columns = col_names

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
                best_strategy = display_df.loc[best_idx, 'Strategy']
                best_savings = display_df.loc[best_idx, 'Savings %']

                st.success(f"**Recommended Strategy:** {best_strategy} ({best_savings:.1f}% savings)")


if __name__ == "__main__":
    show_strategies_page()
