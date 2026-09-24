"""
Unit tests for in-session auto-refresh: the shared helper
``utils/ui_refresh.schedule_rerun`` and the four pages that use it
(Run Analysis, Compress Tables, Session Browser, Scheduler), plus the deferred
mode app.py uses (``defer_reruns`` / ``run_deferred_rerun``), which moves the
wait after the SQL Debug Console.

Each page runs under ``streamlit.testing.v1.AppTest`` with the central/target
query layers mocked, so no database is needed. The helper's ``time`` module and
``st.rerun`` are mocked, so an auto-refresh run ends instead of looping, and
every data-source call, sleep and rerun is logged in one ordered event list:
that is how the tests check that a page renders BEFORE it waits.

The page tests call the page functions directly, without app.py, so there the
page's own ``schedule_rerun`` call still waits in place (no ``defer_reruns``
in the run). ``TestDeferredRerun`` and ``TestAppShellAutoRefresh`` cover the
deferred path, the latter through the real app.py.
"""
from contextlib import ExitStack
from unittest.mock import MagicMock, call, patch

import pandas as pd
import pytest
import streamlit as st
from streamlit.testing.v1 import AppTest

from hcc_advisor.utils import sql_debug, ui_refresh
from hcc_advisor.utils.central_queries import CentralQueries
from hcc_advisor.utils.target_queries import TargetQueries
from hcc_advisor.views import (
    page_01_analysis,
    page_03_execution,
    page_07_sessions,
    page_12_scheduler,
)

from tests.unit.app_harness import app_shell, new_app

TIMEOUT = 15  # seconds per AppTest run; generous for slow CI machines


class Recorder:
    """Ordered log of data-source calls, sleeps and reruns in a page run."""

    def __init__(self):
        self.events = []
        self.time = MagicMock(name="ui_refresh.time")
        self.time.sleep.side_effect = lambda s: self.events.append(("sleep", s))
        self.rerun = MagicMock(name="st.rerun",
                               side_effect=lambda: self.events.append(("rerun",)))

    def source(self, name, value):
        """A mock data source that logs its call and returns a fresh copy of `value`."""
        def _call(*args, **kwargs):
            self.events.append(("query", name))
            return value.copy()
        return MagicMock(name=name, side_effect=_call)

    def reset(self):
        self.events.clear()
        self.time.sleep.reset_mock()
        self.rerun.reset_mock()

    @property
    def slept(self):
        return sum(e[1] for e in self.events if e[0] == "sleep")

    def queries(self):
        return [e[1] for e in self.events if e[0] == "query"]

    def assert_rendered_before_waiting(self):
        """Every data-source call precedes the first sleep; the rerun comes last."""
        kinds = [e[0] for e in self.events]
        assert "sleep" in kinds, self.events
        first_sleep = kinds.index("sleep")
        assert "query" in kinds[:first_sleep], self.events
        assert "query" not in kinds[first_sleep:], self.events
        assert kinds[-1] == "rerun", self.events


@pytest.fixture
def rec():
    """Mock the helper's clock and st.rerun for the duration of a test."""
    recorder = Recorder()
    with patch.object(ui_refresh, "time", recorder.time), \
            patch.object(st, "rerun", recorder.rerun):
        yield recorder


def _patch_all(stack, targets):
    """Enter patch.object(obj, attr, value) for each (obj, attr, value)."""
    mocks = {}
    for obj, attr, value in targets:
        mocks[attr] = stack.enter_context(patch.object(obj, attr, value))
    return mocks


def _spy_helper(stack, page_module):
    """Wrap the page's schedule_rerun so its calls can be asserted."""
    spy = MagicMock(name="schedule_rerun", wraps=ui_refresh.schedule_rerun)
    stack.enter_context(patch.object(page_module, "schedule_rerun", spy))
    return spy


def _texts(elements):
    return [str(e.value) for e in elements]


def _metric_labels(at):
    return [m.label for m in at.metric]


# ============================================================================
# The helper
# ============================================================================

