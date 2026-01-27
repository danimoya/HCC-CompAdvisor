"""
Connection Manager Page - Manage database connections for HCC Compression Advisor
"""

import streamlit as st
import json
import os
from pathlib import Path
from typing import Dict, List, Optional
from datetime import datetime
import oracledb

# Connections storage file
CONNECTIONS_FILE = Path(__file__).parent.parent / "data" / "connections.json"


def load_connections() -> Dict:
    """Load saved connections from file"""
    if CONNECTIONS_FILE.exists():
        try:
            with open(CONNECTIONS_FILE, 'r') as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            pass

    # Return default structure with test connection pre-populated
    return {
        "connections": {
            "Oracle Free 23c (Test)": {
                "host": "hcc-oracle-23c",
                "port": 1521,
                "service": "FREEPDB1",
                "username": "COMPRESSION_MGR",
                "password": "Compress123",
                "description": "Test Oracle Free 23c container for HCC testing",
                "tested_ok": False,
                "last_tested": None
            }
        },
        "active_connection": "Oracle Free 23c (Test)"
    }


def save_connections(data: Dict) -> bool:
    """Save connections to file"""
    try:
        # Ensure data directory exists
        CONNECTIONS_FILE.parent.mkdir(parents=True, exist_ok=True)

        with open(CONNECTIONS_FILE, 'w') as f:
            json.dump(data, f, indent=2)
        return True
    except IOError as e:
        st.error(f"Failed to save connections: {e}")
        return False


def test_connection(conn_details: Dict) -> tuple:
    """Test a database connection and return (success, message, version)"""
    try:
        dsn = f"{conn_details['host']}:{conn_details['port']}/{conn_details['service']}"
        connection = oracledb.connect(
            user=conn_details['username'],
            password=conn_details['password'],
            dsn=dsn
        )

        # Test with simple query
        cursor = connection.cursor()
        cursor.execute("SELECT 1 FROM DUAL")
        cursor.fetchone()
        cursor.close()

        # Get database version
        cursor = connection.cursor()
        cursor.execute("SELECT banner FROM v$version WHERE ROWNUM = 1")
        version = cursor.fetchone()[0]
        cursor.close()

        connection.close()
        return True, f"Connected successfully!", version
    except oracledb.Error as e:
        return False, f"Connection failed: {str(e)}", None


def get_active_connection() -> Optional[Dict]:
    """Get the currently active connection details"""
    data = load_connections()
    active_name = data.get("active_connection")
    if active_name and active_name in data.get("connections", {}):
        conn = data["connections"][active_name].copy()
        conn["name"] = active_name
        return conn
    return None


def get_tested_connections(data: Dict) -> List[str]:
    """Get list of connection names that have been tested OK"""
    tested = []
    for name, details in data.get("connections", {}).items():
        if details.get("tested_ok", False):
            tested.append(name)
    return tested


