"""
Shared data and harness for the page tests (test_page_smoke.py,
test_page_actions.py): render a view page's entry function under
``streamlit.testing.v1.AppTest`` for a logged-in role, with the central and
target connectors routed to empty fakes (tests/unit/db_fakes.py) and
st.rerun / the auto-refresh clock mocked. Not a test module itself.

The ``env`` fixture fails a test at teardown if any statement the page ran had
binds that did not match its placeholders.
"""
from unittest.mock import MagicMock

import pandas as pd
import pytest
import streamlit as st
from streamlit.testing.v1 import AppTest
from streamlit.testing.v1.element_tree import Selectbox

from hcc_advisor import __version__
from hcc_advisor.auth import ROLE_ADMIN, ROLE_VIEWER
from hcc_advisor.utils import ui_refresh
from hcc_advisor.utils.central_queries import CentralQueries
from hcc_advisor.utils.sql_patches import PatchScan

from tests.unit.app_harness import _selectbox_index
from tests.unit.db_fakes import SqlRouter, df, install_central, install_target

TIMEOUT = 20  # seconds per AppTest run (the first run imports plotly & co)
DB = 1


# ============================================================================
# Data
# ============================================================================

TARGETS = df([{
    'DATABASE_ID': DB, 'DATABASE_NAME': 'PROD', 'DISPLAY_NAME': 'Prod', 'DB_HOST': 'db1',
    'PORT': 1521, 'SERVICE_NAME': 'PDB1', 'USERNAME': 'HCC', 'ENVIRONMENT': 'PRODUCTION',
    'PLATFORM_TYPE': 'EXADATA', 'ORACLE_VERSION': '19.0.0', 'CONNECTION_MODE': 'NORMAL',
    'IS_ACTIVE': 'Y', 'LAST_CONNECTED': None, 'DESCRIPTION': 'main', 'PASSWORD_ENCRYPTED': None,
}])

TARGET_INFO = {
    'database_id': DB, 'database_name': 'PROD', 'display_name': 'Prod', 'db_host': 'db1',
    'host': 'db1', 'port': 1521, 'service_name': 'PDB1', 'service': 'PDB1', 'username': 'HCC',
    'platform_type': 'EXADATA', 'oracle_version': '19.0.0',
}

_REC_COLUMNS = [
    'RECOMMENDATION_ID', 'DATABASE_ID', 'TABLE_OWNER', 'TABLE_NAME', 'OBJECT_TYPE',
    'PARTITION_NAME', 'SUBPARTITION_NAME', 'ORIGINAL_SIZE_MB', 'CURRENT_SIZE_MB',
    'ESTIMATED_ROWS', 'CURRENT_COMPRESSION', 'RECOMMENDED_STRATEGY', 'ESTIMATED_SIZE_MB',
    'SAVINGS_PCT', 'COMPRESSION_RATIO', 'BASIC_RATIO', 'OLTP_RATIO', 'QUERY_LOW_RATIO',
    'QUERY_HIGH_RATIO', 'HOTNESS_SCORE', 'HOTNESS_CATEGORY', 'RECOMMENDATION_REASON',
    'ANALYSIS_TIMESTAMP', 'EXECUTION_STATUS',
]
_TS = pd.Timestamp('2026-09-20 10:00')
RECS = df([
    [101, DB, 'APP', 'ORDERS', 'TABLE', None, None, 512.0, 512.0, 100000, 'NONE', 'QUERY HIGH',
     128.0, 75.0, 4.0, 1.5, 2.0, 3.0, 4.0, 12.0, 'COLD', 'cold table', _TS, 'Pending'],
    [102, DB, 'APP', 'SALES', 'PARTITION', 'P1', None, 256.0, 256.0, 5000, 'NONE', 'OLTP',
     128.0, 50.0, 2.0, None, 2.0, None, None, 55.0, 'WARM', 'warm partition', _TS, 'Compressed'],
    [103, DB, 'APP', 'SALES', 'SUBPARTITION', 'P2', 'SP1', 64.0, 64.0, 800, 'NONE',
     'ARCHIVE HIGH', 8.0, 87.5, 8.0, None, None, None, None, 3.0, 'COLD', 'idle', _TS, 'FAILED'],
    [104, DB, 'HR', 'EMP', 'TABLE', None, None, 10.0, 10.0, 100, 'NONE', 'NONE', 10.0, 0.0, 1.0,
     None, None, None, None, 95.0, 'HOT', 'very hot', _TS, 'Pending'],
], columns=_REC_COLUMNS)

