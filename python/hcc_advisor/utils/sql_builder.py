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

import re
from datetime import datetime
from typing import Optional

import pandas as pd

from hcc_advisor.utils.target_connector import TargetConnector


# SECURITY (CWE-89): identifiers (owner/table/partition/index) flow into generated
# ALTER TABLE/INDEX DDL by raw interpolation. Validate them as standard Oracle
# unquoted identifiers so a malicious object name cannot inject extra DDL into the
# exported script.
_IDENTIFIER_RE = re.compile(r'^[A-Za-z][A-Za-z0-9_$#]{0,127}$')


def _is_valid_identifier(value) -> bool:
    """Return True if value is a safe Oracle unquoted identifier.

    Uses fullmatch (not match): with re.match, the pattern's trailing ``$``
    also matches just before a single trailing newline, so ``"NAME\n"`` would
    slip through. fullmatch requires the entire string to match.
    """
    return isinstance(value, str) and bool(_IDENTIFIER_RE.fullmatch(value))


def _sql_quote(value) -> str:
    """Wrap value in single quotes, escaping any embedded quotes."""
    return "'" + str(value).replace("'", "''") + "'"


def chunk_list(values, size: int = 1000) -> list:
    """Split an iterable into lists of at most `size` items.

    Oracle limits an IN (...) list to 1000 expressions (ORA-01795). Any caller
    that interpolates an arbitrary-length identifier set into an IN-list must
    chunk it and union the per-chunk results.
    """
    values = list(values)
    return [values[i:i + size] for i in range(0, len(values), size)]


def _indexes_for_objects(did: int, owners: list, tables: list) -> pd.DataFrame:
    """Fetch indexes for (owners x tables) on a target, chunking each IN-list
    to stay under Oracle's 1000-expression limit. Returns a concatenated
    DataFrame with lowercase columns (empty if nothing matched)."""
    frames = []
    for o_chunk in chunk_list(owners):
        if not o_chunk:
            continue
        owners_csv = ",".join(_sql_quote(o) for o in o_chunk)
        for t_chunk in chunk_list(tables):
            if not t_chunk:
                continue
            tables_csv = ",".join(_sql_quote(t) for t in t_chunk)
            q = f"""
                SELECT i.owner as index_owner, i.index_name,
                       i.table_owner, i.table_name, i.partitioned
                FROM all_indexes i
                WHERE i.table_owner IN ({owners_csv})
                  AND i.table_name IN ({tables_csv})
                  AND i.index_type NOT IN ('LOB', 'IOT - TOP')
            """
            d = TargetConnector.execute_query(did, q)
            if not d.empty:
                frames.append(d)
    if not frames:
        return pd.DataFrame()
    out = pd.concat(frames, ignore_index=True)
    out.columns = [c.lower() for c in out.columns]
    return out


def _ind_partitions_for(did: int, ip_owners: list, ip_names: list) -> dict:
    """Map (index_owner, index_name) -> [partition_name, ...] for partitioned
    indexes, chunking both IN-lists (ORA-01795 safe)."""
    ind_partitions: dict = {}
    for o_chunk in chunk_list(ip_owners):
        if not o_chunk:
            continue
        oc = ",".join(_sql_quote(o) for o in o_chunk)
        for n_chunk in chunk_list(ip_names):
            if not n_chunk:
                continue
            nc = ",".join(_sql_quote(n) for n in n_chunk)
            q = f"""
                SELECT index_owner, index_name, partition_name
                FROM all_ind_partitions
                WHERE index_owner IN ({oc}) AND index_name IN ({nc})
            """
            ip_df = TargetConnector.execute_query(did, q)
            if ip_df.empty:
                continue
            ip_df.columns = [c.lower() for c in ip_df.columns]
            for _, r in ip_df.iterrows():
                k = (r['index_owner'], r['index_name'])
                ind_partitions.setdefault(k, []).append(r['partition_name'])
    return ind_partitions


def gather_dependent_indexes(df: pd.DataFrame) -> dict:
    """Query target databases for indexes on each affected table.

    Returns a dict keyed by (database_id, owner, object_name) with
        {'indexes': [{'owner', 'name', 'partitioned'}],
         'ind_partitions': {(idx_owner, idx_name): [part_name, ...]}}

    IN-lists are chunked (see chunk_list) so exporting a plan with more than
    1000 distinct tables/indexes no longer hits ORA-01795.
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
            idx_df = _indexes_for_objects(did, owners, tables)
            if idx_df.empty:
                continue

            # For partitioned indexes, also get partition names
            partitioned_idx = idx_df[idx_df['partitioned'] == 'YES']
            ind_partitions: dict = {}
            if not partitioned_idx.empty:
                ind_partitions = _ind_partitions_for(
                    did,
                    list(partitioned_idx['index_owner'].unique()),
                    list(partitioned_idx['index_name'].unique()),
                )

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

        # SECURITY (CWE-89): refuse to emit DDL for identifiers / compression
        # types that are not safe — comment them out instead of interpolating.
        part_present = bool(part and str(part) != 'None')
        if not _is_valid_identifier(owner) or not _is_valid_identifier(obj) or \
                (part_present and not _is_valid_identifier(part)):
            lines.append(f"-- SKIPPED (invalid identifier): {owner}.{obj}"
                         f"{('.' + str(part)) if part_present else ''}")
            lines.append("")
            continue
        clause = _CLAUSE_MAP.get(str(comp_type).upper())
        if clause is None:
            lines.append(f"-- SKIPPED (unsupported compression type {comp_type!r}): {owner}.{obj}")
            lines.append("")
            continue
        dop = min(max(int(dop), 1), 128)

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
                # SECURITY (CWE-89): validate index identifiers before interpolating.
                if not _is_valid_identifier(idx_owner) or not _is_valid_identifier(idx_name):
                    lines.append(f"-- SKIPPED index rebuild (invalid identifier): {idx_owner}.{idx_name}")
                    continue
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
                                if not _is_valid_identifier(pn):
                                    lines.append(f"-- SKIPPED partition rebuild (invalid identifier): {idx_full}.{pn}")
                                    continue
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


# Canonical, re-importable column order for the CSV manifest. The Scheduler's
# CSV import reads `owner`, `object_name`, `partition_name`, `compression_type`
# and `parallel_degree`; the rest is informational provenance.
MANIFEST_COLUMNS = [
    'database_id', 'database_name', 'owner', 'object_name', 'object_type',
    'partition_name', 'subpartition_name', 'compression_type',
    'parallel_degree', 'operation_status',
]


def build_compression_manifest(df: pd.DataFrame) -> pd.DataFrame:
    """Build a portable CSV manifest of compression operations.

    Unlike the SQL script (which targets the source database), the manifest
    carries only object identity + intended compression so it can be imported
    into a *different* target database, where the importer re-verifies each
    object's existence and current compression state.
    """
    src = df.copy()
    src.columns = [c.lower() for c in src.columns]
    out = pd.DataFrame(index=src.index)
    out['database_id'] = src.get('database_id')
    out['database_name'] = src.get('database_display', src.get('database_name'))
    out['owner'] = src.get('owner')
    out['object_name'] = src.get('object_name')
    out['object_type'] = src.get('object_type')
    out['partition_name'] = src.get('partition_name')
    out['subpartition_name'] = src.get('subpartition_name')
    out['compression_type'] = src.get('compression_type_applied')
    out['parallel_degree'] = src.get('parallel_degree')
    out['operation_status'] = src.get('operation_status')
    return out[MANIFEST_COLUMNS]
