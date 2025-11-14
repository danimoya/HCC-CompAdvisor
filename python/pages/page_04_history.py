"""
History Page - HCC Compression Advisor
View execution history and analytics
"""

import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from datetime import datetime, timedelta
from utils.api_client import get_api_client
from config import config


def show_history_page():
    """Display history page"""

    st.title("🕐 Execution History")
    st.markdown("View and analyze compression execution history")
    st.markdown("---")

    api_client = get_api_client()

    # Date range filter
    col1, col2, col3 = st.columns([2, 2, 1])

    with col1:
        start_date = st.date_input(
            "Start Date",
            value=datetime.now() - timedelta(days=30)
        )

    with col2:
        end_date = st.date_input(
            "End Date",
            value=datetime.now()
        )

    with col3:
        limit = st.number_input(
            "Max Results",
            min_value=10,
            max_value=1000,
            value=100,
            step=10
        )

    # Fetch history
    with st.spinner("Loading execution history..."):
        history = api_client.get_execution_history(
            start_date=start_date.isoformat(),
            end_date=end_date.isoformat(),
            limit=limit
        )

    if "error" in history:
        st.error("Failed to load execution history")
        return

    if "items" not in history or not history["items"]:
        st.warning("No execution history found for the selected date range")
        return

    df = pd.DataFrame(history["items"])

    # Convert dates
    if 'executed_at' in df.columns:
        df['executed_at'] = pd.to_datetime(df['executed_at'])

    # Summary metrics
    col1, col2, col3, col4 = st.columns(4)

    with col1:
        st.metric(
            label="Total Executions",
            value=f"{len(df):,}"
        )

    with col2:
        completed = len(df[df['status'] == 'COMPLETED'])
        success_rate = (completed / len(df) * 100) if len(df) > 0 else 0
        st.metric(
            label="Success Rate",
            value=f"{success_rate:.1f}%",
            delta=f"{completed} / {len(df)}"
        )

    with col3:
        total_savings = df['savings_pct'].mean() if 'savings_pct' in df.columns else 0
        st.metric(
            label="Avg Savings",
            value=f"{total_savings:.1f}%"
        )

    with col4:
        unique_tables = df['table_name'].nunique() if 'table_name' in df.columns else 0
        st.metric(
            label="Tables Processed",
            value=f"{unique_tables:,}"
        )

    st.markdown("---")

    # Visualizations
    col1, col2 = st.columns(2)

    with col1:
        st.subheader("📈 Executions Over Time")

        if 'executed_at' in df.columns:
            # Group by date
            daily_counts = df.groupby(df['executed_at'].dt.date).size().reset_index()
            daily_counts.columns = ['Date', 'Count']

            fig = px.line(
                daily_counts,
                x='Date',
                y='Count',
                markers=True,
                color_discrete_sequence=[config.CHART_COLORS['primary']]
            )

            fig.update_layout(
                xaxis_title="Date",
                yaxis_title="Number of Executions",
                height=400
            )

            st.plotly_chart(fig, use_container_width=True)

    with col2:
        st.subheader("📊 Executions by Status")

        status_counts = df['status'].value_counts()

        colors = {
            'COMPLETED': config.CHART_COLORS['success'],
            'RUNNING': config.CHART_COLORS['info'],
            'FAILED': config.CHART_COLORS['danger'],
            'PENDING': config.CHART_COLORS['warning']
        }

        fig = go.Figure(data=[
            go.Pie(
                labels=status_counts.index,
                values=status_counts.values,
                marker=dict(colors=[colors.get(status, config.CHART_COLORS['secondary']) for status in status_counts.index])
            )
        ])

        fig.update_layout(height=400)
        st.plotly_chart(fig, use_container_width=True)

    # Strategy analysis
    st.markdown("---")
    col1, col2 = st.columns(2)

    with col1:
        st.subheader("🎯 Executions by Strategy")

        if 'strategy' in df.columns:
            strategy_counts = df['strategy'].value_counts()

            fig = go.Figure(data=[
                go.Bar(
                    x=strategy_counts.index,
                    y=strategy_counts.values,
                    marker_color=config.CHART_COLORS['primary']
                )
            ])

            fig.update_layout(
                xaxis_title="Strategy",
                yaxis_title="Number of Executions",
                height=400
            )

            st.plotly_chart(fig, use_container_width=True)

    with col2:
        st.subheader("💾 Savings Distribution")

        if 'savings_pct' in df.columns:
            fig = px.histogram(
                df,
                x='savings_pct',
                nbins=20,
                color_discrete_sequence=[config.CHART_COLORS['success']]
            )

            fig.update_layout(
                xaxis_title="Savings (%)",
                yaxis_title="Number of Executions",
                height=400
            )

            st.plotly_chart(fig, use_container_width=True)

    # Top tables by savings
    st.markdown("---")
    st.subheader("🏆 Top Tables by Savings")

    if 'savings_pct' in df.columns:
        top_tables = df.nlargest(10, 'savings_pct')

        fig = go.Figure()

        fig.add_trace(go.Bar(
            x=top_tables['table_name'],
            y=top_tables['savings_pct'],
            marker_color=config.CHART_COLORS['success'],
            text=top_tables['savings_pct'].round(1),
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

    # Detailed history table
    st.markdown("---")
    st.subheader("📋 Execution History Details")

    # Prepare display DataFrame
    display_columns = [
        'execution_id', 'table_owner', 'table_name', 'strategy',
        'status', 'savings_pct', 'dry_run', 'executed_at'
    ]

    display_df = df[display_columns].copy()

    display_df.columns = [
        'ID', 'Owner', 'Table', 'Strategy',
        'Status', 'Savings %', 'Dry Run', 'Executed At'
    ]

    # Format dates
    if 'Executed At' in display_df.columns:
        display_df['Executed At'] = display_df['Executed At'].dt.strftime('%Y-%m-%d %H:%M:%S')

    # Format numbers
    if 'Savings %' in display_df.columns:
        display_df['Savings %'] = display_df['Savings %'].round(1)

    # Display with color coding for status
    st.dataframe(
        display_df,
        use_container_width=True,
        hide_index=True
    )

    # Export options
    st.markdown("---")
    st.subheader("📥 Export History")

    col1, col2 = st.columns(2)

    with col1:
        csv_data = display_df.to_csv(index=False)
        st.download_button(
            label="📄 Download CSV",
            data=csv_data,
            file_name=f"hcc_history_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
            mime="text/csv",
            use_container_width=True
        )

    with col2:
        import io
        buffer = io.BytesIO()
        with pd.ExcelWriter(buffer, engine='xlsxwriter') as writer:
            display_df.to_excel(writer, sheet_name='Execution History', index=False)

        st.download_button(
            label="📊 Download Excel",
            data=buffer.getvalue(),
            file_name=f"hcc_history_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            use_container_width=True
        )


if __name__ == "__main__":
    show_history_page()