ANALYSIS_DETAILS = {
    'OWNER': 'APP', 'OBJECT_NAME': 'ORDERS', 'DATABASE_ID': DB, 'SIZE_MB': 512.0,
    'SIZE_BYTES': 512 * 1048576, 'ROW_COUNT': 100000, 'CURRENT_COMPRESSION': 'NONE',
    'ADVISABLE_COMPRESSION': 'QUERY HIGH', 'PROJECTED_SAVINGS_PCT': 75.0, 'CONFIDENCE_SCORE': 80,
    'RECOMMENDATION_REASON': 'cold table', 'BASIC_RATIO': 1.5, 'BLKCNT_UNCMP_BASIC': 1000,
    'BLKCNT_CMP_BASIC': 660, 'OLTP_RATIO': 2.0, 'ADV_HIGH_RATIO': 4.0, 'BEST_RATIO': 4.0,
    'INSERT_COUNT': 10, 'UPDATE_COUNT': 2, 'DELETE_COUNT': 0, 'TOTAL_DML': 12,
    'LOGICAL_READS': 5000, 'PHYSICAL_READS': 40, 'HOTNESS_SCORE': 80.0,
    'HOTNESS_CATEGORY': 'HOT', 'READ_RATIO': 0.9, 'WRITE_RATIO': 0.1, 'TABLESPACE_NAME': None,
    'BLOCK_COUNT': 65536, 'AVG_ROW_LENGTH': 120,
}

INDEX_ANALYSIS = df([{
    'INDEX_NAME': 'ORDERS_PK', 'INDEX_TYPE': 'NORMAL', 'CURRENT_COMPRESSION': 'NONE',
    'ADVISABLE_COMPRESSION': 'ADVANCED LOW', 'PROJECTED_SAVINGS_MB': 12.0,
    'PREFIX_COMPRESSION_RATIO': 1.4, 'ADVANCED_LOW_RATIO': 2.0, 'ADVANCED_HIGH_RATIO': None,
    'RECOMMENDATION_REASON': 'repetitive keys'}])

LOB_ANALYSIS = df([{
    'COLUMN_NAME': 'DOC', 'DATA_TYPE': 'CLOB', 'SECUREFILE': 'NO', 'CURRENT_COMPRESSION': 'NONE',
    'ADVISABLE_COMPRESSION': 'MEDIUM', 'PROJECTED_SAVINGS_MB': 40.0, 'LOB_SIZE_MB': 100.0,
    'NUM_LOBS': 2000, 'AVG_LOB_SIZE_KB': 50.0, 'DEDUP_SAVINGS_PCT': 10.0,
    'LOW_COMPRESSION_RATIO': 1.5, 'MEDIUM_COMPRESSION_RATIO': 2.0, 'HIGH_COMPRESSION_RATIO': None,
    'RECOMMENDATION_REASON': 'text documents', 'RECOMMEND_SECUREFILE': 'Y'}])

COLUMN_INFO = df([
    {'COLUMN_NAME': 'ID', 'DATA_TYPE': 'NUMBER', 'DATA_LENGTH': 22, 'NULLABLE': 'N',
     'NUM_DISTINCT': 100000, 'NUM_NULLS': 0, 'AVG_COL_LEN': 5, 'HISTOGRAM': 'NONE',
     'COMPRESSION_HINT': 'Numeric - Moderate compression'},
    {'COLUMN_NAME': 'NOTE', 'DATA_TYPE': 'VARCHAR2', 'DATA_LENGTH': 400, 'NULLABLE': 'Y',
     'NUM_DISTINCT': 30, 'NUM_NULLS': 900, 'AVG_COL_LEN': 80, 'HISTOGRAM': 'FREQUENCY',
     'COMPRESSION_HINT': 'Text - Good for HCC'}])

