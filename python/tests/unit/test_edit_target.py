"""
Unit tests for editing a registered target database (Target Database Manager).

- save_target_edit: validates the edit, tests the connection with the new
  details (the stored password, decrypted, when no new one is entered) and only
  then saves through CentralQueries.update_target_database.
- The page (streamlit AppTest): the Edit action opens a prefilled form in the
  target's expander; Test & Save / Cancel / failure handling.

The connection test, CentralQueries and the registry listing are mocked; the
password encryption is real (a throwaway Fernet key), so ciphertexts round-trip.
"""
from unittest.mock import MagicMock

import pandas as pd
import pytest
import streamlit as st
from cryptography.fernet import Fernet
from streamlit.testing.v1 import AppTest

from hcc_advisor.auth import ROLE_ADMIN, ROLE_OPERATOR
from hcc_advisor.utils.central_queries import CentralQueries
from hcc_advisor.views import page_06_connections
from hcc_advisor.views.page_06_connections import save_target_edit

TIMEOUT = 15  # seconds per AppTest run
VERSION = 'Oracle Database 23ai Free Release 23.0.0.0.0'
KEY = Fernet.generate_key().decode()


def _encrypt(plain: str, key: str = KEY) -> str:
    return Fernet(key.encode()).encrypt(plain.encode()).decode()


def _decrypt(token: str) -> str:
    return Fernet(KEY.encode()).decrypt(token.encode()).decode()


def _values(**overrides):
    values = {
        'display_name': 'Prod', 'host': 'newhost', 'port': 1522, 'service': 'PDB2',
        'username': 'HCC', 'mode': 'NORMAL', 'environment': 'PRODUCTION',
        'platform_type': 'EXADATA', 'description': 'edited', 'new_password': '',
    }
    values.update(overrides)
    return values


@pytest.fixture
def mocks(monkeypatch):
    """Real encryption key; connection test and registry writes mocked."""
    monkeypatch.setattr(page_06_connections.config, 'ENCRYPTION_KEY', KEY)
    m = MagicMock()
    m.test = MagicMock(return_value=(True, 'Connected successfully!', VERSION))
    m.update = MagicMock(return_value=(True, 'Target database updated successfully'))
    m.last_connected = MagicMock(return_value=True)
    monkeypatch.setattr(page_06_connections, 'test_target_connection', m.test)
    monkeypatch.setattr(CentralQueries, 'update_target_database', m.update)
    monkeypatch.setattr(CentralQueries, 'update_target_last_connected', m.last_connected)
    return m


# ============================================================================
# save_target_edit
# ============================================================================

