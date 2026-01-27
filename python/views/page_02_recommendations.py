"""
Recommendations Page - HCC Compression Advisor
View and filter compression recommendations with batch execution capability
"""

import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import io
from utils.db_queries import CompressionQueries
from config import config


def show_recommendations_page():
    """Display recommendations page"""

    st.title("Compression Recommendations")
    st.markdown("View, filter, and execute compression candidates")
    st.markdown("---")

    # Filters (outside tabs - always visible)
    st.subheader("Filters")

    # Get available schemas for filter
    schemas = CompressionQueries.get_available_schemas()

    col1, col2, col3, col4, col5 = st.columns(5)

    with col1:
        schema_options = ["All Schemas"] + schemas
        schema_filter = st.selectbox(
            "Schema",
            options=schema_options,
            index=0
        )

    with col2:
        strategy_filter = st.selectbox(
            "Strategy",
            options=["All"] + config.COMPRESSION_STRATEGIES,
            index=0
        )

    with col3:
        min_savings = st.slider(
            "Min Savings %",
            min_value=0,
            max_value=100,
            value=10,
            step=5
        )

    with col4:
        min_size = st.number_input(
            "Min Size (MB)",
            min_value=0,
            max_value=10000,
            value=0,
            step=10
        )

    with col5:
        limit = st.number_input(
            "Max Results",
            min_value=10,
            max_value=1000,
            value=100,
            step=10
        )

    # Fetch recommendations using direct database query
    strategy_param = None if strategy_filter == "All" else strategy_filter
    schema_param = None if schema_filter == "All Schemas" else schema_filter

    with st.spinner("Loading recommendations..."):
        df = CompressionQueries.get_recommendations(
            schema=schema_param,
            strategy=strategy_param,
            min_savings_pct=min_savings,
            min_size_mb=min_size,
            limit=limit
        )

    if df.empty:
        st.warning("No recommendations found. Try adjusting your filters or run a new analysis.")
        return

    # Normalize column names to lowercase
    df.columns = [col.lower() for col in df.columns]

    st.markdown("---")

    # Two tabs: Overview & Charts | Detailed Recommendations
    tab1, tab2 = st.tabs(["Overview & Charts", "Detailed Recommendations"])

    # =========================================================================
    # TAB 1: Overview & Charts
    # =========================================================================
    with tab1:
        show_overview_tab(df)

    # =========================================================================
    # TAB 2: Detailed Recommendations with Batch Actions
    # =========================================================================
    with tab2:
        show_detailed_tab(df)


def show_overview_tab(df: pd.DataFrame):
    """Display overview metrics and charts"""

    # Summary metrics
    col1, col2, col3, col4 = st.columns(4)

    with col1:
        st.metric(
            label="Total Candidates",
            value=f"{len(df):,}"
        )

    with col2:
        total_current = df['current_size_mb'].sum() / 1024 if 'current_size_mb' in df.columns else 0
        st.metric(
            label="Total Current Size",
            value=f"{total_current:.2f} GB"
        )

    with col3:
        total_compressed = df['estimated_size_mb'].sum() / 1024 if 'estimated_size_mb' in df.columns else 0
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

    # Visualizations - Two columns
    col1, col2 = st.columns(2)

    with col1:
        st.subheader("Recommendations by Strategy")

        if 'recommended_strategy' in df.columns:
            strategy_counts = df['recommended_strategy'].value_counts()

            fig = px.pie(
                values=strategy_counts.values,
                names=strategy_counts.index,
                color_discrete_sequence=px.colors.qualitative.Set3
            )

            fig.update_layout(height=400)
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("No strategy data available")

    with col2:
        st.subheader("Savings Distribution")

        if 'savings_pct' in df.columns:
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
        else:
            st.info("No savings data available")

    st.markdown("---")

    # Top recommendations bar chart
    st.subheader("Top Recommendations by Savings")

    top_n = st.slider("Show top N tables", min_value=5, max_value=50, value=10, step=5)

    if 'savings_pct' in df.columns and 'table_name' in df.columns:
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
    else:
        st.info("Insufficient data for top recommendations chart")


