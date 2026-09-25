"""
Page actions under ``streamlit.testing.v1.AppTest``: the buttons and forms
behind the pages rendered in test_page_smoke.py (scheduler refresh /
reconcile / CSV import, admin settings and patching, target registration,
Quick Action scan and bulk submit) plus the setup page's direct-connection
helpers.

Same harness as the smoke tests (tests/unit/page_harness.py): connectors
routed to empty fakes with bind checking, st.rerun and the auto-refresh clock
mocked. Outbound HTTP (Ollama, webhooks) goes to an in-memory opener. The
scheduler queue, execution and rollback internals are mocked at the
TargetQueries boundary; they have their own test modules.
"""
import io
import json
import urllib.request
from types import SimpleNamespace
from unittest.mock import MagicMock

import oracledb
import pandas as pd
import pytest
import streamlit as st
from cryptography.fernet import Fernet

from hcc_advisor.auth import ROLE_ADMIN, ROLE_OPERATOR, ROLE_VIEWER
from hcc_advisor.utils import ui_refresh, url_guard
from hcc_advisor.utils.central_queries import CentralQueries
from hcc_advisor.utils.sql_patches import find_patches_dir, list_patch_dirs
from hcc_advisor.utils.target_queries import TargetQueries
from hcc_advisor.views import page_00_setup, page_06_connections, page_09_admin

from tests.unit.db_fakes import SqlRouter, df
from tests.unit.page_harness import (
    DB, RECS, TARGETS, button, env_fixture, ok, page, patch_scan, texts,
)

_FIXTURES = (env_fixture,)  # registered as the `env` fixture


# ============================================================================
# Scheduler
# ============================================================================

def _reconcile_result(database_id, **overrides):
    result = {'database_id': database_id, 'running': 1, 'pending': 2, 'advisor_runs_failed': 0,
              'errors': [], 'updated': [{'history_id': 5, 'object': 'APP.ORDERS',
                                         'job_name': 'HCC_ORDERS_1', 'status': 'SUCCESS',
                                         'reason': 'job SUCCEEDED'}]}
    result.update(overrides)
    return result


_DRAIN = {'submitted': 1, 'blocked': 0, 'failed': 1, 'not_claimed': 0, 'waiting': 2,
          'skipped_databases': [3], 'errors': ['db 3 unreachable']}