HELPER_SCRIPT = """
import streamlit as st
from hcc_advisor.utils.ui_refresh import schedule_rerun
st.session_state["runs"] = st.session_state.get("runs", 0) + 1
st.markdown("page content")
st.session_state["result"] = schedule_rerun("toggle", st.session_state["interval"])
"""


def _helper_app(toggle, interval):
    at = AppTest.from_string(HELPER_SCRIPT, default_timeout=TIMEOUT)
    at.session_state["toggle"] = toggle
    at.session_state["interval"] = interval
    return at


class TestScheduleRerun:

    def test_off_does_not_sleep_or_rerun(self, rec):
        at = _helper_app(False, 10).run()
        assert not at.exception
        assert at.session_state["result"] is False
        rec.time.sleep.assert_not_called()
        rec.rerun.assert_not_called()

    def test_missing_toggle_key_counts_as_off(self, rec):
        at = AppTest.from_string(HELPER_SCRIPT.replace('"toggle"', '"never_set"'),
                                 default_timeout=TIMEOUT)
        at.session_state["interval"] = 10
        at.run()
        assert at.session_state["result"] is False
        rec.time.sleep.assert_not_called()
        rec.rerun.assert_not_called()

    def test_on_waits_the_interval_then_reruns_once(self, rec):
        at = _helper_app(True, 5).run()
        assert not at.exception
        assert at.session_state["result"] is True
        # 1 s ticks (each one a Streamlit yield point), then a single rerun.
        assert rec.time.sleep.call_args_list == [call(1.0)] * 5
        rec.rerun.assert_called_once_with()
        assert rec.events[-1] == ("rerun",)
        assert "page content" in _texts(at.markdown)
        assert any(c.startswith("Auto-refresh on") for c in _texts(at.caption))

    @pytest.mark.parametrize("interval, expected", [
        (0, 2), (0.5, 2), (-5, 2), (2, 2), (2.5, 2.5), (600, 600),
    ])
    def test_interval_is_clamped_to_minimum(self, rec, interval, expected):
        _helper_app(True, interval).run()
        assert rec.slept == pytest.approx(expected)
        assert all(0 < c.args[0] <= 1.0 for c in rec.time.sleep.call_args_list)
        rec.rerun.assert_called_once_with()

    def test_pending_interaction_cuts_the_wait_short(self, rec):
        """A user action during the wait (here: a queued rerun request, which is
        what a click sends) ends the wait at the next tick, not after the full
        interval, and the script reruns with that request."""
        from streamlit.runtime.scriptrunner import RerunData, get_script_run_ctx

        sleeps = []

        def sleep(seconds):
            sleeps.append(seconds)
            if len(sleeps) == 1:
                get_script_run_ctx().script_requests.request_rerun(RerunData())

        rec.time.sleep.side_effect = sleep
        at = _helper_app(True, 5).run()

        assert not at.exception
        assert at.session_state["runs"] == 2
        # Run 1 was abandoned after its first tick; run 2 waited in full.
        assert sleeps == [1.0] + [1.0] * 5
        rec.rerun.assert_called_once_with()

    @pytest.mark.parametrize("seconds, text", [
        (1, "1s"), (4.2, "5s"), (59, "59s"), (60, "1m 00s"), (300, "5m 00s"), (61, "1m 01s"),
    ])
    def test_countdown_format(self, seconds, text):
        assert ui_refresh._format_remaining(seconds) == text


# ============================================================================
# Deferred mode (what app.py does around the page)
# ============================================================================

DEFERRED_SCRIPT = """
import streamlit as st
from hcc_advisor.utils import ui_refresh
from hcc_advisor.utils.ui_refresh import defer_reruns, run_deferred_rerun, schedule_rerun
ss = st.session_state
ss["runs"] = ss.get("runs", 0) + 1
defer_reruns()
st.markdown("page content")
if not ss.get("skip_schedule"):
    ss["result"] = schedule_rerun("toggle", ss["interval"])
    if ss.get("second_key"):
        schedule_rerun(ss["second_key"], 60)
ss["sleeps_when_page_done"] = ui_refresh.time.sleep.call_count
st.markdown("after the page")
if ss.get("stop_before_end"):
    st.stop()
ss["deferred_result"] = run_deferred_rerun()
"""