@pytest.mark.unit
class TestSaveTargetEdit:

    def test_saves_only_after_successful_test(self, mocks):
        order = []
        mocks.test.side_effect = lambda conn: order.append('test') or (True, 'ok', VERSION)
        mocks.update.side_effect = lambda db_id, data: order.append('update') or (True, 'ok')

        ok, msg = save_target_edit(7, _encrypt('old-pw'), _values())

        assert ok and "'Prod' updated" in msg and VERSION in msg
        assert order == ['test', 'update']
        mocks.test.assert_called_once_with({
            'host': 'newhost', 'port': 1522, 'service': 'PDB2',
            'username': 'HCC', 'password': 'old-pw', 'mode': 'NORMAL',
        })
        db_id, data = mocks.update.call_args.args
        assert db_id == 7
        assert data == {
            'display_name': 'Prod', 'db_host': 'newhost', 'port': 1522,
            'service_name': 'PDB2', 'username': 'HCC', 'connection_mode': 'NORMAL',
            'description': 'edited', 'environment': 'PRODUCTION',
            'platform_type': 'EXADATA', 'oracle_version': VERSION,
        }
        mocks.last_connected.assert_called_once_with(7)

    def test_blank_password_keeps_the_stored_one(self, mocks):
        ok, _msg = save_target_edit(7, _encrypt('old-pw'), _values(new_password=''))
        assert ok
        assert mocks.test.call_args.args[0]['password'] == 'old-pw'
        assert 'password_encrypted' not in mocks.update.call_args.args[1]

    def test_new_password_is_tested_and_stored_encrypted(self, mocks):
        ok, _msg = save_target_edit(7, _encrypt('old-pw'), _values(new_password='new-pw'))
        assert ok
        assert mocks.test.call_args.args[0]['password'] == 'new-pw'
        stored = mocks.update.call_args.args[1]['password_encrypted']
        assert stored != 'new-pw' and _decrypt(stored) == 'new-pw'

    def test_new_password_without_stored_one(self, mocks):
        # A new password doesn't need the old one to decrypt
        ok, _msg = save_target_edit(7, None, _values(new_password='new-pw'))
        assert ok and mocks.update.called

    def test_failed_test_does_not_save(self, mocks):
        mocks.test.return_value = (False, 'Connection failed: ORA-12541: no listener', None)
        ok, msg = save_target_edit(7, _encrypt('old-pw'), _values(new_password='new-pw'))
        assert not ok
        assert 'ORA-12541' in msg and 'nothing was saved' in msg
        mocks.update.assert_not_called()
        mocks.last_connected.assert_not_called()

    @pytest.mark.parametrize('stored', [
        _encrypt('old-pw', key=Fernet.generate_key().decode()),  # rotated key
        'not-a-fernet-token',                                     # corrupted
        None,                                                     # missing
    ])
    def test_decrypt_failure_is_reported(self, mocks, stored):
        ok, msg = save_target_edit(7, stored, _values(new_password=''))
        assert not ok
        assert 'stored password' in msg and 'Failed to decrypt' in msg
        assert 'Enter a new password' in msg
        mocks.test.assert_not_called()
        mocks.update.assert_not_called()

    def test_missing_encryption_key_is_reported(self, mocks, monkeypatch):
        monkeypatch.setattr(page_06_connections.config, 'ENCRYPTION_KEY', '')
        ok, msg = save_target_edit(7, _encrypt('old-pw'), _values(new_password=''))
        assert not ok and 'ENCRYPTION_KEY is not set' in msg
        ok, msg = save_target_edit(7, _encrypt('old-pw'), _values(new_password='new-pw'))
        assert not ok and 'Cannot save the new password' in msg
        mocks.test.assert_not_called()
        mocks.update.assert_not_called()

    @pytest.mark.parametrize('field, label', [
        ('display_name', 'Display Name'), ('host', 'Host'),
        ('service', 'Service Name'), ('username', 'Username'),
    ])
    def test_required_fields(self, mocks, field, label):
        ok, msg = save_target_edit(7, _encrypt('old-pw'), _values(**{field: '   '}))
        assert not ok and label in msg
        mocks.test.assert_not_called()
        mocks.update.assert_not_called()

    def test_sys_as_sysdba_username(self, mocks):
        ok, _msg = save_target_edit(7, _encrypt('old-pw'),
                                    _values(username='sys as sysdba', mode='NORMAL'))
        assert ok
        conn = mocks.test.call_args.args[0]
        assert (conn['username'], conn['mode']) == ('sys', 'SYSDBA')
        data = mocks.update.call_args.args[1]
        assert (data['username'], data['connection_mode']) == ('sys', 'SYSDBA')

    def test_unsupported_mode_rejected(self, mocks):
        ok, msg = save_target_edit(7, _encrypt('old-pw'), _values(username='sys as sysoper'))
        assert not ok and 'SYSOPER' in msg
        mocks.test.assert_not_called()

    def test_update_failure_is_reported(self, mocks):
        mocks.update.return_value = (False, 'Failed to update target database: ORA-12899')
        ok, msg = save_target_edit(7, _encrypt('old-pw'), _values())
        assert not ok and 'ORA-12899' in msg
        mocks.last_connected.assert_not_called()


# ============================================================================
# Page (AppTest)
# ============================================================================

