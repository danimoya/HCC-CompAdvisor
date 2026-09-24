"""
Target Database Manager - HCC Compression Advisor
Register and manage target Oracle databases for analysis
"""

import html
import math

import streamlit as st
import oracledb
from typing import Any, Dict, List, Optional, Tuple
from datetime import datetime
from hcc_advisor.utils.central_queries import CentralQueries
from hcc_advisor.utils.target_connector import TargetConnector, build_connect_kwargs, parse_target_login
from hcc_advisor.utils.logger import log_error, log_info
from hcc_advisor.config import config
from hcc_advisor.auth import AuthManager, ROLE_ADMIN

# Try to import cryptography for password encryption
try:
    from cryptography.fernet import Fernet
    HAS_CRYPTO = True
except ImportError:
    HAS_CRYPTO = False


class CredentialEncryptionError(RuntimeError):
    """Raised when a target credential cannot be encrypted/decrypted securely."""


def encrypt_password(password: str) -> str:
    """Encrypt password for storage.

    Fails closed: refuses to return plaintext when no usable encryption key /
    cryptography library is available, so a misconfigured deployment can never
    silently persist target-DB credentials in cleartext.
    """
    if not HAS_CRYPTO:
        raise CredentialEncryptionError(
            "cryptography library is not installed; cannot encrypt target credential. "
            "Install 'cryptography' to store target databases securely."
        )
    key = config.ENCRYPTION_KEY
    if not key:
        raise CredentialEncryptionError(
            "ENCRYPTION_KEY is not set; refusing to store target-DB password in plaintext. "
            "Generate a Fernet key (Setup page) and set ENCRYPTION_KEY before registering targets."
        )
    try:
        f = Fernet(key.encode() if isinstance(key, str) else key)
        return f.encrypt(password.encode()).decode()
    except Exception as exc:
        raise CredentialEncryptionError(f"Invalid ENCRYPTION_KEY: {exc}") from exc


def decrypt_password(encrypted: str) -> str:
    """Decrypt stored password.

    Surfaces decrypt failures explicitly (raises) instead of silently returning
    the raw stored value, which would mask key rotation/corruption and leak
    ciphertext into a live connection attempt.
    """
    if not HAS_CRYPTO:
        raise CredentialEncryptionError(
            "cryptography library is not installed; cannot decrypt stored credential."
        )
    key = config.ENCRYPTION_KEY
    if not key:
        raise CredentialEncryptionError(
            "ENCRYPTION_KEY is not set; cannot decrypt stored target-DB password."
        )
    try:
        f = Fernet(key.encode() if isinstance(key, str) else key)
        return f.decrypt(encrypted.encode()).decode()
    except Exception as exc:
        raise CredentialEncryptionError(
            "Failed to decrypt stored target-DB password (wrong/rotated ENCRYPTION_KEY "
            "or corrupted ciphertext)."
        ) from exc


def test_target_connection(conn_details: Dict) -> Tuple[bool, str, Optional[str]]:
    """Test a target database connection directly. Supports SYSDBA mode, also
    when typed as a "SYS AS SYSDBA" username (see parse_target_login)."""
    try:
        connect_kwargs = build_connect_kwargs(conn_details)
    except ValueError as e:
        return False, f"Connection failed: {e}", None
    try:
        connection = oracledb.connect(**connect_kwargs)
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


ENVIRONMENTS = ['PRODUCTION', 'DEV', 'TEST', 'UAT', 'STAGING']
PLATFORMS = ['STANDARD', 'EXADATA']
CONNECTION_MODES = ['NORMAL', 'SYSDBA']

# Session-state keys: the target whose edit form is open, and a message shown
# once at the top of the list after a rerun (e.g. "... updated").
_EDIT_TARGET_KEY = 'edit_target_id'
_FLASH_KEY = 'target_registry_flash'


def _text(value: Any, default: str = '') -> str:
    """A registry cell as text; `default` for NULL (None, or NaN from pandas)."""
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return default
    return str(value)


def _edit_key(db_id: Any, field: str) -> str:
    return f"edit_target_{field}_{db_id}"


