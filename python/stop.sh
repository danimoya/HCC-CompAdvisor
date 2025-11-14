#!/bin/bash
#
# HCC Compression Advisor Dashboard Stop Script
#

echo "Stopping HCC Compression Advisor Dashboard..."

# Find and kill streamlit processes
PIDS=$(pgrep -f "streamlit run app.py")

if [ -z "$PIDS" ]; then
    echo "No running dashboard found"
    exit 0
fi

echo "Found processes: $PIDS"
kill $PIDS

echo "Dashboard stopped"