@pytest.mark.unit
class TestSchedulerActions:

    def test_reconcile_shows_what_changed(self, env):
        reconcile = env.patch(TargetQueries, 'reconcile_operations',
                              MagicMock(side_effect=lambda did: _reconcile_result(did)))
        at = ok(page('page_12_scheduler', 'show_scheduler_page', ROLE_OPERATOR).run())
        at = ok(at.button(key='sched_reconcile_btn').click().run())
        reconcile.assert_called_once_with(DB)
        body = texts(at)
        assert 'Rows closed 1' in body and 'Still running 1' in body
        assert 'Pending / waiting 2' in body

    def test_reconcile_all_databases_reports_failures(self, env):
        env.patch(TargetQueries, 'reconcile_operations',
                  MagicMock(side_effect=RuntimeError('ORA-12541')))
        at = ok(page('page_12_scheduler', 'show_scheduler_page', ROLE_OPERATOR, db_id=None).run())
        at = ok(at.button(key='sched_reconcile_btn').click().run())
        assert 'db_id=1: ORA-12541' in texts(at)

    def test_viewer_cannot_reconcile(self, env):
        at = ok(page('page_12_scheduler', 'show_scheduler_page', ROLE_VIEWER).run())
        assert at.button(key='sched_reconcile_btn').disabled

    @pytest.mark.parametrize('role, drains', [(ROLE_OPERATOR, True), (ROLE_VIEWER, False)])
    def test_refresh_now(self, env, role, drains):
        reconcile = env.patch(TargetQueries, 'reconcile_operations', MagicMock(
            return_value=_reconcile_result(DB, errors=['job view not readable'])))
        drain = env.patch(TargetQueries, 'drain_compression_queue', MagicMock(return_value=_DRAIN))
        at = ok(page('page_12_scheduler', 'show_scheduler_page', role).run())
        at = ok(at.button(key='sched_refresh').click().run())
        reconcile.assert_called_once_with(DB)
        assert drain.called is drains
        assert 'scheduler_last_refresh' in at.session_state

    def test_cross_database_refresh_polls_every_target(self, env):
        env.targets = pd.concat([TARGETS, TARGETS.assign(DATABASE_ID=2, DISPLAY_NAME='QA')])
        reconcile = env.patch(TargetQueries, 'reconcile_operations', MagicMock(side_effect=[
            _reconcile_result(1, errors=['partial']), RuntimeError('down')]))
        env.patch(TargetQueries, 'drain_compression_queue', MagicMock(return_value=_DRAIN))
        at = ok(page('page_12_scheduler', 'show_scheduler_page', db_id=None).run())
        ok(at.button(key='sched_refresh').click().run())
        assert [c.args for c in reconcile.call_args_list] == [(1,), (2,)]

    def test_auto_refresh_on_waits_and_reruns(self, env):
        env.patch(TargetQueries, 'reconcile_operations',
                  MagicMock(return_value=_reconcile_result(DB, updated=[])))
        env.patch(TargetQueries, 'drain_compression_queue', MagicMock(return_value={
            **_DRAIN, 'failed': 0, 'skipped_databases': [], 'errors': []}))
        at = ok(page('page_12_scheduler', 'show_scheduler_page',
                     scheduler_auto_refresh=True).run())
        assert 'Last refresh:' in texts(at)
        assert button(at, 'Stop Auto-refresh')
        ui_refresh.time.sleep.assert_called()
        env.rerun.assert_called()

    def test_start_and_stop_auto_refresh(self, env):
        env.patch(TargetQueries, 'reconcile_operations',
                  MagicMock(return_value=_reconcile_result(DB, updated=[])))
        at = ok(page('page_12_scheduler', 'show_scheduler_page', ROLE_VIEWER).run())
        at = ok(at.button(key='sched_start').click().run())
        assert at.session_state['scheduler_auto_refresh'] is True
        at = ok(at.run())                  # st.rerun is mocked: render the new state
        at = ok(at.button(key='sched_stop').click().run())
        assert at.session_state['scheduler_auto_refresh'] is False

    def _upload(self, env, csv_text):
        env.patch(st, 'file_uploader', lambda *a, **k: io.BytesIO(csv_text.encode()))
        env.target.on('from all_tables', result=df([
            {'OWNER': 'APP', 'TABLE_NAME': 'ORDERS', 'COMPRESSION': 'DISABLED',
             'COMPRESS_FOR': None},
            {'OWNER': 'APP', 'TABLE_NAME': 'DONE', 'COMPRESSION': 'ENABLED',
             'COMPRESS_FOR': 'ADVANCED'}]))

    def test_import_verifies_then_queues(self, env):
        self._upload(env, "owner,object_name,compression_type,dop\n"
                          "app,orders,QUERY HIGH,4\napp,done,OLTP,x\napp,missing,OLTP,2\n"
                          ",nameless,OLTP,1\n")
        enqueue = env.patch(TargetQueries, 'enqueue_compression_jobs', MagicMock(return_value={
            'added': 1, 'duplicates': 0, 'rejected': 0, 'errors': []}))
        at = ok(page('page_12_scheduler', 'show_scheduler_page', ROLE_OPERATOR).run())
        assert 'Parsed **3** object(s) from the manifest.' in texts(at)
        at = ok(at.button(key='import_verify_btn').click().run())
        body = texts(at)
        assert 'Ready to queue 1' in body and 'Already compressed 1' in body
        assert 'Missing 1' in body
        at = ok(at.button(key='import_add_queue_btn').click().run())
        (items,), _ = enqueue.call_args
        assert [(i['owner'], i['table_name'], i['dop']) for i in items] == [('APP', 'ORDERS', 4)]
        assert 'Queued 1 verified object(s) for Prod' in texts(at)

    def test_viewer_may_verify_but_not_queue(self, env):
        self._upload(env, "owner,object_name,compression_type\nAPP,ORDERS,QUERY HIGH\n")
        at = ok(page('page_12_scheduler', 'show_scheduler_page', ROLE_VIEWER).run())
        at = ok(at.button(key='import_verify_btn').click().run())
        assert at.button(key='import_add_queue_btn').disabled
        assert 'View only: queueing objects requires the operator role.' in texts(at)

    def test_import_of_an_unusable_csv(self, env):
        self._upload(env, "foo,bar\n1,2\n")
        at = ok(page('page_12_scheduler', 'show_scheduler_page').run())
        assert "No usable rows found." in texts(at)


