"""CLI entry point for hcc-advisor."""

import sys
from pathlib import Path


def main():
    """Launch the HCC Advisor Streamlit dashboard."""
    app_path = str(Path(__file__).parent / "app.py")

    # First run without DASHBOARD_PASSWORD: issue the one-time setup token now so
    # it is printed with the startup output. Streamlit runs the app in this same
    # process, so the login page sees the same token (it also issues one lazily
    # when started another way, e.g. `streamlit run`).
    try:
        from hcc_advisor.auth import ensure_bootstrap_token
        ensure_bootstrap_token()
    except Exception:
        pass

    sys.argv = ["streamlit", "run", app_path,
                "--server.headless=true"] + sys.argv[1:]

    from streamlit.web.cli import main as st_main
    st_main()


if __name__ == "__main__":
    main()
