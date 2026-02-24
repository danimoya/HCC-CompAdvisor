"""
Target Database Manager - HCC Compression Advisor
Register and manage target Oracle databases for analysis
"""

import streamlit as st
import oracledb
from typing import Dict, Optional, Tuple
from datetime import datetime
from utils.central_queries import CentralQueries
from utils.target_connector import TargetConnector
from utils.logger import log_error, log_info
from config import config

# Try to import cryptography for password encryption
try:
    from cryptography.fernet import Fernet
    HAS_CRYPTO = True
except ImportError:
    HAS_CRYPTO = False


def encrypt_password(password: str) -> str:
    """Encrypt password for storage"""
    key = config.ENCRYPTION_KEY
    if key and HAS_CRYPTO:
        f = Fernet(key.encode() if isinstance(key, str) else key)
        return f.encrypt(password.encode()).decode()
    return password  # Store plain if no encryption key


def decrypt_password(encrypted: str) -> str:
    """Decrypt stored password"""
    key = config.ENCRYPTION_KEY
    if key and HAS_CRYPTO:
        try:
            f = Fernet(key.encode() if isinstance(key, str) else key)
            return f.decrypt(encrypted.encode()).decode()
        except Exception:
            return encrypted  # Return as-is if decryption fails
    return encrypted


def test_target_connection(conn_details: Dict) -> Tuple[bool, str, Optional[str]]:
    """Test a target database connection directly"""
    try:
        dsn = f"{conn_details['host']}:{conn_details['port']}/{conn_details['service']}"
        connection = oracledb.connect(
            user=conn_details['username'],
            password=conn_details['password'],
            dsn=dsn
        )
        cursor = connection.cursor()
        cursor.execute("SELECT 1 FROM DUAL")
        cursor.fetchone()
        cursor.close()

        cursor = connection.cursor()
        cursor.execute("SELECT banner FROM v$version WHERE ROWNUM = 1")
        version = cursor.fetchone()[0]
        cursor.close()
        connection.close()
        return True, "Connected successfully!", version
    except oracledb.Error as e:
        return False, f"Connection failed: {str(e)}", None


