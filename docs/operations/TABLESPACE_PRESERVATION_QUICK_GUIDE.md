# Tablespace Preservation - Quick Reference Guide

## What Changed?

All compression operations in `PKG_COMPRESSION_EXECUTOR` now preserve original tablespace assignments.

## Modified Functions

### 1. `compress_table`
**Before:** `ALTER TABLE t MOVE COMPRESS FOR OLTP`
**After:** `ALTER TABLE t MOVE COMPRESS FOR OLTP TABLESPACE original_ts`

```sql
EXEC PKG_COMPRESSION_EXECUTOR.compress_table('HR', 'EMPLOYEES', 'OLTP');
-- Result: Table compressed in same tablespace as before
```

### 2. `rebuild_table_indexes` (Internal)
**Before:** `ALTER INDEX i REBUILD`
**After:** `ALTER INDEX i REBUILD TABLESPACE original_ts`

Automatically called by `compress_table` - indexes preserve their tablespaces.

### 3. `compress_partition` (NEW)
Compress single partition preserving its tablespace.

```sql
EXEC PKG_COMPRESSION_EXECUTOR.compress_partition('SALES', 'ORDERS', 'P_2024_Q1', 'OLTP');
-- Result: Partition stays in original tablespace
```

### 4. `compress_all_partitions` (NEW)
Compress all partitions, each preserving its own tablespace.

```sql
EXEC PKG_COMPRESSION_EXECUTOR.compress_all_partitions('SALES', 'ORDERS', 'OLTP');
-- Result: Each partition stays in its original tablespace
```

### 5. `compress_lob` (NEW)
Compress LOB segments preserving LOB tablespace.

```sql
EXEC PKG_COMPRESSION_EXECUTOR.compress_lob('HR', 'DOCUMENTS', 'RESUME_TEXT', 'HIGH');
-- Result: LOB stays in original LOB tablespace
```

## Implementation Details

### Tables
- Queries `DBA_TABLES.tablespace_name`
- Adds `TABLESPACE` clause to `MOVE` statement
- Logs preservation action

### Partitions
- Queries `DBA_TAB_PARTITIONS.tablespace_name`
- Each partition handled individually
- Partition indexes also preserved

### Indexes
- Queries `DBA_INDEXES.tablespace_name`
- Added to all `REBUILD` statements
- Applies to regular and partition indexes

### LOBs
- Queries `DBA_LOBS.tablespace_name`
- Uses `MODIFY LOB` with tablespace clause
- LOBs can be in different tablespace than base table

## Verification

```sql
-- Before compression
SELECT tablespace_name FROM user_tables WHERE table_name = 'EMPLOYEES';
-- Result: TS_DATA

-- Run compression
EXEC PKG_COMPRESSION_EXECUTOR.compress_table(USER, 'EMPLOYEES', 'OLTP');

-- After compression
SELECT tablespace_name FROM user_tables WHERE table_name = 'EMPLOYEES';
-- Result: TS_DATA (same as before!)
```

## Testing

Run comprehensive test suite:
```bash
sqlplus user/pass@db @tests/test_tablespace_preservation.sql
```

Tests verify:
1. Regular table preservation
2. Index preservation
3. Partition preservation (individual)
4. LOB preservation
5. Batch partition preservation

## Log Output Example

```
[INFO] Current tablespace: TS_DATA
[INFO] Preserving tablespace: TS_DATA
[INFO] DDL: ALTER TABLE HR.EMPLOYEES MOVE COMPRESS FOR OLTP TABLESPACE TS_DATA ONLINE
[INFO] Preserving index tablespace: TS_INDEX for IDX_EMP_NAME
```

## Key Points

1. **No Breaking Changes:** All existing procedure signatures unchanged
2. **Automatic:** Tablespace preservation happens automatically
3. **Logged:** All preservation actions are logged
4. **Tested:** Comprehensive test suite included
5. **Safe:** No unintended data movement

## Files Modified

- `/home/claude/Oracle-Database-Related/HCC-CompAdvisor/sql/04_executor_pkg.sql` - Main implementation
- `/home/claude/Oracle-Database-Related/HCC-CompAdvisor/tests/test_tablespace_preservation.sql` - Test suite
- `/home/claude/Oracle-Database-Related/HCC-CompAdvisor/docs/tablespace_preservation.md` - Full documentation

## Quick Syntax Reference

```sql
-- Regular table
PKG_COMPRESSION_EXECUTOR.compress_table(owner, table_name, compression_type, online, dry_run);

-- Single partition
PKG_COMPRESSION_EXECUTOR.compress_partition(owner, table_name, partition_name, compression_type, online);

-- All partitions
PKG_COMPRESSION_EXECUTOR.compress_all_partitions(owner, table_name, compression_type, online);

-- LOB column
PKG_COMPRESSION_EXECUTOR.compress_lob(owner, table_name, column_name, compression_type);

-- Index
PKG_COMPRESSION_EXECUTOR.compress_index(owner, index_name, compression_type, online);
```

## Compression Types

- **Tables/Partitions:** BASIC, OLTP, NOCOMPRESS
- **Indexes:** ADV_LOW, ADV_HIGH, NOCOMPRESS
- **LOBs:** HIGH, MEDIUM, LOW, NOCOMPRESS