def show_detailed_tab(df: pd.DataFrame):
    """Display detailed recommendations with multi-select and batch actions"""

    st.subheader("Select Tables for Export or Execution")
    st.markdown("Use checkboxes to select tables, then choose an action below. Click on a row to view analysis details.")

    # Prepare display DataFrame with selection column
    column_mapping = {
        'recommendation_id': 'ID',
        'table_owner': 'Owner',
        'table_name': 'Table',
        'current_size_mb': 'Current (MB)',
        'recommended_strategy': 'Strategy',
        'estimated_size_mb': 'Compressed (MB)',
        'savings_pct': 'Savings %',
        'compression_ratio': 'Ratio',
        'estimated_rows': 'Rows'
    }

    # Filter to available columns
    available_cols = [c for c in column_mapping.keys() if c in df.columns]
    display_df = df[available_cols].copy()

    # Add selection column at the beginning
    display_df.insert(0, 'select', False)

    # Format numbers
    if 'current_size_mb' in display_df.columns:
        display_df['current_size_mb'] = display_df['current_size_mb'].round(2)
    if 'estimated_size_mb' in display_df.columns:
        display_df['estimated_size_mb'] = display_df['estimated_size_mb'].round(2)
    if 'savings_pct' in display_df.columns:
        display_df['savings_pct'] = display_df['savings_pct'].round(1)
    if 'compression_ratio' in display_df.columns:
        display_df['compression_ratio'] = display_df['compression_ratio'].round(2)

    # Rename columns for display
    rename_map = {'select': 'Select'}
    rename_map.update({k: v for k, v in column_mapping.items() if k in display_df.columns})
    display_df = display_df.rename(columns=rename_map)

    # Data editor with checkboxes
    edited_df = st.data_editor(
        display_df,
        use_container_width=True,
        hide_index=True,
        column_config={
            "Select": st.column_config.CheckboxColumn(
                "Select",
                help="Select for batch action",
                default=False,
                width="small"
            ),
            "ID": st.column_config.NumberColumn("ID", width="small"),
            "Owner": st.column_config.TextColumn("Owner", width="medium"),
            "Table": st.column_config.TextColumn("Table", width="medium"),
            "Current (MB)": st.column_config.NumberColumn("Current (MB)", format="%.2f"),
            "Compressed (MB)": st.column_config.NumberColumn("Compressed (MB)", format="%.2f"),
            "Savings %": st.column_config.NumberColumn("Savings %", format="%.1f%%"),
            "Strategy": st.column_config.TextColumn("Strategy", width="medium"),
            "Ratio": st.column_config.NumberColumn("Ratio", format="%.2f"),
            "Rows": st.column_config.NumberColumn("Rows", format="%d"),
        },
        disabled=[col for col in display_df.columns if col != "Select"],
        key="recommendations_table"
    )

    # Analysis Details Viewer
    st.markdown("---")
    st.subheader("View Analysis Details")

    # Dropdown to select a table for detailed view
    table_options = []
    for _, row in df.iterrows():
        rec_id = row.get('recommendation_id', row.get('RECOMMENDATION_ID', 'N/A'))
        owner = row.get('table_owner', row.get('TABLE_OWNER', ''))
        tbl = row.get('table_name', row.get('TABLE_NAME', ''))
        table_options.append(f"{rec_id}: {owner}.{tbl}")

    selected_detail = st.selectbox(
        "Select a table to view detailed analysis",
        options=["Select a table..."] + table_options,
        key="detail_selector"
    )

    if selected_detail and selected_detail != "Select a table...":
        # Parse the selection to get analysis_id
        analysis_id = int(selected_detail.split(":")[0])
        show_analysis_details(analysis_id)

    # Get selected rows
    selected_mask = edited_df['Select'] == True
    selected_df = edited_df[selected_mask]
    selected_count = len(selected_df)

    # Selection summary
    st.markdown("---")

    if selected_count > 0:
        col1, col2, col3 = st.columns(3)

        with col1:
            st.metric("Selected Tables", selected_count)

        with col2:
            if 'Current (MB)' in selected_df.columns:
                total_size = selected_df['Current (MB)'].sum()
                st.metric("Total Size", f"{total_size:.2f} MB")
            else:
                st.metric("Total Size", "N/A")

        with col3:
            if 'Savings %' in selected_df.columns:
                avg_savings = selected_df['Savings %'].mean()
                st.metric("Avg Savings", f"{avg_savings:.1f}%")
            else:
                st.metric("Avg Savings", "N/A")

        st.markdown("---")

        # Action buttons
        st.subheader("Actions for Selected Tables")

        col1, col2, col3, col4 = st.columns(4)

        with col1:
            # CSV export for selected
            export_df = selected_df.drop(columns=['Select'])
            csv_data = export_df.to_csv(index=False)
            st.download_button(
                label="Download CSV",
                data=csv_data,
                file_name=f"selected_recommendations_{pd.Timestamp.now().strftime('%Y%m%d_%H%M%S')}.csv",
                mime="text/csv",
                use_container_width=True
            )

        with col2:
            # Excel export for selected
            buffer = io.BytesIO()
            export_df = selected_df.drop(columns=['Select'])
            with pd.ExcelWriter(buffer, engine='xlsxwriter') as writer:
                export_df.to_excel(writer, sheet_name='Selected', index=False)

            st.download_button(
                label="Download Excel",
                data=buffer.getvalue(),
                file_name=f"selected_recommendations_{pd.Timestamp.now().strftime('%Y%m%d_%H%M%S')}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                use_container_width=True
            )

        with col3:
            dry_run = st.checkbox("Dry Run (Preview)", value=True, key="batch_dry_run")

        with col4:
            parallel_degree = st.slider("Parallel", min_value=1, max_value=16, value=4, key="batch_parallel")

        # Execute button
        st.markdown("")

        col1, col2, col3 = st.columns([1, 2, 1])

        with col2:
            execute_disabled = selected_count == 0
            execute_label = f"Execute {selected_count} Selected Tables" if selected_count > 0 else "Select Tables First"

            if st.button(
                execute_label,
                use_container_width=True,
                type="primary",
                disabled=execute_disabled
            ):
                execute_batch_compression(selected_df, df, dry_run, parallel_degree)

    else:
        st.info("Select one or more tables using the checkboxes to enable export and execution options.")

        # Still show export all option
        st.markdown("---")
        st.subheader("Export All Recommendations")

        col1, col2, col3 = st.columns([1, 1, 2])

        export_all_df = display_df.drop(columns=['Select'])

        with col1:
            csv_data = export_all_df.to_csv(index=False)
            st.download_button(
                label="Download All (CSV)",
                data=csv_data,
                file_name=f"all_recommendations_{pd.Timestamp.now().strftime('%Y%m%d_%H%M%S')}.csv",
                mime="text/csv",
                use_container_width=True
            )

        with col2:
            buffer = io.BytesIO()
            with pd.ExcelWriter(buffer, engine='xlsxwriter') as writer:
                export_all_df.to_excel(writer, sheet_name='Recommendations', index=False)

            st.download_button(
                label="Download All (Excel)",
                data=buffer.getvalue(),
                file_name=f"all_recommendations_{pd.Timestamp.now().strftime('%Y%m%d_%H%M%S')}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                use_container_width=True
            )


