"""
Fake central / target connectors for query-layer and page tests. Not a test
module itself.

``SqlRouter`` stands in for ``CentralConnector`` or ``TargetConnector``: every
statement is recorded (normalised SQL + binds), answered from routes matched
on SQL substrings, and its binds are checked against the statement's
``:name`` placeholders the way python-oracledb does (an unused or a missing
bind is an error). A mismatch is *recorded*, not raised: the query layer
catches every exception and returns its fallback, which would hide a raised
assertion. The fixtures that install a router fail the test at teardown when
any mismatch was recorded.

Like the real connectors, the installed entry points turn an oracledb error
into their non-strict sentinel (empty DataFrame, 0, False; recorded in
``router.swallowed``) unless the caller passed ``raise_on_error=True``; any
other exception a route raises propagates.
"""
import re
from contextlib import contextmanager
from typing import Any, Dict, Iterable, List, Optional, Tuple
from unittest.mock import MagicMock

import oracledb
import pandas as pd

from hcc_advisor.utils.central_connector import CentralConnector
from hcc_advisor.utils.target_connector import TargetConnector

_LITERAL = re.compile(r"'(?:[^']|'')*'|\"[^\"]*\"")
_COMMENT = re.compile(r"--[^\n]*")
_PLACEHOLDER = re.compile(r"(?<![:\w]):([A-Za-z_]\w*)")


def norm(sql: str) -> str:
    """Whitespace-normalised SQL."""
    return " ".join(sql.split())


def placeholders(sql: str) -> set:
    """Lower-cased ``:name`` bind placeholders of `sql`, ignoring string
    literals, quoted identifiers and ``--`` comments (names are
    case-insensitive in Oracle, as in python-oracledb)."""
    text = _COMMENT.sub(" ", _LITERAL.sub("''", sql))
    return {m.lower() for m in _PLACEHOLDER.findall(text)}


def bind_mismatch(sql: str, params: Optional[Dict[str, Any]], extra: Iterable[str] = ()) -> Optional[str]:
    """None when the binds match the placeholders, else a description."""
    names = placeholders(sql)
    given = {str(k).lower() for k in (params or {})} | {e.lower() for e in extra}
    if names == given:
        return None
    return (f"bind mismatch: unused={sorted(given - names)} missing={sorted(names - given)}\n"
            f"{norm(sql)[:400]}")


def df(rows: List[Dict[str, Any]], columns: Optional[List[str]] = None) -> pd.DataFrame:
    """A result frame as the connectors build it (upper-case column names)."""
    frame = pd.DataFrame(rows, columns=columns)
    frame.columns = [str(c).upper() for c in frame.columns]
    return frame


class Call:
    """One recorded statement."""

    def __init__(self, kind: str, sql: str, params: Optional[Dict[str, Any]], database_id=None):
        self.kind = kind
        self.sql = norm(sql)
        self.params = dict(params) if params else {}
        self.database_id = database_id

    def __repr__(self):
        return f"Call({self.kind}, {self.sql[:60]!r}, {self.params})"


class SqlRouter:
    """Answers statements from routes matched on SQL substrings (case-insensitive).

    A route's result is a DataFrame (returned as a copy), an Exception instance
    or class (raised), a plain value (returned as is, e.g. a rowcount or a
    bool) or a callable ``f(sql, params)`` returning one of those.
    """

    def __init__(self, name: str):
        self.name = name
        self.routes: List[Tuple[Tuple[str, ...], Any]] = []
        self.calls: List[Call] = []
        self.bind_errors: List[str] = []
        self.swallowed: List[str] = []     # oracledb errors a non-strict call turned into a sentinel
        self.default_query: Any = None     # None -> empty DataFrame
        self.default_dml: Any = 1
        self.default_plsql: Any = True

    # -- configuration -------------------------------------------------------
    def on(self, *needles: str, result: Any) -> "SqlRouter":
        """Answer statements containing every needle with `result` (latest route wins)."""
        self.routes.insert(0, (tuple(n.lower() for n in needles), result))
        return self

    # -- inspection ----------------------------------------------------------
    def find(self, *needles: str, kind: Optional[str] = None) -> List[Call]:
        low = [n.lower() for n in needles]
        return [c for c in self.calls
                if (kind is None or c.kind == kind) and all(n in c.sql.lower() for n in low)]

    def one(self, *needles: str, kind: Optional[str] = None) -> Call:
        found = self.find(*needles, kind=kind)
        assert len(found) == 1, f"expected one {needles} call, got {found}"
        return found[0]

    @property
    def last(self) -> Call:
        assert self.calls, "no statement was executed"
        return self.calls[-1]

    # -- execution -----------------------------------------------------------
    def _answer(self, kind: str, sql: str, params, default, extra=(), database_id=None):
        call = Call(kind, sql, params, database_id)
        self.calls.append(call)
        problem = bind_mismatch(sql, params, extra)
        if problem:
            self.bind_errors.append(problem)
        low = call.sql.lower()
        result = default
        for needles, value in self.routes:
            if all(n in low for n in needles):
                result = value
                break
        if callable(result) and not isinstance(result, type):
            result = result(call.sql, call.params)
        if isinstance(result, BaseException) or (
                isinstance(result, type) and issubclass(result, BaseException)):
            raise result
        if isinstance(result, pd.DataFrame):
            return result.copy()
        return result

    def query(self, sql, params=None, database_id=None):
        out = self._answer('query', sql, params, self.default_query, database_id=database_id)
        return pd.DataFrame() if out is None else out

    def dml(self, sql, params=None, database_id=None, extra=()):
        return self._answer('dml', sql, params, self.default_dml, extra=extra,
                            database_id=database_id)

    def plsql(self, sql, params=None, database_id=None, extra=()):
        return self._answer('plsql', sql, params, self.default_plsql, extra=extra,
                            database_id=database_id)

    # -- a DB-API connection over the same routes ----------------------------
    def connection(self, database_id=None) -> "FakeConnection":
        return FakeConnection(self, database_id)


