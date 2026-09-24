"""
Redaction of secrets in bind parameters and log context.

Shared by the SQL Debug Console (utils/sql_debug.py) and the application log
(utils/logger.py), so a password, encrypted password, key or token passed as a
bind parameter or as log context never reaches either of them.
"""

from collections.abc import Mapping

REDACTED = '***'

# Substrings that mark a key as sensitive; matched case-insensitively against
# the key name. Covers password / password_encrypted / short-form pwd/passwd /
# dash_pwd / passphrase / credential / secret / key / api_key / token /
# authorization / cookie variants.
SENSITIVE_KEY_PARTS = (
    'password', 'passwd', 'pwd', 'passphrase', 'secret', 'key', 'token', 'cred',
    'authorization', 'cookie',
)

# Containers nested deeper than this are replaced by a placeholder instead of
# being walked (guards against self-referencing structures).
_MAX_DEPTH = 10


def is_sensitive_key(key) -> bool:
    """True if a parameter / context key names a secret."""
    name = str(key).lower()
    return any(part in name for part in SENSITIVE_KEY_PARTS)


def redact(value, _depth: int = 0):
    """Return a copy of ``value`` with the values of sensitive keys masked.

    Walks dicts (any Mapping), namedtuples, lists, tuples and sets at any
    depth, so a secret nested in a context dict
    (``{'db_data': {'password_encrypted': ...}}``) or in a list of bind dicts
    (executemany) is masked too. Keys are kept; only the values of sensitive
    keys become ``'***'`` (a namedtuple becomes a dict, a set a list). Other
    values are returned unchanged, and the input is never modified. Positional
    binds carry no key, so they cannot be recognised and are kept as they are.
    """
    if _depth > _MAX_DEPTH:
        return '...'
    if isinstance(value, tuple) and hasattr(value, '_asdict'):
        value = value._asdict()  # namedtuple: its field names are keys too
    if isinstance(value, Mapping):
        return {
            k: REDACTED if is_sensitive_key(k) else redact(v, _depth + 1)
            for k, v in value.items()
        }
    if isinstance(value, tuple):
        return tuple(redact(v, _depth + 1) for v in value)
    if isinstance(value, (list, set, frozenset)):
        return [redact(v, _depth + 1) for v in value]
    return value
