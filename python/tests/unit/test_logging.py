"""
Unit tests for the application log (utils/logger.py), the shared secret
redaction (utils/redaction.py) and the Overview page's log viewer (app.py):

- the file handler rotates by size (LOG_MAX_MB / LOG_BACKUP_COUNT) and logs
  at LOG_LEVEL (INFO by default, DEBUG opt-in),
- "Clear Logs" empties the file in place, so logging goes on at once,
- the viewer reads only the tail of the log, and only when it is switched on,
- every logger path that writes params / context masks secrets, including
  target registration's ``password_encrypted``.

Every test that writes logs uses the ``tmp_log`` fixture (a file under
pytest's tmp_path); tests/conftest.py also points the module's own log
directory at a temporary directory, never the real log path.
"""
import logging
import os
from collections import namedtuple
from logging.handlers import RotatingFileHandler
from unittest.mock import MagicMock, patch

import oracledb
import pytest
import streamlit as st

from hcc_advisor.utils import central_connector as cc_module
from hcc_advisor.utils import logger
from hcc_advisor.utils import sql_debug
from hcc_advisor.utils.central_connector import CentralConnector
from hcc_advisor.utils.central_queries import CentralQueries
from hcc_advisor.utils.redaction import REDACTED, is_sensitive_key, redact

from tests.unit.app_harness import app_shell, new_app

SECRET = "S3cr3t-Value"


@pytest.fixture
def tmp_log(tmp_path, monkeypatch):
    """Point app_logger (and the module's LOG_DIR / LOG_FILE) at tmp_path.

    The logger's own handlers are detached for the test and restored after.
    Yields the log file path.
    """
    log_file = tmp_path / "hcc_advisor.log"
    monkeypatch.setattr(logger, "LOG_DIR", tmp_path)
    monkeypatch.setattr(logger, "LOG_FILE", log_file)
    app = logger.app_logger
    saved_handlers, saved_level = app.handlers[:], app.level
    for handler in saved_handlers:
        app.removeHandler(handler)
    handler = logger._make_file_handler(log_file, 1024 * 1024, 3)
    app.addHandler(handler)
    app.setLevel(logging.INFO)
    try:
        yield log_file
    finally:
        for h in app.handlers[:]:
            app.removeHandler(h)
            h.close()
        for h in saved_handlers:
            app.addHandler(h)
        app.setLevel(saved_level)


def _read(path) -> str:
    return path.read_text(encoding="utf-8") if path.exists() else ""


# ============================================================================
# Configuration: rotation and level
# ============================================================================