def _edit_defaults(db) -> Dict[str, Any]:
    """Edit-form values for a target's current registration (a registry row)."""
    try:
        port = int(db.get('port'))
    except (TypeError, ValueError):
        port = 1521
    if not 1 <= port <= 65535:
        port = 1521
    mode = _text(db.get('connection_mode'), 'NORMAL').upper()
    return {
        'display_name': _text(db.get('display_name')),
        'host': _text(db.get('db_host')),
        'port': port,
        'service': _text(db.get('service_name')),
        'username': _text(db.get('username')),
        'mode': mode if mode in CONNECTION_MODES else 'NORMAL',
        'environment': _text(db.get('environment')) or ENVIRONMENTS[0],
        'platform_type': _text(db.get('platform_type')) or PLATFORMS[0],
        'description': _text(db.get('description')),
        'new_password': '',
    }


def _with_current(options: List[str], current: str) -> List[str]:
    """Selectbox options that also offer a stored value outside the standard
    list, so opening the edit form never silently changes it."""
    return options if current in options else options + [current]


def _close_edit_form(db_id: Any) -> None:
    """Close a target's edit form. Its field values need no explicit clearing:
    Streamlit drops the state of widgets that a run doesn't render, so the next
    Edit starts again from the registry."""
    if st.session_state.get(_EDIT_TARGET_KEY) == db_id:
        st.session_state.pop(_EDIT_TARGET_KEY, None)


def save_target_edit(
    database_id: int, stored_password_encrypted: Optional[str], values: Dict[str, Any]
) -> Tuple[bool, str]:
    """
    Validate, test and save an edit of a registered target database.

    The connection is tested with the edited details first, using the new
    password when one is given and otherwise the stored one (decrypted; fails
    closed if it can't be). The registry is only updated after a successful
    test, together with the Oracle version the test reported.

    Args:
        database_id: Target database ID
        stored_password_encrypted: The target's current PASSWORD_ENCRYPTED
        values: Edit-form values: display_name, host, port, service, username,
            mode, environment, platform_type, description and new_password
            (blank = keep the current password)

    Returns:
        Tuple of (success, message)
    """
    display_name = (values.get('display_name') or '').strip()
    host = (values.get('host') or '').strip()
    service = (values.get('service') or '').strip()
    username = (values.get('username') or '').strip()
    missing = [label for label, value in (
        ('Display Name', display_name), ('Host', host),
        ('Service Name', service), ('Username', username)) if not value]
    if missing:
        return False, f"Please fill in the required fields: {', '.join(missing)}"
    port = int(values.get('port') or 1521)

    # Accept "SYS AS SYSDBA" typed as the username (SYS always logs on AS SYSDBA)
    try:
        username, mode = parse_target_login(username, values.get('mode'))
    except ValueError as exc:
        return False, str(exc)

    new_password = values.get('new_password') or ''
    password_encrypted = None
    if new_password:
        # Encrypt before testing: no point testing a password that can't be stored
        try:
            password_encrypted = encrypt_password(new_password)
        except CredentialEncryptionError as exc:
            return False, f"Cannot save the new password: {exc}"
        password = new_password
    else:
        try:
            password = decrypt_password(stored_password_encrypted or '')
        except CredentialEncryptionError as exc:
            return False, (f"Cannot test the connection with the stored password: {exc} "
                           f"Enter a new password to replace it.")

    ok, msg, version = test_target_connection({
        'host': host, 'port': port, 'service': service,
        'username': username, 'password': password, 'mode': mode,
    })
    if not ok:
        return False, f"Connection test failed, nothing was saved. {msg}"

    db_data = {
        'display_name': display_name,
        'db_host': host,
        'port': port,
        'service_name': service,
        'username': username,
        'connection_mode': mode,
        'description': (values.get('description') or '').strip(),
        'environment': values.get('environment'),
        'platform_type': values.get('platform_type'),
        'oracle_version': version,
    }
    if password_encrypted:
        db_data['password_encrypted'] = password_encrypted
    ok, msg = CentralQueries.update_target_database(database_id, db_data)
    if not ok:
        return False, f"Connection test passed but saving failed: {msg}"
    CentralQueries.update_target_last_connected(database_id)
    log_info(f"Target database edited: {display_name} (ID: {database_id})")
    return True, f"'{display_name}' updated." + (f" {version}" if version else "")


