"""
Application Logger for HCC Compression Advisor
Provides detailed logging for debugging and error tracking
"""

import logging
import os
from datetime import datetime
from pathlib import Path

# Create logs directory if it doesn't exist
LOG_DIR = Path("/app/logs")
LOG_DIR.mkdir(parents=True, exist_ok=True)

# Log file path with date
LOG_FILE = LOG_DIR / f"hcc_advisor_{datetime.now().strftime('%Y%m%d')}.log"

# Configure logging format
LOG_FORMAT = "%(asctime)s | %(levelname)-8s | %(name)s | %(funcName)s:%(lineno)d | %(message)s"
DATE_FORMAT = "%Y-%m-%d %H:%M:%S"


def setup_logger(name: str = "hcc_advisor") -> logging.Logger:
    """
    Set up and return a configured logger

    Args:
        name: Logger name (usually module name)

    Returns:
        Configured logger instance
    """
    logger = logging.getLogger(name)

    # Avoid adding handlers multiple times
    if logger.handlers:
        return logger

    logger.setLevel(logging.DEBUG)

    # File handler - logs everything to file
    file_handler = logging.FileHandler(LOG_FILE, encoding='utf-8')
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(logging.Formatter(LOG_FORMAT, DATE_FORMAT))

    # Console handler - logs warnings and above to console
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.WARNING)
    console_handler.setFormatter(logging.Formatter(LOG_FORMAT, DATE_FORMAT))

    logger.addHandler(file_handler)
    logger.addHandler(console_handler)

    return logger


# Create default application logger
app_logger = setup_logger("hcc_advisor")


def log_error(error: Exception, context: str = "", extra_info: dict = None):
    """
    Log an error with full details

    Args:
        error: The exception that occurred
        context: Description of what was happening when error occurred
        extra_info: Additional information dictionary
    """
    import traceback

    error_details = {
        "error_type": type(error).__name__,
        "error_message": str(error),
        "context": context,
        "traceback": traceback.format_exc()
    }

    if extra_info:
        error_details.update(extra_info)

    app_logger.error(
        f"ERROR in {context}: {type(error).__name__}: {error}\n"
        f"Extra Info: {extra_info}\n"
        f"Traceback:\n{traceback.format_exc()}"
    )

    return error_details


def log_db_error(error: Exception, query: str = "", params: dict = None):
    """
    Log a database error with query details

    Args:
        error: The database exception
        query: The SQL query that failed
        params: Query parameters
    """
    # Truncate query if too long
    query_preview = query[:500] + "..." if len(query) > 500 else query

    app_logger.error(
        f"DATABASE ERROR: {type(error).__name__}: {error}\n"
        f"Query: {query_preview}\n"
        f"Params: {params}"
    )


def log_info(message: str, **kwargs):
    """Log an info message"""
    if kwargs:
        message = f"{message} | {kwargs}"
    app_logger.info(message)


def log_warning(message: str, **kwargs):
    """Log a warning message"""
    if kwargs:
        message = f"{message} | {kwargs}"
    app_logger.warning(message)


def log_debug(message: str, **kwargs):
    """Log a debug message"""
    if kwargs:
        message = f"{message} | {kwargs}"
    app_logger.debug(message)


def get_recent_logs(lines: int = 100) -> str:
    """
    Get recent log entries

    Args:
        lines: Number of recent lines to return

    Returns:
        String containing recent log entries
    """
    try:
        if LOG_FILE.exists():
            with open(LOG_FILE, 'r', encoding='utf-8') as f:
                all_lines = f.readlines()
                return ''.join(all_lines[-lines:])
    except Exception as e:
        return f"Error reading logs: {e}"

    return "No logs available"


def get_error_logs(lines: int = 50) -> str:
    """
    Get recent error log entries only

    Args:
        lines: Number of recent error lines to return

    Returns:
        String containing recent error entries
    """
    try:
        if LOG_FILE.exists():
            with open(LOG_FILE, 'r', encoding='utf-8') as f:
                error_lines = [line for line in f if '| ERROR' in line or '| CRITICAL' in line]
                return ''.join(error_lines[-lines:])
    except Exception as e:
        return f"Error reading logs: {e}"

    return "No error logs available"