class TestLoggerConfiguration:

    def test_tests_never_log_to_the_real_log_dir(self):
        assert str(logger.LOG_DIR) == os.environ["HCC_ADVISOR_LOG_DIR"]

    def test_file_handler_rotates_with_configured_limits(self):
        handler = logger._file_handler()
        assert isinstance(handler, RotatingFileHandler)
        assert handler.baseFilename == os.path.abspath(logger.LOG_FILE)
        assert handler.maxBytes == logger.LOG_MAX_BYTES > 0
        assert handler.backupCount == logger.LOG_BACKUP_COUNT >= 1
        assert handler.level == logger.LOG_LEVEL

    def test_defaults_are_10mb_times_5_at_info(self, monkeypatch):
        for name in ("LOG_MAX_MB", "LOG_BACKUP_COUNT", "LOG_LEVEL"):
            monkeypatch.delenv(name, raising=False)
        assert logger._env_number("LOG_MAX_MB", 10.0, 1.0) == 10.0
        assert logger._env_number("LOG_BACKUP_COUNT", 5, 1) == 5
        assert logger._env_level() == logging.INFO

    @pytest.mark.parametrize("raw, expected", [
        ("25", 25.0), ("2.5", 2.5), ("0", 1.0), ("-3", 1.0),
        ("abc", 10.0), ("inf", 10.0), ("nan", 10.0), ("", 10.0),
    ])
    def test_max_mb_from_env(self, monkeypatch, raw, expected):
        monkeypatch.setenv("LOG_MAX_MB", raw)
        assert logger._env_number("LOG_MAX_MB", 10.0, 1.0) == expected

    @pytest.mark.parametrize("raw, expected", [("3", 3), ("0", 1), ("x", 5), ("7.9", 7)])
    def test_backup_count_from_env(self, monkeypatch, raw, expected):
        monkeypatch.setenv("LOG_BACKUP_COUNT", raw)
        assert logger._env_number("LOG_BACKUP_COUNT", 5, 1) == expected

    @pytest.mark.parametrize("raw, expected", [
        ("DEBUG", logging.DEBUG), ("debug", logging.DEBUG), (" warning ", logging.WARNING),
        ("ERROR", logging.ERROR), ("TRACE", logging.INFO), ("", logging.INFO),
    ])
    def test_level_from_env(self, monkeypatch, raw, expected):
        monkeypatch.setenv("LOG_LEVEL", raw)
        assert logger._env_level() == expected

    def test_rollover_keeps_backup_count_files(self, tmp_path):
        path = tmp_path / "hcc_advisor.log"
        handler = logger._make_file_handler(path, max_bytes=400, backup_count=2)
        test_logger = logging.getLogger("hcc_advisor_rotation_test")
        test_logger.propagate = False
        test_logger.addHandler(handler)
        try:
            for i in range(100):
                test_logger.warning("line %03d %s", i, "x" * 40)
        finally:
            test_logger.removeHandler(handler)
            handler.close()
        names = sorted(p.name for p in tmp_path.iterdir())
        assert names == ["hcc_advisor.log", "hcc_advisor.log.1", "hcc_advisor.log.2"]
        assert all(p.stat().st_size <= 400 for p in tmp_path.iterdir())
        assert "line 099" in _read(path)

    def test_info_is_default_and_debug_is_dropped_unformatted(self, tmp_log):
        logger.log_info("an info line")
        logger.log_debug("a debug line", query_preview="SELECT 1")
        text = _read(tmp_log)
        assert "an info line" in text
        assert "a debug line" not in text

    def test_debug_opt_in_logs_debug(self, tmp_log):
        logger.app_logger.setLevel(logging.DEBUG)
        logger.log_debug("a debug line", query_preview="SELECT 1")
        assert "a debug line" in _read(tmp_log)


# ============================================================================
# Clear Logs
# ============================================================================

class TestClearLogs:

    def test_logging_continues_after_clear(self, tmp_log):
        logger.log_info("before-clear")
        inode = os.stat(tmp_log).st_ino

        result = logger.clear_logs(cleared_by="admin")
        logger.log_info("after-clear")

        assert result.startswith("Log cleared")
        # Emptied in place (same file), not deleted from under the handler.
        assert os.stat(tmp_log).st_ino == inode
        text = logger.get_recent_logs(lines=50)
        assert "after-clear" in text
        assert "before-clear" not in text
        assert "Log cleared by admin" in text

    def test_removes_rotated_and_legacy_files(self, tmp_log):
        logger.log_info("current")
        backup = tmp_log.with_name("hcc_advisor.log.1")
        legacy = tmp_log.with_name("hcc_advisor_20260101.log")
        other = tmp_log.with_name("unrelated.log")
        for path in (backup, legacy, other):
            path.write_text("stale-entry | ERROR | x\n", encoding="utf-8")

        result = logger.clear_logs()

        assert not backup.exists() and not legacy.exists()
        assert other.exists()
        assert tmp_log.exists()
        assert "deleted 2" in result
        assert "stale-entry" not in logger.get_recent_logs(lines=50)

    def test_file_removed_externally_is_recreated(self, tmp_log):
        logger.log_info("first")
        tmp_log.unlink()
        logger.clear_logs()
        logger.log_info("second")
        assert "second" in _read(tmp_log)

    def test_clear_holds_the_handler_lock(self, tmp_log):
        """No record or rollover can interleave with the truncation."""
        handler = logger._file_handler()
        lock_seen = []
        real_open = handler._open

        def reopen():
            # RLock owned by this thread while clear_logs reopens the stream.
            lock_seen.append(handler.lock._is_owned())
            return real_open()

        handler._open = reopen
        logger.clear_logs()
        assert lock_seen == [True]