def show_connections_page():
    """Display the target database manager page"""

    st.markdown("## Target Database Manager")
    st.markdown("Register and manage Oracle databases for compression analysis")

    # Load target databases from central DB
    targets_df = CentralQueries.get_target_databases()

    # Active database banner
    active_db_id = st.session_state.get('active_database_id')
    if active_db_id and not targets_df.empty:
        targets_df.columns = [c.lower() for c in targets_df.columns]
        active_row = targets_df[targets_df['database_id'] == active_db_id]
        if not active_row.empty:
            active = active_row.iloc[0]
            st.markdown(f"""
            <div style="background: linear-gradient(90deg, #1a1a2e 0%, #16213e 100%);
                        padding: 15px 20px; border-radius: 10px; margin-bottom: 20px;
                        border-left: 4px solid green;">
                <span style="color: #888; font-size: 12px;">ACTIVE TARGET DATABASE</span>
                <h3 style="margin: 5px 0; color: white;">{active.get('display_name', 'N/A')}</h3>
                <code style="color: #4fc3f7;">{active.get('username', '')}@{active.get('host', '')}:{active.get('port', '')}/{active.get('service_name', '')}</code>
            </div>
            """, unsafe_allow_html=True)

    st.markdown("---")

    # Tabs
    tab1, tab2, tab3 = st.tabs(["Registered Databases", "Add New Database", "Quick Test"])

    # Tab 1: Registered databases
    with tab1:
        st.markdown("### Registered Target Databases")

        if targets_df.empty:
            st.info("No target databases registered. Add one in the 'Add New Database' tab.")
        else:
            if 'database_id' not in targets_df.columns:
                targets_df.columns = [c.lower() for c in targets_df.columns]

            for _, db in targets_df.iterrows():
                db_id = db.get('database_id')
                db_name = db.get('display_name', db.get('database_name', 'Unknown'))
                is_active = db_id == active_db_id
                env = db.get('environment', 'N/A')

                icon = "●" if is_active else "○"
                badge = " (Active)" if is_active else ""

                with st.expander(f"{icon} {db_name}{badge} - {env}", expanded=is_active):
                    col1, col2 = st.columns([3, 1])

                    with col1:
                        st.markdown(f"""
                        | Property | Value |
                        |----------|-------|
                        | **Host** | `{db.get('host', 'N/A')}` |
                        | **Port** | `{db.get('port', 'N/A')}` |
                        | **Service** | `{db.get('service_name', 'N/A')}` |
                        | **Username** | `{db.get('username', 'N/A')}` |
                        | **Environment** | {env} |
                        | **Platform** | {db.get('platform_type', 'STANDARD')} |
                        | **Oracle Version** | {db.get('oracle_version', 'Unknown')} |
                        | **Description** | {db.get('description', 'N/A')} |
                        | **Last Connected** | {str(db.get('last_connected', 'Never'))[:19] if db.get('last_connected') else 'Never'} |
                        """)

                    with col2:
                        st.markdown("**Actions**")

                        if st.button("Test", key=f"test_{db_id}", use_container_width=True):
                            pwd = decrypt_password(db.get('password_encrypted', ''))
                            conn = {
                                'host': db.get('host'),
                                'port': int(db.get('port', 1521)),
                                'service': db.get('service_name'),
                                'username': db.get('username'),
                                'password': pwd
                            }
                            with st.spinner("Testing..."):
                                success, msg, version = test_target_connection(conn)
                                if success:
                                    CentralQueries.update_target_last_connected(db_id)
                                    if version:
                                        CentralQueries.update_target_metadata(db_id, version, db.get('platform_type', 'STANDARD'))
                                    st.success(f"{msg}\n{version}")
                                else:
                                    st.error(msg)

                        if not is_active:
                            if st.button("Set Active", key=f"activate_{db_id}", use_container_width=True, type="primary"):
                                st.session_state.active_database_id = db_id
                                st.success(f"'{db_name}' is now active")
                                st.rerun()

                        if st.button("Remove", key=f"delete_{db_id}", use_container_width=True, disabled=is_active):
                            success, msg = CentralQueries.delete_target_database(db_id)
                            if success:
                                if active_db_id == db_id:
                                    st.session_state.active_database_id = None
                                st.success(msg)
                                st.rerun()
                            else:
                                st.error(msg)

    # Tab 2: Add new database
    with tab2:
        st.markdown("### Add New Target Database")

        with st.form("new_target_form"):
            col1, col2 = st.columns(2)

            with col1:
                db_name = st.text_input("Database Name *", placeholder="e.g., prod-oracle-01")
                display_name = st.text_input("Display Name *", placeholder="e.g., Production DB")
                host = st.text_input("Host *", placeholder="hostname or IP")
                service = st.text_input("Service Name *", placeholder="e.g., FREEPDB1")
                password = st.text_input("Password *", type="password")

            with col2:
                environment = st.selectbox("Environment", options=['PROD', 'DEV', 'TEST', 'UAT'])
                platform_type = st.selectbox("Platform", options=['STANDARD', 'EXADATA'])
                port = st.number_input("Port *", min_value=1, max_value=65535, value=1521)
                username = st.text_input("Username *", placeholder="e.g., COMPRESSION_MGR")
                description = st.text_input("Description", placeholder="Optional description")

            set_active = st.checkbox("Set as active database", value=True)
            submitted = st.form_submit_button("Add Database", use_container_width=True)

            if submitted:
                if not all([db_name, display_name, host, service, username, password]):
                    st.error("Please fill in all required fields")
                else:
                    # Test first
                    test_conn = {'host': host, 'port': port, 'service': service, 'username': username, 'password': password}
                    with st.spinner("Testing connection..."):
                        success, msg, version = test_target_connection(test_conn)

                    if success:
                        db_data = {
                            'database_name': db_name,
                            'display_name': display_name,
                            'host': host,
                            'port': port,
                            'service_name': service,
                            'username': username,
                            'password_encrypted': encrypt_password(password),
                            'description': description,
                            'environment': environment,
                            'platform_type': platform_type,
                            'oracle_version': version
                        }
                        ok, result_msg, new_id = CentralQueries.add_target_database(db_data)
                        if ok:
                            if set_active and new_id:
                                st.session_state.active_database_id = new_id
                            st.success(f"Database added! {version}")
                            st.rerun()
                        else:
                            st.error(f"Failed to save: {result_msg}")
                    else:
                        st.error(f"Connection test failed: {msg}")

    # Tab 3: Quick test
    with tab3:
        st.markdown("### Quick Connection Test")
        st.markdown("Test connection details without saving.")

        col1, col2 = st.columns(2)
        with col1:
            test_host = st.text_input("Host", value="localhost", key="test_host")
            test_service = st.text_input("Service Name", value="FREEPDB1", key="test_service")
            test_password = st.text_input("Password", type="password", key="test_password")
        with col2:
            test_port = st.number_input("Port", value=1521, key="test_port")
            test_username = st.text_input("Username", value="COMPRESSION_MGR", key="test_username")

        if st.button("Test Connection", key="quick_test", use_container_width=True, type="primary"):
            test_conn = {'host': test_host, 'port': test_port, 'service': test_service, 'username': test_username, 'password': test_password}
            with st.spinner("Testing..."):
                success, msg, version = test_target_connection(test_conn)
            if success:
                st.success(f"{msg}\n{version}")
            else:
                st.error(msg)
