"""
Versioned SQL patches for the central schema.

Each patch is a directory under sql/patches/ (YYYYMMDD-description, applied in
name order) holding patch.sql, an optional check.sql and a readme.md. Shared by
Admin > SQL Patches and the deployment page's non-destructive Upgrade, so both
detect, apply and record patches the same way:

- a patch counts as applied when its check.sql returns RESULT > 0, or when
  T_PATCH_HISTORY holds a SUCCESS row for it;
- patch.sql is split with the SQL*Plus-aware parser and run statement by
  statement; the first failing statement aborts the patch.

The DB helpers take an optional oracledb connection. Without one they borrow a
connection from the CentralConnector pool (Admin page); the deployment page
passes its own direct connection.
"""

import stat
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Dict, List, Optional

from hcc_advisor.utils.logger import log_error, log_warning


class PatchError(Exception):
    """The patch set itself cannot be used (directory missing or unsafe)."""


# Result statuses reported by apply_pending_patches()
PATCH_APPLIED = 'APPLIED'
PATCH_FAILED = 'FAILED'

_PATCH_HISTORY_DDL = """
    CREATE TABLE T_PATCH_HISTORY (
        patch_id      NUMBER GENERATED ALWAYS AS IDENTITY,
        patch_name    VARCHAR2(200) NOT NULL,
        applied_date  TIMESTAMP DEFAULT SYSTIMESTAMP,
        applied_by    VARCHAR2(100) DEFAULT USER,
        status        VARCHAR2(20),
        error_message VARCHAR2(4000),
        CONSTRAINT PK_PATCH_HISTORY PRIMARY KEY (patch_id)
    )"""


@dataclass
class PatchScan:
    """Patch state of the central schema (see scan_patches)."""
    patch_dirs: List[Path]
    recorded: Dict[str, dict]      # latest T_PATCH_HISTORY row per patch
    detected: Dict[str, bool]      # check.sql result per patch that has one
    has_history_table: bool
    auto_marked: int = 0           # detected-as-applied patches recorded by this scan

    def is_applied(self, name: str) -> bool:
        return is_patch_applied(name, self.recorded, self.detected)

    @property
    def pending(self) -> List[Path]:
        return [d for d in self.patch_dirs if not self.is_applied(d.name)]


@dataclass
class PatchResult:
    name: str
    status: str                    # PATCH_APPLIED or PATCH_FAILED
    error: str = ''
    statements: int = 0


@dataclass
class UpgradeResult:
    results: List[PatchResult] = field(default_factory=list)

    @property
    def failed(self) -> Optional[PatchResult]:
        return next((r for r in self.results if r.status == PATCH_FAILED), None)

    @property
    def ok(self) -> bool:
        return self.failed is None


# ---------------------------------------------------------------------------
# Patch files
# ---------------------------------------------------------------------------

def find_patches_dir() -> Optional[Path]:
    """
    Locate sql/patches. Order: package layout (bundled/mounted into the
    container at hcc_advisor/sql/patches), dev layout (repo_root/sql/patches),
    then legacy fallbacks.
    """
    here = Path(__file__).resolve()
    candidates = [
        here.parents[1] / 'sql' / 'patches',   # /app/hcc_advisor/sql/patches (container bind mount)
        here.parents[3] / 'sql' / 'patches',   # repo_root/sql/patches (dev)
        here.parents[2] / 'sql' / 'patches',   # legacy dev fallback
        Path('/app/sql/patches'),              # legacy container fallback
    ]
    for c in candidates:
        if c.exists():
            return c
    return None


def patches_dir_problem(patches_dir: Path) -> Optional[str]:
    """
    Return why patches must not be loaded from `patches_dir`, or None if safe.

    The patch SQL is executed verbatim against the central DB, so the patch
    source must be a trusted, read-only directory. Refuse a group/world-writable
    location, which would let any local process tamper with patch.sql and turn
    patching into an arbitrary-SQL-execution primitive. The intended deployment
    mounts sql/patches read-only (`:ro`), which is not group/world-writable.
    """
    try:
        mode = patches_dir.stat().st_mode
    except OSError:
        return f"Could not verify permissions on patches directory `{patches_dir}`."
    if mode & (stat.S_IWGRP | stat.S_IWOTH):
        return ("Refusing to load patches: the patches directory "
                f"`{patches_dir}` is group/world-writable. Patch SQL must come "
                "from a trusted, read-only location. Re-mount it read-only "
                "(`:ro`) and ensure it is not writable by other users.")
    return None


