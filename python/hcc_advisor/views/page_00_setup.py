"""
Deployment / Setup Page - HCC Compression Advisor
Pre-login wizard shown when central DB is not configured or schema needs attention.
Handles first-run setup, schema install, re-install, upgrade, and cleanup.
"""

import streamlit as st
import oracledb
from pathlib import Path
from typing import Optional, Dict, Tuple
from cryptography.fernet import Fernet

from hcc_advisor import __version__
from hcc_advisor.config import Config, config


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_sql_dir() -> Path:
    """Locate the sql/central directory bundled with the package."""
    # When installed via pip, SQL files are at hcc_advisor/sql/central/
    pkg_sql = Path(__file__).parent.parent / 'sql' / 'central'
    if pkg_sql.exists():
        return pkg_sql
    # Dev layout: repo_root/sql/central/
    repo_sql = Path(__file__).parent.parent.parent.parent / 'sql' / 'central'
    if repo_sql.exists():
        return repo_sql
    return pkg_sql  # fallback


def _test_connection(host: str, port: int, service: str, user: str, password: str) -> Tuple[bool, str]:
    """Test Oracle connection and return (success, message)."""
    try:
        dsn = f"{host}:{port}/{service}"
        conn = oracledb.connect(user=user, password=password, dsn=dsn)
        cur = conn.cursor()
        cur.execute("SELECT BANNER FROM V$VERSION WHERE ROWNUM = 1")
        row = cur.fetchone()
        banner = row[0] if row else "Unknown"
        cur.close()
        conn.close()
        return True, banner
    except oracledb.Error as e:
        return False, str(e)


def _check_privileges(host: str, port: int, service: str, user: str, password: str) -> Tuple[bool, list]:
    """Check required privileges. Returns (all_ok, list_of_results)."""
    required = ['CREATE TABLE', 'CREATE SEQUENCE', 'CREATE SESSION',
                 'CREATE PROCEDURE', 'CREATE VIEW', 'CREATE TRIGGER', 'CREATE TYPE']
    results = []
    try:
        dsn = f"{host}:{port}/{service}"
        conn = oracledb.connect(user=user, password=password, dsn=dsn)
        cur = conn.cursor()
        for priv in required:
            cur.execute(
                "SELECT COUNT(*) FROM session_privs WHERE privilege = :p",
                {'p': priv}
            )
            has = cur.fetchone()[0] > 0
            results.append((priv, has))
        # Check tablespace quota
        cur.execute(
            "SELECT COUNT(*) FROM user_ts_quotas WHERE max_bytes = -1 OR max_bytes > 0"
        )
        has_quota = cur.fetchone()[0] > 0
        results.append(('TABLESPACE QUOTA', has_quota))
        cur.close()
        conn.close()
    except oracledb.Error as e:
        results.append(('CONNECTION', False))
    all_ok = all(ok for _, ok in results)
    return all_ok, results


def _get_schema_state(host: str, port: int, service: str, user: str, password: str) -> Dict:
    """Inspect the schema: installed tables, version, install date."""
    state = {'connected': False, 'tables_found': 0, 'total_tables': 9,
             'version': None, 'installed_at': None, 'banner': None}
    try:
        dsn = f"{host}:{port}/{service}"
        conn = oracledb.connect(user=user, password=password, dsn=dsn)
        state['connected'] = True

        cur = conn.cursor()
        cur.execute("SELECT BANNER FROM V$VERSION WHERE ROWNUM = 1")
        row = cur.fetchone()
        state['banner'] = row[0] if row else "Unknown"

        # Count known tables
        expected = [
            'T_TARGET_DATABASES', 'T_COMPRESSION_STRATEGIES', 'T_STRATEGY_RULES',
            'T_ADVISOR_RUN', 'T_COMPRESSION_ANALYSIS', 'T_COMPRESSION_HISTORY',
            'T_INDEX_COMPRESSION_ANALYSIS', 'T_LOB_COMPRESSION_ANALYSIS',
            'T_SCHEMA_METADATA'
        ]
        placeholders = ', '.join([f"'{t}'" for t in expected])
        cur.execute(f"SELECT COUNT(*) FROM user_tables WHERE table_name IN ({placeholders})")
        state['tables_found'] = cur.fetchone()[0]

        # Version
        cur.execute("SELECT value FROM t_schema_metadata WHERE key = 'schema_version'")
        row = cur.fetchone()
        state['version'] = row[0] if row else None

        cur.execute("SELECT value FROM t_schema_metadata WHERE key = 'installed_at'")
        row = cur.fetchone()
        state['installed_at'] = row[0] if row else None

        cur.close()
        conn.close()
    except Exception:
        pass
    return state