def _registry():
    """Two registered targets, as the central registry returns them."""
    return pd.DataFrame([
        {'DATABASE_ID': 5, 'DATABASE_NAME': 'prod-01', 'DISPLAY_NAME': 'Prod',
         'DB_HOST': 'prodhost', 'PORT': 1521, 'SERVICE_NAME': 'PROD',
         'USERNAME': 'HCC', 'PASSWORD_ENCRYPTED': _encrypt('prod-pw'),
         'CONNECTION_MODE': 'NORMAL', 'ENVIRONMENT': 'PRODUCTION',
         'PLATFORM_TYPE': 'STANDARD', 'ORACLE_VERSION': '19c', 'DESCRIPTION': None,
         'LAST_CONNECTED': None},
        {'DATABASE_ID': 7, 'DATABASE_NAME': 'dev-01', 'DISPLAY_NAME': '<b>Dev</b>',
         'DB_HOST': 'devhost', 'PORT': 1521, 'SERVICE_NAME': 'FREEPDB1',
         'USERNAME': 'SYS', 'PASSWORD_ENCRYPTED': _encrypt('dev-pw'),
         'CONNECTION_MODE': 'SYSDBA', 'ENVIRONMENT': 'QA',
         'PLATFORM_TYPE': 'STANDARD', 'ORACLE_VERSION': '23ai', 'DESCRIPTION': 'dev box',
         'LAST_CONNECTED': None},
    ])


def _page():
    from hcc_advisor.views.page_06_connections import show_connections_page
    show_connections_page()


@pytest.fixture
def page(mocks, monkeypatch):
    """AppTest of the page for an admin whose active target is ID 5."""
    monkeypatch.setattr(CentralQueries, 'get_target_databases', lambda: _registry())
    # AppTest (1.31) keeps a clicked button's trigger across st.rerun(), so a
    # handler that reruns after acting would loop until timeout.
    monkeypatch.setattr(st, 'rerun', MagicMock())
    at = AppTest.from_function(_page, default_timeout=TIMEOUT)
    at.session_state['authenticated'] = True
    at.session_state['role'] = ROLE_ADMIN
    at.session_state['active_database_id'] = 5
    return at.run()


def _button(at, label):
    return next(b for b in at.button if b.label == label)


def _open_editor(at, db_id):
    at.button(key=f'edit_{db_id}').click().run()
    return at.run()  # the rerun the Edit button asks for (mocked above)


def _field(at, db_id, field, kind='text_input'):
    return getattr(at, kind)(key=f'edit_target_{field}_{db_id}')