def resolve_patches_dir(patches_dir: Optional[Path] = None) -> Path:
    """Return a usable patch directory (default: find_patches_dir()) or raise PatchError."""
    patches_dir = patches_dir or find_patches_dir()
    if patches_dir is None:
        raise PatchError("Patches directory not found. Expected at `sql/patches/` "
                         "relative to the project root.")
    problem = patches_dir_problem(patches_dir)
    if problem:
        raise PatchError(problem)
    return patches_dir


def list_patch_dirs(patches_dir: Path) -> List[Path]:
    """Patch directories in apply order (by name, i.e. date prefix)."""
    return sorted([d for d in patches_dir.iterdir() if d.is_dir()], key=lambda d: d.name)


def _read_patch_file(pdir: Path, name: str) -> Optional[str]:
    path = pdir / name
    return path.read_text() if path.exists() else None


def is_patch_applied(name: str, recorded: Dict[str, dict], detected: Dict[str, bool]) -> bool:
    """Applied = check.sql passes, or T_PATCH_HISTORY's latest row is SUCCESS."""
    info = recorded.get(name)
    return bool(detected.get(name, False) or (info and info['status'] == 'SUCCESS'))


# ---------------------------------------------------------------------------
# Database helpers
# ---------------------------------------------------------------------------

@contextmanager
def _borrow(conn=None):
    """Yield `conn`, or a pooled central connection when none is given."""
    if conn is not None:
        yield conn
        return
    from hcc_advisor.utils.central_connector import CentralConnector
    with CentralConnector.get_connection() as pooled:
        yield pooled


def _history_table_exists(cur) -> bool:
    cur.execute("SELECT COUNT(*) FROM user_tables WHERE table_name = 'T_PATCH_HISTORY'")
    row = cur.fetchone()
    return bool(row and row[0])


def ensure_patch_history_table(conn=None) -> bool:
    """Create T_PATCH_HISTORY if it doesn't exist. Returns True if table exists."""
    try:
        with _borrow(conn) as c:
            cur = c.cursor()
            try:
                if _history_table_exists(cur):
                    return True
                try:
                    cur.execute(_PATCH_HISTORY_DDL)
                except Exception:
                    # Another session may have created it meanwhile (ORA-00955).
                    if _history_table_exists(cur):
                        return True
                    raise
                return True
            finally:
                cur.close()
    except Exception as e:
        log_error(e, "ensure_patch_history_table: CREATE TABLE T_PATCH_HISTORY failed")
        return False


def check_patch_applied(check_sql: str, conn=None) -> bool:
    """Run a check.sql query — returns True if its RESULT column is > 0."""
    try:
        with _borrow(conn) as c:
            cur = c.cursor()
            try:
                cur.execute(check_sql.strip().rstrip(';'))
                row = cur.fetchone()
                if not row:
                    return False
                cols = [d[0].upper() for d in (cur.description or [])]
                idx = cols.index('RESULT') if 'RESULT' in cols else 0
                return int(row[idx] or 0) > 0
            finally:
                cur.close()
    except Exception as e:
        log_warning(f"check_patch_applied: check.sql query failed: {e}")
        return False


def record_patch(patch_name: str, status: str = 'SUCCESS', error: str = None, conn=None) -> bool:
    """Insert a record into T_PATCH_HISTORY. Returns True if it was written."""
    try:
        with _borrow(conn) as c:
            cur = c.cursor()
            try:
                if error:
                    cur.execute(
                        "INSERT INTO t_patch_history (patch_name, status, error_message) VALUES (:n, :s, :e)",
                        {'n': patch_name, 's': status, 'e': str(error)[:4000]}
                    )
                else:
                    cur.execute(
                        "INSERT INTO t_patch_history (patch_name, status) VALUES (:n, :s)",
                        {'n': patch_name, 's': status}
                    )
                c.commit()
            finally:
                cur.close()
        return True
    except Exception as e:
        # A failed insert here means the audit row (esp. a FAILED patch) is lost —
        # surface it rather than swallowing silently.
        log_error(e, "record_patch", {'patch_name': patch_name, 'status': status})
        return False


