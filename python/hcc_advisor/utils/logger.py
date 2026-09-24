"""
Application Logger for HCC Compression Advisor
Provides detailed logging for debugging and error tracking

The log file (``hcc_advisor.log`` in the log directory) rotates by size, so a
long-running container cannot fill its log volume, and every parameter /
context dict is passed through utils/redaction.py before it is written.

Settings (environment variables, see python/.env.example):
    HCC_ADVISOR_LOG_DIR  log directory (default /app/logs in Docker, else
                         ~/.local/share/hcc-advisor/logs)
    LOG_LEVEL            file log level, default INFO; DEBUG also logs every
                         SQL statement the connectors run
    LOG_MAX_MB           size at which the file is rotated, default 10
    LOG_BACKUP_COUNT     rotated files kept (hcc_advisor.log.1 ...), default 5
"""

import logging
import math
import os
from logging.handlers import RotatingFileHandler
from pathlib import Path

from hcc_advisor.utils.redaction import redact


def _get_log_dir() -> Path:
    """Determine log directory: env var > /app/logs (Docker) > ~/.local/share/hcc-advisor/logs."""
    env = os.getenv('HCC_ADVISOR_LOG_DIR')
    if env:
        return Path(env)

    docker_path = Path("/app/logs")
    if docker_path.exists() and os.access(str(docker_path), os.W_OK):
        return docker_path

    return Path.home() / '.local' / 'share' / 'hcc-advisor' / 'logs'


def _env_level(name: str = 'LOG_LEVEL', default: int = logging.INFO) -> int:
    """Log level from the environment (DEBUG, INFO, WARNING, ERROR, CRITICAL)."""
    level = logging.getLevelName(os.getenv(name, '').strip().upper())
    return level if isinstance(level, int) else default


def _env_number(name: str, default, minimum):
    """Number from the environment, `default` if unset or invalid, at least `minimum`."""
    try:
        value = float(os.getenv(name, '').strip())
    except ValueError:
        return default
    if not math.isfinite(value):
        return default
    return max(minimum, type(default)(value))


# Create logs directory if it doesn't exist
LOG_DIR = _get_log_dir()
LOG_DIR.mkdir(parents=True, exist_ok=True)

# One stable file name: the handler renames it to hcc_advisor.log.1, .2, ...
# when it reaches LOG_MAX_BYTES and deletes the oldest beyond LOG_BACKUP_COUNT,
# so the logs never take more than LOG_MAX_BYTES * (LOG_BACKUP_COUNT + 1).
LOG_FILE = LOG_DIR / "hcc_advisor.log"
# Files an older version wrote (a new dated file per process start, never
# rotated). Nothing writes them any more; clear_logs() removes them.
LEGACY_LOG_GLOB = "hcc_advisor_*.log"

LOG_LEVEL = _env_level()
LOG_MAX_BYTES = int(_env_number('LOG_MAX_MB', 10.0, 1.0) * 1024 * 1024)
# At least one backup: with 0, RotatingFileHandler never truncates the file.
LOG_BACKUP_COUNT = _env_number('LOG_BACKUP_COUNT', 5, 1)

# The log viewer reads at most this many bytes from the end of the log, so its
# cost does not grow with the file.
MAX_TAIL_BYTES = 2 * 1024 * 1024
_TAIL_CHUNK_BYTES = 64 * 1024

# Configure logging format
LOG_FORMAT = "%(asctime)s | %(levelname)-8s | %(name)s | %(funcName)s:%(lineno)d | %(message)s"
DATE_FORMAT = "%Y-%m-%d %H:%M:%S"


def _make_file_handler(path, max_bytes: int, backup_count: int) -> RotatingFileHandler:
    handler = RotatingFileHandler(path, maxBytes=max_bytes, backupCount=backup_count,
                                  encoding='utf-8')
    handler.setFormatter(logging.Formatter(LOG_FORMAT, DATE_FORMAT))
    return handler


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

    # The logger itself filters at LOG_LEVEL, so DEBUG records are dropped
    # before they are formatted unless LOG_LEVEL=DEBUG.
    logger.setLevel(LOG_LEVEL)

    # File handler - rotating, logs LOG_LEVEL and above
    file_handler = _make_file_handler(LOG_FILE, LOG_MAX_BYTES, LOG_BACKUP_COUNT)
    file_handler.setLevel(LOG_LEVEL)

    # Console handler - logs warnings and above to console
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.WARNING)
    console_handler.setFormatter(logging.Formatter(LOG_FORMAT, DATE_FORMAT))

    logger.addHandler(file_handler)
    logger.addHandler(console_handler)

    return logger


# Create default application logger
app_logger = setup_logger("hcc_advisor")


def _file_handler():
    """The handler that writes LOG_FILE, or None.

    Looked up on the logger rather than kept in a module global: if this
    module is re-imported, setup_logger() keeps the handler the first import
    attached.
    """
    target = os.path.abspath(LOG_FILE)
    for handler in app_logger.handlers:
        if isinstance(handler, logging.FileHandler) and handler.baseFilename == target:
            return handler
    return None


