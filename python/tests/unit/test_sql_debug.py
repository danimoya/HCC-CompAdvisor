"""
Unit tests for the SQL debug console log (hcc_advisor.utils.sql_debug):
entries are captured per session with secrets redacted, listed newest first,
capped at MAX_SQL_LOG_ENTRIES and clearable. The redaction rules themselves
are covered by test_logging.
"""
from types import SimpleNamespace

import pytest

from hcc_advisor.utils import sql_debug


class _Session(dict):
    def __getattr__(self, name):
        try:
            return self[name]
        except KeyError:
            raise AttributeError(name)

    def __setattr__(self, name, value):
        self[name] = value


@pytest.fixture
def session(monkeypatch):
    state = _Session()
    monkeypatch.setattr(sql_debug, 'st', SimpleNamespace(session_state=state))
    return state


@pytest.mark.unit
class TestSqlDebugLog:

    def test_capture_records_the_statement(self, session):
        sql_debug.capture_sql('target(id=1)', 'SELECT', '  SELECT * FROM t WHERE a = :a  ',
                              {'a': 1}, rows_affected=3, duration_ms=12.345)
        (entry,) = sql_debug.get_sql_log()
        assert entry['database'] == 'target(id=1)'
        assert entry['operation'] == 'SELECT'
        assert entry['sql'] == 'SELECT * FROM t WHERE a = :a'
        assert entry['params'] == {'a': 1}
        assert entry['rows'] == 3
        assert entry['duration_ms'] == 12.3
        assert entry['status'] == 'OK' and entry['error'] is None
        assert len(entry['timestamp']) == len('12:34:56.789')

    def test_secrets_are_not_kept(self, session):
        sql_debug.capture_sql('central', 'DML', 'UPDATE t SET pw = :password',
                              {'password': 'hunter2-secret', 'owner': 'APP'})
        entry = sql_debug.get_sql_log()[0]
        assert 'hunter2-secret' not in str(entry)
        assert entry['params']['owner'] == 'APP'

    def test_errors_are_recorded(self, session):
        sql_debug.capture_sql('central', 'PLSQL', 'BEGIN x; END;', status='ERROR',
                              error='ORA-06550', duration_ms=0)
        entry = sql_debug.get_sql_log()[0]
        assert (entry['status'], entry['error'], entry['duration_ms']) == ('ERROR', 'ORA-06550', None)

    def test_newest_first_and_capped(self, session):
        total = sql_debug.MAX_SQL_LOG_ENTRIES + 5
        for i in range(total):
            sql_debug.capture_sql('central', 'SELECT', f'SELECT {i} FROM dual')
        log = sql_debug.get_sql_log()
        assert len(log) == sql_debug.MAX_SQL_LOG_ENTRIES
        assert log[0]['sql'] == f'SELECT {total - 1} FROM dual'
        assert log[-1]['sql'] == 'SELECT 5 FROM dual'

    def test_clear_and_empty_log(self, session):
        assert sql_debug.get_sql_log() == []
        sql_debug.capture_sql('central', 'SELECT', 'SELECT 1 FROM dual')
        sql_debug.clear_sql_log()
        assert sql_debug.get_sql_log() == []

    def test_debug_flag(self, session):
        assert sql_debug.is_debug_enabled() is False
        session['sql_debug_enabled'] = True
        assert sql_debug.is_debug_enabled() is True

    def test_non_json_values_are_shown_as_repr(self):
        class Lob:
            def __repr__(self):
                return '<LOB>'
        assert sql_debug._sanitize_params({'doc': Lob()}) == {'doc': '<LOB>'}
        assert sql_debug._sanitize_params('scalar') == 'scalar'
