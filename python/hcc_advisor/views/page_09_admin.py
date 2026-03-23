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


def _ensure_patch_history_table():
    """Create T_PATCH_HISTORY if it doesn't exist. Returns True if table exists."""
    try:
        df = CentralConnector.execute_query(
            "SELECT 1 FROM user_tables WHERE table_name = 'T_PATCH_HISTORY'"
        )
        if not df.empty:
            return True
    except Exception:
        pass

    try:
        CentralConnector.execute_plsql("""
            BEGIN
                EXECUTE IMMEDIATE '
                    CREATE TABLE T_PATCH_HISTORY (
                        patch_id      NUMBER GENERATED ALWAYS AS IDENTITY,
                        patch_name    VARCHAR2(200) NOT NULL,
                        applied_date  TIMESTAMP DEFAULT SYSTIMESTAMP,
                        applied_by    VARCHAR2(100) DEFAULT USER,
                        status        VARCHAR2(20),
                        error_message VARCHAR2(4000),
                        CONSTRAINT PK_PATCH_HISTORY PRIMARY KEY (patch_id)
                    )
                ';
            END;
        """)
        return True
    except Exception:
        return False


def _check_patch_applied(check_sql: str) -> bool:
    """Run a check.sql query — returns True if result > 0."""
    try:
        df = CentralConnector.execute_query(check_sql.strip())
        if not df.empty:
            return int(df.iloc[0]['RESULT'] or 0) > 0
    except Exception:
        pass
    return False


def _record_patch(patch_name: str, status: str = 'SUCCESS', error: str = None):
    """Insert a record into T_PATCH_HISTORY."""
    try:
        if error:
            CentralConnector.execute_dml(
                "INSERT INTO t_patch_history (patch_name, status, error_message) VALUES (:n, :s, :e)",
                {'n': patch_name, 's': status, 'e': str(error)[:4000]}
            )
        else:
            CentralConnector.execute_dml(
                "INSERT INTO t_patch_history (patch_name, status) VALUES (:n, :s)",
                {'n': patch_name, 's': status}
            )
    except Exception:
        pass


def show_sql_patches():
    """Show SQL patch management with auto-detection via check.sql queries."""

    st.subheader("SQL Patch Management")
    st.markdown("Apply versioned SQL patches to the central database without redeploying.")

    # Find patches directory
    candidates = [
        Path(__file__).resolve().parents[2] / 'sql' / 'patches',
        Path(__file__).resolve().parents[3] / 'sql' / 'patches',
        Path('/app/sql/patches'),
    ]
    patches_dir = None
    for c in candidates:
        if c.exists():
            patches_dir = c
            break

    if patches_dir is None:
        st.warning("Patches directory not found. Expected at `sql/patches/` relative to the project root.")
        return

    patch_dirs = sorted([d for d in patches_dir.iterdir() if d.is_dir()], key=lambda d: d.name)
    if not patch_dirs:
        st.info("No patch directories found.")
        return

    # Ensure T_PATCH_HISTORY exists
    has_history_table = _ensure_patch_history_table()

    # Load recorded patches from DB
    recorded = {}
    if has_history_table:
        try:
            df = CentralConnector.execute_query("""
                SELECT patch_name, status,
                       TO_CHAR(applied_date, 'YYYY-MM-DD HH24:MI:SS') as applied_date,
                       applied_by
                FROM t_patch_history ORDER BY applied_date DESC
            """)
            if not df.empty:
                for _, r in df.iterrows():
                    name = r['PATCH_NAME']
                    if name not in recorded:
                        recorded[name] = {
                            'status': r['STATUS'], 'date': r['APPLIED_DATE'],
                            'by': r.get('APPLIED_BY', '')
                        }
        except Exception:
            pass

    # Run check.sql for each patch to detect actual DB state
    detected = {}
    auto_marked = 0
    for pdir in patch_dirs:
        check_path = pdir / 'check.sql'
        if check_path.exists():
            check_sql = check_path.read_text().strip()
            if check_sql:
                detected[pdir.name] = _check_patch_applied(check_sql)
                # Auto-mark: if detected as applied but not recorded, record it
                if detected[pdir.name] and pdir.name not in recorded and has_history_table:
                    _record_patch(pdir.name, 'SUCCESS')
                    recorded[pdir.name] = {'status': 'SUCCESS', 'date': 'auto-detected', 'by': 'system'}
                    auto_marked += 1

    if auto_marked > 0:
        st.toast(f"{auto_marked} patch(es) auto-detected as applied and recorded")

    # Summary
    total = len(patch_dirs)
    applied_count = sum(1 for d in patch_dirs
                        if detected.get(d.name, False) or
                        (d.name in recorded and recorded[d.name]['status'] == 'SUCCESS'))
    pending_count = total - applied_count

    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric("Total Patches", total)
    with col2:
        st.metric("Applied", applied_count)
    with col3:
        st.metric("Pending", pending_count)

    if not has_history_table:
        st.warning("T_PATCH_HISTORY table could not be created. Check central DB permissions.")

    st.markdown("---")

    # List patches
    for pdir in patch_dirs:
        patch_name = pdir.name
        info = recorded.get(patch_name)
        check_ok = detected.get(patch_name, False)
        is_applied = check_ok or (info and info['status'] == 'SUCCESS')
        is_failed = info and info['status'] == 'FAILED' and not check_ok

        if is_applied:
            icon = "🟢"
            if info:
                label = f"Applied — {info['date']} by {info.get('by', 'N/A')}"
            else:
                label = "Detected as applied (check.sql passed)"
        elif is_failed:
            icon = "🔴"
            label = f"FAILED — {info['date']}"
        else:
            icon = "⚪"
            label = "Pending"

        readme_path = pdir / 'readme.md'
        sql_path = pdir / 'patch.sql'
        check_path = pdir / 'check.sql'
        readme_text = readme_path.read_text() if readme_path.exists() else "No description."
        sql_text = sql_path.read_text() if sql_path.exists() else None
        check_text = check_path.read_text().strip() if check_path.exists() else None

        with st.expander(f"{icon} **{patch_name}** — {label}"):
            st.markdown(readme_text)

            if check_text:
                st.caption("**Verification query** (check.sql):")
                st.code(check_text, language='sql')

            if sql_text:
                st.caption("**Patch SQL** (patch.sql):")
                st.code(sql_text, language='sql')

                if not is_applied:
                    if st.button(f"Apply Patch", key=f"apply_{patch_name}", type="primary"):
                        with st.spinner(f"Applying {patch_name}..."):
                            try:
                                blocks = [b.strip() for b in sql_text.split('\n/\n') if b.strip()]
                                if not blocks:
                                    blocks = [sql_text.strip()]

                                for block in blocks:
                                    clean = block.rstrip().rstrip('/')
                                    if not clean:
                                        continue
                                    upper = clean.lstrip().upper()
                                    if upper.startswith('DECLARE') or upper.startswith('BEGIN'):
                                        CentralConnector.execute_plsql(clean)
                                    else:
                                        for stmt in clean.split(';'):
                                            stmt = stmt.strip()
                                            if stmt:
                                                CentralConnector.execute_dml(stmt)

                                _record_patch(patch_name, 'SUCCESS')
                                st.success(f"Patch **{patch_name}** applied!")
                                st.rerun()

                            except Exception as e:
                                _record_patch(patch_name, 'FAILED', str(e))
                                st.error(f"Patch failed: {e}")
            else:
                st.warning("No `patch.sql` found.")


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