def _render_edit_form(db, db_id: int) -> None:
    """Edit form for one registered target, shown inside its expander."""
    current = _edit_defaults(db)
    # Seed the fields from the registry when the form opens; while it stays open
    # the widgets keep what was typed (e.g. across a failed save).
    for field, value in current.items():
        key = _edit_key(db_id, field)
        if key not in st.session_state:
            st.session_state[key] = value

    st.markdown("#### Edit Connection")
    with st.form(f"edit_target_form_{db_id}"):
        col1, col2 = st.columns(2)

        with col1:
            st.text_input("Database Name", value=_text(db.get('database_name')), disabled=True,
                          key=_edit_key(db_id, 'database_name'),
                          help="The registry's unique key; it can't be changed.")
            display_name = st.text_input("Display Name *", key=_edit_key(db_id, 'display_name'))
            host = st.text_input("Host *", key=_edit_key(db_id, 'host'))
            service = st.text_input("Service Name *", key=_edit_key(db_id, 'service'))
            new_password = st.text_input("New Password", type="password",
                                         key=_edit_key(db_id, 'new_password'),
                                         help="Leave blank to keep the current password")

        with col2:
            environment = st.selectbox("Environment", _with_current(ENVIRONMENTS, current['environment']),
                                       key=_edit_key(db_id, 'environment'))
            platform_type = st.selectbox("Platform", _with_current(PLATFORMS, current['platform_type']),
                                         key=_edit_key(db_id, 'platform_type'))
            port = st.number_input("Port *", min_value=1, max_value=65535, key=_edit_key(db_id, 'port'))
            username = st.text_input("Username *", key=_edit_key(db_id, 'username'),
                                     help="For SYS use Connection Mode SYSDBA ('SYS AS SYSDBA' is also accepted)")
            mode = st.selectbox("Connection Mode", CONNECTION_MODES, key=_edit_key(db_id, 'mode'),
                                help="Use SYSDBA for SYS user connections")
            description = st.text_input("Description", key=_edit_key(db_id, 'description'))

        st.caption("The connection is tested with these details before anything is saved.")
        save_col, cancel_col = st.columns(2)
        with save_col:
            save = st.form_submit_button("Test & Save", type="primary", use_container_width=True)
        with cancel_col:
            cancel = st.form_submit_button("Cancel", use_container_width=True)

    if cancel:
        _close_edit_form(db_id)
        st.rerun()

    if save:
        values = {
            'display_name': display_name, 'host': host, 'port': port, 'service': service,
            'username': username, 'mode': mode, 'environment': environment,
            'platform_type': platform_type, 'description': description,
            'new_password': new_password,
        }
        with st.spinner("Testing connection..."):
            ok, msg = save_target_edit(int(db_id), _text(db.get('password_encrypted')), values)
        if ok:
            # The database ID doesn't change, so an edited active target stays active.
            _close_edit_form(db_id)
            st.session_state[_FLASH_KEY] = msg
            st.rerun()
        else:
            st.error(msg)


