"""
Pytest configuration shared by all HCC Compression Advisor tests.

Test modules build their own fakes (pools, cursors, Streamlit session state);
see tests/unit/conftest.py for the unit-test fixtures.
"""
import atexit
import os
import shutil
import tempfile

# hcc_advisor.utils.logger opens its log file when first imported: point it at
# a throwaway directory before any test imports it, so the test run never
# writes to (or clears) the real application log.
_TEST_LOG_DIR = tempfile.mkdtemp(prefix='hcc_advisor_test_logs_')
os.environ['HCC_ADVISOR_LOG_DIR'] = _TEST_LOG_DIR
atexit.register(shutil.rmtree, _TEST_LOG_DIR, ignore_errors=True)