def _deferred_app(toggle, interval, **state):
    at = AppTest.from_string(DEFERRED_SCRIPT, default_timeout=TIMEOUT)
    at.session_state["toggle"] = toggle
    at.session_state["interval"] = interval
    for key, value in state.items():
        at.session_state[key] = value
    return at


class TestDeferredRerun:

    def test_page_returns_at_once_and_the_wait_comes_last(self, rec):
        at = _deferred_app(True, 5).run()
        assert not at.exception
        # schedule_rerun only recorded the refresh...
        assert at.session_state["result"] is True
        assert at.session_state["sleeps_when_page_done"] == 0
        assert "after the page" in _texts(at.markdown)
        # ...and run_deferred_rerun waited exactly as schedule_rerun would.
        assert at.session_state["deferred_result"] is True
        assert rec.time.sleep.call_args_list == [call(1.0)] * 5
        rec.rerun.assert_called_once_with()
        assert any(c.startswith("Auto-refresh on") for c in _texts(at.caption))
        # The deferral ends with the run.
        assert ui_refresh._PENDING_KEY not in at.session_state

    def test_off_never_sleeps(self, rec):
        at = _deferred_app(False, 5).run()
        assert at.session_state["result"] is False
        assert at.session_state["deferred_result"] is False
        rec.time.sleep.assert_not_called()
        rec.rerun.assert_not_called()

    @pytest.mark.parametrize("interval, expected", [(0, 2), (0.5, 2), (2.5, 2.5), (30, 30)])
    def test_interval_is_clamped_to_minimum(self, rec, interval, expected):
        _deferred_app(True, interval).run()
        assert rec.slept == pytest.approx(expected)
        rec.rerun.assert_called_once_with()

    def test_first_scheduled_refresh_wins(self, rec):
        at = _deferred_app(True, 3, second_key="toggle2", toggle2=True).run()
        assert rec.slept == 3
        rec.rerun.assert_called_once_with()
        assert at.session_state["deferred_result"] is True

    def test_early_stop_never_reruns_and_leaves_nothing_behind(self, rec):
        at = _deferred_app(True, 5, stop_before_end=True).run()
        assert not at.exception
        rec.time.sleep.assert_not_called()
        rec.rerun.assert_not_called()
        # Next run: the page (still toggled on) does not schedule this time.
        # The refresh recorded by the stopped run must not fire now.
        at.session_state["stop_before_end"] = False
        at.session_state["skip_schedule"] = True
        at.run()
        assert at.session_state["deferred_result"] is False
        rec.time.sleep.assert_not_called()
        rec.rerun.assert_not_called()

    def test_without_defer_the_page_still_waits_in_place(self, rec):
        """A page rendered outside app.py (no defer_reruns in the run)."""
        at = _helper_app(True, 3).run()
        assert at.session_state["result"] is True
        assert rec.slept == 3
        assert ui_refresh._PENDING_KEY not in at.session_state


# ============================================================================
# app.py: the wait comes after the SQL Debug Console
# ============================================================================

class TestAppShellAutoRefresh:

    def _run(self, rec, auto_refresh):
        console = MagicMock(name="get_sql_log",
                            side_effect=lambda: rec.events.append(("console",)) or [])
        extra = [*_page_07_sources(rec), (sql_debug, "get_sql_log", console)]
        with app_shell("Session Browser", extra=extra):
            at = new_app()
            at.session_state["sql_debug_enabled"] = True
            at.session_state["session_auto_refresh"] = auto_refresh
            at.run()
        return at

    def test_console_renders_before_the_wait(self, rec):
        at = self._run(rec, auto_refresh=True)

        assert not at.exception
        assert "SQL Debug Console" in _texts(at.subheader)
        assert len(at.tabs) == 3  # the Session Browser page itself
        kinds = [e[0] for e in rec.events]
        assert "console" in kinds and "sleep" in kinds, rec.events
        # Page queries, then the console, then the whole wait, then the rerun.
        assert kinds.index("console") < kinds.index("sleep")
        assert "query" not in kinds[kinds.index("console"):]
        rec.assert_rendered_before_waiting()
        assert rec.slept == 5  # the page's default interval
        rec.rerun.assert_called_once_with()

    def test_off_renders_console_without_waiting(self, rec):
        at = self._run(rec, auto_refresh=False)
        assert not at.exception
        assert "SQL Debug Console" in _texts(at.subheader)
        rec.time.sleep.assert_not_called()
        rec.rerun.assert_not_called()