# ============================================================================
# Administration
# ============================================================================

class _FakeOpener:
    """urllib opener stand-in: records what was opened, answers with `payload`."""

    def __init__(self, payload=b'{"models": [{"name": "llama3:latest"}]}', status=200):
        self.payload = payload
        self.status = status
        self.opened = []

    def __call__(self, *handlers):          # urllib.request.build_opener(...)
        return self

    def open(self, req, timeout=None):
        self.opened.append(req)
        return SimpleNamespace(read=lambda: self.payload, status=self.status)


@pytest.mark.unit
class TestAdminActions:

    @pytest.fixture(autouse=True)
    def _admin_env(self, env):
        env.patch(page_09_admin, 'find_patches_dir', lambda: None)
        env.returns(CentralQueries, 'get_history_purge_preview', {
            'counts': {t: 0 for t in CentralQueries.PURGE_HISTORY_TABLES},
            'targets_to_reset': 0, 'active': {'queued': 0, 'in_progress': 0, 'running_runs': 0}})
        env.patch(url_guard, 'validate_outbound_url', lambda url, kind: url)
        self.http = env.patch(urllib.request, 'build_opener', _FakeOpener())

    def _admin(self):
        return ok(page('page_09_admin', 'show_admin_page').run())

    def test_ollama_save_test_and_clear(self, env):
        at = self._admin()
        at.text_input(key='admin_ollama_url').input('http://ollama.example:11434')
        at = ok(at.button(key='ollama_save').click().run())
        merges = env.central.find('merge into t_schema_metadata')
        assert [m.params for m in merges] == [
            {'k': 'ollama_url', 'v': 'http://ollama.example:11434'},
            {'k': 'ollama_model', 'v': 'llama3'}]
        at = ok(at.button(key='ollama_test').click().run())
        assert at.session_state['admin_ollama_models_list'] == ['llama3:latest']
        assert self.http.opened == ['http://ollama.example:11434/api/tags']
        at = ok(at.button(key='ollama_clear').click().run())
        assert env.central.find("delete from t_schema_metadata where key in ('ollama_url'")
        assert 'admin_ollama_models_list' not in at.session_state

    def test_ollama_without_models(self, env):
        self.http.payload = b'{"models": []}'
        at = self._admin()
        at.text_input(key='admin_ollama_url').input('http://ollama.example:11434')
        at = ok(at.button(key='ollama_test').click().run())
        assert 'Connected but no models found.' in texts(at)

    def test_ollama_test_needs_a_url(self, env):
        at = ok(self._admin().button(key='ollama_test').click().run())
        assert 'Enter a URL first' in texts(at)

    def test_rejected_ollama_url_is_not_saved(self, env):
        def reject(url, kind):
            raise url_guard.UrlNotAllowed('private address')
        env.patch(url_guard, 'validate_outbound_url', reject)
        at = self._admin()
        at.text_input(key='admin_ollama_url').input('http://10.0.0.1:11434')
        at = ok(at.button(key='ollama_save').click().run())
        assert 'Ollama URL rejected: private address' in texts(at)
        assert not env.central.find('merge into t_schema_metadata')

    def test_webhook_save_test_and_clear(self, env):
        at = self._admin()
        at.text_input(key='webhook_url_input').input('https://hooks.example/abc')
        at = ok(at.button(key='webhook_save').click().run())
        assert env.central.one("'webhook_url' as key").params == {'url': 'https://hooks.example/abc'}
        at = ok(at.button(key='webhook_test').click().run())
        assert 'Test notification sent!' in texts(at)
        assert json.loads(self.http.opened[0].data)['text'].startswith('HCC Compression Advisor')
        at = ok(at.button(key='webhook_clear').click().run())
        assert env.central.find("delete from t_schema_metadata where key = 'webhook_url'")

    def test_webhook_error_status(self, env):
        self.http.status = 500
        at = self._admin()
        at.text_input(key='webhook_url_input').input('https://hooks.example/abc')
        at = ok(at.button(key='webhook_test').click().run())
        assert 'Webhook returned status 500' in texts(at)

    def test_awr_enable_and_revoke(self, env):
        at = self._admin()
        at = ok(at.checkbox(key='awr_confirm').check().run())
        at = ok(at.button(key='awr_enable').click().run())
        assert env.central.find("'awr_acknowledged' as key")
        assert at.session_state['awr_acknowledged'] is True
        env.central.on("key = 'awr_acknowledged'", result=df([{'VALUE': 'Y'}]))
        at = ok(at.run())
        at = ok(at.button(key='awr_revoke').click().run())
        assert env.central.find("delete from t_schema_metadata where key = 'awr_acknowledged'")
        assert at.session_state['awr_acknowledged'] is False

    def test_apply_a_pending_patch(self, env):
        dirs = list_patch_dirs(find_patches_dir())
        env.patch(page_09_admin, 'find_patches_dir', find_patches_dir)
        env.patch(page_09_admin, 'patches_dir_problem', lambda d: None)
        env.patch(page_09_admin, 'scan_patches', lambda pd_: patch_scan(dirs))
        pending = dirs[3].name
        at = self._admin()
        at = ok(at.button(key=f'apply_{pending}').click().run())
        assert env.central.one('insert into t_patch_history').params == {
            'n': pending, 's': 'SUCCESS'}
        at = ok(at.run())                  # the result is shown after the rerun
        assert f'Patch **{pending}** applied!' in texts(at)

    def test_purge_after_the_phrase(self, env):
        env.returns(CentralQueries, 'get_history_purge_preview', {
            'counts': {t: 3 for t in CentralQueries.PURGE_HISTORY_TABLES},
            'targets_to_reset': 1, 'active': {'queued': 0, 'in_progress': 0, 'running_runs': 0}})
        purge = env.patch(CentralQueries, 'purge_operation_history', MagicMock(return_value=(
            True, 'Purged', {'T_COMPRESSION_HISTORY': 3})))
        at = self._admin()
        at = ok(at.selectbox(key='admin_purge_scope').select('Prod (ID 1)').run())
        assert at.button(key='admin_purge_btn_1').disabled
        at = ok(at.text_input(key='admin_purge_confirm_1').input('DELETE HISTORY').run())
        at = ok(at.button(key='admin_purge_btn_1').click().run())
        purge.assert_called_once_with(database_id=1, include_active=False, acting_user=ROLE_ADMIN)
        env.rerun.assert_called()
        # shown after the rerun; the typed confirmation is cleared
        assert at.session_state['admin_purge_result'] == {
            'message': 'Purged', 'deleted': {'T_COMPRESSION_HISTORY': 3}}
        assert 'admin_purge_confirm_1' not in at.session_state


