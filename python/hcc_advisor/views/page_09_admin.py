"""
Admin Page - HCC Compression Advisor
SQL Patches, system maintenance, and administration tools
"""

import streamlit as st
import pandas as pd
from pathlib import Path
from hcc_advisor.utils.central_connector import CentralConnector
from hcc_advisor.config import config


def show_admin_page():
    st.title("Administration")
    st.markdown("System maintenance and SQL patch management")
    st.markdown("---")

    tab1, tab2 = st.tabs(["SQL Patches", "System Info"])

    with tab1:
        show_sql_patches()

    with tab2:
        show_system_info()


def show_sql_patches():
    """Show SQL patch management UI with clear applied/pending status."""

    st.subheader("SQL Patch Management")
    st.markdown("Apply versioned SQL patches to the central database without redeploying.")

    # Search multiple possible locations for sql/patches
    candidates = [
        Path(__file__).resolve().parents[2] / 'sql' / 'patches',  # non-Docker: python/hcc_advisor/views -> python -> project/sql/patches
        Path(__file__).resolve().parents[3] / 'sql' / 'patches',  # alternative project layout
        Path('/app/sql/patches'),                                   # Docker mount
    ]
    patches_dir = None
    for c in candidates:
        if c.exists():
            patches_dir = c
            break

    if patches_dir is None:
        st.warning("Patches directory not found. Expected at `sql/patches/` relative to the project root.")
        return

    # Scan for patch directories
    patch_dirs = sorted(
        [d for d in patches_dir.iterdir() if d.is_dir()],
        key=lambda d: d.name
    )

    if not patch_dirs:
        st.info("No patch directories found.")
        return

    # Get applied patches from DB
    applied = {}
    try:
        df = CentralConnector.execute_query("""
            SELECT patch_name, status,
                   TO_CHAR(applied_date, 'YYYY-MM-DD HH24:MI:SS') as applied_date,
                   applied_by
            FROM t_patch_history
            ORDER BY applied_date DESC
        """)
        if not df.empty:
            for _, r in df.iterrows():
                name = r['PATCH_NAME']
                if name not in applied:
                    applied[name] = {
                        'status': r['STATUS'],
                        'date': r['APPLIED_DATE'],
                        'by': r.get('APPLIED_BY', '')
                    }
    except Exception:
        st.caption("T_PATCH_HISTORY table not found — apply the bootstrap patch first.")

    # Summary
    total = len(patch_dirs)
    applied_count = sum(1 for d in patch_dirs if d.name in applied and applied[d.name]['status'] == 'SUCCESS')
    pending_count = total - applied_count

    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric("Total Patches", total)
    with col2:
        st.metric("Applied", applied_count)
    with col3:
        st.metric("Pending", pending_count)

    st.markdown("---")

    # List patches
    for pdir in patch_dirs:
        patch_name = pdir.name
        info = applied.get(patch_name)
        is_applied = info and info['status'] == 'SUCCESS'
        is_failed = info and info['status'] == 'FAILED'

        if is_applied:
            icon = "🟢"
            label = f"Applied on {info['date']}"
        elif is_failed:
            icon = "🔴"
            label = f"FAILED on {info['date']}"
        else:
            icon = "⚪"
            label = "Not applied"

        readme_path = pdir / 'readme.md'
        sql_path = pdir / 'patch.sql'
        readme_text = readme_path.read_text() if readme_path.exists() else "No description."
        sql_text = sql_path.read_text() if sql_path.exists() else None

        with st.expander(f"{icon} **{patch_name}** — {label}"):
            st.markdown(readme_text)

            if sql_text:
                st.code(sql_text, language='sql')

                if not is_applied:
                    if st.button(f"Apply Patch", key=f"apply_{patch_name}", type="primary"):
                        with st.spinner(f"Applying {patch_name}..."):
                            try:
                                # Split on standalone / for PL/SQL blocks, or execute as DML
                                blocks = [b.strip() for b in sql_text.split('\n/\n') if b.strip()]
                                if not blocks:
                                    blocks = [sql_text.strip()]

                                for block in blocks:
                                    clean = block.rstrip().rstrip('/')
                                    if not clean:
                                        continue
                                    # Try PL/SQL first (DECLARE/BEGIN), else DML
                                    upper = clean.lstrip().upper()
                                    if upper.startswith('DECLARE') or upper.startswith('BEGIN'):
                                        CentralConnector.execute_plsql(clean)
                                    else:
                                        # May be multiple statements separated by ;
                                        for stmt in clean.split(';'):
                                            stmt = stmt.strip()
                                            if stmt:
                                                CentralConnector.execute_dml(stmt)

                                # Record success
                                try:
                                    CentralConnector.execute_dml(
                                        "INSERT INTO t_patch_history (patch_name, status) VALUES (:n, 'SUCCESS')",
                                        {'n': patch_name}
                                    )
                                except Exception:
                                    pass

                                st.success(f"Patch **{patch_name}** applied successfully!")
                                st.rerun()

                            except Exception as e:
                                try:
                                    CentralConnector.execute_dml(
                                        "INSERT INTO t_patch_history (patch_name, status, error_message) VALUES (:n, 'FAILED', :e)",
                                        {'n': patch_name, 'e': str(e)[:4000]}
                                    )
                                except Exception:
                                    pass
                                st.error(f"Patch failed: {e}")
                else:
                    st.success(f"Applied by {info.get('by', 'N/A')} on {info['date']}")
            else:
                st.warning("No `patch.sql` found in this directory.")


def show_system_info():
    """Show system info and central DB status."""
    st.subheader("System Information")

    try:
        ver = CentralConnector.execute_query(
            "SELECT value FROM t_schema_metadata WHERE key = 'schema_version'"
        )
        if not ver.empty:
            st.metric("Schema Version", ver.iloc[0]['VALUE'])
    except Exception:
        st.caption("Schema version not available.")

    try:
        counts = CentralConnector.execute_query("""
            SELECT 'Analysis Results' as item, COUNT(*) as cnt FROM t_compression_analysis
            UNION ALL SELECT 'Execution History', COUNT(*) FROM t_compression_history
            UNION ALL SELECT 'Advisor Runs', COUNT(*) FROM t_advisor_run
            UNION ALL SELECT 'Target Databases', COUNT(*) FROM t_target_databases
            UNION ALL SELECT 'Strategy Rules', COUNT(*) FROM t_strategy_rules
        """)
        if not counts.empty:
            st.markdown("### Central Database Counts")
            for _, r in counts.iterrows():
                st.metric(r['ITEM'], f"{int(r['CNT']):,}")
    except Exception:
        pass


if __name__ == "__main__":
    show_admin_page()
