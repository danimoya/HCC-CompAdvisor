"""
Oracle version / platform rules for the compression DDL the advisor generates.

Pure (no database, no Streamlit). TargetQueries.generate_ddl, the SQL script
builder (sql_builder.build_compression_script) and the Scheduler CSV import all
decide through these functions, so a MOVE is built, or refused, the same way on
every path.

Rules (Oracle SQL Language Reference "ALTER TABLE", New Features guides):

* ALTER TABLE ... MOVE PARTITION / MOVE SUBPARTITION ... ONLINE: 12c Release 1
  (12.1). An online (sub)partition move maintains the local and global
  indexes, so none of them goes UNUSABLE.
* ALTER TABLE ... MOVE ONLINE of a non-partitioned heap table: 12c Release 2
  (12.2), as is UPDATE INDEXES on a table-level MOVE. Earlier releases accept
  ONLINE only for index-organized tables, which the advisor never compresses
  (basic/OLTP/HCC table compression does not apply to IOTs, and
  _discover_analysis_tables skips them).
* Below those releases a (sub)partition MOVE takes UPDATE INDEXES
  (update_index_clauses, 10g+) so its indexes stay usable; DML on that segment
  waits for the move. A table MOVE leaves every index on the table UNUSABLE,
  so the indexes are rebuilt afterwards.
* Hybrid Columnar Compression (COMPRESS FOR QUERY / ARCHIVE LOW / HIGH) needs
  Exadata storage (the registry's EXADATA platform); elsewhere the MOVE fails
  with ORA-64307.
"""

import math
import re
from typing import Optional, Tuple

from hcc_advisor.utils.logger import log_warning

OracleVersion = Tuple[int, int]

TABLE = 'TABLE'
PARTITION = 'PARTITION'
SUBPARTITION = 'SUBPARTITION'

# First release whose ALTER TABLE ... MOVE accepts ONLINE, per object level.
ONLINE_MOVE_SINCE = {
    TABLE: (12, 2),
    PARTITION: (12, 1),
    SUBPARTITION: (12, 1),
}

# What a MOVE carries in front of PARALLEL n (see move_modifier).
MOVE_ONLINE = 'ONLINE'
MOVE_UPDATE_INDEXES = 'UPDATE INDEXES'
MOVE_OFFLINE = ''

# "Release 19.0.0.0.0" (v$version.banner) / "Version 19.21.0.0.0" (banner_full)
_RELEASE_RE = re.compile(r'\b(?:release|version)\s+(\d{1,2})\.(\d{1,2})', re.IGNORECASE)
# a bare dotted version: "11.2.0.4.0", "19.3"
_DOTTED_RE = re.compile(r'(?<![\d.])(\d{1,2})\.(\d{1,2})(?:\.\d+)*')
# marketing name only: "19c", "11g", "23ai", "Oracle9i"
_MARKETING_RE = re.compile(r'(?<!\d)(\d{1,2})\s?(?:ai|c|g|i)\b', re.IGNORECASE)
# A marketing name before 18c covers several releases (12c = 12.1 and 12.2):
# assume the first, which has the fewest features.
_MARKETING_FIRST_MINOR = {10: 1, 11: 1, 12: 1}

_UNPARSED_LOGGED: set = set()


def _log_unknown_version(text: str) -> None:
    key = text[:200]
    if key in _UNPARSED_LOGGED:
        return
    _UNPARSED_LOGGED.add(key)
    log_warning(f"Oracle version {text!r} not recognised: generating DDL for a "
                f"modern release (ONLINE moves, 12.2+)")


def parse_oracle_version(value) -> Optional[OracleVersion]:
    """(major, minor) of a stored Oracle version, or None when unknown.

    Accepts the v$version banner kept in T_TARGET_DATABASES.ORACLE_VERSION
    ("Oracle Database 11g Enterprise Edition Release 11.2.0.4.0 - 64bit
    Production", "Oracle Database 23ai Free Release 23.0.0.0.0 - ..."), a bare
    version ("19.3.0.0.0") or a marketing name ("19c"). None, NaN, blanks and
    unrecognised text give None; unrecognised text is logged once.
    """
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return None
    text = str(value).strip()
    if not text or text.lower() in ('none', 'nan', 'unknown'):
        return None
    for pattern in (_RELEASE_RE, _DOTTED_RE):
        m = pattern.search(text)
        if m and int(m.group(1)) >= 8:
            return int(m.group(1)), int(m.group(2))
    m = _MARKETING_RE.search(text)
    if m and int(m.group(1)) >= 8:
        major = int(m.group(1))
        return major, _MARKETING_FIRST_MINOR.get(major, 0)
    _log_unknown_version(text)
    return None