# ============================================================================
# Target registration (DB Connections)
# ============================================================================

@pytest.mark.unit
class TestConnectionsActions:

    @pytest.fixture
    def tester(self, env):
        """Two registered targets with a real encrypted password; the
        connection test is mocked."""
        key = Fernet.generate_key().decode()
        env.patch(page_06_connections.config, 'ENCRYPTION_KEY', key)
        token = Fernet(key.encode()).encrypt(b'pw').decode()
        env.targets = pd.concat([
            TARGETS.assign(PASSWORD_ENCRYPTED=token),
            TARGETS.assign(DATABASE_ID=2, DATABASE_NAME='QA', DISPLAY_NAME='QA',
                           PASSWORD_ENCRYPTED=token)])
        return env.patch(page_06_connections, 'test_target_connection', MagicMock(
            return_value=(True, 'Connected successfully!', 'Oracle 23ai')))

    def test_test_a_registered_target(self, env, tester):
        at = ok(page('page_06_connections', 'show_connections_page').run())
        ok(at.button(key='test_1').click().run())
        conn = tester.call_args.args[0]
        assert (conn['host'], conn['password'], conn['mode']) == ('db1', 'pw', 'NORMAL')
        assert env.central.one('set last_connected').params == {'database_id': 1}
        assert env.central.one('set oracle_version').params['oracle_version'] == 'Oracle 23ai'

    def test_activate_and_remove_another_target(self, env, tester):
        at = ok(page('page_06_connections', 'show_connections_page').run())
        assert at.button(key='delete_1').disabled                  # the active one
        at = ok(at.button(key='activate_2').click().run())
        assert at.session_state['active_database_id'] == 2
        at = ok(page('page_06_connections', 'show_connections_page').run())
        ok(at.button(key='delete_2').click().run())
        assert env.central.one("set is_active = 'n'").params == {'database_id': 2}

    def test_add_a_target(self, env, tester):
        add = env.patch(CentralQueries, 'add_target_database', MagicMock(
            return_value=(True, 'Target database registered successfully', 9)))
        at = ok(page('page_06_connections', 'show_connections_page').run())
        values = {'Database Name *': 'dwh', 'Display Name *': 'DWH', 'Host *': 'dwhhost',
                  'Service Name *': 'DWHPDB', 'Password *': 'secret', 'Username *': 'hcc'}
        for widget in at.text_input:
            if widget.label in values:
                widget.input(values[widget.label])
        at = ok(button(at, 'Add Database').click().run())
        data = add.call_args.args[0]
        assert (data['database_name'], data['username'], data['oracle_version']) == (
            'dwh', 'hcc', 'Oracle 23ai')
        assert data['password_encrypted'] != 'secret'
        assert at.session_state['active_database_id'] == 9

    def test_add_requires_every_field(self, env, tester):
        at = ok(page('page_06_connections', 'show_connections_page').run())
        at = ok(button(at, 'Add Database').click().run())
        assert 'Please fill in all required fields' in texts(at)
        tester.assert_not_called()

    def test_quick_and_pre_tests(self, env, tester):
        at = ok(page('page_06_connections', 'show_connections_page').run())
        at.text_input(key='test_password').input('pw')
        at = ok(at.button(key='quick_test').click().run())
        assert 'Connected successfully!\nOracle 23ai' in texts(at)
        at = ok(at.button(key='pretest_btn').click().run())
        assert 'Fill in all fields' in texts(at)