@pytest.mark.unit
class TestEditTargetPage:

    def test_edit_opens_prefilled_form(self, page):
        assert not page.exception
        assert not any(b.label == 'Test & Save' for b in page.button)

        at = _open_editor(page, 7)
        assert not at.exception
        assert at.session_state['edit_target_id'] == 7
        assert at.button(key='edit_7').proto.disabled
        assert _field(at, 7, 'database_name').value == 'dev-01'
        assert _field(at, 7, 'database_name').proto.disabled
        assert _field(at, 7, 'display_name').value == '<b>Dev</b>'
        assert _field(at, 7, 'host').value == 'devhost'
        assert _field(at, 7, 'port', 'number_input').value == 1521
        assert _field(at, 7, 'service').value == 'FREEPDB1'
        assert _field(at, 7, 'username').value == 'SYS'
        assert _field(at, 7, 'mode', 'selectbox').value == 'SYSDBA'
        # A stored value outside the standard list is kept, not replaced
        assert _field(at, 7, 'environment', 'selectbox').value == 'QA'
        assert _field(at, 7, 'description').value == 'dev box'
        assert _field(at, 7, 'new_password').value == ''
        # Only the chosen target's form is open
        assert [b.label for b in at.button].count('Test & Save') == 1
        with pytest.raises(KeyError):
            _field(at, 5, 'host')

    def test_save_tests_then_updates_and_closes_form(self, page, mocks):
        at = _open_editor(page, 7)
        _field(at, 7, 'host').input('devhost2')
        _field(at, 7, 'port', 'number_input').set_value(1522)
        _field(at, 7, 'display_name').input('Dev 2')
        st.rerun.reset_mock()
        _button(at, 'Test & Save').click().run()

        assert not at.exception
        assert not at.error
        conn = mocks.test.call_args.args[0]
        assert conn == {'host': 'devhost2', 'port': 1522, 'service': 'FREEPDB1',
                        'username': 'SYS', 'password': 'dev-pw', 'mode': 'SYSDBA'}
        mocks.update.assert_called_once()
        db_id, data = mocks.update.call_args.args
        assert db_id == 7
        assert data['db_host'] == 'devhost2' and data['display_name'] == 'Dev 2'
        assert data['environment'] == 'QA' and data['oracle_version'] == VERSION
        assert 'password_encrypted' not in data  # blank = keep current
        assert 'edit_target_id' not in at.session_state
        assert at.session_state['active_database_id'] == 5
        st.rerun.assert_called_once_with()

        at.run()  # the rerun after saving (mocked above)
        assert any("'Dev 2' updated" in s.value for s in at.success)
        assert not any(b.label == 'Test & Save' for b in at.button)

    def test_active_target_stays_active_after_edit(self, page, mocks):
        at = _open_editor(page, 5)
        _field(at, 5, 'new_password').input('new-pw')
        _button(at, 'Test & Save').click().run()

        assert not at.error
        assert mocks.test.call_args.args[0]['password'] == 'new-pw'
        data = mocks.update.call_args.args[1]
        assert _decrypt(data['password_encrypted']) == 'new-pw'
        assert at.session_state['active_database_id'] == 5

    def test_failed_test_keeps_form_values_and_saves_nothing(self, page, mocks):
        mocks.test.return_value = (False, 'Connection failed: ORA-12541: no listener', None)
        at = _open_editor(page, 7)
        _field(at, 7, 'host').input('badhost')
        _button(at, 'Test & Save').click().run()

        mocks.update.assert_not_called()
        assert any('ORA-12541' in e.value for e in at.error)
        assert at.session_state['edit_target_id'] == 7
        assert _field(at, 7, 'host').value == 'badhost'

        at.run()  # still open with what was typed
        assert _field(at, 7, 'host').value == 'badhost'

    def test_decrypt_failure_is_shown(self, page, mocks, monkeypatch):
        at = _open_editor(page, 7)
        monkeypatch.setattr(page_06_connections.config, 'ENCRYPTION_KEY',
                            Fernet.generate_key().decode())  # rotated key
        _button(at, 'Test & Save').click().run()

        mocks.test.assert_not_called()
        mocks.update.assert_not_called()
        assert any('Failed to decrypt stored target-DB password' in e.value for e in at.error)
        assert at.session_state['edit_target_id'] == 7

    def test_cancel_closes_without_saving(self, page, mocks):
        at = _open_editor(page, 7)
        _field(at, 7, 'host').input('other')
        _button(at, 'Cancel').click().run()

        mocks.test.assert_not_called()
        mocks.update.assert_not_called()
        assert 'edit_target_id' not in at.session_state

        at.run()
        assert not any(b.label == 'Test & Save' for b in at.button)
        at = _open_editor(at, 7)  # reopened from the registry, not the typed value
        assert _field(at, 7, 'host').value == 'devhost'

    def test_non_admin_cannot_edit(self, mocks, monkeypatch):
        monkeypatch.setattr(CentralQueries, 'get_target_databases', lambda: _registry())
        at = AppTest.from_function(_page, default_timeout=TIMEOUT)
        at.session_state['authenticated'] = True
        at.session_state['role'] = ROLE_OPERATOR
        at.session_state['edit_target_id'] = 7  # e.g. left over / crafted
        at.run()

        assert 'admin role' in ' '.join(e.value for e in at.error)
        assert not any(b.label in ('Edit', 'Test & Save') for b in at.button)
        mocks.update.assert_not_called()