STRATEGIES = df([
    {'STRATEGY_ID': 1, 'STRATEGY_NAME': 'Aggressive', 'DESCRIPTION': 'max', 'CATEGORY': 'SPACE',
     'HOTNESS_THRESHOLD_HOT': 80, 'HOTNESS_THRESHOLD_WARM': 60, 'HOTNESS_THRESHOLD_COOL': 30,
     'DML_THRESHOLD_HIGH': 10000, 'DML_THRESHOLD_MEDIUM': 1000, 'DML_THRESHOLD_LOW': 100,
     'SIZE_THRESHOLD_LARGE_GB': 50, 'SIZE_THRESHOLD_MEDIUM_GB': 10, 'SIZE_THRESHOLD_SMALL_GB': 1,
     'AGE_THRESHOLD_RECENT_DAYS': 30, 'AGE_THRESHOLD_OLD_DAYS': 90,
     'AGE_THRESHOLD_ARCHIVE_DAYS': 180, 'MIN_COMPRESSION_RATIO': 2.0,
     'MIN_SPACE_SAVINGS_MB': 100, 'ACTIVE_FLAG': 'Y', 'IS_DEFAULT': None, 'PRIORITY': 60},
    {'STRATEGY_ID': 2, 'STRATEGY_NAME': 'Balanced', 'DESCRIPTION': 'default',
     'CATEGORY': 'BALANCED', 'HOTNESS_THRESHOLD_HOT': 75, 'HOTNESS_THRESHOLD_WARM': 50,
     'HOTNESS_THRESHOLD_COOL': 25, 'DML_THRESHOLD_HIGH': 10000, 'DML_THRESHOLD_MEDIUM': 1000,
     'DML_THRESHOLD_LOW': 100, 'SIZE_THRESHOLD_LARGE_GB': 50, 'SIZE_THRESHOLD_MEDIUM_GB': 10,
     'SIZE_THRESHOLD_SMALL_GB': 1, 'AGE_THRESHOLD_RECENT_DAYS': 30, 'AGE_THRESHOLD_OLD_DAYS': 90,
     'AGE_THRESHOLD_ARCHIVE_DAYS': 180, 'MIN_COMPRESSION_RATIO': 1.5,
     'MIN_SPACE_SAVINGS_MB': 100, 'ACTIVE_FLAG': 'Y', 'IS_DEFAULT': 'Y', 'PRIORITY': 50},
])

RULES = df([{'RULE_ID': 7, 'STRATEGY_ID': 2, 'STRATEGY_NAME': 'Balanced', 'OBJECT_TYPE': 'TABLE',
             'HOTNESS_MIN': 0, 'HOTNESS_MAX': 30, 'DML_RATIO_THRESHOLD': 0.5,
             'COMPRESSION_TYPE': 'QUERY HIGH', 'PRIORITY': 50, 'ENABLED_FLAG': 'Y',
             'RULE_DESCRIPTION': 'cold tables'}])

SAVINGS_BY_STRATEGY = df([{'STRATEGY': 'QUERY HIGH', 'TABLE_COUNT': 3, 'AVG_SAVINGS_PCT': 70.0,
                           'AVG_COMPRESSION_RATIO': 3.5, 'TOTAL_SIZE_GB': 2.0,
                           'TOTAL_SAVINGS_GB': 1.4}])

HISTORY = df([
    {'EXECUTION_ID': 11, 'DATABASE_ID': DB, 'TABLE_OWNER': 'APP', 'TABLE_NAME': 'ORDERS',
     'OBJECT_TYPE': 'TABLE', 'PARTITION_NAME': None, 'SUBPARTITION_NAME': None,
     'STRATEGY': 'QUERY HIGH', 'ORIGINAL_SIZE_MB': 512.0, 'FINAL_SIZE_MB': 128.0,
     'SAVINGS_MB': 384.0, 'SAVINGS_PCT': 75.0, 'STATUS': 'SUCCESS', 'ROLLBACK_STATUS': None,
     'EXECUTED_AT': pd.Timestamp('2026-09-21 10:00'), 'END_TIME': pd.Timestamp('2026-09-21 10:05'),
     'ERROR_MESSAGE': None},
    {'EXECUTION_ID': 12, 'DATABASE_ID': DB, 'TABLE_OWNER': 'APP', 'TABLE_NAME': 'SALES',
     'OBJECT_TYPE': 'PARTITION', 'PARTITION_NAME': 'P1', 'SUBPARTITION_NAME': None,
     'STRATEGY': 'OLTP', 'ORIGINAL_SIZE_MB': 256.0, 'FINAL_SIZE_MB': None, 'SAVINGS_MB': None,
     'SAVINGS_PCT': None, 'STATUS': 'FAILED', 'ROLLBACK_STATUS': None,
     'EXECUTED_AT': pd.Timestamp('2026-09-22 10:00'), 'END_TIME': None,
     'ERROR_MESSAGE': 'ORA-01652: unable to extend temp segment'},
])