def _drop_all_hcc_objects(host: str, port: int, service: str, user: str, password: str) -> list:
    """Drop all HCC tables and sequences. Returns list of messages."""
    tables = [
        'T_COMPRESSION_HISTORY', 'T_LOB_COMPRESSION_ANALYSIS',
        'T_INDEX_COMPRESSION_ANALYSIS', 'T_COMPRESSION_ANALYSIS',
        'T_ADVISOR_RUN', 'T_STRATEGY_RULES', 'T_COMPRESSION_STRATEGIES',
        'T_TARGET_DATABASES', 'T_SCHEMA_METADATA'
    ]
    sequences = ['SEQ_DATABASE_ID']
    messages = []
    try:
        dsn = f"{host}:{port}/{service}"
        conn = oracledb.connect(user=user, password=password, dsn=dsn)
        cur = conn.cursor()
        for tbl in tables:
            try:
                cur.execute(f"DROP TABLE {tbl} CASCADE CONSTRAINTS PURGE")
                messages.append(f"Dropped table {tbl}")
            except oracledb.Error:
                pass
        for seq in sequences:
            try:
                cur.execute(f"DROP SEQUENCE {seq}")
                messages.append(f"Dropped sequence {seq}")
            except oracledb.Error:
                pass
        conn.commit()
        cur.close()
        conn.close()
    except oracledb.Error as e:
        messages.append(f"Error: {e}")
    return messages


def _run_schema_install(host: str, port: int, service: str, user: str, password: str,
                        progress_callback=None) -> Tuple[int, int, list]:
    """Execute central schema + seed SQL files via sql_executor."""
    from hcc_advisor.utils.sql_executor import execute_sql_file

    sql_dir = _get_sql_dir()
    schema_file = sql_dir / '01_central_schema.sql'
    seed_file = sql_dir / '02_seed_strategies.sql'

    dsn = f"{host}:{port}/{service}"
    conn = oracledb.connect(user=user, password=password, dsn=dsn)

    total_ok = 0
    total_err = 0
    all_msgs = []

    for sql_file in [schema_file, seed_file]:
        if sql_file.exists():
            ok, err, msgs = execute_sql_file(conn, sql_file, on_progress=progress_callback)
            total_ok += ok
            total_err += err
            all_msgs.extend(msgs)

    conn.close()
    return total_ok, total_err, all_msgs


# ---------------------------------------------------------------------------
# Main page
# ---------------------------------------------------------------------------

def show_deployment_page(mode: str = 'setup'):
    """
    Display the deployment/setup page.

    Args:
        mode: 'setup' for first-run, 'upgrade' for schema version mismatch
    """
    # Page config may already have been set by app.py (which now sets it first so
    # the auth gate can render before this wizard). set_page_config can only be
    # called once per run, so ignore the "already set" error in that case.
    try:
        st.set_page_config(
            page_title="HCC Advisor - Setup",
            page_icon="🔧",
            layout="centered"
        )
    except st.errors.StreamlitAPIException:
        pass

    st.markdown("""
    <style>
        .setup-header { text-align: center; padding: 1rem 0; }
        .status-box { padding: 1rem; border-radius: 0.5rem; margin: 0.5rem 0; }
        .status-ok { background-color: #1a3d2a; border-left: 4px solid #28a745; color: #d4edda; }
        .status-warn { background-color: #3d3a1a; border-left: 4px solid #ffc107; color: #fff3cd; }
        .status-err { background-color: #3d1a1a; border-left: 4px solid #dc3545; color: #f8d7da; }
    </style>
    """, unsafe_allow_html=True)

    st.markdown('<div class="setup-header"><h1>🔧 HCC Compression Advisor Setup</h1></div>',
                unsafe_allow_html=True)
    st.markdown(f"**Package Version:** `{__version__}`")
    st.markdown("---")

    # Initialize session state for wizard
    if 'setup_step' not in st.session_state:
        st.session_state.setup_step = 0
    if 'setup_conn' not in st.session_state:
        st.session_state.setup_conn = {}

    # If env vars exist but schema needs attention, show status panel
    if mode == 'upgrade' and config.CENTRAL_DB_PASSWORD:
        _show_existing_installation()
        return

    # First-run wizard
    _show_setup_wizard()


