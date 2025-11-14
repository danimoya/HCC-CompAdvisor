"""
Execution Page - HCC Compression Advisor
Execute compression recommendations
"""

import streamlit as st
import pandas as pd
import time
from utils.api_client import get_api_client
from config import config


def show_execution_page():
    """Display execution page"""

    st.title("▶️ Execute Compression")
    st.markdown("Execute compression for selected recommendations")
    st.markdown("---")

    api_client = get_api_client()

    # Execution mode selector
    tab1, tab2, tab3 = st.tabs(["Single Table", "Batch Execution", "Monitor Progress"])

    with tab1:
        show_single_execution(api_client)

    with tab2:
        show_batch_execution(api_client)

    with tab3:
        show_execution_monitor(api_client)


def show_single_execution(api_client):
    """Show single table execution interface"""

    st.subheader("🎯 Execute Single Table Compression")

    # Fetch recommendations
    recommendations = api_client.get_recommendations(limit=100, min_savings_pct=10.0)

    if "items" not in recommendations or not recommendations["items"]:
        st.warning("No recommendations available. Run an analysis first.")
        return

    df = pd.DataFrame(recommendations["items"])

    # Table selector
    col1, col2 = st.columns([2, 1])

    with col1:
        selected_index = st.selectbox(
            "Select Table",
            options=range(len(df)),
            format_func=lambda x: f"{df.iloc[x]['table_owner']}.{df.iloc[x]['table_name']} - {df.iloc[x]['savings_pct']:.1f}% savings"
        )

    with col2:
        st.info(f"""
        **Selected Table:**
        {df.iloc[selected_index]['table_owner']}.{df.iloc[selected_index]['table_name']}
        """)

    # Execution parameters
    st.markdown("---")
    st.subheader("⚙️ Execution Parameters")

    col1, col2, col3 = st.columns(3)

    with col1:
        dry_run = st.checkbox(
            "Dry Run (Preview Only)",
            value=True,
            help="Execute without making actual changes"
        )

    with col2:
        parallel_degree = st.slider(
            "Parallel Degree",
            min_value=1,
            max_value=16,
            value=4,
            help="Number of parallel processes"
        )

    with col3:
        confirm_execution = st.checkbox(
            "Confirm Execution",
            value=False,
            help="Confirm you want to execute this compression"
        )

    # Display details
    selected_row = df.iloc[selected_index]

    col1, col2 = st.columns(2)

    with col1:
        st.markdown(f"""
        <div class="metric-card">
            <h4>Current State</h4>
            <strong>Size:</strong> {selected_row['current_size_mb']:.2f} MB<br>
            <strong>Rows:</strong> {selected_row['estimated_rows']:,}<br>
            <strong>Compression:</strong> {selected_row.get('current_compression', 'NONE')}
        </div>
        """, unsafe_allow_html=True)

    with col2:
        st.markdown(f"""
        <div class="metric-card success-card">
            <h4>After Compression</h4>
            <strong>Strategy:</strong> {selected_row['recommended_strategy']}<br>
            <strong>Estimated Size:</strong> {selected_row['estimated_size_mb']:.2f} MB<br>
            <strong>Savings:</strong> {selected_row['savings_pct']:.1f}% ({selected_row['compression_ratio']:.2f}x)
        </div>
        """, unsafe_allow_html=True)

    # Execute button
    st.markdown("---")

    if not dry_run and not confirm_execution:
        st.warning("⚠️ Please confirm execution for production changes")

    col1, col2, col3 = st.columns([1, 1, 1])

    with col2:
        execute_button = st.button(
            "🚀 Execute Compression",
            disabled=(not dry_run and not confirm_execution),
            use_container_width=True
        )

    if execute_button:
        with st.spinner("Executing compression..."):
            result = api_client.execute_compression(
                recommendation_id=int(selected_row['recommendation_id']),
                dry_run=dry_run,
                parallel_degree=parallel_degree
            )

            if "error" in result:
                st.error(f"Execution failed: {result['error']}")
            elif "items" in result and result["items"]:
                execution_data = result["items"][0]
                st.success(f"✅ Execution started! ID: {execution_data.get('execution_id')}")

                # Store execution ID for monitoring
                st.session_state.last_execution_id = execution_data.get('execution_id')

                # Show execution details
                st.json(execution_data)
            else:
                st.success("Execution completed successfully!")