# ============================================================================
# Quick Action
# ============================================================================

@pytest.mark.unit
class TestQuickScanActions:

    @pytest.fixture(autouse=True)
    def _data(self, env):
        env.returns(TargetQueries, 'get_available_schemas', ['APP', 'HR'])
        env.returns(TargetQueries, 'get_cpu_count', 16)
        env.returns(CentralQueries, 'get_recommendations', RECS)

    def test_scan_now(self, env):
        scan = env.patch(TargetQueries, 'quick_scan', MagicMock(return_value=[{}, {}, {}]))
        at = ok(page('page_08_quick_scan', 'show_quick_scan_page', ROLE_OPERATOR).run())
        at = ok(at.button(key='qs_scan').click().run())
        scan.assert_called_once_with(DB, owner=None)
        assert at.session_state['qs_last_count'] == 3

    def test_scan_finding_nothing_explains_why(self, env):
        env.patch(TargetQueries, 'quick_scan', MagicMock(return_value=[]))
        at = ok(page('page_08_quick_scan', 'show_quick_scan_page', ROLE_OPERATOR).run())
        at = ok(at.selectbox(key='qs_schema').select('HR').run())
        at = ok(at.button(key='qs_scan').click().run())
        at = ok(at.run())                  # st.rerun is mocked: render the new state
        warning = ' '.join(w.value for w in at.warning)
        assert 'Last scan (HR) found no eligible tables' in warning
        assert 'DBA_TABLES' in warning
        assert not any('objects analyzed' in s.value for s in at.success)

    def test_refresh_checks_completed_jobs(self, env):
        check = env.patch(TargetQueries, 'check_completed_jobs', MagicMock(return_value=[{}]))
        at = ok(page('page_08_quick_scan', 'show_quick_scan_page', ROLE_VIEWER).run())
        ok(at.button(key='qs_refresh').click().run())
        check.assert_called_once_with(DB)

    def test_running_only_filter(self, env):
        at = ok(page('page_08_quick_scan', 'show_quick_scan_page').run())
        at = ok(at.checkbox(key='qs_running_only').check().run())
        assert 'No running compression jobs.' in texts(at)

    def test_bulk_submit(self, env):
        enqueue = env.patch(TargetQueries, 'enqueue_compression_jobs', MagicMock(return_value={
            'added': 2, 'duplicates': 0, 'rejected': 0, 'errors': []}))
        env.patch(TargetQueries, 'drain_compression_queue', MagicMock(return_value={
            'submitted': 1, 'failed': 0, 'waiting': 1, 'errors': []}))
        at = ok(page('page_08_quick_scan', 'show_quick_scan_page', ROLE_OPERATOR).run())
        at = ok(at.multiselect(key='qs_bulk_schemas').select('APP').run())
        at = ok(at.checkbox(key='qs_bulk_confirm').check().run())
        at = ok(at.button(key='qs_bulk_submit').click().run())
        (items,), _ = enqueue.call_args
        assert sorted((i['table_name'], i['subpartition_name']) for i in items) == [
            ('ORDERS', None), ('SALES', 'SP1')]
        assert 'Submitted: 1, Queued for later: 1' in texts(at)
        assert at.session_state['selected_page'] == 'Scheduler'

    def test_export_filters(self, env):
        at = ok(page('page_08_quick_scan', 'show_quick_scan_page').run())
        at = ok(at.selectbox(key='qs_export_type').select('Partitions only').run())
        assert '**1** operations will be included in the export' in texts(at)
        at = ok(at.selectbox(key='qs_export_status').select('Failed').run())
        assert 'No operations match the selected filters.' in texts(at)


