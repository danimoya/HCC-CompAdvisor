"""
Strategies Page - HCC Compression Advisor
View, edit and manage compression strategies
"""

import streamlit as st
import pandas as pd
import plotly.graph_objects as go
import plotly.express as px
from hcc_advisor.utils.central_queries import CentralQueries
from hcc_advisor.utils.target_queries import TargetQueries
from hcc_advisor.config import config


def show_strategies_page():
    """Display strategies page"""

    st.title("Compression Rules")
    st.markdown("Manage compression strategies and rules")
    st.markdown("---")

    # Create tabs for different sections
    tab1, tab2, tab3, tab4 = st.tabs([
        "Strategy Overview",
        "Edit Strategies",
        "Strategy Rules",
        "Compare Strategies"
    ])

    with tab1:
        show_strategy_overview()

    with tab2:
        show_strategy_editor()

    with tab3:
        show_strategy_rules_editor()

    with tab4:
        show_strategy_comparison()


def show_strategy_overview():
    """Display strategy overview with statistics"""

    st.subheader("Available Strategies")

    strategies_df = CentralQueries.get_all_strategies(include_inactive=False)

    if strategies_df.empty:
        st.info("No strategies found. Create a new strategy to get started.")
        return

    # Normalize columns
    strategies_df.columns = [c.lower() for c in strategies_df.columns]

    # Display strategy cards
    for _, strategy in strategies_df.iterrows():
        strategy_name = strategy.get('strategy_name', 'Unknown')
        is_default = strategy.get('is_default') == 'Y'
        category = strategy.get('category', 'BALANCED')

        # Card header with badge
        badge = " 🏷️ *Default*" if is_default else ""
        category_color = {
            'PERFORMANCE': '🟢',
            'BALANCED': '🟡',
            'SPACE': '🔵',
            'CUSTOM': '⚪'
        }.get(category, '⚪')

        with st.expander(f"{category_color} {strategy_name}{badge}", expanded=False):
            col1, col2, col3 = st.columns(3)

            with col1:
                st.markdown("**General Info**")
                st.markdown(f"- **Category:** {category}")
                st.markdown(f"- **Description:** {strategy.get('description', 'N/A')}")
                st.markdown(f"- **Priority:** {strategy.get('priority', 0)}")
                st.markdown(f"- **Min Compression Ratio:** {strategy.get('min_compression_ratio', 1.5):.2f}x")
                st.markdown(f"- **Min Space Savings:** {strategy.get('min_space_savings_mb', 100)} MB")

            with col2:
                st.markdown("**Hotness Thresholds**")
                st.markdown(f"- **Hot (≥):** {strategy.get('hotness_threshold_hot', 75)}")
                st.markdown(f"- **Warm (≥):** {strategy.get('hotness_threshold_warm', 50)}")
                st.markdown(f"- **Cool (≥):** {strategy.get('hotness_threshold_cool', 25)}")
                st.markdown("**DML Thresholds (ops/day)**")
                st.markdown(f"- **High:** {strategy.get('dml_threshold_high', 10000):,}")
                st.markdown(f"- **Medium:** {strategy.get('dml_threshold_medium', 1000):,}")
                st.markdown(f"- **Low:** {strategy.get('dml_threshold_low', 100):,}")

            with col3:
                st.markdown("**Size Thresholds (GB)**")
                st.markdown(f"- **Large (≥):** {strategy.get('size_threshold_large_gb', 50)} GB")
                st.markdown(f"- **Medium (≥):** {strategy.get('size_threshold_medium_gb', 10)} GB")
                st.markdown(f"- **Small (≥):** {strategy.get('size_threshold_small_gb', 1)} GB")
                st.markdown("**Age Thresholds (days)**")
                st.markdown(f"- **Recent:** {strategy.get('age_threshold_recent_days', 30)} days")
                st.markdown(f"- **Old:** {strategy.get('age_threshold_old_days', 90)} days")
                st.markdown(f"- **Archive:** {strategy.get('age_threshold_archive_days', 180)} days")

    # Strategy performance statistics
    st.markdown("---")
    st.subheader("Strategy Performance Statistics")

    strategy_stats_df = CentralQueries.get_savings_by_strategy(database_id=st.session_state.get('active_database_id'))

    if not strategy_stats_df.empty:
        strategy_stats_df.columns = [c.lower() for c in strategy_stats_df.columns]

        fig = go.Figure()
        fig.add_trace(go.Bar(
            name='Average Savings %',
            x=strategy_stats_df['strategy'],
            y=strategy_stats_df['avg_savings_pct'],
            marker_color=config.CHART_COLORS['primary'],
            yaxis='y',
            offsetgroup=1
        ))

        if 'avg_compression_ratio' in strategy_stats_df.columns:
            fig.add_trace(go.Bar(
                name='Compression Ratio',
                x=strategy_stats_df['strategy'],
                y=strategy_stats_df['avg_compression_ratio'],
                marker_color=config.CHART_COLORS['success'],
                yaxis='y2',
                offsetgroup=2
            ))

        fig.update_layout(
            xaxis_title="Compression Type",
            yaxis_title="Average Savings (%)",
            yaxis2=dict(title="Compression Ratio", overlaying='y', side='right'),
            height=400,
            barmode='group'
        )
        st.plotly_chart(fig, use_container_width=True)

        # Statistics table
        display_df = strategy_stats_df.copy()
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

        for col in ['Avg Savings %', 'Avg Ratio', 'Total Size (GB)', 'Total Savings (GB)']:
            if col in display_df.columns:
                display_df[col] = display_df[col].round(2)

        st.dataframe(display_df, use_container_width=True, hide_index=True)
    else:
        st.info("No compression analysis data available yet.")