def _show_existing_installation():
    """Show status panel for an existing installation that needs attention."""
    st.subheader("Existing Installation Detected")

    state = _get_schema_state(
        config.CENTRAL_DB_HOST, config.CENTRAL_DB_PORT,
        config.CENTRAL_DB_SERVICE, config.CENTRAL_DB_USER,
        config.CENTRAL_DB_PASSWORD
    )

    if state['connected']:
        st.success(f"Central DB: connected ({state['banner']})")
    else:
        st.error("Central DB: connection failed")
        st.info("Check your environment variables or .env file.")
        st.stop()

    col1, col2 = st.columns(2)
    with col1:
        st.markdown(f"**Schema Version:** `{state['version'] or 'not found'}`")
        st.markdown(f"**Package Version:** `{__version__}`")
    with col2:
        st.markdown(f"**Tables:** {state['tables_found']}/{state['total_tables']} present")
        st.markdown(f"**Installed:** {state['installed_at'] or 'unknown'}")

    # Status
    if state['version'] and state['version'] == __version__:
        st.info("Schema is up to date.")
    elif state['version']:
        st.warning(f"Schema version mismatch: DB has `{state['version']}`, package is `{__version__}`")
    else:
        st.warning("Schema metadata not found. Schema may need re-installation.")

    st.markdown("---")

    col1, col2, col3, col4 = st.columns(4)

    with col1:
        if st.button("Re-install Schema", type="secondary", use_container_width=True):
            st.session_state.setup_action = 'reinstall'

    with col2:
        if st.button("Upgrade", type="secondary", use_container_width=True):
            st.session_state.setup_action = 'upgrade'

    with col3:
        if st.button("Cleanup / Uninstall", type="secondary", use_container_width=True):
            st.session_state.setup_action = 'cleanup'

    with col4:
        if st.button("Continue to Dashboard", type="primary", use_container_width=True):
            st.session_state.setup_complete = True
            st.rerun()

    # Handle actions
    action = st.session_state.get('setup_action')

    if action == 'reinstall':
        st.markdown("---")
        st.warning("**Re-install** will DROP all HCC tables and recreate the schema. All data will be lost.")
        if st.button("Confirm Re-install", type="primary"):
            with st.spinner("Dropping existing objects..."):
                drop_msgs = _drop_all_hcc_objects(
                    config.CENTRAL_DB_HOST, config.CENTRAL_DB_PORT,
                    config.CENTRAL_DB_SERVICE, config.CENTRAL_DB_USER,
                    config.CENTRAL_DB_PASSWORD
                )
                for msg in drop_msgs:
                    st.text(msg)

            progress = st.progress(0, text="Installing schema...")

            def on_progress(cur, total, stype, msg):
                if total > 0:
                    progress.progress(cur / total, text=msg)

            ok, err, msgs = _run_schema_install(
                config.CENTRAL_DB_HOST, config.CENTRAL_DB_PORT,
                config.CENTRAL_DB_SERVICE, config.CENTRAL_DB_USER,
                config.CENTRAL_DB_PASSWORD,
                progress_callback=on_progress
            )
            progress.progress(1.0, text="Done!")

            if err == 0:
                st.success(f"Schema re-installed successfully ({ok} statements executed)")
            else:
                st.warning(f"Completed with {err} errors ({ok} successful)")

            with st.expander("Execution Details"):
                for msg in msgs:
                    st.text(msg)

            st.session_state.pop('setup_action', None)

    elif action == 'upgrade':
        st.markdown("---")
        st.info("For v2.0.0, upgrade performs a full re-install (no migration scripts yet).")
        if st.button("Confirm Upgrade (Re-install)", type="primary"):
            with st.spinner("Dropping existing objects..."):
                _drop_all_hcc_objects(
                    config.CENTRAL_DB_HOST, config.CENTRAL_DB_PORT,
                    config.CENTRAL_DB_SERVICE, config.CENTRAL_DB_USER,
                    config.CENTRAL_DB_PASSWORD
                )

            progress = st.progress(0, text="Installing schema...")

            def on_progress(cur, total, stype, msg):
                if total > 0:
                    progress.progress(cur / total, text=msg)

            ok, err, msgs = _run_schema_install(
                config.CENTRAL_DB_HOST, config.CENTRAL_DB_PORT,
                config.CENTRAL_DB_SERVICE, config.CENTRAL_DB_USER,
                config.CENTRAL_DB_PASSWORD,
                progress_callback=on_progress
            )
            progress.progress(1.0, text="Done!")

            if err == 0:
                st.success(f"Schema upgraded successfully ({ok} statements)")
            else:
                st.warning(f"Completed with {err} errors ({ok} successful)")

            with st.expander("Execution Details"):
                for msg in msgs:
                    st.text(msg)

            st.session_state.pop('setup_action', None)

    elif action == 'cleanup':
        st.markdown("---")
        st.error("**Cleanup** will DROP all HCC tables and remove the .env configuration. This cannot be undone.")
        if st.button("Confirm Cleanup", type="primary"):
            with st.spinner("Dropping all HCC objects..."):
                drop_msgs = _drop_all_hcc_objects(
                    config.CENTRAL_DB_HOST, config.CENTRAL_DB_PORT,
                    config.CENTRAL_DB_SERVICE, config.CENTRAL_DB_USER,
                    config.CENTRAL_DB_PASSWORD
                )
                for msg in drop_msgs:
                    st.text(msg)

            # Remove .env from config dir
            env_file = Config.get_config_dir() / '.env'
            if env_file.exists():
                env_file.unlink()
                st.text(f"Removed {env_file}")

            st.success("Cleanup complete. Refresh to start fresh.")
            st.session_state.pop('setup_action', None)

    st.stop()