def format_version(value) -> str:
    """"19.0" for a known version, "unknown" otherwise (script comments)."""
    ver = value if isinstance(value, tuple) else parse_oracle_version(value)
    return f"{ver[0]}.{ver[1]}" if ver else "unknown"


def object_level(partition_name=None, subpartition_name=None) -> str:
    """TABLE / PARTITION / SUBPARTITION for a MOVE of the given segment."""
    if subpartition_name:
        return SUBPARTITION
    if partition_name:
        return PARTITION
    return TABLE


def _level(value) -> str:
    level = str(value or TABLE).strip().upper()
    if level not in ONLINE_MOVE_SINCE:
        raise ValueError(f"Unknown object level for a MOVE: {value!r}")
    return level


def supports_online_move(version, level: str = TABLE) -> bool:
    """True if ALTER TABLE ... MOVE [SUB]PARTITION ... ONLINE works at `level`
    on this Oracle version (a banner, a bare version or a (major, minor)
    tuple). An unknown version is assumed to be a modern release."""
    ver = version if isinstance(version, tuple) else parse_oracle_version(version)
    if ver is None:
        return True
    return tuple(ver[:2]) >= ONLINE_MOVE_SINCE[_level(level)]


def move_modifier(version, level: str = TABLE) -> str:
    """What the MOVE carries in front of PARALLEL n on this version:

    MOVE_ONLINE          online move; indexes stay usable
    MOVE_UPDATE_INDEXES  (sub)partition move before 12.1; indexes stay usable
    MOVE_OFFLINE         table move before 12.2; its indexes go UNUSABLE
    """
    level = _level(level)
    if supports_online_move(version, level):
        return MOVE_ONLINE
    if level in (PARTITION, SUBPARTITION):
        return MOVE_UPDATE_INDEXES
    return MOVE_OFFLINE


def move_leaves_indexes_unusable(version, level: str = TABLE) -> bool:
    """True if the MOVE generated for this version leaves the table's indexes
    UNUSABLE, so they must be rebuilt afterwards."""
    return move_modifier(version, level) == MOVE_OFFLINE


# ----------------------------------------------------------------------------
# Platform: Hybrid Columnar Compression
# ----------------------------------------------------------------------------

EXADATA = 'EXADATA'
HCC_NOT_SUPPORTED = 'HCC NOT SUPPORTED'

HCC_COMPRESSION_TYPES = frozenset({
    'QUERY LOW', 'QUERY HIGH', 'ARCHIVE LOW', 'ARCHIVE HIGH',
    'QUERY_LOW', 'QUERY_HIGH', 'ARCHIVE_LOW', 'ARCHIVE_HIGH',
})


def is_hcc_compression(value) -> bool:
    """True for a Hybrid Columnar Compression type (QUERY/ARCHIVE LOW/HIGH)."""
    return bool(value) and not (isinstance(value, float) and math.isnan(value)) \
        and str(value).strip().upper() in HCC_COMPRESSION_TYPES


def normalize_platform(value) -> Optional[str]:
    """Upper-cased platform type, or None for None/NaN/blank."""
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return None
    text = str(value).strip().upper()
    return text if text and text not in ('NONE', 'NAN') else None


def hcc_block_reason(compression_type, platform_type) -> Optional[str]:
    """Why compression_type cannot be applied on a target of platform_type,
    or None if it can. The one platform check behind every path that turns a
    compression type into DDL or a job.

    Only HCC types are ever refused, and only when the platform is known and
    not EXADATA. An unknown platform (None: the target could not be looked
    up) is not checked here; Oracle still refuses the MOVE with ORA-64307.
    """
    if not is_hcc_compression(compression_type):
        return None
    platform = normalize_platform(platform_type)
    if platform is None or platform == EXADATA:
        return None
    ctype = str(compression_type).strip().upper().replace('_', ' ')
    return (f"{HCC_NOT_SUPPORTED}: {ctype} is Hybrid Columnar Compression, which "
            f"needs Exadata storage; the target's platform is {platform} "
            f"(the MOVE would fail with ORA-64307)")