# ============================================================================
# Run Analysis (page_01) — Monitor Progress tab
# ============================================================================

PAGE_01_SCRIPT = """
from hcc_advisor.views.page_01_analysis import show_analysis_page
show_analysis_page()
"""


def _page_01_sources(rec):
    running = pd.DataFrame([{
        "OPERATION_TYPE": "ANALYSIS", "OPERATION_ID": 42, "OWNER": "SALES",
        "STATUS": "RUNNING", "DURATION_MINUTES": 3.5, "PROGRESS_PCT": 40.0,
    }])
    runs = pd.DataFrame([{
        "RUN_ID": 41, "STATUS": "COMPLETED", "OWNER_FILTER": "SALES",
        "TABLES_ANALYZED": 12, "CANDIDATES_FOUND": 4, "DURATION_SECONDS": 90,
        "RUN_DATE": "2026-09-24 10:00:00", "ERROR_MESSAGE": None,
    }])
    progress = {"OBJECTS_ANALYZED": 7, "OBJECTS_SKIPPED": 1, "RECOMMEND_BASIC": 2}
    return [
        (CentralQueries, "get_running_operations", rec.source("running_ops", running)),
        (CentralQueries, "get_analysis_runs", rec.source("analysis_runs", runs)),
        (CentralQueries, "get_operation_progress", rec.source("progress", progress)),
        # The other two tabs are out of scope here.
        (page_01_analysis, "show_analysis_config", MagicMock()),
        (page_01_analysis, "show_schema_size", MagicMock()),
    ]


class TestAnalysisPageAutoRefresh:

    def test_off_renders_without_waiting(self, rec):
        with ExitStack() as stack:
            _patch_all(stack, _page_01_sources(rec))
            spy = _spy_helper(stack, page_01_analysis)
            at = AppTest.from_string(PAGE_01_SCRIPT, default_timeout=TIMEOUT).run()

        assert not at.exception
        assert "Run ID" in _metric_labels(at)
        spy.assert_called_once_with("analysis_auto_refresh", 10)
        rec.time.sleep.assert_not_called()
        rec.rerun.assert_not_called()

    def test_on_renders_monitor_then_waits_chosen_interval(self, rec):
        with ExitStack() as stack:
            _patch_all(stack, _page_01_sources(rec))
            spy = _spy_helper(stack, page_01_analysis)
            at = AppTest.from_string(PAGE_01_SCRIPT, default_timeout=TIMEOUT).run()
            at.slider(key="analysis_refresh_interval").set_value(15)
            at.checkbox(key="analysis_auto_refresh").check()
            rec.reset()
            spy.reset_mock()
            at.run()

        assert not at.exception
        # Monitor content is in the tree...
        assert any("Running Analysis" in t for t in _texts(at.markdown))
        labels = _metric_labels(at)
        for label in ("Run ID", "Status", "Objects Analyzed", "Candidates Found"):
            assert label in labels
        assert len(at.dataframe) == 1  # Recent Analysis Runs
        # ...rendered before the wait, which uses the chosen interval once.
        spy.assert_called_once_with("analysis_auto_refresh", 15)
        assert rec.slept == 15
        rec.rerun.assert_called_once_with()
        rec.assert_rendered_before_waiting()
        # Widget state survives the in-session rerun.
        assert at.session_state["analysis_auto_refresh"] is True
        assert at.session_state["analysis_refresh_interval"] == 15


