"""
One-time Migration Utility for HCC Compression Advisor
Imports existing analysis data from a target Oracle DB into the centralized
architecture. Registers the target DB in T_TARGET_DATABASES and copies rows
from the five analysis/history tables, injecting the new DATABASE_ID.

Usage:
    python -m utils.migration \
        --host TARGET_HOST --port 1521 --service FREEPDB1 \
        --username USER --password PASS --name "My Database"
"""

import argparse
import sys
import os
import oracledb
from datetime import datetime
from typing import Dict, Any, List, Optional, Tuple

from hcc_advisor.config import config
from cryptography.fernet import Fernet

BATCH_SIZE = 500

# Ordered list: T_ADVISOR_RUN first (FK parent), then children.
MIGRATION_ORDER = [
    "T_ADVISOR_RUN", "T_COMPRESSION_ANALYSIS", "T_COMPRESSION_HISTORY",
    "T_INDEX_COMPRESSION_ANALYSIS", "T_LOB_COMPRESSION_ANALYSIS",
]

# Source columns per table (non-virtual only). Central INSERT prepends DATABASE_ID.
TABLE_CONFIGS: Dict[str, Dict[str, Any]] = {
    "T_ADVISOR_RUN": {"pk": "RUN_ID", "columns": [
        "RUN_ID", "RUN_NAME", "RUN_TYPE", "RUN_DESCRIPTION",
        "SCHEMA_FILTER", "OBJECT_TYPE_FILTER", "OBJECT_NAME_PATTERN",
        "INCLUDE_PARTITIONS", "STRATEGY_ID", "STRATEGY_NAME",
        "SAMPLE_SIZE", "PARALLEL_DEGREE", "ANALYSIS_MODE",
        "START_TIME", "END_TIME", "DURATION_MINUTES",
        "RUN_STATUS", "ERROR_MESSAGE",
        "OBJECTS_ANALYZED", "OBJECTS_SUCCEEDED", "OBJECTS_FAILED",
        "TOTAL_SIZE_MB", "COMPRESSIBLE_SIZE_MB",
        "PROJECTED_SAVINGS_MB", "PROJECTED_SAVINGS_PCT",
        "RECOMMEND_NONE", "RECOMMEND_BASIC", "RECOMMEND_OLTP",
        "RECOMMEND_ADV_LOW", "RECOMMEND_ADV_HIGH",
        "CPU_TIME_SECONDS", "ELAPSED_TIME_SECONDS", "TEMP_SPACE_MB",
        "INITIATED_BY", "INITIATED_FROM"]},
    "T_COMPRESSION_ANALYSIS": {"pk": "ANALYSIS_ID", "columns": [
        "ANALYSIS_ID", "OWNER", "OBJECT_NAME", "OBJECT_TYPE",
        "PARTITION_NAME", "SUBPARTITION_NAME",
        "SIZE_BYTES", "ROW_COUNT", "BLOCK_COUNT", "AVG_ROW_LENGTH",
        "BASIC_RATIO", "OLTP_RATIO", "ADV_LOW_RATIO", "ADV_HIGH_RATIO",
        "BLKCNT_UNCMP_BASIC", "BLKCNT_CMP_BASIC",
        "BLKCNT_UNCMP_OLTP", "BLKCNT_CMP_OLTP",
        "BLKCNT_UNCMP_ADV_LOW", "BLKCNT_CMP_ADV_LOW",
        "BLKCNT_UNCMP_ADV_HIGH", "BLKCNT_CMP_ADV_HIGH",
        "INSERT_COUNT", "UPDATE_COUNT", "DELETE_COUNT",
        "LOGICAL_READS", "PHYSICAL_READS", "ACCESS_FREQUENCY", "LAST_ACCESS_DATE",
        "HOTNESS_SCORE", "READ_RATIO", "WRITE_RATIO", "DML_24H_RATE",
        "LAST_ANALYZED", "DATA_AGE_DAYS",
        "CURRENT_COMPRESSION", "ADVISABLE_COMPRESSION",
        "RECOMMENDATION_REASON", "CONFIDENCE_SCORE",
        "PROJECTED_SAVINGS_BYTES", "PROJECTED_SAVINGS_PCT",
        "ADVISOR_RUN_ID", "ANALYSIS_DATE", "ANALYSIS_TIMESTAMP",
        "ANALYSIS_DURATION_SEC", "SAMPLE_SIZE_ROWS"]},
    "T_COMPRESSION_HISTORY": {"pk": "HISTORY_ID", "columns": [
        "HISTORY_ID", "EXECUTION_ID",
        "OWNER", "OBJECT_NAME", "OBJECT_TYPE", "PARTITION_NAME", "SUBPARTITION_NAME",
        "COMPRESSION_TYPE_APPLIED", "COMPRESSION_CLAUSE",
        "EXECUTION_MODE", "PARALLEL_DEGREE",
        "ORIGINAL_SIZE_BYTES", "ORIGINAL_BLOCKS", "ORIGINAL_ROW_COUNT",
        "COMPRESSED_SIZE_BYTES", "COMPRESSED_BLOCKS", "COMPRESSED_ROW_COUNT",
        "COMPRESSION_RATIO_ACHIEVED", "PREDICTED_RATIO",
        "START_TIME", "END_TIME", "DURATION_SECONDS",
        "OPERATION_STATUS", "ERROR_CODE", "ERROR_MESSAGE", "ERROR_BACKTRACE",
        "CPU_TIME_SECONDS", "IO_WAIT_SECONDS", "TEMP_SPACE_MB", "UNDO_SPACE_MB",
        "INDEXES_REBUILT_COUNT", "INDEX_REBUILD_TIME_SEC", "INDEX_REBUILD_STATUS",
        "VALIDATION_STATUS", "DATA_INTEGRITY_CHECK", "CHECKSUM_BEFORE", "CHECKSUM_AFTER",
        "ANALYSIS_ID", "EXECUTED_BY", "EXECUTED_FROM_IP", "EXECUTED_FROM_PROGRAM",
        "ROLLBACK_POSSIBLE", "ROLLBACK_STATUS", "ORIGINAL_DDL"]},
    "T_INDEX_COMPRESSION_ANALYSIS": {"pk": "INDEX_ANALYSIS_ID", "columns": [
        "INDEX_ANALYSIS_ID",
        "INDEX_OWNER", "INDEX_NAME", "TABLE_OWNER", "TABLE_NAME",
        "INDEX_TYPE", "UNIQUENESS", "PARTITION_NAME", "SUBPARTITION_NAME",
        "INDEX_SIZE_BYTES", "LEAF_BLOCKS", "DISTINCT_KEYS", "CLUSTERING_FACTOR",
        "PREFIX_COMPRESSION_RATIO", "ADVANCED_LOW_RATIO", "ADVANCED_HIGH_RATIO",
        "BLKCNT_UNCMP_PREFIX", "BLKCNT_CMP_PREFIX",
        "BLKCNT_UNCMP_ADV_LOW", "BLKCNT_CMP_ADV_LOW",
        "BLKCNT_UNCMP_ADV_HIGH", "BLKCNT_CMP_ADV_HIGH",
        "CURRENT_COMPRESSION", "CURRENT_PREFIX_LENGTH",
        "SCAN_COUNT", "LOOKUP_COUNT", "ACCESS_FREQUENCY",
        "ADVISABLE_COMPRESSION", "RECOMMENDED_PREFIX_LENGTH",
        "RECOMMENDATION_REASON", "PROJECTED_SAVINGS_MB",
        "ADVISOR_RUN_ID", "ANALYSIS_DATE", "ANALYSIS_TIMESTAMP"]},
    "T_LOB_COMPRESSION_ANALYSIS": {"pk": "LOB_ANALYSIS_ID", "columns": [
        "LOB_ANALYSIS_ID",
        "TABLE_OWNER", "TABLE_NAME", "COLUMN_NAME",
        "LOB_NAME", "DATA_TYPE", "SECUREFILE", "PARTITION_NAME", "SUBPARTITION_NAME",
        "LOB_SIZE_BYTES", "NUM_LOBS", "AVG_LOB_SIZE_KB",
        "CURRENT_COMPRESSION", "CURRENT_DEDUPLICATION", "CURRENT_ENCRYPTION", "CHUNK_SIZE",
        "LOW_COMPRESSION_RATIO", "MEDIUM_COMPRESSION_RATIO",
        "HIGH_COMPRESSION_RATIO", "DEDUP_SAVINGS_PCT",
        "BLKCNT_UNCMP_LOW", "BLKCNT_CMP_LOW",
        "BLKCNT_UNCMP_MEDIUM", "BLKCNT_CMP_MEDIUM",
        "BLKCNT_UNCMP_HIGH", "BLKCNT_CMP_HIGH",
        "READ_FREQUENCY", "WRITE_FREQUENCY", "READ_WRITE_RATIO",
        "ADVISABLE_COMPRESSION", "ADVISABLE_DEDUP",
        "RECOMMENDATION_REASON", "PROJECTED_SAVINGS_MB", "RECOMMEND_SECUREFILE",
        "ADVISOR_RUN_ID", "ANALYSIS_DATE", "ANALYSIS_TIMESTAMP"]},
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def encrypt_password(password: str) -> str:
    """Encrypt a password for storage in T_TARGET_DATABASES."""
    key = config.ENCRYPTION_KEY
    if key:
        f = Fernet(key.encode() if isinstance(key, str) else key)
        return f.encrypt(password.encode()).decode()
    return password


def get_central_connection() -> oracledb.Connection:
    """Open a standalone connection to the central database."""
    dsn = f"{config.CENTRAL_DB_HOST}:{config.CENTRAL_DB_PORT}/{config.CENTRAL_DB_SERVICE}"
    return oracledb.connect(
        user=config.CENTRAL_DB_USER, password=config.CENTRAL_DB_PASSWORD, dsn=dsn,
    )


def get_target_connection(args: argparse.Namespace) -> oracledb.Connection:
    """Open a standalone connection to the target database."""
    dsn = f"{args.host}:{args.port}/{args.service}"
    return oracledb.connect(user=args.username, password=args.password, dsn=dsn)


def test_connection(conn: oracledb.Connection, label: str) -> bool:
    """Verify a connection is alive."""
    try:
        cur = conn.cursor()
        cur.execute("SELECT 1 FROM DUAL")
        cur.fetchone()
        cur.close()
        print(f"  [OK] {label} connection verified")
        return True
    except oracledb.Error as exc:
        print(f"  [FAIL] {label} connection failed: {exc}")
        return False


def table_exists(conn: oracledb.Connection, table_name: str) -> bool:
    """Check whether a table exists in the connected schema."""
    cur = conn.cursor()
    cur.execute(
        "SELECT COUNT(*) FROM user_tables WHERE table_name = :t",
        {"t": table_name.upper()},
    )
    cnt = cur.fetchone()[0]
    cur.close()
    return cnt > 0


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

def register_target_database(
    central: oracledb.Connection, args: argparse.Namespace, dry_run: bool,
) -> Optional[int]:
    """Insert a row into T_TARGET_DATABASES and return the new DATABASE_ID."""
    db_name = args.name.replace(" ", "_").upper()
    enc_pwd = encrypt_password(args.password)

    if dry_run:
        print(f"  [DRY-RUN] Would register '{db_name}' -> {args.host}:{args.port}/{args.service}")
        return -1

    insert_sql = """
        INSERT INTO t_target_databases (
            database_name, display_name, db_host, port, service_name,
            username, password_encrypted, description, environment,
            platform_type, is_active, created_date, created_by
        ) VALUES (
            :database_name, :display_name, :db_host, :port, :service_name,
            :username, :password_encrypted, :description, :environment,
            :platform_type, 'Y', SYSDATE, USER
        )
    """
    params = {
        "database_name": db_name, "display_name": args.name,
        "db_host": args.host, "port": args.port, "service_name": args.service,
        "username": args.username, "password_encrypted": enc_pwd,
        "description": args.description or f"Migrated from {args.host}:{args.port}/{args.service}",
        "environment": args.environment, "platform_type": args.platform,
    }
    cur = central.cursor()
    cur.execute(insert_sql, params)
    cur.execute(
        "SELECT database_id FROM t_target_databases WHERE database_name = :n",
        {"n": db_name},
    )
    row = cur.fetchone()
    cur.close()
    if row is None:
        raise RuntimeError("Failed to retrieve DATABASE_ID after registration")
    return int(row[0])


# ---------------------------------------------------------------------------
# Table migration
# ---------------------------------------------------------------------------

def migrate_table(
    target: oracledb.Connection, central: oracledb.Connection,
    table_name: str, database_id: int, dry_run: bool,
) -> int:
    """Copy rows from a source table into the central DB with DATABASE_ID."""
    cfg = TABLE_CONFIGS[table_name]
    columns = cfg["columns"]

    if not table_exists(target, table_name):
        print(f"  [SKIP] {table_name} does not exist in target database")
        return 0

    # Read all rows from source
    select_sql = f"SELECT {', '.join(columns)} FROM {table_name} ORDER BY {cfg['pk']}"
    cur = target.cursor()
    cur.execute(select_sql)
    rows = cur.fetchall()
    cur.close()
    row_count = len(rows)

    if row_count == 0:
        print(f"  [SKIP] {table_name}: 0 rows in source")
        return 0
    if dry_run:
        print(f"  [DRY-RUN] {table_name}: would migrate {row_count} rows")
        return row_count

    # Build INSERT with DATABASE_ID prepended
    central_cols = ["DATABASE_ID"] + columns
    bind_vars = [":b_database_id"] + [f":b_{c.lower()}" for c in columns]
    insert_sql = (
        f"INSERT INTO {table_name} ({', '.join(central_cols)}) "
        f"VALUES ({', '.join(bind_vars)})"
    )

    cur = central.cursor()
    batch: List[Dict[str, Any]] = []
    for row in rows:
        params: Dict[str, Any] = {"b_database_id": database_id}
        for idx, col in enumerate(columns):
            params[f"b_{col.lower()}"] = row[idx]
        batch.append(params)
        if len(batch) >= BATCH_SIZE:
            cur.executemany(insert_sql, batch)
            batch.clear()
    if batch:
        cur.executemany(insert_sql, batch)
    cur.close()
    print(f"  [OK] {table_name}: {row_count} rows migrated")
    return row_count


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Migrate analysis data from a target Oracle DB into the "
                    "centralized HCC Compression Advisor database.",
    )
    p.add_argument("--host", required=True, help="Target DB host")
    p.add_argument("--port", type=int, default=1521, help="Target DB port")
    p.add_argument("--service", required=True, help="Target DB service name")
    p.add_argument("--username", required=True, help="Target DB username")
    p.add_argument("--password", required=True, help="Target DB password")
    p.add_argument("--name", required=True, help="Display name for the target database")
    p.add_argument("--description", default=None, help="Optional description")
    p.add_argument("--environment", default="PRODUCTION",
                   choices=["PRODUCTION", "DEV", "TEST", "UAT", "STAGING"],
                   help="Environment label (default: PRODUCTION)")
    p.add_argument("--platform", default="STANDARD",
                   choices=["STANDARD", "EXADATA"],
                   help="Platform type (default: STANDARD)")
    p.add_argument("--dry-run", action="store_true",
                   help="Simulate without writing data")
    return p