def show_strategy_editor():
    """Display strategy editing interface"""

    st.subheader("Strategy Management")

    # Load all strategies including inactive
    strategies_df = CentralQueries.get_all_strategies(include_inactive=True)

    if not strategies_df.empty:
        strategies_df.columns = [c.lower() for c in strategies_df.columns]

    # Strategy selector
    col1, col2, col3 = st.columns([2, 1, 1])

    with col1:
        strategy_options = ["➕ Create New Strategy"]
        if not strategies_df.empty:
            for _, row in strategies_df.iterrows():
                status = "✓" if row.get('active_flag') == 'Y' else "✗"
                default = " (Default)" if row.get('is_default') == 'Y' else ""
                strategy_options.append(f"{status} {row.get('strategy_name')}{default}")

        selected_option = st.selectbox(
            "Select Strategy to Edit",
            options=strategy_options,
            key="strategy_selector"
        )

    # Determine if editing existing or creating new
    editing_new = selected_option == "➕ Create New Strategy"

    if editing_new:
        strategy_data = {
            'strategy_id': None,
            'strategy_name': '',
            'description': '',
            'category': 'BALANCED',
            'hotness_threshold_hot': 75,
            'hotness_threshold_warm': 50,
            'hotness_threshold_cool': 25,
            'dml_threshold_high': 10000,
            'dml_threshold_medium': 1000,
            'dml_threshold_low': 100,
            'size_threshold_large_gb': 50,
            'size_threshold_medium_gb': 10,
            'size_threshold_small_gb': 1,
            'age_threshold_recent_days': 30,
            'age_threshold_old_days': 90,
            'age_threshold_archive_days': 180,
            'min_compression_ratio': 1.5,
            'min_space_savings_mb': 100,
            'active_flag': 'Y',
            'priority': 50
        }
    else:
        # Find selected strategy
        strategy_name = selected_option.split(' ', 1)[1].replace(' (Default)', '').strip()
        strategy_row = strategies_df[strategies_df['strategy_name'] == strategy_name]
        if not strategy_row.empty:
            strategy_data = strategy_row.iloc[0].to_dict()
        else:
            st.error("Strategy not found")
            return

    st.markdown("---")

    # Strategy form
    with st.form("strategy_form"):
        st.markdown("### Strategy Details")

        col1, col2 = st.columns(2)

        with col1:
            strategy_name_input = st.text_input(
                "Strategy Name *",
                value=strategy_data.get('strategy_name', ''),
                max_chars=50,
                help="Unique identifier for this strategy"
            )

            description_input = st.text_area(
                "Description",
                value=strategy_data.get('description', ''),
                max_chars=500
            )

            category_input = st.selectbox(
                "Category",
                options=['PERFORMANCE', 'BALANCED', 'SPACE', 'CUSTOM'],
                index=['PERFORMANCE', 'BALANCED', 'SPACE', 'CUSTOM'].index(
                    strategy_data.get('category', 'BALANCED')
                )
            )

        with col2:
            active_input = st.checkbox(
                "Active",
                value=strategy_data.get('active_flag') == 'Y'
            )

            priority_input = st.number_input(
                "Priority",
                min_value=0,
                max_value=100,
                value=int(strategy_data.get('priority') or 50),
                help="Higher priority strategies are preferred"
            )

            min_ratio_input = st.number_input(
                "Minimum Compression Ratio",
                min_value=1.0,
                max_value=20.0,
                value=float(strategy_data.get('min_compression_ratio') or 1.5),
                step=0.1
            )

            min_savings_input = st.number_input(
                "Minimum Space Savings (MB)",
                min_value=0,
                max_value=10000,
                value=int(strategy_data.get('min_space_savings_mb') or 100)
            )

        st.markdown("### Hotness Thresholds")
        st.caption("Tables with hotness score >= threshold are classified in that category")

        col1, col2, col3 = st.columns(3)
        with col1:
            hot_threshold = st.number_input(
                "Hot (≥)",
                min_value=0,
                max_value=100,
                value=int(strategy_data.get('hotness_threshold_hot') or 75),
                help="High activity - minimal compression recommended"
            )
        with col2:
            warm_threshold = st.number_input(
                "Warm (≥)",
                min_value=0,
                max_value=100,
                value=int(strategy_data.get('hotness_threshold_warm') or 50),
                help="Moderate activity - OLTP compression recommended"
            )
        with col3:
            cool_threshold = st.number_input(
                "Cool (≥)",
                min_value=0,
                max_value=100,
                value=int(strategy_data.get('hotness_threshold_cool') or 25),
                help="Low activity - query compression recommended"
            )

        st.markdown("### DML Thresholds (operations/day)")

        col1, col2, col3 = st.columns(3)
        with col1:
            dml_high = st.number_input(
                "High DML (≥)",
                min_value=0,
                value=int(strategy_data.get('dml_threshold_high') or 10000)
            )
        with col2:
            dml_medium = st.number_input(
                "Medium DML (≥)",
                min_value=0,
                value=int(strategy_data.get('dml_threshold_medium') or 1000)
            )
        with col3:
            dml_low = st.number_input(
                "Low DML (≥)",
                min_value=0,
                value=int(strategy_data.get('dml_threshold_low') or 100)
            )

        st.markdown("### Size Thresholds (GB)")

        col1, col2, col3 = st.columns(3)
        with col1:
            size_large = st.number_input(
                "Large (≥)",
                min_value=0.0,
                value=float(strategy_data.get('size_threshold_large_gb') or 50)
            )
        with col2:
            size_medium = st.number_input(
                "Medium (≥)",
                min_value=0.0,
                value=float(strategy_data.get('size_threshold_medium_gb') or 10)
            )
        with col3:
            size_small = st.number_input(
                "Small (≥)",
                min_value=0.0,
                value=float(strategy_data.get('size_threshold_small_gb') or 1)
            )

        st.markdown("### Age Thresholds (days)")

        col1, col2, col3 = st.columns(3)
        with col1:
            age_recent = st.number_input(
                "Recent (≤)",
                min_value=0,
                value=int(strategy_data.get('age_threshold_recent_days') or 30)
            )
        with col2:
            age_old = st.number_input(
                "Old (≤)",
                min_value=0,
                value=int(strategy_data.get('age_threshold_old_days') or 90)
            )
        with col3:
            age_archive = st.number_input(
                "Archive (>)",
                min_value=0,
                value=int(strategy_data.get('age_threshold_archive_days') or 180)
            )

        # Form buttons
        col1, col2, col3, col4 = st.columns(4)

        with col1:
            save_button = st.form_submit_button("💾 Save Strategy", type="primary", use_container_width=True)

        with col2:
            if not editing_new:
                set_default_button = st.form_submit_button("🏷️ Set as Default", use_container_width=True)
            else:
                set_default_button = False

        with col3:
            if not editing_new:
                delete_button = st.form_submit_button("🗑️ Deactivate", use_container_width=True)
            else:
                delete_button = False

    # Handle form submission
    if save_button:
        if not strategy_name_input:
            st.error("Strategy name is required")
        else:
            save_data = {
                'strategy_id': strategy_data.get('strategy_id'),
                'strategy_name': strategy_name_input,
                'description': description_input,
                'category': category_input,
                'hotness_threshold_hot': hot_threshold,
                'hotness_threshold_warm': warm_threshold,
                'hotness_threshold_cool': cool_threshold,
                'dml_threshold_high': dml_high,
                'dml_threshold_medium': dml_medium,
                'dml_threshold_low': dml_low,
                'size_threshold_large_gb': size_large,
                'size_threshold_medium_gb': size_medium,
                'size_threshold_small_gb': size_small,
                'age_threshold_recent_days': age_recent,
                'age_threshold_old_days': age_old,
                'age_threshold_archive_days': age_archive,
                'min_compression_ratio': min_ratio_input,
                'min_space_savings_mb': min_savings_input,
                'active_flag': 'Y' if active_input else 'N',
                'priority': priority_input
            }

            success, message = CentralQueries.save_strategy(save_data)
            if success:
                st.success(message)
                st.rerun()
            else:
                st.error(f"Failed to save: {message}")

    if set_default_button and not editing_new:
        strategy_id = strategy_data.get('strategy_id')
        if strategy_id:
            success, message = CentralQueries.set_default_strategy(strategy_id)
            if success:
                st.success(message)
                st.rerun()
            else:
                st.error(f"Failed: {message}")

    if delete_button and not editing_new:
        strategy_id = strategy_data.get('strategy_id')
        if strategy_id:
            success, message = CentralQueries.delete_strategy(strategy_id)
            if success:
                st.success(message)
                st.rerun()
            else:
                st.error(f"Failed: {message}")