def _show_setup_wizard():
    """Show the first-run setup wizard."""
    step = st.session_state.setup_step
    conn = st.session_state.setup_conn

    # Progress indicator
    steps = ["Welcome", "Database Connection", "Test & Verify", "Deploy Schema", "Security", "Finish"]
    cols = st.columns(len(steps))
    for i, (col, label) in enumerate(zip(cols, steps)):
        with col:
            if i < step:
                st.markdown(f"~~{label}~~")
            elif i == step:
                st.markdown(f"**{label}**")
            else:
                st.markdown(f"<span style='color:gray'>{label}</span>", unsafe_allow_html=True)

    st.markdown("---")

    if step == 0:
        _wizard_welcome()
    elif step == 1:
        _wizard_connection()
    elif step == 2:
        _wizard_verify()
    elif step == 3:
        _wizard_deploy()
    elif step == 4:
        _wizard_security()
    elif step == 5:
        _wizard_finish()

    st.stop()


def _wizard_welcome():
    """Step 0: Welcome"""
    st.subheader("Welcome to HCC Compression Advisor")
    st.markdown(f"""
    This wizard will set up the central database schema for HCC Advisor v`{__version__}`.

    **Prerequisites:**
    - An Oracle database (23c Free, 23ai, or Exadata) accessible via TCP
    - A database user with CREATE TABLE, SEQUENCE, SESSION, PROCEDURE, VIEW, TRIGGER, TYPE privileges
    - Sufficient tablespace quota

    The central database stores all analysis results, compression history, strategies,
    and target database registrations.
    """)

    if st.button("Begin Setup", type="primary"):
        st.session_state.setup_step = 1
        st.rerun()


