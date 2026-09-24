"""
Unit tests for role-based gating of mutating actions (viewer < operator < admin).

- AuthManager.role_gate returns (allowed, help_text) following ROLE_LEVELS.
- Representative pages: for an under-privileged role the button is disabled AND
  a forced click (AppTest clicks disabled buttons, as a crafted websocket
  message could) does not call the mutating function; for a sufficient role it
  does. Roles are set through session state, so the real has_role runs.
"""
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest
import streamlit as st
from streamlit.testing.v1 import AppTest

from hcc_advisor import auth
from hcc_advisor.auth import AuthManager, ROLE_ADMIN, ROLE_OPERATOR, ROLE_VIEWER
from hcc_advisor.utils.central_queries import CentralQueries
from hcc_advisor.utils.target_queries import TargetQueries
from hcc_advisor.views import page_00_setup, page_10_tablespaces, page_12_scheduler


def _app(script, role, **state):
    """AppTest for `script` with an authenticated session of `role` (None = anonymous)."""
    at = AppTest.from_function(script, default_timeout=10)
    at.session_state['authenticated'] = role is not None
    at.session_state['role'] = role
    for key, value in state.items():
        at.session_state[key] = value
    return at


def _errors(at):
    return " ".join(e.value for e in at.error)


def _pin_formatted_selectbox(selectbox):
    """AppTest (1.31) can't send back a selectbox that uses format_func (it looks
    the raw value up among the formatted labels); pin it to its current index."""
    selectbox.select_index(selectbox.proto.default)


@pytest.fixture(autouse=True)
def no_rerun():
    """AppTest (1.31) keeps a clicked button's trigger across st.rerun(), so a
    handler that reruns after acting would loop until timeout."""
    with patch.object(st, 'rerun'):
        yield


# ---------------------------------------------------------------------------
# role_gate helper
# ---------------------------------------------------------------------------

@pytest.fixture
def session(monkeypatch):
    """Replace auth's streamlit handle with a plain-dict session state."""
    state = {}
    monkeypatch.setattr(auth, 'st', SimpleNamespace(session_state=state, error=MagicMock()))
    return state


@pytest.mark.unit
@pytest.mark.auth
class TestRoleGate:

    @pytest.mark.parametrize('role, required, allowed', [
        (ROLE_VIEWER, ROLE_VIEWER, True),
        (ROLE_VIEWER, ROLE_OPERATOR, False),
        (ROLE_VIEWER, ROLE_ADMIN, False),
        (ROLE_OPERATOR, ROLE_OPERATOR, True),
        (ROLE_OPERATOR, ROLE_ADMIN, False),
        (ROLE_ADMIN, ROLE_OPERATOR, True),
        (ROLE_ADMIN, ROLE_ADMIN, True),
    ])
    def test_follows_role_hierarchy(self, session, role, required, allowed):
        session.update(authenticated=True, role=role)
        assert AuthManager.role_gate(required) == (
            allowed, None if allowed else f"Requires the {required} role.")

    def test_denied_when_not_authenticated(self, session):
        session.update(authenticated=False, role=ROLE_ADMIN)
        assert AuthManager.role_gate(ROLE_VIEWER) == (False, "Requires the viewer role.")

    def test_legacy_session_without_role_is_admin(self, session):
        session.update(authenticated=True, role=None)
        assert AuthManager.role_gate(ROLE_ADMIN) == (True, None)


# ---------------------------------------------------------------------------
# Scheduler: refresh drains the queue only for operators
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestSchedulerRefreshDrain:

    @pytest.mark.parametrize('role, drains', [
        (ROLE_VIEWER, False), (ROLE_OPERATOR, True), (ROLE_ADMIN, True),
    ])
    def test_drain_requires_operator(self, session, role, drains):
        session.update(authenticated=True, role=role)
        with patch.object(TargetQueries, 'check_completed_jobs') as poll, \
                patch.object(page_12_scheduler, '_drain_pending_queue') as drain:
            page_12_scheduler._do_refresh(1)
        poll.assert_called_once_with(1)  # status polling stays open to viewers
        assert drain.called is drains


# ---------------------------------------------------------------------------
# Scheduler: recurring DBMS_SCHEDULER jobs
# ---------------------------------------------------------------------------

def _recurring_jobs_app():
    from hcc_advisor.views.page_12_scheduler import _render_recurring_jobs
    _render_recurring_jobs(1)


