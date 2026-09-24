"""
Leaf-segment rule for totals over T_COMPRESSION_ANALYSIS.

An analysis run with partitions stores the TABLE row (its size covers every
segment of the table) *and* one row per partition, or per subpartition for
composite partitioning. Summing every row counts the same bytes two or three
times, so sizes, savings, averages and counts are taken over leaf segments.
Per table (DATABASE_ID, OWNER, OBJECT_NAME):

- if it has partition/subpartition rows and the TABLE row is not newer than
  all of them, its partition/subpartition rows count and the TABLE row does not;
  a PARTITION row gives way to its own SUBPARTITION rows;
- otherwise (no child rows, or a later table-only analysis refreshed the TABLE
  row, e.g. a Quick Scan with partitions followed by a Full Analysis without)
  the TABLE row counts and the older child rows do not.

Siblings are matched per object, not per ADVISOR_RUN_ID: the central table
keeps one row per segment (UNQ_COMP_ANALYSIS_OBJECT, refreshed by MERGE), so
rows of one table can come from different runs. "Newer" compares
ANALYSIS_TIMESTAMP (set on every MERGE); rows stored by one run tie, and a tie
or a missing timestamp goes to the child rows.

Object-level lists (recommendations, per-object detail) keep every row; only
aggregates apply this rule. leaf_analysis_sql() is the SQL form,
leaf_segment_mask() / leaf_segments() the in-memory form.
"""

from typing import Any, Dict, List, Optional, Union

import pandas as pd

# Inline view over T_COMPRESSION_ANALYSIS returning only leaf-segment rows, with
# every column of the table (plus leaf_* helper columns). Built from window
# functions so it is one scan; an outer filter on DATABASE_ID is pushed inside.
_LEAF_ANALYSIS_SQL = """(
                SELECT *
                FROM (
                    SELECT ca.*,
                           COUNT(ca.partition_name) OVER (
                               PARTITION BY ca.database_id, ca.owner, ca.object_name) AS leaf_n_children,
                           MAX(CASE WHEN ca.partition_name IS NULL THEN ca.analysis_timestamp END) OVER (
                               PARTITION BY ca.database_id, ca.owner, ca.object_name) AS leaf_table_ts,
                           MAX(CASE WHEN ca.partition_name IS NOT NULL THEN ca.analysis_timestamp END) OVER (
                               PARTITION BY ca.database_id, ca.owner, ca.object_name) AS leaf_child_ts,
                           COUNT(ca.subpartition_name) OVER (
                               PARTITION BY ca.database_id, ca.owner, ca.object_name,
                                            ca.partition_name) AS leaf_n_subs
                    FROM t_compression_analysis ca
                )
                WHERE CASE WHEN leaf_n_children = 0 OR leaf_table_ts > leaf_child_ts
                           THEN 'TABLE' ELSE 'CHILDREN' END
                      = CASE WHEN partition_name IS NULL THEN 'TABLE' ELSE 'CHILDREN' END
                  AND (subpartition_name IS NOT NULL OR leaf_n_subs = 0)
            )"""

# Column spellings accepted in memory: raw analysis rows (OWNER/OBJECT_NAME)
# and get_recommendations() output (TABLE_OWNER/TABLE_NAME). Case-insensitive.
_KEY_COLUMNS = (('DATABASE_ID',), ('OWNER', 'TABLE_OWNER'), ('OBJECT_NAME', 'TABLE_NAME'))

Rows = Union[pd.DataFrame, List[Dict[str, Any]]]


def leaf_analysis_sql() -> str:
    """Parenthesised inline view of the leaf-segment rows of T_COMPRESSION_ANALYSIS.
    Aggregates select from it instead of the table:
    ``FROM {leaf_analysis_sql()} a WHERE a.database_id = :database_id``."""
    return _LEAF_ANALYSIS_SQL


def _present(value: Any) -> bool:
    """True for a real value (not None/NaN/NaT/NA/'')."""
    if value is None or (not isinstance(value, str) and pd.isna(value)):
        return False
    return value != ''


def _column(df: pd.DataFrame, *names: str) -> Optional[pd.Series]:
    by_upper = {str(c).upper(): c for c in df.columns}
    for name in names:
        if name in by_upper:
            return df[by_upper[name]]
    return None


def leaf_segment_mask(rows: Rows) -> pd.Series:
    """Boolean Series (positional for a list of dicts), True for leaf segments.

    In-memory twin of leaf_analysis_sql(): siblings are looked up within `rows`
    only, so it fits a run's own results or the rows a page is showing. Without
    an ANALYSIS_TIMESTAMP column all rows count as analysed together (child rows
    win). Rows without owner/object columns cannot be grouped and all count."""
    df = rows if isinstance(rows, pd.DataFrame) else pd.DataFrame(list(rows or []))
    if df.empty:
        return pd.Series(True, index=df.index, dtype=bool)

    db, owner, name = (_column(df, *names) for names in _KEY_COLUMNS)
    if owner is None or name is None:  # nothing to find siblings with
        return pd.Series(True, index=df.index, dtype=bool)

    def values(column):
        col = _column(df, column)
        return [v if _present(v) else None for v in ([None] * len(df) if col is None else col)]

    parts = values('PARTITION_NAME')
    subs = [s is not None for s in values('SUBPARTITION_NAME')]
    stamps = values('ANALYSIS_TIMESTAMP')
    objects = list(zip(*[k for k in (db, owner, name) if k is not None]))

    def newest(current, ts):
        return ts if current is None or (ts is not None and ts > current) else current

    table_ts, child_ts, has_children, partitions_with_subs = {}, {}, set(), set()
    for o, p, s, ts in zip(objects, parts, subs, stamps):
        if p is None:
            table_ts[o] = newest(table_ts.get(o), ts)
            continue
        has_children.add(o)
        child_ts[o] = newest(child_ts.get(o), ts)
        if s:
            partitions_with_subs.add((o, p))

    def table_level(o):
        if o not in has_children:
            return True
        t, c = table_ts.get(o), child_ts.get(o)
        return t is not None and c is not None and t > c

    mask = [table_level(o) if p is None
            else not table_level(o) and (s or (o, p) not in partitions_with_subs)
            for o, p, s in zip(objects, parts, subs)]
    return pd.Series(mask, index=df.index, dtype=bool)


def leaf_segments(rows: Rows) -> Rows:
    """The leaf-segment rows of `rows`, as the same kind (DataFrame or list)."""
    mask = leaf_segment_mask(rows)
    if isinstance(rows, pd.DataFrame):
        return rows[mask]
    return [r for r, keep in zip(list(rows or []), mask) if keep]