def show_connections_page():
    """Display the target database manager page"""

    st.markdown("## Target Database Manager")
    st.markdown("Register and manage Oracle databases for compression analysis")

    # Credential management (register/delete targets, view/decrypt-and-test stored
    # DB passwords) is admin-only.
    if not AuthManager.require_role(
        ROLE_ADMIN, "Managing target-database credentials requires the admin role."
    ):
        return

    # Load target databases from central DB
    targets_df = CentralQueries.get_target_databases()

    # Active database banner
    active_db_id = st.session_state.get('active_database_id')
    if active_db_id and not targets_df.empty:
        targets_df.columns = [c.lower() for c in targets_df.columns]
        active_row = targets_df[targets_df['database_id'] == active_db_id]
        if not active_row.empty:
            active = active_row.iloc[0]
            # Escape registered-DB metadata before injecting into raw HTML to
            # prevent stored XSS via malicious display name / host / service.
            _disp = html.escape(str(active.get('display_name', 'N/A')))
            _user = html.escape(str(active.get('username', '')))
            _host = html.escape(str(active.get('db_host', '')))
            _port = html.escape(str(active.get('port', '')))
            _svc = html.escape(str(active.get('service_name', '')))
            st.markdown(f"""
            <div style="background: linear-gradient(90deg, #1a1a2e 0%, #16213e 100%);
                        padding: 15px 20px; border-radius: 10px; margin-bottom: 20px;
                        border-left: 4px solid green;">
                <span style="color: #888; font-size: 12px;">ACTIVE TARGET DATABASE</span>
                <h3 style="margin: 5px 0; color: white;">{_disp}</h3>
                <code style="color: #4fc3f7;">{_user}@{_host}:{_port}/{_svc}</code>
            </div>
            """, unsafe_allow_html=True)

    st.markdown("---")

    # Tabs
    tab1, tab2, tab3 = st.tabs(["Registered Databases", "Add New Database", "Quick Test"])

    # Tab 1: Registered databases
    with tab1:
        st.markdown("### Registered Target Databases")

        flash = st.session_state.pop(_FLASH_KEY, None)
        if flash:
            st.success(flash)

        if targets_df.empty:
            st.info("No target databases registered. Add one in the 'Add New Database' tab.")
        else:
            if 'database_id' not in targets_df.columns:
                targets_df.columns = [c.lower() for c in targets_df.columns]

            for _, db in targets_df.iterrows():
                db_id = db.get('database_id')
                db_name = db.get('display_name', db.get('database_name', 'Unknown'))
                is_active = db_id == active_db_id
                is_editing = st.session_state.get(_EDIT_TARGET_KEY) == db_id
                env = db.get('environment', 'N/A')

                icon = "●" if is_active else "○"
                badge = " (Active)" if is_active else ""

                with st.expander(f"{icon} {db_name}{badge} - {env}", expanded=is_active or is_editing):
                    col1, col2 = st.columns([3, 1])

                    with col1:
                        st.markdown(f"""
                        | Property | Value |
                        |----------|-------|
                        | **Host** | `{db.get('db_host', 'N/A')}` |
                        | **Port** | `{db.get('port', 'N/A')}` |
                        | **Service** | `{db.get('service_name', 'N/A')}` |
                        | **Username** | `{db.get('username', 'N/A')}` |
                        | **Connection Mode** | {db.get('connection_mode') or 'NORMAL'} |
                        | **Environment** | {env} |
                        | **Platform** | {db.get('platform_type', 'STANDARD')} |
                        | **Oracle Version** | {db.get('oracle_version', 'Unknown')} |
                        | **Description** | {db.get('description', 'N/A')} |
                        | **Last Connected** | {str(db.get('last_connected', 'Never'))[:19] if db.get('last_connected') else 'Never'} |
                        """)

                    with col2:
                        st.markdown("**Actions**")

                        if st.button("Test", key=f"test_{db_id}", use_container_width=True):
                            try:
                                pwd = decrypt_password(db.get('password_encrypted', ''))
                            except CredentialEncryptionError as exc:
                                st.error(str(exc))
                                st.stop()
                            conn = {
                                'host': db.get('db_host'),
                                'port': int(db.get('port', 1521)),
                                'service': db.get('service_name'),
                                'username': db.get('username'),
                                'password': pwd,
                                'mode': db.get('connection_mode') or 'NORMAL',
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

                        if st.button("Edit", key=f"edit_{db_id}", use_container_width=True,
                                     disabled=is_editing):
                            st.session_state[_EDIT_TARGET_KEY] = db_id
                            st.rerun()

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
                                _close_edit_form(db_id)
                                st.success(msg)
                                st.rerun()
                            else:
                                st.error(msg)

                    if is_editing:
                        _render_edit_form(db, db_id)

    # Tab 2: Add new database
    with tab2:
        st.markdown("### Add New Target Database")

        # Quick test connection (outside the form)
        with st.expander("Test Connection First", expanded=False):
            tc1, tc2 = st.columns(2)
            with tc1:
                _t_host = st.text_input("Host", key="pretest_host", placeholder="hostname or IP")
                _t_service = st.text_input("Service", key="pretest_service", placeholder="e.g., FREEPDB1")
                _t_user = st.text_input("Username", key="pretest_user")
            with tc2:
                _t_port = st.number_input("Port", value=1521, min_value=1, max_value=65535, key="pretest_port")
                _t_pass = st.text_input("Password", type="password", key="pretest_pass")
                _t_mode = st.selectbox("Connection Mode", ["NORMAL", "SYSDBA"], key="pretest_mode",
                                       help="Use SYSDBA for SYS user connections")
                if st.button("Test Connection", use_container_width=True, type="primary", key="pretest_btn"):
                    if all([_t_host, _t_service, _t_user, _t_pass]):
                        conn_cfg = {'host': _t_host, 'port': _t_port, 'service': _t_service,
                                    'username': _t_user, 'password': _t_pass, 'mode': _t_mode}
                        with st.spinner("Testing..."):
                            ok, msg, ver = test_target_connection(conn_cfg)
                        if ok:
                            st.success(f"{msg} — {ver}")
                        else:
                            st.error(f"Failed: {msg}")
                    else:
                        st.warning("Fill in all fields")

        with st.form("new_target_form"):
            col1, col2 = st.columns(2)

            with col1:
                db_name = st.text_input("Database Name *", placeholder="e.g., prod-oracle-01")
                display_name = st.text_input("Display Name *", placeholder="e.g., Production DB")
                host = st.text_input("Host *", placeholder="hostname or IP")
                service = st.text_input("Service Name *", placeholder="e.g., FREEPDB1")
                password = st.text_input("Password *", type="password")

            with col2:
                environment = st.selectbox("Environment", options=ENVIRONMENTS)
                platform_type = st.selectbox("Platform", options=PLATFORMS)
                port = st.number_input("Port *", min_value=1, max_value=65535, value=1521)
                username = st.text_input("Username *", placeholder="e.g., COMPRESSION_MGR",
                                         help="For SYS use Connection Mode SYSDBA ('SYS AS SYSDBA' is also accepted)")
                conn_mode = st.selectbox("Connection Mode", ["NORMAL", "SYSDBA"],
                                          help="Use SYSDBA for SYS user connections")
                description = st.text_input("Description", placeholder="Optional description")

            set_active = st.checkbox("Set as active database", value=True)
            submitted = st.form_submit_button("Add Database", use_container_width=True)

            if submitted:
                if not all([db_name, display_name, host, service, username, password]):
                    st.error("Please fill in all required fields")
                else:
                    # Accept "SYS AS SYSDBA" typed as the username and save the clean
                    # username + mode (SYS always logs on AS SYSDBA).
                    try:
                        username, conn_mode = parse_target_login(username, conn_mode)
                    except ValueError as exc:
                        st.error(str(exc))
                        st.stop()
                    # Test first
                    test_conn = {'host': host, 'port': port, 'service': service,
                                 'username': username, 'password': password, 'mode': conn_mode}
                    with st.spinner("Testing connection..."):
                        success, msg, version = test_target_connection(test_conn)

                    if success:
                        try:
                            password_encrypted = encrypt_password(password)
                        except CredentialEncryptionError as exc:
                            st.error(f"Cannot save database: {exc}")
                            st.stop()
                        db_data = {
                            'database_name': db_name,
                            'display_name': display_name,
                            'db_host': host,
                            'port': port,
                            'service_name': service,
                            'username': username,
                            'password_encrypted': password_encrypted,
                            'description': description,
                            'environment': environment,
                            'platform_type': platform_type,
                            'connection_mode': conn_mode,
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
            test_mode = st.selectbox("Connection Mode", ["NORMAL", "SYSDBA"], key="quick_test_mode",
                                      help="Use SYSDBA for SYS user connections")

        if st.button("Test Connection", key="quick_test", use_container_width=True, type="primary"):
            test_conn = {'host': test_host, 'port': test_port, 'service': test_service,
                         'username': test_username, 'password': test_password, 'mode': test_mode}
            with st.spinner("Testing..."):
                success, msg, version = test_target_connection(test_conn)
            if success:
                st.success(f"{msg}\n{version}")
            else:
                st.error(msg)