def show_analysis_details(analysis_id: int):
    """Display detailed analysis information for justification"""

    with st.spinner("Loading analysis details..."):
        justification = CompressionQueries.build_recommendation_justification(analysis_id)

    if justification.get('error'):
        st.error(justification['error'])
        return

    summary = justification.get('summary', {})
    compression = justification.get('compression_analysis', {})
    activity = justification.get('activity_metrics', {})
    storage = justification.get('storage', {})

    # Summary Section
    with st.expander("📊 Recommendation Summary", expanded=True):
        col1, col2, col3, col4 = st.columns(4)

        with col1:
            st.metric("Table", summary.get('table') or 'N/A')
        with col2:
            current_size = summary.get('current_size_mb') or 0
            st.metric("Current Size", f"{current_size:.2f} MB")
        with col3:
            st.metric("Recommended", summary.get('recommended') or 'N/A')
        with col4:
            savings_pct = summary.get('projected_savings_pct') or 0
            st.metric("Projected Savings", f"{savings_pct:.1f}%")

        st.markdown("**Recommendation Reason:**")
        st.info(summary.get('reason') or 'No specific reason recorded')

        confidence = summary.get('confidence_score') or 0
        st.progress(min(confidence / 100, 1.0), text=f"Confidence Score: {confidence:.0f}%")

    # Compression Ratios Comparison
    with st.expander("📈 Compression Ratio Analysis", expanded=True):
        st.markdown("**Comparison of compression methods tested:**")

        comp_data = []
        has_compression_data = False
        for method, data in compression.items():
            if method != 'best_ratio' and isinstance(data, dict):
                ratio = data.get('ratio', 0) or 0
                uncmp = data.get('uncompressed_blocks', 0) or 0
                cmp = data.get('compressed_blocks', 0) or 0
                if ratio > 0 or uncmp > 0:
                    has_compression_data = True
                savings_pct = ((uncmp - cmp) / uncmp * 100) if uncmp > 0 else 0
                comp_data.append({
                    'Method': method.upper().replace('_', ' '),
                    'Compression Ratio': f"{ratio:.2f}x" if ratio else "N/A",
                    'Uncompressed Blocks': f"{uncmp:,}" if uncmp else "N/A",
                    'Compressed Blocks': f"{cmp:,}" if cmp else "N/A",
                    'Block Reduction %': f"{savings_pct:.1f}%" if uncmp > 0 else "N/A"
                })

        if comp_data:
            comp_df = pd.DataFrame(comp_data)
            st.dataframe(comp_df, use_container_width=True, hide_index=True)

            if not has_compression_data:
                st.warning("No compression analysis data found. Run PKG_COMPRESSION_ADVISOR.ANALYZE_TABLE to collect compression ratios.")
            else:
                # Bar chart of compression ratios
                ratios = []
                labels = []
                for method, data in compression.items():
                    if method != 'best_ratio' and isinstance(data, dict):
                        ratio = data.get('ratio', 0) or 0
                        if ratio > 0:
                            ratios.append(ratio)
                            labels.append(method.upper().replace('_', ' '))

                if ratios:
                    fig = go.Figure(data=[
                        go.Bar(x=labels, y=ratios, marker_color=['#1f77b4', '#2ca02c', '#ff7f0e', '#d62728'][:len(ratios)])
                    ])
                    fig.update_layout(
                        title="Compression Ratio by Method",
                        xaxis_title="Compression Method",
                        yaxis_title="Compression Ratio (higher = better)",
                        height=300
                    )
                    st.plotly_chart(fig, use_container_width=True)

        best = compression.get('best_ratio', 0) or 0
        if best > 0:
            st.success(f"**Best Compression Ratio: {best:.2f}x**")
        else:
            st.info("Best compression ratio not yet calculated.")

    # Activity Metrics
    with st.expander("🔄 Activity & Hotness Analysis", expanded=False):
        col1, col2 = st.columns(2)

        with col1:
            st.markdown("**DML Activity:**")
            dml_data = {
                'Operation': ['Inserts', 'Updates', 'Deletes', 'Total DML'],
                'Count': [
                    f"{activity.get('inserts') or 0:,}",
                    f"{activity.get('updates') or 0:,}",
                    f"{activity.get('deletes') or 0:,}",
                    f"{activity.get('total_dml') or 0:,}"
                ]
            }
            st.dataframe(pd.DataFrame(dml_data), use_container_width=True, hide_index=True)

        with col2:
            st.markdown("**Read Activity:**")
            read_data = {
                'Metric': ['Logical Reads', 'Physical Reads'],
                'Count': [
                    f"{activity.get('logical_reads') or 0:,}",
                    f"{activity.get('physical_reads') or 0:,}"
                ]
            }
            st.dataframe(pd.DataFrame(read_data), use_container_width=True, hide_index=True)

        st.markdown("---")
        st.markdown("**Hotness Assessment:**")

        col1, col2, col3, col4 = st.columns(4)
        with col1:
            hotness = activity.get('hotness_score') or 0
            st.metric("Hotness Score", f"{hotness:.1f}")
        with col2:
            category = activity.get('hotness_category') or 'UNKNOWN'
            color = "🔴" if category == 'HOT' else "🟡" if category == 'WARM' else "🔵"
            st.metric("Category", f"{color} {category}")
        with col3:
            read_ratio = activity.get('read_ratio') or 0
            st.metric("Read Ratio", f"{read_ratio:.1%}")
        with col4:
            write_ratio = activity.get('write_ratio') or 0
            st.metric("Write Ratio", f"{write_ratio:.1%}")

        # Hotness explanation
        if hotness >= 70:
            st.warning("⚠️ **High Activity Table**: Frequent DML operations may cause row migration with aggressive compression. Consider OLTP compression.")
        elif hotness >= 30:
            st.info("ℹ️ **Moderate Activity**: Table has balanced read/write activity. Most compression methods suitable.")
        else:
            st.success("✅ **Low Activity Table**: Ideal candidate for aggressive compression (QUERY HIGH or ARCHIVE).")

    # Column Statistics
    with st.expander("📋 Column Statistics", expanded=False):
        parts = summary.get('table', '.').split('.')
        if len(parts) == 2:
            owner, table_name = parts
            col_stats = CompressionQueries.get_table_column_info(owner, table_name)

            if not col_stats.empty:
                col_stats.columns = [c.lower() for c in col_stats.columns]

                # Display column info
                display_cols = ['column_name', 'data_type', 'data_length', 'nullable',
                               'num_distinct', 'num_nulls', 'avg_col_len', 'histogram', 'compression_hint']
                available_display = [c for c in display_cols if c in col_stats.columns]

                if available_display:
                    st.dataframe(col_stats[available_display], use_container_width=True, hide_index=True)

                    # Summary stats
                    st.markdown("**Column Analysis Summary:**")
                    col1, col2, col3 = st.columns(3)
                    with col1:
                        st.metric("Total Columns", len(col_stats))
                    with col2:
                        nullable_count = (col_stats['nullable'] == 'Y').sum() if 'nullable' in col_stats.columns else 0
                        st.metric("Nullable Columns", nullable_count)
                    with col3:
                        if 'avg_col_len' in col_stats.columns:
                            avg_len = col_stats['avg_col_len'].mean()
                            st.metric("Avg Column Length", f"{avg_len:.1f}" if pd.notna(avg_len) else "N/A")
            else:
                st.info("Column statistics not available. Run DBMS_STATS.GATHER_TABLE_STATS to collect statistics.")

    # Storage Information
    with st.expander("💾 Storage Details", expanded=False):
        # Helper function for human-readable sizes
        def format_size(size_bytes):
            if size_bytes is None or size_bytes == 0:
                return "N/A"
            for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
                if abs(size_bytes) < 1024:
                    return f"{size_bytes:.2f} {unit}"
                size_bytes /= 1024
            return f"{size_bytes:.2f} PB"

        col1, col2, col3, col4 = st.columns(4)

        with col1:
            tablespace = storage.get('tablespace') or 'N/A'
            if tablespace == 'N/A' or not tablespace:
                # Try to get tablespace from summary table info
                parts = summary.get('table', '.').split('.')
                if len(parts) == 2:
                    ts_info = CompressionQueries.get_table_tablespace(parts[0], parts[1])
                    tablespace = ts_info or 'N/A'
            st.metric("Tablespace", tablespace)
        with col2:
            block_count = storage.get('block_count') or 0
            st.metric("Block Count", f"{block_count:,}" if block_count else "N/A")
        with col3:
            avg_row_len = storage.get('avg_row_length') or 0
            st.metric("Avg Row Length", f"{avg_row_len:,} bytes" if avg_row_len else "N/A")
        with col4:
            size_bytes = storage.get('size_bytes') or 0
            size_mb = summary.get('current_size_mb') or 0
            if size_bytes > 0:
                st.metric("Size", format_size(size_bytes))
            elif size_mb > 0:
                st.metric("Size", f"{size_mb:.2f} MB")
            else:
                st.metric("Size", "N/A")