def load_patch_history(conn=None) -> Dict[str, dict]:
    """Latest T_PATCH_HISTORY row per patch: {name: {'status', 'date', 'by'}}."""
    recorded: Dict[str, dict] = {}
    try:
        with _borrow(conn) as c:
            cur = c.cursor()
            try:
                cur.execute("""
                    SELECT patch_name, status,
                           TO_CHAR(applied_date, 'YYYY-MM-DD HH24:MI:SS') as applied_date,
                           applied_by
                    FROM t_patch_history ORDER BY applied_date DESC, patch_id DESC
                """)
                for name, status, applied_date, applied_by in cur.fetchall():
                    if name not in recorded:
                        recorded[name] = {'status': status, 'date': applied_date,
                                          'by': applied_by or ''}
            finally:
                cur.close()
    except Exception as e:
        log_warning(f"load_patch_history: could not load recorded patch history: {e}")
    return recorded


def scan_patches(patch_dirs: List[Path], conn=None) -> PatchScan:
    """
    Detect which patches are applied: ensure T_PATCH_HISTORY, load it, and run
    each patch's check.sql. A patch detected as applied but never recorded is
    recorded as SUCCESS (auto-mark), so the history reflects the real DB state.
    """
    has_history_table = ensure_patch_history_table(conn)
    recorded = load_patch_history(conn) if has_history_table else {}

    detected: Dict[str, bool] = {}
    auto_marked = 0
    for pdir in patch_dirs:
        check_sql = (_read_patch_file(pdir, 'check.sql') or '').strip()
        if not check_sql:
            continue
        detected[pdir.name] = check_patch_applied(check_sql, conn=conn)
        if detected[pdir.name] and pdir.name not in recorded and has_history_table:
            record_patch(pdir.name, 'SUCCESS', conn=conn)
            recorded[pdir.name] = {'status': 'SUCCESS', 'date': 'auto-detected', 'by': 'system'}
            auto_marked += 1

    return PatchScan(patch_dirs=list(patch_dirs), recorded=recorded, detected=detected,
                     has_history_table=has_history_table, auto_marked=auto_marked)


def apply_patch_sql(sql_text: str, conn=None) -> int:
    """
    Execute patch.sql statement by statement and commit. Raises on the first
    failing statement (after rolling back uncommitted DML). Returns the number
    of statements executed.
    """
    # SQL*Plus-aware parser instead of naive split('\n/\n')/split(';'), which
    # mis-splits string literals or PL/SQL with embedded semicolons.
    from hcc_advisor.utils.sql_executor import parse_sql_text

    statements = parse_sql_text(sql_text)
    with _borrow(conn) as c:
        cur = c.cursor()
        try:
            for stmt_type, stmt_text in statements:
                cur.execute(stmt_text)
                if stmt_type == 'SELECT':
                    cur.fetchall()
            c.commit()
        except Exception:
            try:
                c.rollback()
            except Exception:
                pass
            raise
        finally:
            cur.close()
    return len(statements)


def apply_pending_patches(conn=None, patches_dir: Optional[Path] = None,
                          on_progress: Optional[Callable[[int, int, str], None]] = None
                          ) -> UpgradeResult:
    """
    Apply every pending patch in name order, recording each in T_PATCH_HISTORY.
    Stops at the first failure: later patches may depend on it.

    Args:
        conn: Central DB connection (default: borrow from the pool)
        patches_dir: Patch directory (default: find_patches_dir())
        on_progress: Callback (index, total, patch_name) before each patch

    Raises:
        PatchError: patch directory missing or unsafe (nothing was applied)
    """
    patches_dir = resolve_patches_dir(patches_dir)
    pending = scan_patches(list_patch_dirs(patches_dir), conn=conn).pending
    outcome = UpgradeResult()
    for idx, pdir in enumerate(pending):
        if on_progress:
            on_progress(idx, len(pending), pdir.name)
        sql_text = _read_patch_file(pdir, 'patch.sql')
        try:
            if not sql_text or not sql_text.strip():
                raise PatchError(f"{pdir.name}: no patch.sql found")
            count = apply_patch_sql(sql_text, conn=conn)
        except Exception as e:
            record_patch(pdir.name, 'FAILED', str(e), conn=conn)
            outcome.results.append(PatchResult(pdir.name, PATCH_FAILED, error=str(e)))
            break
        record_patch(pdir.name, 'SUCCESS', conn=conn)
        outcome.results.append(PatchResult(pdir.name, PATCH_APPLIED, statements=count))
    return outcome
