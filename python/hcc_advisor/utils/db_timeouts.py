"""
Database timeouts shared by the central and target connectors.

Three limits keep an unreachable, slow or saturated database from holding a
Streamlit script thread indefinitely:

- tcp_connect_timeout (CENTRAL_CONNECT_TIMEOUT / TARGET_CONNECT_TIMEOUT): a
  pooled connection to a host that does not answer fails after that many
  seconds (DPY-6005 ... timed out) instead of the driver's 60s.
- getmode=POOL_GETMODE_TIMEDWAIT + wait_timeout (POOL_WAIT_TIMEOUT): acquire()
  on a pool whose connections are all busy fails with DPY-4005 instead of
  waiting forever.
- call_timeout (DB_CALL_TIMEOUT): a per-round-trip limit set only by the SELECT
  helpers (execute_query) that serve interactive reads, and put back to 0
  before the connection returns to the pool, so a pooled connection never
  carries it into someone else's DDL. execute_plsql (compression MOVE, index
  rebuild, DBMS_SCHEDULER.CREATE_JOB), execute_dml and the procedure helpers
  (DBMS_COMPRESSION) never get one. Code that runs long reads on purpose
  (analysis, quick scan, compression) runs inside long_operation(), which turns
  the read limit off for every execute_query issued from that thread.
"""

import contextvars
from contextlib import contextmanager
from typing import Any, Dict, Optional

import oracledb

from hcc_advisor.config import config

# Per thread (each thread starts with its own context): worker threads started
# inside a long operation do not inherit it and must enter it themselves.
_LONG_OPERATION = contextvars.ContextVar('hcc_long_operation', default=False)


@contextmanager
def long_operation():
    """Run the enclosed block without the interactive read call_timeout.

    Also usable as a decorator: `@long_operation()` (a fresh context manager is
    created for every call, so concurrent calls from several threads are safe).
    """
    token = _LONG_OPERATION.set(True)
    try:
        yield
    finally:
        _LONG_OPERATION.reset(token)


def in_long_operation() -> bool:
    """True inside long_operation() on this thread."""
    return _LONG_OPERATION.get()


def read_call_timeout_ms(seconds: Optional[float] = None) -> int:
    """call_timeout in ms for an interactive read.

    Args:
        seconds: explicit per-call limit (0 = none); None = DB_CALL_TIMEOUT,
            or no limit inside long_operation()
    """
    if seconds is None:
        if _LONG_OPERATION.get():
            return 0
        seconds = config.DB_CALL_TIMEOUT
    try:
        ms = int(float(seconds) * 1000)
    except (TypeError, ValueError):
        return 0
    return max(ms, 0)


@contextmanager
def connection_call_timeout(connection, ms: int):
    """Set connection.call_timeout to `ms` (> 0) for the enclosed statements and
    reset it to 0 on exit, before the caller releases the connection to its pool."""
    applied = False
    if ms and ms > 0:
        try:
            connection.call_timeout = ms
            applied = True
        except Exception:
            # e.g. a dead connection: the statement itself reports the error
            pass
    try:
        yield
    finally:
        if applied:
            try:
                connection.call_timeout = 0
            except Exception:
                pass


def pool_timeout_kwargs(connect_timeout: Optional[float]) -> Dict[str, Any]:
    """create_pool() kwargs for the connect timeout and the bounded acquire wait."""
    kwargs: Dict[str, Any] = {}
    if connect_timeout and connect_timeout > 0:
        kwargs['tcp_connect_timeout'] = float(connect_timeout)
    if config.POOL_WAIT_TIMEOUT and config.POOL_WAIT_TIMEOUT > 0:
        kwargs['getmode'] = oracledb.POOL_GETMODE_TIMEDWAIT
        kwargs['wait_timeout'] = int(config.POOL_WAIT_TIMEOUT * 1000)  # ms
    return kwargs


def describe_db_error(exc: BaseException) -> str:
    """str(exc), followed by what to do about it when it is one of the timeouts above."""
    text = str(exc)
    upper = text.upper()
    if 'DPY-4005' in upper:
        hint = (f"every pooled connection stayed busy for POOL_WAIT_TIMEOUT="
                f"{config.POOL_WAIT_TIMEOUT}s (long-running compressions or other sessions "
                f"hold them). Try again shortly, run compressions as background jobs, or "
                f"raise TARGET_POOL_MAX / POOL_WAIT_TIMEOUT.")
    elif 'DPY-4024' in upper:
        hint = (f"the statement ran longer than DB_CALL_TIMEOUT={config.DB_CALL_TIMEOUT}s "
                f"and was cancelled. Narrow the filter, or raise DB_CALL_TIMEOUT.")
    elif 'ORA-12170' in upper or ('DPY-6005' in upper and 'TIMED OUT' in upper):
        hint = ("the database host did not answer within the connect timeout "
                "(CENTRAL_CONNECT_TIMEOUT / TARGET_CONNECT_TIMEOUT). Check the host, port, "
                "listener and firewall.")
    else:
        return text
    return f"{text} — {hint}"