# ============================================================================
# Compress Tables (page_03) — Monitor Progress tab
# ============================================================================

PAGE_03_SCRIPT = """
from hcc_advisor.views.page_03_execution import show_execution_page
show_execution_page()
"""


def _page_03_sources(rec):
    running = pd.DataFrame([{
        "OPERATION_TYPE": "COMPRESSION", "OPERATION_ID": 7, "STATUS": "RUNNING",
        "OWNER": "SALES", "TABLE_NAME": "ORDERS", "DURATION_MINUTES": 2.0,
        "PROGRESS_PCT": 55.0,
    }])
    long_ops = pd.DataFrame([{
        "OPNAME": "Table Scan", "TARGET": "SALES.ORDERS", "PCT_COMPLETE": 30.0,
        "ELAPSED_SECONDS": 60, "SECONDS_REMAINING": 140, "MESSAGE": "",
    }])
    recent = pd.DataFrame([{
        "STATUS": "SUCCESS", "OPERATION_TYPE": "COMPRESSION", "OWNER": "SALES",
        "NAME": "CUSTOMERS", "STRATEGY": "QUERY HIGH", "DURATION_MINUTES": 1.5,
        "RESULT_PCT": 62.0, "START_TIME": "2026-09-24 09:00:00", "ERROR_MESSAGE": None,
    }])
    return [
        (CentralQueries, "get_running_operations", rec.source("running_ops", running)),
        (CentralQueries, "get_recent_operations", rec.source("recent_ops", recent)),
        (TargetQueries, "get_long_operations", rec.source("long_ops", long_ops)),
        # The execution tabs are out of scope here.
        (page_03_execution, "show_single_execution", MagicMock()),
        (page_03_execution, "show_batch_execution", MagicMock()),
    ]


def _page_03_app():
    at = AppTest.from_string(PAGE_03_SCRIPT, default_timeout=TIMEOUT)
    at.session_state["active_database_id"] = 1
    return at


class TestExecutionPageAutoRefresh:

    def test_off_renders_without_waiting(self, rec):
        with ExitStack() as stack:
            _patch_all(stack, _page_03_sources(rec))
            spy = _spy_helper(stack, page_03_execution)
            at = _page_03_app().run()

        assert not at.exception
        assert "Operation ID" in _metric_labels(at)
        spy.assert_called_once_with("auto_refresh", 10)
        rec.time.sleep.assert_not_called()
        rec.rerun.assert_not_called()

    def test_on_renders_monitor_then_waits_chosen_interval(self, rec):
        with ExitStack() as stack:
            _patch_all(stack, _page_03_sources(rec))
            spy = _spy_helper(stack, page_03_execution)
            at = _page_03_app().run()
            at.slider(key="refresh_interval").set_value(20)
            at.checkbox(key="auto_refresh").check()
            rec.reset()
            spy.reset_mock()
            at.run()

        assert not at.exception
        markdown = _texts(at.markdown)
        assert any("Running Operations" in t for t in markdown)
        assert any("Long-Running Database Operations" in t for t in markdown)
        labels = _metric_labels(at)
        for label in ("Operation ID", "Duration", "Elapsed", "Remaining"):
            assert label in labels
        assert len(at.dataframe) == 1  # Recent Operations
        spy.assert_called_once_with("auto_refresh", 20)
        assert rec.slept == 20
        rec.rerun.assert_called_once_with()
        rec.assert_rendered_before_waiting()
        assert sorted(rec.queries()) == ["long_ops", "recent_ops", "running_ops"]


# ============================================================================
# Session Browser (page_07)
# ============================================================================

PAGE_07_SCRIPT = """
from hcc_advisor.views.page_07_sessions import show_sessions_page
show_sessions_page()
"""