def show_batch_execution(api_client):
    """Show batch execution interface"""

    st.subheader("📦 Batch Compression Execution")

    # Fetch recommendations
    recommendations = api_client.get_recommendations(limit=100, min_savings_pct=10.0)

    if "items" not in recommendations or not recommendations["items"]:
        st.warning("No recommendations available. Run an analysis first.")
        return

    df = pd.DataFrame(recommendations["items"])

    # Multi-select
    st.markdown("Select multiple tables for batch execution:")

    selected_tables = st.multiselect(
        "Tables",
        options=df['recommendation_id'].tolist(),
        format_func=lambda x: f"{df[df['recommendation_id']==x].iloc[0]['table_owner']}.{df[df['recommendation_id']==x].iloc[0]['table_name']}"
    )

    if selected_tables:
        # Show summary
        selected_df = df[df['recommendation_id'].isin(selected_tables)]

        col1, col2, col3 = st.columns(3)

        with col1:
            st.metric("Selected Tables", len(selected_tables))

        with col2:
            total_size = selected_df['current_size_mb'].sum()
            st.metric("Total Size", f"{total_size:.2f} MB")

        with col3:
            avg_savings = selected_df['savings_pct'].mean()
            st.metric("Avg Savings", f"{avg_savings:.1f}%")

        # Execution parameters
        st.markdown("---")

        col1, col2 = st.columns(2)

        with col1:
            batch_dry_run = st.checkbox(
                "Dry Run (Preview Only)",
                value=True,
                key="batch_dry_run"
            )

        with col2:
            batch_parallel = st.slider(
                "Parallel Degree",
                min_value=1,
                max_value=16,
                value=4,
                key="batch_parallel"
            )

        # Execute batch
        col1, col2, col3 = st.columns([1, 1, 1])

        with col2:
            if st.button("🚀 Execute Batch", use_container_width=True):
                with st.spinner(f"Executing {len(selected_tables)} compressions..."):
                    result = api_client.batch_execute(
                        recommendation_ids=selected_tables,
                        dry_run=batch_dry_run,
                        parallel_degree=batch_parallel
                    )

                    if "error" in result:
                        st.error(f"Batch execution failed: {result['error']}")
                    else:
                        st.success(f"✅ Batch execution started for {len(selected_tables)} tables!")


def show_execution_monitor(api_client):
    """Show execution monitoring interface"""

    st.subheader("📊 Execution Progress Monitor")

    # Fetch recent executions
    history = api_client.get_execution_history(limit=20)

    if "items" not in history or not history["items"]:
        st.info("No executions to monitor")
        return

    df = pd.DataFrame(history["items"])

    # Display active executions
    active_df = df[df['status'].isin(['RUNNING', 'PENDING'])]

    if not active_df.empty:
        st.markdown("### ⏳ Active Executions")

        for _, row in active_df.iterrows():
            with st.expander(f"🔄 {row['table_owner']}.{row['table_name']} - {row['status']}"):
                col1, col2 = st.columns(2)

                with col1:
                    st.markdown(f"""
                    **Execution ID:** {row['execution_id']}<br>
                    **Strategy:** {row['strategy']}<br>
                    **Started:** {row['executed_at']}<br>
                    **Status:** {row['status']}
                    """, unsafe_allow_html=True)

                with col2:
                    st.markdown(f"""
                    **Dry Run:** {row.get('dry_run', 'N/A')}<br>
                    **Parallel Degree:** {row.get('parallel_degree', 'N/A')}<br>
                    **Progress:** {row.get('progress_pct', 0):.1f}%
                    """, unsafe_allow_html=True)

                # Progress bar
                st.progress(row.get('progress_pct', 0) / 100)

                # Refresh button
                if st.button(f"🔄 Refresh", key=f"refresh_{row['execution_id']}"):
                    st.rerun()

    # Recent completed executions
    st.markdown("---")
    st.markdown("### ✅ Recent Completed Executions")

    completed_df = df[df['status'] == 'COMPLETED'].head(10)

    if not completed_df.empty:
        display_df = completed_df[[
            'execution_id', 'table_owner', 'table_name',
            'strategy', 'savings_pct', 'executed_at'
        ]].copy()

        display_df.columns = [
            'ID', 'Owner', 'Table', 'Strategy', 'Savings %', 'Executed At'
        ]

        st.dataframe(display_df, use_container_width=True, hide_index=True)
    else:
        st.info("No completed executions")


if __name__ == "__main__":
    show_execution_page()