# ============================================================================
# Setup page: direct-connection helpers
# ============================================================================

CREDS = ('db', 1521, 'PDB', 'HCC', 'pw')


@pytest.mark.unit
class TestSetupHelpers:

    @pytest.fixture
    def setup_db(self, env):
        """page_00_setup._connect answering from its own router."""
        router = SqlRouter('setup')
        connect = env.patch(page_00_setup, '_connect',
                            MagicMock(side_effect=lambda *a: router.connection()))
        yield router
        assert not router.bind_errors, router.bind_errors
        assert connect.called

    def test_connection_banner(self, setup_db):
        setup_db.on('v$version', result=df([{'BANNER': 'Oracle Database 23ai'}]))
        assert page_00_setup._test_connection(*CREDS) == (True, 'Oracle Database 23ai')

    def test_connection_failure(self, env):
        def refuse(*args):
            raise oracledb.DatabaseError('ORA-12541: no listener')
        env.patch(page_00_setup, '_connect', refuse)
        assert page_00_setup._test_connection(*CREDS) == (False, 'ORA-12541: no listener')
        assert page_00_setup._check_privileges(*CREDS) == (False, [('CONNECTION', False)])
        assert page_00_setup._get_schema_state(*CREDS)['connected'] is False
        assert page_00_setup._drop_all_hcc_objects(*CREDS) == ['Error: ORA-12541: no listener']
        assert page_00_setup._get_pending_patches(*CREDS) == (None, 'ORA-12541: no listener')

    def test_privileges(self, setup_db):
        setup_db.on('session_privs', result=lambda sql, params: df([
            {'N': 0 if params['p'] == 'CREATE TYPE' else 1}]))
        setup_db.on('user_ts_quotas', result=df([{'N': 1}]))
        all_ok, results = page_00_setup._check_privileges(*CREDS)
        assert all_ok is False
        assert ('CREATE TYPE', False) in results and ('TABLESPACE QUOTA', True) in results

    def test_schema_state(self, setup_db):
        setup_db.on('v$version', result=df([{'BANNER': 'Oracle 23ai'}]))
        setup_db.on('from user_tables', result=df([{'N': 9}]))
        setup_db.on("key = 'schema_version'", result=df([{'VALUE': '3.1.0'}]))
        setup_db.on("key = 'installed_at'", result=df([{'VALUE': '2026-01-01'}]))
        setup_db.on('from user_tab_columns', result=df([{'N': 1}]))   # the deployed check
        state = page_00_setup._get_schema_state(*CREDS)
        assert state['connected'] and state['banner'] == 'Oracle 23ai'
        assert state['tables_found'] == 9 and state['deployed'] is True
        assert state['version'] == '3.1.0' and state['installed_at'] == '2026-01-01'

    def test_drop_ignores_missing_objects(self, setup_db):
        setup_db.on('drop table t_patch_history',
                    result=oracledb.DatabaseError('ORA-00942: table or view does not exist'))
        setup_db.on('drop table t_schema_metadata',
                    result=oracledb.DatabaseError('ORA-00054: resource busy'))
        messages = page_00_setup._drop_all_hcc_objects(*CREDS)
        assert 'Dropped table T_COMPRESSION_HISTORY' in messages
        assert not any('T_PATCH_HISTORY' in m for m in messages)
        assert any(m.startswith('Could not drop table T_SCHEMA_METADATA') for m in messages)
        assert 'Dropped sequence SEQ_EXECUTION_ID' in messages

    def test_pending_patches(self, setup_db, env):
        env.patch(page_00_setup.sql_patches, 'scan_patches', lambda dirs, conn=None: SimpleNamespace(
            pending=[SimpleNamespace(name='20260924-x')]))
        assert page_00_setup._get_pending_patches(*CREDS) == (['20260924-x'], None)