def _page_07_sources(rec):
    longop = {
        "SID": 101, "SERIAL_NUM": 5, "OPNAME": "Table Move", "TARGET": "SALES.ORDERS",
        "PCT_COMPLETE": 45.0, "SOFAR": 450, "TOTALWORK": 1000, "UNITS": "Blocks",
        "ELAPSED_SECONDS": 120, "TIME_REMAINING_SEC": 150, "USERNAME": "HCC",
        "MESSAGE": "moving", "SQL_ID": "abc123", "START_TIME": "2026-09-24 09:58:00",
    }
    session = {
        "SID": 101, "SERIAL_NUM": 5, "USERNAME": "HCC", "ELAPSED_SECONDS": 120,
        "SQL_TEXT": "ALTER TABLE SALES.ORDERS MOVE COMPRESS FOR QUERY HIGH",
        "PCT_COMPLETE": 45.0, "REMAINING_MINUTES": 2.5, "WAIT_CLASS": "User I/O",
        "EVENT": "db file scattered read", "OPNAME": "Table Move",
    }
    return [
        (TargetQueries, "get_session_longops",
         rec.source("session_longops", pd.DataFrame([longop]))),
        (TargetQueries, "get_all_active_longops",
         rec.source("all_active_longops", pd.DataFrame([longop]))),
        (TargetQueries, "get_compression_sessions",
         rec.source("compression_sessions", pd.DataFrame([session]))),
    ]


def _page_07_app():
    at = AppTest.from_string(PAGE_07_SCRIPT, default_timeout=TIMEOUT)
    at.session_state["active_database_id"] = 1
    return at


class TestSessionsPageAutoRefresh:

    def test_off_renders_without_waiting(self, rec):
        with ExitStack() as stack:
            _patch_all(stack, _page_07_sources(rec))
            spy = _spy_helper(stack, page_07_sessions)
            at = _page_07_app().run()

        assert not at.exception
        assert len(at.tabs) == 3
        spy.assert_called_once()
        assert spy.call_args.args[0] == "session_auto_refresh"
        rec.time.sleep.assert_not_called()
        rec.rerun.assert_not_called()

    def test_on_renders_tabs_then_waits_chosen_interval(self, rec):
        with ExitStack() as stack:
            _patch_all(stack, _page_07_sources(rec))
            spy = _spy_helper(stack, page_07_sessions)
            at = _page_07_app().run()
            normal_render_queries = sorted(rec.queries())

            at.checkbox(key="session_auto_refresh").check().run()  # interval defaults to 5
            assert rec.slept == 5
            at.selectbox(key="session_refresh_interval").select_index(1)  # 10 seconds
            rec.reset()
            spy.reset_mock()
            at.run()

        assert not at.exception
        # The tabs and their content are in the tree (previously the page
        # reran every 0.1 s before the tabs were ever rendered).
        assert len(at.tabs) == 3
        labels = _metric_labels(at)
        for label in ("Active Operations", "Active Compression Sessions", "Rate"):
            assert label in labels
        assert len(at.dataframe) >= 2
        # One wait of the chosen interval, then one rerun.
        spy.assert_called_once_with("session_auto_refresh", 10)
        assert rec.slept == 10
        rec.rerun.assert_called_once_with()
        rec.assert_rendered_before_waiting()
        # A refresh cycle queries the target exactly as often as a normal render.
        assert sorted(rec.queries()) == normal_render_queries == [
            "all_active_longops", "compression_sessions", "session_longops",
        ]

    def test_no_target_selected_never_waits(self, rec):
        with ExitStack() as stack:
            _patch_all(stack, _page_07_sources(rec))
            spy = _spy_helper(stack, page_07_sessions)
            at = AppTest.from_string(PAGE_07_SCRIPT, default_timeout=TIMEOUT)
            at.session_state["session_auto_refresh"] = True  # left on from earlier
            at.run()

        assert not at.exception
        spy.assert_not_called()  # the page returns before the toggle is shown
        rec.time.sleep.assert_not_called()
        rec.rerun.assert_not_called()


# ============================================================================
# Scheduler (page_12)
# ============================================================================

PAGE_12_SCRIPT = """
from hcc_advisor.views.page_12_scheduler import show_scheduler_page
show_scheduler_page()
"""