@pytest.fixture
def recurring_mocks():
    jobs = pd.DataFrame({'JOB_NAME': ['HCC_SCAN_WEEKLY'], 'ENABLED': ['TRUE']})
    with patch.object(TargetQueries, 'get_recurring_scan_jobs', return_value=jobs), \
            patch.object(TargetQueries, 'drop_recurring_scan_job', return_value=True) as drop, \
            patch.object(TargetQueries, 'create_recurring_scan_job',
                         return_value={'success': True, 'job_name': 'HCC_SCAN_DAILY'}) as create:
        yield drop, create


@pytest.mark.unit
class TestRecurringJobsGate:

    def test_viewer_cannot_drop_or_create(self, recurring_mocks):
        drop, create = recurring_mocks
        at = _app(_recurring_jobs_app, ROLE_VIEWER).run()
        assert at.button(key='sched_drop_btn').proto.disabled
        assert at.button(key='sched_create_recurring').proto.disabled

        at = at.button(key='sched_drop_btn').click().run()
        at = at.button(key='sched_create_recurring').click().run()
        drop.assert_not_called()
        create.assert_not_called()
        assert 'operator' in _errors(at)

    def test_operator_can_drop_and_create(self, recurring_mocks):
        drop, create = recurring_mocks
        at = _app(_recurring_jobs_app, ROLE_OPERATOR).run()
        assert not at.button(key='sched_drop_btn').proto.disabled

        at.button(key='sched_drop_btn').click().run()
        drop.assert_called_once_with(1, 'HCC_SCAN_WEEKLY')
        at.button(key='sched_create_recurring').click().run()
        create.assert_called_once_with(1, 'WEEKLY')


# ---------------------------------------------------------------------------
# Recommendations: live batch execution vs dry run
# ---------------------------------------------------------------------------

def _batch_app():
    import pandas as pd
    import streamlit as st
    from hcc_advisor.views.page_02_recommendations import execute_batch_compression
    sel = pd.DataFrame({'ID': [7], 'Table': ['T1'], 'Owner': ['APP'],
                        'Advised': ['QUERY HIGH'], 'Partition': [None]})
    execute_batch_compression(sel, sel, st.session_state['test_dry_run'], 4)


@pytest.mark.unit
class TestRecommendationsExecuteGate:

    @pytest.mark.parametrize('role, dry_run, runs', [
        (ROLE_VIEWER, False, False),
        (ROLE_VIEWER, True, True),      # DDL preview only: allowed
        (ROLE_OPERATOR, False, True),
    ])
    def test_live_execution_requires_operator(self, role, dry_run, runs):
        result = {'success': True, 'dry_run': dry_run, 'ddl': 'ALTER TABLE ...', 'execution_id': 1}
        with patch.object(TargetQueries, 'execute_compression', return_value=result) as execute:
            at = _app(_batch_app, role, active_database_id=1, test_dry_run=dry_run).run()
        assert execute.called is runs
        if runs:
            assert execute.call_args.kwargs['dry_run'] is dry_run
        else:
            assert 'operator' in _errors(at)


# ---------------------------------------------------------------------------
# Tablespaces: datafile resize
# ---------------------------------------------------------------------------

def _tablespaces_app():
    from hcc_advisor.views.page_10_tablespaces import show_tablespaces_page
    show_tablespaces_page()


@pytest.fixture
def shrink_mocks():
    usage = pd.DataFrame({
        'tablespace_name': ['USERS'], 'allocated_mb': [1000.0], 'used_mb': [200.0],
        'free_mb': [800.0], 'used_pct': [20.0], 'shrinkable_mb': [700.0], 'can_shrink': ['YES'],
    })
    shrink_result = {'message': '1 file(s) resized', 'level': 'success', 'files': []}
    with patch.object(page_10_tablespaces, '_get_tablespace_usage', return_value=usage), \
            patch.object(page_10_tablespaces, '_get_datafile_details', return_value=pd.DataFrame()), \
            patch.object(page_10_tablespaces, '_shrink_tablespace', return_value=shrink_result) as shrink:
        yield shrink


@pytest.mark.unit
class TestTablespaceShrinkGate:

    @pytest.mark.parametrize('role, runs', [(ROLE_VIEWER, False), (ROLE_OPERATOR, True)])
    def test_shrink_requires_operator(self, shrink_mocks, role, runs):
        at = _app(_tablespaces_app, role, active_database_id=1,
                  ts_shrink_targets=['USERS']).run()
        at = at.checkbox(key='ts_confirm').check().run()
        assert at.button(key='ts_execute').proto.disabled is not runs

        at.button(key='ts_execute').click().run()
        if runs:
            shrink_mocks.assert_called_once_with(1, 'USERS')
        else:
            shrink_mocks.assert_not_called()


