"""
Shared DDL builder for HCC Compression Advisor.

Produces the ALTER TABLE MOVE + dependent-index REBUILD script used by the
Scheduler export, the Quick Action export, and the Execution page's dry-run.
Kept framework-free (no Streamlit) so it's callable from any context.

Input DataFrame for `build_compression_script` / `gather_dependent_indexes`:
    database_id, database_display, database_name,
    owner, object_name, partition_name,
    compression_type_applied, parallel_degree,
    operation_status, error_message
"""

from datetime import datetime
from typing import Optional

import pandas as pd

from hcc_advisor.utils.target_connector import TargetConnector


def _sql_quote(value) -> str:
    """Wrap value in single quotes, escaping any embedded quotes."""
    return "'" + str(value).replace("'", "''") + "'"


def gather_dependent_indexes(df: pd.DataFrame) -> dict:
    """Query target databases for indexes on each affected table.

    Returns a dict keyed by (database_id, owner, object_name) with
        {'indexes': [{'owner', 'name', 'partitioned'}],
         'ind_partitions': {(idx_owner, idx_name): [part_name, ...]}}
    """
    df_cols = [c.lower() for c in df.columns]
    df.columns = df_cols

    # Group (owner, table) by database_id
    by_db: dict = {}
    for _, row in df.iterrows():
        did = int(row.get('database_id') or 0)
        if did == 0:
            continue
        key = (row['owner'], row['object_name'])
        by_db.setdefault(did, set()).add(key)

    result: dict = {}
    for did, objects in by_db.items():
        if not objects:
            continue
        owners = list({o for o, _ in objects})
        tables = list({t for _, t in objects})

        try:
            owners_csv = ",".join(_sql_quote(o) for o in owners)
            tables_csv = ",".join(_sql_quote(t) for t in tables)
            idx_query_inline = f"""
                SELECT i.owner as index_owner, i.index_name,
                       i.table_owner, i.table_name, i.partitioned
                FROM all_indexes i
                WHERE i.table_owner IN ({owners_csv})
                  AND i.table_name IN ({tables_csv})
                  AND i.index_type NOT IN ('LOB', 'IOT - TOP')
            """
            idx_df = TargetConnector.execute_query(did, idx_query_inline)
            if idx_df.empty:
                continue
            idx_df.columns = [c.lower() for c in idx_df.columns]

            # For partitioned indexes, also get partition names
            partitioned_idx = idx_df[idx_df['partitioned'] == 'YES']
            ind_partitions: dict = {}
            if not partitioned_idx.empty:
                ip_owners = ",".join(_sql_quote(o) for o in partitioned_idx['index_owner'].unique())
                ip_names = ",".join(_sql_quote(n) for n in partitioned_idx['index_name'].unique())
                ip_query = f"""
                    SELECT index_owner, index_name, partition_name
                    FROM all_ind_partitions
                    WHERE index_owner IN ({ip_owners}) AND index_name IN ({ip_names})
                """
                ip_df = TargetConnector.execute_query(did, ip_query)
                if not ip_df.empty:
                    ip_df.columns = [c.lower() for c in ip_df.columns]
                    for _, r in ip_df.iterrows():
                        k = (r['index_owner'], r['index_name'])
                        ind_partitions.setdefault(k, []).append(r['partition_name'])

            # Build result keyed by (db_id, table_owner, table_name)
            for _, r in idx_df.iterrows():
                k = (did, r['table_owner'], r['table_name'])
                entry = result.setdefault(k, {'indexes': [], 'ind_partitions': ind_partitions})
                entry['indexes'].append({
                    'owner': r['index_owner'],
                    'name': r['index_name'],
                    'partitioned': r['partitioned'],
                })
        except Exception:
            # Index discovery is best-effort; script generation continues without
            # the REBUILD block for the failing database.
            pass

    return result


_CLAUSE_MAP = {
    'OLTP': 'COMPRESS FOR OLTP',
    'QUERY LOW': 'COMPRESS FOR QUERY LOW',
    'QUERY HIGH': 'COMPRESS FOR QUERY HIGH',
    'ARCHIVE LOW': 'COMPRESS FOR ARCHIVE LOW',
    'ARCHIVE HIGH': 'COMPRESS FOR ARCHIVE HIGH',
    'BASIC': 'COMPRESS BASIC',
    'NONE': 'NOCOMPRESS',
}