def main() -> int:
    args = build_parser().parse_args()
    print("=" * 70)
    print("HCC Compression Advisor - Data Migration Utility")
    print("=" * 70)
    started_at = datetime.now()

    # 1. Connect to both databases
    print("\n[1/4] Establishing connections...")
    try:
        central = get_central_connection()
    except oracledb.Error as exc:
        print(f"  [FATAL] Cannot connect to central DB: {exc}")
        return 1
    try:
        target = get_target_connection(args)
    except oracledb.Error as exc:
        central.close()
        print(f"  [FATAL] Cannot connect to target DB: {exc}")
        return 1
    if not test_connection(central, "Central DB") or not test_connection(target, "Target DB"):
        central.close()
        target.close()
        return 1

    # 2. Register the target database
    print("\n[2/4] Registering target database...")
    try:
        database_id = register_target_database(central, args, args.dry_run)
        print(f"  Database registered with ID: {database_id}")
    except Exception as exc:
        print(f"  [FATAL] Registration failed: {exc}")
        central.rollback()
        central.close()
        target.close()
        return 1

    # 3. Migrate tables
    print("\n[3/4] Migrating data...")
    summary: Dict[str, int] = {}
    try:
        for tbl in MIGRATION_ORDER:
            summary[tbl] = migrate_table(target, central, tbl, database_id, args.dry_run)
        if not args.dry_run:
            central.commit()
            print("\n  Transaction committed.")
        else:
            print("\n  [DRY-RUN] No data was written.")
    except Exception as exc:
        print(f"\n  [ERROR] Migration failed: {exc}")
        if not args.dry_run:
            print("  Rolling back all changes...")
            central.rollback()
        central.close()
        target.close()
        return 1

    # 4. Summary
    elapsed = (datetime.now() - started_at).total_seconds()
    total_rows = sum(summary.values())
    print("\n[4/4] Migration Summary")
    print("-" * 50)
    for tbl in MIGRATION_ORDER:
        print(f"  {tbl:<40s} {summary.get(tbl, 0):>6d} rows")
    print("-" * 50)
    print(f"  {'TOTAL':<40s} {total_rows:>6d} rows")
    print(f"  Database ID: {database_id}")
    print(f"  Elapsed: {elapsed:.1f}s")
    if args.dry_run:
        print("  Mode: DRY-RUN (no data written)")
    print("=" * 70)
    central.close()
    target.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
