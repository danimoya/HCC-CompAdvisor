"""
SQL Executor for HCC Compression Advisor
Parses SQL*Plus-formatted files and executes via oracledb.
Strips SQL*Plus directives and handles PL/SQL blocks, DDL, DML, and SELECT.
"""

import re
from pathlib import Path
from typing import List, Tuple, Callable, Optional, Union

# SQL*Plus directives to strip (case-insensitive, line-level)
_SQLPLUS_DIRECTIVES = re.compile(
    r'^\s*(SET\s+|PROMPT\b|SPOOL\s|@@|WHENEVER\s|EXIT\b|QUIT\b|DEFINE\s|ACCEPT\s|COLUMN\s|SHOW\s|HOST\s)',
    re.IGNORECASE
)

# PL/SQL block start (DECLARE or BEGIN at line start)
_PLSQL_START = re.compile(r'^\s*(DECLARE|BEGIN)\b', re.IGNORECASE)

# Standalone slash that terminates PL/SQL blocks
_SLASH_LINE = re.compile(r'^\s*/\s*$')

# SQL comment lines
_LINE_COMMENT = re.compile(r'^\s*--')
_BLOCK_COMMENT_START = re.compile(r'^\s*/\*')
_BLOCK_COMMENT_END = re.compile(r'\*/')


def parse_sql_file(path: Union[str, Path]) -> List[Tuple[str, str]]:
    """
    Parse a SQL*Plus-formatted file into executable statements.

    Returns a list of (stmt_type, stmt_text) tuples where stmt_type is one of:
    'DDL', 'DML', 'PLSQL', 'SELECT', 'COMMIT'.
    """
    path = Path(path)
    content = path.read_text(encoding='utf-8')
    return parse_sql_text(content)


def parse_sql_text(content: str) -> List[Tuple[str, str]]:
    """
    Parse SQL*Plus-formatted text (already in memory) into executable
    statements. Same contract as parse_sql_file but takes a string, so callers
    that have the SQL in hand (e.g. the admin patch panel) can reuse this
    SQL*Plus-aware splitter instead of naive split(';'), which mis-splits
    statements containing string literals or PL/SQL with embedded semicolons.

    Returns a list of (stmt_type, stmt_text) tuples where stmt_type is one of:
    'DDL', 'DML', 'PLSQL', 'SELECT', 'COMMIT'.
    """
    lines = content.splitlines()

    statements: List[Tuple[str, str]] = []
    current_lines: List[str] = []
    in_plsql = False
    in_block_comment = False

    def _classify(stmt: str) -> str:
        s = stmt.strip().upper()
        if s.startswith(('CREATE', 'ALTER', 'DROP', 'GRANT', 'REVOKE', 'TRUNCATE')):
            return 'DDL'
        if s.startswith(('INSERT', 'UPDATE', 'DELETE', 'MERGE')):
            return 'DML'
        if s.startswith('SELECT'):
            return 'SELECT'
        if s.startswith('COMMIT'):
            return 'COMMIT'
        if s.startswith(('DECLARE', 'BEGIN')):
            return 'PLSQL'
        return 'DDL'

    def _flush_plsql():
        nonlocal current_lines, in_plsql
        if current_lines:
            text = '\n'.join(current_lines).strip()
            if text:
                statements.append(('PLSQL', text))
        current_lines = []
        in_plsql = False

    def _flush_sql():
        nonlocal current_lines
        if current_lines:
            text = '\n'.join(current_lines).strip()
            # Remove trailing semicolon for oracledb execution
            if text.endswith(';'):
                text = text[:-1].strip()
            if text:
                statements.append((_classify(text), text))
        current_lines = []

    for line in lines:
        # Skip block comments
        if in_block_comment:
            if _BLOCK_COMMENT_END.search(line):
                in_block_comment = False
            continue

        if _BLOCK_COMMENT_START.match(line) and not _BLOCK_COMMENT_END.search(line):
            in_block_comment = True
            continue

        # Full-line block comment (/* ... */ on one line)
        stripped = line.strip()
        if stripped.startswith('/*') and stripped.endswith('*/'):
            continue

        # Skip line comments
        if _LINE_COMMENT.match(line):
            # Allow comments inside PL/SQL blocks
            if in_plsql:
                current_lines.append(line)
            continue

        # Skip SQL*Plus directives
        if _SQLPLUS_DIRECTIVES.match(line):
            continue

        # Skip empty lines (unless in PL/SQL)
        if not stripped:
            if in_plsql:
                current_lines.append(line)
            continue

        # Handle PL/SQL blocks
        if in_plsql:
            if _SLASH_LINE.match(line):
                _flush_plsql()
            else:
                current_lines.append(line)
            continue

        # Detect PL/SQL block start
        if _PLSQL_START.match(line):
            _flush_sql()
            in_plsql = True
            current_lines.append(line)
            continue

        # Handle standalone slash (shouldn't happen outside PL/SQL but skip)
        if _SLASH_LINE.match(line):
            continue

        # Regular SQL line
        current_lines.append(line)

        # Semicolon at end of line terminates SQL statement
        if stripped.endswith(';'):
            _flush_sql()

    # Flush anything remaining
    if in_plsql:
        _flush_plsql()
    else:
        _flush_sql()

    return statements


def execute_sql_file(
    conn,
    path: Union[str, Path],
    on_progress: Optional[Callable[[int, int, str, str], None]] = None,
    stop_on_error: bool = False
) -> Tuple[int, int, List[str]]:
    """
    Parse and execute a SQL*Plus file via an oracledb connection.

    Args:
        conn: oracledb.Connection
        path: Path to SQL file
        on_progress: Callback (current_idx, total, stmt_type, status_msg)
        stop_on_error: If True, stop execution on first error

    Returns:
        (successes, errors, messages) tuple
    """
    statements = parse_sql_file(path)
    total = len(statements)
    successes = 0
    errors = 0
    messages: List[str] = []

    for idx, (stmt_type, stmt_text) in enumerate(statements):
        preview = stmt_text[:80].replace('\n', ' ')
        if on_progress:
            on_progress(idx, total, stmt_type, f"Executing: {preview}...")

        try:
            cursor = conn.cursor()
            cursor.execute(stmt_text)

            if stmt_type == 'SELECT':
                cursor.fetchall()

            if stmt_type in ('DML', 'COMMIT'):
                conn.commit()

            cursor.close()
            successes += 1
            messages.append(f"[OK] {stmt_type}: {preview}")

        except Exception as e:
            errors += 1
            err_msg = f"[ERROR] {stmt_type}: {preview} -> {e}"
            messages.append(err_msg)
            if stop_on_error:
                break

    if on_progress:
        on_progress(total, total, 'DONE', f"Completed: {successes} ok, {errors} errors")

    return successes, errors, messages
