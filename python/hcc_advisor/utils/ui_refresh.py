"""
Auto-refresh helper for Streamlit pages.

Streamlit 1.31 (pinned in requirements.txt) has no
``st.fragment(run_every=...)`` (added in 1.37), so a page that refreshes
itself has to finish rendering, wait, and then call ``st.rerun()``. Waiting
*before* the page content leaves the page blank, and reloading the browser
(``<meta http-equiv="refresh">``) starts a new Streamlit session, which drops
``st.session_state`` (login, toggles, selected menu item). ``st.rerun()``
keeps the session and every widget value.

A page only states that it wants a refresh (``schedule_rerun``). When the page
runs inside app.py, app.py still renders more after the page function returns
(the SQL Debug Console), so it defers the wait: ``defer_reruns()`` before the
page, ``run_deferred_rerun()`` as the very last statement of the run. A page
rendered on its own (no ``defer_reruns()`` in the run, e.g. a test calling the
page function directly) waits inside ``schedule_rerun`` as before.
"""

import math
import time

import streamlit as st

# Shortest wait between two automatic reruns, whatever the caller asks for.
MIN_INTERVAL_S = 2
# The wait is split into ticks of this length (see schedule_rerun).
_TICK_S = 1.0
# Session-state key that holds the refresh a page asked for while reruns are
# deferred: None until a page schedules one, then (toggle key, interval).
# Only present between defer_reruns() and run_deferred_rerun().
_PENDING_KEY = '_ui_refresh_pending'


def _format_remaining(seconds: float) -> str:
    secs = math.ceil(seconds)
    if secs >= 60:
        return f"{secs // 60}m {secs % 60:02d}s"
    return f"{secs}s"


def _wait_then_rerun(interval_s) -> bool:
    remaining = max(float(MIN_INTERVAL_S), float(interval_s))
    countdown = st.empty()
    while remaining > 0:
        countdown.caption(f"Auto-refresh on: next update in {_format_remaining(remaining)}")
        step = min(_TICK_S, remaining)
        time.sleep(step)
        remaining -= step

    countdown.caption("Auto-refresh on: refreshing...")
    st.rerun()
    return True


def schedule_rerun(key: str, interval_s) -> bool:
    """Wait ``interval_s`` seconds, then rerun the script in the same session.

    Call it as the LAST statement of a page's render, so everything the page
    shows is on screen before the wait starts. It does nothing, and never
    sleeps, unless ``st.session_state[key]`` (the page's auto-refresh toggle)
    is truthy. A page that returns early or calls ``st.stop()`` before this
    call never schedules a rerun. ``interval_s`` is clamped to at least
    ``MIN_INTERVAL_S``.

    If the host script called ``defer_reruns()`` in this run (app.py does),
    the call only records the refresh and returns True at once; the host's
    ``run_deferred_rerun()`` then waits and reruns after the rest of the host's
    output (the SQL Debug Console). If a refresh is already recorded in this
    run, the first one is kept, as when waiting here the first call never
    returns.

    The wait is split into ~1 s ticks that update a small countdown caption.
    Each update is a Streamlit yield point: if the user interacts with the page
    during the wait (unticks the toggle, clicks a button, switches page),
    Streamlit abandons the wait and reruns at once with that interaction. The
    toggle's session-state value itself cannot change mid-run (Streamlit
    applies widget changes at the start of the next run), so there is nothing
    to poll for.

    Returns False when auto-refresh is off. When it is on, ``st.rerun()`` ends
    the current run, so the call does not return (it returns True only when
    the rerun is deferred, or when ``st.rerun`` is mocked, e.g. in tests).
    """
    if not st.session_state.get(key):
        return False

    if _PENDING_KEY in st.session_state:
        if st.session_state[_PENDING_KEY] is None:
            st.session_state[_PENDING_KEY] = (key, interval_s)
        return True

    return _wait_then_rerun(interval_s)


def defer_reruns() -> None:
    """Make ``schedule_rerun`` calls in this run record the refresh, not wait.

    For a host script that renders more after the page function returns:
    call it before the page renders, and ``run_deferred_rerun()`` as the very
    last statement of the run. Also drops a refresh recorded by an earlier run
    that raised or stopped before reaching ``run_deferred_rerun()``.
    """
    st.session_state[_PENDING_KEY] = None


def run_deferred_rerun() -> bool:
    """Wait for and run the refresh a page recorded in this run, if any.

    Call it as the very last statement of the host script's run (after
    ``defer_reruns()`` and the page). Ends the deferral, so a later
    ``schedule_rerun`` call without ``defer_reruns()`` waits in place again.
    Waits exactly as ``schedule_rerun`` does on its own (clamped interval,
    1 s countdown ticks, then ``st.rerun()``). Returns False, without
    sleeping, when no refresh was recorded or its toggle is off; otherwise
    ``st.rerun()`` ends the run (True only when ``st.rerun`` is mocked).
    """
    pending = st.session_state.get(_PENDING_KEY)
    if _PENDING_KEY in st.session_state:
        del st.session_state[_PENDING_KEY]
    if not pending:
        return False
    key, interval_s = pending
    if not st.session_state.get(key):
        return False
    return _wait_then_rerun(interval_s)
