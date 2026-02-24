"""CLI entry point for hcc-advisor."""

import sys
from pathlib import Path


def main():
    """Launch the HCC Advisor Streamlit dashboard."""
    app_path = str(Path(__file__).parent / "app.py")

    sys.argv = ["streamlit", "run", app_path,
                "--server.headless=true"] + sys.argv[1:]

    from streamlit.web.cli import main as st_main
    st_main()


if __name__ == "__main__":
    main()