def _wizard_connection():
    """Step 1: Database Connection"""
    st.subheader("Central Database Connection")

    conn = st.session_state.setup_conn

    with st.form("db_connection_form"):
        host = st.text_input("Host", value=conn.get('host', 'localhost'))
        col1, col2 = st.columns(2)
        with col1:
            port = st.number_input("Port", value=conn.get('port', 1521), min_value=1, max_value=65535)
        with col2:
            service = st.text_input("Service Name", value=conn.get('service', 'FREEPDB1'))

        username = st.text_input("Username", value=conn.get('username', 'COMPRESSION_MGR'))
        password = st.text_input("Password", type="password", value=conn.get('password', ''))

        col1, col2 = st.columns(2)
        with col1:
            back = st.form_submit_button("Back")
        with col2:
            submit = st.form_submit_button("Test Connection", type="primary")

    if back:
        st.session_state.setup_step = 0
        st.rerun()

    if submit:
        if not all([host, service, username, password]):
            st.error("All fields are required.")
            return

        st.session_state.setup_conn = {
            'host': host, 'port': int(port), 'service': service,
            'username': username, 'password': password
        }
        st.session_state.setup_step = 2
        st.rerun()


def _wizard_verify():
    """Step 2: Test Connection & Verify Privileges"""
    st.subheader("Connection Test & Privilege Verification")

    conn = st.session_state.setup_conn

    # Test connection
    with st.spinner("Testing connection..."):
        ok, banner = _test_connection(conn['host'], conn['port'], conn['service'],
                                       conn['username'], conn['password'])

    if ok:
        st.success(f"Connection successful: {banner}")
    else:
        st.error(f"Connection failed: {banner}")
        if st.button("Back to Connection"):
            st.session_state.setup_step = 1
            st.rerun()
        return

    # Check privileges
    with st.spinner("Checking privileges..."):
        all_ok, priv_results = _check_privileges(
            conn['host'], conn['port'], conn['service'],
            conn['username'], conn['password']
        )

    st.markdown("**Required Privileges:**")
    for priv, has in priv_results:
        icon = "✅" if has else "❌"
        st.markdown(f"{icon} {priv}")

    # Check schema state
    state = _get_schema_state(conn['host'], conn['port'], conn['service'],
                               conn['username'], conn['password'])

    if state['version']:
        st.markdown("---")
        st.info(f"Existing schema detected: v{state['version']} ({state['tables_found']}/{state['total_tables']} tables)")
        st.session_state.setup_conn['schema_state'] = state

    st.markdown("---")
    col1, col2 = st.columns(2)
    with col1:
        if st.button("Back"):
            st.session_state.setup_step = 1
            st.rerun()
    with col2:
        if all_ok:
            if st.button("Deploy Schema", type="primary"):
                st.session_state.setup_step = 3
                st.rerun()
        else:
            st.warning("Some privileges are missing. Grant them before continuing.")


