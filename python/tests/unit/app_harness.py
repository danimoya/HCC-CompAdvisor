"""
Run the real ``hcc_advisor/app.py`` under ``streamlit.testing.v1.AppTest``
with the central database, the login and the sidebar menu mocked, so tests can
check what the app shell does around a page (log viewer, SQL Debug Console,
deferred auto-refresh). Not a test module itself.
"""
from contextlib import ExitStack, contextmanager
from pathlib import Path
from unittest.mock import MagicMock, patch

import pandas as pd
import streamlit_option_menu
from streamlit.testing.v1 import AppTest
from streamlit.testing.v1.element_tree import Selectbox

import hcc_advisor
from hcc_advisor import auth
from hcc_advisor.auth import AuthManager
from hcc_advisor.config import Config
from hcc_advisor.utils.central_connector import CentralConnector
from hcc_advisor.utils.central_queries import CentralQueries

APP_PATH = str(Path(hcc_advisor.__file__).parent / "app.py")
TIMEOUT = 30  # seconds per AppTest run; app.py imports a lot on its first run


def _target_databases(*args, **kwargs):
    return pd.DataFrame([{"DATABASE_ID": 1, "DATABASE_NAME": "DB1", "DISPLAY_NAME": "DB1"}])


_SELECTBOX_INDEX = Selectbox.index


def _selectbox_index(self):
    """AppTest (1.31) sends a selectbox back by looking str(value) up in the
    displayed options, which fails for a format_func'd selectbox such as the
    sidebar target selector (options are database ids, labels are names).
    A selection the test made (select / select_index) still goes that way; an
    untouched one keeps the index the app rendered it with (its default)."""
    try:
        return _SELECTBOX_INDEX.fget(self)
    except ValueError:
        return self.proto.default


def _overview_sources():
    """Empty results for every query show_dashboard (Overview) runs."""
    return [
        (CentralQueries, "get_dashboard_summary", MagicMock(return_value={})),
        (CentralQueries, "get_compression_progress", MagicMock(return_value={})),
        (CentralQueries, "get_savings_timeline", MagicMock(return_value=pd.DataFrame())),
        (CentralQueries, "get_forecast_data", MagicMock(return_value={"pending_count": 0})),
        (CentralQueries, "get_savings_by_strategy", MagicMock(return_value=pd.DataFrame())),
        (CentralQueries, "get_recent_executions", MagicMock(return_value=pd.DataFrame())),
        (CentralQueries, "get_growth_alerts", MagicMock(return_value=pd.DataFrame())),
    ]


@contextmanager
def app_shell(page: str, extra=()):
    """Patch what app.py needs to render `page` (a sidebar menu label).

    `extra` is more (obj, attr, value) patches, applied last.
    """
    targets = [
        (Config, "is_first_run", MagicMock(return_value=False)),
        (AuthManager, "require_authentication", MagicMock()),
        (auth, "render_logout_button", MagicMock()),
        (CentralConnector, "initialize_pool", MagicMock()),
        (CentralConnector, "test_connection", MagicMock(return_value=True)),
        (CentralQueries, "get_target_databases", MagicMock(side_effect=_target_databases)),
        (streamlit_option_menu, "option_menu", MagicMock(return_value=page)),
        (Selectbox, "index", property(_selectbox_index)),
        *_overview_sources(),
        *extra,
    ]
    with ExitStack() as stack:
        for obj, attr, value in targets:
            stack.enter_context(patch.object(obj, attr, value))
        yield


def new_app(role: str = "admin") -> AppTest:
    """An AppTest of app.py for a logged-in session with the given role."""
    at = AppTest.from_file(APP_PATH, default_timeout=TIMEOUT)
    at.session_state["authenticated"] = True
    at.session_state["role"] = role
    at.session_state["username"] = role
    at.session_state["schema_check_passed"] = True  # skip the schema DB check
    at.session_state["active_database_id"] = 1
    return at