# ============================================================================
# Tail reader
# ============================================================================

class _CountingOpen:
    """Stand-in for open() that counts the bytes read through it."""

    def __init__(self):
        self.bytes_read = 0

    def __call__(self, *args, **kwargs):
        return _CountingFile(open(*args, **kwargs), self)


class _CountingFile:
    def __init__(self, f, counter):
        self._f, self._counter = f, counter

    def read(self, *args):
        data = self._f.read(*args)
        self._counter.bytes_read += len(data)
        return data

    def __getattr__(self, name):
        return getattr(self._f, name)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self._f.close()


def _write_lines(path, lines):
    with open(path, "w", encoding="utf-8") as f:
        f.writelines(line + "\n" for line in lines)


class TestTailReader:

    @pytest.mark.parametrize("chunk", [7, 64, 4096])
    @pytest.mark.parametrize("n", [1, 3, 10, 50])
    def test_last_lines_match_the_file(self, tmp_log, monkeypatch, chunk, n):
        lines = [f"2026-09-24 | INFO     | l{i} | {'é' * (i % 5)}" for i in range(40)]
        _write_lines(tmp_log, lines)
        monkeypatch.setattr(logger, "_TAIL_CHUNK_BYTES", chunk)
        assert logger._tail_lines(n) == lines[-n:]

    def test_error_filter(self, tmp_log, monkeypatch):
        lines = [f"x | {'ERROR' if i % 7 == 0 else 'INFO'}    | l{i}" for i in range(100)]
        _write_lines(tmp_log, lines)
        monkeypatch.setattr(logger, "_TAIL_CHUNK_BYTES", 50)
        expected = [line for line in lines if "| ERROR" in line][-5:]
        assert logger.get_error_logs(lines=5) == "\n".join(expected) + "\n"

    def test_continues_into_rotated_backup(self, tmp_log):
        _write_lines(tmp_log.with_name("hcc_advisor.log.1"), ["old1", "old2"])
        _write_lines(tmp_log, ["new1"])
        assert logger._tail_lines(3) == ["old1", "old2", "new1"]

    def test_empty_or_missing_log(self, tmp_log):
        assert logger.get_recent_logs() == "No logs available"
        assert logger.get_error_logs() == "No error logs available"

    def test_reads_a_bounded_tail_of_a_large_file(self, tmp_log, monkeypatch):
        line = "2026-09-24 12:00:00 | INFO     | hcc_advisor | f:1 | " + "x" * 100
        with open(tmp_log, "w", encoding="utf-8") as f:
            for i in range(50_000):  # ~7.5 MB
                f.write(f"{line} {i}\n")
        size = tmp_log.stat().st_size
        assert size > 3 * logger.MAX_TAIL_BYTES

        counting = _CountingOpen()
        monkeypatch.setattr(logger, "open", counting, raising=False)
        text = logger.get_recent_logs(lines=100)
        assert text.splitlines()[-1].endswith(" 49999")
        assert len(text.splitlines()) == 100
        assert counting.bytes_read <= 2 * logger._TAIL_CHUNK_BYTES

        # No error line anywhere: the search stops at the byte budget.
        counting.bytes_read = 0
        assert logger.get_error_logs(lines=50) == "No error logs available"
        assert counting.bytes_read == logger.MAX_TAIL_BYTES

    def test_fragment_at_budget_edge_is_dropped(self, tmp_log):
        _write_lines(tmp_log, ["a" * 30, "b" * 30, "c" * 30])
        # 40 bytes from the end: an 8-byte fragment of the b line, "\n", "c"*30, "\n".
        assert logger._tail_lines(10, max_bytes=40) == ["c" * 30]


# ============================================================================
# Redaction
# ============================================================================