def show_strategy_rules_editor():
    """Display strategy rules editing interface"""

    st.subheader("Strategy Rules")
    st.caption("Rules define which compression type to recommend based on object characteristics")

    # Get strategies for dropdown
    strategies_df = CentralQueries.get_all_strategies(include_inactive=False)
    if strategies_df.empty:
        st.warning("No active strategies found. Create a strategy first.")
        return

    strategies_df.columns = [c.lower() for c in strategies_df.columns]

    # Strategy filter
    strategy_options = {row['strategy_name']: row['strategy_id'] for _, row in strategies_df.iterrows()}
    selected_strategy = st.selectbox(
        "Filter by Strategy",
        options=["All Strategies"] + list(strategy_options.keys()),
        key="rules_strategy_filter"
    )

    strategy_id_filter = None
    if selected_strategy != "All Strategies":
        strategy_id_filter = strategy_options.get(selected_strategy)

    # Load rules
    rules_df = CentralQueries.get_all_strategy_rules(strategy_id=strategy_id_filter)

    if not rules_df.empty:
        rules_df.columns = [c.lower() for c in rules_df.columns]

        # Display rules table
        display_cols = ['rule_id', 'strategy_name', 'object_type', 'hotness_min', 'hotness_max',
                       'dml_ratio_threshold', 'compression_type', 'priority', 'enabled_flag']
        available_cols = [c for c in display_cols if c in rules_df.columns]

        st.dataframe(
            rules_df[available_cols],
            use_container_width=True,
            hide_index=True,
            column_config={
                'rule_id': 'ID',
                'strategy_name': 'Strategy',
                'object_type': 'Object Type',
                'hotness_min': 'Hotness Min',
                'hotness_max': 'Hotness Max',
                'dml_ratio_threshold': 'DML Ratio',
                'compression_type': 'Compression',
                'priority': 'Priority',
                'enabled_flag': 'Active'
            }
        )

    st.markdown("---")

    # Rule editor
    st.markdown("### Add/Edit Rule")

    with st.form("rule_form"):
        col1, col2 = st.columns(2)

        with col1:
            rule_strategy = st.selectbox(
                "Strategy *",
                options=list(strategy_options.keys()),
                key="rule_strategy"
            )

            object_type = st.selectbox(
                "Object Type",
                options=['TABLE', 'INDEX', 'LOB', 'IOT']
            )

            compression_type = st.selectbox(
                "Compression Type",
                options=['NONE', 'BASIC', 'OLTP', 'ADV_LOW', 'ADV_HIGH',
                        'QUERY LOW', 'QUERY HIGH', 'ARCHIVE LOW', 'ARCHIVE HIGH']
            )

        with col2:
            hotness_min = st.number_input("Hotness Min", min_value=0, max_value=100, value=0)
            hotness_max = st.number_input("Hotness Max", min_value=0, max_value=100, value=100)
            dml_ratio = st.number_input("DML Ratio Threshold", min_value=0.0, max_value=1.0, value=0.5, step=0.1)
            priority = st.number_input("Priority", min_value=0, max_value=100, value=50)

        rule_description = st.text_input("Rule Description", max_chars=500)
        enabled = st.checkbox("Enabled", value=True)

        col1, col2 = st.columns(2)
        with col1:
            add_rule = st.form_submit_button("➕ Add Rule", use_container_width=True)

    if add_rule:
        rule_data = {
            'rule_id': None,
            'strategy_id': strategy_options.get(rule_strategy),
            'object_type': object_type,
            'hotness_min': hotness_min,
            'hotness_max': hotness_max,
            'dml_ratio_threshold': dml_ratio,
            'compression_type': compression_type,
            'priority': priority,
            'enabled_flag': 'Y' if enabled else 'N',
            'rule_description': rule_description
        }

        success, message = CentralQueries.save_strategy_rule(rule_data)
        if success:
            st.success(message)
            st.rerun()
        else:
            st.error(f"Failed: {message}")

    # Delete rule section
    if not rules_df.empty:
        st.markdown("---")
        st.markdown("### Delete Rule")

        col1, col2 = st.columns([2, 1])
        with col1:
            rule_to_delete = st.selectbox(
                "Select Rule to Delete",
                options=rules_df['rule_id'].tolist(),
                format_func=lambda x: f"Rule {x}: {rules_df[rules_df['rule_id']==x].iloc[0].get('rule_description', 'No description')[:50]}"
            )
        with col2:
            if st.button("🗑️ Delete Rule", use_container_width=True):
                success, message = CentralQueries.delete_strategy_rule(rule_to_delete)
                if success:
                    st.success(message)
                    st.rerun()
                else:
                    st.error(f"Failed: {message}")


