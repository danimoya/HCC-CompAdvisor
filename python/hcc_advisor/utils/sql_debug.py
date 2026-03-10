"""
SQL Debug Console - Real-Time Query Viewer
Captures SQL/PL/SQL statements in Streamlit session state for live inspection.
"""

import streamlit as st
from datetime import datetime
from typing import Optional, Dict, Any

MAX_SQL_LOG_ENTRIES = 200


def capture_sql(
    database: str,
    operation: str,
    sql: str,
    params: Optional[Dict] = None,
    rows_affected: Optional[int] = None,
    duration_ms: Optional[float] = None,
    status: str = 'OK',
    error: Optional[str] = None
):
    """Append a SQL execution record to session state debug log."""
    if 'sql_debug_log' not in st.session_state:
        st.session_state.sql_debug_log = []

    entry = {
        'timestamp': datetime.now().strftime('%H:%M:%S.%f')[:-3],
        'database': database,
        'operation': operation,
        'sql': sql.strip(),
        'params': _sanitize_params(params),
        'rows': rows_affected,
        'duration_ms': round(duration_ms, 1) if duration_ms else None,
        'status': status,
        'error': error,
    }
    log = st.session_state.sql_debug_log
    log.append(entry)
    if len(log) > MAX_SQL_LOG_ENTRIES:
        st.session_state.sql_debug_log = log[-MAX_SQL_LOG_ENTRIES:]


def get_sql_log():
    """Return current SQL debug log (newest first)."""
    return list(reversed(st.session_state.get('sql_debug_log', [])))


def clear_sql_log():
    """Clear the SQL debug log."""
    st.session_state.sql_debug_log = []


def is_debug_enabled():
    """Check if SQL debug mode is enabled."""
    return st.session_state.get('sql_debug_enabled', False)


def _sanitize_params(params):
    """Redact password-like parameters for safe display."""
    if not params:
        return None
    safe = {}
    for k, v in params.items():
        if any(word in str(k).lower() for word in ('password', 'secret', 'key', 'token')):
            safe[k] = '***'
        else:
            safe[k] = repr(v) if not isinstance(v, (str, int, float, type(None))) else v
    return safe
