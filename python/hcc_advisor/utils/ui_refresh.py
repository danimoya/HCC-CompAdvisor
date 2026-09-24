"""
Auto-refresh helper for Streamlit pages.

Streamlit 1.31 (pinned in requirements.txt) has no
``st.fragment(run_every=...)`` (added in 1.37), so a page that refreshes
itself has to finish rendering, wait, and then call ``st.rerun()``. Waiting
*before* the page content leaves the page blank, and reloading the browser
(``<meta http-equiv="refresh">``) starts a new Streamlit session, which drops
``st.session_state`` (login, toggles, selected menu item). ``st.rerun()``
keeps the session and every widget value.
"""

import math
import time

import streamlit as st

# Shortest wait between two automatic reruns, whatever the caller asks for.
MIN_INTERVAL_S = 2
# The wait is split into ticks of this length (see schedule_rerun).
_TICK_S = 1.0


def _format_remaining(seconds: float) -> str:
    secs = math.ceil(seconds)
    if secs >= 60:
        return f"{secs // 60}m {secs % 60:02d}s"
    return f"{secs}s"


def schedule_rerun(key: str, interval_s) -> bool:
    """Wait ``interval_s`` seconds, then rerun the script in the same session.

    Call it as the LAST statement of a page's render, so everything the page
    shows is on screen before the wait starts. It does nothing, and never
    sleeps, unless ``st.session_state[key]`` (the page's auto-refresh toggle)
    is truthy. A page that returns early or calls ``st.stop()`` before this
    call never schedules a rerun. ``interval_s`` is clamped to at least
    ``MIN_INTERVAL_S``.

    The wait is split into ~1 s ticks that update a small countdown caption.
    Each update is a Streamlit yield point: if the user interacts with the page
    during the wait (unticks the toggle, clicks a button, switches page),
    Streamlit abandons the wait and reruns at once with that interaction. The
    toggle's session-state value itself cannot change mid-run (Streamlit
    applies widget changes at the start of the next run), so there is nothing
    to poll for.

    Returns False when auto-refresh is off. When it is on, ``st.rerun()`` ends
    the current run, so the call does not return (it returns True only when
    ``st.rerun`` is mocked, e.g. in tests).
    """
    if not st.session_state.get(key):
        return False

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