def show_strategy_comparison():
    """Display strategy comparison for specific tables"""

    st.subheader("Compare Strategies for Specific Table")

    # Get available schemas (requires target DB connection)
    db_id = st.session_state.get('active_database_id')
    if db_id:
        schemas = TargetQueries.get_available_schemas(db_id)
    else:
        schemas = []

    col1, col2, col3 = st.columns([2, 2, 1])

    with col1:
        if schemas:
            owner = st.selectbox("Schema Owner", options=schemas, index=0)
        else:
            owner = st.text_input("Schema Owner", value="HR")

    with col2:
        table_name = st.text_input("Table Name", value="EMPLOYEES")

    with col3:
        st.markdown("<br>", unsafe_allow_html=True)
        compare_button = st.button("Compare", use_container_width=True, type="primary")

    if compare_button and owner and table_name:
        if not db_id:
            st.warning("Select a target database from the sidebar to compare strategies.")
            return
        with st.spinner(f"Comparing strategies for {owner}.{table_name}..."):
            comp_df = TargetQueries.compare_strategies(db_id, owner, table_name)

            if comp_df.empty:
                st.warning("No comparison data available for this table. Make sure the table exists and has been analyzed.")
            else:
                comp_df.columns = [col.lower() for col in comp_df.columns]

                # Show current table info
                current_size = comp_df.iloc[0].get('current_size_mb', 0) or 0
                row_count = comp_df.iloc[0].get('row_count', 0) or 0

                col1, col2, col3 = st.columns(3)
                with col1:
                    st.metric("Current Size", f"{current_size:.2f} MB")
                with col2:
                    st.metric("Row Count", f"{int(row_count):,}")
                with col3:
                    if 'savings_pct' in comp_df.columns:
                        best_savings = comp_df['savings_pct'].max()
                        st.metric("Best Possible Savings", f"{best_savings:.1f}%")

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

                display_df = comp_df[[c for c in display_cols if c in comp_df.columns]].copy()

                col_names = {'strategy': 'Strategy', 'estimated_size_mb': 'Size (MB)',
                            'savings_pct': 'Savings %', 'compression_ratio': 'Ratio',
                            'estimated_blocks': 'Blocks'}
                display_df.columns = [col_names.get(c, c) for c in display_df.columns]

                for col in ['Size (MB)', 'Savings %', 'Ratio']:
                    if col in display_df.columns:
                        display_df[col] = display_df[col].round(2)

                st.dataframe(
                    display_df.style.highlight_max(subset=['Savings %'], color='lightgreen'),
                    use_container_width=True,
                    hide_index=True
                )

                # Recommendation
                if 'Savings %' in display_df.columns:
                    best_idx = display_df['Savings %'].idxmax()
                    best_strategy = display_df.loc[best_idx, 'Strategy']
                    best_savings = display_df.loc[best_idx, 'Savings %']
                    st.success(f"**Recommended Strategy:** {best_strategy} ({best_savings:.1f}% savings)")