def execute_batch_compression(selected_df: pd.DataFrame, original_df: pd.DataFrame, dry_run: bool, parallel_degree: int):
    """Execute batch compression for selected tables"""

    # Map selected rows back to original recommendation IDs
    if 'ID' not in selected_df.columns:
        st.error("Cannot execute: Missing recommendation IDs")
        return

    selected_ids = selected_df['ID'].tolist()

    if not selected_ids:
        st.warning("No tables selected for execution")
        return

    # Show confirmation
    st.markdown("---")

    if dry_run:
        st.info(f"**Dry Run Mode**: Generating DDL for {len(selected_ids)} tables without making changes...")
    else:
        st.warning(f"**Live Execution**: Compressing {len(selected_ids)} tables. This may take a while...")

    # Progress tracking
    progress_bar = st.progress(0)
    status_text = st.empty()
    results_container = st.container()

    success_count = 0
    error_count = 0
    results = []

    for i, rec_id in enumerate(selected_ids):
        progress = (i + 1) / len(selected_ids)
        progress_bar.progress(progress)

        # Get table info from selected_df
        table_row = selected_df[selected_df['ID'] == rec_id].iloc[0]
        table_name = table_row.get('Table', f'ID-{rec_id}')
        owner = table_row.get('Owner', 'UNKNOWN')

        status_text.text(f"Processing {i+1}/{len(selected_ids)}: {owner}.{table_name}...")

        try:
            result = CompressionQueries.execute_compression(
                analysis_id=int(rec_id),
                dry_run=dry_run,
                parallel_degree=parallel_degree
            )

            if result.get('error'):
                error_count += 1
                results.append({
                    'Table': f"{owner}.{table_name}",
                    'Status': 'Error',
                    'Message': result.get('error', 'Unknown error')
                })
            elif result.get('dry_run'):
                success_count += 1
                results.append({
                    'Table': f"{owner}.{table_name}",
                    'Status': 'DDL Generated',
                    'Message': result.get('ddl', '')[:100] + '...' if len(result.get('ddl', '')) > 100 else result.get('ddl', '')
                })
            else:
                success_count += 1
                results.append({
                    'Table': f"{owner}.{table_name}",
                    'Status': 'Completed',
                    'Message': f"Execution ID: {result.get('execution_id', 'N/A')}"
                })
        except Exception as e:
            error_count += 1
            results.append({
                'Table': f"{owner}.{table_name}",
                'Status': 'Error',
                'Message': str(e)
            })

    # Clear progress indicators
    progress_bar.empty()
    status_text.empty()

    # Show results
    with results_container:
        st.markdown("### Execution Results")

        if error_count == 0:
            st.success(f"All {success_count} tables processed successfully!")
        elif success_count == 0:
            st.error(f"All {error_count} tables failed!")
        else:
            st.warning(f"Completed: {success_count} success, {error_count} errors")

        # Results table
        results_df = pd.DataFrame(results)
        st.dataframe(results_df, use_container_width=True, hide_index=True)

        # Show DDL for dry run
        if dry_run and success_count > 0:
            with st.expander("View Generated DDL Statements"):
                for result in results:
                    if result['Status'] == 'DDL Generated':
                        st.code(result['Message'], language='sql')


if __name__ == "__main__":
    show_recommendations_page()