def build_compression_script(
    df: pd.DataFrame,
    status_label: str,
    db_label: str,
    index_map: Optional[dict] = None,
) -> str:
    """Build a SQL script from the exported operations."""
    if index_map is None:
        index_map = {}

    lines = [
        "-- HCC Compression Advisor - Exported Operations",
        f"-- Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"-- Database Filter: {db_label}",
        f"-- Status Filter: {status_label}",
        f"-- Total Operations: {len(df)}",
        f"-- Index rebuild statements: {'INCLUDED' if index_map else 'NOT INCLUDED'}",
        "-- ",
        "-- Run these ALTER TABLE MOVE statements to apply the compression",
        "-- recommendations. Review before executing in production.",
        "-- ",
        "",
        "SET SERVEROUTPUT ON;",
        "SET TIMING ON;",
        "",
    ]

    current_db = None
    for _, row in df.iterrows():
        db_name = row.get('database_display') or row.get('database_name') or f"db_{row.get('database_id', '?')}"
        owner = row['owner']
        obj = row['object_name']
        part = row.get('partition_name')
        comp_type = row.get('compression_type_applied') or 'OLTP'
        dop = int(row.get('parallel_degree') or 4)
        status = row.get('operation_status', '')
        err = row.get('error_message', '')

        if db_name != current_db:
            lines.append("")
            lines.append("-- ==================================================")
            lines.append(f"-- Database: {db_name}")
            lines.append("-- ==================================================")
            current_db = db_name

        clause = _CLAUSE_MAP.get(str(comp_type).upper(), f'COMPRESS FOR {comp_type}')

        status_marker = f" [{status}]"
        if status == 'FAILED' and err:
            status_marker += f" -- error: {str(err)[:100]}"
        lines.append(f"-- {owner}.{obj}{'.' + part if part and str(part) != 'None' else ''}{status_marker}")

        is_partition_move = bool(part and str(part) != 'None')
        if is_partition_move:
            lines.append(f"ALTER TABLE {owner}.{obj} MOVE PARTITION {part} {clause} ONLINE PARALLEL {dop};")
        else:
            lines.append(f"ALTER TABLE {owner}.{obj} MOVE {clause} ONLINE PARALLEL {dop};")

        did = int(row.get('database_id') or 0)
        key = (did, owner, obj)
        entry = index_map.get(key)
        if entry and entry.get('indexes'):
            indexes = entry['indexes']
            ind_partitions = entry.get('ind_partitions', {})
            lines.append(f"-- Rebuild {len(indexes)} dependent index(es) for {owner}.{obj}")
            for idx in indexes:
                idx_owner = idx['owner']
                idx_name = idx['name']
                idx_full = f"{idx_owner}.{idx_name}"

                if is_partition_move:
                    if idx['partitioned'] == 'YES':
                        lines.append(f"ALTER INDEX {idx_full} REBUILD PARTITION {part} ONLINE PARALLEL {dop};")
                    else:
                        lines.append(f"ALTER INDEX {idx_full} REBUILD ONLINE PARALLEL {dop};")
                else:
                    if idx['partitioned'] == 'YES':
                        parts_list = ind_partitions.get((idx_owner, idx_name), [])
                        if parts_list:
                            for pn in parts_list:
                                lines.append(f"ALTER INDEX {idx_full} REBUILD PARTITION {pn} ONLINE PARALLEL {dop};")
                        else:
                            lines.append(f"-- WARNING: could not enumerate partitions for {idx_full}; rebuild manually")
                    else:
                        lines.append(f"ALTER INDEX {idx_full} REBUILD ONLINE PARALLEL {dop};")
        else:
            lines.append(f"-- No dependent indexes found for {owner}.{obj} (or index info unavailable)")
        lines.append("")

    lines.append("")
    lines.append("-- End of generated script")
    return "\n".join(lines)