def _db_data():
    """What page_06 passes to CentralQueries.add_target_database."""
    return {
        'database_name': 'PROD', 'display_name': 'Prod', 'db_host': 'dbhost',
        'port': 1521, 'service_name': 'FREEPDB1', 'username': 'HCC',
        'password_encrypted': SECRET, 'description': '', 'environment': 'PRODUCTION',
        'platform_type': 'STANDARD', 'connection_mode': 'NORMAL',
        'oracle_version': 'Oracle Database 23ai',
    }


class TestRedact:

    @pytest.mark.parametrize("key", [
        "password", "PASSWORD", "password_encrypted", "Passwd", "pwd", "dash_pwd",
        "db_passphrase", "client_secret", "api_key", "ENCRYPTION_KEY", "token",
        "access_token", "Authorization", "credentials", "cookie",
    ])
    def test_sensitive_keys(self, key):
        assert is_sensitive_key(key)

    @pytest.mark.parametrize("key", ["username", "db_host", "port", "database_id", "query"])
    def test_ordinary_keys(self, key):
        assert not is_sensitive_key(key)

    def test_nested_values_are_masked_and_input_untouched(self):
        Login = namedtuple("Login", "user password")
        data = {
            "database_id": 7,
            "Password": SECRET,
            "db_data": _db_data(),
            "binds": [{"pwd": SECRET, "owner": "SALES"}, ("x", {"token": SECRET})],
            "login": Login("HCC", SECRET),
            "headers": {"Authorization": f"Bearer {SECRET}"},
        }
        safe = redact(data)
        assert SECRET not in repr(safe)
        assert safe["database_id"] == 7
        assert safe["Password"] == REDACTED
        assert safe["db_data"]["password_encrypted"] == REDACTED
        assert safe["db_data"]["username"] == "HCC"
        assert safe["binds"][0] == {"pwd": REDACTED, "owner": "SALES"}
        assert safe["binds"][1] == ("x", {"token": REDACTED})
        assert safe["login"] == {"user": "HCC", "password": REDACTED}
        # The caller's dict still holds the real values (it is used for the SQL).
        assert data["db_data"]["password_encrypted"] == SECRET
        assert data["Password"] == SECRET

    def test_scalars_and_none_pass_through(self):
        assert redact(None) is None
        assert redact("text") == "text"
        assert redact([1, "a"]) == [1, "a"]

    def test_self_reference_terminates(self):
        loop = {"a": 1}
        loop["self"] = loop
        assert redact(loop)["a"] == 1

    def test_sql_debug_console_uses_the_same_rules(self):
        from datetime import date
        safe = sql_debug._sanitize_params({
            "owner": "SALES", "password_encrypted": SECRET, "day": date(2026, 9, 24),
            "nested": {"api_key": SECRET},
        })
        assert safe["owner"] == "SALES"
        assert safe["password_encrypted"] == REDACTED
        assert safe["day"] == repr(date(2026, 9, 24))
        assert SECRET not in safe["nested"]
        assert sql_debug._sanitize_params(None) is None
        assert sql_debug._sanitize_params(["SALES", 1]) == ["SALES", 1]