def show_connections_page():
    """Display the connection manager page"""

    st.markdown("## :link: Connection Manager")
    st.markdown("Manage database connections for the HCC Compression Advisor")

    # Load current connections
    data = load_connections()
    connections = data.get("connections", {})
    active_connection = data.get("active_connection")

    # =========================================================================
    # ACTIVE CONNECTION BANNER (TOP)
    # =========================================================================
    active_conn = get_active_connection()

    if active_conn:
        # Status indicator
        is_tested = active_conn.get("tested_ok", False)
        status_color = "green" if is_tested else "orange"
        status_text = "Tested OK" if is_tested else "Not Tested"

        st.markdown(f"""
        <div style="background: linear-gradient(90deg, #1a1a2e 0%, #16213e 100%);
                    padding: 15px 20px; border-radius: 10px; margin-bottom: 20px;
                    border-left: 4px solid {status_color};">
            <div style="display: flex; justify-content: space-between; align-items: center;">
                <div>
                    <span style="color: #888; font-size: 12px;">ACTIVE CONNECTION</span>
                    <h3 style="margin: 5px 0; color: white;">{active_conn.get('name', 'N/A')}</h3>
                    <code style="color: #4fc3f7;">{active_conn.get('username')}@{active_conn.get('host')}:{active_conn.get('port')}/{active_conn.get('service')}</code>
                </div>
                <div style="text-align: right;">
                    <span style="background: {status_color}; color: white; padding: 4px 12px;
                                 border-radius: 12px; font-size: 12px;">{status_text}</span>
                </div>
            </div>
        </div>
        """, unsafe_allow_html=True)

        # Quick Switch Section
        tested_connections = get_tested_connections(data)
        other_tested = [c for c in tested_connections if c != active_connection]

        if other_tested:
            col1, col2, col3 = st.columns([2, 2, 1])
            with col1:
                switch_to = st.selectbox(
                    "Quick Switch",
                    options=other_tested,
                    key="quick_switch",
                    label_visibility="collapsed",
                    help="Switch to another tested connection"
                )
            with col2:
                if st.button("Switch Connection", use_container_width=True, type="primary"):
                    data["active_connection"] = switch_to
                    if save_connections(data):
                        st.success(f"Switched to '{switch_to}'")
                        st.rerun()
            with col3:
                if st.button("Test Current", use_container_width=True):
                    with st.spinner("Testing..."):
                        success, message, version = test_connection(active_conn)
                        if success:
                            # Update tested status
                            data["connections"][active_connection]["tested_ok"] = True
                            data["connections"][active_connection]["last_tested"] = datetime.now().isoformat()
                            save_connections(data)
                            st.success(f"{message}\n{version}")
                        else:
                            data["connections"][active_connection]["tested_ok"] = False
                            save_connections(data)
                            st.error(message)
        else:
            col1, col2 = st.columns([3, 1])
            with col2:
                if st.button("Test Current Connection", use_container_width=True):
                    with st.spinner("Testing..."):
                        success, message, version = test_connection(active_conn)
                        if success:
                            data["connections"][active_connection]["tested_ok"] = True
                            data["connections"][active_connection]["last_tested"] = datetime.now().isoformat()
                            save_connections(data)
                            st.success(f"{message}\n{version}")
                        else:
                            data["connections"][active_connection]["tested_ok"] = False
                            save_connections(data)
                            st.error(message)
            with col1:
                st.info("No other tested connections available. Test a connection to enable quick switch.")
    else:
        st.warning("No active connection set. Please select or add a connection below.")

    st.markdown("---")

    # =========================================================================
    # TABS FOR MANAGEMENT
    # =========================================================================
    tab1, tab2, tab3 = st.tabs(["Saved Connections", "Add New Connection", "Quick Test"])

    # Tab 1: Saved Connections
    with tab1:
        st.markdown("### Saved Connections")

        if not connections:
            st.info("No saved connections. Add a new connection to get started.")
        else:
            for conn_name, conn_details in connections.items():
                is_active = conn_name == active_connection
                is_tested = conn_details.get("tested_ok", False)
                last_tested = conn_details.get("last_tested")

                # Status badges
                badges = []
                if is_active:
                    badges.append("Active")
                if is_tested:
                    badges.append("Tested OK")

                badge_str = " | ".join(badges) if badges else "Not Tested"
                icon = "✓" if is_tested else "○"

                with st.expander(
                    f"{icon} {conn_name} ({badge_str})",
                    expanded=is_active
                ):
                    col1, col2 = st.columns([3, 1])

                    with col1:
                        st.markdown(f"""
                        | Property | Value |
                        |----------|-------|
                        | **Host** | `{conn_details.get('host', 'N/A')}` |
                        | **Port** | `{conn_details.get('port', 'N/A')}` |
                        | **Service** | `{conn_details.get('service', 'N/A')}` |
                        | **Username** | `{conn_details.get('username', 'N/A')}` |
                        | **Password** | `{'*' * 8}` |
                        | **Description** | {conn_details.get('description', 'N/A')} |
                        | **Last Tested** | {last_tested[:16].replace('T', ' ') if last_tested else 'Never'} |
                        """)

                    with col2:
                        st.markdown("**Actions**")

                        # Test connection button
                        if st.button("Test", key=f"test_{conn_name}", use_container_width=True):
                            with st.spinner("Testing connection..."):
                                success, message, version = test_connection(conn_details)
                                if success:
                                    # Update tested status
                                    data["connections"][conn_name]["tested_ok"] = True
                                    data["connections"][conn_name]["last_tested"] = datetime.now().isoformat()
                                    save_connections(data)
                                    st.success(f"{message}\n{version}")
                                    st.rerun()
                                else:
                                    data["connections"][conn_name]["tested_ok"] = False
                                    save_connections(data)
                                    st.error(message)

                        # Set as active button
                        if not is_active:
                            btn_type = "primary" if is_tested else "secondary"
                            if st.button(
                                "Set Active",
                                key=f"activate_{conn_name}",
                                use_container_width=True,
                                type=btn_type,
                                disabled=not is_tested,
                                help="Test connection first" if not is_tested else None
                            ):
                                data["active_connection"] = conn_name
                                if save_connections(data):
                                    st.success(f"'{conn_name}' is now the active connection")
                                    st.rerun()

                        # Delete button (disabled if active)
                        if st.button(
                            "Delete",
                            key=f"delete_{conn_name}",
                            use_container_width=True,
                            disabled=is_active,
                            help="Cannot delete active connection" if is_active else None
                        ):
                            del data["connections"][conn_name]
                            if save_connections(data):
                                st.success(f"Deleted '{conn_name}'")
                                st.rerun()

    # Tab 2: Add New Connection
    with tab2:
        st.markdown("### Add New Connection")

        with st.form("new_connection_form"):
            conn_name = st.text_input(
                "Connection Name *",
                placeholder="e.g., Production DB, Dev Oracle"
            )

            col1, col2 = st.columns(2)

            with col1:
                host = st.text_input(
                    "Host *",
                    placeholder="hostname or IP address"
                )
                service = st.text_input(
                    "Service Name *",
                    placeholder="e.g., FREEPDB1, XEPDB1, ORCL"
                )
                password = st.text_input(
                    "Password *",
                    type="password"
                )

            with col2:
                port = st.number_input(
                    "Port *",
                    min_value=1,
                    max_value=65535,
                    value=1521
                )
                username = st.text_input(
                    "Username *",
                    placeholder="database username"
                )
                description = st.text_input(
                    "Description",
                    placeholder="Optional description"
                )

            set_active = st.checkbox("Set as active connection", value=True)

            submitted = st.form_submit_button("Add Connection", use_container_width=True)

            if submitted:
                # Validate required fields
                if not all([conn_name, host, service, username, password]):
                    st.error("Please fill in all required fields (marked with *)")
                elif conn_name in connections:
                    st.error(f"A connection named '{conn_name}' already exists")
                else:
                    # Test connection first
                    new_conn = {
                        "host": host,
                        "port": port,
                        "service": service,
                        "username": username,
                        "password": password,
                        "description": description,
                        "tested_ok": False,
                        "last_tested": None
                    }

                    with st.spinner("Testing connection..."):
                        success, message, version = test_connection(new_conn)

                    if success:
                        new_conn["tested_ok"] = True
                        new_conn["last_tested"] = datetime.now().isoformat()
                        data["connections"][conn_name] = new_conn
                        if set_active:
                            data["active_connection"] = conn_name

                        if save_connections(data):
                            st.success(f"Connection '{conn_name}' added successfully!\n{version}")
                            st.rerun()
                    else:
                        st.error(f"Connection test failed: {message}")
                        st.warning("Connection was not saved. Please verify the details.")

    # Tab 3: Quick Test
    with tab3:
        st.markdown("### Quick Test")
        st.markdown("Test connection details without saving them.")

        col1, col2 = st.columns(2)

        with col1:
            test_host = st.text_input("Host", value="hcc-oracle-23c", key="test_host")
            test_service = st.text_input("Service Name", value="FREEPDB1", key="test_service")
            test_password = st.text_input("Password", value="Compress123", type="password", key="test_password")

        with col2:
            test_port = st.number_input("Port", value=1521, key="test_port")
            test_username = st.text_input("Username", value="COMPRESSION_MGR", key="test_username")

        if st.button("Test Connection", key="quick_test", use_container_width=True, type="primary"):
            test_conn = {
                "host": test_host,
                "port": test_port,
                "service": test_service,
                "username": test_username,
                "password": test_password
            }

            with st.spinner("Testing connection..."):
                success, message, version = test_connection(test_conn)

            if success:
                st.success(f"{message}\n{version}")
            else:
                st.error(message)


if __name__ == "__main__":
    show_connections_page()