def show_sql_patches():
    """Show SQL patch management UI."""
    import os
    from pathlib import Path
    from hcc_advisor.utils.central_connector import CentralConnector

    st.subheader("SQL Patch Management")
    st.markdown("Apply versioned SQL patches to the central database without redeploying.")

    patches_dir = Path(__file__).resolve().parents[2] / 'sql' / 'patches'

    if not patches_dir.exists():
        st.info(f"No patches directory found at `sql/patches/`.")
        return

    # Scan for patch directories (YYYYMMDD-description)
    patch_dirs = sorted(
        [d for d in patches_dir.iterdir() if d.is_dir()],
        key=lambda d: d.name, reverse=True
    )

    if not patch_dirs:
        st.info("No patches found.")
        return

    # Get applied patches from DB (if T_PATCH_HISTORY exists)
    applied = set()
    try:
        df = CentralConnector.execute_query(
            "SELECT patch_name FROM t_patch_history WHERE status = 'SUCCESS'"
        )
        if not df.empty:
            applied = set(df['PATCH_NAME'].tolist())
    except Exception:
        pass  # Table may not exist yet

    for pdir in patch_dirs:
        patch_name = pdir.name
        is_applied = patch_name in applied
        status_icon = "🟢" if is_applied else "⚪"

        readme_path = pdir / 'readme.md'
        sql_path = pdir / 'patch.sql'
        readme_text = readme_path.read_text() if readme_path.exists() else "No description."
        sql_text = sql_path.read_text() if sql_path.exists() else None

        with st.expander(f"{status_icon} {patch_name} {'(applied)' if is_applied else ''}"):
            st.markdown(readme_text)
            if sql_text:
                st.code(sql_text, language='sql')

                if not is_applied:
                    if st.button(f"Apply Patch: {patch_name}", key=f"apply_{patch_name}"):
                        with st.spinner("Applying patch..."):
                            try:
                                # Split on / for PL/SQL blocks
                                blocks = [b.strip() for b in sql_text.split('\n/\n') if b.strip()]
                                for block in blocks:
                                    clean = block.rstrip().rstrip('/')
                                    if clean:
                                        CentralConnector.execute_plsql(clean)

                                # Record success
                                try:
                                    CentralConnector.execute_dml(
                                        "INSERT INTO t_patch_history (patch_name) VALUES (:n)",
                                        {'n': patch_name}
                                    )
                                except Exception:
                                    pass
                                st.success(f"Patch {patch_name} applied successfully!")
                                st.rerun()
                            except Exception as e:
                                # Record failure
                                try:
                                    CentralConnector.execute_dml(
                                        "INSERT INTO t_patch_history (patch_name, status, error_message) VALUES (:n, 'FAILED', :e)",
                                        {'n': patch_name, 'e': str(e)[:4000]}
                                    )
                                except Exception:
                                    pass
                                st.error(f"Patch failed: {e}")
                else:
                    st.caption("Already applied.")
            else:
                st.warning("No patch.sql found in this directory.")


if __name__ == "__main__":
    show_strategies_page()