def log_error(error: Exception, context: str = "", extra_info: dict = None):
    """
    Log an error with full details

    Args:
        error: The exception that occurred
        context: Description of what was happening when error occurred
        extra_info: Additional information dictionary (secrets are redacted)
    """
    import traceback

    extra_info = redact(extra_info)
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
        params: Query parameters (secrets are redacted)
    """
    # Truncate query if too long
    query_preview = query[:500] + "..." if len(query) > 500 else query

    app_logger.error(
        f"DATABASE ERROR: {type(error).__name__}: {error}\n"
        f"Query: {query_preview}\n"
        f"Params: {redact(params)}"
    )


def log_info(message: str, **kwargs):
    """Log an info message"""
    if kwargs:
        message = f"{message} | {redact(kwargs)}"
    app_logger.info(message)


def log_warning(message: str, **kwargs):
    """Log a warning message"""
    if kwargs:
        message = f"{message} | {redact(kwargs)}"
    app_logger.warning(message)


def log_debug(message: str, **kwargs):
    """Log a debug message"""
    # Called for every SQL statement: skip the formatting unless DEBUG is on.
    if not app_logger.isEnabledFor(logging.DEBUG):
        return
    if kwargs:
        message = f"{message} | {redact(kwargs)}"
    app_logger.debug(message)


def _log_files_newest_first():
    """The current log file, then its rotated backups (.1 is the most recent)."""
    files = [LOG_FILE]
    for i in range(1, LOG_BACKUP_COUNT + 1):
        backup = Path(f"{LOG_FILE}.{i}")
        if not backup.exists():
            break
        files.append(backup)
    return files


def _tail_lines(max_lines: int, keep=None, max_bytes: int = None) -> list:
    """The last `max_lines` lines of the log (only those `keep` accepts, if given).

    Reads backwards from the end in chunks, continuing into the rotated
    backups while more lines are needed, and stops after `max_bytes` in total
    (default MAX_TAIL_BYTES), so the cost depends on the lines asked for,
    never on the file size. Returned oldest first, without line endings.
    """
    newest_first = []
    budget = MAX_TAIL_BYTES if max_bytes is None else max_bytes
    for path in _log_files_newest_first():
        if len(newest_first) >= max_lines or budget <= 0:
            break
        try:
            f = open(path, 'rb')
        except FileNotFoundError:
            continue
        with f:
            f.seek(0, os.SEEK_END)
            pos = f.tell()
            carry = b''  # start of the earliest line read so far (maybe partial)
            first_block = True
            while pos > 0 and budget > 0 and len(newest_first) < max_lines:
                step = min(_TAIL_CHUNK_BYTES, pos, budget)
                pos -= step
                budget -= step
                f.seek(pos)
                parts = (f.read(step) + carry).split(b'\n')
                if first_block and parts[-1] == b'':
                    parts.pop()  # the newline that ends the file
                first_block = False
                carry = parts.pop(0)  # may continue in the bytes before `pos`
                for raw in reversed(parts):
                    line = raw.decode('utf-8', errors='replace').rstrip('\r')
                    if keep is None or keep(line):
                        newest_first.append(line)
                        if len(newest_first) >= max_lines:
                            break
            # At the start of the file the carry is a whole line; if the byte
            # budget ran out first it is a fragment and is dropped.
            if pos == 0 and carry and len(newest_first) < max_lines:
                line = carry.decode('utf-8', errors='replace').rstrip('\r')
                if keep is None or keep(line):
                    newest_first.append(line)
    newest_first.reverse()
    return newest_first


def _is_error_line(line: str) -> bool:
    return '| ERROR' in line or '| CRITICAL' in line


def get_recent_logs(lines: int = 100) -> str:
    """
    Get recent log entries

    Args:
        lines: Number of recent lines to return

    Returns:
        String containing recent log entries
    """
    try:
        tail = _tail_lines(lines)
    except Exception as e:
        return f"Error reading logs: {e}"
    if tail:
        return '\n'.join(tail) + '\n'
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
        tail = _tail_lines(lines, keep=_is_error_line)
    except Exception as e:
        return f"Error reading logs: {e}"
    if tail:
        return '\n'.join(tail) + '\n'
    return "No error logs available"


def clear_logs(cleared_by: str = None) -> str:
    """
    Empty the log file and delete the rotated backups and legacy dated files.

    The file handler keeps LOG_FILE open, so the file is truncated in place
    (the handler's stream closed, the file emptied, the stream reopened, all
    under the handler's lock so no record or rollover interleaves) instead of
    deleted: deleting it left the handler writing to an unlinked file, and the
    viewer showed "No logs" until the app was restarted. Logging continues in
    the emptied file at once.

    Args:
        cleared_by: Who cleared the logs, recorded in the first new entry

    Returns:
        Status message
    """
    handler = _file_handler()
    if handler is not None:
        handler.acquire()
    try:
        if handler is not None and handler.stream is not None:
            handler.stream.close()
            # A handler with no stream opens the file again on its next
            # record, so logging goes on even if something below fails.
            handler.stream = None
        if LOG_FILE.exists():
            with open(LOG_FILE, 'w', encoding='utf-8'):
                pass
        removed = 0
        old_files = list(LOG_DIR.glob(f"{LOG_FILE.name}.*")) + list(LOG_DIR.glob(LEGACY_LOG_GLOB))
        for old in old_files:
            old.unlink()
            removed += 1
        if handler is not None:
            handler.stream = handler._open()
    except Exception as e:
        return f"Error clearing logs: {e}"
    finally:
        if handler is not None:
            handler.release()

    app_logger.warning(
        f"Log cleared by {cleared_by or 'unknown user'}"
        f" ({removed} rotated/old log file(s) deleted)"
    )
    if removed:
        return f"Log cleared; deleted {removed} rotated/old log file(s)"
    return "Log cleared"