def _page_12_sources(rec):
    summary = {"total": 3, "queued": 1, "running": 1, "succeeded": 1, "failed": 0}
    details = pd.DataFrame([{
        "JOB_NAME": "HCC_JOB_1", "OWNER": "SALES", "OBJECT_NAME": "ORDERS",
        "STATUS": "IN_PROGRESS",
    }])
    do_refresh = MagicMock(name="_do_refresh",
                           side_effect=lambda db_id: rec.events.append(("query", "do_refresh")))
    return [
        (CentralQueries, "get_scheduler_job_summary", rec.source("job_summary", summary)),
        (CentralQueries, "get_scheduler_job_details", rec.source("job_details", details)),
        (page_12_scheduler, "_do_refresh", do_refresh),
        # Export / import / recurring-job expanders are out of scope here.
        (page_12_scheduler, "_render_export_section", MagicMock()),
        (page_12_scheduler, "_render_import_section", MagicMock()),
        (page_12_scheduler, "_render_recurring_jobs", MagicMock()),
    ]


def _page_12_app(auto_refresh):
    at = AppTest.from_string(PAGE_12_SCRIPT, default_timeout=TIMEOUT)
    at.session_state["authenticated"] = True
    at.session_state["active_database_id"] = 1
    at.session_state["scheduler_pending_queue"] = []  # skip the queue reload
    at.session_state["scheduler_auto_refresh"] = auto_refresh
    return at


def _assert_no_meta_refresh(at):
    for text in _texts(at.markdown):
        assert "http-equiv" not in text.lower()


class TestSchedulerPageAutoRefresh:

    def test_off_renders_without_waiting(self, rec):
        with ExitStack() as stack:
            mocks = _patch_all(stack, _page_12_sources(rec))
            spy = _spy_helper(stack, page_12_scheduler)
            at = _page_12_app(auto_refresh=False).run()

        assert not at.exception
        _assert_no_meta_refresh(at)
        spy.assert_called_once_with("scheduler_auto_refresh", 300)
        mocks["_do_refresh"].assert_not_called()
        rec.time.sleep.assert_not_called()
        rec.rerun.assert_not_called()

    def test_on_reruns_in_session_instead_of_meta_refresh(self, rec):
        with ExitStack() as stack:
            mocks = _patch_all(stack, _page_12_sources(rec))
            spy = _spy_helper(stack, page_12_scheduler)
            at = _page_12_app(auto_refresh=True).run()
            assert rec.slept == 300  # default interval: 5 min
            at.selectbox(key="sched_interval").select_index(1)  # 2 min
            rec.reset()
            spy.reset_mock()
            mocks["_do_refresh"].reset_mock()
            at.run()

        assert not at.exception
        _assert_no_meta_refresh(at)
        # Page content first...
        labels = _metric_labels(at)
        for label in ("Total (24h)", "Queued", "Running", "Succeeded", "Failed"):
            assert label in labels
        assert len(at.dataframe) == 1
        assert any(c.startswith("Last refresh:") for c in _texts(at.caption))
        mocks["_do_refresh"].assert_called_once_with(1)
        # ...then one wait of the chosen interval and an in-session rerun.
        spy.assert_called_once_with("scheduler_auto_refresh", 120)
        assert rec.slept == 120
        rec.rerun.assert_called_once_with()
        rec.assert_rendered_before_waiting()
        # Session state (login, toggle) is kept: no new browser session.
        assert at.session_state["authenticated"] is True
        assert at.session_state["scheduler_auto_refresh"] is True

    def test_stop_button_turns_waiting_off(self, rec):
        with ExitStack() as stack:
            _patch_all(stack, _page_12_sources(rec))
            at = _page_12_app(auto_refresh=True).run()
            rec.reset()
            # AppTest 1.31 cannot re-serialize an untouched selectbox that has
            # a format_func, so set the interval explicitly (5 min).
            at.selectbox(key="sched_interval").select_index(2)
            at.button(key="sched_stop").click().run()

        assert not at.exception
        assert at.session_state["scheduler_auto_refresh"] is False
        rec.time.sleep.assert_not_called()