def _wizard_deploy():
    """Step 3: Deploy Schema"""
    st.subheader("Deploy Central Schema")

    conn = st.session_state.setup_conn
    schema_state = conn.get('schema_state', {})

    if schema_state.get('version'):
        st.warning(f"Existing schema v{schema_state['version']} detected. Deploying will re-install.")
        if st.button("Drop existing and re-install"):
            with st.spinner("Dropping existing objects..."):
                _drop_all_hcc_objects(conn['host'], conn['port'], conn['service'],
                                      conn['username'], conn['password'])
            st.session_state.setup_conn.pop('schema_state', None)
            st.rerun()
        if st.button("Skip (keep existing schema)"):
            st.session_state.setup_step = 4
            st.rerun()
        return

    sql_dir = _get_sql_dir()
    schema_file = sql_dir / '01_central_schema.sql'
    seed_file = sql_dir / '02_seed_strategies.sql'

    st.markdown(f"**SQL Directory:** `{sql_dir}`")
    st.markdown(f"- Schema: `{'found' if schema_file.exists() else 'MISSING'}`")
    st.markdown(f"- Seed Data: `{'found' if seed_file.exists() else 'MISSING'}`")

    if not schema_file.exists():
        st.error("Schema SQL file not found. Ensure the package includes sql/central/ files.")
        return

    if st.button("Install Schema", type="primary"):
        progress = st.progress(0, text="Starting installation...")

        def on_progress(cur, total, stype, msg):
            if total > 0:
                progress.progress(min(cur / total, 1.0), text=msg)

        ok, err, msgs = _run_schema_install(
            conn['host'], conn['port'], conn['service'],
            conn['username'], conn['password'],
            progress_callback=on_progress
        )
        progress.progress(1.0, text="Installation complete!")

        if err == 0:
            st.success(f"Schema deployed successfully! ({ok} statements)")
            st.session_state.setup_step = 4
            st.rerun()
        else:
            st.warning(f"Completed with {err} errors ({ok} successful)")
            with st.expander("Execution Details"):
                for msg in msgs:
                    st.text(msg)

    col1, col2 = st.columns(2)
    with col1:
        if st.button("Back"):
            st.session_state.setup_step = 2
            st.rerun()


def _wizard_security():
    """Step 4: Security Setup"""
    st.subheader("Security Configuration")

    conn = st.session_state.setup_conn

    with st.form("security_form"):
        dash_pwd = st.text_input("Dashboard Password", type="password",
                                  help="Password to access the web dashboard")
        dash_pwd_confirm = st.text_input("Confirm Password", type="password")

        st.markdown("**Encryption Key** (for storing target database passwords)")
        if st.session_state.get('generated_key'):
            enc_key = st.session_state.generated_key
        else:
            enc_key = Fernet.generate_key().decode()
            st.session_state.generated_key = enc_key

        st.code(enc_key, language=None)
        st.caption("Save this key securely. It encrypts target database credentials.")

        col1, col2 = st.columns(2)
        with col1:
            back = st.form_submit_button("Back")
        with col2:
            submit = st.form_submit_button("Save Configuration", type="primary")

    if back:
        st.session_state.setup_step = 3
        st.rerun()

    if submit:
        if not dash_pwd:
            st.error("Dashboard password is required.")
            return
        if dash_pwd != dash_pwd_confirm:
            st.error("Passwords do not match.")
            return

        st.session_state.setup_conn['dashboard_password'] = dash_pwd
        st.session_state.setup_conn['encryption_key'] = enc_key
        st.session_state.setup_step = 5
        st.rerun()


def _wizard_finish():
    """Step 5: Save & Finish"""
    st.subheader("Setup Complete")

    conn = st.session_state.setup_conn

    settings = {
        'CENTRAL_DB_HOST': conn['host'],
        'CENTRAL_DB_PORT': str(conn['port']),
        'CENTRAL_DB_SERVICE': conn['service'],
        'CENTRAL_DB_USER': conn['username'],
        'CENTRAL_DB_PASSWORD': conn['password'],
        'DASHBOARD_PASSWORD': conn.get('dashboard_password', 'admin123'),
        'ENCRYPTION_KEY': conn.get('encryption_key', ''),
    }

    st.markdown("**Configuration Summary:**")
    for k, v in settings.items():
        display_val = '***' if 'PASSWORD' in k or 'KEY' in k else v
        st.markdown(f"- `{k}` = `{display_val}`")

    if st.button("Save & Launch Dashboard", type="primary"):
        with st.spinner("Writing configuration..."):
            env_path = Config.write_env_file(settings)
        st.success(f"Configuration saved to `{env_path}`")
        st.session_state.setup_complete = True
        st.balloons()
        st.markdown("Refreshing in 3 seconds...")
        import time
        time.sleep(3)
        st.rerun()

    if st.button("Back"):
        st.session_state.setup_step = 4
        st.rerun()