# ---------------------------------------------------------------------------
# Wizard: quick scan step
# ---------------------------------------------------------------------------

def _wizard_scan_app():
    from hcc_advisor.views.page_14_wizard import _step_quick_scan
    _step_quick_scan()


@pytest.mark.unit
class TestWizardScanGate:

    @pytest.mark.parametrize('role, runs', [(ROLE_VIEWER, False), (ROLE_OPERATOR, True)])
    def test_scan_requires_operator(self, role, runs):
        with patch.object(TargetQueries, 'get_available_schemas', return_value=['APP']), \
                patch.object(TargetQueries, 'quick_scan', return_value=[]) as scan:
            at = _app(_wizard_scan_app, role, wizard_db_id=1, wizard_step=2).run()
            # A viewer can't scan, so Next is open to review existing candidates.
            assert at.button(key='wiz_next').proto.disabled is runs
            _pin_formatted_selectbox(at.selectbox(key='wiz_throttle'))
            at.button(key='wiz_scan').click().run()
        assert scan.called is runs


# ---------------------------------------------------------------------------
# Compression rules: admin only
# ---------------------------------------------------------------------------

def _rules_app():
    from hcc_advisor.views.page_05_strategies import show_strategy_rules_editor
    show_strategy_rules_editor()


@pytest.mark.unit
class TestStrategyRulesGate:

    @pytest.mark.parametrize('role, runs', [(ROLE_OPERATOR, False), (ROLE_ADMIN, True)])
    def test_delete_rule_requires_admin(self, role, runs):
        strategies = pd.DataFrame({'STRATEGY_ID': [2], 'STRATEGY_NAME': ['BALANCED']})
        rules = pd.DataFrame({'RULE_ID': [11], 'STRATEGY_NAME': ['BALANCED'],
                              'RULE_DESCRIPTION': ['hot tables'], 'ENABLED_FLAG': ['Y']})
        with patch.object(CentralQueries, 'get_all_strategies', return_value=strategies), \
                patch.object(CentralQueries, 'get_all_strategy_rules', return_value=rules), \
                patch.object(CentralQueries, 'delete_strategy_rule',
                             return_value=(True, 'deleted')) as delete:
            at = _app(_rules_app, role).run()
            _pin_formatted_selectbox(next(sb for sb in at.selectbox
                                          if sb.label == 'Select Rule to Delete'))
            button = next(b for b in at.button if 'Delete Rule' in b.label)
            assert button.proto.disabled is not runs
            button.click().run()
        if runs:
            delete.assert_called_once_with(11)
        else:
            delete.assert_not_called()


# ---------------------------------------------------------------------------
# Deployment wizard: admin only (first run included)
# ---------------------------------------------------------------------------

def _deploy_app():
    import streamlit as st
    from hcc_advisor.views.page_00_setup import show_deployment_page
    show_deployment_page(mode=st.session_state['test_mode'])


@pytest.fixture
def deploy_mocks():
    with patch.object(page_00_setup.config, 'CENTRAL_DB_PASSWORD', 'central-secret'), \
            patch.object(page_00_setup, '_show_existing_installation') as existing, \
            patch.object(page_00_setup, '_show_setup_wizard') as wizard:
        yield existing, wizard


@pytest.mark.unit
class TestDeploymentGate:

    @pytest.mark.parametrize('role', [ROLE_VIEWER, ROLE_OPERATOR])
    @pytest.mark.parametrize('mode', ['setup', 'upgrade'])
    def test_non_admin_is_blocked(self, deploy_mocks, role, mode):
        existing, wizard = deploy_mocks
        at = _app(_deploy_app, role, test_mode=mode).run()
        existing.assert_not_called()
        wizard.assert_not_called()
        assert 'admin role' in _errors(at)

    def test_non_admin_can_continue_past_upgrade(self, deploy_mocks):
        at = _app(_deploy_app, ROLE_VIEWER, test_mode='upgrade').run()
        at.button(key='setup_continue_non_admin').click().run()
        assert at.session_state['setup_complete'] is True

    @pytest.mark.parametrize('mode', ['setup', 'upgrade'])
    def test_admin_reaches_wizard(self, deploy_mocks, mode):
        existing, wizard = deploy_mocks
        at = _app(_deploy_app, ROLE_ADMIN, test_mode=mode).run()
        assert existing.called is (mode == 'upgrade')
        assert wizard.called is (mode == 'setup')
        assert not at.error
