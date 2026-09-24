"""
Central schema version handling for HCC Compression Advisor.

The single source of truth for the version is ``hcc_advisor.__version__``: a
fresh install stamps it into T_SCHEMA_METADATA.schema_version, and the
non-destructive Upgrade stamps it after applying the pending SQL patches.

Only a schema whose MAJOR.MINOR is lower than the application's needs an
upgrade. A different patch level, or a schema newer than the application, is
reported as a notice but never routes users into the deployment page.
"""

import re
from typing import Optional, Tuple

from hcc_advisor import __version__

# schema_status() results
STATUS_MISSING = 'missing'        # central schema not deployed (or DB unreachable)
STATUS_UNKNOWN = 'unknown'        # deployed, but schema_version absent / unparseable
STATUS_OUTDATED = 'outdated'      # schema MAJOR.MINOR lower than the app's -> Upgrade
STATUS_CURRENT = 'current'        # same version
STATUS_PATCH_DIFF = 'patch_diff'  # same MAJOR.MINOR, different patch level
STATUS_NEWER = 'newer'            # schema MAJOR.MINOR higher than the app's

# Statuses that send the session to the deployment page (Existing Installation
# panel). An unknown version goes there too: Upgrade applies the patches that
# check.sql reports as missing and then stamps a proper version.
_UPGRADE_STATUSES = frozenset({STATUS_MISSING, STATUS_UNKNOWN, STATUS_OUTDATED})

# '3', '3.1', 'v3.1.2', '3.1.2-rc1', '3.1.2+build'
_VERSION_RE = re.compile(r'[vV]?(\d+)(?:\.(\d+))?(?:\.(\d+))?(?:[-+].*)?')


def parse_version(value) -> Optional[Tuple[int, int, int]]:
    """
    Parse a version string into (major, minor, patch).

    Missing minor/patch parts default to 0. Returns None for None, empty or
    unparseable values instead of raising.
    """
    if value is None:
        return None
    m = _VERSION_RE.fullmatch(str(value).strip())
    if not m:
        return None
    major, minor, patch = (int(g) if g is not None else 0 for g in m.groups())
    return major, minor, patch


def schema_status(deployed: bool, schema_version, app_version: str = __version__) -> str:
    """Classify the central schema against the application version (STATUS_*)."""
    if not deployed:
        return STATUS_MISSING
    schema = parse_version(schema_version)
    app = parse_version(app_version)
    if schema is None or app is None:
        return STATUS_UNKNOWN
    if schema[:2] < app[:2]:
        return STATUS_OUTDATED
    if schema[:2] > app[:2]:
        return STATUS_NEWER
    if schema != app:
        return STATUS_PATCH_DIFF
    return STATUS_CURRENT


def needs_upgrade(status: str) -> bool:
    """True when the session must go to the deployment page before the dashboard."""
    return status in _UPGRADE_STATUSES


def version_is_behind(schema_version, app_version: str = __version__) -> bool:
    """
    True when stamping `app_version` would move the schema forward: its version
    is unknown/unparseable or strictly lower (patch level included). Guards
    the Upgrade against stamping a newer schema down to an older version.
    """
    schema = parse_version(schema_version)
    app = parse_version(app_version)
    if app is None:
        return False
    return schema is None or schema < app


def version_notice(status: str, schema_version, app_version: str = __version__) -> Optional[str]:
    """Message for a schema that is usable but not an exact match (else None)."""
    if status == STATUS_NEWER:
        return (f"Central schema version {schema_version} is newer than this "
                f"application ({app_version}). Upgrade the HCC Advisor package; "
                "do not re-install the schema.")
    if status == STATUS_PATCH_DIFF:
        return (f"Central schema version {schema_version} differs from the "
                f"application ({app_version}) at patch level only. No upgrade is "
                "required; pending SQL patches, if any, are listed under "
                "Admin > SQL Patches.")
    return None


# A schema counts as deployed when T_TARGET_DATABASES has the DB_HOST column
# (renamed from HOST in 2.0.0); older layouts can only be re-installed.
DEPLOYED_CHECK_SQL = """
    SELECT COUNT(*) FROM user_tab_columns
    WHERE table_name = 'T_TARGET_DATABASES' AND column_name = 'DB_HOST'"""

_METADATA_DDL = """
    CREATE TABLE T_SCHEMA_METADATA (
        KEY         VARCHAR2(100) PRIMARY KEY,
        VALUE       VARCHAR2(500) NOT NULL,
        UPDATED_AT  TIMESTAMP DEFAULT SYSTIMESTAMP
    )"""

_UPSERT_METADATA = """
    MERGE INTO t_schema_metadata tgt
    USING (SELECT :k AS key FROM DUAL) src ON (tgt.key = src.key)
    WHEN MATCHED THEN UPDATE SET value = :v
    WHEN NOT MATCHED THEN INSERT (key, value) VALUES (:k, :v)"""

_UPSERT_UPGRADED_AT = """
    MERGE INTO t_schema_metadata tgt
    USING (SELECT 'last_upgraded_at' AS key,
                  TO_CHAR(SYSTIMESTAMP, 'YYYY-MM-DD HH24:MI:SS') AS value
           FROM DUAL) src ON (tgt.key = src.key)
    WHEN MATCHED THEN UPDATE SET value = src.value
    WHEN NOT MATCHED THEN INSERT (key, value) VALUES (src.key, src.value)"""


def ensure_schema_metadata_table(conn) -> None:
    """Create T_SCHEMA_METADATA if the schema lacks it. Raises on failure."""
    cur = conn.cursor()
    try:
        cur.execute("SELECT COUNT(*) FROM user_tables WHERE table_name = 'T_SCHEMA_METADATA'")
        if not cur.fetchone()[0]:
            cur.execute(_METADATA_DDL)
    finally:
        cur.close()


def stamp_schema_version(conn, version: str = __version__, upgraded: bool = False) -> None:
    """
    Record `version` as T_SCHEMA_METADATA.schema_version and commit.

    Creates T_SCHEMA_METADATA if the schema lacks it. With upgraded=True
    also stamps last_upgraded_at. Raises on failure.

    Args:
        conn: oracledb connection to the central schema
        version: Version to record (defaults to the package version)
        upgraded: True when called after applying upgrade patches
    """
    ensure_schema_metadata_table(conn)
    cur = conn.cursor()
    try:
        cur.execute(_UPSERT_METADATA, {'k': 'schema_version', 'v': version})
        if upgraded:
            cur.execute(_UPSERT_UPGRADED_AT)
        conn.commit()
    finally:
        cur.close()