class FakeCursor:
    """DB-API cursor answering from a router (tuples, like oracledb)."""

    def __init__(self, router: SqlRouter, database_id=None):
        self.router = router
        self.database_id = database_id
        self.description = None
        self.rowcount = 0
        self._rows: List[tuple] = []

    def execute(self, sql, params=None):
        out = self.router._answer('cursor', sql, params, None, database_id=self.database_id)
        if isinstance(out, pd.DataFrame):
            self.description = [(c, None, None, None, None, None, None) for c in out.columns]
            self._rows = [tuple(r) for r in out.itertuples(index=False, name=None)]
            self.rowcount = len(self._rows)
        else:
            self.description = None
            self._rows = []
            self.rowcount = out if isinstance(out, int) else 0

    def executemany(self, sql, rows):
        for params in rows:
            self.router._answer('executemany', sql, params, None, database_id=self.database_id)
        self.rowcount = len(rows)

    def fetchall(self):
        return list(self._rows)

    def fetchone(self):
        return self._rows[0] if self._rows else None

    def close(self):
        pass


class FakeConnection:
    def __init__(self, router: SqlRouter, database_id=None):
        self.router = router
        self.database_id = database_id
        self.commits = 0
        self.rollbacks = 0

    def cursor(self):
        return FakeCursor(self.router, self.database_id)

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1

    def close(self):
        pass



def _non_strict(router: SqlRouter, raise_on_error: bool, sentinel, call):
    """Run `call` like a connector: an oracledb error becomes `sentinel` (and is
    recorded) unless raise_on_error; other exceptions propagate."""
    try:
        return call()
    except oracledb.Error as e:
        if raise_on_error:
            raise
        router.swallowed.append(str(e))
        return sentinel() if callable(sentinel) else sentinel


def install_central(monkeypatch, router: SqlRouter) -> SqlRouter:
    """Route every CentralConnector entry point through `router`."""

    def execute_query(query, params=None, raise_on_error=False, call_timeout=None):
        return _non_strict(router, raise_on_error, pd.DataFrame,
                           lambda: router.query(query, params))

    def execute_dml(statement, params=None, commit=True, raise_on_error=False):
        return _non_strict(router, raise_on_error, 0, lambda: router.dml(statement, params))

    def execute_plsql(plsql_block, params=None, commit=True, raise_on_error=False):
        return _non_strict(router, raise_on_error, False,
                           lambda: router.plsql(plsql_block, params))

    def execute_dml_returning(statement, params=None, out_bind='new_id', commit=True,
                              raise_on_error=False):
        return _non_strict(router, raise_on_error, None,
                           lambda: router.dml(statement, params, extra=(out_bind,)))

    @contextmanager
    def get_connection():
        yield router.connection()

    for name, fn in (('execute_query', execute_query), ('execute_dml', execute_dml),
                     ('execute_plsql', execute_plsql),
                     ('execute_dml_returning', execute_dml_returning),
                     ('get_connection', get_connection)):
        monkeypatch.setattr(CentralConnector, name, staticmethod(fn))
    monkeypatch.setattr(CentralConnector, 'test_connection', staticmethod(lambda: True))
    monkeypatch.setattr(CentralConnector, 'initialize_pool', staticmethod(lambda *a, **k: None))
    return router


def install_target(monkeypatch, router: SqlRouter) -> SqlRouter:
    """Route every TargetConnector entry point through `router`."""

    def execute_query(database_id, query, params=None, conn_config=None,
                      raise_on_error=False, call_timeout=None):
        return _non_strict(router, raise_on_error, pd.DataFrame,
                           lambda: router.query(query, params, database_id=database_id))

    def execute_dml(database_id, statement, params=None, commit=True, conn_config=None,
                    raise_on_error=False):
        return _non_strict(router, raise_on_error, 0,
                           lambda: router.dml(statement, params, database_id=database_id))

    def execute_plsql(database_id, plsql_block, params=None, commit=True, conn_config=None,
                      raise_on_error=False):
        return _non_strict(router, raise_on_error, False,
                           lambda: router.plsql(plsql_block, params, database_id=database_id))

    def execute_procedure_with_output(database_id, plsql_block, in_params=None,
                                      out_params=None, conn_config=None):
        # The real one always re-raises database errors.
        out = router.plsql(plsql_block, in_params, database_id=database_id,
                           extra=tuple(out_params or ()))
        return out if isinstance(out, dict) else {}

    pool = MagicMock(name='target_pool')
    pool.acquire.side_effect = lambda: router.connection()

    @contextmanager
    def get_connection(database_id, conn_config=None):
        yield router.connection(database_id)

    for name, fn in (('execute_query', execute_query), ('execute_dml', execute_dml),
                     ('execute_plsql', execute_plsql),
                     ('execute_procedure_with_output', execute_procedure_with_output),
                     ('get_connection', get_connection)):
        monkeypatch.setattr(TargetConnector, name, staticmethod(fn))
    monkeypatch.setattr(TargetConnector, 'get_pool', staticmethod(lambda database_id, conn_config: pool))
    monkeypatch.setattr(TargetConnector, 'test_connection_by_id', staticmethod(lambda database_id: True))
    router.pool = pool
    return router