class TestLoggerRedaction:

    def test_log_db_error_masks_params(self, tmp_log):
        logger.log_db_error(oracledb.DatabaseError("ORA-12899"), "INSERT INTO t", _db_data())
        text = _read(tmp_log)
        assert "DATABASE ERROR" in text
        assert SECRET not in text
        assert f"'password_encrypted': '{REDACTED}'" in text

    def test_log_error_masks_nested_extra_info(self, tmp_log):
        details = logger.log_error(ValueError("boom"), "ctx", {"db_data": _db_data(), "id": 3})
        text = _read(tmp_log)
        assert "ERROR in ctx" in text
        assert SECRET not in text
        assert SECRET not in repr(details)

    @pytest.mark.parametrize("func", ["log_info", "log_warning", "log_debug"])
    def test_kwargs_are_masked(self, tmp_log, func):
        logger.app_logger.setLevel(logging.DEBUG)
        getattr(logger, func)("event", password=SECRET, ctx={"token": SECRET}, user="HCC")
        text = _read(tmp_log)
        assert "event" in text and "'user': 'HCC'" in text
        assert SECRET not in text

    def test_add_target_database_never_logs_the_encrypted_password(self, tmp_log, monkeypatch):
        """Regression: a failed registration logged db_data, password_encrypted
        included, through log_db_error (the INSERT's binds) and log_error."""
        conn = MagicMock()
        cursor = conn.cursor.return_value
        cursor.description = [("DATABASE_ID",), ("IS_ACTIVE",)]
        cursor.fetchall.return_value = []  # duplicate-name pre-check: no row

        def execute(sql, params=None):
            if "INSERT INTO t_target_databases" in sql:
                raise oracledb.DatabaseError("ORA-12899: value too large for column")

        cursor.execute.side_effect = execute
        pool = MagicMock()
        pool.acquire.return_value = conn
        monkeypatch.setattr(CentralConnector, "_pool", pool)
        monkeypatch.setattr(cc_module, "st", MagicMock())
        monkeypatch.setattr(cc_module, "is_debug_enabled", lambda: False)
        monkeypatch.setattr(CentralQueries, "ensure_connection_mode_column", lambda: True)

        ok, msg, _ = CentralQueries.add_target_database(_db_data())

        assert ok is False and "ORA-12899" in msg
        text = _read(tmp_log)
        assert "ORA-12899" in text  # the failure itself is logged...
        assert SECRET not in text   # ...without the encrypted password
        assert "password_encrypted" in text and REDACTED in text


# ============================================================================
# Log viewer (Overview page in app.py)
# ============================================================================

@pytest.fixture
def viewer_spies():
    spies = {
        "get_recent_logs": MagicMock(return_value="2026 | INFO     | recent line\n"),
        "get_error_logs": MagicMock(return_value="2026 | ERROR    | error line\n"),
        "clear_logs": MagicMock(return_value="Log cleared"),
    }
    with app_shell("Overview", extra=[(logger, name, spy) for name, spy in spies.items()]):
        yield spies


class TestLogViewer:

    def test_log_is_not_read_until_the_viewer_is_switched_on(self, viewer_spies):
        at = new_app().run()
        assert not at.exception
        assert [t.label for t in at.toggle] == ["View Application Logs"]
        assert "Log Type" not in [s.label for s in at.selectbox]
        viewer_spies["get_recent_logs"].assert_not_called()
        viewer_spies["get_error_logs"].assert_not_called()

        at.toggle(key="show_app_logs").set_value(True).run()
        assert not at.exception
        viewer_spies["get_error_logs"].assert_called_once_with(lines=50)
        viewer_spies["get_recent_logs"].assert_not_called()
        assert any("error line" in m.value for m in at.markdown)

        at.selectbox(key="log_type_select").select("All Logs").run()
        viewer_spies["get_recent_logs"].assert_called_once_with(lines=50)
        assert any("recent line" in m.value for m in at.markdown)

    def test_log_lines_are_escaped(self, viewer_spies):
        viewer_spies["get_error_logs"].return_value = "x | ERROR | <script>alert(1)</script>\n"
        at = new_app()
        at.session_state["show_app_logs"] = True
        at.run()
        viewer = [m.value for m in at.markdown if 'class="log-viewer"' in m.value]
        assert viewer and "<script>" not in viewer[0] and "&lt;script&gt;" in viewer[0]

    def test_admin_clears_logs(self, viewer_spies):
        at = new_app("admin")
        at.session_state["show_app_logs"] = True
        at.run()
        # AppTest 1.31 replays the click on every st.rerun(), so the rerun
        # after clearing is mocked out.
        with patch.object(st, "rerun") as rerun:
            at.button(key="clear_logs_btn").click().run()
        assert not at.exception
        viewer_spies["clear_logs"].assert_called_once_with(cleared_by="admin")
        rerun.assert_called_once_with()

    def test_non_admin_cannot_clear_logs(self, viewer_spies):
        at = new_app("operator")
        at.session_state["show_app_logs"] = True
        at.run()
        assert at.button(key="clear_logs_btn").disabled
        at.button(key="clear_logs_btn").click().run()
        viewer_spies["clear_logs"].assert_not_called()
