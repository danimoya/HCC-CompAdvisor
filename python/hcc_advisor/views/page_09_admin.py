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

    tab1, tab2, tab3, tab4, tab5 = st.tabs([
        "SQL Patches", "AI / Ollama", "Webhooks", "AWR License", "System Info"
    ])

    with tab1:
        show_sql_patches()

    with tab2:
        show_ollama_config()

    with tab3:
        show_webhooks()

    with tab4:
        show_awr_disclaimer()

    with tab5:
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

    # Find patches directory. Order: package layout (bundled/mounted into the
    # container at hcc_advisor/sql/patches), dev layout (repo_root/sql/patches),
    # then legacy absolute fallbacks.
    here = Path(__file__).resolve()
    candidates = [
        here.parent.parent / 'sql' / 'patches',   # /app/hcc_advisor/sql/patches (container bind mount)
        here.parents[3] / 'sql' / 'patches',       # repo_root/sql/patches (dev)
        here.parents[2] / 'sql' / 'patches',       # legacy dev fallback
        Path('/app/sql/patches'),                   # legacy container fallback
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


def show_ollama_config():
    """Configure Ollama URL and model for AI Advisor."""
    st.subheader("AI / Ollama Configuration")
    st.markdown("Configure the local Ollama instance for AI-powered compression analysis.")

    import json
    import urllib.request

    # Load current values
    current_url = ''
    current_model = 'llama3'
    try:
        df = CentralConnector.execute_query(
            "SELECT key, value FROM t_schema_metadata WHERE key IN ('ollama_url', 'ollama_model')"
        )
        if not df.empty:
            for _, r in df.iterrows():
                if r['KEY'] == 'ollama_url':
                    current_url = r['VALUE'] or ''
                elif r['KEY'] == 'ollama_model':
                    current_model = r['VALUE'] or 'llama3'
    except Exception:
        pass

    col1, col2 = st.columns(2)
    with col1:
        url = st.text_input("Ollama URL", value=current_url,
                             placeholder="http://localhost:11434", key="admin_ollama_url")
    with col2:
        # Always use a text_input as the source of truth — Ollama is picky about
        # the exact tag string, so the user controls what gets saved verbatim.
        # Test Connection lists the discovered models below as a reference.
        model = st.text_input("Model", value=current_model,
                               placeholder="llama3, mistral, phi3...",
                               help="Type the exact model name as reported by `ollama list`.",
                               key="admin_ollama_model")

    available_models = st.session_state.get('admin_ollama_models_list') or []
    if available_models:
        st.caption("Available models (from `/api/tags`) — copy any name into the Model field above:")
        st.markdown("\n".join(f"- `{m}`" for m in available_models))

    col1, col2, col3 = st.columns(3)
    with col1:
        if st.button("Save", key="ollama_save", use_container_width=True):
            try:
                for k, v in [('ollama_url', url), ('ollama_model', model)]:
                    CentralConnector.execute_dml("""
                        MERGE INTO t_schema_metadata tgt
                        USING (SELECT :k as key FROM DUAL) src ON (tgt.key = src.key)
                        WHEN MATCHED THEN UPDATE SET value = :v
                        WHEN NOT MATCHED THEN INSERT (key, value) VALUES (:k, :v)
                    """, {'k': k, 'v': v})
                st.session_state['ollama_url'] = url
                st.session_state['ollama_model'] = model
                st.success("Ollama configuration saved!")
            except Exception as e:
                st.error(f"Failed: {e}")

    with col2:
        if st.button("Test Connection", key="ollama_test", use_container_width=True):
            if url:
                try:
                    resp = urllib.request.urlopen(f"{url}/api/tags", timeout=10)
                    data = json.loads(resp.read())
                    models = [m['name'] for m in data.get('models', [])]
                    if models:
                        st.session_state['admin_ollama_models_list'] = models
                        st.success(f"Connected! {len(models)} model(s) available — see list below.")
                        st.rerun()
                    else:
                        st.session_state.pop('admin_ollama_models_list', None)
                        st.warning("Connected but no models found. Run: `ollama pull llama3`")
                except Exception as e:
                    st.error(f"Cannot reach Ollama at {url}: {e}")
            else:
                st.warning("Enter a URL first")

    with col3:
        if st.button("Clear", key="ollama_clear", use_container_width=True):
            try:
                CentralConnector.execute_dml(
                    "DELETE FROM t_schema_metadata WHERE key IN ('ollama_url', 'ollama_model')"
                )
                st.session_state.pop('ollama_url', None)
                st.session_state.pop('ollama_model', None)
                st.session_state.pop('admin_ollama_models_list', None)
                st.success("Ollama configuration cleared")
                st.rerun()
            except Exception:
                pass

    st.markdown("---")
    st.markdown("### Setup Guide")

    with st.expander("1. Install Ollama", expanded=False):
        st.markdown("""
**Linux / macOS:**
```bash
curl -fsSL https://ollama.com/install.sh | sh
```

**Windows:** Download from [ollama.com/download](https://ollama.com/download)

**Docker (headless server):**
```bash
docker run -d --gpus=all -v ollama:/root/.ollama -p 11434:11434 --name ollama ollama/ollama
```

After installation, verify Ollama is running:
```bash
curl http://localhost:11434/api/tags
```
""")

    with st.expander("2. Download a Model", expanded=False):
        st.markdown("""
```bash
# Recommended for most use cases:
ollama pull llama3

# Lighter alternative (faster, less RAM):
ollama pull phi3:mini

# For deeper analysis (more capable):
ollama pull mistral
```

**Model comparison:**

| Model | RAM Required | Speed | Analysis Quality |
|-------|-------------|-------|-----------------|
| `phi3:mini` (3.8B) | ~3 GB | Fast | Good for per-object |
| `mistral` (7B) | ~5 GB | Medium | Good schema-level |
| `llama3` (8B) | ~5 GB | Medium | Best overall |
| `llama3:70b` (70B) | ~40 GB | Slow | Most capable (GPU required) |
""")

    with st.expander("3. Configure in HCC Advisor", expanded=False):
        st.markdown("""
1. Enter the **Ollama URL** above (default: `http://localhost:11434`)
   - If Ollama runs on a different server: `http://<server-ip>:11434`
   - If Ollama runs in Docker on the same host: `http://host.docker.internal:11434`
2. Enter the **Model** name (must match a downloaded model exactly)
3. Click **Save**
4. Click **Test Connection** to verify
5. Go to **AI Advisor** page to start analyzing
""")

    with st.expander("4. Network & Security Notes", expanded=False):
        st.markdown("""
- **All data stays local** — Ollama runs on your network, no data sent to cloud
- **No API keys** required — Ollama is open-source and free
- **Air-gapped compatible** — download model once, runs offline
- **Firewall**: Port 11434 must be accessible from the HCC Advisor server
- **GPU optional** — CPU inference works for 7B models (slower but functional)
- **Privacy**: Table names, schemas, and sizes are sent to the local model only
""")


def show_webhooks():
    """Global webhook configuration for notifications."""
    st.subheader("Notification Webhooks")
    st.markdown("Configure a global webhook URL (Slack/Teams/custom) to receive notifications "
                "when compression batches complete or jobs fail.")

    # Load from session state or central DB
    current_url = st.session_state.get('webhook_url', '')
    try:
        df = CentralConnector.execute_query(
            "SELECT value FROM t_schema_metadata WHERE key = 'webhook_url'"
        )
        if not df.empty:
            current_url = df.iloc[0]['VALUE'] or ''
            st.session_state['webhook_url'] = current_url
    except Exception:
        pass

    url = st.text_input("Webhook URL", value=current_url,
                         placeholder="https://hooks.slack.com/services/... or Teams webhook URL",
                         key="webhook_url_input")

    col1, col2, col3 = st.columns(3)
    with col1:
        if st.button("Save", key="webhook_save", use_container_width=True):
            try:
                CentralConnector.execute_dml("""
                    MERGE INTO t_schema_metadata tgt
                    USING (SELECT 'webhook_url' as key FROM DUAL) src ON (tgt.key = src.key)
                    WHEN MATCHED THEN UPDATE SET value = :url
                    WHEN NOT MATCHED THEN INSERT (key, value) VALUES ('webhook_url', :url)
                """, {'url': url})
                st.session_state['webhook_url'] = url
                st.success("Webhook URL saved!")
            except Exception as e:
                st.error(f"Failed to save: {e}")
    with col2:
        if st.button("Test", key="webhook_test", use_container_width=True):
            if url:
                _test_webhook(url)
            else:
                st.warning("Enter a URL first")
    with col3:
        if st.button("Clear", key="webhook_clear", use_container_width=True):
            try:
                CentralConnector.execute_dml(
                    "DELETE FROM t_schema_metadata WHERE key = 'webhook_url'"
                )
                st.session_state.pop('webhook_url', None)
                st.success("Webhook cleared")
                st.rerun()
            except Exception:
                pass

    st.markdown("---")
    st.caption("**Events that trigger notifications:**")
    st.markdown("- Compression batch completed (all jobs in a submission finished)\n"
                "- Individual job failed with error\n"
                "- Growth alert: compressed table grew >20% since compression")


def _test_webhook(url: str):
    """Send a test message to the webhook URL."""
    import urllib.request
    import json
    payload = json.dumps({
        "text": "HCC Compression Advisor — Test notification. Webhook is working!"
    }).encode('utf-8')
    try:
        req = urllib.request.Request(url, data=payload,
                                     headers={'Content-Type': 'application/json'})
        resp = urllib.request.urlopen(req, timeout=10)
        if resp.status < 300:
            st.success("Test notification sent!")
        else:
            st.error(f"Webhook returned status {resp.status}")
    except Exception as e:
        st.error(f"Webhook test failed: {e}")


def show_awr_disclaimer():
    """AWR/ASH license acknowledgement for enhanced hotness scoring."""
    st.subheader("AWR / Diagnostics Pack License")
    st.warning(
        "**Important:** The AWR-enhanced hotness scoring feature queries `DBA_HIST_SEG_STAT` "
        "which is part of the **Oracle Diagnostics Pack**. Using this feature requires a valid "
        "Diagnostics Pack license on the target database. Using it without the license is a "
        "violation of Oracle licensing terms.\n\n"
        "**Ensure your database is properly licensed before enabling this feature.**"
    )

    acknowledged = st.session_state.get('awr_acknowledged', False)
    try:
        df = CentralConnector.execute_query(
            "SELECT value FROM t_schema_metadata WHERE key = 'awr_acknowledged'"
        )
        if not df.empty and df.iloc[0]['VALUE'] == 'Y':
            acknowledged = True
            st.session_state['awr_acknowledged'] = True
    except Exception:
        pass

    if acknowledged:
        st.success("AWR feature acknowledged and enabled. Enhanced hotness scoring is active.")
        if st.button("Revoke Acknowledgement", key="awr_revoke"):
            try:
                CentralConnector.execute_dml(
                    "DELETE FROM t_schema_metadata WHERE key = 'awr_acknowledged'"
                )
                st.session_state['awr_acknowledged'] = False
                st.rerun()
            except Exception:
                pass
    else:
        st.info("AWR-enhanced hotness scoring is **disabled**.")
        if st.checkbox("I confirm that the target database has a valid Oracle Diagnostics Pack license",
                       key="awr_confirm"):
            if st.button("Enable AWR Features", key="awr_enable", type="primary"):
                try:
                    CentralConnector.execute_dml("""
                        MERGE INTO t_schema_metadata tgt
                        USING (SELECT 'awr_acknowledged' as key FROM DUAL) src ON (tgt.key = src.key)
                        WHEN MATCHED THEN UPDATE SET value = 'Y'
                        WHEN NOT MATCHED THEN INSERT (key, value) VALUES ('awr_acknowledged', 'Y')
                    """)
                    st.session_state['awr_acknowledged'] = True
                    st.success("AWR features enabled!")
                    st.rerun()
                except Exception as e:
                    st.error(f"Failed: {e}")


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