SCHEDULER_JOBS = df([
    {'OWNER': 'APP', 'TABLE_NAME': 'ORDERS', 'OBJECT_TYPE': 'TABLE', 'PARTITION_NAME': None,
     'STRATEGY': 'QUERY HIGH', 'JOB_NAME': 'HCC_ORDERS_1', 'STATUS': 'IN_PROGRESS', 'DOP': 4,
     'STARTED': '2026-09-24 08:00:00', 'DURATION_MIN': 3.0, 'ORIGINAL_MB': 512.0,
     'COMPRESSED_MB': None, 'SAVED_MB': 0.0, 'ERROR_MESSAGE': None},
    {'OWNER': 'APP', 'TABLE_NAME': 'SALES', 'OBJECT_TYPE': 'PARTITION', 'PARTITION_NAME': 'P1',
     'STRATEGY': 'OLTP', 'JOB_NAME': 'HCC_SALES_2', 'STATUS': 'FAILED', 'DOP': 2,
     'STARTED': '2026-09-24 07:00:00', 'DURATION_MIN': 1.0, 'ORIGINAL_MB': 256.0,
     'COMPRESSED_MB': None, 'SAVED_MB': 0.0, 'ERROR_MESSAGE': 'ORA-01652'},
])

EXPORT_JOBS = df([
    {'DATABASE_NAME': 'PROD', 'DATABASE_DISPLAY': 'Prod', 'DATABASE_ID': DB, 'OWNER': 'APP',
     'OBJECT_NAME': 'ORDERS', 'OBJECT_TYPE': 'TABLE', 'PARTITION_NAME': None,
     'SUBPARTITION_NAME': None, 'COMPRESSION_TYPE_APPLIED': 'QUERY HIGH', 'PARALLEL_DEGREE': 4,
     'OPERATION_STATUS': 'QUEUED', 'START_TIME': '2026-09-24 08:00:00', 'ERROR_MESSAGE': None},
    {'DATABASE_NAME': 'PROD', 'DATABASE_DISPLAY': 'Prod', 'DATABASE_ID': DB, 'OWNER': 'APP',
     'OBJECT_NAME': 'SALES', 'OBJECT_TYPE': 'SUBPARTITION', 'PARTITION_NAME': 'P2',
     'SUBPARTITION_NAME': 'SP1', 'COMPRESSION_TYPE_APPLIED': 'ARCHIVE HIGH',
     'PARALLEL_DEGREE': 2, 'OPERATION_STATUS': 'FAILED', 'START_TIME': '2026-09-24 07:00:00',
     'ERROR_MESSAGE': 'ORA-01652'},
])


# ============================================================================
# Harness
# ============================================================================

class Env:
    """Fake data sources for one test: connector routers plus query patches."""

    def __init__(self, monkeypatch, target, central):
        self.monkeypatch = monkeypatch
        self.target = target
        self.central = central
        self.targets = TARGETS

    def returns(self, owner, name, value):
        """Patch owner.name to return a fresh copy of `value` on every call."""
        def _fn(*args, **kwargs):
            return value.copy() if hasattr(value, 'copy') else value
        mock = MagicMock(name=name, side_effect=_fn)
        self.monkeypatch.setattr(owner, name, mock)
        return mock

    def patch(self, owner, name, value):
        self.monkeypatch.setattr(owner, name, value)
        return value


@pytest.fixture(name='env')
def env_fixture(monkeypatch):
    """The ``env`` fixture: an Env whose routers back every connector call.
    Test modules import ``env_fixture`` (pytest registers it as ``env``)."""
    target = install_target(monkeypatch, SqlRouter('target'))
    central = install_central(monkeypatch, SqlRouter('central'))
    e = Env(monkeypatch, target, central)
    monkeypatch.setattr(CentralQueries, 'get_target_databases',
                        staticmethod(lambda: e.targets.copy()))
    monkeypatch.setattr(CentralQueries, 'get_target_database',
                        staticmethod(lambda database_id: dict(TARGET_INFO)))
    e.rerun = MagicMock(name='st.rerun')
    monkeypatch.setattr(st, 'rerun', e.rerun)
    monkeypatch.setattr(ui_refresh, 'time', MagicMock(name='ui_refresh.time'))
    # AppTest 1.31 sends a format_func'd selectbox back by its label (see app_harness)
    monkeypatch.setattr(Selectbox, 'index', property(_selectbox_index))
    yield e
    errors = target.bind_errors + central.bind_errors
    assert not errors, "\n\n".join(errors)


def page(module: str, func: str, role: str = ROLE_ADMIN, db_id=DB, args: str = '', **state) -> AppTest:
    """AppTest running hcc_advisor.views.<module>.<func>(<args>) for a logged-in `role`."""
    script = f"from hcc_advisor.views import {module}\n{module}.{func}({args})\n"
    at = AppTest.from_string(script, default_timeout=TIMEOUT)
    at.session_state['authenticated'] = True
    at.session_state['role'] = role
    at.session_state['username'] = role
    if db_id is not None:
        at.session_state['active_database_id'] = db_id
    for key, value in state.items():
        at.session_state[key] = value
    return at


def ok(at: AppTest) -> AppTest:
    """Assert the run raised nothing; returns the AppTest for chaining."""
    assert not at.exception, [e.value for e in at.exception]
    return at


def texts(at: AppTest) -> str:
    """Every visible text of the common element types, joined."""
    parts = []
    for kind in ('title', 'header', 'subheader', 'markdown', 'caption', 'info', 'warning',
                 'error', 'success', 'text', 'code'):
        parts.extend(str(e.value) for e in getattr(at, kind))
    parts.extend(f"{m.label} {m.value}" for m in at.metric)
    return "\n".join(parts)


def button(at: AppTest, label: str):
    """The single button labelled `label`."""
    found = [b for b in at.button if b.label == label]
    assert len(found) == 1, [b.label for b in at.button]
    return found[0]


ROLES = [ROLE_ADMIN, ROLE_VIEWER]


INDEXES = df([
    {'INDEX_OWNER': 'APP', 'INDEX_NAME': 'ORDERS_PK', 'TABLE_OWNER': 'APP',
     'TABLE_NAME': 'ORDERS', 'INDEX_TYPE': 'NORMAL', 'STATUS': 'UNUSABLE', 'SIZE_MB': 12.0,
     'PARTITIONED': 'NO'},
    {'INDEX_OWNER': 'APP', 'INDEX_NAME': 'SALES_IX', 'TABLE_OWNER': 'APP',
     'TABLE_NAME': 'SALES', 'INDEX_TYPE': 'NORMAL', 'STATUS': 'N/A', 'SIZE_MB': 30.0,
     'PARTITIONED': 'YES'},
])


def patch_scan(patch_dirs):
    """Admin > SQL Patches scan: 1st patch applied, 2nd failed, 3rd detected
    by its check.sql, the rest pending."""
    names = [d.name for d in patch_dirs]
    return PatchScan(
        patch_dirs=list(patch_dirs),
        recorded={names[0]: {'status': 'SUCCESS', 'date': '2026-09-01', 'by': 'ADMIN'},
                  names[1]: {'status': 'FAILED', 'date': '2026-09-02', 'by': 'ADMIN'}},
        detected={names[2]: True}, has_history_table=True, auto_marked=1)


def schema_state(**overrides):
    """page_00_setup._get_schema_state result: a current, complete schema."""
    state = {'connected': True, 'tables_found': 9, 'total_tables': 9, 'deployed': True,
             'version': __version__, 'installed_at': '2026-01-01', 'banner': 'Oracle 23ai'}
    state.update(overrides)
    return state
